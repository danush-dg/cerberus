from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from google.cloud import compute_v1, monitoring_v3, billing_v1
from google.oauth2 import service_account
from google.protobuf import duration_pb2

from cerberus.state import CerberusState, validate_resource_record, push_trace_event
from cerberus.config import get_config, validate_project_id
from cerberus.tools.gcp_retry import gcp_call_with_retry, CerberusRetryExhausted

logger = logging.getLogger(__name__)

CPU_IDLE_THRESHOLD: float = 0.05
CPU_IDLE_WINDOW_HOURS: int = 72
HOURS_PER_MONTH: float = 730.0
COMPUTE_SERVICE_ID: str = "6F81-5844-456A"

# vCPUs and memory (GB) for common GCP machine types — avoids per-VM API calls.
# Unknown types fall back to MachineTypesClient.get.
_MACHINE_SPECS: dict[str, tuple[int, float]] = {
    # N1 standard
    "n1-standard-1": (1, 3.75),    "n1-standard-2": (2, 7.5),    "n1-standard-4": (4, 15.0),
    "n1-standard-8": (8, 30.0),    "n1-standard-16": (16, 60.0), "n1-standard-32": (32, 120.0),
    "n1-standard-64": (64, 240.0), "n1-standard-96": (96, 360.0),
    # N1 highmem / highcpu
    "n1-highmem-2": (2, 13.0),     "n1-highmem-4": (4, 26.0),   "n1-highmem-8": (8, 52.0),
    "n1-highmem-16": (16, 104.0),  "n1-highmem-32": (32, 208.0), "n1-highmem-64": (64, 416.0),
    "n1-highcpu-4": (4, 3.6),      "n1-highcpu-8": (8, 7.2),    "n1-highcpu-16": (16, 14.4),
    "n1-highcpu-32": (32, 28.8),   "n1-highcpu-64": (64, 57.6),
    # N2 standard / highmem
    "n2-standard-2": (2, 8.0),     "n2-standard-4": (4, 16.0),  "n2-standard-8": (8, 32.0),
    "n2-standard-16": (16, 64.0),  "n2-standard-32": (32, 128.0), "n2-standard-48": (48, 192.0),
    "n2-standard-64": (64, 256.0), "n2-standard-80": (80, 320.0),
    "n2-highmem-2": (2, 16.0),     "n2-highmem-4": (4, 32.0),   "n2-highmem-8": (8, 64.0),
    "n2-highmem-16": (16, 128.0),  "n2-highmem-32": (32, 256.0), "n2-highmem-48": (48, 384.0),
    "n2-highmem-64": (64, 512.0),
    # E2
    "e2-standard-2": (2, 8.0),     "e2-standard-4": (4, 16.0),  "e2-standard-8": (8, 32.0),
    "e2-standard-16": (16, 64.0),  "e2-standard-32": (32, 128.0),
    "e2-highmem-2": (2, 16.0),     "e2-highmem-4": (4, 32.0),   "e2-highmem-8": (8, 64.0),
    "e2-highmem-16": (16, 128.0),
    "e2-highcpu-2": (2, 2.0),      "e2-highcpu-4": (4, 4.0),    "e2-highcpu-8": (8, 8.0),
    "e2-highcpu-16": (16, 16.0),   "e2-highcpu-32": (32, 32.0),
    "e2-micro": (2, 1.0),          "e2-small": (2, 2.0),         "e2-medium": (2, 4.0),
    # Shared-core
    "f1-micro": (1, 0.6),          "g1-small": (1, 1.7),
    # N2D
    "n2d-standard-2": (2, 8.0),    "n2d-standard-4": (4, 16.0), "n2d-standard-8": (8, 32.0),
    "n2d-standard-16": (16, 64.0), "n2d-standard-32": (32, 128.0),
    # C2
    "c2-standard-4": (4, 16.0),    "c2-standard-8": (8, 32.0),  "c2-standard-16": (16, 64.0),
    "c2-standard-30": (30, 120.0), "c2-standard-60": (60, 240.0),
}


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

            mt_name = (instance.machine_type or "").rsplit("/", 1)[-1]
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
                    "_machine_type": mt_name,
                    "_zone": zone,
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

            disk_type_name = (getattr(disk, "type", "") or "").rsplit("/", 1)[-1]
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
                    "_disk_size_gb": int(getattr(disk, "size_gb", 0) or 0),
                    "_disk_type": disk_type_name,
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


def _sku_unit_price_usd(sku) -> float:
    """Return the lowest-tier unit price in USD from a billing SKU."""
    for pi in sku.pricing_info:
        for rate in pi.pricing_expression.tiered_rates:
            if rate.start_usage_amount == 0:
                m = rate.unit_price
                return float(m.units) + float(m.nanos) / 1_000_000_000
    return 0.0


