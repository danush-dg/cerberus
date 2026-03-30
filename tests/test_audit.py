from __future__ import annotations

import json
import os
from unittest.mock import Mock, patch

import pytest

from cerberus.nodes.audit_node import AuditEntry, audit_node, write_audit_entry
from cerberus.state import initialise_state
from tests.conftest import make_resource_record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_resource(resource_id: str, outcome: str, estimated_monthly_savings: float = 0.0) -> dict:
    return make_resource_record(
        resource_id,
        decision="safe_to_stop",
        reasoning="Idle for 72 hours at 2% CPU utilisation, costing $45/mo.",
        outcome=outcome,
        estimated_monthly_savings=estimated_monthly_savings,
    )


def make_state(resources: list[dict], log_dir: str | None = None) -> dict:
    state = initialise_state("nexus-tech-dev-test")
    state["resources"] = resources
    state["approved_actions"] = [r for r in resources if r.get("outcome") in ("SUCCESS", "FAILED")]
    if log_dir:
        os.environ["AUDIT_LOG_DIR"] = log_dir
    return state


def make_audit_entry() -> AuditEntry:
    return AuditEntry(
        timestamp="2026-01-01T00:00:00",
        resource_id="vm-test",
        action_type="safe_to_stop",
        llm_reasoning="Idle for 72h.",
        actor="agent",
        outcome="SUCCESS",
        run_id="run-1",
        session_mutation_count=1,
        project_id="nexus-tech-dev-test",
    )


# ---------------------------------------------------------------------------
# AuditEntry schema
# ---------------------------------------------------------------------------

def test_audit_entry_has_no_credential_fields():
    fields = AuditEntry.model_fields.keys()
    forbidden = {"service_account_key", "credentials", "key_path", "api_key", "secret"}
    assert not (forbidden & set(fields)), f"Credential fields found in AuditEntry: {forbidden & set(fields)}"


def test_audit_entry_valid():
    entry = make_audit_entry()
    assert entry.run_id == "run-1"
    assert entry.outcome == "SUCCESS"


# ---------------------------------------------------------------------------
# write_audit_entry
# ---------------------------------------------------------------------------

def test_write_audit_entry_creates_file(tmp_path):
    entry = make_audit_entry()
    write_audit_entry(entry, str(tmp_path / "logs"), "run-1")
    log = (tmp_path / "logs" / "audit_run-1.jsonl").read_text()
    data = json.loads(log.strip())
    assert data["resource_id"] == "vm-test"


