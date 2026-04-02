from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cerberus.config import get_config, validate_project_id
from cerberus.graph import cerberus_graph
from cerberus.state import initialise_state, CerberusState
from cerberus.routes.iam_routes import router as iam_router
from cerberus.routes.cost_routes import router as cost_router
from cerberus.routes.security_routes import router as security_router
from cerberus.routes.ticket_routes import router as ticket_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Cerberus")
app.include_router(iam_router)
app.include_router(cost_router)
app.include_router(security_router)
app.include_router(ticket_router)

# In-memory store keyed by run_id.
# Each entry: {"thread_id", "project_id", "status", "approval_payload", "final_state", "error_message"}
# status values: "scanning" | "awaiting_approval" | "executing" | "complete" | "error"
active_runs: dict[str, dict] = {}

# In-memory IAM ticket store keyed by ticket_id.
# Each entry: {"id", "ts", "plan", "status"}
# status values: "pending" | "approved" | "rejected"
iam_tickets: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    project_id: str
    dry_run: bool = True


class ApproveRequest(BaseModel):
    approved_ids: list[str]


class RunSummary(BaseModel):
    run_id: str
    resources_scanned: int
    total_waste_identified: float | None
    actions_approved: int
    actions_executed: int
    estimated_monthly_savings_recovered: float
    audit_log_path: str | None
    langsmith_trace_url: str | None


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------


_TRACED_NODES = frozenset({
    "scan_node", "enrich_node", "reason_node",
    "revalidate_node", "approve_node", "execute_node", "audit_node",
})

_NODE_ICONS = {
    "scan_node":       "🔍",
    "enrich_node":     "🏷️",
    "reason_node":     "🧠",
    "revalidate_node": "🔄",
    "approve_node":    "✅",
    "execute_node":    "⚡",
    "audit_node":      "📋",
}

_NODE_COLORS = {
    "scan_node":       "#1f77b4",
    "enrich_node":     "#7b1fa2",
    "reason_node":     "#ff9800",
    "revalidate_node": "#00838f",
    "approve_node":    "#4caf50",
    "execute_node":    "#f44336",
    "audit_node":      "#607d8b",
}


def _process_trace_event(run_id: str, event: dict) -> None:
    if run_id not in active_runs:
        return
    event_type: str = event.get("event", "")
    name: str = event.get("name", "")

    if event_type == "on_chain_start" and name in _TRACED_NODES:
        active_runs[run_id]["trace_events"].append({
            "type": "node_start",
            "node": name,
            "icon": _NODE_ICONS.get(name, "▶"),
            "color": _NODE_COLORS.get(name, "#495057"),
            "ts": datetime.now(timezone.utc).isoformat(),
            "message": f"{name.replace('_node', '').replace('_', ' ').title()} started",
        })
    elif event_type == "on_chain_end" and name in _TRACED_NODES:
        output = event.get("data", {}).get("output") or {}
        out = output if isinstance(output, dict) else {}
        active_runs[run_id]["trace_events"].append({
            "type": "node_end",
            "node": name,
            "icon": _NODE_ICONS.get(name, "✓"),
            "color": _NODE_COLORS.get(name, "#495057"),
            "ts": datetime.now(timezone.utc).isoformat(),
            "message": _summarize_node_output(name, out),
            "detail": _node_detail(name, out),
        })


