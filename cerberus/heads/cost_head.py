from __future__ import annotations

import logging
from collections import defaultdict

from cerberus.models.cost_record import ProjectCostSummary, UserCostSummary
from cerberus.tools.chroma_client import query_owner_history, query_project_history

logger = logging.getLogger(__name__)


async def get_project_cost_summary(project_id: str) -> ProjectCostSummary:
    """Return a per-owner cost breakdown for *project_id* from ChromaDB history.

    INV-COST-01: if unattributed_usd > 0, an explicit {"owner_email": "unattributed",
    "cost_usd": X} row is appended to breakdown — never silently omitted.
    INV-COST-02: no Cloud Billing API call — all data from ChromaDB only.
    """
    records = query_project_history(project_id)

    owner_costs: dict[str, float] = defaultdict(float)
    for rec in records:
        cost = float(rec.get("estimated_monthly_cost") or 0.0)
        email = rec.get("owner_email") or "unknown"
        owner_costs[email] += cost

    attributed_usd = sum(v for k, v in owner_costs.items() if k not in ("unknown", "unattributed"))
    unattributed_usd = sum(v for k, v in owner_costs.items() if k in ("unknown", "unattributed"))
    total_usd = attributed_usd + unattributed_usd

    breakdown: list[dict] = [
        {"owner_email": email, "cost_usd": round(cost, 4)}
        for email, cost in sorted(owner_costs.items(), key=lambda x: -x[1])
        if email not in ("unknown", "unattributed")
    ]

    # INV-COST-01: unattributed row must be present when unattributed_usd > 0.
    if unattributed_usd > 0:
        breakdown.append({"owner_email": "unattributed", "cost_usd": round(unattributed_usd, 4)})

    _actionable = {"safe_to_stop", "safe_to_delete"}
    resources: list[dict] = []
    ghost_resources: list[dict] = []
    for rec in records:
        decision = rec.get("decision") or "unknown"
        entry = {
            "resource_id": rec.get("resource_id") or "unknown",
            "resource_type": rec.get("resource_type") or "unknown",
            "region": rec.get("region") or "—",
            "owner_email": rec.get("owner_email") or "unattributed",
            "ownership_status": rec.get("ownership_status") or "unknown",
            "decision": decision,
            "reasoning": rec.get("reasoning") or None,
            "estimated_monthly_cost": float(rec.get("estimated_monthly_cost") or 0.0),
            "estimated_monthly_savings": float(rec.get("estimated_monthly_savings") or 0.0),
        }
        resources.append(entry)
        if decision in _actionable:
            ghost_resources.append(entry)

    return ProjectCostSummary(
        project_id=project_id,
        total_usd=round(total_usd, 4),
        attributed_usd=round(attributed_usd, 4),
        unattributed_usd=round(unattributed_usd, 4),
        period="current_month",
        breakdown=breakdown,
        resources=resources,
        ghost_resources=ghost_resources,
    )


async def get_user_cost_summary(owner_email: str, project_id: str) -> UserCostSummary:
    """Return all resources owned by *owner_email* in *project_id* with their costs.

    INV-COST-02: no Cloud Billing API call — all data from ChromaDB only.
    """
    records = query_owner_history(owner_email, project_id)

    total_usd = 0.0
    resources: list[dict] = []
    for rec in records:
        cost = float(rec.get("estimated_monthly_cost") or 0.0)
        total_usd += cost
        resources.append({
            "resource_id": rec.get("resource_id") or "unknown",
            "resource_type": rec.get("resource_type") or "unknown",
            "cost_usd": round(cost, 4),
        })

    return UserCostSummary(
        owner_email=owner_email,
        project_id=project_id,
        total_usd=round(total_usd, 4),
        resource_count=len(resources),
        resources=resources,
    )
