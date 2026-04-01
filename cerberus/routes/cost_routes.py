from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/cost/project/{project_id}")
async def get_project_cost(project_id: str) -> JSONResponse:
    return JSONResponse(status_code=200, content={})


@router.get("/cost/user")
async def get_user_cost(owner_email: str, project_id: str) -> JSONResponse:
    return JSONResponse(status_code=200, content={})
