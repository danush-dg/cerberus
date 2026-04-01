from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from cerberus.heads.security_head import (
    check_budget_status,
    generate_audit_report_data,
    get_security_flags,
)
from cerberus.services.pdf_report import generate_audit_report

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/security/flags")
async def get_security_flags_route(project_id: str) -> JSONResponse:
    """Active security flags for a project (Task 10.4)."""
    try:
        flags = await get_security_flags(project_id, credentials=None)
        return JSONResponse(status_code=200, content=[f.model_dump() for f in flags])
    except Exception as exc:
        logger.exception("get_security_flags failed for %s", project_id)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/security/budget-status")
async def get_budget_status_route(project_id: str) -> JSONResponse:
    """Budget breach status for a project (Task 10.4)."""
    try:
        status = await check_budget_status(project_id)
        return JSONResponse(status_code=200, content=status.model_dump())
    except Exception as exc:
        logger.exception("check_budget_status failed for %s", project_id)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/security/report/download")
async def get_report_download_route(project_id: str) -> Response:
    """Download PDF audit report for a project (Task 10.4).

    INV-SEC2-03: reportlab only, no network calls.
    """
    try:
        report_data = await generate_audit_report_data(project_id, credentials=None)
        pdf_bytes = generate_audit_report(project_id, report_data)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="cerberus_audit_{project_id}.pdf"'
            },
        )
    except Exception as exc:
        logger.exception("generate_audit_report failed for %s", project_id)
        return JSONResponse(status_code=500, content={"error": str(exc)})
