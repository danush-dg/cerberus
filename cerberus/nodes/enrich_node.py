from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from google.cloud import asset_v1, logging_v2, resourcemanager_v3
from google.oauth2 import service_account
from google.api_core.exceptions import Forbidden

from cerberus.config import get_config
from cerberus.state import CerberusState
from cerberus.tools.gcp_retry import gcp_call_with_retry, CerberusRetryExhausted

logger = logging.getLogger(__name__)

STALENESS_THRESHOLD_DAYS: int = 90


# ---------------------------------------------------------------------------
# Task 3.1 — Four-step ownership lookup chain (INV-ENR-01)
# ---------------------------------------------------------------------------

def lookup_by_labels(resource: dict) -> str | None:
    """Step 1: check resource labels for owner, created-by, team (in that order)."""
    labels = resource.get("labels")
    if not labels:
        return None
    for key in ("owner", "created-by", "team"):
        value = labels.get(key)
        if value:
            return value
    return None


def lookup_by_asset_inventory(
    resource_id: str,
    project_id: str,
    credentials: Any,
) -> str | None:
    """Step 2: Cloud Asset Inventory search for creator email."""
    def _search() -> str | None:
        client = asset_v1.AssetServiceClient(credentials=credentials)
        request = asset_v1.SearchAllResourcesRequest(
            scope=f"projects/{project_id}",
            query=resource_id,
            page_size=1,
        )
        for result in client.search_all_resources(request=request):
            annotations = getattr(result, "annotations", {}) or {}
            for key in ("creator", "created-by", "owner"):
                email = annotations.get(key)
                if email:
                    return email
            # also check additional_attributes if present
            additional = getattr(result, "additional_attributes", None)
            if additional:
                for key in ("creator", "created-by", "owner"):
                    email = additional.get(key)
                    if email:
                        return email
        return None

    try:
        return gcp_call_with_retry(_search)
    except (CerberusRetryExhausted, Forbidden) as e:
        logger.warning("lookup_by_asset_inventory failed (likely API disabled) for %s: %s", resource_id, e)
        return None


def lookup_by_iam_history(
    resource_id: str,
    project_id: str,
    credentials: Any,
) -> str | None:
    """Step 3: Cloud Audit Log — most recent setIamPolicy actor for this resource."""
    def _query() -> str | None:
        client = logging_v2.Client(project=project_id, credentials=credentials)
        log_filter = (
            f'protoPayload.resourceName:"{resource_id}" '
            f'protoPayload.methodName:"setIamPolicy"'
        )
        entries = client.list_entries(
            filter_=log_filter,
            order_by=logging_v2.DESCENDING,
            page_size=1,
        )
        for entry in entries:
            payload = entry.payload or {}
            auth_info = payload.get("authenticationInfo", {}) or {}
            email = auth_info.get("principalEmail")
            if email:
                return email
        return None

    try:
        return gcp_call_with_retry(_query)
    except (CerberusRetryExhausted, Forbidden) as e:
        logger.warning("lookup_by_iam_history failed (likely API disabled) for %s: %s", resource_id, e)
        return None


def lookup_by_audit_log(
    resource_id: str,
    project_id: str,
    credentials: Any,
) -> str | None:
    """Step 4: Cloud Audit Log — most recent mutation actor for this resource."""
    def _query() -> str | None:
        client = logging_v2.Client(project=project_id, credentials=credentials)
        log_filter = f'protoPayload.resourceName:"{resource_id}"'
        entries = client.list_entries(
            filter_=log_filter,
            order_by=logging_v2.DESCENDING,
            page_size=1,
        )
        for entry in entries:
            payload = entry.payload or {}
            auth_info = payload.get("authenticationInfo", {}) or {}
            email = auth_info.get("principalEmail")
            if email:
                return email
        return None

    try:
        return gcp_call_with_retry(_query)
    except (CerberusRetryExhausted, Forbidden) as e:
        logger.warning("lookup_by_audit_log failed (likely API disabled) for %s: %s", resource_id, e)
        return None


# ---------------------------------------------------------------------------
# Task 3.2 — IAM membership check and staleness downgrade (INV-ENR-02)
# ---------------------------------------------------------------------------

