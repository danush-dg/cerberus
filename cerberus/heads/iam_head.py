from __future__ import annotations

from cerberus.models.iam_ticket import (
    IAMBinding,
    IAMRequest,
    IAMTicket,
    SynthesizedIAMPlan,
)
from cerberus.config import CerberusConfig


async def synthesize_iam_request(
    request: IAMRequest, config: CerberusConfig
) -> SynthesizedIAMPlan:
    pass


async def create_ticket(plan: SynthesizedIAMPlan) -> IAMTicket:
    pass


async def get_pending_tickets() -> list[IAMTicket]:
    pass


async def approve_ticket(ticket_id: str, reviewer_email: str) -> IAMTicket:
    pass


async def provision_iam_binding(ticket: IAMTicket, dry_run: bool = True) -> dict:
    pass


async def get_iam_inventory(project_id: str, credentials) -> list[IAMBinding]:
    pass
