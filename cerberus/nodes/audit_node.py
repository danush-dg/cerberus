from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from cerberus.state import CerberusState
from cerberus.tools.chroma_client import upsert_resource_record

logger = logging.getLogger(__name__)


class AuditEntry(BaseModel):
    timestamp: str
    resource_id: str | None
    action_type: str
    llm_reasoning: str | None
    actor: Literal["human", "agent"]
    outcome: Literal["SUCCESS", "FAILED", "REJECTED", "SKIPPED_GUARDRAIL", "DRY_RUN", "NODE_ERROR"]
    run_id: str
    session_mutation_count: int
    project_id: str


def write_audit_entry(entry: AuditEntry, log_dir: str, run_id: str) -> None:
    log_path = os.path.join(log_dir, f"audit_{run_id}.jsonl")
    os.makedirs(log_dir, exist_ok=True)
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(entry.model_dump_json() + "\n")
            fh.flush()
    except IOError:
        logger.error("Failed to write audit entry to %s", log_path, exc_info=True)
        raise


def audit_node(state: CerberusState) -> CerberusState:
    run_id = state["run_id"]
    project_id = state["project_id"]
    mutation_count = state.get("mutation_count", 0)
    log_dir = os.environ.get("AUDIT_LOG_DIR", "./logs")
    log_path = os.path.join(log_dir, f"audit_{run_id}.jsonl")

    resources_with_outcome = [r for r in state.get("resources", []) if r.get("outcome") is not None]

    # STEP 1: Write JSONL for each resource with an outcome. Raise on IOError.
    for resource in resources_with_outcome:
        outcome = resource["outcome"]
        # Coerce to a valid AuditEntry outcome literal; fallback to NODE_ERROR
        valid_outcomes = {"SUCCESS", "FAILED", "REJECTED", "SKIPPED_GUARDRAIL", "DRY_RUN", "NODE_ERROR"}
        if outcome not in valid_outcomes:
            outcome = "NODE_ERROR"

        entry = AuditEntry(
            timestamp=datetime.utcnow().isoformat(),
            resource_id=resource["resource_id"],
            action_type=resource.get("decision") or "UNKNOWN",
            llm_reasoning=resource.get("reasoning"),
            actor="agent",
            outcome=outcome,  # type: ignore[arg-type]
            run_id=run_id,
            session_mutation_count=mutation_count,
            project_id=project_id,
        )
        write_audit_entry(entry, log_dir, run_id)

    # STEP 2: Write ChromaDB for each resource with an outcome. Log WARNING on failure; do not raise.
    for resource in resources_with_outcome:
        try:
            upsert_resource_record(resource, run_id, project_id)
        except Exception as exc:
            logger.warning(
                "ChromaDB write failed for resource %s: %s",
                resource.get("resource_id", "unknown"),
                exc,
            )

    # STEP 3: Write COST_SUMMARY JSONL entry.
    resources_scanned = len(state.get("resources", []))
    total_waste_identified = sum(
        (r.get("estimated_monthly_cost") or 0.0) for r in state.get("resources", [])
        if r.get("decision") in ("safe_to_stop", "safe_to_delete")
    )
    actions_approved = len(state.get("approved_actions", []))
    actions_executed = sum(
        1 for r in resources_with_outcome if r.get("outcome") in ("SUCCESS", "FAILED")
    )
    estimated_monthly_savings_recovered = sum(
        (r.get("estimated_monthly_savings") or 0.0)
        for r in resources_with_outcome
        if r.get("outcome") == "SUCCESS"
    )

    summary_payload = json.dumps({
        "resources_scanned": resources_scanned,
        "total_waste_identified": total_waste_identified,
        "actions_approved": actions_approved,
        "actions_executed": actions_executed,
        "estimated_monthly_savings_recovered": estimated_monthly_savings_recovered,
    })

    cost_summary_entry = AuditEntry(
        timestamp=datetime.utcnow().isoformat(),
        resource_id=None,
        action_type="COST_SUMMARY",
        llm_reasoning=summary_payload,
        actor="agent",
        outcome="SUCCESS",
        run_id=run_id,
        session_mutation_count=mutation_count,
        project_id=project_id,
    )
    write_audit_entry(cost_summary_entry, log_dir, run_id)

    # STEP 4: Persist COST_SUMMARY into state for the /summary endpoint (INV-AUD-02).
    state["cost_summary"] = {
        "resources_scanned": resources_scanned,
        "total_waste_identified": total_waste_identified,
        "actions_approved": actions_approved,
        "actions_executed": actions_executed,
        "estimated_monthly_savings_recovered": estimated_monthly_savings_recovered,
    }

    # STEP 6: Set audit_log_path in state.
    state["audit_log_path"] = log_path

    # STEP 7: Attempt LangSmith trace URL retrieval.
    try:
        from langsmith import Client as LangSmithClient  # type: ignore[import]
        ls_client = LangSmithClient()
        runs = list(ls_client.list_runs(project_name=os.environ.get("LANGSMITH_PROJECT", "cerberus"), limit=1))
        if runs:
            state["langsmith_trace_url"] = f"https://smith.langchain.com/o/default/projects/p/{runs[0].id}"
        else:
            state["langsmith_trace_url"] = None
            logger.warning("LangSmith unavailable — local JSONL is the authoritative record.")
    except Exception:
        state["langsmith_trace_url"] = None
        logger.warning("LangSmith unavailable — local JSONL is the authoritative record.")

    # STEP 8: Mark run complete.
    state["run_complete"] = True

    # STEP 9: Return state.
    return state
