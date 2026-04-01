from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cerberus.config import get_config, validate_project_id
from cerberus.heads.iam_head import (
    _tickets,
    create_ticket,
    get_iam_inventory,
    synthesize_iam_request,
)
from cerberus.models.iam_ticket import IAMRequest

logger = logging.getLogger(__name__)
router = APIRouter()


class IamRequestBody(BaseModel):
    natural_language_request: str
    requester_email: str
    project_id: str


@router.post("/iam/request")
async def post_iam_request(body: IamRequestBody) -> JSONResponse:
    """Synthesize an IAM plan and create a pending ticket.

    INV-IAM-01: synthesis completes before ticket is created.
    INV-SEC-01: project_id validated before any GCP/Gemini call.
    """
    config = get_config()
    try:
        validate_project_id(body.project_id, config.allowed_project_pattern)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    try:
        request = IAMRequest(
            natural_language_request=body.natural_language_request,
            requester_email=body.requester_email,
            project_id=body.project_id,
        )
        plan = await synthesize_iam_request(request, config)
        ticket = await create_ticket(plan)
        return JSONResponse(status_code=200, content=ticket.model_dump())
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception as exc:
        logger.exception("IAM request failed")
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/iam/request/{request_id}/preview")
async def get_iam_request_preview(request_id: str) -> JSONResponse:
    """Return the synthesized plan for a ticket (preview before confirm)."""
    ticket = _tickets.get(request_id)
    if not ticket:
        return JSONResponse(status_code=404, content={"error": "Ticket not found."})
    return JSONResponse(status_code=200, content=ticket.plan.model_dump())


@router.post("/iam/request/{request_id}/confirm")
async def post_iam_request_confirm(request_id: str) -> JSONResponse:
    """Confirm ticket creation — idempotent, returns the existing ticket."""
    ticket = _tickets.get(request_id)
    if not ticket:
        return JSONResponse(status_code=404, content={"error": "Ticket not found."})
    return JSONResponse(status_code=200, content=ticket.model_dump())


@router.get("/iam/inventory")
async def get_iam_inventory_route(project_id: str) -> JSONResponse:
    """List live GCP IAM bindings for a project."""
    config = get_config()
    try:
        validate_project_id(project_id, config.allowed_project_pattern)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    try:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            config.service_account_key_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        bindings = await get_iam_inventory(project_id, credentials)
        return JSONResponse(status_code=200, content=[b.model_dump() for b in bindings])
    except Exception as exc:
        logger.exception("IAM inventory failed for %s", project_id)
        return JSONResponse(status_code=500, content={"error": str(exc)})