def check_iam_membership(email: str, project_id: str, credentials: Any) -> bool:
    """Return True if email holds any active IAM binding in the project."""
    def _get_policy() -> bool:
        client = resourcemanager_v3.ProjectsClient(credentials=credentials)
        policy = client.get_iam_policy(request={"resource": f"projects/{project_id}"})
        for binding in policy.bindings:
            if any(email in member for member in binding.members):
                return True
        return False

    try:
        return gcp_call_with_retry(_get_policy)
    except CerberusRetryExhausted as e:
        logger.warning("check_iam_membership failed for %s: %s", email, e)
        return False


def check_iam_last_activity(
    email: str,
    project_id: str,
    credentials: Any,
) -> datetime | None:
    """Return the timestamp of the most recent Cloud Audit Log event by this principal."""
    def _query() -> datetime | None:
        client = logging_v2.Client(project=project_id, credentials=credentials)
        log_filter = (
            f'protoPayload.authenticationInfo.principalEmail="{email}"'
        )
        entries = client.list_entries(
            filter_=log_filter,
            order_by=logging_v2.DESCENDING,
            page_size=1,
        )
        for entry in entries:
            ts = entry.timestamp
            if ts is not None:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return ts
        return None

    try:
        return gcp_call_with_retry(_query)
    except CerberusRetryExhausted as e:
        logger.warning("check_iam_last_activity failed for %s: %s", email, e)
        return None


def classify_ownership(
    resolved_email: str | None,
    project_id: str,
    credentials: Any,
) -> tuple[str, bool]:
    """Return (ownership_status, owner_iam_active) for a resolved email."""
    if resolved_email is None:
        return ("no_owner", False)

    in_iam = check_iam_membership(resolved_email, project_id, credentials)
    if not in_iam:
        return ("departed_owner", False)

    last_activity = check_iam_last_activity(resolved_email, project_id, credentials)
    if last_activity is not None:
        now = datetime.now(tz=timezone.utc)
        days_inactive = (now - last_activity).days
        if days_inactive > STALENESS_THRESHOLD_DAYS:
            logger.warning(
                "Owner %s in IAM but last activity %dd ago — downgraded",
                resolved_email,
                days_inactive,
            )
            return ("departed_owner", False)

    return ("active_owner", True)


def resolve_owner(
    resource: dict,
    project_id: str,
    credentials: Any,
) -> str | None:
    """Call the four lookup functions in priority order; return first non-None result."""
    result = lookup_by_labels(resource)
    if result is not None:
        return result

    resource_id = resource.get("resource_id", "")

    result = lookup_by_asset_inventory(resource_id, project_id, credentials)
    if result is not None:
        return result

    result = lookup_by_iam_history(resource_id, project_id, credentials)
    if result is not None:
        return result

    return lookup_by_audit_log(resource_id, project_id, credentials)


# ---------------------------------------------------------------------------
# Task 3.3 — enrich_node assembly (INV-ENR-01, INV-ENR-02, INV-ENR-03)
# ---------------------------------------------------------------------------

def _load_credentials(key_path: str):
    return service_account.Credentials.from_service_account_file(
        key_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


async def enrich_node(state: CerberusState) -> CerberusState:
    config = get_config()
    credentials = _load_credentials(config.service_account_key_path)
    project_id = state["project_id"]
    resources = state["resources"]

    for resource in resources:
        try:
            resolved_email = resolve_owner(resource, project_id, credentials)
            ownership_status, owner_iam_active = classify_ownership(
                resolved_email, project_id, credentials
            )
            resource["owner_email"] = resolved_email
            resource["ownership_status"] = ownership_status
            resource["owner_iam_active"] = owner_iam_active
            # Preserve any pre-existing True flag (e.g. sensitive disk from scan_node).
            resource["flagged_for_review"] = (
                resource.get("flagged_for_review", False) or (ownership_status == "no_owner")
            )
        except Exception as exc:
            logger.warning(
                "enrich_node: failed to enrich resource %s: %s",
                resource.get("resource_id", "unknown"),
                exc,
            )
            # Leave ownership_status=None; completeness guard will force to no_owner.

    # Completeness guard — no resource may exit with ownership_status=None.
    missing = [r for r in resources if r.get("ownership_status") is None]
    if missing:
        for r in missing:
            r["ownership_status"] = "no_owner"
            r["flagged_for_review"] = True
        count = len(resources) - len(missing)
        total = len(resources)
        state["error_message"] = (
            f"Enrichment incomplete: {count}/{total} resources enriched. "
            f"{len(missing)} forced to no_owner and flagged for review."
        )

    state["resources"] = resources
    return state
