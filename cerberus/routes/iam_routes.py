from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/iam/request")
async def post_iam_request() -> JSONResponse:
    return JSONResponse(status_code=200, content={})


@router.get("/iam/request/{request_id}/preview")
async def get_iam_request_preview(request_id: str) -> JSONResponse:
    return JSONResponse(status_code=200, content={})


@router.post("/iam/request/{request_id}/confirm")
async def post_iam_request_confirm(request_id: str) -> JSONResponse:
    return JSONResponse(status_code=200, content={})


@router.get("/iam/inventory")
async def get_iam_inventory(project_id: str) -> JSONResponse:
    return JSONResponse(status_code=200, content=[])
