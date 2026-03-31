"""
test_e2e.py — System-level regression guard for every Cerberus invariant.

Runs the full pipeline with mock GCP nodes (no real API calls) and asserts
on plan state, execution outcomes, JSONL audit log, and ChromaDB records.

Invariants covered: all INV-* from CLAUDE.md.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

import pytest
from langgraph.checkpoint.memory import MemorySaver

import cerberus.tools.chroma_client as _chroma_mod
from cerberus.graph import _build_graph
from cerberus.state import initialise_state, VALID_DECISIONS

# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

PROJECT_ID = "nexus-tech-dev-e2e-test"
_NOW = datetime.now(tz=timezone.utc)
_CREATION_TS = (_NOW - timedelta(days=30)).isoformat()
_LAST_ACTIVITY_80H = (_NOW - timedelta(hours=80)).isoformat()  # > CPU_IDLE_WINDOW_HOURS (72h)

# Resource IDs — stable references used throughout assertions
VM_DEPARTED = "vm-departed"
VM_ACTIVE = "vm-active"
VM_NOOWNER = "vm-noowner"
DISK_SENSITIVE = "disk-sensitive"
DISK_PLAIN = "disk-plain"
IP_ACTIVE = "ip-active"

ALL_RESOURCE_IDS = [VM_DEPARTED, VM_ACTIVE, VM_NOOWNER, DISK_SENSITIVE, DISK_PLAIN, IP_ACTIVE]
ALL_VM_IDS = [VM_DEPARTED, VM_ACTIVE, VM_NOOWNER]


# ---------------------------------------------------------------------------
# Mock nodes
# ---------------------------------------------------------------------------


def _base_record(
    resource_id: str,
    resource_type: str,
    flagged: bool = False,
    labels: dict | None = None,
) -> dict:
    """Minimal valid ResourceRecord (all four INV-SCAN-01 required fields present)."""
    return {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "region": "us-central1",
        "creation_timestamp": _CREATION_TS,
        "last_activity_timestamp": _LAST_ACTIVITY_80H,
        "estimated_monthly_cost": 30.0,
        "ownership_status": None,
        "owner_email": None,
        "owner_iam_active": None,
        "flagged_for_review": flagged,
        "decision": None,
        "reasoning": None,
        "estimated_monthly_savings": None,
        "outcome": None,
        # Internal — used by mock_enrich to drive ownership logic
        "_labels": labels or {},
    }


async def mock_scan_node(state):
    """Return 6 deterministic resources matching the e2e scenario spec."""
    resources = [
        # 3 VMs — all idle > 72h (INV-SCAN-02 would flag them as idle)
        _base_record(VM_DEPARTED, "vm"),
        _base_record(VM_ACTIVE, "vm"),
        _base_record(VM_NOOWNER, "vm"),
        # 1 orphaned disk: departed_owner, data-classification=sensitive (INV-SCAN-03)
        _base_record(
            DISK_SENSITIVE,
            "orphaned_disk",
            flagged=True,  # INV-SCAN-03: sensitive label → flagged at scan time
            labels={"data-classification": "sensitive"},
        ),
        # 1 orphaned disk: no labels → will resolve to no_owner in enrich
        _base_record(DISK_PLAIN, "orphaned_disk"),
        # 1 unused IP: active_owner
        _base_record(IP_ACTIVE, "unused_ip"),
    ]
    state["resources"] = resources
    state["expected_resource_count"] = len(resources)
    return state


async def mock_enrich_node(state):
    """Set ownership_status without real GCP calls (INV-ENR-01, INV-ENR-02, INV-ENR-03)."""
    _ownership_map = {
        VM_DEPARTED:    ("departed_owner", "departed@nexus.tech", False),
        VM_ACTIVE:      ("active_owner",   "active@nexus.tech",   True),
        VM_NOOWNER:     ("no_owner",       None,                  False),
        DISK_SENSITIVE: ("departed_owner", "departed@nexus.tech", False),
        DISK_PLAIN:     ("no_owner",       None,                  False),
        IP_ACTIVE:      ("active_owner",   "active@nexus.tech",   True),
    }

    for r in state["resources"]:
        rid = r["resource_id"]
        status, email, iam_active = _ownership_map.get(rid, ("no_owner", None, False))
        r["ownership_status"] = status
        r["owner_email"] = email
        r["owner_iam_active"] = iam_active
        # INV-ENR-03 enforcement point 1: no_owner → flagged_for_review=True
        r["flagged_for_review"] = r.get("flagged_for_review", False) or (status == "no_owner")

    return state


async def mock_reason_node(state):
    """Classify resources without calling Gemini (INV-RSN-01, INV-RSN-02, INV-RSN-03)."""
    _decision_map = {
        VM_DEPARTED:    ("safe_to_stop",   "CPU averaged 1% over 80 hours, below the 5% idle threshold. Owner departed 120 days ago with no recent IAM activity. Estimated waste $30.00/month."),
        VM_ACTIVE:      ("safe_to_stop",   "CPU averaged 1% over 80 hours, meeting the idle threshold criteria. Active owner confirmed but resource appears unused. Estimated cost $30.00/month."),
        VM_NOOWNER:     ("needs_review",   "Resource has no identified owner and is flagged for human review. CPU idle 80 hours but manual confirmation required before action."),
        DISK_SENSITIVE: ("needs_review",   "Disk is flagged sensitive (data-classification=sensitive label) and requires human review. Owner departed; $30.00/month estimated cost."),
        DISK_PLAIN:     ("needs_review",   "No owner could be resolved for this orphaned disk costing $30.00/month. Flagged for human review before any action."),
        IP_ACTIVE:      ("safe_to_delete", "Static IP has no forwarding rule or VM association and costs $30.00/month. Owner confirmed active; IP appears abandoned."),
    }

    for r in state["resources"]:
        rid = r["resource_id"]
        decision, reasoning = _decision_map.get(rid, ("needs_review", "Unknown resource — flagged for review."))

        # INV-ENR-03 enforcement point 2 (reason_node): override if flagged_for_review
        if r.get("flagged_for_review") and decision != "needs_review":
            decision = "needs_review"

        # INV-RSN-01: decision must be in VALID_DECISIONS
        assert decision in VALID_DECISIONS, f"Mock produced invalid decision {decision!r}"

        # INV-RSN-03: actionable decisions must have non-None non-negative savings
        savings = 30.0 if decision in ("safe_to_stop", "safe_to_delete") else 0.0

        r["decision"] = decision
        r["reasoning"] = reasoning
        r["estimated_monthly_savings"] = savings

    return state


async def mock_revalidate_node(state):
    """Pass-through — no real GCP re-check needed in mock environment."""
    return state


# ---------------------------------------------------------------------------
# Main e2e test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_mock(tmp_path):
    """
    Full pipeline integration test — the regression guard for every invariant.

    Approval strategy: approve all 6 resource IDs so that audit_node writes
    6 DRY_RUN entries + 1 COST_SUMMARY, satisfying the >= 6 JSONL-lines assertion
    and the >= 6 ChromaDB-records assertion.  The flagged_for_review flag on
    no_owner / sensitive resources (INV-ENR-03) is asserted independently.
    In live mode these resources would receive SKIPPED_GUARDRAIL in execute_node;
    in dry_run mode all approved resources unconditionally receive DRY_RUN.
    """
    # ------------------------------------------------------------------
    # Setup: isolated storage directories and reset ChromaDB singleton
    # ------------------------------------------------------------------
    log_dir = str(tmp_path / "logs")
    chroma_dir = str(tmp_path / "chroma")
    os.environ["AUDIT_LOG_DIR"] = log_dir
    os.environ["CHROMA_PERSIST_DIR"] = chroma_dir

    # Reset module-level ChromaDB singleton so the temp path is used
    _chroma_mod._client = None
    _chroma_mod._collection = None

    # ------------------------------------------------------------------
    # Build graph with mock nodes; compile with MemorySaver + interrupt_before.
    # interrupt_before=["approve_node"] is used instead of interrupt() inside
    # approve_node because langgraph.types.interrupt() requires Python 3.11+
    # in async contexts (get_config() fails on Python 3.10).
    # ------------------------------------------------------------------
    graph = _build_graph(
        _scan=mock_scan_node,
        _enrich=mock_enrich_node,
        _reason=mock_reason_node,
        _revalidate=mock_revalidate_node,
        # execute_node and audit_node are real — they handle dry_run and
        # write JSONL/ChromaDB without any GCP calls.
    ).compile(
        checkpointer=MemorySaver(),
        interrupt_before=["approve_node"],
    )

    state = initialise_state(PROJECT_ID, dry_run=True)
    config = {"configurable": {"thread_id": "e2e-test-01"}}

    # ------------------------------------------------------------------
    # Phase 1: scan → enrich → reason → interrupt before approve_node
    # ------------------------------------------------------------------
    async for _ in graph.astream_events(state, config=config, version="v2"):
        pass

    graph_state = await graph.aget_state(config)

    # With interrupt_before=["approve_node"], the graph pauses *before* approve_node.
    # graph_state.next contains the node(s) that would run next.
    assert graph_state.next and "approve_node" in graph_state.next, \
        "Graph must have paused before approve_node (interrupt_before)"

    # The approval plan is the resource list from current graph state.
    plan: list[dict] = graph_state.values.get("resources", [])

    # ------------------------------------------------------------------
    # Step 3 assertions — plan state
    # ------------------------------------------------------------------

    # 3a. All 6 resources discovered
    assert len(plan) == 6, f"Expected 6 resources in plan, got {len(plan)}"

    plan_by_id = {r["resource_id"]: r for r in plan}

    # 3b. Sensitive disk has flagged_for_review=True (INV-SCAN-03, INV-ENR-03)
    # Note: plan is the approval_payload from approve_node which only includes
    # display fields — check the in-progress graph state values instead.
    state_values = graph_state.values
    resources_by_id = {r["resource_id"]: r for r in state_values["resources"]}

    assert resources_by_id[DISK_SENSITIVE]["flagged_for_review"] is True, \
        "INV-SCAN-03: sensitive disk must have flagged_for_review=True"

    # 3c. no_owner resources have decision="needs_review" (INV-ENR-03)
    for rid in (VM_NOOWNER, DISK_PLAIN):
        r = resources_by_id[rid]
        assert r["ownership_status"] == "no_owner", \
            f"{rid} must have ownership_status=no_owner"
        assert r["decision"] == "needs_review", \
            f"INV-ENR-03: {rid} (no_owner) must have decision=needs_review, got {r['decision']!r}"

    # 3d. No resource has decision=None (INV-RSN-01)
    for r in state_values["resources"]:
        assert r["decision"] is not None, \
            f"INV-RSN-01: resource {r['resource_id']} has decision=None"

    # 3e. No resource has ownership_status=None (INV-ENR-01)
    for r in state_values["resources"]:
        assert r["ownership_status"] is not None, \
            f"INV-ENR-01: resource {r['resource_id']} has ownership_status=None"

    # 3f. Reasoning is non-empty for every resource (INV-RSN-02)
    for r in state_values["resources"]:
        assert r.get("reasoning"), \
            f"INV-RSN-02: resource {r['resource_id']} has empty reasoning"

    # ------------------------------------------------------------------
    # Phase 2: inject approved_actions then resume (Python 3.10 compatible).
    # interrupt() inside async nodes requires Python 3.11+; use aupdate_state
    # + astream(None) instead.
    # ------------------------------------------------------------------
    all_resources = graph_state.values["resources"]
    await graph.aupdate_state(
        config,
        {"approved_actions": all_resources, "mutation_count": 0},
    )

    async for _ in graph.astream_events(None, config=config, version="v2"):
        pass

    final_graph_state = await graph.aget_state(config)
    final: dict = final_graph_state.values

    # ------------------------------------------------------------------
    # Step 5 assertions — final state
    # ------------------------------------------------------------------

    final_resources_by_id = {r["resource_id"]: r for r in final["resources"]}

    # 5a. mutation_count == 0 (dry_run — INV-UI-03)
    assert final["mutation_count"] == 0, \
        f"INV-UI-03: dry_run must not increment mutation_count, got {final['mutation_count']}"

    # 5b. run_complete == True (INV-NFR-03)
    assert final["run_complete"] is True, "run_complete must be True after audit_node"

    # 5c. error_message is None (clean run)
    assert final.get("error_message") is None, \
        f"Unexpected error_message: {final.get('error_message')!r}"

    # 5d. All 3 VMs have outcome="DRY_RUN" (INV-UI-03, execute_node dry_run path)
    for vid in ALL_VM_IDS:
        assert final_resources_by_id[vid]["outcome"] == "DRY_RUN", \
            f"INV-UI-03: {vid} must have outcome=DRY_RUN, got {final_resources_by_id[vid]['outcome']!r}"

    # 5e. no_owner disk: flagged_for_review=True is the invariant (INV-ENR-03).
    #     In dry_run all approved resources receive DRY_RUN regardless of flags.
    #     In live mode this resource would receive SKIPPED_GUARDRAIL.
    no_owner_disk = final_resources_by_id[DISK_PLAIN]
    assert no_owner_disk["flagged_for_review"] is True, \
        "INV-ENR-03: no_owner disk must have flagged_for_review=True"
    assert no_owner_disk["outcome"] in ("DRY_RUN", "SKIPPED_GUARDRAIL"), \
        f"no_owner disk outcome unexpected: {no_owner_disk['outcome']!r}"

    # 5f. JSONL audit log: file exists and has >= 6 lines
    #     (6 DRY_RUN entries, one per approved resource, + 1 COST_SUMMARY = 7)
    run_id = final["run_id"]
    audit_path = os.path.join(log_dir, f"audit_{run_id}.jsonl")
    assert os.path.exists(audit_path), f"JSONL audit log not found at {audit_path}"

    with open(audit_path, encoding="utf-8") as fh:
        log_lines = [json.loads(line) for line in fh if line.strip()]

    assert len(log_lines) >= 6, \
        f"INV-AUD-01: expected >= 6 JSONL entries, got {len(log_lines)}"

    # 5g. COST_SUMMARY entry exists (INV-AUD-02)
    cost_summary_lines = [l for l in log_lines if l.get("action_type") == "COST_SUMMARY"]
    assert len(cost_summary_lines) == 1, \
        f"INV-AUD-02: expected exactly 1 COST_SUMMARY entry, got {len(cost_summary_lines)}"

    summary_payload = json.loads(cost_summary_lines[0]["llm_reasoning"])
    assert summary_payload["resources_scanned"] == 6, \
        f"COST_SUMMARY resources_scanned should be 6, got {summary_payload['resources_scanned']}"

    # All JSONL entries include the mandatory fields (INV-AUD-01)
    mandatory_fields = {"timestamp", "action_type", "actor", "outcome", "run_id", "project_id"}
    for entry in log_lines:
        missing = mandatory_fields - entry.keys()
        assert not missing, f"INV-AUD-01: JSONL entry missing fields {missing}: {entry}"

    # 5h. ChromaDB collection has >= 6 records (one per resource with an outcome)
    collection = _chroma_mod.get_chroma_collection()
    chroma_count = collection.count()
    assert chroma_count >= 6, \
        f"ChromaDB must have >= 6 records after the run, got {chroma_count}"

    # 5i. INV-SEC-02: audit entries must not contain credential fields
    credential_fields = {"service_account_key_path", "gcp_service_account_key_path", "api_key", "gemini_api_key"}
    for entry in log_lines:
        leaked = credential_fields & entry.keys()
        assert not leaked, f"INV-SEC-02: credential field(s) {leaked} found in audit entry"
