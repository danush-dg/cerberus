from __future__ import annotations

import uuid
import logging
from typing import TypedDict

logger = logging.getLogger(__name__)

VALID_DECISIONS: frozenset = frozenset({"safe_to_stop", "safe_to_delete", "needs_review", "skip"})
VALID_OUTCOMES: frozenset = frozenset({"SUCCESS", "FAILED", "REJECTED", "SKIPPED_GUARDRAIL", "DRY_RUN"})


class ResourceRecord(TypedDict):
    resource_id: str
    resource_type: str
    region: str
    creation_timestamp: str
    last_activity_timestamp: str | None
    estimated_monthly_cost: float | None
    ownership_status: str | None
    owner_email: str | None
    owner_iam_active: bool | None
    flagged_for_review: bool
    decision: str | None
    reasoning: str | None
    estimated_monthly_savings: float | None
    outcome: str | None


class CerberusState(TypedDict):
    project_id: str
    run_id: str
    resources: list[ResourceRecord]
    expected_resource_count: int
    approved_actions: list[ResourceRecord]
    mutation_count: int
    error_message: str | None
    run_complete: bool
    audit_log_path: str | None
    dry_run: bool
    langsmith_trace_url: str | None
    cost_summary: dict | None


def validate_resource_record(record: dict) -> "ResourceRecord":
    required_non_none = ["resource_id", "resource_type", "region", "creation_timestamp"]
    missing = [f for f in required_non_none if f not in record or record[f] is None]
    if missing:
        raise ValueError(f"ResourceRecord missing required fields: {missing}")
    if "estimated_monthly_cost" not in record:
        logger.warning(
            "ResourceRecord for '%s' has no estimated_monthly_cost field",
            record.get("resource_id", "unknown"),
        )
    elif record.get("estimated_monthly_cost") is None:
        logger.warning(
            "ResourceRecord for '%s' has estimated_monthly_cost=None",
            record.get("resource_id", "unknown"),
        )
    return record  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Runtime event bus — nodes push granular trace events here; api.py drains them.
# All callers run inside the same asyncio event loop so no lock is needed.
# ---------------------------------------------------------------------------

_event_bus: dict[str, list] = {}


def init_event_bus(run_id: str) -> None:
    _event_bus[run_id] = []


def push_trace_event(run_id: str, event: dict) -> None:
    if run_id in _event_bus:
        _event_bus[run_id].append(event)


def drain_trace_events(run_id: str) -> list[dict]:
    events = list(_event_bus.get(run_id, []))
    if run_id in _event_bus:
        _event_bus[run_id] = []
    return events


def initialise_state(project_id: str, dry_run: bool = True) -> CerberusState:
    return CerberusState(
        project_id=project_id,
        run_id=str(uuid.uuid4()),
        resources=[],
        expected_resource_count=0,
        approved_actions=[],
        mutation_count=0,
        error_message=None,
        run_complete=False,
        audit_log_path=None,
        dry_run=dry_run,
        langsmith_trace_url=None,
        cost_summary=None,
    )
