from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Callable

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from cerberus.nodes.audit_node import AuditEntry, write_audit_entry
from cerberus.nodes.approve_node import approve_node
from cerberus.nodes.audit_node import audit_node
from cerberus.nodes.enrich_node import enrich_node
from cerberus.nodes.execute_node import execute_node
from cerberus.nodes.reason_node import reason_node
from cerberus.nodes.revalidate_node import revalidate_node
from cerberus.nodes.scan_node import scan_node
from cerberus.state import CerberusState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# error_node — INV-NFR-03
# ---------------------------------------------------------------------------


def error_node(state: CerberusState) -> CerberusState:
    if not state.get("error_message"):
        state["error_message"] = "An unexpected error occurred. Check the audit log."
    try:
        log_dir = os.environ.get("AUDIT_LOG_DIR", "./logs")
        try:
            from cerberus.config import get_config
            log_dir = get_config().audit_log_dir
        except Exception:
            pass  # fall back to env var
        write_audit_entry(
            AuditEntry(
                timestamp=datetime.utcnow().isoformat(),
                resource_id=None,
                action_type="NODE_ERROR",
                llm_reasoning=state["error_message"],
                actor="agent",
                outcome="NODE_ERROR",
                run_id=state["run_id"],
                session_mutation_count=state.get("mutation_count", 0),
                project_id=state["project_id"],
            ),
            log_dir,
            state["run_id"],
        )
    except Exception as exc:
        logger.error("audit write failed in error_node: %s", exc)
    state["run_complete"] = True
    return state


# ---------------------------------------------------------------------------
# Node exception wrapper — INV-NFR-03
# Re-raises GraphInterrupt so approve_node's interrupt() propagates correctly.
# ---------------------------------------------------------------------------


def _wrap_node(fn: Callable, node_name: str) -> Callable:
    """Catch unhandled exceptions; preserve LangGraph interrupt signals."""
    try:
        from langgraph.errors import GraphInterrupt  # type: ignore[import]
        _interrupt_types: tuple = (GraphInterrupt,)
    except ImportError:
        _interrupt_types = ()

    if asyncio.iscoroutinefunction(fn):
        async def async_wrapped(state: CerberusState) -> CerberusState:
            try:
                return await fn(state)
            except BaseException as exc:
                if _interrupt_types and isinstance(exc, _interrupt_types):
                    raise
                logger.error("Unhandled exception in %s: %s", node_name, exc, exc_info=True)
                state["error_message"] = str(exc)
                state["run_complete"] = True
                return state
        return async_wrapped
    else:
        def sync_wrapped(state: CerberusState) -> CerberusState:
            try:
                return fn(state)
            except BaseException as exc:
                if _interrupt_types and isinstance(exc, _interrupt_types):
                    raise
                logger.error("Unhandled exception in %s: %s", node_name, exc, exc_info=True)
                state["error_message"] = str(exc)
                state["run_complete"] = True
                return state
        return sync_wrapped


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def _route_after_scan(state: CerberusState) -> str:
    # Unhandled exception in wrapper sets run_complete=True
    if state.get("run_complete"):
        return "error_node"
    # INV-SEC-01: BLOCKED project routes to error_node
    if "BLOCKED" in (state.get("error_message") or ""):
        return "error_node"
    return "enrich_node"


def _route_after_revalidate(state: CerberusState) -> str:
    if state.get("run_complete"):
        return "error_node"
    if len(state.get("approved_actions") or []) == 0:
        return "audit_node"
    return "execute_node"


def _check_error_then(next_node: str) -> Callable[[CerberusState], str]:
    """Return a routing function that falls through to next_node unless a crash occurred."""
    def route(state: CerberusState) -> str:
        if state.get("run_complete"):
            return "error_node"
        return next_node
    return route


# ---------------------------------------------------------------------------
# Graph factory (accepts node overrides for testing)
# ---------------------------------------------------------------------------


def _build_graph(
    _scan: Any = None,
    _enrich: Any = None,
    _reason: Any = None,
    _approve: Any = None,
    _revalidate: Any = None,
    _execute: Any = None,
    _audit: Any = None,
) -> StateGraph:
    # Use provided overrides or the real node functions
    scan = _scan or scan_node
    enrich = _enrich or enrich_node
    reason = _reason or reason_node
    approve = _approve or approve_node
    revalidate = _revalidate or revalidate_node
    execute = _execute or execute_node
    audit = _audit or audit_node

    builder = StateGraph(CerberusState)

    builder.add_node("scan_node", _wrap_node(scan, "scan_node"))
    builder.add_node("enrich_node", _wrap_node(enrich, "enrich_node"))
    builder.add_node("reason_node", _wrap_node(reason, "reason_node"))
    # approve_node uses interrupt() which requires direct LangGraph context access —
    # must NOT be wrapped (interrupt() calls get_config() internally).
    builder.add_node("approve_node", approve)
    builder.add_node("revalidate_node", _wrap_node(revalidate, "revalidate_node"))
    builder.add_node("execute_node", _wrap_node(execute, "execute_node"))
    builder.add_node("audit_node", _wrap_node(audit, "audit_node"))
    builder.add_node("error_node", error_node)

    builder.add_edge(START, "scan_node")

    builder.add_conditional_edges(
        "scan_node", _route_after_scan, ["error_node", "enrich_node"]
    )
    builder.add_conditional_edges(
        "enrich_node", _check_error_then("reason_node"), ["error_node", "reason_node"]
    )
    builder.add_conditional_edges(
        "reason_node", _check_error_then("approve_node"), ["error_node", "approve_node"]
    )
    builder.add_conditional_edges(
        "approve_node", _check_error_then("revalidate_node"), ["error_node", "revalidate_node"]
    )
    builder.add_conditional_edges(
        "revalidate_node", _route_after_revalidate, ["error_node", "audit_node", "execute_node"]
    )
    builder.add_edge("execute_node", "audit_node")
    builder.add_edge("audit_node", END)
    builder.add_edge("error_node", END)

    return builder


cerberus_graph = _build_graph().compile(
    checkpointer=MemorySaver(),
    interrupt_before=["approve_node"],
)
