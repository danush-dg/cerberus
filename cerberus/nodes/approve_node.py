from __future__ import annotations

import logging

from cerberus.state import CerberusState

logger = logging.getLogger(__name__)


async def approve_node(state: CerberusState) -> CerberusState:
    """Accept the human-approved resource list.

    On Python < 3.11, langgraph.types.interrupt() cannot access its runnable
    context in async nodes.  The approval gate is therefore implemented via
    interrupt_before=["approve_node"] at compile time: the graph pauses *before*
    this node runs.  The caller (API or test) then injects approved_actions and
    mutation_count=0 via graph.aupdate_state() before resuming with astream(None).

    By the time this node executes, state["approved_actions"] is already set.
    """
    logger.info(
        "approve_node: %d resource(s) approved out of %d",
        len(state.get("approved_actions") or []),
        len(state["resources"]),
    )
    # mutation_count must be 0 at the start of execute_node (INV-EXE-03).
    # Callers set it via aupdate_state; guard here in case they forget.
    state["mutation_count"] = 0
    return state
