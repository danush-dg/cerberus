"""Tests for Session 5 — approve_node, revalidate_node, execute_node, and FastAPI API."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from cerberus.state import initialise_state
from cerberus.nodes.approve_node import approve_node
from tests.conftest import make_resource_record


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Return a synchronous TestClient for the FastAPI app.

    Patches get_config so no real .env is required.
    """
    from cerberus.config import CerberusConfig

    mock_config = CerberusConfig(
        gcp_project_id="nexus-tech-dev-1",
        service_account_key_path="/fake/key.json",
        billing_account_id="AAAAAA-BBBBBB-CCCCCC",
        gemini_api_key="fake-key",
    )

    with patch("cerberus.api.get_config", return_value=mock_config):
        from cerberus.api import app, active_runs

        active_runs.clear()
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        active_runs.clear()


@pytest.fixture
def active_run_fixture(client):
    """Pre-populate active_runs with a scanning run for nexus-tech-dev-1."""
    from cerberus.api import active_runs

    run_id = "fixture-run-id"
    active_runs[run_id] = {
        "thread_id": "fixture-thread-id",
        "project_id": "nexus-tech-dev-1",
        "status": "scanning",
        "approval_payload": None,
        "final_state": None,
        "error_message": None,
    }
    yield run_id
    active_runs.pop(run_id, None)


@pytest.fixture
def awaiting_approval_run(client):
    """Pre-populate active_runs with a run that is awaiting approval."""
    from cerberus.api import active_runs

    run_id = "approval-run-id"
    active_runs[run_id] = {
        "thread_id": "approval-thread-id",
        "project_id": "nexus-tech-dev-2",
        "status": "awaiting_approval",
        "approval_payload": [{"resource_id": "vm-1"}],
        "final_state": None,
        "error_message": None,
    }
    yield run_id
    active_runs.pop(run_id, None)


@pytest.fixture
def completed_run(client):
    """Pre-populate active_runs with a completed run."""
    from cerberus.api import active_runs

    run_id = "done-run-id"
    active_runs[run_id] = {
        "thread_id": "done-thread-id",
        "project_id": "nexus-tech-dev-3",
        "status": "complete",
        "approval_payload": None,
        "final_state": {
            "resources": [],
            "error_message": None,
            "run_complete": True,
            "dry_run": True,
            "langsmith_trace_url": None,
            "mutation_count": 0,
        },
        "error_message": None,
    }
    yield run_id
    active_runs.pop(run_id, None)


# ---------------------------------------------------------------------------
# approve_node unit tests
# ---------------------------------------------------------------------------


def _make_state_with_resources(resource_ids: list[str], approved_ids: list[str] | None = None):
    """Return a CerberusState containing resources for the given IDs."""
    state = initialise_state("nexus-tech-dev-1")
    state["resources"] = [
        make_resource_record(
            rid,
            decision="safe_to_stop",
            reasoning="CPU idle for 72h at 0.02 avg; cost $45/mo; owner active.",
            estimated_monthly_savings=45.0,
        )
        for rid in resource_ids
    ]
    return state


def _run_approve_node(approved_ids: list[str], resource_ids: list[str] | None = None):
    """Drive approve_node through the interrupt and return the resulting state."""
    if resource_ids is None:
        resource_ids = approved_ids

    state = _make_state_with_resources(resource_ids)

    with patch("cerberus.nodes.approve_node.interrupt", return_value=approved_ids):
        result = approve_node(state)

    return result


def test_mutation_count_zero_after_approve():
    """INV-EXE-03: mutation_count must be 0 after approve_node runs."""
    state = _run_approve_node(approved_ids=["vm-1", "vm-2"])
    assert state["mutation_count"] == 0


def test_approved_actions_filtered_by_ids():
    """Only resources whose IDs appear in approved_ids enter approved_actions."""
    state = _run_approve_node(
        approved_ids=["vm-1"],
        resource_ids=["vm-1", "vm-2"],
    )
    ids = [r["resource_id"] for r in state["approved_actions"]]
    assert ids == ["vm-1"]
    assert "vm-2" not in ids


def test_approve_node_empty_approved_ids():
    """Approving zero resources yields an empty approved_actions list."""
    state = _run_approve_node(approved_ids=[], resource_ids=["vm-1"])
    assert state["approved_actions"] == []
    assert state["mutation_count"] == 0