def _fetch_compute_pricing(
    catalog_client, regions: set[str]
) -> dict[str, dict[str, float]]:
    """Fetch Compute Engine SKU pricing from Cloud Catalog for the given regions.

    CPU/RAM prices: USD per vCPU-hour or per GB-hour.
    Disk prices: USD per GB-month.
    Static IP prices: USD per IP-hour.
    """
    pricing: dict[str, dict[str, float]] = {
        "n1_cpu": {}, "n1_ram": {},
        "n2_cpu": {}, "n2_ram": {},
        "n2d_cpu": {}, "n2d_ram": {},
        "e2_cpu": {}, "e2_ram": {},
        "c2_cpu": {}, "c2_ram": {},
        "pd_standard": {}, "pd_ssd": {},
        "f1_micro": {}, "g1_small": {},
        "static_ip": {},
    }
    try:
        skus = gcp_call_with_retry(
            catalog_client.list_skus,
            parent=f"services/{COMPUTE_SERVICE_ID}",
        )
        for sku in skus:
            cat = sku.category
            if cat.usage_type not in ("OnDemand", ""):
                continue
            sku_regions = set(sku.service_regions)
            relevant = regions if "global" in sku_regions else (regions & sku_regions)
            if not relevant:
                continue
            price = _sku_unit_price_usd(sku)
            if price <= 0.0:
                continue
            desc = sku.description.lower()

            if cat.resource_family == "Compute" and cat.resource_group == "CPU":
                for family in ("n1", "n2d", "n2", "e2", "c2"):
                    if desc.startswith(f"{family} "):
                        d = pricing[f"{family}_cpu"]
                        for r in relevant:
                            d.setdefault(r, price)
                        break
            elif cat.resource_family == "Compute" and cat.resource_group == "RAM":
                for family in ("n1", "n2d", "n2", "e2", "c2"):
                    if desc.startswith(f"{family} "):
                        d = pricing[f"{family}_ram"]
                        for r in relevant:
                            d.setdefault(r, price)
                        break
            elif cat.resource_family == "Compute" and "micro instance" in desc:
                for r in relevant:
                    pricing["f1_micro"].setdefault(r, price)
            elif cat.resource_family == "Compute" and "small instance" in desc:
                for r in relevant:
                    pricing["g1_small"].setdefault(r, price)
            elif cat.resource_family == "Storage" and "storage pd capacity" in desc and "ssd" not in desc:
                for r in relevant:
                    pricing["pd_standard"].setdefault(r, price)
            elif cat.resource_family == "Storage" and "ssd backed pd" in desc:
                for r in relevant:
                    pricing["pd_ssd"].setdefault(r, price)
            elif "static ip" in desc:
                for r in relevant:
                    pricing["static_ip"].setdefault(r, price)
    except Exception as e:
        logger.warning("CloudCatalog SKU fetch partial/failed: %s", e)
    return pricing


def _machine_vcpus_memory(
    machine_type: str, zone: str, project_id: str, credentials
) -> tuple[int, float] | None:
    """Return (vcpus, memory_gb) for a machine type. Lookup table first, API fallback."""
    specs = _MACHINE_SPECS.get(machine_type)
    if specs:
        return specs
    try:
        client = compute_v1.MachineTypesClient(credentials=credentials)
        mt = gcp_call_with_retry(
            client.get, project=project_id, zone=zone, machine_type=machine_type
        )
        return mt.guest_cpus, mt.memory_mb / 1024.0
    except Exception as exc:
        logger.warning("Cannot resolve machine type specs for %s: %s", machine_type, exc)
        return None


def _estimate_vm_cost(
    resource: dict,
    pricing: dict[str, dict[str, float]],
    project_id: str,
    credentials,
) -> float | None:
    """Estimate monthly on-demand cost for a VM from SKU pricing × machine specs."""
    machine_type = resource.get("_machine_type", "")
    zone = resource.get("_zone", "")
    region = resource.get("region", "")
    if not machine_type:
        return None

    prefix = machine_type.split("-")[0].lower()

    if prefix == "f1":
        price = pricing["f1_micro"].get(region)
        return round(price * HOURS_PER_MONTH, 4) if price else None
    if prefix == "g1":
        price = pricing["g1_small"].get(region)
        return round(price * HOURS_PER_MONTH, 4) if price else None

    specs = _machine_vcpus_memory(machine_type, zone, project_id, credentials)
    if not specs:
        return None
    vcpus, memory_gb = specs

    cpu_price = pricing.get(f"{prefix}_cpu", {}).get(region) or pricing["n1_cpu"].get(region)
    ram_price = pricing.get(f"{prefix}_ram", {}).get(region) or pricing["n1_ram"].get(region)
    if not cpu_price or not ram_price:
        return None

    return round((vcpus * cpu_price + memory_gb * ram_price) * HOURS_PER_MONTH, 4)


