from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from cerberus.heads.iam_head import get_iam_inventory
from cerberus.models.security_flag import BudgetStatus, SecurityFlag
from cerberus.nodes.audit_node import AuditEntry, write_audit_entry
from cerberus.nodes.enrich_node import check_iam_last_activity
from cerberus.tools.chroma_client import query_project_history

logger = logging.getLogger(__name__)

OVER_PERMISSION_INACTIVITY_DAYS: int = 30
BUDGET_ALERT_THRESHOLD_DEFAULT: float = 500.0


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _sentinel_run_id() -> str:
    return f"security-{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%S')}"


def _get_gcp_budget_threshold(billing_account_id: str, credentials) -> float | None:
    """Fetch the largest configured GCP budget threshold for the billing account.

    Uses Cloud Billing Budgets API. Returns None if no budgets found or on error.
    INV-COST-02 does not apply here — this is security_head.py, not cost_head.py.
    """
    try:
        from google.cloud.billing import budgets_v1
        client = budgets_v1.BudgetServiceClient(credentials=credentials)
        budgets = list(client.list_budgets(parent=f"billingAccounts/{billing_account_id}"))
        if not budgets:
            return None
        max_threshold = 0.0
        for budget in budgets:
            amount = getattr(budget, "amount", None)
            if amount is None:
                continue
            specified = getattr(amount, "specified_amount", None)
            if specified is None:
                continue
            units = int(getattr(specified, "units", 0) or 0)
            nanos = int(getattr(specified, "nanos", 0) or 0)
            threshold = units + nanos / 1e9
            if threshold > max_threshold:
                max_threshold = threshold
        return max_threshold if max_threshold > 0 else None
    except Exception as exc:
        logger.debug("_get_gcp_budget_threshold skipped: %s", exc)
        return None


