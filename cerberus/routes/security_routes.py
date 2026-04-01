from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

router = APIRouter()


@router.get("/security/flags")
async def get_security_flags(project_id: str) -> JSONResponse:
    return JSONResponse(status_code=200, content=[])


@router.get("/security/budget-status")
async def get_budget_status(project_id: str) -> JSONResponse:
    return JSONResponse(status_code=200, content={})


@router.get("/security/report/download")
async def get_report_download(project_id: str) -> Response:
    return Response(content=b"", media_type="application/pdf")
