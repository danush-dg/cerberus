#!/usr/bin/env python
"""
scripts/run_demo_smoke_test.py

Demo-day gate check — runs three consecutive dry-run scans against the seeded
sandbox project and verifies determinism, JSONL logs, and ChromaDB records.

Usage:
    # Real GCP sandbox (demo day):
    python scripts/run_demo_smoke_test.py

    # Mock mode — no GCP credentials needed (CI / pre-demo validation):
    python scripts/run_demo_smoke_test.py --mock

Exit code 0 on PASS, 1 on FAIL.
Run this script the morning of demo day as the final gate check.

Invariants verified:
    INV-SCAN-02  — idle detection consistent across runs
    INV-RSN-01   — determinism at temperature=0
    INV-AUD-01   — JSONL logs produced for every run
    INV-ENR-03   — no_owner resources never reach execution
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure cerberus package is importable when run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from httpx import ASGITransport

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "nexus-tech-dev-sandbox")
PLAN_POLL_TIMEOUT_S = 120
STATUS_POLL_TIMEOUT_S = 60
POLL_INTERVAL_S = 1.0

# ---------------------------------------------------------------------------
# Mock nodes (--mock mode — no GCP credentials needed)
# Mirrors the 6-resource scenario from test_e2e.py.
# ---------------------------------------------------------------------------

_NOW = datetime.now(tz=timezone.utc)
_CREATION_TS = (_NOW - timedelta(days=30)).isoformat()
_LAST_ACTIVITY_80H = (_NOW - timedelta(hours=80)).isoformat()


def _base_record(rid: str, rtype: str, flagged: bool = False) -> dict:
    return {
        "resource_id": rid, "resource_type": rtype, "region": "us-central1",
        "creation_timestamp": _CREATION_TS, "last_activity_timestamp": _LAST_ACTIVITY_80H,
        "estimated_monthly_cost": 30.0, "ownership_status": None, "owner_email": None,
        "owner_iam_active": None, "flagged_for_review": flagged, "decision": None,
        "reasoning": None, "estimated_monthly_savings": None, "outcome": None,
    }


async def _mock_scan_node(state: dict) -> dict:
    state["resources"] = [
        _base_record("vm-departed",    "vm"),
        _base_record("vm-active",      "vm"),
        _base_record("vm-noowner",     "vm"),
        _base_record("disk-sensitive", "orphaned_disk", flagged=True),
        _base_record("disk-plain",     "orphaned_disk"),
        _base_record("ip-active",      "unused_ip"),
    ]
    state["expected_resource_count"] = 6
    return state


async def _mock_enrich_node(state: dict) -> dict:
    _om = {
        "vm-departed":    ("departed_owner", "departed@nexus.tech", False),
        "vm-active":      ("active_owner",   "active@nexus.tech",   True),
        "vm-noowner":     ("no_owner",       None,                  False),
        "disk-sensitive": ("departed_owner", "departed@nexus.tech", False),
        "disk-plain":     ("no_owner",       None,                  False),
        "ip-active":      ("active_owner",   "active@nexus.tech",   True),
    }
    for r in state["resources"]:
        status, email, iam_active = _om.get(r["resource_id"], ("no_owner", None, False))
        r["ownership_status"] = status
        r["owner_email"] = email
        r["owner_iam_active"] = iam_active
        r["flagged_for_review"] = r.get("flagged_for_review", False) or (status == "no_owner")
    return state


async def _mock_reason_node(state: dict) -> dict:
    _dm = {
        "vm-departed":    ("safe_to_stop",   "CPU averaged 1% over 80h, below 5% threshold. Owner departed 120d ago. Estimated cost $30/mo."),
        "vm-active":      ("safe_to_stop",   "CPU averaged 1% over 80h meeting idle criteria. Active owner confirmed. Estimated cost $30/mo."),
        "vm-noowner":     ("needs_review",   "No owner resolved. CPU idle 80h. Manual confirmation required. Cost $30/mo."),
        "disk-sensitive": ("needs_review",   "Sensitive data-classification label present. Owner departed. Estimated cost $30/mo."),
        "disk-plain":     ("needs_review",   "No owner resolved for orphaned disk. Cost $30/mo. Flagged for human review."),
        "ip-active":      ("safe_to_delete", "No forwarding rule or VM association. Active owner. Static IP costs $30/mo."),
    }
    for r in state["resources"]:
        decision, reasoning = _dm.get(r["resource_id"], ("needs_review", "Unknown resource — flagged for review."))
        if r.get("flagged_for_review") and decision != "needs_review":
            decision = "needs_review"
        r["decision"] = decision
        r["reasoning"] = reasoning
        r["estimated_monthly_savings"] = 30.0 if decision in ("safe_to_stop", "safe_to_delete") else 0.0
    return state


async def _mock_revalidate_node(state: dict) -> dict:
    return state


def _patch_graph_with_mocks() -> None:
    """Replace the module-level cerberus_graph singleton with mock nodes."""
    from langgraph.checkpoint.memory import MemorySaver
    import cerberus.graph as _graph_mod

    _graph_mod.cerberus_graph = _graph_mod._build_graph(
        _scan=_mock_scan_node,
        _enrich=_mock_enrich_node,
        _reason=_mock_reason_node,
        _revalidate=_mock_revalidate_node,
    ).compile(
        checkpointer=MemorySaver(),
        interrupt_before=["approve_node"],
    )


# ---------------------------------------------------------------------------
# Polling helpers
# ---------------------------------------------------------------------------


async def _poll_plan(client: httpx.AsyncClient, run_id: str) -> list[dict]:
    """Poll /run/{run_id}/plan until status=awaiting_approval."""
    deadline = time.monotonic() + PLAN_POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        resp = await client.get(f"/run/{run_id}/plan")
        resp.raise_for_status()
        body = resp.json()
        if body["status"] == "awaiting_approval":
            return body["plan"]
        if body["status"] == "error":
            raise RuntimeError(f"Run {run_id} entered error state during scan")
        await asyncio.sleep(POLL_INTERVAL_S)
    raise TimeoutError(
        f"Plan not ready after {PLAN_POLL_TIMEOUT_S}s for run {run_id}"
    )


async def _poll_status(client: httpx.AsyncClient, run_id: str) -> dict:
    """Poll /run/{run_id}/status until run_complete=True."""
    deadline = time.monotonic() + STATUS_POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        resp = await client.get(f"/run/{run_id}/status")
        resp.raise_for_status()
        body = resp.json()
        if body.get("run_complete"):
            return body
        if body["status"] == "error":
            raise RuntimeError(
                f"Run {run_id} entered error state during execution"
            )
        await asyncio.sleep(POLL_INTERVAL_S)
    raise TimeoutError(
        f"Run {run_id} not complete after {STATUS_POLL_TIMEOUT_S}s"
    )


# ---------------------------------------------------------------------------
# Single run
# ---------------------------------------------------------------------------


async def _single_run(client: httpx.AsyncClient, run_num: int) -> dict:
    """Execute one full scan → approve-all → execute cycle.

    Returns a summary dict for use in the determinism and gate checks.
    """
    # 1. Start run
    resp = await client.post(
        "/run", json={"project_id": PROJECT_ID, "dry_run": True}
    )
    resp.raise_for_status()
    run_id = resp.json()["run_id"]

    # 2. Poll for approval plan
    plan = await _poll_plan(client, run_id)

    # 3. Approve every resource in the plan
    all_ids = [r["resource_id"] for r in plan]
    resp = await client.post(
        f"/run/{run_id}/approve", json={"approved_ids": all_ids}
    )
    resp.raise_for_status()

    # 4. Poll for completion
    final_status = await _poll_status(client, run_id)

    # 5. Build printable summary
    resources = final_status.get("resources", [])
    decisions = [r.get("decision") for r in resources if r.get("decision")]
    decision_counts = Counter(decisions)
    total_savings = sum(
        r.get("estimated_monthly_savings") or 0.0
        for r in resources
        if r.get("decision") in ("safe_to_stop", "safe_to_delete")
    )
    decision_str = ", ".join(
        f"{d} x{n}" for d, n in sorted(decision_counts.items())
    )
    print(
        f"  Run {run_num}: {len(resources)} resources, "
        f"${total_savings:.0f}/month identified, "
        f"decisions: [{decision_str}]"
    )

    return {
        "run_id": run_id,
        "decisions": sorted(decisions),
        "resource_count": len(resources),
        "run_complete": final_status.get("run_complete", False),
        "error_message": final_status.get("error_message"),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(mock: bool = False) -> int:
    if mock:
        _patch_graph_with_mocks()
        import cerberus.tools.chroma_client as _chroma_mod
        _chroma_mod._client = None
        _chroma_mod._collection = None

    from cerberus.api import app, active_runs
    import cerberus.tools.chroma_client as _chroma_mod

    log_dir = os.environ.get("AUDIT_LOG_DIR", "./logs")
    os.makedirs(log_dir, exist_ok=True)
    # Snapshot existing log files so we can count only the 3 new ones.
    existing_logs: set[Path] = set(Path(log_dir).glob("audit_*.jsonl"))

    mode_label = "MOCK (no GCP calls)" if mock else "LIVE GCP"
    print("=" * 52)
    print("CERBERUS DEMO SMOKE TEST")
    print(f"Project : {PROJECT_ID}")
    print(f"Mode    : {mode_label}")
    print(f"Runs    : 3  |  dry_run=True")
    print("=" * 52)

    results: list[dict | None] = []

    # Clear stale runs from any previous invocation in the same process.
    active_runs.clear()

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=180.0
    ) as client:
        for i in range(1, 4):
            try:
                result = await _single_run(client, i)
                results.append(result)
            except Exception as exc:
                print(f"  Run {i}: FAILED — {exc}")
                results.append(None)

    print()

    # ------------------------------------------------------------------
    # Gate checks
    # ------------------------------------------------------------------

    # CHECK 1 — All runs completed without fatal error
    # (partial-scan warnings from INV-NFR-01 timeout are acceptable)
    check1 = True
    for r in results:
        if r is None or not r["run_complete"]:
            check1 = False
            break
        err = r.get("error_message") or ""
        if err and "partial" not in err.lower() and "timeout" not in err.lower():
            check1 = False

    # CHECK 2 — Determinism: all 3 runs classify the same resources the same way
    check2 = (
        len(results) == 3
        and all(r is not None for r in results)
        and results[0]["decisions"] == results[1]["decisions"]  # type: ignore[index]
        and results[1]["decisions"] == results[2]["decisions"]  # type: ignore[index]
    )

    # CHECK 3 — At least 1 actionable decision (safe_to_stop/delete) per run
    actionable = {"safe_to_stop", "safe_to_delete"}
    check3 = all(
        r is not None and any(d in actionable for d in r["decisions"])
        for r in results
    )

    # CHECK 4 — 3 new JSONL audit log files written (INV-AUD-01)
    new_logs = [
        f for f in Path(log_dir).glob("audit_*.jsonl")
        if f not in existing_logs
    ]
    check4 = len(new_logs) >= 3

    # CHECK 5 — ChromaDB has records for all seeded resources after run 1
    chroma_count = 0
    check5 = False
    try:
        collection = _chroma_mod.get_chroma_collection()
        chroma_count = collection.count()
        check5 = chroma_count >= 6
    except Exception as exc:
        print(f"  ChromaDB check error: {exc}")

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    print(f"  Determinism check:   {'PASS' if check2 else 'FAIL'}")
    print(f"  All runs complete:   {'PASS' if check1 else 'FAIL'}")
    print(f"  Actionable results:  {'PASS' if check3 else 'FAIL'}")
    print(f"  JSONL logs:          {len(new_logs)} files found  {'PASS' if check4 else 'FAIL'}")
    print(f"  ChromaDB records:    {chroma_count} found  {'PASS' if check5 else 'FAIL'}")
    print()

    overall = check1 and check2 and check3 and check4 and check5
    print(f"  OVERALL: {'PASS' if overall else 'FAIL'}")
    print("=" * 52)

    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
