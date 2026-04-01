from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


FLAG_TYPES = Literal["OVER_PERMISSIONED", "GHOST_RESOURCE", "BUDGET_BREACH"]


class SecurityFlag(BaseModel):
    flag_id: str              # uuid4
    flag_type: FLAG_TYPES
    identity_or_resource: str # email or resource_id
    project_id: str
    detected_at: str          # ISO 8601
    detail: str               # human-readable explanation
    status: Literal["open", "acknowledged", "resolved"] = "open"


class BudgetStatus(BaseModel):
    project_id: str
    current_month_usd: float
    threshold_usd: float
    breached: bool
    percent_used: float
    live_budget_threshold_usd: float | None = None
