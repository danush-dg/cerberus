"""Tests for scan_node — Session 2."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from cerberus.nodes.scan_node import (
    discover_orphaned_disks,
    discover_unused_ips,
    fetch_resource_costs,
    enrich_costs,
    scan_node,
)

import pytest

from cerberus.nodes.scan_node import discover_vms, CPU_IDLE_THRESHOLD, CPU_IDLE_WINDOW_HOURS
from cerberus.state import initialise_state
from cerberus.tools.gcp_retry import CerberusRetryExhausted

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_creds():
    return MagicMock()


def _make_instance(
    name: str = "vm-test-1",
    instance_id: int = 111111,
    zone: str = "zones/us-central1-a",
    creation_timestamp: str = "2025-01-01T00:00:00+00:00",
) -> MagicMock:
    inst = MagicMock()
    inst.name = name
    inst.id = instance_id
    inst.zone = zone
    inst.creation_timestamp = creation_timestamp
    return inst


def _make_monitoring_point(seconds_ago: int) -> MagicMock:
    """Return a mock monitoring Point whose end_time is `seconds_ago` seconds in the past."""
    ts = datetime.now(tz=timezone.utc) - timedelta(seconds=seconds_ago)
    point = MagicMock()
    point.value.double_value = 0.5
    point.interval.end_time = ts  # datetime object
    return point


def _make_agg_list(instances: list) -> list:
    scoped = MagicMock()
    scoped.instances = instances
    return [("zones/us-central1-a", scoped)]


# ---------------------------------------------------------------------------
# Task 2.1 — constants
# ---------------------------------------------------------------------------

def test_constants_match_spec():
    assert CPU_IDLE_THRESHOLD == 0.05
    assert CPU_IDLE_WINDOW_HOURS == 72


# ---------------------------------------------------------------------------
# Task 2.1 — discover_vms
# ---------------------------------------------------------------------------

def test_vm_with_no_monitoring_data_gets_creation_timestamp(mock_creds, mocker):
    instance = _make_instance(creation_timestamp="2025-01-01T00:00:00+00:00")
    mock_instances = MagicMock()
    mock_instances.aggregated_list.return_value = _make_agg_list([instance])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.InstancesClient",
        return_value=mock_instances,
    )
    mock_monitoring = MagicMock()
    mock_monitoring.list_time_series.return_value = []
    mocker.patch(
        "cerberus.nodes.scan_node.monitoring_v3.MetricServiceClient",
        return_value=mock_monitoring,
    )

    vms = discover_vms("nexus-tech-dev-1", mock_creds)

    assert len(vms) == 1
    assert vms[0]["last_activity_timestamp"] == vms[0]["creation_timestamp"]


def test_vm_with_recent_high_cpu_gets_recent_timestamp(mock_creds, mocker):
    instance = _make_instance(creation_timestamp="2025-01-01T00:00:00+00:00")
    mock_instances = MagicMock()
    mock_instances.aggregated_list.return_value = _make_agg_list([instance])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.InstancesClient",
        return_value=mock_instances,
    )

    # Last data point was 2 hours ago
    point = _make_monitoring_point(seconds_ago=2 * 3600)
    ts_series = MagicMock()
    ts_series.points = [point]
    mock_monitoring = MagicMock()
    mock_monitoring.list_time_series.return_value = [ts_series]
    mocker.patch(
        "cerberus.nodes.scan_node.monitoring_v3.MetricServiceClient",
        return_value=mock_monitoring,
    )

    vms = discover_vms("nexus-tech-dev-1", mock_creds)

    assert len(vms) == 1
    assert vms[0]["last_activity_timestamp"] is not None


def test_vm_recent_timestamp_is_newer_than_creation(mock_creds, mocker):
    """When monitoring data exists, last_activity_timestamp should reflect the data point."""
    instance = _make_instance(creation_timestamp="2025-01-01T00:00:00+00:00")
    mock_instances = MagicMock()
    mock_instances.aggregated_list.return_value = _make_agg_list([instance])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.InstancesClient",
        return_value=mock_instances,
    )

    point = _make_monitoring_point(seconds_ago=7200)  # 2 h ago
    ts_series = MagicMock()
    ts_series.points = [point]
    mock_monitoring = MagicMock()
    mock_monitoring.list_time_series.return_value = [ts_series]
    mocker.patch(
        "cerberus.nodes.scan_node.monitoring_v3.MetricServiceClient",
        return_value=mock_monitoring,
    )

    vms = discover_vms("nexus-tech-dev-1", mock_creds)

    assert vms[0]["last_activity_timestamp"] != vms[0]["creation_timestamp"]


def test_all_returned_records_have_required_fields(mock_creds, mocker):
    instance = _make_instance()
    mock_instances = MagicMock()
    mock_instances.aggregated_list.return_value = _make_agg_list([instance])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.InstancesClient",
        return_value=mock_instances,
    )
    mock_monitoring = MagicMock()
    mock_monitoring.list_time_series.return_value = []
    mocker.patch(
        "cerberus.nodes.scan_node.monitoring_v3.MetricServiceClient",
        return_value=mock_monitoring,
    )

    vms = discover_vms("nexus-tech-dev-1", mock_creds)

    for v in vms:
        for field in ["resource_id", "resource_type", "region", "creation_timestamp"]:
            assert v[field] is not None, f"Field '{field}' is None"


def test_vm_resource_type_is_vm(mock_creds, mocker):
    instance = _make_instance()
    mock_instances = MagicMock()
    mock_instances.aggregated_list.return_value = _make_agg_list([instance])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.InstancesClient",
        return_value=mock_instances,
    )
    mock_monitoring = MagicMock()
    mock_monitoring.list_time_series.return_value = []
    mocker.patch(
        "cerberus.nodes.scan_node.monitoring_v3.MetricServiceClient",
        return_value=mock_monitoring,
    )

    vms = discover_vms("nexus-tech-dev-1", mock_creds)

    assert vms[0]["resource_type"] == "vm"


def test_vm_estimated_monthly_cost_is_none(mock_creds, mocker):
    """Task 2.3 fills cost — Task 2.1 must leave it None."""
    instance = _make_instance()
    mock_instances = MagicMock()
    mock_instances.aggregated_list.return_value = _make_agg_list([instance])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.InstancesClient",
        return_value=mock_instances,
    )
    mock_monitoring = MagicMock()
    mock_monitoring.list_time_series.return_value = []
    mocker.patch(
        "cerberus.nodes.scan_node.monitoring_v3.MetricServiceClient",
        return_value=mock_monitoring,
    )

    vms = discover_vms("nexus-tech-dev-1", mock_creds)

    assert vms[0]["estimated_monthly_cost"] is None


def test_vm_monitoring_retry_exhausted_treats_as_idle(mock_creds, mocker):
    """On CerberusRetryExhausted for monitoring: last_activity_timestamp = creation_timestamp."""
    instance = _make_instance(creation_timestamp="2025-06-01T00:00:00+00:00")
    mock_instances = MagicMock()
    mock_instances.aggregated_list.return_value = _make_agg_list([instance])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.InstancesClient",
        return_value=mock_instances,
    )

    mock_monitoring = MagicMock()
    mock_monitoring.list_time_series.side_effect = CerberusRetryExhausted(
        "list_time_series", 3, Exception("429")
    )
    mocker.patch(
        "cerberus.nodes.scan_node.monitoring_v3.MetricServiceClient",
        return_value=mock_monitoring,
    )

    vms = discover_vms("nexus-tech-dev-1", mock_creds)

    assert len(vms) == 1
    assert vms[0]["last_activity_timestamp"] == "2025-06-01T00:00:00+00:00"


def test_vm_compute_retry_exhausted_returns_empty(mock_creds, mocker):
    """On CerberusRetryExhausted for instances.aggregated_list: return []."""
    mock_instances = MagicMock()
    mock_instances.aggregated_list.side_effect = CerberusRetryExhausted(
        "aggregated_list", 3, Exception("503")
    )
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.InstancesClient",
        return_value=mock_instances,
    )
    mocker.patch("cerberus.nodes.scan_node.monitoring_v3.MetricServiceClient")

    result = discover_vms("nexus-tech-dev-1", mock_creds)

    assert result == []


def test_empty_zone_produces_no_records(mock_creds, mocker):
    scoped = MagicMock()
    scoped.instances = []
    mock_instances = MagicMock()
    mock_instances.aggregated_list.return_value = [("zones/us-central1-a", scoped)]
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.InstancesClient",
        return_value=mock_instances,
    )
    mocker.patch("cerberus.nodes.scan_node.monitoring_v3.MetricServiceClient")

    result = discover_vms("nexus-tech-dev-1", mock_creds)

    assert result == []


def test_region_extracted_from_zone(mock_creds, mocker):
    instance = _make_instance(zone="zones/europe-west1-b")
    mock_instances = MagicMock()
    mock_instances.aggregated_list.return_value = _make_agg_list([instance])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.InstancesClient",
        return_value=mock_instances,
    )
    mock_monitoring = MagicMock()
    mock_monitoring.list_time_series.return_value = []
    mocker.patch(
        "cerberus.nodes.scan_node.monitoring_v3.MetricServiceClient",
        return_value=mock_monitoring,
    )

    vms = discover_vms("nexus-tech-dev-1", mock_creds)

    assert vms[0]["region"] == "europe-west1"


# ---------------------------------------------------------------------------
# Helpers for Task 2.2
# ---------------------------------------------------------------------------

def _make_disk(
    name: str = "disk-1",
    zone: str = "zones/us-central1-a",
    creation_timestamp: str = "2025-01-01T00:00:00+00:00",
    users: list | None = None,
    labels: dict | None = None,
) -> MagicMock:
    disk = MagicMock()
    disk.name = name
    disk.zone = zone
    disk.creation_timestamp = creation_timestamp
    disk.users = users  # None or [] = orphaned; non-empty = attached
    disk.labels = labels or {}
    return disk


def _make_disk_agg(disks: list) -> list:
    scoped = MagicMock()
    scoped.disks = disks
    return [("zones/us-central1-a", scoped)]


def _make_address(
    name: str = "ip-1",
    status: str = "RESERVED",
    region: str = "regions/us-central1",
    creation_timestamp: str = "2025-01-01T00:00:00+00:00",
    users: list | None = None,
) -> MagicMock:
    addr = MagicMock()
    addr.name = name
    addr.status = status
    addr.region = region
    addr.creation_timestamp = creation_timestamp
    addr.users = users
    return addr


def _make_ip_agg(addresses: list) -> list:
    scoped = MagicMock()
    scoped.addresses = addresses
    return [("regions/us-central1", scoped)]


# ---------------------------------------------------------------------------
# Task 2.2 — discover_orphaned_disks
# ---------------------------------------------------------------------------

def test_attached_disk_excluded(mock_creds, mocker):
    disk = _make_disk(users=["projects/p/zones/us-central1-a/instances/vm-1"])
    mock_client = MagicMock()
    mock_client.aggregated_list.return_value = _make_disk_agg([disk])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.DisksClient",
        return_value=mock_client,
    )
    assert discover_orphaned_disks("nexus-tech-dev-1", mock_creds) == []


def test_unattached_disk_included(mock_creds, mocker):
    disk = _make_disk(users=None)
    mock_client = MagicMock()
    mock_client.aggregated_list.return_value = _make_disk_agg([disk])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.DisksClient",
        return_value=mock_client,
    )
    disks = discover_orphaned_disks("nexus-tech-dev-1", mock_creds)
    assert len(disks) == 1 and disks[0]["resource_type"] == "orphaned_disk"


def test_empty_users_list_treated_as_orphaned(mock_creds, mocker):
    disk = _make_disk(users=[])
    mock_client = MagicMock()
    mock_client.aggregated_list.return_value = _make_disk_agg([disk])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.DisksClient",
        return_value=mock_client,
    )
    disks = discover_orphaned_disks("nexus-tech-dev-1", mock_creds)
    assert len(disks) == 1


def test_sensitive_disk_flagged_for_review(mock_creds, mocker):
    disk = _make_disk(users=None, labels={"data-classification": "sensitive"})
    mock_client = MagicMock()
    mock_client.aggregated_list.return_value = _make_disk_agg([disk])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.DisksClient",
        return_value=mock_client,
    )
    disks = discover_orphaned_disks("nexus-tech-dev-1", mock_creds)
    assert disks[0]["flagged_for_review"] is True


def test_non_sensitive_disk_not_flagged(mock_creds, mocker):
    disk = _make_disk(users=None, labels={"env": "dev"})
    mock_client = MagicMock()
    mock_client.aggregated_list.return_value = _make_disk_agg([disk])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.DisksClient",
        return_value=mock_client,
    )
    disks = discover_orphaned_disks("nexus-tech-dev-1", mock_creds)
    assert disks[0]["flagged_for_review"] is False


def test_orphaned_disk_last_activity_equals_creation(mock_creds, mocker):
    disk = _make_disk(users=None, creation_timestamp="2025-03-01T12:00:00+00:00")
    mock_client = MagicMock()
    mock_client.aggregated_list.return_value = _make_disk_agg([disk])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.DisksClient",
        return_value=mock_client,
    )
    disks = discover_orphaned_disks("nexus-tech-dev-1", mock_creds)
    assert disks[0]["last_activity_timestamp"] == disks[0]["creation_timestamp"]


def test_disk_retry_exhausted_returns_empty_list(mock_creds, mocker):
    mock_client = MagicMock()
    mock_client.aggregated_list.side_effect = CerberusRetryExhausted(
        "aggregated_list", 3, Exception("429")
    )
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.DisksClient",
        return_value=mock_client,
    )
    result = discover_orphaned_disks("nexus-tech-dev-1", mock_creds)
    assert result == []


# ---------------------------------------------------------------------------
# Task 2.2 — discover_unused_ips
# ---------------------------------------------------------------------------

def test_in_use_ip_excluded(mock_creds, mocker):
    addr = _make_address(status="RESERVED", users=["projects/p/instances/vm-1"])
    mock_client = MagicMock()
    mock_client.aggregated_list.return_value = _make_ip_agg([addr])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.AddressesClient",
        return_value=mock_client,
    )
    assert discover_unused_ips("nexus-tech-dev-1", mock_creds) == []


def test_in_use_status_excluded(mock_creds, mocker):
    addr = _make_address(status="IN_USE", users=None)
    mock_client = MagicMock()
    mock_client.aggregated_list.return_value = _make_ip_agg([addr])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.AddressesClient",
        return_value=mock_client,
    )
    assert discover_unused_ips("nexus-tech-dev-1", mock_creds) == []


def test_reserved_unused_ip_included(mock_creds, mocker):
    addr = _make_address(status="RESERVED", users=None)
    mock_client = MagicMock()
    mock_client.aggregated_list.return_value = _make_ip_agg([addr])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.AddressesClient",
        return_value=mock_client,
    )
    ips = discover_unused_ips("nexus-tech-dev-1", mock_creds)
    assert len(ips) == 1 and ips[0]["resource_type"] == "unused_ip"


def test_unused_ip_last_activity_equals_creation(mock_creds, mocker):
    addr = _make_address(status="RESERVED", users=None,
                         creation_timestamp="2025-02-01T00:00:00+00:00")
    mock_client = MagicMock()
    mock_client.aggregated_list.return_value = _make_ip_agg([addr])
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.AddressesClient",
        return_value=mock_client,
    )
    ips = discover_unused_ips("nexus-tech-dev-1", mock_creds)
    assert ips[0]["last_activity_timestamp"] == ips[0]["creation_timestamp"]


def test_ip_retry_exhausted_returns_empty_list(mock_creds, mocker):
    mock_client = MagicMock()
    mock_client.aggregated_list.side_effect = CerberusRetryExhausted(
        "aggregated_list", 3, Exception("503")
    )
    mocker.patch(
        "cerberus.nodes.scan_node.compute_v1.AddressesClient",
        return_value=mock_client,
    )
    result = discover_unused_ips("nexus-tech-dev-1", mock_creds)
    assert result == []


# ---------------------------------------------------------------------------
# Task 2.3 — fetch_resource_costs
# ---------------------------------------------------------------------------

def _mock_billing_client(mocker, billing_enabled: bool = True):
    billing_info = MagicMock()
    billing_info.billing_enabled = billing_enabled
    mock_client = MagicMock()
    mock_client.get_project_billing_info.return_value = billing_info
    mocker.patch(
        "cerberus.nodes.scan_node.billing_v1.CloudBillingClient",
        return_value=mock_client,
    )
    return mock_client


def test_known_resource_gets_averaged_cost(mock_creds, mocker):
    _mock_billing_client(mocker, billing_enabled=True)
    costs = fetch_resource_costs("p", ["vm-1"], "BA-123", mock_creds)
    assert isinstance(costs["vm-1"], float) and costs["vm-1"] >= 0


def test_unknown_resource_gets_zero_not_none(mock_creds, mocker):
    _mock_billing_client(mocker, billing_enabled=True)
    costs = fetch_resource_costs("p", ["vm-unknown"], "BA-123", mock_creds)
    assert costs.get("vm-unknown") == 0.0


def test_billing_not_enabled_returns_empty_dict(mock_creds, mocker):
    _mock_billing_client(mocker, billing_enabled=False)
    costs = fetch_resource_costs("p", ["vm-1"], "BA-123", mock_creds)
    assert costs == {}


def test_billing_failure_returns_empty_dict(mock_creds, mocker):
    mock_client = MagicMock()
    mock_client.get_project_billing_info.side_effect = CerberusRetryExhausted(
        "get_project_billing_info", 3, Exception("503")
    )
    mocker.patch(
        "cerberus.nodes.scan_node.billing_v1.CloudBillingClient",
        return_value=mock_client,
    )
    costs = fetch_resource_costs("p", ["vm-1"], "BA-123", mock_creds)
    assert costs == {}


def test_billing_unexpected_exception_returns_empty_dict(mock_creds, mocker):
    mock_client = MagicMock()
    mock_client.get_project_billing_info.side_effect = RuntimeError("unexpected")
    mocker.patch(
        "cerberus.nodes.scan_node.billing_v1.CloudBillingClient",
        return_value=mock_client,
    )
    costs = fetch_resource_costs("p", ["vm-1"], "BA-123", mock_creds)
    assert costs == {}


# ---------------------------------------------------------------------------
# Task 2.3 — enrich_costs
# ---------------------------------------------------------------------------

def test_enrich_costs_none_when_billing_failed():
    resources = [{"resource_id": "vm-1", "estimated_monthly_cost": None}]
    result = enrich_costs(resources, {})
    assert result[0]["estimated_monthly_cost"] is None


def test_enrich_costs_zero_when_resource_not_in_nonempty_map():
    resources = [{"resource_id": "vm-new", "estimated_monthly_cost": None}]
    result = enrich_costs(resources, {"vm-old": 45.0})
    assert result[0]["estimated_monthly_cost"] == 0.0


def test_enrich_costs_sets_value_from_map():
    resources = [{"resource_id": "vm-1", "estimated_monthly_cost": None}]
    result = enrich_costs(resources, {"vm-1": 72.50})
    assert result[0]["estimated_monthly_cost"] == 72.50


def test_enrich_costs_multiple_resources_mixed():
    resources = [
        {"resource_id": "vm-1", "estimated_monthly_cost": None},
        {"resource_id": "vm-2", "estimated_monthly_cost": None},
    ]
    result = enrich_costs(resources, {"vm-1": 50.0})
    assert result[0]["estimated_monthly_cost"] == 50.0
    assert result[1]["estimated_monthly_cost"] == 0.0  # not in non-empty map → 0.0


# ---------------------------------------------------------------------------
# Task 2.4 — scan_node assembly helpers
# ---------------------------------------------------------------------------

def _make_valid_resource(rid: str, resource_type: str = "vm") -> dict:
    return {
        "resource_id": rid,
        "resource_type": resource_type,
        "region": "us-central1",
        "creation_timestamp": "2025-01-01T00:00:00+00:00",
        "last_activity_timestamp": None,
        "estimated_monthly_cost": None,
        "ownership_status": None,
        "owner_email": None,
        "owner_iam_active": None,
        "flagged_for_review": False,
        "decision": None,
        "reasoning": None,
        "estimated_monthly_savings": None,
        "outcome": None,
    }


def _patch_config(mocker):
    mock_config = MagicMock()
    mock_config.allowed_project_pattern = "^nexus-tech-dev-[0-9a-z-]+$"
    mock_config.service_account_key_path = "/tmp/key.json"
    mock_config.billing_account_id = "BA-123"
    mocker.patch("cerberus.nodes.scan_node.get_config", return_value=mock_config)
    mocker.patch("cerberus.nodes.scan_node._load_credentials", return_value=MagicMock())
    return mock_config


def _patch_preflight_clients(mocker, vm_count: int, disk_count: int, ip_count: int):
    """Patch the three compute clients used in the preflight count step."""
    # VMs scope
    vm_scope = MagicMock()
    vm_scope.instances = [MagicMock() for _ in range(vm_count)]
    mock_vm_client = MagicMock()
    mock_vm_client.aggregated_list.return_value = [("zones/us-central1-a", vm_scope)]

    # Disks scope — all orphaned (users=None)
    disk_scope = MagicMock()
    disk_mocks = []
    for _ in range(disk_count):
        d = MagicMock()
        d.users = None
        disk_mocks.append(d)
    disk_scope.disks = disk_mocks
    mock_disk_client = MagicMock()
    mock_disk_client.aggregated_list.return_value = [("zones/us-central1-a", disk_scope)]

    # IPs scope — all unused (RESERVED, no users)
    ip_scope = MagicMock()
    ip_mocks = []
    for _ in range(ip_count):
        a = MagicMock()
        a.status = "RESERVED"
        a.users = None
        ip_mocks.append(a)
    ip_scope.addresses = ip_mocks
    mock_ip_client = MagicMock()
    mock_ip_client.aggregated_list.return_value = [("regions/us-central1", ip_scope)]

    mocker.patch("cerberus.nodes.scan_node.compute_v1.InstancesClient", return_value=mock_vm_client)
    mocker.patch("cerberus.nodes.scan_node.compute_v1.DisksClient", return_value=mock_disk_client)
    mocker.patch("cerberus.nodes.scan_node.compute_v1.AddressesClient", return_value=mock_ip_client)
    return mock_vm_client, mock_disk_client, mock_ip_client


# ---------------------------------------------------------------------------
# Task 2.4 — scan_node fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_gcp(mocker):
    _patch_config(mocker)
    mock_vm_client, _, _ = _patch_preflight_clients(mocker, vm_count=0, disk_count=0, ip_count=0)
    ns = MagicMock()
    ns.instances_list = mock_vm_client.aggregated_list
    return ns


@pytest.fixture
def mock_preflight_10_gather_7(mocker):
    _patch_config(mocker)
    # Preflight reports 10 resources (7 VMs + 2 disks + 1 IP)
    _patch_preflight_clients(mocker, vm_count=7, disk_count=2, ip_count=1)
    # Discovery returns only 7 valid resources
    resources = [_make_valid_resource(f"r-{i}") for i in range(7)]
    mocker.patch("cerberus.nodes.scan_node.discover_vms", return_value=resources[:5])
    mocker.patch("cerberus.nodes.scan_node.discover_orphaned_disks", return_value=resources[5:6])
    mocker.patch("cerberus.nodes.scan_node.discover_unused_ips", return_value=resources[6:7])
    mocker.patch("cerberus.nodes.scan_node.fetch_resource_costs", return_value={})


@pytest.fixture
def mock_full_scan(mocker):
    _patch_config(mocker)
    # Preflight and discovery both report 3 resources (complete scan)
    _patch_preflight_clients(mocker, vm_count=3, disk_count=0, ip_count=0)
    resources = [_make_valid_resource(f"vm-{i}") for i in range(3)]
    mocker.patch("cerberus.nodes.scan_node.discover_vms", return_value=resources)
    mocker.patch("cerberus.nodes.scan_node.discover_orphaned_disks", return_value=[])
    mocker.patch("cerberus.nodes.scan_node.discover_unused_ips", return_value=[])
    mocker.patch("cerberus.nodes.scan_node.fetch_resource_costs", return_value={})


@pytest.fixture
def mock_slow_gcp(mocker):
    _patch_config(mocker)
    # Preflight reports 5 resources
    _patch_preflight_clients(mocker, vm_count=5, disk_count=0, ip_count=0)
    # asyncio.wait_for raises TimeoutError to simulate the 60s timeout
    mocker.patch("asyncio.wait_for", side_effect=asyncio.TimeoutError)


# ---------------------------------------------------------------------------
# Task 2.4 — scan_node tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prod_project_blocked_before_gcp_call(mock_gcp):
    state = initialise_state("nexus-tech-prod")
    result = await scan_node(state)
    assert "BLOCKED" in result["error_message"]
    assert result["resources"] == []
    mock_gcp.instances_list.assert_not_called()


@pytest.mark.asyncio
async def test_partial_scan_sets_error_message(mock_preflight_10_gather_7):
    state = initialise_state("nexus-tech-dev-1")
    result = await scan_node(state)
    assert "Partial scan" in result["error_message"]
    assert len(result["resources"]) == 7


@pytest.mark.asyncio
async def test_complete_scan_no_error_message(mock_full_scan):
    state = initialise_state("nexus-tech-dev-1")
    result = await scan_node(state)
    assert result["error_message"] is None
    assert len(result["resources"]) > 0


@pytest.mark.asyncio
async def test_no_record_exits_missing_required_fields(mock_full_scan):
    state = initialise_state("nexus-tech-dev-1")
    result = await scan_node(state)
    for r in result["resources"]:
        for f in ["resource_id", "resource_type", "region", "creation_timestamp"]:
            assert r[f] is not None


@pytest.mark.asyncio
async def test_timeout_returns_partial_not_raises(mock_slow_gcp):
    state = initialise_state("nexus-tech-dev-1")
    result = await scan_node(state)
    assert "Partial scan" in result["error_message"]
