"""tests/test_access.py — Unit tests for cerberus/nodes/access_node.py (Task 9.1)."""
from __future__ import annotations

import json
import pytest

from cerberus.nodes.access_node import IamRequest, IamProvisioningPlan, synthesize_iam_request


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VALID_PLAN = {
    "requester_email": "alice@example.com",
    "custom_role_id": "cerberus_bq_fraud_read_20260331",
    "permissions": [
        "bigquery.tables.get",
        "bigquery.tables.list",
        "bigquery.jobs.create",
    ],
    "binding_condition": (
        "resource.name.startsWith('projects/nexus-tech-dev-sandbox/datasets/fraud_transactions')"
    ),
    "budget_alert_threshold_usd": 200.0,
    "review_after_days": 90,
    "checklist": [
        "Step 1: Create custom role cerberus_bq_fraud_read_20260331 in nexus-tech-dev-sandbox",
        "Step 2: Bind alice@example.com to the custom role",
        "Step 3: Set resource-level IAM condition to fraud_transactions dataset",
        "Step 4: Configure $200 budget alert on nexus-tech-dev-sandbox",
        "Step 5: Schedule 90-day IAM binding review",
        "Step 6: Write JSONL audit entry for provisioning",
        "Step 7: Confirm access with alice@example.com",
    ],
    "reasoning": (
        "Granting bigquery.tables.get and bigquery.tables.list provides read-only "
        "access to the fraud_transactions dataset. The custom role avoids broad "
        "predefined roles. A 90-day review is scheduled per staleness policy."
    ),
}

_VALID_REQUEST = IamRequest(
    requester_email="alice@example.com",
    request_text="I need BigQuery read access for fraud_transactions",
    project_id="nexus-tech-dev-sandbox",
)


@pytest.fixture
def mock_gemini(mocker):
    """Return a valid full IamProvisioningPlan JSON."""
    mocker.patch(
        "cerberus.nodes.access_node.gcp_call_with_retry",
        return_value=json.dumps(_VALID_PLAN),
    )
    mocker.patch(
        "cerberus.nodes.access_node.get_config",
        return_value=_make_config(mocker),
    )


@pytest.fixture
def mock_gemini_short_checklist(mocker):
    """Return a plan with only 3 checklist items — should be padded to 7."""
    short_plan = dict(_VALID_PLAN)
    short_plan["checklist"] = [
        "Step 1: Create role",
        "Step 2: Bind user",
        "Step 3: Set alert",
    ]
    mocker.patch(
        "cerberus.nodes.access_node.gcp_call_with_retry",
        return_value=json.dumps(short_plan),
    )
    mocker.patch(
        "cerberus.nodes.access_node.get_config",
        return_value=_make_config(mocker),
    )


@pytest.fixture
def mock_gemini_wrong_days(mocker):
    """Return a plan where review_after_days=30 — should be overridden to 90."""
    wrong_days_plan = dict(_VALID_PLAN)
    wrong_days_plan["review_after_days"] = 30
    mocker.patch(
        "cerberus.nodes.access_node.gcp_call_with_retry",
        return_value=json.dumps(wrong_days_plan),
    )
    mocker.patch(
        "cerberus.nodes.access_node.get_config",
        return_value=_make_config(mocker),
    )


def _make_config(mocker):
    cfg = mocker.MagicMock()
    cfg.gemini_api_key = "test-key"
    cfg.gemini_model = "gemini-1.5-pro-002"
    cfg.allowed_project_pattern = "^nexus-tech-dev-[0-9a-z-]+$"
    return cfg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_synthesize_returns_custom_role(mock_gemini):
    plan = synthesize_iam_request(_VALID_REQUEST)

    assert isinstance(plan, IamProvisioningPlan)
    assert plan.custom_role_id.startswith("cerberus_")
    assert len(plan.permissions) >= 1
    assert all("bigquery" in p for p in plan.permissions)
    assert plan.review_after_days == 90
    assert plan.requester_email == "alice@example.com"


def test_checklist_always_seven_steps(mock_gemini_short_checklist):
    plan = synthesize_iam_request(_VALID_REQUEST)

    assert len(plan.checklist) == 7
    # Padded steps should follow the "Step N: Human review required" pattern
    assert "Human review required" in plan.checklist[3]
    assert "Human review required" in plan.checklist[4]
    assert "Human review required" in plan.checklist[5]
    assert "Human review required" in plan.checklist[6]


def test_review_days_override(mock_gemini_wrong_days):
    plan = synthesize_iam_request(_VALID_REQUEST)

    assert plan.review_after_days == 90


def test_invalid_project_raises(mock_gemini):
    with pytest.raises(ValueError, match="pattern|BLOCKED"):
        synthesize_iam_request(
            IamRequest(
                requester_email="alice@example.com",
                request_text="I need BigQuery access",
                project_id="nexus-tech-PROD-1",  # fails pattern — uppercase PROD
            )
        )


def test_gemini_not_called_on_invalid_project(mocker):
    """gcp_call_with_retry must not be called if project_id fails validation."""
    mock_retry = mocker.patch("cerberus.nodes.access_node.gcp_call_with_retry")
    mocker.patch(
        "cerberus.nodes.access_node.get_config",
        return_value=_make_config(mocker),
    )

    with pytest.raises(ValueError):
        synthesize_iam_request(
            IamRequest(
                requester_email="alice@example.com",
                request_text="I need BigQuery access",
                project_id="production-project-1",
            )
        )

    mock_retry.assert_not_called()


def test_parse_failure_raises_value_error(mocker):
    """If Gemini returns unparseable JSON, synthesize_iam_request raises ValueError."""
    mocker.patch(
        "cerberus.nodes.access_node.gcp_call_with_retry",
        return_value="not valid json {{{",
    )
    mocker.patch(
        "cerberus.nodes.access_node.get_config",
        return_value=_make_config(mocker),
    )

    with pytest.raises(ValueError, match="failed to parse"):
        synthesize_iam_request(_VALID_REQUEST)


def test_plan_has_all_required_fields(mock_gemini):
    plan = synthesize_iam_request(_VALID_REQUEST)

    assert plan.requester_email
    assert plan.custom_role_id
    assert isinstance(plan.permissions, list)
    assert plan.binding_condition
    assert plan.budget_alert_threshold_usd >= 0
    assert plan.review_after_days == 90
    assert len(plan.checklist) == 7
    assert plan.reasoning
