"""Task 10.2 — IAM Head tests."""
from __future__ import annotations

import json
import pytest

from cerberus.config import CerberusConfig
from cerberus.heads import iam_head
from cerberus.heads.iam_head import (
    _tickets,
    approve_ticket,
    create_ticket,
    get_iam_inventory,
    get_pending_tickets,
    provision_iam_binding,
    synthesize_iam_request,
)
from cerberus.models.iam_ticket import IAMRequest, SynthesizedIAMPlan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_test_plan(**kwargs) -> SynthesizedIAMPlan:
    defaults = dict(
        requester_email="alice@x.com",
        project_id="nexus-tech-dev-1",
        role="roles/bigquery.dataViewer",
        justification="read-only access for analytics",
        synthesized_at="2026-03-31T10:00:00Z",
        raw_request="give alice bigquery read",
    )
    defaults.update(kwargs)
    return SynthesizedIAMPlan(**defaults)


mock_config = CerberusConfig(
    gcp_project_id="nexus-tech-dev-1",
    service_account_key_path="./fake-key.json",
    billing_account_id="123456-123456-123456",
    gemini_api_key="fake-key",
    gemini_model="gemini-1.5-pro-002",
)


@pytest.fixture(autouse=True)
def clear_tickets():
    """Isolate ticket store between tests."""
    _tickets.clear()
    yield
    _tickets.clear()


# ---------------------------------------------------------------------------
# synthesize_iam_request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_synthesis_calls_gemini_with_temperature_zero(mocker):
    plan_json = json.dumps({
        "requester_email": "alice@x.com",
        "project_id": "nexus-tech-dev-1",
        "role": "roles/bigquery.dataViewer",
        "justification": "read-only",
        "synthesized_at": "2026-03-31T10:00:00Z",
        "raw_request": "give alice bigquery read",
    })
    mock_response = mocker.MagicMock()
    mock_response.text = plan_json

    mock_client = mocker.MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mocker.patch("cerberus.heads.iam_head.genai.Client", return_value=mock_client)

    # gcp_call_with_retry calls the inner _call() closure directly
    mocker.patch("cerberus.heads.iam_head.gcp_call_with_retry", side_effect=lambda fn, *a, **kw: fn())

    result = await synthesize_iam_request(
        IAMRequest(
            natural_language_request="give alice bigquery read",
            requester_email="alice@x.com",
            project_id="nexus-tech-dev-1",
        ),
        mock_config,
    )

    assert result.role == "roles/bigquery.dataViewer"
    mock_client.models.generate_content.assert_called_once()
    call_kwargs = mock_client.models.generate_content.call_args[1]
    assert call_kwargs["config"].temperature == 0


@pytest.mark.asyncio
async def test_synthesis_raises_on_unparseable_response(mocker):
    mock_response = mocker.MagicMock()
    mock_response.text = "not json at all"
    mock_client = mocker.MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mocker.patch("cerberus.heads.iam_head.genai.Client", return_value=mock_client)
    mocker.patch("cerberus.heads.iam_head.gcp_call_with_retry", side_effect=lambda fn, *a, **kw: fn())

    with pytest.raises(ValueError, match="IAM synthesis failed"):
        await synthesize_iam_request(
            IAMRequest(
                natural_language_request="give alice access",
                requester_email="alice@x.com",
                project_id="nexus-tech-dev-1",
            ),
            mock_config,
        )


# ---------------------------------------------------------------------------
# create_ticket
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_ticket_stores_in_memory():
    plan = make_test_plan()
    ticket = await create_ticket(plan)
    assert ticket.ticket_id in _tickets
    assert ticket.status == "pending"


@pytest.mark.asyncio
async def test_create_ticket_sets_pending_status():
    plan = make_test_plan()
    ticket = await create_ticket(plan)
    assert ticket.status == "pending"
    assert ticket.reviewed_at is None
    assert ticket.reviewed_by is None


# ---------------------------------------------------------------------------
# approve_ticket
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_ticket_changes_status():
    plan = make_test_plan()
    ticket = await create_ticket(plan)
    approved = await approve_ticket(ticket.ticket_id, "admin@x.com")
    assert approved.status == "approved"
    assert approved.reviewed_by == "admin@x.com"
    assert approved.reviewed_at is not None


@pytest.mark.asyncio
async def test_approve_ticket_raises_on_unknown_id():
    with pytest.raises(KeyError, match="not found"):
        await approve_ticket("nonexistent-id", "admin@x.com")


# ---------------------------------------------------------------------------
# provision_iam_binding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provision_dry_run_returns_dry_run_status():
    plan = make_test_plan()
    ticket = await create_ticket(plan)
    await approve_ticket(ticket.ticket_id, "admin@x.com")
    result = await provision_iam_binding(ticket, dry_run=True)
    assert result["status"] == "DRY_RUN"
    assert "would_add" in result
    assert ticket.ticket_id == result["ticket_id"]


@pytest.mark.asyncio
async def test_provision_dry_run_contains_role_and_email():
    plan = make_test_plan()
    ticket = await create_ticket(plan)
    result = await provision_iam_binding(ticket, dry_run=True)
    assert "roles/bigquery.dataViewer" in result["would_add"]
    assert "alice@x.com" in result["would_add"]


# ---------------------------------------------------------------------------
# get_pending_tickets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_pending_tickets_filters_non_pending():
    plan = make_test_plan()
    t1 = await create_ticket(plan)
    t2 = await create_ticket(plan)
    await approve_ticket(t1.ticket_id, "admin@x.com")
    pending = await get_pending_tickets()
    ids = [t.ticket_id for t in pending]
    assert t1.ticket_id not in ids
    assert t2.ticket_id in ids


# ---------------------------------------------------------------------------
# get_iam_inventory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_iam_inventory_returns_binding_list(mocker):
    mock_binding = mocker.MagicMock()
    mock_binding.role = "roles/viewer"
    mock_binding.members = ["user:alice@x.com", "serviceAccount:sa@proj.iam.gserviceaccount.com"]

    mock_policy = mocker.MagicMock()
    mock_policy.bindings = [mock_binding]

    mock_client = mocker.MagicMock()
    mock_client.get_iam_policy.return_value = mock_policy
    mocker.patch(
        "cerberus.heads.iam_head.resourcemanager_v3.ProjectsClient",
        return_value=mock_client,
    )
    mocker.patch(
        "cerberus.heads.iam_head.gcp_call_with_retry",
        side_effect=lambda fn, *a, **kw: fn(),
    )

    bindings = await get_iam_inventory("nexus-tech-dev-1", None)
    assert len(bindings) == 2
    for b in bindings:
        assert b.identity is not None
        assert b.role is not None
        assert b.project_id == "nexus-tech-dev-1"


@pytest.mark.asyncio
async def test_iam_inventory_returns_empty_on_retry_exhausted(mocker):
    from cerberus.tools.gcp_retry import CerberusRetryExhausted
    mocker.patch(
        "cerberus.heads.iam_head.resourcemanager_v3.ProjectsClient",
        return_value=mocker.MagicMock(),
    )
    mocker.patch(
        "cerberus.heads.iam_head.gcp_call_with_retry",
        side_effect=CerberusRetryExhausted("get_iam_policy", 3, Exception("timeout")),
    )
    result = await get_iam_inventory("nexus-tech-dev-1", None)
    assert result == []
