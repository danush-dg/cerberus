from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/tickets")
async def get_tickets() -> JSONResponse:
    return JSONResponse(status_code=200, content=[])


@router.post("/tickets/{ticket_id}/approve")
async def post_ticket_approve(ticket_id: str) -> JSONResponse:
    return JSONResponse(status_code=200, content={})


@router.post("/tickets/{ticket_id}/provision")
async def post_ticket_provision(ticket_id: str) -> JSONResponse:
    return JSONResponse(status_code=200, content={})
