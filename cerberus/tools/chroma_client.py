from __future__ import annotations

import hashlib
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

_client: chromadb.PersistentClient | None = None
_collection: chromadb.Collection | None = None


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


def get_chroma_collection() -> chromadb.Collection:
    global _client, _collection
    if _collection is not None:
        return _collection
    persist_dir = os.environ.get("CHROMA_PERSIST_DIR", "./chroma_db")
    os.makedirs(persist_dir, exist_ok=True)
    _client = chromadb.PersistentClient(path=persist_dir)
    _collection = _client.get_or_create_collection(
        COLLECTION_NAME,
        embedding_function=_LocalEmbedding(),
    )
    return _collection


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


def query_owner_history(owner_email: str, project_id: str) -> list[dict]:
    try:
        collection = get_chroma_collection()
        result = collection.get(
            where={"$and": [{"owner_email": {"$eq": owner_email}}, {"project_id": {"$eq": project_id}}]}
        )
        if result and result["metadatas"]:
            return result["metadatas"]
        return []
    except Exception as e:
        logger.warning(
            "ChromaDB query_owner_history failed for owner=%s project=%s: %s",
            owner_email, project_id, e,
        )
        return []