async def check_budget_status(project_id: str) -> BudgetStatus:
    """Query ChromaDB for project cost and compare to configured threshold.

    INV-COST-02: no Cloud Billing API call in cost_head.py — ChromaDB only there.
    security_head.py IS permitted to call the GCP Budget API (different module).
    """
    records = query_project_history(project_id)
    total = sum(float(r.get("estimated_monthly_cost") or 0.0) for r in records)

    # Try to fetch real GCP budget threshold from Cloud Billing Budgets API.
    live_threshold: float | None = None
    try:
        from cerberus.config import get_config
        from google.oauth2 import service_account as _sa
        cfg = get_config()
        _creds = _sa.Credentials.from_service_account_file(
            cfg.service_account_key_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        live_threshold = _get_gcp_budget_threshold(cfg.billing_account_id, _creds)
    except Exception as exc:
        logger.debug("live budget fetch skipped (config/creds unavailable): %s", exc)

    # Effective threshold: live GCP budget > config threshold > hardcoded default.
    try:
        from cerberus.config import get_config as _gc
        _cfg = _gc()
        config_threshold = _cfg.budget_thresholds.get(project_id, BUDGET_ALERT_THRESHOLD_DEFAULT)
    except Exception:
        config_threshold = BUDGET_ALERT_THRESHOLD_DEFAULT

    threshold = live_threshold if live_threshold is not None else config_threshold

    percent = round((total / threshold) * 100, 1) if threshold > 0 else 0.0
    return BudgetStatus(
        project_id=project_id,
        current_month_usd=round(total, 4),
        threshold_usd=threshold,
        breached=total > threshold,
        percent_used=percent,
        live_budget_threshold_usd=live_threshold,
    )


async def get_security_flags(project_id: str, credentials) -> list[SecurityFlag]:
    """Run three security checks and return combined SecurityFlag list.

    INV-SEC2-01: OVER_PERMISSIONED requires BOTH role AND inactivity conditions.
    INV-SEC2-02: BUDGET_BREACH flags are written to JSONL audit log.
    """
    flags: list[SecurityFlag] = []
    now = datetime.now(tz=timezone.utc)
    log_dir = os.environ.get("AUDIT_LOG_DIR", "./logs")
    run_id = _sentinel_run_id()

    # CHECK 1 — OVER_PERMISSIONED
    try:
        bindings = await get_iam_inventory(project_id, credentials)
        for binding in bindings:
            role = binding.role or ""
            identity = binding.identity or ""
            if role not in ("roles/owner", "roles/editor"):
                continue
            last_activity = check_iam_last_activity(identity, project_id, credentials)
            if last_activity is not None and last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            if last_activity is None:
                days = OVER_PERMISSION_INACTIVITY_DAYS + 1  # treat unknown as stale
                detail = f"{identity} holds {role} but has no recorded IAM activity"
            else:
                days = (now - last_activity).days
                if days <= OVER_PERMISSION_INACTIVITY_DAYS:
                    continue  # INV-SEC2-01: both conditions must be true
                detail = f"{identity} holds {role} but inactive for {days} days"

            flags.append(SecurityFlag(
                flag_id=str(uuid.uuid4()),
                flag_type="OVER_PERMISSIONED",
                identity_or_resource=identity,
                project_id=project_id,
                detected_at=_now_iso(),
                detail=detail,
            ))
    except Exception as exc:
        logger.warning("CHECK 1 (OVER_PERMISSIONED) failed for %s: %s", project_id, exc)

    # CHECK 2 — GHOST_RESOURCE (idle resources from ChromaDB)
    try:
        records = query_project_history(project_id)
        for rec in records:
            decision = rec.get("decision") or ""
            if decision not in ("safe_to_stop", "safe_to_delete"):
                continue
            resource_id = rec.get("resource_id") or "unknown"
            resource_type = rec.get("resource_type") or "unknown"
            cost_usd = round(float(rec.get("estimated_monthly_cost") or 0.0), 2)
            flags.append(SecurityFlag(
                flag_id=str(uuid.uuid4()),
                flag_type="GHOST_RESOURCE",
                identity_or_resource=resource_id,
                project_id=project_id,
                detected_at=_now_iso(),
                detail=f"{resource_type} idle — ${cost_usd}/month",
            ))
    except Exception as exc:
        logger.warning("CHECK 2 (GHOST_RESOURCE) failed for %s: %s", project_id, exc)

    # CHECK 3 — BUDGET_BREACH
    try:
        budget_status = await check_budget_status(project_id)
        if budget_status.breached:
            flag = SecurityFlag(
                flag_id=str(uuid.uuid4()),
                flag_type="BUDGET_BREACH",
                identity_or_resource=project_id,
                project_id=project_id,
                detected_at=_now_iso(),
                detail=(
                    f"Spend ${budget_status.current_month_usd:.2f} exceeds "
                    f"threshold ${budget_status.threshold_usd:.2f}"
                ),
            )
            flags.append(flag)

            # INV-SEC2-02: BUDGET_BREACH must produce a JSONL audit entry before returning
            entry = AuditEntry(
                timestamp=_now_iso(),
                resource_id=project_id,
                action_type="SECURITY_FLAG",
                llm_reasoning=flag.detail,
                actor="agent",
                outcome="SUCCESS",
                run_id=run_id,
                session_mutation_count=0,
                project_id=project_id,
            )
            write_audit_entry(entry, log_dir, run_id)
    except Exception as exc:
        logger.warning("CHECK 3 (BUDGET_BREACH) failed for %s: %s", project_id, exc)

    return flags


async def generate_audit_report_data(project_id: str, credentials=None) -> dict:
    """Assemble structured data for PDF generation — no GCP mutations."""
    from cerberus.heads.cost_head import get_project_cost_summary
    from cerberus.heads.iam_head import _tickets, load_tickets_from_chroma

    security_flags: list[dict] = []
    iam_changes: list[dict] = []
    idle_resources: list[dict] = []
    cost_summary: dict = {}
    iam_tickets: list[dict] = []

    try:
        flags = await get_security_flags(project_id, credentials)
        security_flags = [f.model_dump() for f in flags]
        idle_resources = [
            {"identity_or_resource": f.identity_or_resource, "detail": f.detail}
            for f in flags if f.flag_type == "GHOST_RESOURCE"
        ]
    except Exception as exc:
        logger.warning("generate_audit_report_data: security flags failed: %s", exc)

    try:
        bindings = await get_iam_inventory(project_id, credentials)
        iam_changes = [b.model_dump() for b in bindings]
    except Exception as exc:
        logger.warning("generate_audit_report_data: IAM inventory failed: %s", exc)

    try:
        summary = await get_project_cost_summary(project_id)
        cost_summary = {
            "total_usd": summary.total_usd,
            "attributed_usd": summary.attributed_usd,
            "unattributed_usd": summary.unattributed_usd,
            "breakdown": summary.breakdown,
        }
    except Exception as exc:
        logger.warning("generate_audit_report_data: cost summary failed: %s", exc)

    try:
        load_tickets_from_chroma()
        iam_tickets = [
            t.model_dump()
            for t in _tickets.values()
            if t.plan.project_id == project_id
        ]
    except Exception as exc:
        logger.warning("generate_audit_report_data: IAM tickets failed: %s", exc)

    resources_scanned = len(query_project_history(project_id))

    return {
        "report_timestamp": _now_iso(),
        "project_id": project_id,
        "resources_scanned": resources_scanned,
        "total_waste_identified": len(idle_resources),
        "iam_changes": iam_changes,
        "security_flags": security_flags,
        "idle_resources": idle_resources,
        "cost_summary": cost_summary,
        "iam_tickets": iam_tickets,
    }
