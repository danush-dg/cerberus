from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, List

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings

if TYPE_CHECKING:
    from cerberus.state import ResourceRecord

logger = logging.getLogger(__name__)

COLLECTION_NAME = "resource_history"
IAM_COLLECTION_NAME = "iam_history"

_client: chromadb.PersistentClient | None = None
_collection: chromadb.Collection | None = None
_iam_collection: chromadb.Collection | None = None


class _LocalEmbedding(EmbeddingFunction):
    """Deterministic local embedding — no network, no model download.
    Used because chromadb 1.x downloads a model on first upsert.
    All queries in this project use metadata filters, not semantic similarity,
    so embedding quality is irrelevant."""

    def __init__(self) -> None:
        pass

    def name(self) -> str:
        return "cerberus-local-hash"

    def __call__(self, input: Documents) -> Embeddings:
        result: Embeddings = []
        for text in input:
            digest = hashlib.sha256(text.encode()).digest()
            vec = [((b / 255.0) * 2 - 1) for b in digest[:64]]
            result.append(vec)
        return result


def get_chroma_collection(collection_name: str = COLLECTION_NAME) -> chromadb.Collection:
    global _client, _collection, _iam_collection
    
    if collection_name == COLLECTION_NAME and _collection is not None:
        return _collection
    if collection_name == IAM_COLLECTION_NAME and _iam_collection is not None:
        return _iam_collection

    persist_dir = os.environ.get("CHROMA_PERSIST_DIR", "./chroma_db")
    os.makedirs(persist_dir, exist_ok=True)
    
    if _client is None:
        _client = chromadb.PersistentClient(path=persist_dir)
        
    collection = _client.get_or_create_collection(
        collection_name,
        embedding_function=_LocalEmbedding(),
    )
    
    if collection_name == COLLECTION_NAME:
        _collection = collection
    else:
        _iam_collection = collection
        
    return collection


def upsert_resource_record(record: dict, run_id: str, project_id: str) -> None:
    try:
        collection = get_chroma_collection()
        document = (
            f"{record['resource_type']} {record['resource_id']} "
            f"owned by {record.get('owner_email', 'unknown')} in {record['region']}"
        )
        metadata = {
            "run_id": run_id,
            "resource_type": record["resource_type"],
            "ownership_status": record.get("ownership_status") or "unknown",
            "decision": record.get("decision") or "unknown",
            "outcome": record.get("outcome") or "unknown",
            "estimated_monthly_cost": float(record.get("estimated_monthly_cost") or 0.0),
            "estimated_monthly_savings": float(record.get("estimated_monthly_savings") or 0.0),
            "region": record["region"],
            "owner_email": record.get("owner_email") or "unknown",
            "scanned_at": datetime.utcnow().isoformat(),
            "project_id": project_id,
        }
        collection.upsert(
            documents=[document],
            metadatas=[metadata],
            ids=[record["resource_id"]],
        )
    except Exception as e:
        logger.warning("ChromaDB upsert failed for %s: %s", record.get("resource_id", "unknown"), e)


def query_resource_history(resource_id: str) -> dict | None:
    try:
        collection = get_chroma_collection()
        result = collection.get(ids=[resource_id])
        if result and result["metadatas"] and len(result["metadatas"]) > 0:
            return result["metadatas"][0]
        return None
    except Exception as e:
        logger.warning("ChromaDB query failed for resource_id=%s: %s", resource_id, e)
        return None


def query_project_history(project_id: str) -> list[dict]:
    """Return all resource records stored for *project_id* in ChromaDB."""
    try:
        collection = get_chroma_collection()
        result = collection.get(where={"project_id": {"$eq": project_id}})
        if result and result["metadatas"]:
            ids = result.get("ids") or []
            return [
                {**meta, "resource_id": doc_id}
                for meta, doc_id in zip(result["metadatas"], ids)
            ]
        return []
    except Exception as e:
        logger.warning(
            "ChromaDB query_project_history failed for project=%s: %s",
            project_id, e,
        )
        return []


def query_owner_history(owner_email: str, project_id: str) -> list[dict]:
    try:
        collection = get_chroma_collection()
        result = collection.get(
            where={"$and": [{"owner_email": {"$eq": owner_email}}, {"project_id": {"$eq": project_id}}]}
        )
        if result and result["metadatas"]:
            ids = result.get("ids") or []
            return [
                {**meta, "resource_id": doc_id}
                for meta, doc_id in zip(result["metadatas"], ids)
            ]
        return []
    except Exception as e:
        logger.warning(
            "ChromaDB query_owner_history failed for owner=%s project=%s: %s",
            owner_email, project_id, e,
        )
        return []
def upsert_iam_ticket(ticket_data: dict) -> None:
    """Store an IAM ticket in ChromaDB with all fields needed for full reconstruction."""
    try:
        collection = get_chroma_collection(IAM_COLLECTION_NAME)
        ticket_id = ticket_data["ticket_id"]

        document = (
            f"IAM Ticket {ticket_id} for {ticket_data['requester_email']} "
            f"role {ticket_data['role']} in {ticket_data['project_id']}"
        )

        permissions = ticket_data.get("permissions", [])
        metadata = {
            "ticket_id": ticket_id,
            "requester_email": ticket_data["requester_email"],
            "project_id": ticket_data["project_id"],
            "role": ticket_data["role"],
            "status": ticket_data["status"],
            "created_at": ticket_data["created_at"],
            "justification": ticket_data.get("justification", ""),
            # Full reconstruction fields
            "permissions": json.dumps(permissions if isinstance(permissions, list) else []),
            "raw_request": ticket_data.get("raw_request", ""),
            "synthesized_at": ticket_data.get("synthesized_at", ""),
            "reviewed_at": ticket_data.get("reviewed_at") or "",
            "reviewed_by": ticket_data.get("reviewed_by") or "",
        }

        collection.upsert(
            documents=[document],
            metadatas=[metadata],
            ids=[ticket_id],
        )
    except Exception as e:
        logger.warning("ChromaDB upsert_iam_ticket failed: %s", e)


def query_iam_history(project_id: str) -> list[dict]:
    """Return all IAM tickets stored for *project_id* in ChromaDB."""
    try:
        collection = get_chroma_collection(IAM_COLLECTION_NAME)
        result = collection.get(where={"project_id": {"$eq": project_id}})
        if result and result["metadatas"]:
            return result["metadatas"]
        return []
    except Exception as e:
        logger.warning("ChromaDB query_iam_history failed for project=%s: %s", project_id, e)
        return []


def query_all_iam_history() -> list[dict]:
    """Return all IAM tickets stored in ChromaDB (all projects)."""
    try:
        collection = get_chroma_collection(IAM_COLLECTION_NAME)
        result = collection.get()
        if result and result["metadatas"]:
            return result["metadatas"]
        return []
    except Exception as e:
        logger.warning("ChromaDB query_all_iam_history failed: %s", e)
        return []


def query_all_project_ids() -> list[str]:
    """Return all unique project_ids present in the resource_history collection."""
    try:
        collection = get_chroma_collection(COLLECTION_NAME)
        result = collection.get()
        if not result or not result["metadatas"]:
            return []
        seen: set[str] = set()
        for meta in result["metadatas"]:
            pid = meta.get("project_id")
            if pid:
                seen.add(pid)
        return sorted(seen)
    except Exception as e:
        logger.warning("ChromaDB query_all_project_ids failed: %s", e)
        return []
