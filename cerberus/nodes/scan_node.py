from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from google.cloud import compute_v1, monitoring_v3, billing_v1
from google.oauth2 import service_account
from google.protobuf import duration_pb2

from cerberus.state import CerberusState, validate_resource_record
from cerberus.config import get_config, validate_project_id
from cerberus.tools.gcp_retry import gcp_call_with_retry, CerberusRetryExhausted

logger = logging.getLogger(__name__)

CPU_IDLE_THRESHOLD: float = 0.05
CPU_IDLE_WINDOW_HOURS: int = 72


def _load_credentials(key_path: str):
    return service_account.Credentials.from_service_account_file(
        key_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


def discover_vms(project_id: str, credentials) -> list[dict]:
    instances_client = compute_v1.InstancesClient(credentials=credentials)
    monitoring_client = monitoring_v3.MetricServiceClient(credentials=credentials)

    try:
        agg_list = gcp_call_with_retry(
            instances_client.aggregated_list,
            project=project_id,
        )
    except CerberusRetryExhausted:
        logger.error("VM discovery: retry exhausted for project %s", project_id)
        return []

    now = datetime.now(tz=timezone.utc)
    window_start = now - timedelta(hours=CPU_IDLE_WINDOW_HOURS)
    results = []

    for _scope, zone_data in agg_list:
        instances = getattr(zone_data, "instances", None) or []
        for instance in instances:
            zone = (instance.zone or "").rsplit("/", 1)[-1]
            region = zone.rsplit("-", 1)[0] if zone else "unknown"
            creation_ts = instance.creation_timestamp
            last_activity_timestamp = creation_ts

            filter_str = (
                'metric.type="compute.googleapis.com/instance/cpu/utilization"'
                f' AND resource.labels.instance_id="{instance.id}"'
            )
            request = monitoring_v3.ListTimeSeriesRequest(
                name=f"projects/{project_id}",
                filter=filter_str,
                interval=monitoring_v3.TimeInterval(
                    end_time=now,
                    start_time=window_start,
                ),
                aggregation=monitoring_v3.Aggregation(
                    alignment_period=duration_pb2.Duration(
                        seconds=CPU_IDLE_WINDOW_HOURS * 3600
                    ),
                    per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
                ),
            )

            try:
                time_series = list(
                    gcp_call_with_retry(
                        monitoring_client.list_time_series, request=request
                    )
                )
                latest_ts: str | None = None
                for ts in time_series:
                    for point in ts.points:
                        pt_end = point.interval.end_time
                        if hasattr(pt_end, "isoformat"):
                            pt_str = pt_end.isoformat()
                        else:
                            pt_str = datetime.fromtimestamp(
                                pt_end.seconds, tz=timezone.utc
                            ).isoformat()
                        if latest_ts is None or pt_str > latest_ts:
                            latest_ts = pt_str
                if latest_ts is not None:
                    last_activity_timestamp = latest_ts

            except CerberusRetryExhausted:
                logger.warning(
                    "Monitoring retry exhausted for VM %s — treating as idle",
                    instance.name,
                )
                last_activity_timestamp = creation_ts

            results.append(
                {
                    "resource_id": instance.name,
                    "resource_type": "vm",
                    "region": region,
                    "creation_timestamp": creation_ts,
                    "last_activity_timestamp": last_activity_timestamp,
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
            )

    return results


def discover_orphaned_disks(project_id: str, credentials) -> list[dict]:
    disks_client = compute_v1.DisksClient(credentials=credentials)
    try:
        agg_list = gcp_call_with_retry(
            disks_client.aggregated_list,
            project=project_id,
        )
    except CerberusRetryExhausted:
        logger.error("Disk discovery: retry exhausted for project %s", project_id)
        return []

    results = []
    for _scope, scope_data in agg_list:
        disks = getattr(scope_data, "disks", None) or []
        for disk in disks:
            users = getattr(disk, "users", None)
            if users:
                continue  # attached — skip

            zone = (getattr(disk, "zone", "") or "").rsplit("/", 1)[-1]
            region = zone.rsplit("-", 1)[0] if zone else "unknown"
            creation_ts = disk.creation_timestamp
            labels = dict(getattr(disk, "labels", {}) or {})
            flagged = labels.get("data-classification") == "sensitive"

            results.append(
                {
                    "resource_id": disk.name,
                    "resource_type": "orphaned_disk",
                    "region": region,
                    "creation_timestamp": creation_ts,
                    "last_activity_timestamp": creation_ts,
                    "estimated_monthly_cost": None,
                    "ownership_status": None,
                    "owner_email": None,
                    "owner_iam_active": None,
                    "flagged_for_review": flagged,
                    "decision": None,
                    "reasoning": None,
                    "estimated_monthly_savings": None,
                    "outcome": None,
                }
            )
    return results


def discover_unused_ips(project_id: str, credentials) -> list[dict]:
    addresses_client = compute_v1.AddressesClient(credentials=credentials)
    try:
        agg_list = gcp_call_with_retry(
            addresses_client.aggregated_list,
            project=project_id,
        )
    except CerberusRetryExhausted:
        logger.error("IP discovery: retry exhausted for project %s", project_id)
        return []

    results = []
    for _scope, scope_data in agg_list:
        addresses = getattr(scope_data, "addresses", None) or []
        for address in addresses:
            if address.status != "RESERVED":
                continue
            users = getattr(address, "users", None)
            if users:
                continue  # in use — skip

            region_str = (getattr(address, "region", "") or "").rsplit("/", 1)[-1]
            region = region_str if region_str else "global"
            creation_ts = address.creation_timestamp

            results.append(
                {
                    "resource_id": address.name,
                    "resource_type": "unused_ip",
                    "region": region,
                    "creation_timestamp": creation_ts,
                    "last_activity_timestamp": creation_ts,
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
            )
    return results


def fetch_resource_costs(
    project_id: str,
    resource_ids: list[str],
    billing_account_id: str,
    credentials,
) -> dict[str, float]:
    try:
        client = billing_v1.CloudBillingClient(credentials=credentials)
        billing_info = gcp_call_with_retry(
            client.get_project_billing_info,
            name=f"projects/{project_id}",
        )
        if not billing_info.billing_enabled:
            logger.warning("Billing not enabled for project %s", project_id)
            return {}
        # Billing confirmed active. Per-resource spend requires BigQuery export
        # (not available in this API). Return 0.0 for all known resource IDs.
        return {rid: 0.0 for rid in resource_ids}
    except CerberusRetryExhausted:
        logger.error("Billing API retry exhausted for project %s", project_id)
        return {}
    except Exception as e:
        logger.error("Billing API failed for project %s: %s", project_id, e)
        return {}


def enrich_costs(resources: list[dict], cost_map: dict[str, float]) -> list[dict]:
    for resource in resources:
        rid = resource["resource_id"]
        if cost_map:
            resource["estimated_monthly_cost"] = cost_map.get(rid, 0.0)
        else:
            resource["estimated_monthly_cost"] = None
    return resources


async def scan_node(state: CerberusState) -> CerberusState:
    # Step 1 — Project guard (INV-SEC-01): must be first, before any GCP call
    try:
        validate_project_id(state["project_id"], get_config().allowed_project_pattern)
    except ValueError as e:
        state["error_message"] = str(e)
        return state

    config = get_config()
    credentials = _load_credentials(config.service_account_key_path)

    # Step 2 — Preflight count (lightweight list calls to know expected total)
    expected_count = 0
    try:
        vm_count = sum(
            len(getattr(zone_data, "instances", None) or [])
            for _, zone_data in gcp_call_with_retry(
                compute_v1.InstancesClient(credentials=credentials).aggregated_list,
                project=state["project_id"],
            )
        )
        disk_count = sum(
            len([d for d in (getattr(sd, "disks", None) or [])
                 if not getattr(d, "users", None)])
            for _, sd in gcp_call_with_retry(
                compute_v1.DisksClient(credentials=credentials).aggregated_list,
                project=state["project_id"],
            )
        )
        ip_count = sum(
            len([a for a in (getattr(sd, "addresses", None) or [])
                 if a.status == "RESERVED" and not getattr(a, "users", None)])
            for _, sd in gcp_call_with_retry(
                compute_v1.AddressesClient(credentials=credentials).aggregated_list,
                project=state["project_id"],
            )
        )
        expected_count = vm_count + disk_count + ip_count
    except Exception:
        expected_count = 0

    state["expected_resource_count"] = expected_count

    # Step 3 — Full discovery inside asyncio.wait_for (INV-NFR-01: 60s timeout)
    valid_resources: list[dict] = []

    async def _discover() -> list[dict]:
        vm_list, disk_list, ip_list = await asyncio.gather(
            asyncio.to_thread(discover_vms, state["project_id"], credentials),
            asyncio.to_thread(discover_orphaned_disks, state["project_id"], credentials),
            asyncio.to_thread(discover_unused_ips, state["project_id"], credentials),
        )
        all_resources = vm_list + disk_list + ip_list

        resource_ids = [r["resource_id"] for r in all_resources]
        cost_map = fetch_resource_costs(
            state["project_id"],
            resource_ids,
            config.billing_account_id,
            credentials,
        )
        all_resources = enrich_costs(all_resources, cost_map)

        valid: list[dict] = []
        for record in all_resources:
            try:
                valid.append(validate_resource_record(record))
            except ValueError as exc:
                logger.warning("Dropping invalid resource record: %s", exc)
        return valid

    discover_coro = _discover()
    try:
        valid_resources = await asyncio.wait_for(discover_coro, timeout=60.0)
        actual_count = len(valid_resources)
    except asyncio.TimeoutError:
        discover_coro.close()  # no-op on real cancellation; prevents warning when mocked
        actual_count = len(valid_resources)
        logger.warning(
            "scan_node timed out after 60s. Partial results: %d/%d resources discovered.",
            actual_count,
            expected_count,
        )
        # Step 5 — timeout handler: return partial results with warning
        state["error_message"] = (
            f"Partial scan: {actual_count}/{expected_count} resources discovered. "
            f"{expected_count - actual_count} could not be analysed. "
            f"Proceeding — re-run for full coverage."
        )
        state["resources"] = valid_resources
        return state

    # Step 4 — Completeness check
    if expected_count > 0 and actual_count < expected_count:
        missing = expected_count - actual_count
        state["error_message"] = (
            f"Partial scan: {actual_count}/{expected_count} resources discovered. "
            f"{missing} could not be analysed. "
            f"Proceeding — re-run for full coverage."
        )

    # Step 6 — Write state
    state["resources"] = valid_resources
    return state
