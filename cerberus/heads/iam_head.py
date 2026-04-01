from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from google import genai
from google.genai import types
from google.cloud import resourcemanager_v3

from cerberus.config import CerberusConfig
from cerberus.models.iam_ticket import IAMBinding, IAMRequest, IAMTicket, SynthesizedIAMPlan
from cerberus.tools.gcp_retry import CerberusRetryExhausted, gcp_call_with_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level in-memory ticket store (same pattern as active_runs in api.py)
# ---------------------------------------------------------------------------

_tickets: dict[str, IAMTicket] = {}


# ---------------------------------------------------------------------------
# Gemini synthesis
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a GCP IAM analyst. Convert a natural language access request "
    "into a structured IAM plan. Output ONLY valid JSON matching this schema: "
    f"{SynthesizedIAMPlan.model_json_schema()}. "
    "Choose the minimum-privilege role that satisfies the request. "
    "Never suggest roles/owner or roles/editor unless explicitly requested and justified."
)


async def synthesize_iam_request(
    request: IAMRequest, config: CerberusConfig
) -> SynthesizedIAMPlan:
    """Call Gemini to produce a structured IAM plan from natural language.

    INV-IAM-01: synthesis must complete before any ticket is created.
    """
    client = genai.Client(api_key=config.gemini_api_key)
    user_prompt = (
        f"Request: {request.natural_language_request}\n"
        f"Requester: {request.requester_email}\n"
        f"Project: {request.project_id}"
    )

    def _call() -> str:
        response = client.models.generate_content(
            model=config.gemini_model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                temperature=0,
                response_mime_type="application/json",
            ),
        )
        return response.text

    raw_text = gcp_call_with_retry(_call)

    try:
        parsed = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"IAM synthesis failed: unparseable response — {exc}") from exc

    parsed["raw_request"] = request.natural_language_request
    parsed["synthesized_at"] = datetime.now(timezone.utc).isoformat()
    parsed.setdefault("requester_email", request.requester_email)
    parsed.setdefault("project_id", request.project_id)

    return SynthesizedIAMPlan(**parsed)


# ---------------------------------------------------------------------------
# Ticket lifecycle
# ---------------------------------------------------------------------------


async def create_ticket(plan: SynthesizedIAMPlan) -> IAMTicket:
    ticket_id = str(uuid.uuid4())
    ticket = IAMTicket(
        ticket_id=ticket_id,
        plan=plan,
        status="pending",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _tickets[ticket_id] = ticket
    logger.info("IAM ticket %s created for %s", ticket_id, plan.requester_email)
    return ticket


async def get_pending_tickets() -> list[IAMTicket]:
    return [t for t in _tickets.values() if t.status == "pending"]


async def approve_ticket(ticket_id: str, reviewer_email: str) -> IAMTicket:
    if ticket_id not in _tickets:
        raise KeyError(f"Ticket {ticket_id} not found")
    ticket = _tickets[ticket_id]
    ticket.status = "approved"
    ticket.reviewed_at = datetime.now(timezone.utc).isoformat()
    ticket.reviewed_by = reviewer_email
    logger.info("IAM ticket %s approved by %s", ticket_id, reviewer_email)
    return ticket


async def provision_iam_binding(ticket: IAMTicket, dry_run: bool = True) -> dict:
    """Provision (or preview) an IAM binding for an approved ticket.

    INV-IAM-02: dry_run=True is the default — live provisioning requires explicit False.
    """
    if dry_run:
        return {
            "status": "DRY_RUN",
            "would_add": (
                f"{ticket.plan.requester_email} → {ticket.plan.role} "
                f"on {ticket.plan.project_id}"
            ),
            "ticket_id": ticket.ticket_id,
        }

    # Live provisioning — get current policy, add binding, set policy back.
    rm_client = resourcemanager_v3.ProjectsClient()
    project_name = f"projects/{ticket.plan.project_id}"

    def _get_policy():
        return rm_client.get_iam_policy(
            request={"resource": project_name}
        )

    policy = gcp_call_with_retry(_get_policy)

    new_binding = resourcemanager_v3.types.Binding(
        role=ticket.plan.role,
        members=[f"user:{ticket.plan.requester_email}"],
    )
    policy.bindings.append(new_binding)

    def _set_policy():
        return rm_client.set_iam_policy(
            request={"resource": project_name, "policy": policy}
        )

    gcp_call_with_retry(_set_policy)
    ticket.status = "provisioned"
    logger.info("IAM ticket %s provisioned (live)", ticket.ticket_id)
    return {"status": "SUCCESS", "ticket_id": ticket.ticket_id}


# ---------------------------------------------------------------------------
# Asset inventory
# ---------------------------------------------------------------------------


async def get_iam_inventory(project_id: str, credentials) -> list[IAMBinding]:
    """Return all IAM bindings for the project.

    Wraps GCP call in gcp_call_with_retry. Returns [] on CerberusRetryExhausted.
    """
    rm_client = resourcemanager_v3.ProjectsClient(credentials=credentials)
    project_name = f"projects/{project_id}"

    def _get_policy():
        return rm_client.get_iam_policy(request={"resource": project_name})

    try:
        policy = gcp_call_with_retry(_get_policy)
    except CerberusRetryExhausted:
        logger.warning("get_iam_inventory: GCP retries exhausted for %s", project_id)
        return []

    bindings: list[IAMBinding] = []
    for binding in policy.bindings:
        for member in binding.members:
            if member.startswith("user:"):
                binding_type = "user"
                identity = member[len("user:"):]
            elif member.startswith("serviceAccount:"):
                binding_type = "serviceAccount"
                identity = member[len("serviceAccount:"):]
            elif member.startswith("group:"):
                binding_type = "group"
                identity = member[len("group:"):]
            else:
                continue
            bindings.append(
                IAMBinding(
                    identity=identity,
                    role=binding.role,
                    project_id=project_id,
                    binding_type=binding_type,
                )
            )
    return bindings
