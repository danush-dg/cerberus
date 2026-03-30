import pytest
from cerberus.state import ResourceRecord


def make_resource_record(resource_id: str, **kwargs) -> dict:
    defaults = {
        "resource_id": resource_id,
        "resource_type": "vm",
        "region": "us-central1",
        "creation_timestamp": "2024-01-01T00:00:00Z",
        "last_activity_timestamp": None,
        "estimated_monthly_cost": 45.0,
        "ownership_status": "active_owner",
        "owner_email": "test@nexus.tech",
        "owner_iam_active": True,
        "flagged_for_review": False,
        "decision": None,
        "reasoning": None,
        "estimated_monthly_savings": None,
        "outcome": None,
    }
    defaults.update(kwargs)
    return defaults
