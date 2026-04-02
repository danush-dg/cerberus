from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cerberus.heads.iam_head import (
    _tickets,
    approve_ticket,
    load_tickets_from_chroma,
    provision_iam_binding,
    reject_ticket,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_chroma_loaded = False


def _ensure_loaded() -> None:
    """Load tickets from ChromaDB on first request (lazy startup restore)."""
    global _chroma_loaded
    if not _chroma_loaded:
        _chroma_loaded = True
        try:
            load_tickets_from_chroma()
        except Exception as exc:
            logger.warning("_ensure_loaded: ChromaDB restore failed: %s", exc)


class ApproveBody(BaseModel):
    reviewer_email: str = "admin@cerberus"


class ProvisionBody(BaseModel):
    dry_run: bool = True


@router.get("/tickets")
async def get_tickets() -> JSONResponse:
    """List all IAM tickets (all statuses), restoring from ChromaDB if needed."""
    _ensure_loaded()
    return JSONResponse(
        status_code=200,
        content=[t.model_dump() for t in _tickets.values()],
    )


@router.post("/tickets/{ticket_id}/approve")
async def post_ticket_approve(ticket_id: str, body: ApproveBody = ApproveBody()) -> JSONResponse:
    """Approve a pending IAM ticket."""
    _ensure_loaded()
    try:
        ticket = await approve_ticket(ticket_id, body.reviewer_email)
        return JSONResponse(status_code=200, content=ticket.model_dump())
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        logger.exception("Ticket approve failed for %s", ticket_id)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/tickets/{ticket_id}/reject")
async def post_ticket_reject(ticket_id: str, body: ApproveBody = ApproveBody()) -> JSONResponse:
    """Reject a pending IAM ticket."""
    _ensure_loaded()
    try:
        ticket = await reject_ticket(ticket_id, body.reviewer_email)
        return JSONResponse(status_code=200, content=ticket.model_dump())
    except KeyError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        logger.exception("Ticket reject failed for %s", ticket_id)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/tickets/{ticket_id}/provision")
async def post_ticket_provision(
    ticket_id: str, body: ProvisionBody = ProvisionBody()
) -> JSONResponse:
    """Provision an approved IAM ticket.

    INV-IAM-02: ticket.status must be "approved" before provisioning.
    Pending, rejected, or already-provisioned tickets are rejected.
    """
    _ensure_loaded()
    ticket = _tickets.get(ticket_id)
    if not ticket:
        return JSONResponse(status_code=404, content={"error": "Ticket not found."})

    if ticket.status != "approved":
        return JSONResponse(
            status_code=400,
            content={
                "error": (
                    f"Ticket {ticket_id} cannot be provisioned — "
                    f"status is '{ticket.status}', must be 'approved'."
                )
            },
        )

    try:
        result = await provision_iam_binding(ticket, dry_run=body.dry_run)
        return JSONResponse(status_code=200, content=result)
    except Exception as exc:
        logger.exception("Ticket provision failed for %s", ticket_id)
        return JSONResponse(status_code=500, content={"error": str(exc)})