def _summarize_node_output(node: str, output: dict) -> str:
    if node == "scan_node":
        resources = output.get("resources", [])
        count = len(resources) if isinstance(resources, list) else 0
        return f"Scan complete — {count} resource(s) discovered"
    if node == "enrich_node":
        resources = output.get("resources", [])
        if isinstance(resources, list):
            owned = sum(1 for r in resources if isinstance(r, dict) and r.get("ownership_status") not in (None, "no_owner"))
            return f"Enrichment complete — {owned}/{len(resources)} resources have an owner"
        return "Enrichment complete"
    if node == "reason_node":
        resources = output.get("resources", [])
        if isinstance(resources, list):
            classified = sum(1 for r in resources if isinstance(r, dict) and r.get("decision"))
            stop = sum(1 for r in resources if isinstance(r, dict) and r.get("decision") == "safe_to_stop")
            delete = sum(1 for r in resources if isinstance(r, dict) and r.get("decision") == "safe_to_delete")
            review = sum(1 for r in resources if isinstance(r, dict) and r.get("decision") == "needs_review")
            return f"Gemini classified {classified} resource(s): {stop} stop · {delete} delete · {review} review"
        return "Gemini classification complete"
    if node == "revalidate_node":
        drift = output.get("revalidation_drift", False)
        return f"Revalidation complete — {'drift detected' if drift else 'no drift'}"
    if node == "approve_node":
        approved = output.get("approved_actions", [])
        count = len(approved) if isinstance(approved, list) else 0
        return f"Approval gate — {count} action(s) approved"
    if node == "execute_node":
        resources = output.get("resources", [])
        if isinstance(resources, list):
            success = sum(1 for r in resources if isinstance(r, dict) and r.get("outcome") == "SUCCESS")
            dry = sum(1 for r in resources if isinstance(r, dict) and r.get("outcome") == "DRY_RUN")
            return f"Execution complete — {success} success · {dry} dry-run"
        return "Execution complete"
    if node == "audit_node":
        return "Audit log written — JSONL entries flushed to disk"
    return f"{node} complete"


def _node_detail(node: str, output: dict) -> list[dict]:
    detail: list[dict] = []
    if node == "reason_node":
        for r in (output.get("resources") or []):
            if not isinstance(r, dict):
                continue
            detail.append({
                "resource_id": r.get("resource_id", "?"),
                "resource_type": r.get("resource_type", "?"),
                "decision": r.get("decision") or "—",
                "reasoning": r.get("reasoning") or "—",
                "savings": r.get("estimated_monthly_savings"),
            })
    if node == "execute_node":
        for r in (output.get("resources") or []):
            if not isinstance(r, dict) or not r.get("outcome"):
                continue
            detail.append({
                "resource_id": r.get("resource_id", "?"),
                "resource_type": r.get("resource_type", "?"),
                "outcome": r.get("outcome") or "—",
                "decision": r.get("decision") or "—",
            })
    return detail


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
        async for event in cerberus_graph.astream_events(
            state, config=config, version="v2"
        ):
            _process_trace_event(run_id, event)

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
        async for event in cerberus_graph.astream_events(
            None, config=config, version="v2"
        ):
            _process_trace_event(run_id, event)

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
        "trace_events": [],
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


@app.get("/run/{run_id}/events")
async def get_events(run_id: str, offset: int = 0) -> JSONResponse:
    """Return agent trace events for a run (polled by the frontend).

    offset: return only events starting at this index (incremental polling).
    INV-SEC-02: no credential fields are included.
    """
    if run_id not in active_runs:
        return JSONResponse(status_code=404, content={"error": "Run not found."})

    events: list[dict] = active_runs[run_id].get("trace_events", [])
    return JSONResponse(
        status_code=200,
        content={
            "run_id": run_id,
            "status": active_runs[run_id]["status"],
            "total": len(events),
            "events": events[offset:],
        },
    )


@app.get("/run/{run_id}/summary")
async def get_summary(run_id: str) -> JSONResponse:
    """Return COST_SUMMARY as JSON.

    INV-SEC-02: no fields from CerberusConfig appear in the response.
    Returns 404 if the run is not complete or the summary has not been written yet.
    """
    if run_id not in active_runs:
        return JSONResponse(status_code=404, content={"error": "Run not found."})

    final_state: dict = active_runs[run_id].get("final_state") or {}
    cost_summary = final_state.get("cost_summary")

    if not cost_summary:
        return JSONResponse(
            status_code=404,
            content={"error": "Run not complete or summary not yet written."},
        )

    summary = RunSummary(
        run_id=run_id,
        resources_scanned=cost_summary.get("resources_scanned", 0),
        total_waste_identified=cost_summary.get("total_waste_identified"),
        actions_approved=cost_summary.get("actions_approved", 0),
        actions_executed=cost_summary.get("actions_executed", 0),
        estimated_monthly_savings_recovered=cost_summary.get(
            "estimated_monthly_savings_recovered", 0.0
        ),
        audit_log_path=final_state.get("audit_log_path"),
        langsmith_trace_url=final_state.get("langsmith_trace_url"),
    )
    return JSONResponse(status_code=200, content=summary.model_dump())


