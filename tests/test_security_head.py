"""Task 10.4 — Security Head tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from cerberus.heads import security_head
from cerberus.heads.security_head import (
    OVER_PERMISSION_INACTIVITY_DAYS,
    check_budget_status,
    get_security_flags,
)
from cerberus.models.iam_ticket import IAMBinding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _binding(identity: str = "alice@x.com", role: str = "roles/owner") -> IAMBinding:
    return IAMBinding(
        identity=identity,
        role=role,
        project_id="nexus-tech-dev-1",
        binding_type="user",
    )


def _idle_record(resource_id: str = "vm-idle-1", cost: float = 120.0) -> dict:
    return {
        "resource_id": resource_id,
        "resource_type": "gce_instance",
        "decision": "safe_to_stop",
        "estimated_monthly_cost": cost,
    }


def _cheap_record(resource_id: str = "vm-cheap-1") -> dict:
    return {
        "resource_id": resource_id,
        "resource_type": "gce_instance",
        "decision": "safe_to_stop",
        "estimated_monthly_cost": 10.0,
    }


# ---------------------------------------------------------------------------
# check_budget_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_status_not_breached_when_under_threshold(monkeypatch):
    """Total cost below default threshold → breached=False."""
    records = [_cheap_record(resource_id=f"vm-{i}") for i in range(3)]  # 30 < 500
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: records)

    status = await check_budget_status("nexus-tech-dev-1")

    assert status.project_id == "nexus-tech-dev-1"
    assert status.breached is False
    assert status.current_month_usd == pytest.approx(30.0)
    assert status.threshold_usd == pytest.approx(500.0)


@pytest.mark.asyncio
async def test_budget_status_breached_when_over_threshold(monkeypatch):
    """Total cost above default threshold → breached=True."""
    records = [_idle_record(resource_id=f"vm-{i}", cost=100.0) for i in range(6)]  # 600 > 500
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: records)

    status = await check_budget_status("nexus-tech-dev-1")

    assert status.breached is True
    assert status.current_month_usd == pytest.approx(600.0)
    assert status.percent_used == pytest.approx(120.0)


@pytest.mark.asyncio
async def test_budget_status_empty_records(monkeypatch):
    """No records → zero cost, not breached."""
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: [])

    status = await check_budget_status("nexus-tech-dev-1")

    assert status.current_month_usd == 0.0
    assert status.breached is False


# ---------------------------------------------------------------------------
# get_security_flags — CHECK 1: OVER_PERMISSIONED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_over_permissioned_flag_raised_for_inactive_owner(monkeypatch):
    """INV-SEC2-01: flag raised when BOTH privileged role AND inactivity conditions are met."""
    stale_dt = datetime.now(tz=timezone.utc) - timedelta(days=OVER_PERMISSION_INACTIVITY_DAYS + 10)

    monkeypatch.setattr(security_head, "get_iam_inventory", AsyncMock(return_value=[_binding()]))
    monkeypatch.setattr(
        security_head, "check_iam_last_activity",
        lambda identity, project_id, credentials: stale_dt,
    )
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: [])
    monkeypatch.setattr(security_head, "write_audit_entry", lambda *a, **kw: None)

    flags = await get_security_flags("nexus-tech-dev-1", credentials=None)

    over = [f for f in flags if f.flag_type == "OVER_PERMISSIONED"]
    assert len(over) >= 1
    assert "inactive" in over[0].detail.lower() or "days" in over[0].detail


@pytest.mark.asyncio
async def test_over_permissioned_flag_not_raised_for_active_owner(monkeypatch):
    """INV-SEC2-01: flag NOT raised when owner is recently active."""
    recent_dt = datetime.now(tz=timezone.utc) - timedelta(days=5)  # < threshold

    monkeypatch.setattr(security_head, "get_iam_inventory", AsyncMock(return_value=[_binding()]))
    monkeypatch.setattr(
        security_head, "check_iam_last_activity",
        lambda identity, project_id, credentials: recent_dt,
    )
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: [])
    monkeypatch.setattr(security_head, "write_audit_entry", lambda *a, **kw: None)

    flags = await get_security_flags("nexus-tech-dev-1", credentials=None)

    over = [f for f in flags if f.flag_type == "OVER_PERMISSIONED"]
    assert len(over) == 0


@pytest.mark.asyncio
async def test_over_permissioned_not_raised_for_non_privileged_role(monkeypatch):
    """INV-SEC2-01: viewer role never triggers OVER_PERMISSIONED even when inactive."""
    stale_dt = datetime.now(tz=timezone.utc) - timedelta(days=60)

    monkeypatch.setattr(
        security_head, "get_iam_inventory",
        AsyncMock(return_value=[_binding(role="roles/viewer")]),
    )
    monkeypatch.setattr(
        security_head, "check_iam_last_activity",
        lambda identity, project_id, credentials: stale_dt,
    )
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: [])
    monkeypatch.setattr(security_head, "write_audit_entry", lambda *a, **kw: None)

    flags = await get_security_flags("nexus-tech-dev-1", credentials=None)

    over = [f for f in flags if f.flag_type == "OVER_PERMISSIONED"]
    assert len(over) == 0


@pytest.mark.asyncio
async def test_inv_sec2_01_both_conditions_required(monkeypatch):
    """INV-SEC2-01: privileged role alone without inactivity must not raise flag."""
    recent_dt = datetime.now(tz=timezone.utc) - timedelta(days=1)

    monkeypatch.setattr(
        security_head, "get_iam_inventory",
        AsyncMock(return_value=[_binding(role="roles/owner")]),
    )
    monkeypatch.setattr(
        security_head, "check_iam_last_activity",
        lambda identity, project_id, credentials: recent_dt,
    )
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: [])
    monkeypatch.setattr(security_head, "write_audit_entry", lambda *a, **kw: None)

    flags = await get_security_flags("nexus-tech-dev-1", credentials=None)

    over = [f for f in flags if f.flag_type == "OVER_PERMISSIONED"]
    assert len(over) == 0, "INV-SEC2-01: active owner with privileged role must not be flagged"


@pytest.mark.asyncio
async def test_over_permissioned_raised_for_none_last_activity(monkeypatch):
    """Unknown last_activity (None) treats the owner as stale and raises the flag."""
    monkeypatch.setattr(security_head, "get_iam_inventory", AsyncMock(return_value=[_binding()]))
    monkeypatch.setattr(
        security_head, "check_iam_last_activity",
        lambda identity, project_id, credentials: None,
    )
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: [])
    monkeypatch.setattr(security_head, "write_audit_entry", lambda *a, **kw: None)

    flags = await get_security_flags("nexus-tech-dev-1", credentials=None)

    over = [f for f in flags if f.flag_type == "OVER_PERMISSIONED"]
    assert len(over) >= 1


# ---------------------------------------------------------------------------
# get_security_flags — CHECK 2: GHOST_RESOURCE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ghost_resource_flag_from_chroma(monkeypatch):
    """GHOST_RESOURCE flag raised for idle records in ChromaDB."""
    idle_records = [_idle_record(resource_id="vm-ghost-1")]

    monkeypatch.setattr(security_head, "get_iam_inventory", AsyncMock(return_value=[]))
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: idle_records)
    monkeypatch.setattr(security_head, "write_audit_entry", lambda *a, **kw: None)

    flags = await get_security_flags("nexus-tech-dev-1", credentials=None)

    ghosts = [f for f in flags if f.flag_type == "GHOST_RESOURCE"]
    assert len(ghosts) >= 1
    assert ghosts[0].identity_or_resource == "vm-ghost-1"


@pytest.mark.asyncio
async def test_ghost_resource_for_safe_to_delete_decision(monkeypatch):
    """safe_to_delete decisions also produce GHOST_RESOURCE flags."""
    records = [{**_idle_record(resource_id="disk-orphan"), "decision": "safe_to_delete"}]

    monkeypatch.setattr(security_head, "get_iam_inventory", AsyncMock(return_value=[]))
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: records)
    monkeypatch.setattr(security_head, "write_audit_entry", lambda *a, **kw: None)

    flags = await get_security_flags("nexus-tech-dev-1", credentials=None)

    ghosts = [f for f in flags if f.flag_type == "GHOST_RESOURCE"]
    assert len(ghosts) >= 1


@pytest.mark.asyncio
async def test_ghost_resource_no_flags_for_non_actionable_decisions(monkeypatch):
    """needs_review and skip decisions do not produce GHOST_RESOURCE flags."""
    records = [
        {**_idle_record(), "decision": "needs_review"},
        {**_idle_record(resource_id="vm-2"), "decision": "skip"},
    ]

    monkeypatch.setattr(security_head, "get_iam_inventory", AsyncMock(return_value=[]))
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: records)
    monkeypatch.setattr(security_head, "write_audit_entry", lambda *a, **kw: None)

    flags = await get_security_flags("nexus-tech-dev-1", credentials=None)

    ghosts = [f for f in flags if f.flag_type == "GHOST_RESOURCE"]
    assert len(ghosts) == 0


# ---------------------------------------------------------------------------
# get_security_flags — CHECK 3: BUDGET_BREACH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_breach_flag_when_over_threshold(monkeypatch):
    """BUDGET_BREACH flag raised when total cost exceeds threshold."""
    expensive = [_idle_record(resource_id=f"vm-{i}", cost=100.0) for i in range(6)]  # 600 > 500

    monkeypatch.setattr(security_head, "get_iam_inventory", AsyncMock(return_value=[]))
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: expensive)

    written: list = []
    monkeypatch.setattr(
        security_head, "write_audit_entry",
        lambda entry, log_dir, run_id: written.append(entry),
    )

    flags = await get_security_flags("nexus-tech-dev-1", credentials=None)

    budget_flags = [f for f in flags if f.flag_type == "BUDGET_BREACH"]
    assert len(budget_flags) == 1


@pytest.mark.asyncio
async def test_budget_breach_inv_sec2_02_audit_entry_written(monkeypatch):
    """INV-SEC2-02: BUDGET_BREACH flag must produce a JSONL audit entry."""
    expensive = [_idle_record(resource_id=f"vm-{i}", cost=100.0) for i in range(6)]

    monkeypatch.setattr(security_head, "get_iam_inventory", AsyncMock(return_value=[]))
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: expensive)

    written: list = []
    monkeypatch.setattr(
        security_head, "write_audit_entry",
        lambda entry, log_dir, run_id: written.append(entry),
    )

    await get_security_flags("nexus-tech-dev-1", credentials=None)

    assert len(written) >= 1, "INV-SEC2-02: write_audit_entry must be called for BUDGET_BREACH"
    assert written[0].action_type == "SECURITY_FLAG"


@pytest.mark.asyncio
async def test_budget_not_breached_when_under_threshold(monkeypatch):
    """No BUDGET_BREACH flag when total cost is below threshold."""
    cheap = [_cheap_record(resource_id=f"vm-{i}") for i in range(3)]  # 30 < 500

    monkeypatch.setattr(security_head, "get_iam_inventory", AsyncMock(return_value=[]))
    monkeypatch.setattr(security_head, "query_project_history", lambda pid: cheap)
    monkeypatch.setattr(security_head, "write_audit_entry", lambda *a, **kw: None)

    flags = await get_security_flags("nexus-tech-dev-1", credentials=None)

    budget_flags = [f for f in flags if f.flag_type == "BUDGET_BREACH"]
    assert len(budget_flags) == 0
