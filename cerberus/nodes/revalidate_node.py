from __future__ import annotations

import logging

from google.api_core.exceptions import NotFound
from google.cloud import compute_v1
from google.oauth2 import service_account

from cerberus.config import get_config
from cerberus.state import CerberusState
from cerberus.tools.gcp_retry import gcp_call_with_retry

logger = logging.getLogger(__name__)


def _load_credentials(key_path: str):
    return service_account.Credentials.from_service_account_file(
        key_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


def _check_vm(resource: dict, project_id: str, credentials) -> tuple[bool, bool]:
    """Return (exists=True, drifted) or raise NotFound.

    Drifted means the VM is now RUNNING (was expected idle/stopped).
    Uses aggregated_list with name filter because the ResourceRecord only
    stores region, not the full zone required by InstancesClient.get().
    """
    instances_client = compute_v1.InstancesClient(credentials=credentials)
    agg = gcp_call_with_retry(
        instances_client.aggregated_list,
        project=project_id,
        filter=f'name="{resource["resource_id"]}"',
    )
    for _scope, data in agg:
        instances = getattr(data, "instances", None) or []
        for inst in instances:
            if inst.name == resource["resource_id"]:
                drifted = inst.status == "RUNNING"
                return True, drifted
    raise NotFound(f"VM {resource['resource_id']} not found in project {project_id}")


def _check_disk(resource: dict, project_id: str, credentials) -> tuple[bool, bool]:
    """Return (exists=True, drifted) or raise NotFound.

    Drifted means the disk now has attached users (was expected unattached).
    """
    disks_client = compute_v1.DisksClient(credentials=credentials)
    agg = gcp_call_with_retry(
        disks_client.aggregated_list,
        project=project_id,
        filter=f'name="{resource["resource_id"]}"',
    )
    for _scope, data in agg:
        disks = getattr(data, "disks", None) or []
        for disk in disks:
            if disk.name == resource["resource_id"]:
                users = getattr(disk, "users", None)
                drifted = bool(users)
                return True, drifted
    raise NotFound(f"Disk {resource['resource_id']} not found in project {project_id}")


def _check_ip(resource: dict, project_id: str, credentials) -> tuple[bool, bool]:
    """Return (exists=True, drifted) or raise NotFound.

    Drifted means the IP is now IN_USE (was expected RESERVED/idle).
    """
    addresses_client = compute_v1.AddressesClient(credentials=credentials)
    agg = gcp_call_with_retry(
        addresses_client.aggregated_list,
        project=project_id,
        filter=f'name="{resource["resource_id"]}"',
    )
    for _scope, data in agg:
        addresses = getattr(data, "addresses", None) or []
        for addr in addresses:
            if addr.name == resource["resource_id"]:
                drifted = addr.status == "IN_USE"
                return True, drifted
    raise NotFound(f"IP {resource['resource_id']} not found in project {project_id}")


async def revalidate_node(state: CerberusState) -> CerberusState:
    """Re-fetch each approved resource from GCP and remove any that have drifted.

    CASE 1 — NotFound (404): silently remove, no error_message.
    CASE 2 — Drift detected: downgrade decision to "needs_review", remove from
              approved_actions, and set error_message.
    CASE 3 — No change: resource remains in approved_actions.
    """
    config = get_config()
    credentials = _load_credentials(config.service_account_key_path)
    project_id = state["project_id"]

    original_approved = list(state["approved_actions"])
    to_remove: set[str] = set()
    drifted: list[dict] = []

    for resource in original_approved:
        resource_id = resource["resource_id"]
        resource_type = resource["resource_type"]

        try:
            if resource_type == "vm":
                _exists, is_drifted = _check_vm(resource, project_id, credentials)
            elif resource_type == "orphaned_disk":
                _exists, is_drifted = _check_disk(resource, project_id, credentials)
            elif resource_type == "unused_ip":
                _exists, is_drifted = _check_ip(resource, project_id, credentials)
            else:
                logger.warning(
                    "revalidate_node: unknown resource_type '%s' for %s — skipping",
                    resource_type,
                    resource_id,
                )
                continue

            if is_drifted:
                logger.warning(
                    "%s drifted since approval — downgrading to needs_review",
                    resource_id,
                )
                # Downgrade in state["resources"] (single source of truth)
                for r in state["resources"]:
                    if r["resource_id"] == resource_id:
                        r["decision"] = "needs_review"
                        break
                drifted.append(resource)
                to_remove.add(resource_id)

        except NotFound:
            # CASE 1: resource gone — remove silently, do NOT set error_message
            logger.info("%s no longer exists — removed from plan.", resource_id)
            to_remove.add(resource_id)

    # Rebuild approved_actions excluding 404'd and drifted resources
    state["approved_actions"] = [
        r for r in original_approved if r["resource_id"] not in to_remove
    ]

    drifted_count = len(drifted)
    original_count = len(original_approved)

    if 0 < drifted_count < original_count:
        remaining = len(state["approved_actions"])
        state["error_message"] = (
            f"{drifted_count} resource(s) changed state since approval and were removed. "
            f"Remaining {remaining} actions will proceed."
        )
    elif drifted_count == original_count:
        state["approved_actions"] = []
        state["error_message"] = (
            "All approved resources changed state — execution cancelled. "
            "Re-run scan for current state."
        )

    return state