# ---------------------------------------------------------------------------
# IAM Access Head endpoint (Task 9.1 UI)
# ---------------------------------------------------------------------------


class IamSynthesizeRequest(BaseModel):
    requester_email: str
    request_text: str
    project_id: str


@app.post("/iam/synthesize")
async def post_iam_synthesize(req: IamSynthesizeRequest) -> JSONResponse:
    """Synthesize a least-privilege IAM provisioning plan from a natural-language request.

    INV-SEC-01: project_id is validated before any Gemini call.
    INV-SEC-02: no credential fields in response.
    """
    from cerberus.nodes.access_node import synthesize_iam_request, IamRequest
    try:
        plan = synthesize_iam_request(
            IamRequest(
                requester_email=req.requester_email,
                request_text=req.request_text,
                project_id=req.project_id,
            )
        )
        return JSONResponse(status_code=200, content=plan.model_dump())
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception as exc:
        logger.exception("IAM synthesis failed")
        return JSONResponse(status_code=500, content={"error": str(exc)})


# ---------------------------------------------------------------------------
# IAM Ticket endpoints (Cerberus Admin ticket queue)
# ---------------------------------------------------------------------------


class IamTicketCreate(BaseModel):
    plan: dict


class IamTicketReview(BaseModel):
    action: str  # "approved" | "rejected"


@app.post("/iam/tickets")
async def post_iam_ticket(req: IamTicketCreate) -> JSONResponse:
    """Create a new IAM ticket from a synthesized plan submitted for admin approval."""
    ticket_id = str(uuid.uuid4())
    iam_tickets[ticket_id] = {
        "id": ticket_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "plan": req.plan,
        "status": "pending",
    }
    logger.info("IAM ticket %s created for requester %s", ticket_id, req.plan.get("requester_email"))
    return JSONResponse(status_code=200, content={"id": ticket_id})


@app.get("/iam/tickets")
async def get_iam_tickets() -> JSONResponse:
    """List all IAM tickets (pending, approved, rejected).

    Reads from iam_head._tickets — the same store written by POST /iam/request.
    Maps IAMTicket {ticket_id, created_at, plan, status} to the frontend shape
    {id, ts, plan, status} that IamTicketResponse expects.
    """
    from cerberus.heads.iam_head import _tickets as _iam_tickets
    items = []
    for ticket in _iam_tickets.values():
        items.append({
            "id": ticket.ticket_id,
            "ts": ticket.created_at,
            "plan": ticket.plan.model_dump(),
            "status": ticket.status,
        })
    return JSONResponse(status_code=200, content=items)


@app.post("/iam/tickets/{ticket_id}/review")
async def post_iam_ticket_review(ticket_id: str, req: IamTicketReview) -> JSONResponse:
    """Approve or reject an IAM ticket.

    Reads from iam_head._tickets — the same store written by POST /iam/request.
    """
    from cerberus.heads.iam_head import _tickets as _iam_tickets, approve_ticket, reject_ticket
    if ticket_id not in _iam_tickets:
        return JSONResponse(status_code=404, content={"error": "Ticket not found."})
    if req.action not in ("approved", "rejected"):
        return JSONResponse(status_code=400, content={"error": "action must be 'approved' or 'rejected'"})
    try:
        if req.action == "approved":
            ticket = await approve_ticket(ticket_id, reviewer_email="admin@cerberus")
        else:
            ticket = await reject_ticket(ticket_id, reviewer_email="admin@cerberus")
        logger.info("IAM ticket %s %s", ticket_id, req.action)
        return JSONResponse(status_code=200, content={"status": ticket.status})
    except Exception as exc:
        logger.exception("IAM ticket review failed for %s", ticket_id)
        return JSONResponse(status_code=500, content={"error": str(exc)})
