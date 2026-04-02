from __future__ import annotations

from pydantic import BaseModel


class ProjectCostSummary(BaseModel):
    project_id: str
    total_usd: float
    attributed_usd: float
    unattributed_usd: float
    period: str               # "current_month"
    breakdown: list[dict]     # [{"owner_email": str, "cost_usd": float}]
    resources: list[dict] = []  # full resource records with decision/reasoning
    ghost_resources: list[dict] = []  # resources with safe_to_stop or safe_to_delete decision


class UserCostSummary(BaseModel):
    owner_email: str
    project_id: str
    total_usd: float
    resource_count: int
    resources: list[dict]     # [{"resource_id": str, "resource_type": str, "cost_usd": float}]