def test_approval_payload_excludes_credentials():
    """approve_node must not include credential fields in the interrupt payload."""
    captured_payload = None

    def fake_interrupt(value):
        nonlocal captured_payload
        captured_payload = value
        return []

    state = _make_state_with_resources(["vm-1"])
    with patch("cerberus.nodes.approve_node.interrupt", side_effect=fake_interrupt):
        approve_node(state)

    assert captured_payload is not None
    forbidden_keys = {
        "service_account_key_path",
        "gemini_api_key",
        "billing_account_id",
        "langsmith_api_key",
    }
    for item in captured_payload:
        assert not forbidden_keys.intersection(item.keys()), (
            f"Credential field found in approval payload: {item}"
        )


def test_approval_payload_contains_required_display_fields():
    """approve_node payload must include all display fields per INV-UI-01."""
    captured_payload = None

    def fake_interrupt(value):
        nonlocal captured_payload
        captured_payload = value
        return []

    state = _make_state_with_resources(["vm-1"])
    with patch("cerberus.nodes.approve_node.interrupt", side_effect=fake_interrupt):
        approve_node(state)

    required_keys = {
        "resource_id",
        "resource_type",
        "region",
        "owner_email",
        "ownership_status",
        "decision",
        "reasoning",
        "estimated_monthly_savings",
    }
    for item in captured_payload:
        assert required_keys.issubset(item.keys()), (
            f"Missing display fields in payload item: {item}"
        )


# ---------------------------------------------------------------------------
# FastAPI endpoint tests
# ---------------------------------------------------------------------------


def test_post_run_rejects_prod_project(client):
    """INV-SEC-01: project IDs not matching the pattern must be rejected."""
    r = client.post("/run", json={"project_id": "nexus-tech-prod"})
    assert r.status_code in (400, 422)
    assert "BLOCKED" in r.json()["error"]


def test_post_run_rejects_arbitrary_project(client):
    """Non-dev project names must be rejected."""
    r = client.post("/run", json={"project_id": "my-prod-db"})
    assert r.status_code in (400, 422)
    assert "BLOCKED" in r.json()["error"]


def test_concurrent_scan_returns_409(client, active_run_fixture):
    """A second scan request for the same project returns HTTP 409."""
    r = client.post("/run", json={"project_id": "nexus-tech-dev-1"})
    assert r.status_code == 409


def test_completed_run_allows_new_scan(client, completed_run):
    """A project whose previous run is complete may be scanned again."""
    from cerberus.api import active_runs

    # The completed_run fixture uses nexus-tech-dev-3.
    with patch("cerberus.api._run_graph_until_interrupt", new=AsyncMock()):
        r = client.post("/run", json={"project_id": "nexus-tech-dev-3"})
    # Should not 409 — completed runs are not "active".
    assert r.status_code != 409


def test_status_endpoint_excludes_credentials(client, completed_run):
    """INV-SEC-02: /status must not expose credential fields."""
    r = client.get(f"/run/{completed_run}/status")
    assert r.status_code == 200
    body_str = r.text
    for forbidden in ["service_account", "cerberus-key", "GOOGLE_APPLICATION", "api_key"]:
        assert forbidden.lower() not in body_str.lower(), (
            f"Credential string '{forbidden}' found in /status response"
        )


