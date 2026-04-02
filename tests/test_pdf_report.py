"""Task 10.4 — PDF Report tests (INV-SEC2-03)."""
from __future__ import annotations

import socket
from unittest.mock import Mock

import pytest

from cerberus.services.pdf_report import generate_audit_report


# ---------------------------------------------------------------------------
# Core correctness
# ---------------------------------------------------------------------------


def test_pdf_generates_valid_bytes():
    """Generate a minimal PDF and verify magic bytes and non-trivial size."""
    pdf_bytes = generate_audit_report(
        "nexus-tech-dev-1",
        {
            "report_timestamp": "2026-03-31T10:00:00Z",
            "project_id": "nexus-tech-dev-1",
            "resources_scanned": 6,
            "iam_changes": [],
            "security_flags": [],
            "idle_resources": [],
        },
    )
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes[:4] == b"%PDF"


def test_pdf_does_not_require_network(monkeypatch):
    """INV-SEC2-03: PDF must generate even when all network calls are blocked."""
    monkeypatch.setattr(socket, "getaddrinfo", Mock(side_effect=OSError("no network")))

    pdf_bytes = generate_audit_report("nexus-tech-dev-1", {})

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0


def test_pdf_contains_project_id_text():
    """Generated PDF must be non-empty for any project ID."""
    pdf_bytes = generate_audit_report("my-test-project", {})

    assert len(pdf_bytes) > 500


def test_pdf_empty_report_data():
    """Empty dict must still produce a valid minimal PDF."""
    pdf_bytes = generate_audit_report("nexus-tech-dev-empty", {})

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 200


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------


def test_pdf_with_security_flags():
    """PDF with security flags renders without error."""
    report_data = {
        "report_timestamp": "2026-03-31T10:00:00Z",
        "project_id": "nexus-tech-dev-1",
        "resources_scanned": 3,
        "iam_changes": [],
        "security_flags": [
            {
                "flag_type": "OVER_PERMISSIONED",
                "identity_or_resource": "alice@x.com",
                "detected_at": "2026-03-31T09:00:00Z",
                "detail": "alice@x.com holds roles/owner but inactive for 45 days",
            }
        ],
        "idle_resources": [],
    }
    pdf_bytes = generate_audit_report("nexus-tech-dev-1", report_data)

    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 1000


def test_pdf_with_iam_changes():
    """PDF with IAM bindings renders the IAM changes table."""
    report_data = {
        "report_timestamp": "2026-03-31T10:00:00Z",
        "project_id": "nexus-tech-dev-1",
        "resources_scanned": 0,
        "iam_changes": [
            {
                "identity": "bob@x.com",
                "role": "roles/editor",
                "changed_at": "2026-01-15T00:00:00Z",
                "changed_by": "admin@x.com",
            }
        ],
        "security_flags": [],
        "idle_resources": [],
    }
    pdf_bytes = generate_audit_report("nexus-tech-dev-1", report_data)

    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 1000


def test_pdf_with_idle_resources():
    """PDF with idle resources renders the idle resources table."""
    report_data = {
        "report_timestamp": "2026-03-31T10:00:00Z",
        "project_id": "nexus-tech-dev-1",
        "resources_scanned": 2,
        "iam_changes": [],
        "security_flags": [],
        "idle_resources": [
            {
                "identity_or_resource": "vm-idle-001",
                "detail": "gce_instance idle — $120.00/month",
            }
        ],
    }
    pdf_bytes = generate_audit_report("nexus-tech-dev-1", report_data)

    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 1000


def test_pdf_null_fields_do_not_crash():
    """None values in report_data tables must not raise exceptions."""
    report_data = {
        "iam_changes": [
            {"identity": None, "role": None, "changed_at": None, "changed_by": None}
        ],
        "security_flags": [
            {
                "flag_type": None,
                "identity_or_resource": None,
                "detected_at": None,
                "detail": None,
            }
        ],
        "idle_resources": [{"resource_id": None, "resource_type": None}],
    }
    pdf_bytes = generate_audit_report("nexus-tech-dev-1", report_data)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# INV-SEC2-03: reportlab only — no other PDF library imported
# ---------------------------------------------------------------------------


def test_inv_sec2_03_only_reportlab_used():
    """INV-SEC2-03: pdf_report must not import weasyprint, fpdf, or xhtml2pdf."""
    import ast
    import importlib
    import inspect

    mod = importlib.import_module("cerberus.services.pdf_report")
    src = inspect.getsource(mod)
    tree = ast.parse(src)

    forbidden = {"weasyprint", "fpdf", "xhtml2pdf", "pdfkit"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            else:
                continue
            assert not any(f in module for f in forbidden), (
                f"INV-SEC2-03 violated: found forbidden PDF library import '{module}'"
            )


def test_inv_sec2_03_no_network_imports():
    """INV-SEC2-03: pdf_report must not import requests, httpx, or urllib3."""
    import ast
    import importlib
    import inspect

    mod = importlib.import_module("cerberus.services.pdf_report")
    src = inspect.getsource(mod)
    tree = ast.parse(src)

    forbidden = {"requests", "httpx", "urllib3", "aiohttp"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            else:
                continue
            assert not any(f in module for f in forbidden), (
                f"INV-SEC2-03 violated: found network import '{module}' in pdf_report"
            )
