from __future__ import annotations

from cerberus.models.cost_record import ProjectCostSummary, UserCostSummary


async def get_project_cost_summary(project_id: str) -> ProjectCostSummary:
    pass


async def get_user_cost_summary(
    owner_email: str, project_id: str
) -> UserCostSummary:
    pass
