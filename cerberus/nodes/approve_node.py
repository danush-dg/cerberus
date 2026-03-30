from __future__ import annotations

import logging

from langgraph.types import interrupt

from cerberus.state import CerberusState

logger = logging.getLogger(__name__)


def approve_node(state: CerberusState) -> CerberusState:
    """Pause for human approval using LangGraph interrupt.

    Builds a display-only payload (no credentials), suspends the graph,
    and resumes with the list of approved resource IDs.
    """
    approval_payload = [
        {
            "resource_id": r["resource_id"],
            "resource_type": r["resource_type"],
            "region": r["region"],
            "owner_email": r["owner_email"],
            "ownership_status": r["ownership_status"],
            "decision": r["decision"],
            "reasoning": r["reasoning"],
            "estimated_monthly_savings": r["estimated_monthly_savings"],
        }
        for r in state["resources"]
    ]

    logger.info(
        "approve_node: suspending for human approval — %d resource(s) in payload",
        len(approval_payload),
    )

    approved_ids: list[str] = interrupt(approval_payload)

    state["approved_actions"] = [
        r for r in state["resources"] if r["resource_id"] in approved_ids
    ]
    state["mutation_count"] = 0  # INV-EXE-03: session counter reset here

    logger.info(
        "approve_node: %d resource(s) approved out of %d",
        len(state["approved_actions"]),
        len(state["resources"]),
    )

    return state
