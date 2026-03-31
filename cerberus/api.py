from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cerberus.config import get_config, validate_project_id
from cerberus.graph import cerberus_graph
from cerberus.state import initialise_state, CerberusState

logger = logging.getLogger(__name__)

app = FastAPI(title="Cerberus")

# In-memory store keyed by run_id.
# Each entry: {"thread_id", "project_id", "status", "approval_payload", "final_state", "error_message"}
# status values: "scanning" | "awaiting_approval" | "executing" | "complete" | "error"
active_runs: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    project_id: str
    dry_run: bool = True


class ApproveRequest(BaseModel):
    approved_ids: list[str]


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------


async def _run_graph_until_interrupt(
    run_id: str, state: CerberusState, thread_id: str
) -> None:
    """Stream the graph from the start until the approval gate or completion.

    The approval gate uses interrupt_before=["approve_node"] (compile-time).
    When paused, graph_state.next contains "approve_node" and the plan is
    read directly from graph_state.values["resources"].
    """
    config = {"configurable": {"thread_id": thread_id}}
    try:
        async for _event in cerberus_graph.astream_events(
            state, config=config, version="v2"
        ):
            pass

        graph_state = await cerberus_graph.aget_state(config)

        if graph_state.next and "approve_node" in graph_state.next:
            # Graph paused before approve_node — surface resources as plan.
            resources = graph_state.values.get("resources", [])
            active_runs[run_id]["approval_payload"] = [
                {
                    "resource_id": r["resource_id"],
                    "resource_type": r["resource_type"],
                    "region": r["region"],
                    "owner_email": r["owner_email"],
                    "ownership_status": r["ownership_status"],
                    "decision": r["decision"],
                    "reasoning": r["reasoning"],
                    "estimated_monthly_savings": r["estimated_monthly_savings"],
                }
                for r in resources
            ]
            active_runs[run_id]["status"] = "awaiting_approval"
            logger.info("run %s reached approval gate", run_id)
        else:
            active_runs[run_id]["final_state"] = dict(graph_state.values)
            active_runs[run_id]["status"] = "complete"
            logger.info("run %s completed without interrupt", run_id)

    except Exception:
        logger.exception("run %s failed during graph execution", run_id)
        active_runs[run_id]["status"] = "error"


async def _resume_graph(
    run_id: str, approved_ids: list[str], thread_id: str
) -> None:
    """Resume the graph after human approval.

    Injects approved_actions into the graph state via aupdate_state (Python 3.10
    compatible — avoids langgraph.types.interrupt() which requires Python 3.11+
    in async contexts), then resumes by streaming None.
    """
    config = {"configurable": {"thread_id": thread_id}}
    try:
        # Read current resources to build approved_actions list.
        graph_state = await cerberus_graph.aget_state(config)
        resources = graph_state.values.get("resources", [])
        approved_resources = [
            r for r in resources if r["resource_id"] in approved_ids
        ]

        # Inject approved state before approve_node runs.
        await cerberus_graph.aupdate_state(
            config,
            {"approved_actions": approved_resources, "mutation_count": 0},
        )

        # Resume from the interrupted point (approve_node).
        async for _event in cerberus_graph.astream_events(
            None, config=config, version="v2"
        ):
            pass

        graph_state = await cerberus_graph.aget_state(config)
        active_runs[run_id]["final_state"] = dict(graph_state.values)
        active_runs[run_id]["status"] = "complete"
        logger.info("run %s completed after approval", run_id)

    except Exception:
        logger.exception("run %s failed during post-approval execution", run_id)
        active_runs[run_id]["status"] = "error"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/run")
async def post_run(req: RunRequest, background_tasks: BackgroundTasks) -> JSONResponse:
    """Start a new agent run.

    Validates project_id, rejects concurrent scans for the same project,
    then kicks off the graph as a background task.
    """
    config = get_config()
    try:
        validate_project_id(req.project_id, config.allowed_project_pattern)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    # INV-SEC-01 is enforced by validate_project_id above before any GCP call.
    # Reject concurrent scans on the same project.
    for run_info in active_runs.values():
        if (
            run_info["project_id"] == req.project_id
            and run_info["status"] not in ("complete", "error")
        ):
            return JSONResponse(
                status_code=409,
                content={"error": "A scan for this project is already running."},
            )

    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())

    active_runs[run_id] = {
        "thread_id": thread_id,
        "project_id": req.project_id,
        "status": "scanning",
        "approval_payload": None,
        "final_state": None,
        "error_message": None,
    }

    state = initialise_state(req.project_id, dry_run=req.dry_run)
    # Override the auto-generated run_id so it matches our tracking key.
    state["run_id"] = run_id

    background_tasks.add_task(_run_graph_until_interrupt, run_id, state, thread_id)

    return JSONResponse(status_code=200, content={"run_id": run_id})


@app.get("/run/{run_id}/plan")
async def get_plan(run_id: str) -> JSONResponse:
    """Poll for the approval payload.

    Returns {"status": "scanning", "plan": null} until the graph reaches the
    interrupt, then {"status": "awaiting_approval", "plan": [...]}.
    """
    if run_id not in active_runs:
        return JSONResponse(status_code=404, content={"error": "Run not found."})

    run_info = active_runs[run_id]
    if run_info["status"] == "awaiting_approval":
        return JSONResponse(
            status_code=200,
            content={"status": "awaiting_approval", "plan": run_info["approval_payload"]},
        )

    return JSONResponse(
        status_code=200,
        content={"status": run_info["status"], "plan": None},
    )


@app.post("/run/{run_id}/approve")
async def post_approve(
    run_id: str, req: ApproveRequest, background_tasks: BackgroundTasks
) -> JSONResponse:
    """Resume the graph with the user-selected approved_ids."""
    if run_id not in active_runs:
        return JSONResponse(status_code=404, content={"error": "Run not found."})

    run_info = active_runs[run_id]
    active_runs[run_id]["status"] = "executing"

    background_tasks.add_task(
        _resume_graph, run_id, req.approved_ids, run_info["thread_id"]
    )

    return JSONResponse(status_code=200, content={"status": "executing"})


@app.get("/run/{run_id}/status")
async def get_status(run_id: str) -> JSONResponse:
    """Return run state.

    INV-SEC-02: must not include any field from CerberusConfig (no credentials).
    """
    if run_id not in active_runs:
        return JSONResponse(status_code=404, content={"error": "Run not found."})

    run_info = active_runs[run_id]
    final_state: dict = run_info.get("final_state") or {}

    return JSONResponse(
        status_code=200,
        content={
            "run_id": run_id,
            "status": run_info["status"],
            "resources": final_state.get("resources", []),
            "error_message": run_info.get("error_message") or final_state.get("error_message"),
            "run_complete": final_state.get("run_complete", False),
            "dry_run": final_state.get("dry_run", True),
            "langsmith_trace_url": final_state.get("langsmith_trace_url"),
            "mutation_count": final_state.get("mutation_count", 0),
        },
    )
