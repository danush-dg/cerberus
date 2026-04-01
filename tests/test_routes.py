"""Task 10.1 — route registration tests.

Verifies that all new routes are registered and reachable (not 404),
and that existing routes remain untouched.
"""
import pytest
from fastapi.testclient import TestClient

from cerberus.api import app

client = TestClient(app)


def test_iam_inventory_route_exists():
    r = client.get("/iam/inventory?project_id=nexus-tech-dev-1")
    assert r.status_code != 404


def test_iam_request_route_exists():
    r = client.post("/iam/request")
    assert r.status_code != 404


def test_iam_request_preview_route_exists():
    r = client.get("/iam/request/test-id/preview")
    assert r.status_code != 404


def test_iam_request_confirm_route_exists():
    r = client.post("/iam/request/test-id/confirm")
    assert r.status_code != 404


def test_cost_project_route_exists():
    r = client.get("/cost/project/nexus-tech-dev-1")
    assert r.status_code != 404


def test_cost_user_route_exists():
    r = client.get("/cost/user?owner_email=alice@example.com&project_id=nexus-tech-dev-1")
    assert r.status_code != 404


def test_security_flags_route_exists():
    r = client.get("/security/flags?project_id=nexus-tech-dev-1")
    assert r.status_code != 404


def test_security_budget_status_route_exists():
    r = client.get("/security/budget-status?project_id=nexus-tech-dev-1")
    assert r.status_code != 404


def test_security_report_download_route_exists():
    r = client.get("/security/report/download?project_id=nexus-tech-dev-1")
    assert r.status_code != 404


def test_tickets_route_exists():
    r = client.get("/tickets")
    assert r.status_code != 404


def test_ticket_approve_route_exists():
    r = client.post("/tickets/test-id/approve")
    assert r.status_code != 404


def test_ticket_provision_route_exists():
    r = client.post("/tickets/test-id/provision")
    assert r.status_code != 404


def test_existing_run_route_untouched():
    r = client.get("/run/nonexistent-id/status")
    assert r.status_code == 404  # not 500 — existing routes still work


def test_iam_ticket_model_validation():
    from cerberus.models.iam_ticket import IAMTicket, SynthesizedIAMPlan

    plan = SynthesizedIAMPlan(
        requester_email="alice@x.com",
        project_id="nexus-tech-dev-1",
        role="roles/bigquery.dataViewer",
        justification="needs read access",
        synthesized_at="2026-03-31T10:00:00Z",
        raw_request="give alice bigquery read",
    )
    ticket = IAMTicket(
        ticket_id="t-1",
        plan=plan,
        status="pending",
        created_at="2026-03-31T10:00:00Z",
    )
    assert ticket.status == "pending"


def test_security_flag_type_locked():
    import pytest
    from cerberus.models.security_flag import SecurityFlag

    with pytest.raises(Exception):
        SecurityFlag(
            flag_id="f-1",
            flag_type="INVALID_TYPE",
            identity_or_resource="vm-1",
            project_id="p",
            detected_at="2026-01-01T00:00:00Z",
            detail="test",
        )
