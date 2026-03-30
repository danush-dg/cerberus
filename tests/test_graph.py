from __future__ import annotations

import os
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from cerberus.graph import (
    _build_graph,
    _check_error_then,
    _route_after_scan,
    _route_after_revalidate,
    error_node,
)
from cerberus.state import initialise_state, CerberusState
from tests.conftest import make_resource_record

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**kwargs) -> CerberusState:
    s = initialise_state("nexus-tech-dev-test")
    for k, v in kwargs.items():
        s[k] = v
    return s


def _compile_graph(**node_overrides):
    """Build + compile a fresh graph for each test, injecting mock nodes."""
    from langgraph.checkpoint.memory import MemorySaver
    return _build_graph(**node_overrides).compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# Unit tests — routing functions
# ---------------------------------------------------------------------------


class TestRouteAfterScan:
    def test_blocked_routes_to_error(self):
        state = _make_state(error_message="BLOCKED: does not match allowed pattern")
        assert _route_after_scan(state) == "error_node"

    def test_run_complete_routes_to_error(self):
        state = _make_state(run_complete=True)
        assert _route_after_scan(state) == "error_node"

    def test_clean_state_routes_to_enrich(self):
        state = _make_state()
        assert _route_after_scan(state) == "enrich_node"

    def test_timeout_warning_routes_to_enrich(self):
        # Partial timeout sets error_message without BLOCKED — pipeline continues
        state = _make_state(error_message="Timeout: partial results returned after 60s")
        assert _route_after_scan(state) == "enrich_node"


class TestRouteAfterRevalidate:
    def test_no_approved_actions_routes_to_audit(self):
        state = _make_state(approved_actions=[])
        assert _route_after_revalidate(state) == "audit_node"

    def test_with_approved_actions_routes_to_execute(self):
        resource = make_resource_record("vm-1")
        state = _make_state(approved_actions=[resource])
        assert _route_after_revalidate(state) == "execute_node"

    def test_run_complete_routes_to_error(self):
        state = _make_state(run_complete=True, approved_actions=[])
        assert _route_after_revalidate(state) == "error_node"


class TestCheckErrorThen:
    def test_routes_to_next_when_clean(self):
        state = _make_state()
        route = _check_error_then("reason_node")
        assert route(state) == "reason_node"

    def test_routes_to_error_when_crashed(self):
        state = _make_state(run_complete=True)
        route = _check_error_then("reason_node")
        assert route(state) == "error_node"


# ---------------------------------------------------------------------------
# Unit tests — error_node
# ---------------------------------------------------------------------------


class TestErrorNode:
    def test_sets_default_error_message(self, tmp_path):
        os.environ["AUDIT_LOG_DIR"] = str(tmp_path)
        state = _make_state()
        result = error_node(state)
        assert result["error_message"] is not None
        assert "unexpected error" in result["error_message"]

    def test_preserves_existing_error_message(self, tmp_path):
        os.environ["AUDIT_LOG_DIR"] = str(tmp_path)
        state = _make_state(error_message="BLOCKED: bad project")
        result = error_node(state)
        assert result["error_message"] == "BLOCKED: bad project"

    def test_sets_run_complete(self, tmp_path):
        os.environ["AUDIT_LOG_DIR"] = str(tmp_path)
        state = _make_state(error_message="some error")
        result = error_node(state)
        assert result["run_complete"] is True

    def test_writes_node_error_audit_entry(self, tmp_path):
        import json
        log_dir = str(tmp_path / "logs")
        os.environ["AUDIT_LOG_DIR"] = log_dir
        state = _make_state(error_message="kaboom")
        error_node(state)
        run_id = state["run_id"]
        log_path = os.path.join(log_dir, f"audit_{run_id}.jsonl")
        lines = [json.loads(l) for l in open(log_path)]
        assert any(l["action_type"] == "NODE_ERROR" for l in lines)

    def test_audit_write_failure_does_not_raise(self, tmp_path):
        os.environ["AUDIT_LOG_DIR"] = str(tmp_path)
        state = _make_state(error_message="some error")
        with patch("cerberus.graph.write_audit_entry", side_effect=IOError("disk full")):
            result = error_node(state)  # must not raise
        assert result["run_complete"] is True


