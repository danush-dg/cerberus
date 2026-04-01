# from __future__ import annotations

# from typing import Literal

# from pydantic import BaseModel


# class IAMRequest(BaseModel):
#     natural_language_request: str
#     requester_email: str
#     project_id: str


# class SynthesizedIAMPlan(BaseModel):
#     requester_email: str
#     project_id: str
#     role: str
#     justification: str
#     synthesized_at: str       # ISO 8601
#     raw_request: str


# class IAMTicket(BaseModel):
#     ticket_id: str            # uuid4
#     plan: SynthesizedIAMPlan
#     status: Literal["pending", "approved", "rejected", "provisioned", "revoked"]
#     created_at: str
#     reviewed_at: str | None = None
#     reviewed_by: str | None = None


# class IAMBinding(BaseModel):
#     identity: str             # user email or service account
#     role: str
#     project_id: str
#     binding_type: Literal["user", "serviceAccount", "group"]


from __future__ import annotations
from typing import Literal
from pydantic import BaseModel

class IAMRequest(BaseModel):
    natural_language_request: str
    requester_email: str
    project_id: str
    role: str  # user-supplied GCP role, e.g. "roles/storage.objectViewer"

class SynthesizedIAMPlan(BaseModel):
    requester_email: str
    project_id: str
    role: str
    permissions: list[str] = []
    justification: str
    synthesized_at: str
    raw_request: str

class IAMTicket(BaseModel):
    ticket_id: str
    plan: SynthesizedIAMPlan
    status: Literal["pending", "approved", "rejected", "provisioned"]
    created_at: str
    reviewed_at: str | None = None
    reviewed_by: str | None = None

class IAMBinding(BaseModel):
    identity: str
    role: str
    project_id: str
    binding_type: Literal["user", "serviceAccount", "group"]
    status: str = "Active"
    last_activity: str | None = None
    days_inactive: str = "0d"

