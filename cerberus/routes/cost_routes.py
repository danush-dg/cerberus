from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cerberus.heads.cost_head import get_project_cost_summary, get_user_cost_summary
from cerberus.tools.chroma_client import query_all_project_ids

logger = logging.getLogger(__name__)
router = APIRouter()


class ResourceExecuteRequest(BaseModel):
    resource_id: str
    resource_type: str
    decision: str
    project_id: str
    dry_run: bool = True


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


@router.get("/cost/projects")
async def get_cost_projects() -> JSONResponse:
    """Return all unique project_ids that have cost history in ChromaDB."""
    try:
        project_ids = query_all_project_ids()
        return JSONResponse(status_code=200, content={"project_ids": project_ids})
    except Exception as exc:
        logger.exception("get_cost_projects failed")
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


@router.post("/cost/resource/execute")
async def execute_resource_action(body: ResourceExecuteRequest) -> JSONResponse:
    """Execute stop or delete action on a specific resource from the Cost Center.

    INV-EXE-01: stop_vm and delete_resource are structurally separate — enforced
    by routing through execute_node functions unchanged.
    INV-EXE-03: mutation_count is not tracked here (single-resource endpoint).
    dry_run=True (default) returns a preview without any GCP mutation.
    """
    actionable = ("safe_to_stop", "safe_to_delete")
    if body.decision not in actionable:
        return JSONResponse(
            status_code=422,
            content={
                "outcome": "SKIPPED",
                "resource_id": body.resource_id,
                "action": "none",
                "detail": f"Decision '{body.decision}' is not actionable — only safe_to_stop / safe_to_delete may be executed.",
            },
        )

    action_label = "stop" if body.decision == "safe_to_stop" else "delete"

    if body.dry_run:
        return JSONResponse(
            status_code=200,
            content={
                "outcome": "DRY_RUN",
                "resource_id": body.resource_id,
                "action": action_label,
                "detail": f"[DRY RUN] Would {action_label} {body.resource_type} '{body.resource_id}' in project '{body.project_id}'.",
            },
        )

    # Live execution — load credentials and call the appropriate execute_node function.
    try:
        from cerberus.config import get_config
        from cerberus.nodes.execute_node import delete_resource, stop_vm
        from google.oauth2 import service_account

        cfg = get_config()
        credentials = service_account.Credentials.from_service_account_file(
            cfg.service_account_key_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        resource = {
            "resource_id": body.resource_id,
            "resource_type": body.resource_type,
            "project_id": body.project_id,
        }

        if body.decision == "safe_to_stop":
            success = await stop_vm(resource, credentials)
        else:
            success = await delete_resource(resource, credentials)

        outcome = "SUCCESS" if success else "FAILED"
        detail = (
            f"{'Successfully' if success else 'Failed to'} {action_label} "
            f"{body.resource_type} '{body.resource_id}'."
        )
        return JSONResponse(
            status_code=200,
            content={"outcome": outcome, "resource_id": body.resource_id, "action": action_label, "detail": detail},
        )
    except Exception as exc:
        logger.exception("execute_resource_action failed for %s", body.resource_id)
        return JSONResponse(status_code=500, content={"error": str(exc)})
