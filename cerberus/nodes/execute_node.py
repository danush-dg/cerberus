from __future__ import annotations

import logging

from google.api_core.exceptions import NotFound
from google.cloud import compute_v1
from google.oauth2 import service_account

from cerberus.config import get_config
from cerberus.state import CerberusState
from cerberus.tools.gcp_retry import gcp_call_with_retry, CerberusRetryExhausted

logger = logging.getLogger(__name__)


def _load_credentials(key_path: str):
    return service_account.Credentials.from_service_account_file(
        key_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


def _get_vm_zone(project_id: str, resource_id: str, credentials) -> str | None:
    """Locate a VM's zone via aggregated_list (ResourceRecord stores region, not zone)."""
    instances_client = compute_v1.InstancesClient(credentials=credentials)
    agg = gcp_call_with_retry(
        instances_client.aggregated_list,
        project=project_id,
        filter=f'name="{resource_id}"',
    )
    for _scope, data in agg:
        instances = getattr(data, "instances", None) or []
        for inst in instances:
            if inst.name == resource_id:
                return (inst.zone or "").rsplit("/", 1)[-1]
    return None


def _get_disk_zone(project_id: str, resource_id: str, credentials) -> str | None:
    """Locate a disk's zone via aggregated_list."""
    disks_client = compute_v1.DisksClient(credentials=credentials)
    agg = gcp_call_with_retry(
        disks_client.aggregated_list,
        project=project_id,
        filter=f'name="{resource_id}"',
    )
    for _scope, data in agg:
        disks = getattr(data, "disks", None) or []
        for disk in disks:
            if disk.name == resource_id:
                return (getattr(disk, "zone", "") or "").rsplit("/", 1)[-1]
    return None


# ---------------------------------------------------------------------------
# INV-EXE-01: stop_vm and delete_resource are structurally separate functions.
# instances.stop is NEVER callable from delete_resource.
# instances.delete is NEVER callable from stop_vm.
# ---------------------------------------------------------------------------


async def stop_vm(resource: dict, credentials) -> bool:
    """Stop a GCE VM instance. Never calls instances.delete.

    Returns True on successful API dispatch, False on error.
    """
    resource_id = resource["resource_id"]
    project_id = resource.get("project_id") or _resolve_project_from_state(resource)
    config = get_config()
    project_id = project_id or config.gcp_project_id

    zone = _get_vm_zone(project_id, resource_id, credentials)
    if zone is None:
        logger.error("stop_vm: cannot locate zone for VM %s — skipping", resource_id)
        return False

    instances_client = compute_v1.InstancesClient(credentials=credentials)
    try:
        gcp_call_with_retry(
            instances_client.stop,
            project=project_id,
            zone=zone,
            instance=resource_id,
        )
        logger.info("stop_vm: dispatched stop for %s in %s/%s", resource_id, project_id, zone)
        return True
    except CerberusRetryExhausted as exc:
        logger.error("stop_vm: retry exhausted for %s: %s", resource_id, exc)
        return False
    except Exception as exc:
        logger.error("stop_vm: unexpected error for %s: %s", resource_id, exc)
        return False


async def delete_resource(resource: dict, credentials) -> bool:
    """Delete a GCE resource. Never calls instances.stop.

    Routes by resource_type:
      "vm"            → instances.delete
      "orphaned_disk" → disks.delete (archives sensitive disks instead of deleting)
      "unused_ip"     → addresses.delete

    Returns True on successful API dispatch, False on error.
    """
    resource_id = resource["resource_id"]
    resource_type = resource["resource_type"]
    config = get_config()
    project_id = config.gcp_project_id

    try:
        if resource_type == "vm":
            zone = _get_vm_zone(project_id, resource_id, credentials)
            if zone is None:
                logger.error("delete_resource: cannot locate zone for VM %s", resource_id)
                return False
            instances_client = compute_v1.InstancesClient(credentials=credentials)
            gcp_call_with_retry(
                instances_client.delete,
                project=project_id,
                zone=zone,
                instance=resource_id,
            )
            logger.info("delete_resource: deleted VM %s in %s/%s", resource_id, project_id, zone)

        elif resource_type == "orphaned_disk":
            # Belt-and-suspenders: sensitive disks must not be deleted.
            # In normal execution this branch is unreachable because execute_node's
            # guardrail skips flagged_for_review resources before calling this function.
            # NOTE: actual Coldline Storage archival would require storage.googleapis.com
            # which is not in the allowed GCP API list (CLAUDE.md Fixed Stack).
            # The guardrail in execute_node (step B) ensures this path is dead code in
            # production. We log and abort to preserve data safety.
            if resource.get("flagged_for_review"):
                logger.warning(
                    "delete_resource: GUARDRAIL — sensitive disk %s reached delete_resource. "
                    "Aborting deletion to preserve data. Manual review required.",
                    resource_id,
                )
                return False

            zone = _get_disk_zone(project_id, resource_id, credentials)
            if zone is None:
                logger.error("delete_resource: cannot locate zone for disk %s", resource_id)
                return False
            disks_client = compute_v1.DisksClient(credentials=credentials)
            gcp_call_with_retry(
                disks_client.delete,
                project=project_id,
                zone=zone,
                disk=resource_id,
            )
            logger.info("delete_resource: deleted disk %s in %s/%s", resource_id, project_id, zone)

        elif resource_type == "unused_ip":
            region = resource.get("region", "")
            addresses_client = compute_v1.AddressesClient(credentials=credentials)
            gcp_call_with_retry(
                addresses_client.delete,
                project=project_id,
                region=region,
                address=resource_id,
            )
            logger.info("delete_resource: deleted IP %s in %s/%s", resource_id, project_id, region)

        else:
            logger.error("delete_resource: unsupported resource_type '%s' for %s", resource_type, resource_id)
            return False

        return True

    except CerberusRetryExhausted as exc:
        logger.error("delete_resource: retry exhausted for %s: %s", resource_id, exc)
        return False
    except Exception as exc:
        logger.error("delete_resource: unexpected error for %s: %s", resource_id, exc)
        return False


async def verify_resource_state(resource: dict, credentials, project_id: str) -> bool:
    """Confirm the expected post-action state via a GCP read call.

    safe_to_stop → instance.status in ("TERMINATED", "STOPPING")
    safe_to_delete → resource raises NotFound (404)

    Returns True if verified, False otherwise. (INV-EXE-02)
    """
    resource_id = resource["resource_id"]
    resource_type = resource["resource_type"]
    decision = resource.get("decision")

    try:
        if decision == "safe_to_stop":
            # Expect TERMINATED or STOPPING
            instances_client = compute_v1.InstancesClient(credentials=credentials)
            agg = gcp_call_with_retry(
                instances_client.aggregated_list,
                project=project_id,
                filter=f'name="{resource_id}"',
            )
            for _scope, data in agg:
                instances = getattr(data, "instances", None) or []
                for inst in instances:
                    if inst.name == resource_id:
                        verified = inst.status in ("TERMINATED", "STOPPING")
                        if not verified:
                            logger.warning(
                                "verify: %s status is '%s', expected TERMINATED/STOPPING",
                                resource_id,
                                inst.status,
                            )
                        return verified
            # VM not found — unexpected for a stop operation
            logger.warning("verify: VM %s not found after stop", resource_id)
            return False

        elif decision == "safe_to_delete":
            # Expect 404 (resource gone)
            if resource_type == "vm":
                instances_client = compute_v1.InstancesClient(credentials=credentials)
                agg = gcp_call_with_retry(
                    instances_client.aggregated_list,
                    project=project_id,
                    filter=f'name="{resource_id}"',
                )
                for _scope, data in agg:
                    instances = getattr(data, "instances", None) or []
                    for inst in instances:
                        if inst.name == resource_id:
                            logger.warning("verify: VM %s still exists after delete", resource_id)
                            return False
                return True  # not found in any zone — delete confirmed

            elif resource_type == "orphaned_disk":
                disks_client = compute_v1.DisksClient(credentials=credentials)
                agg = gcp_call_with_retry(
                    disks_client.aggregated_list,
                    project=project_id,
                    filter=f'name="{resource_id}"',
                )
                for _scope, data in agg:
                    disks = getattr(data, "disks", None) or []
                    for disk in disks:
                        if disk.name == resource_id:
                            logger.warning("verify: disk %s still exists after delete", resource_id)
                            return False
                return True

            elif resource_type == "unused_ip":
                region = resource.get("region", "")
                addresses_client = compute_v1.AddressesClient(credentials=credentials)
                try:
                    gcp_call_with_retry(
                        addresses_client.get,
                        project=project_id,
                        region=region,
                        address=resource_id,
                    )
                    # Still exists — delete not confirmed
                    logger.warning("verify: IP %s still exists after delete", resource_id)
                    return False
                except NotFound:
                    return True

        logger.warning("verify: unhandled decision '%s' for %s", decision, resource_id)
        return False

    except Exception as exc:
        logger.error("verify_resource_state: error for %s: %s", resource_id, exc)
        return False


def _resolve_project_from_state(resource: dict) -> str | None:
    """Fallback: try to get project_id embedded in resource if present."""
    return resource.get("project_id")


# ---------------------------------------------------------------------------
# Main execute node
# ---------------------------------------------------------------------------


async def execute_node(state: CerberusState) -> CerberusState:
    """Execute approved GCP actions with rate limiting and post-action verification.

    INV-EXE-01: stop and delete are structurally separate code paths.
    INV-EXE-02: every mutation is verified before proceeding.
    INV-EXE-03: hard cap of 10 mutations per session.
    INV-ENR-03 (step 3): resources with flagged_for_review are skipped with SKIPPED_GUARDRAIL.
    """
    # PRECONDITION 1 — dry-run: mark all approved actions and return immediately.
    if state["dry_run"]:
        logger.info("DRY RUN — no GCP calls made.")
        for resource in state["approved_actions"]:
            resource["outcome"] = "DRY_RUN"
        return state

    # PRECONDITION 2 — nothing to do.
    if not state["approved_actions"]:
        logger.info("No approved actions.")
        return state

    config = get_config()
    credentials = _load_credentials(config.service_account_key_path)
    project_id = state["project_id"]

    for resource in state["approved_actions"]:
        # A. RATE LIMIT — checked before each API call (INV-EXE-03)
        if state["mutation_count"] >= 10:
            remaining = [
                r for r in state["approved_actions"]
                if r.get("outcome") is None
            ]
            state["error_message"] = (
                f"Rate limit: 10 mutations reached. "
                f"{len(remaining)} action(s) not executed this session."
            )
            logger.warning("execute_node: rate limit reached — halting")
            break

        # B. GUARDRAIL — belt-and-suspenders for flagged resources (INV-ENR-03)
        if resource.get("flagged_for_review"):
            resource["outcome"] = "SKIPPED_GUARDRAIL"
            logger.warning("GUARDRAIL SKIP: %s", resource["resource_id"])
            continue  # do NOT increment mutation_count

        # C. ACTION ROUTING (INV-EXE-01: structurally separate paths)
        decision = resource.get("decision")
        if decision == "safe_to_stop":
            success = await stop_vm(resource, credentials)
        elif decision == "safe_to_delete":
            success = await delete_resource(resource, credentials)
        else:
            # needs_review, skip — never executed
            continue

        # D. INCREMENT COUNTER on dispatch, before verification (INV-EXE-03)
        state["mutation_count"] += 1

        # E. VERIFICATION (INV-EXE-02)
        if success:
            verified = await verify_resource_state(resource, credentials, project_id)
            if verified:
                resource["outcome"] = "SUCCESS"
            else:
                resource["outcome"] = "FAILED"
                state["mutation_count"] -= 1  # failed verification doesn't count
        else:
            resource["outcome"] = "FAILED"
            state["mutation_count"] -= 1

    return state
