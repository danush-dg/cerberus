"""Tests for reason_node — Tasks 4.1, 4.2 & 4.3."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cerberus.nodes.reason_node import (
    ResourceDecision,
    SYSTEM_PROMPT,
    GEMINI_INTER_REQUEST_DELAY_SECONDS,
    build_resource_prompt,
    classify_resource,
    reason_node,
)
from cerberus.state import VALID_DECISIONS, initialise_state


def _make_resource(resource_id: str = "vm-1", **kwargs) -> dict:
    base = {
        "resource_id": resource_id,
        "resource_type": "gce_vm",
        "region": "us-central1",
        "creation_timestamp": "2025-01-01T00:00:00Z",
        "last_activity_timestamp": None,
        "estimated_monthly_cost": 50.0,
        "ownership_status": "active_owner",
        "owner_email": "alice@x.com",
        "owner_iam_active": True,
        "flagged_for_review": False,
        "decision": None,
        "reasoning": None,
        "estimated_monthly_savings": None,
        "outcome": None,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT content requirements (INV-RSN-01, INV-RSN-02, INV-ENR-03)
# ---------------------------------------------------------------------------

def test_system_prompt_contains_all_four_decisions():
    for d in ["safe_to_stop", "safe_to_delete", "needs_review", "skip"]:
        assert d in SYSTEM_PROMPT, f"SYSTEM_PROMPT missing decision value: {d}"


def test_system_prompt_contains_no_owner_rule():
    assert "no_owner" in SYSTEM_PROMPT
    assert "needs_review" in SYSTEM_PROMPT


def test_system_prompt_contains_sentence_limit():
    assert "3 sentences" in SYSTEM_PROMPT


def test_system_prompt_contains_flagged_for_review_rule():
    assert "flagged_for_review" in SYSTEM_PROMPT


def test_system_prompt_contains_null_cost_rule():
    assert "null" in SYSTEM_PROMPT or "estimated_monthly_cost" in SYSTEM_PROMPT


def test_system_prompt_embeds_json_schema():
    # Schema string should be embedded at module load time
    assert "ResourceDecision" in SYSTEM_PROMPT or "decision" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# ResourceDecision schema (INV-RSN-01)
# ---------------------------------------------------------------------------

def test_resource_decision_valid_decisions():
    for d in ["safe_to_stop", "safe_to_delete", "needs_review", "skip"]:
        rd = ResourceDecision(decision=d, reasoning="Test.", estimated_monthly_savings=10.0)
        assert rd.decision == d


def test_resource_decision_rejects_invalid_decision():
    with pytest.raises(Exception):
        ResourceDecision(decision="delete_now", reasoning="Bad.", estimated_monthly_savings=0.0)


def test_resource_decision_fields_present():
    rd = ResourceDecision(decision="skip", reasoning="No action needed.", estimated_monthly_savings=0.0)
    assert rd.reasoning == "No action needed."
    assert rd.estimated_monthly_savings == 0.0


# ---------------------------------------------------------------------------
# build_resource_prompt (INV-RSN-02)
# ---------------------------------------------------------------------------

def test_build_prompt_includes_cost(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    r = _make_resource(estimated_monthly_cost=45.0)
    prompt = build_resource_prompt(r)
    assert "45.0" in prompt


def test_build_prompt_includes_flagged_status(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    r = _make_resource(flagged_for_review=True)
    prompt = build_resource_prompt(r)
    assert "flagged_for_review" in prompt
    assert "true" in prompt.lower()


def test_build_prompt_includes_all_required_fields(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    r = _make_resource()
    prompt = build_resource_prompt(r)
    for field in [
        "resource_id", "resource_type", "region", "creation_timestamp",
        "last_activity_timestamp", "estimated_monthly_cost", "ownership_status",
        "owner_email", "owner_iam_active", "flagged_for_review",
    ]:
        assert field in prompt, f"build_resource_prompt missing field: {field}"


def test_build_prompt_appends_chroma_history(mocker):
    mocker.patch(
        "cerberus.nodes.reason_node.query_resource_history",
        return_value={"decision": "safe_to_stop", "scanned_at": "2025-03-01T00:00:00"},
    )
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    r = _make_resource()
    prompt = build_resource_prompt(r)
    assert "Previous classification" in prompt
    assert "safe_to_stop" in prompt


def test_build_prompt_appends_owner_context(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch(
        "cerberus.nodes.reason_node.query_owner_history",
        return_value=[{"resource_id": "disk-1"}, {"resource_id": "vm-2"}],
    )
    r = _make_resource(owner_email="alice@x.com")
    prompt = build_resource_prompt(r, project_id="nexus-tech-dev-1")
    assert "2 other resources" in prompt


def test_build_prompt_omits_chroma_on_empty(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    r = _make_resource()
    prompt = build_resource_prompt(r)
    assert "Previous classification" not in prompt
    assert "other resources" not in prompt


def test_build_prompt_flagged_false_shows_false(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    r = _make_resource(flagged_for_review=False)
    prompt = build_resource_prompt(r)
    assert "false" in prompt.lower()


# ---------------------------------------------------------------------------
# Module-level constant
# ---------------------------------------------------------------------------

def test_delay_constant_is_half_second():
    assert GEMINI_INTER_REQUEST_DELAY_SECONDS == 0.5


# ---------------------------------------------------------------------------
# Task 4.2 — classify_resource with post-LLM validation
# ---------------------------------------------------------------------------

def _mock_gemini(decision="safe_to_stop", reasoning="VM idle for 120 hours. Cost is $45/mo. No recent activity.", savings=45.0):
    """Return a mock Client whose models.generate_content returns valid JSON."""
    payload = json.dumps({
        "decision": decision,
        "reasoning": reasoning,
        "estimated_monthly_savings": savings,
    })
    mock_response = MagicMock()
    mock_response.text = payload
    client = MagicMock()
    client.models.generate_content.return_value = mock_response
    return client


@pytest.mark.asyncio
async def test_valid_response_applied(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    client = _mock_gemini(decision="safe_to_stop", savings=45.0)
    r = _make_resource("vm-1", estimated_monthly_cost=45.0, ownership_status="departed_owner")
    result = await classify_resource(r, client)
    assert result["decision"] in VALID_DECISIONS
    assert result["reasoning"] is not None


@pytest.mark.asyncio
async def test_invalid_decision_overridden(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    client = _mock_gemini(decision="unclear")
    result = await classify_resource(_make_resource("vm-1"), client)
    assert result["decision"] == "needs_review"


@pytest.mark.asyncio
async def test_flagged_resource_forced_to_needs_review(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    client = _mock_gemini(decision="safe_to_delete", savings=50.0)
    r = _make_resource("vm-1", flagged_for_review=True, ownership_status="no_owner")
    result = await classify_resource(r, client)
    assert result["decision"] == "needs_review"


@pytest.mark.asyncio
async def test_zero_savings_overridden_for_actionable(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    client = _mock_gemini(decision="safe_to_stop", savings=0.0)
    r = _make_resource("vm-1", estimated_monthly_cost=45.0, ownership_status="active_owner")
    result = await classify_resource(r, client)
    assert result["estimated_monthly_savings"] == 45.0


@pytest.mark.asyncio
async def test_json_failure_returns_needs_review(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    mock_response = MagicMock()
    mock_response.text = "not valid json {{{"
    client = MagicMock()
    client.models.generate_content.return_value = mock_response
    result = await classify_resource(_make_resource("vm-1"), client)
    assert result["decision"] == "needs_review"
    assert "unparseable" in result["reasoning"]


@pytest.mark.asyncio
async def test_reasoning_truncated_to_3_sentences(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    long_reasoning = "Sentence one costs $50. Sentence two is idle 100h. Sentence three is fine. Sentence four should be cut."
    client = _mock_gemini(decision="safe_to_stop", reasoning=long_reasoning, savings=50.0)
    result = await classify_resource(_make_resource("vm-1", estimated_monthly_cost=50.0), client)
    sentences = [s.strip() for s in result["reasoning"].split(".") if s.strip()]
    assert len(sentences) <= 3


@pytest.mark.asyncio
async def test_negative_savings_clamped_to_zero(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    client = _mock_gemini(decision="needs_review", savings=-10.0)
    result = await classify_resource(_make_resource("vm-1"), client)
    assert result["estimated_monthly_savings"] >= 0.0


@pytest.mark.asyncio
async def test_empty_reasoning_retried_then_fallback(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    empty_payload = json.dumps({"decision": "skip", "reasoning": "", "estimated_monthly_savings": 0.0})
    mock_response = MagicMock()
    mock_response.text = empty_payload
    client = MagicMock()
    client.models.generate_content.return_value = mock_response
    result = await classify_resource(_make_resource("vm-1"), client)
    assert result["reasoning"]  # non-empty after fallback
    assert result["decision"] == "needs_review"


# ---------------------------------------------------------------------------
# Task 4.3 — reason_node assembly
# ---------------------------------------------------------------------------

def _make_state_with_resources(*resource_ids: str) -> dict:
    state = initialise_state("nexus-tech-dev-1")
    state["resources"] = [_make_resource(rid) for rid in resource_ids]
    return state


def _mock_gemini_client(decision="safe_to_stop", reasoning="VM idle for 120 hours. Cost is $45/mo. No activity.", savings=45.0):
    payload = json.dumps({
        "decision": decision,
        "reasoning": reasoning,
        "estimated_monthly_savings": savings,
    })
    mock_response = MagicMock()
    mock_response.text = payload
    client = MagicMock()
    client.models.generate_content.return_value = mock_response
    return client


@pytest.mark.asyncio
async def test_all_resources_get_non_none_decision(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    mocker.patch(
        "cerberus.nodes.reason_node.genai.Client",
        return_value=_mock_gemini_client(),
    )
    mocker.patch("cerberus.nodes.reason_node.get_config", return_value=MagicMock(
        gemini_api_key="fake-key", gemini_model="gemini-1.5-pro-002"
    ))
    mocker.patch("asyncio.sleep")

    state = _make_state_with_resources("vm-1", "vm-2")
    result = await reason_node(state)
    for r in result["resources"]:
        assert r["decision"] in VALID_DECISIONS


@pytest.mark.asyncio
async def test_sequential_execution_respects_delay(mocker):
    mocker.patch("cerberus.nodes.reason_node.query_resource_history", return_value=None)
    mocker.patch("cerberus.nodes.reason_node.query_owner_history", return_value=[])
    mocker.patch(
        "cerberus.nodes.reason_node.genai.Client",
        return_value=_mock_gemini_client(),
    )
    mocker.patch("cerberus.nodes.reason_node.get_config", return_value=MagicMock(
        gemini_api_key="fake-key", gemini_model="gemini-1.5-pro-002"
    ))
    sleep_mock = mocker.patch("cerberus.nodes.reason_node.asyncio.sleep")

    state = _make_state_with_resources("vm-1", "vm-2", "vm-3")
    await reason_node(state)
    assert sleep_mock.call_count == 3  # one sleep per resource