def _estimate_disk_cost(
    resource: dict, pricing: dict[str, dict[str, float]]
) -> float | None:
    """Estimate monthly cost for an orphaned disk (price is already per GB-month)."""
    size_gb = resource.get("_disk_size_gb") or 0
    disk_type = (resource.get("_disk_type") or "pd-standard").lower()
    region = resource.get("region", "")
    if not size_gb:
        return None
    price_key = "pd_ssd" if "ssd" in disk_type else "pd_standard"
    price_per_gb = pricing[price_key].get(region)
    if not price_per_gb:
        return None
    return round(size_gb * price_per_gb, 4)


def _estimate_ip_cost(
    resource: dict, pricing: dict[str, dict[str, float]]
) -> float | None:
    """Estimate monthly cost for an unused static IP."""
    region = resource.get("region", "")
    price_per_hour = pricing["static_ip"].get(region)
    if not price_per_hour:
        return None
    return round(price_per_hour * HOURS_PER_MONTH, 4)


def fetch_resource_costs(
    project_id: str,
    resources: list[dict],
    billing_account_id: str,
    credentials,
) -> dict[str, float]:
    """Estimate monthly costs per resource using Cloud Billing SKU pricing.

    Confirms billing is active, fetches Compute Engine SKU prices via
    CloudCatalogClient, then estimates cost from resource specs × published
    on-demand prices. Returns {} on any billing API failure so callers treat
    missing entries as None (INV-SCAN-04).
    """
    try:
        billing_client = billing_v1.CloudBillingClient(credentials=credentials)
        billing_info = gcp_call_with_retry(
            billing_client.get_project_billing_info,
            name=f"projects/{project_id}",
        )
        if not billing_info.billing_enabled:
            logger.warning("Billing not enabled for project %s", project_id)
            return {}

        catalog_client = billing_v1.CloudCatalogClient(credentials=credentials)
        regions = {r.get("region") for r in resources if r.get("region")}
        pricing = _fetch_compute_pricing(catalog_client, regions)

        cost_map: dict[str, float] = {}
        for resource in resources:
            rid = resource["resource_id"]
            rtype = resource.get("resource_type")
            if rtype == "vm":
                cost = _estimate_vm_cost(resource, pricing, project_id, credentials)
            elif rtype == "orphaned_disk":
                cost = _estimate_disk_cost(resource, pricing)
            elif rtype == "unused_ip":
                cost = _estimate_ip_cost(resource, pricing)
            else:
                cost = None
            if cost is not None:
                cost_map[rid] = cost

        logger.info(
            "Billing estimates: %d/%d resources priced for project %s",
            len(cost_map), len(resources), project_id,
        )
        return cost_map

    except CerberusRetryExhausted:
        logger.error("Billing API retry exhausted for project %s", project_id)
        return {}
    except Exception as e:
        logger.error("Billing API failed for project %s: %s", project_id, e)
        return {}


def enrich_costs(resources: list[dict], cost_map: dict[str, float]) -> list[dict]:
    """Apply cost estimates to resources. Missing entries stay None (INV-SCAN-04)."""
    for resource in resources:
        resource["estimated_monthly_cost"] = cost_map.get(resource["resource_id"])
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

    _run_id = state["run_id"]

    async def _discover() -> list[dict]:
        push_trace_event(_run_id, {
            "type": "scan_progress",
            "node": "scan_node",
            "icon": "📡",
            "color": "#1f77b4",
            "ts": datetime.now(timezone.utc).isoformat(),
            "message": "Scanning GCE instances, orphaned disks, and unused IPs in parallel…",
        })

        vm_list, disk_list, ip_list = await asyncio.gather(
            asyncio.to_thread(discover_vms, state["project_id"], credentials),
            asyncio.to_thread(discover_orphaned_disks, state["project_id"], credentials),
            asyncio.to_thread(discover_unused_ips, state["project_id"], credentials),
        )
        all_resources = vm_list + disk_list + ip_list

        push_trace_event(_run_id, {
            "type": "scan_progress",
            "node": "scan_node",
            "icon": "📡",
            "color": "#1f77b4",
            "ts": datetime.now(timezone.utc).isoformat(),
            "message": f"Discovery complete — {len(vm_list)} VM(s) · {len(disk_list)} orphaned disk(s) · {len(ip_list)} unused IP(s)",
        })

        push_trace_event(_run_id, {
            "type": "scan_progress",
            "node": "scan_node",
            "icon": "💰",
            "color": "#1f77b4",
            "ts": datetime.now(timezone.utc).isoformat(),
            "message": f"Fetching billing data for {len(all_resources)} resource(s)…",
        })

        cost_map = fetch_resource_costs(
            state["project_id"],
            all_resources,
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
