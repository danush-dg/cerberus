"""Tests for enrich_node — Tasks 3.1, 3.2 & 3.3."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import MagicMock

from cerberus.nodes.enrich_node import (
    lookup_by_labels,
    lookup_by_asset_inventory,
    lookup_by_iam_history,
    lookup_by_audit_log,
    resolve_owner,
    check_iam_membership,
    check_iam_last_activity,
    classify_ownership,
    enrich_node,
    STALENESS_THRESHOLD_DAYS,
)
from cerberus.state import initialise_state

mock_creds = MagicMock()


# ---------------------------------------------------------------------------
# lookup_by_labels
# ---------------------------------------------------------------------------

def test_label_owner_key_wins_over_created_by():
    r = {"labels": {"owner": "alice@x.com", "created-by": "bob@x.com"}}
    assert lookup_by_labels(r) == "alice@x.com"


def test_created_by_used_when_no_owner_key():
    r = {"labels": {"created-by": "bob@x.com"}}
    assert lookup_by_labels(r) == "bob@x.com"


def test_team_used_when_no_owner_or_created_by():
    r = {"labels": {"team": "platform@x.com"}}
    assert lookup_by_labels(r) == "platform@x.com"


def test_no_labels_returns_none():
    assert lookup_by_labels({"labels": {}}) is None
    assert lookup_by_labels({}) is None


def test_empty_owner_value_skipped():
    r = {"labels": {"owner": "", "created-by": "bob@x.com"}}
    assert lookup_by_labels(r) == "bob@x.com"


# ---------------------------------------------------------------------------
# resolve_owner — short-circuit and fallthrough behaviour
# ---------------------------------------------------------------------------

def test_resolve_stops_at_first_hit(mocker):
    mocker.patch("cerberus.nodes.enrich_node.lookup_by_labels", return_value="alice@x.com")
    spy = mocker.patch("cerberus.nodes.enrich_node.lookup_by_asset_inventory")
    resolve_owner({"labels": {"owner": "alice@x.com"}}, "p", mock_creds)
    spy.assert_not_called()


def test_resolve_skips_iam_history_when_asset_inventory_succeeds(mocker):
    mocker.patch("cerberus.nodes.enrich_node.lookup_by_labels", return_value=None)
    mocker.patch(
        "cerberus.nodes.enrich_node.lookup_by_asset_inventory",
        return_value="asset@x.com",
    )
    spy_iam = mocker.patch("cerberus.nodes.enrich_node.lookup_by_iam_history")
    result = resolve_owner({}, "nexus-tech-dev-1", mock_creds)
    assert result == "asset@x.com"
    spy_iam.assert_not_called()


def test_resolve_tries_all_if_labels_fail(mocker):
    mocker.patch("cerberus.nodes.enrich_node.lookup_by_labels", return_value=None)
    mocker.patch(
        "cerberus.nodes.enrich_node.lookup_by_asset_inventory",
        return_value="asset@x.com",
    )
    result = resolve_owner({}, "nexus-tech-dev-1", mock_creds)
    assert result is not None


def test_resolve_falls_through_to_iam_history(mocker):
    mocker.patch("cerberus.nodes.enrich_node.lookup_by_labels", return_value=None)
    mocker.patch("cerberus.nodes.enrich_node.lookup_by_asset_inventory", return_value=None)
    mocker.patch(
        "cerberus.nodes.enrich_node.lookup_by_iam_history",
        return_value="iam@x.com",
    )
    spy_audit = mocker.patch("cerberus.nodes.enrich_node.lookup_by_audit_log")
    result = resolve_owner({}, "nexus-tech-dev-1", mock_creds)
    assert result == "iam@x.com"
    spy_audit.assert_not_called()


def test_resolve_falls_through_to_audit_log(mocker):
    mocker.patch("cerberus.nodes.enrich_node.lookup_by_labels", return_value=None)
    mocker.patch("cerberus.nodes.enrich_node.lookup_by_asset_inventory", return_value=None)
    mocker.patch("cerberus.nodes.enrich_node.lookup_by_iam_history", return_value=None)
    mocker.patch(
        "cerberus.nodes.enrich_node.lookup_by_audit_log",
        return_value="audit@x.com",
    )
    result = resolve_owner({}, "nexus-tech-dev-1", mock_creds)
    assert result == "audit@x.com"


def test_resolve_returns_none_when_all_fail(mocker):
    for fn in [
        "lookup_by_labels",
        "lookup_by_asset_inventory",
        "lookup_by_iam_history",
        "lookup_by_audit_log",
    ]:
        mocker.patch(f"cerberus.nodes.enrich_node.{fn}", return_value=None)
    result = resolve_owner({}, "p", mock_creds)
    assert result is None


def test_resolve_passes_resource_id_to_api_lookups(mocker):
    mocker.patch("cerberus.nodes.enrich_node.lookup_by_labels", return_value=None)
    asset_spy = mocker.patch(
        "cerberus.nodes.enrich_node.lookup_by_asset_inventory", return_value="x@x.com"
    )
    resource = {"resource_id": "projects/p/zones/us-central1-a/instances/my-vm"}
    resolve_owner(resource, "nexus-tech-dev-1", mock_creds)
    asset_spy.assert_called_once_with(
        "projects/p/zones/us-central1-a/instances/my-vm",
        "nexus-tech-dev-1",
        mock_creds,
    )


# ---------------------------------------------------------------------------
# Task 3.2 — IAM membership check and staleness downgrade (INV-ENR-02)
# ---------------------------------------------------------------------------

def test_staleness_constant_is_90():
    assert STALENESS_THRESHOLD_DAYS == 90


def test_none_email_is_no_owner():
    status, active = classify_ownership(None, "p", mock_creds)
    assert status == "no_owner" and active is False


def test_not_in_iam_is_departed(mocker):
    mocker.patch("cerberus.nodes.enrich_node.check_iam_membership", return_value=False)
    status, active = classify_ownership("bob@x.com", "p", mock_creds)
    assert status == "departed_owner" and active is False


def test_active_recent_member(mocker):
    mocker.patch("cerberus.nodes.enrich_node.check_iam_membership", return_value=True)
    recent = datetime.now(tz=timezone.utc) - timedelta(days=10)
    mocker.patch("cerberus.nodes.enrich_node.check_iam_last_activity", return_value=recent)
    status, active = classify_ownership("alice@x.com", "p", mock_creds)
    assert status == "active_owner" and active is True


def test_stale_iam_member_downgraded(mocker):
    mocker.patch("cerberus.nodes.enrich_node.check_iam_membership", return_value=True)
    stale = datetime.now(tz=timezone.utc) - timedelta(days=100)
    mocker.patch("cerberus.nodes.enrich_node.check_iam_last_activity", return_value=stale)
    status, active = classify_ownership("stale@x.com", "p", mock_creds)
    assert status == "departed_owner" and active is False


def test_no_last_activity_treated_as_active(mocker):
    # If we can't determine last activity, we don't downgrade — benefit of the doubt.
    mocker.patch("cerberus.nodes.enrich_node.check_iam_membership", return_value=True)
    mocker.patch("cerberus.nodes.enrich_node.check_iam_last_activity", return_value=None)
    status, active = classify_ownership("alice@x.com", "p", mock_creds)
    assert status == "active_owner" and active is True


def test_staleness_boundary_exactly_90_days_is_active(mocker):
    mocker.patch("cerberus.nodes.enrich_node.check_iam_membership", return_value=True)
    exactly_90 = datetime.now(tz=timezone.utc) - timedelta(days=90)
    mocker.patch("cerberus.nodes.enrich_node.check_iam_last_activity", return_value=exactly_90)
    status, active = classify_ownership("border@x.com", "p", mock_creds)
    # days == 90 is NOT > 90, so still active
    assert status == "active_owner" and active is True


def test_check_iam_membership_retry_exhausted_returns_false(mocker):
    from cerberus.tools.gcp_retry import CerberusRetryExhausted
    mocker.patch(
        "cerberus.nodes.enrich_node.gcp_call_with_retry",
        side_effect=CerberusRetryExhausted("_get_policy", 3, Exception("timeout")),
    )
    result = check_iam_membership("alice@x.com", "p", mock_creds)
    assert result is False


def test_check_iam_last_activity_retry_exhausted_returns_none(mocker):
    from cerberus.tools.gcp_retry import CerberusRetryExhausted
    mocker.patch(
        "cerberus.nodes.enrich_node.gcp_call_with_retry",
        side_effect=CerberusRetryExhausted("_query", 3, Exception("timeout")),
    )
    result = check_iam_last_activity("alice@x.com", "p", mock_creds)
    assert result is None


# ---------------------------------------------------------------------------
# Task 3.3 — enrich_node assembly (INV-ENR-01, INV-ENR-02, INV-ENR-03)
# ---------------------------------------------------------------------------

def _make_resource(resource_id: str, resource_type: str = "gce_vm", **kwargs) -> dict:
    base = {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "region": "us-central1",
        "creation_timestamp": "2025-01-01T00:00:00Z",
        "last_activity_timestamp": None,
        "estimated_monthly_cost": 50.0,
        "ownership_status": None,
        "owner_email": None,
        "owner_iam_active": None,
        "flagged_for_review": False,
        "decision": None,
        "reasoning": None,
        "estimated_monthly_savings": None,
        "outcome": None,
        "labels": {},
    }
    base.update(kwargs)
    return base


def _patch_enrich_internals(mocker, *, owner_email=None, ownership_status="no_owner",
                             owner_iam_active=False):
    mocker.patch("cerberus.nodes.enrich_node.get_config", return_value=MagicMock(
        service_account_key_path="/fake/key.json"
    ))
    mocker.patch("cerberus.nodes.enrich_node._load_credentials", return_value=mock_creds)
    mocker.patch("cerberus.nodes.enrich_node.resolve_owner", return_value=owner_email)
    mocker.patch(
        "cerberus.nodes.enrich_node.classify_ownership",
        return_value=(ownership_status, owner_iam_active),
    )


@pytest.mark.asyncio
async def test_no_owner_resource_flagged(mocker):
    _patch_enrich_internals(mocker, owner_email=None, ownership_status="no_owner",
                            owner_iam_active=False)
    state = initialise_state("nexus-tech-dev-1")
    state["resources"] = [_make_resource("vm-1")]
    result = await enrich_node(state)
    r = result["resources"][0]
    assert r["ownership_status"] == "no_owner"
    assert r["flagged_for_review"] is True


@pytest.mark.asyncio
async def test_active_owner_not_flagged(mocker):
    _patch_enrich_internals(mocker, owner_email="alice@x.com", ownership_status="active_owner",
                            owner_iam_active=True)
    state = initialise_state("nexus-tech-dev-1")
    state["resources"] = [_make_resource("vm-2", labels={"owner": "alice@x.com"})]
    result = await enrich_node(state)
    r = result["resources"][0]
    assert r["ownership_status"] == "active_owner"
    assert r["flagged_for_review"] is False


@pytest.mark.asyncio
async def test_sensitive_disk_flag_preserved(mocker):
    # disk was already flagged_for_review=True by scan_node (sensitive label)
    _patch_enrich_internals(mocker, owner_email="alice@x.com", ownership_status="active_owner",
                            owner_iam_active=True)
    state = initialise_state("nexus-tech-dev-1")
    state["resources"] = [_make_resource("disk-1", resource_type="orphaned_disk",
                                         flagged_for_review=True)]
    result = await enrich_node(state)
    assert result["resources"][0]["flagged_for_review"] is True


@pytest.mark.asyncio
async def test_no_resource_exits_with_none_ownership(mocker):
    # classify_ownership raises partway through — completeness guard must catch any None
    mocker.patch("cerberus.nodes.enrich_node.get_config", return_value=MagicMock(
        service_account_key_path="/fake/key.json"
    ))
    mocker.patch("cerberus.nodes.enrich_node._load_credentials", return_value=mock_creds)
    mocker.patch("cerberus.nodes.enrich_node.resolve_owner", return_value=None)
    # Return None ownership_status to simulate partial failure
    mocker.patch(
        "cerberus.nodes.enrich_node.classify_ownership",
        side_effect=Exception("simulated failure"),
    )
    state = initialise_state("nexus-tech-dev-1")
    state["resources"] = [_make_resource("vm-1"), _make_resource("vm-2")]
    result = await enrich_node(state)
    for r in result["resources"]:
        assert r["ownership_status"] is not None


@pytest.mark.asyncio
async def test_completeness_guard_sets_error_message(mocker):
    mocker.patch("cerberus.nodes.enrich_node.get_config", return_value=MagicMock(
        service_account_key_path="/fake/key.json"
    ))
    mocker.patch("cerberus.nodes.enrich_node._load_credentials", return_value=mock_creds)
    mocker.patch("cerberus.nodes.enrich_node.resolve_owner", return_value=None)
    mocker.patch(
        "cerberus.nodes.enrich_node.classify_ownership",
        side_effect=Exception("simulated failure"),
    )
    state = initialise_state("nexus-tech-dev-1")
    state["resources"] = [_make_resource("vm-1"), _make_resource("vm-2")]
    result = await enrich_node(state)
    assert result["error_message"] is not None
    assert "forced to no_owner" in result["error_message"]


@pytest.mark.asyncio
async def test_owner_fields_written_to_resource(mocker):
    _patch_enrich_internals(mocker, owner_email="bob@x.com", ownership_status="active_owner",
                            owner_iam_active=True)
    state = initialise_state("nexus-tech-dev-1")
    state["resources"] = [_make_resource("vm-3")]
    result = await enrich_node(state)
    r = result["resources"][0]
    assert r["owner_email"] == "bob@x.com"
    assert r["owner_iam_active"] is True