# ---------------------------------------------------------------------------
# Integration tests — graph routing via fresh compiled graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_project_routes_to_error(tmp_path):
    """scan_node returns BLOCKED error → graph completes via error_node."""
    os.environ["AUDIT_LOG_DIR"] = str(tmp_path)

    def mock_scan(state):
        state["error_message"] = "BLOCKED: 'nexus-tech-prod' does not match allowed pattern"
        return state

    async def mock_audit(state):
        state["run_complete"] = True
        return state

    graph = _compile_graph(_scan=mock_scan, _audit=mock_audit)
    result = await graph.ainvoke(
        initialise_state("nexus-tech-dev-test"),
        config={"configurable": {"thread_id": "test-blocked"}},
    )
    assert "BLOCKED" in result["error_message"]
    assert result["run_complete"] is True


@pytest.mark.asyncio
async def test_node_exception_routes_to_error_node(tmp_path):
    """Unhandled exception in scan_node → wrapper catches → error_node runs."""
    os.environ["AUDIT_LOG_DIR"] = str(tmp_path)

    def mock_scan_raises(state):
        raise RuntimeError("GCP credentials not found")

    async def mock_audit(state):
        state["run_complete"] = True
        return state

    graph = _compile_graph(_scan=mock_scan_raises, _audit=mock_audit)
    result = await graph.ainvoke(
        initialise_state("nexus-tech-dev-test"),
        config={"configurable": {"thread_id": "test-exception"}},
    )
    assert result["run_complete"] is True
    assert result["error_message"] is not None


@pytest.mark.asyncio
async def test_empty_approval_skips_execute_to_audit(tmp_path):
    """Approved actions = [] after revalidate → routes to audit_node, execute never called."""
    os.environ["AUDIT_LOG_DIR"] = str(tmp_path)

    execute_called = []

    def mock_scan(state):
        state["resources"] = [make_resource_record("vm-1", decision="safe_to_stop")]
        return state

    async def mock_enrich(state):
        return state

    async def mock_reason(state):
        return state

    def mock_approve(state):
        # Simulate approve with empty selection (no interrupt in test context)
        state["approved_actions"] = []
        state["mutation_count"] = 0
        return state

    async def mock_revalidate(state):
        return state

    async def mock_execute(state):
        execute_called.append(True)
        return state

    async def mock_audit(state):
        state["run_complete"] = True
        return state

    graph = _compile_graph(
        _scan=mock_scan,
        _enrich=mock_enrich,
        _reason=mock_reason,
        _approve=mock_approve,
        _revalidate=mock_revalidate,
        _execute=mock_execute,
        _audit=mock_audit,
    )
    result = await graph.ainvoke(
        initialise_state("nexus-tech-dev-test"),
        config={"configurable": {"thread_id": "test-empty-approval"}},
    )
    assert result["run_complete"] is True
    assert execute_called == [], "execute_node must not be called when approved_actions is empty"


@pytest.mark.asyncio
async def test_execute_called_with_approved_actions(tmp_path):
    """Approved actions present → routes through execute_node then audit_node."""
    os.environ["AUDIT_LOG_DIR"] = str(tmp_path)

    execute_called = []

    def mock_scan(state):
        state["resources"] = [make_resource_record("vm-1", decision="safe_to_stop")]
        return state

    async def mock_enrich(state):
        return state

    async def mock_reason(state):
        return state

    def mock_approve(state):
        state["approved_actions"] = state["resources"]
        state["mutation_count"] = 0
        return state

    async def mock_revalidate(state):
        return state

    async def mock_execute(state):
        execute_called.append(True)
        return state

    async def mock_audit(state):
        state["run_complete"] = True
        return state

    graph = _compile_graph(
        _scan=mock_scan,
        _enrich=mock_enrich,
        _reason=mock_reason,
        _approve=mock_approve,
        _revalidate=mock_revalidate,
        _execute=mock_execute,
        _audit=mock_audit,
    )
    result = await graph.ainvoke(
        initialise_state("nexus-tech-dev-test"),
        config={"configurable": {"thread_id": "test-execute-called"}},
    )
    assert result["run_complete"] is True
    assert execute_called == [True], "execute_node must be called when approved_actions is non-empty"
