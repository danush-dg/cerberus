from __future__ import annotations

import json
import logging
from datetime import date

from google import genai
from google.genai import types
from pydantic import BaseModel

from cerberus.config import get_config, validate_project_id
from cerberus.tools.gcp_retry import gcp_call_with_retry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a GCP security synthesizer. Apply least-privilege. "
    "Never return roles/editor, roles/owner, or roles/viewer. "
    "Always return a custom role with specific permissions. "
    "Return JSON only."
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class IamRequest(BaseModel):
    requester_email: str
    request_text: str
    project_id: str


class IamProvisioningPlan(BaseModel):
    requester_email: str
    custom_role_id: str
    permissions: list[str]
    binding_condition: str
    budget_alert_threshold_usd: float
    review_after_days: int
    checklist: list[str]
    reasoning: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_prompt(request: IamRequest) -> str:
    today = date.today().strftime("%Y%m%d")
    return (
        f"Project: {request.project_id}\n"
        f"Requester: {request.requester_email}\n"
        f"Request: {request.request_text}\n\n"
        f"Rules:\n"
        f"- custom_role_id must start with 'cerberus_' and end with today's date "
        f"({today}), e.g. cerberus_bq_fraud_read_{today}\n"
        f"- permissions must be granular GCP permission strings "
        f"(e.g. bigquery.tables.get)\n"
        f"- binding_condition must be a CEL expression scoping the role to a "
        f"specific resource if possible\n"
        f"- review_after_days must be exactly 90\n"
        f"- checklist must contain exactly 7 steps as strings\n"
        f"- reasoning must be 3 sentences or fewer and cite at least one "
        f"permission name\n"
        f"- requester_email field must be: {request.requester_email}\n"
    )


def _call_gemini(client: genai.Client, model_name: str, prompt: str) -> str:
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0,
            response_mime_type="application/json",
            response_schema=IamProvisioningPlan,
        ),
    )
    return response.text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def synthesize_iam_request(request: IamRequest) -> IamProvisioningPlan:
    """Synthesize a least-privilege IAM provisioning plan from a natural-language request.

    Steps:
      1. Validate project_id against allowed pattern (INV-SEC-01).
      2. Build Gemini prompt including the IamProvisioningPlan JSON schema.
      3. Call Gemini via gcp_call_with_retry (INV-NFR-02).
      4. Parse JSON response into IamProvisioningPlan; raise ValueError on failure.
      5. Enforce checklist length == 7 (pad with human-review steps if short).
      6. Enforce review_after_days == 90 (override if Gemini returns another value).
      7. Return plan.

    Raises:
        ValueError: if project_id fails pattern check or Gemini response is unparseable.
    """
    cfg = get_config()
    validate_project_id(request.project_id, cfg.allowed_project_pattern)

    client = genai.Client(api_key=cfg.gemini_api_key)
    prompt = _build_prompt(request)

    logger.info(
        "synthesize_iam_request: calling Gemini for %s on project %s",
        request.requester_email,
        request.project_id,
    )

    raw_text: str = gcp_call_with_retry(_call_gemini, client, cfg.gemini_model, prompt)

    try:
        parsed_dict = json.loads(raw_text)
        plan = IamProvisioningPlan(**parsed_dict)
    except Exception as exc:
        raise ValueError(
            f"synthesize_iam_request: failed to parse Gemini response: {exc!r}\n"
            f"Raw response: {raw_text}"
        ) from exc

    # Enforce checklist length == 7 (pad with human-review steps if short)
    while len(plan.checklist) < 7:
        step_n = len(plan.checklist) + 1
        plan.checklist.append(f"Step {step_n}: Human review required")

    # Enforce review_after_days == 90 (matches STALENESS_THRESHOLD_DAYS in enrich_node.py)
    if plan.review_after_days != 90:
        logger.warning(
            "synthesize_iam_request: overriding review_after_days %d -> 90",
            plan.review_after_days,
        )
        plan.review_after_days = 90

    logger.info(
        "synthesize_iam_request: plan synthesized — role %s, %d permission(s)",
        plan.custom_role_id,
        len(plan.permissions),
    )
    return plan
