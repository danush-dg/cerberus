from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from cerberus.heads.cost_head import get_project_cost_summary, get_user_cost_summary

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/cost/project/{project_id}")
async def get_project_cost(project_id: str) -> JSONResponse:
    """Per-project cost summary from ChromaDB (Task 10.3).

    INV-COST-01: unattributed row included when unattributed_usd > 0.
    INV-COST-02: no billing API — ChromaDB only.
    """
    try:
        summary = await get_project_cost_summary(project_id)
        return JSONResponse(status_code=200, content=summary.model_dump())
    except Exception as exc:
        logger.exception("get_project_cost failed for %s", project_id)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/cost/user")
async def get_user_cost(owner_email: str, project_id: str) -> JSONResponse:
    """Per-user cost summary from ChromaDB (Task 10.3).

    INV-COST-02: no billing API — ChromaDB only.
    """
    try:
        summary = await get_user_cost_summary(owner_email, project_id)
        return JSONResponse(status_code=200, content=summary.model_dump())
    except Exception as exc:
        logger.exception("get_user_cost failed for owner=%s project=%s", owner_email, project_id)
        return JSONResponse(status_code=500, content={"error": str(exc)})
