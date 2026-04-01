from __future__ import annotations

from cerberus.models.security_flag import BudgetStatus, SecurityFlag


async def get_security_flags(project_id: str, credentials) -> list[SecurityFlag]:
    pass


async def check_budget_status(project_id: str) -> BudgetStatus:
    pass


async def generate_audit_report_data(project_id: str) -> dict:
    pass