def test_write_audit_entry_appends(tmp_path):
    log_dir = str(tmp_path / "logs")
    entry = make_audit_entry()
    write_audit_entry(entry, log_dir, "run-1")
    write_audit_entry(entry, log_dir, "run-1")
    lines = (tmp_path / "logs" / "audit_run-1.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2


def test_jsonl_write_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.open", Mock(side_effect=IOError("disk full")))
    with pytest.raises(IOError):
        write_audit_entry(make_audit_entry(), "/fake/dir", "run-1")


# ---------------------------------------------------------------------------
# audit_node — JSONL per resource
# ---------------------------------------------------------------------------

def test_jsonl_entry_per_resource(tmp_path):
    log_dir = str(tmp_path / "logs")
    os.environ["AUDIT_LOG_DIR"] = log_dir

    resources = [
        make_resource("vm-1", outcome="SUCCESS", estimated_monthly_savings=45.0),
        make_resource("vm-2", outcome="FAILED", estimated_monthly_savings=30.0),
    ]
    state = make_state(resources)

    with patch("cerberus.nodes.audit_node.upsert_resource_record"):
        result = audit_node(state)

    log_path = result["audit_log_path"]
    lines = open(log_path).readlines()
    for line in lines:
        json.loads(line)  # every line must be valid JSON

    # 2 resource entries + 1 COST_SUMMARY
    assert len(lines) == 3


def test_only_resources_with_outcome_logged(tmp_path):
    log_dir = str(tmp_path / "logs")
    os.environ["AUDIT_LOG_DIR"] = log_dir

    resources = [
        make_resource("vm-1", outcome="SUCCESS"),
        make_resource_record("vm-2"),  # no outcome
    ]
    state = make_state(resources)

    with patch("cerberus.nodes.audit_node.upsert_resource_record"):
        result = audit_node(state)

    lines = [json.loads(l) for l in open(result["audit_log_path"])]
    resource_lines = [l for l in lines if l["action_type"] != "COST_SUMMARY"]
    assert len(resource_lines) == 1
    assert resource_lines[0]["resource_id"] == "vm-1"


# ---------------------------------------------------------------------------
# audit_node — COST_SUMMARY
# ---------------------------------------------------------------------------

def test_cost_summary_success_only(tmp_path):
    log_dir = str(tmp_path / "logs")
    os.environ["AUDIT_LOG_DIR"] = log_dir

    resources = [
        make_resource("vm-1", outcome="SUCCESS", estimated_monthly_savings=45.0),
        make_resource("vm-2", outcome="FAILED", estimated_monthly_savings=30.0),
    ]
    state = make_state(resources)

    with patch("cerberus.nodes.audit_node.upsert_resource_record"):
        result = audit_node(state)

    lines = [json.loads(l) for l in open(result["audit_log_path"])]
    summary_line = next(l for l in lines if l["action_type"] == "COST_SUMMARY")
    data = json.loads(summary_line["llm_reasoning"])
    assert data["estimated_monthly_savings_recovered"] == 45.0  # not 75.0


def test_cost_summary_fields_present(tmp_path):
    log_dir = str(tmp_path / "logs")
    os.environ["AUDIT_LOG_DIR"] = log_dir

    resources = [make_resource("vm-1", outcome="SUCCESS", estimated_monthly_savings=10.0)]
    state = make_state(resources)

    with patch("cerberus.nodes.audit_node.upsert_resource_record"):
        result = audit_node(state)

    lines = [json.loads(l) for l in open(result["audit_log_path"])]
    summary = next(l for l in lines if l["action_type"] == "COST_SUMMARY")
    data = json.loads(summary["llm_reasoning"])
    for key in ("resources_scanned", "total_waste_identified", "actions_approved",
                "actions_executed", "estimated_monthly_savings_recovered"):
        assert key in data, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# audit_node — ChromaDB failure does not raise
# ---------------------------------------------------------------------------

def test_chroma_failure_does_not_raise(tmp_path):
    log_dir = str(tmp_path / "logs")
    os.environ["AUDIT_LOG_DIR"] = log_dir

    resources = [make_resource("vm-1", outcome="SUCCESS")]
    state = make_state(resources)

    with patch("cerberus.nodes.audit_node.upsert_resource_record", side_effect=Exception("chroma error")):
        result = audit_node(state)  # must not raise

    assert result["run_complete"] is True


# ---------------------------------------------------------------------------
# audit_node — run_complete always set
# ---------------------------------------------------------------------------

def test_run_complete_always_set(tmp_path):
    log_dir = str(tmp_path / "logs")
    os.environ["AUDIT_LOG_DIR"] = log_dir

    state = initialise_state("nexus-tech-dev-test")
    state["resources"] = []

    with patch("cerberus.nodes.audit_node.upsert_resource_record"):
        result = audit_node(state)

    assert result["run_complete"] is True


# ---------------------------------------------------------------------------
# audit_node — audit_log_path set in state
# ---------------------------------------------------------------------------

def test_audit_log_path_set(tmp_path):
    log_dir = str(tmp_path / "logs")
    os.environ["AUDIT_LOG_DIR"] = log_dir

    state = initialise_state("nexus-tech-dev-test")
    state["resources"] = []

    with patch("cerberus.nodes.audit_node.upsert_resource_record"):
        result = audit_node(state)

    assert result["audit_log_path"] is not None
    assert result["audit_log_path"].endswith(f"audit_{state['run_id']}.jsonl")