def test_get_plan_returns_scanning_before_interrupt(client, active_run_fixture):
    """/plan returns status=scanning and plan=null before interrupt fires."""
    r = client.get(f"/run/{active_run_fixture}/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "scanning"
    assert body["plan"] is None


def test_get_plan_returns_payload_at_interrupt(client, awaiting_approval_run):
    """/plan returns status=awaiting_approval and the payload after interrupt."""
    r = client.get(f"/run/{awaiting_approval_run}/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "awaiting_approval"
    assert body["plan"] is not None


def test_approve_with_empty_list_succeeds(client, awaiting_approval_run):
    """POST /approve with an empty approved_ids list must return HTTP 200."""
    with patch("cerberus.api._resume_graph", new=AsyncMock()):
        r = client.post(
            f"/run/{awaiting_approval_run}/approve",
            json={"approved_ids": []},
        )
    assert r.status_code == 200


def test_approve_sets_status_to_executing(client, awaiting_approval_run):
    """POST /approve must immediately set the run status to 'executing'."""
    with patch("cerberus.api._resume_graph", new=AsyncMock()):
        r = client.post(
            f"/run/{awaiting_approval_run}/approve",
            json={"approved_ids": ["vm-1"]},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "executing"


def test_unknown_run_id_returns_404(client):
    """Requests for an unknown run_id must return HTTP 404."""
    r = client.get("/run/does-not-exist/plan")
    assert r.status_code == 404

    r = client.post("/run/does-not-exist/approve", json={"approved_ids": []})
    assert r.status_code == 404

    r = client.get("/run/does-not-exist/status")
    assert r.status_code == 404


# ===========================================================================
# Task 5.2 — revalidate_node
# ===========================================================================

import pytest
from google.api_core.exceptions import NotFound as GcpNotFound

from cerberus.nodes.revalidate_node import revalidate_node
from cerberus.config import CerberusConfig


def _make_state_with_approvals(resource_ids: list[str]) -> dict:
    """CerberusState with all given IDs in both resources and approved_actions."""
    state = initialise_state("nexus-tech-dev-1")
    resources = [
        make_resource_record(
            rid,
            decision="safe_to_stop",
            reasoning="Idle for 72 h at 0.02 avg CPU; cost $45/mo; owner active.",
            estimated_monthly_savings=45.0,
        )
        for rid in resource_ids
    ]
    state["resources"] = resources
    state["approved_actions"] = list(resources)
    return state


_MOCK_REVALIDATE_CONFIG = CerberusConfig(
    gcp_project_id="nexus-tech-dev-1",
    service_account_key_path="/fake/key.json",
    billing_account_id="AAAAAA-BBBBBB-CCCCCC",
    gemini_api_key="fake-key",
)


@pytest.mark.asyncio
async def test_no_drift_approved_unchanged():
    """All resources pass re-check — approved_actions unchanged, no error_message."""
    state = _make_state_with_approvals(["vm-1", "vm-2"])

    with (
        patch("cerberus.nodes.revalidate_node.get_config", return_value=_MOCK_REVALIDATE_CONFIG),
        patch("cerberus.nodes.revalidate_node._load_credentials", return_value=None),
        patch("cerberus.nodes.revalidate_node._check_vm", return_value=(True, False)),
    ):
        result = await revalidate_node(state)

    assert len(result["approved_actions"]) == 2
    assert result["error_message"] is None


@pytest.mark.asyncio
async def test_drifted_vm_removed():
    """vm-1 is now RUNNING — removed from approved_actions, error_message set."""
    state = _make_state_with_approvals(["vm-1", "vm-2"])

    def _check_vm_mock(resource, *_args):
        drifted = resource["resource_id"] == "vm-1"
        return (True, drifted)

    with (
        patch("cerberus.nodes.revalidate_node.get_config", return_value=_MOCK_REVALIDATE_CONFIG),
        patch("cerberus.nodes.revalidate_node._load_credentials", return_value=None),
        patch("cerberus.nodes.revalidate_node._check_vm", side_effect=_check_vm_mock),
    ):
        result = await revalidate_node(state)

    ids = [r["resource_id"] for r in result["approved_actions"]]
    assert "vm-1" not in ids
    assert "vm-2" in ids
    assert result["error_message"] is not None


@pytest.mark.asyncio
async def test_404_silently_removed():
    """Resource gone (404) is removed without setting error_message."""
    state = _make_state_with_approvals(["vm-deleted"])

    with (
        patch("cerberus.nodes.revalidate_node.get_config", return_value=_MOCK_REVALIDATE_CONFIG),
        patch("cerberus.nodes.revalidate_node._load_credentials", return_value=None),
        patch(
            "cerberus.nodes.revalidate_node._check_vm",
            side_effect=GcpNotFound("gone"),
        ),
    ):
        result = await revalidate_node(state)

    assert len(result["approved_actions"]) == 0
    assert result["error_message"] is None  # 404 is not an error


@pytest.mark.asyncio
async def test_full_drift_clears_approved():
    """All resources drifted → approved_actions empty, 'cancelled' in error_message."""
    state = _make_state_with_approvals(["vm-1", "vm-2", "vm-3"])

    with (
        patch("cerberus.nodes.revalidate_node.get_config", return_value=_MOCK_REVALIDATE_CONFIG),
        patch("cerberus.nodes.revalidate_node._load_credentials", return_value=None),
        patch("cerberus.nodes.revalidate_node._check_vm", return_value=(True, True)),
    ):
        result = await revalidate_node(state)

    assert result["approved_actions"] == []
    assert "cancelled" in result["error_message"]


@pytest.mark.asyncio
async def test_drift_downgrades_decision_in_resources():
    """Drifted resource has its decision updated to 'needs_review' in state['resources']."""
    state = _make_state_with_approvals(["vm-1", "vm-2"])

    def _check_vm_mock(resource, *_args):
        return (True, resource["resource_id"] == "vm-1")

    with (
        patch("cerberus.nodes.revalidate_node.get_config", return_value=_MOCK_REVALIDATE_CONFIG),
        patch("cerberus.nodes.revalidate_node._load_credentials", return_value=None),
        patch("cerberus.nodes.revalidate_node._check_vm", side_effect=_check_vm_mock),
    ):
        result = await revalidate_node(state)

    vm1 = next(r for r in result["resources"] if r["resource_id"] == "vm-1")
    assert vm1["decision"] == "needs_review"
    vm2 = next(r for r in result["resources"] if r["resource_id"] == "vm-2")
    assert vm2["decision"] == "safe_to_stop"  # unchanged


# ===========================================================================
# Task 5.3 — execute_node
# ===========================================================================

from cerberus.nodes.execute_node import execute_node, stop_vm, delete_resource


_MOCK_EXECUTE_CONFIG = CerberusConfig(
    gcp_project_id="nexus-tech-dev-1",
    service_account_key_path="/fake/key.json",
    billing_account_id="AAAAAA-BBBBBB-CCCCCC",
    gemini_api_key="fake-key",
)


def _make_live_state(resources: list[dict]) -> dict:
    """CerberusState in live (non-dry-run) mode with given approved_actions."""
    state = initialise_state("nexus-tech-dev-1", dry_run=False)
    state["resources"] = resources
    state["approved_actions"] = list(resources)
    return state


def _make_resource(resource_id: str, **kwargs) -> dict:
    return make_resource_record(
        resource_id,
        decision=kwargs.pop("decision", "safe_to_stop"),
        reasoning="Idle 72 h; cost $45/mo; owner active.",
        estimated_monthly_savings=45.0,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_dry_run_zero_gcp_calls():
    """In dry_run mode execute_node must not call any GCP mutation API."""
    state = initialise_state("nexus-tech-dev-1", dry_run=True)
    state["approved_actions"] = [_make_resource("vm-1")]
    state["resources"] = list(state["approved_actions"])

    with (
        patch("cerberus.nodes.execute_node.stop_vm", new=AsyncMock()) as mock_stop,
        patch("cerberus.nodes.execute_node.delete_resource", new=AsyncMock()) as mock_delete,
    ):
        await execute_node(state)
        mock_stop.assert_not_called()
        mock_delete.assert_not_called()


@pytest.mark.asyncio
async def test_dry_run_marks_all_outcomes_dry_run():
    """Every approved resource must have outcome='DRY_RUN' after a dry-run pass."""
    state = initialise_state("nexus-tech-dev-1", dry_run=True)
    state["approved_actions"] = [_make_resource("vm-1"), _make_resource("vm-2")]
    state["resources"] = list(state["approved_actions"])

    result = await execute_node(state)

    for r in result["approved_actions"]:
        assert r["outcome"] == "DRY_RUN"


@pytest.mark.asyncio
async def test_rate_limit_halts_at_10():
    """execute_node must halt after 10 mutations and set error_message."""
    resources = [_make_resource(f"vm-{i}") for i in range(15)]
    state = _make_live_state(resources)

    with (
        patch("cerberus.nodes.execute_node.get_config", return_value=_MOCK_EXECUTE_CONFIG),
        patch("cerberus.nodes.execute_node._load_credentials", return_value=None),
        patch("cerberus.nodes.execute_node.stop_vm", new=AsyncMock(return_value=True)),
        patch(
            "cerberus.nodes.execute_node.verify_resource_state",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await execute_node(state)

    assert result["mutation_count"] == 10
    assert "Rate limit" in result["error_message"]


@pytest.mark.asyncio
async def test_flagged_resource_skipped_not_counted():
    """Flagged resources are SKIPPED_GUARDRAIL and must NOT increment mutation_count."""
    resources = [
        _make_resource("vm-flag", decision="safe_to_stop", flagged_for_review=True),
        _make_resource("vm-ok", decision="safe_to_stop", flagged_for_review=False),
    ]
    state = _make_live_state(resources)

    with (
        patch("cerberus.nodes.execute_node.get_config", return_value=_MOCK_EXECUTE_CONFIG),
        patch("cerberus.nodes.execute_node._load_credentials", return_value=None),
        patch("cerberus.nodes.execute_node.stop_vm", new=AsyncMock(return_value=True)),
        patch(
            "cerberus.nodes.execute_node.verify_resource_state",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await execute_node(state)

    # Only vm-ok should have been executed
    assert result["mutation_count"] == 1
    flagged = next(r for r in result["approved_actions"] if r["resource_id"] == "vm-flag")
    assert flagged["outcome"] == "SKIPPED_GUARDRAIL"


@pytest.mark.asyncio
async def test_safe_to_stop_never_calls_delete():
    """safe_to_stop resources must call stop_vm and never delete_resource."""
    state = _make_live_state([_make_resource("vm-1", decision="safe_to_stop")])

    with (
        patch("cerberus.nodes.execute_node.get_config", return_value=_MOCK_EXECUTE_CONFIG),
        patch("cerberus.nodes.execute_node._load_credentials", return_value=None),
        patch("cerberus.nodes.execute_node.stop_vm", new=AsyncMock(return_value=True)) as mock_stop,
        patch("cerberus.nodes.execute_node.delete_resource", new=AsyncMock()) as mock_delete,
        patch(
            "cerberus.nodes.execute_node.verify_resource_state",
            new=AsyncMock(return_value=True),
        ),
    ):
        await execute_node(state)

    mock_stop.assert_called_once()
    mock_delete.assert_not_called()


@pytest.mark.asyncio
async def test_safe_to_delete_never_calls_stop():
    """safe_to_delete resources must call delete_resource and never stop_vm."""
    state = _make_live_state([_make_resource("vm-1", decision="safe_to_delete")])

    with (
        patch("cerberus.nodes.execute_node.get_config", return_value=_MOCK_EXECUTE_CONFIG),
        patch("cerberus.nodes.execute_node._load_credentials", return_value=None),
        patch("cerberus.nodes.execute_node.stop_vm", new=AsyncMock()) as mock_stop,
        patch("cerberus.nodes.execute_node.delete_resource", new=AsyncMock(return_value=True)) as mock_delete,
        patch(
            "cerberus.nodes.execute_node.verify_resource_state",
            new=AsyncMock(return_value=True),
        ),
    ):
        await execute_node(state)

    mock_delete.assert_called_once()
    mock_stop.assert_not_called()


@pytest.mark.asyncio
async def test_failed_verification_decrements_counter():
    """If post-action verification fails, outcome=FAILED and mutation_count decremented."""
    state = _make_live_state([_make_resource("vm-1", decision="safe_to_stop")])

    with (
        patch("cerberus.nodes.execute_node.get_config", return_value=_MOCK_EXECUTE_CONFIG),
        patch("cerberus.nodes.execute_node._load_credentials", return_value=None),
        patch("cerberus.nodes.execute_node.stop_vm", new=AsyncMock(return_value=True)),
        patch(
            "cerberus.nodes.execute_node.verify_resource_state",
            new=AsyncMock(return_value=False),  # verification fails
        ),
    ):
        result = await execute_node(state)

    assert result["mutation_count"] == 0  # decremented after failed verify
    assert result["approved_actions"][0]["outcome"] == "FAILED"


@pytest.mark.asyncio
async def test_failed_action_decrements_counter():
    """If stop_vm itself returns False, outcome=FAILED and mutation_count decremented."""
    state = _make_live_state([_make_resource("vm-1", decision="safe_to_stop")])

    with (
        patch("cerberus.nodes.execute_node.get_config", return_value=_MOCK_EXECUTE_CONFIG),
        patch("cerberus.nodes.execute_node._load_credentials", return_value=None),
        patch("cerberus.nodes.execute_node.stop_vm", new=AsyncMock(return_value=False)),
    ):
        result = await execute_node(state)

    assert result["mutation_count"] == 0
    assert result["approved_actions"][0]["outcome"] == "FAILED"


@pytest.mark.asyncio
async def test_successful_stop_increments_counter():
    """A successful stop must increment mutation_count to 1 and set outcome=SUCCESS."""
    state = _make_live_state([_make_resource("vm-1", decision="safe_to_stop")])

    with (
        patch("cerberus.nodes.execute_node.get_config", return_value=_MOCK_EXECUTE_CONFIG),
        patch("cerberus.nodes.execute_node._load_credentials", return_value=None),
        patch("cerberus.nodes.execute_node.stop_vm", new=AsyncMock(return_value=True)),
        patch(
            "cerberus.nodes.execute_node.verify_resource_state",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await execute_node(state)

    assert result["mutation_count"] == 1
    assert result["approved_actions"][0]["outcome"] == "SUCCESS"


@pytest.mark.asyncio
async def test_empty_approved_actions_no_op():
    """execute_node with no approved actions must return state unchanged."""
    state = _make_live_state([])
    state["mutation_count"] = 0

    with (
        patch("cerberus.nodes.execute_node.get_config", return_value=_MOCK_EXECUTE_CONFIG),
        patch("cerberus.nodes.execute_node._load_credentials", return_value=None),
    ):
        result = await execute_node(state)

    assert result["mutation_count"] == 0
    assert result["approved_actions"] == []
