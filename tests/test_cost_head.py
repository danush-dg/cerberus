"""Task 10.3 — Cost Head tests."""
from __future__ import annotations

import pytest

from cerberus.heads import cost_head
from cerberus.heads.cost_head import get_project_cost_summary, get_user_cost_summary


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_record(resource_id: str, owner_email: str, cost: float, project_id: str) -> dict:
    return {
        "resource_id": resource_id,
        "resource_type": "gce_instance",
        "ownership_status": "owned",
        "decision": "safe_to_stop",
        "outcome": "DRY_RUN",
        "estimated_monthly_cost": cost,
        "estimated_monthly_savings": 0.0,
        "region": "us-central1",
        "owner_email": owner_email,
        "project_id": project_id,
    }


# ---------------------------------------------------------------------------
# get_project_cost_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_cost_summary_basic(monkeypatch):
    """Returns correct totals and per-owner breakdown."""
    records = [
        _make_record("vm-1", "alice@x.com", 50.0, "nexus-tech-dev-1"),
        _make_record("vm-2", "bob@x.com", 30.0, "nexus-tech-dev-1"),
        _make_record("vm-3", "alice@x.com", 20.0, "nexus-tech-dev-1"),
    ]
    monkeypatch.setattr(cost_head, "query_project_history", lambda pid: records)

    result = await get_project_cost_summary("nexus-tech-dev-1")

    assert result.project_id == "nexus-tech-dev-1"
    assert result.total_usd == pytest.approx(100.0)
    assert result.attributed_usd == pytest.approx(100.0)
    assert result.unattributed_usd == pytest.approx(0.0)
    assert result.period == "current_month"

    emails = {r["owner_email"] for r in result.breakdown}
    assert emails == {"alice@x.com", "bob@x.com"}
    alice_row = next(r for r in result.breakdown if r["owner_email"] == "alice@x.com")
    assert alice_row["cost_usd"] == pytest.approx(70.0)


@pytest.mark.asyncio
async def test_project_cost_summary_inv_cost_01_unattributed_row(monkeypatch):
    """INV-COST-01: unattributed row is present when unattributed_usd > 0."""
    records = [
        _make_record("vm-1", "alice@x.com", 40.0, "nexus-tech-dev-1"),
        _make_record("vm-2", "unknown", 15.0, "nexus-tech-dev-1"),
    ]
    monkeypatch.setattr(cost_head, "query_project_history", lambda pid: records)

    result = await get_project_cost_summary("nexus-tech-dev-1")

    assert result.unattributed_usd == pytest.approx(15.0)
    unattr_row = next(
        (r for r in result.breakdown if r["owner_email"] == "unattributed"), None
    )
    assert unattr_row is not None, "INV-COST-01: unattributed row must be in breakdown"
    assert unattr_row["cost_usd"] == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_project_cost_summary_no_unattributed_row_when_zero(monkeypatch):
    """INV-COST-01: unattributed row must NOT appear when unattributed_usd == 0."""
    records = [
        _make_record("vm-1", "alice@x.com", 50.0, "nexus-tech-dev-1"),
    ]
    monkeypatch.setattr(cost_head, "query_project_history", lambda pid: records)

    result = await get_project_cost_summary("nexus-tech-dev-1")

    assert result.unattributed_usd == pytest.approx(0.0)
    unattr_row = next(
        (r for r in result.breakdown if r["owner_email"] == "unattributed"), None
    )
    assert unattr_row is None


@pytest.mark.asyncio
async def test_project_cost_summary_empty(monkeypatch):
    """Empty ChromaDB returns zeroed summary with empty breakdown."""
    monkeypatch.setattr(cost_head, "query_project_history", lambda pid: [])

    result = await get_project_cost_summary("nexus-tech-dev-1")

    assert result.total_usd == 0.0
    assert result.breakdown == []


@pytest.mark.asyncio
async def test_project_cost_summary_none_cost_treated_as_zero(monkeypatch):
    """Resources with None estimated_monthly_cost count as 0.0 — not excluded."""
    records = [
        {**_make_record("vm-1", "alice@x.com", 0.0, "nexus-tech-dev-1"), "estimated_monthly_cost": None},
        _make_record("vm-2", "bob@x.com", 10.0, "nexus-tech-dev-1"),
    ]
    monkeypatch.setattr(cost_head, "query_project_history", lambda pid: records)

    result = await get_project_cost_summary("nexus-tech-dev-1")

    assert result.total_usd == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# get_user_cost_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_cost_summary_basic(monkeypatch):
    """Returns correct per-user totals and resource list."""
    records = [
        _make_record("vm-1", "alice@x.com", 50.0, "nexus-tech-dev-1"),
        _make_record("disk-1", "alice@x.com", 5.0, "nexus-tech-dev-1"),
    ]
    monkeypatch.setattr(cost_head, "query_owner_history", lambda email, pid: records)

    result = await get_user_cost_summary("alice@x.com", "nexus-tech-dev-1")

    assert result.owner_email == "alice@x.com"
    assert result.project_id == "nexus-tech-dev-1"
    assert result.total_usd == pytest.approx(55.0)
    assert result.resource_count == 2
    assert len(result.resources) == 2
    ids = {r["resource_id"] for r in result.resources}
    assert ids == {"vm-1", "disk-1"}


@pytest.mark.asyncio
async def test_user_cost_summary_empty(monkeypatch):
    """No ChromaDB records → zeroed summary."""
    monkeypatch.setattr(cost_head, "query_owner_history", lambda email, pid: [])

    result = await get_user_cost_summary("nobody@x.com", "nexus-tech-dev-1")

    assert result.total_usd == 0.0
    assert result.resource_count == 0
    assert result.resources == []


@pytest.mark.asyncio
async def test_inv_cost_02_no_billing_import():
    """INV-COST-02: cost_head must not import the Cloud Billing client library."""
    import importlib
    import ast

    mod = importlib.import_module("cerberus.heads.cost_head")
    src = __import__("inspect").getsource(mod)
    tree = ast.parse(src)

    forbidden = {"google.cloud.billing", "cloudbilling"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            assert not any(f in module for f in forbidden), (
                f"INV-COST-02 violated: found billing import '{module}'"
            )
