from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Literal, TYPE_CHECKING

from google import genai
from google.genai import types
from pydantic import BaseModel

from cerberus.config import get_config
from cerberus.state import VALID_DECISIONS, CerberusState
from cerberus.tools.chroma_client import query_resource_history, query_owner_history

if TYPE_CHECKING:
    from cerberus.state import ResourceRecord

logger = logging.getLogger(__name__)

GEMINI_INTER_REQUEST_DELAY_SECONDS: float = 0.5


# ---------------------------------------------------------------------------
# Task 4.1 — Gemini schema, system prompt, and resource prompt builder
# ---------------------------------------------------------------------------

class ResourceDecision(BaseModel):
    decision: Literal["safe_to_stop", "safe_to_delete", "needs_review", "skip"]
    reasoning: str
    estimated_monthly_savings: float


SYSTEM_PROMPT: str = (
    "You are a GCP cloud cost optimisation agent. Analyse the resource below and "
    "return a classification decision.\n\n"
    "Output decision as exactly one of: safe_to_stop, safe_to_delete, needs_review, skip\n\n"
    "Rules:\n"
    "- If flagged_for_review is true OR ownership_status is no_owner, decision MUST be needs_review\n"
    "- Reasoning must be 3 sentences or fewer. Sentence 1 must cite at least one of: "
    "idle duration in hours, owner last activity age in days, or estimated monthly cost in USD.\n"
    "- If estimated_monthly_cost is null, set estimated_monthly_savings=0.0 and note this.\n"
    "- Do not recommend deletion without evidence of abandonment.\n\n"
    f"Output ONLY valid JSON matching this schema:\n{ResourceDecision.model_json_schema()}"
)


def build_resource_prompt(resource: "ResourceRecord", project_id: str = "") -> str:
    lines = [
        "Resource to classify:",
        f"  resource_id:             {resource.get('resource_id')}",
        f"  resource_type:           {resource.get('resource_type')}",
        f"  region:                  {resource.get('region')}",
        f"  creation_timestamp:      {resource.get('creation_timestamp')}",
        f"  last_activity_timestamp: {resource.get('last_activity_timestamp')}",
        f"  estimated_monthly_cost:  {resource.get('estimated_monthly_cost')}",
        f"  ownership_status:        {resource.get('ownership_status')}",
        f"  owner_email:             {resource.get('owner_email')}",
        f"  owner_iam_active:        {resource.get('owner_iam_active')}",
        f"  flagged_for_review:      {str(resource.get('flagged_for_review', False)).lower()}",
    ]

    # Best-effort ChromaDB context — omit silently on failure or empty result
    resource_id = resource.get("resource_id", "")
    history = query_resource_history(resource_id)
    if history:
        lines.append(
            f"  Previous classification: {history.get('decision')} on {history.get('scanned_at')}"
        )

    owner_email = resource.get("owner_email") or ""
    if owner_email and project_id:
        owner_context = query_owner_history(owner_email, project_id)
        if owner_context:
            lines.append(
                f"  Owner has {len(owner_context)} other resources in this project."
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Task 4.2 — classify_resource with post-LLM validation
# ---------------------------------------------------------------------------

async def _call_gemini(client: genai.Client, model_name: str, prompt: str) -> str:
    """Single Gemini call; returns response.text."""
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        ),
    )
    return response.text


async def classify_resource(
    resource: "ResourceRecord",
    client: genai.Client,
    model_name: str = "gemini-1.5-pro-002",
) -> "ResourceRecord":
    prompt = build_resource_prompt(resource)

    # Step 1 — call Gemini
    raw_text = await _call_gemini(client, model_name, prompt)

    # Step 2 — parse JSON
    try:
        parsed_dict = json.loads(raw_text)
        parsed = ResourceDecision(**parsed_dict)
    except Exception:
        logger.error(
            "classify_resource: unparseable response for %s: %r",
            resource.get("resource_id"),
            raw_text,
        )
        resource["decision"] = "needs_review"
        resource["reasoning"] = "Reasoning unavailable — LLM returned unparseable output."
        resource["estimated_monthly_savings"] = 0.0
        return resource

    # Step 3 — validate decision against VALID_DECISIONS
    if parsed.decision not in VALID_DECISIONS:
        logger.warning(
            "classify_resource: invalid decision %r for %s — overriding to needs_review",
            parsed.decision,
            resource.get("resource_id"),
        )
        parsed.decision = "needs_review"

    # Step 4 — flagged_for_review code guardrail (INV-ENR-03 second enforcement point)
    if resource.get("flagged_for_review") and parsed.decision != "needs_review":
        logger.warning(
            "Guardrail override: %s flagged_for_review had decision=%s → forced to needs_review",
            resource.get("resource_id"),
            parsed.decision,
        )
        parsed.decision = "needs_review"

    # Step 5 — reasoning validation (INV-RSN-02)
    sentences = [s.strip() for s in re.split(r'\.(?:\s|$)', parsed.reasoning) if s.strip()]
    if len(sentences) > 3:
        parsed.reasoning = ". ".join(sentences[:3]) + "."
        logger.warning("Reasoning truncated for %s", resource.get("resource_id"))

    if not parsed.reasoning.strip():
        # Single retry
        raw_text2 = await _call_gemini(client, model_name, prompt)
        try:
            parsed2 = ResourceDecision(**json.loads(raw_text2))
            if parsed2.reasoning.strip():
                parsed.reasoning = parsed2.reasoning
            else:
                parsed.reasoning = "Reasoning unavailable — flagged for review."
                parsed.decision = "needs_review"
        except Exception:
            parsed.reasoning = "Reasoning unavailable — flagged for review."
            parsed.decision = "needs_review"

    # Step 6 — savings validation (INV-RSN-03)
    if parsed.estimated_monthly_savings < 0:
        parsed.estimated_monthly_savings = 0.0

    if parsed.decision in ("safe_to_stop", "safe_to_delete"):
        if parsed.estimated_monthly_savings == 0.0 and resource.get("estimated_monthly_cost"):
            parsed.estimated_monthly_savings = float(resource["estimated_monthly_cost"])

    # Step 7 — write back to resource
    resource["decision"] = parsed.decision
    resource["reasoning"] = parsed.reasoning
    resource["estimated_monthly_savings"] = parsed.estimated_monthly_savings
    return resource


# ---------------------------------------------------------------------------
# Task 4.3 — reason_node assembly
# ---------------------------------------------------------------------------

async def reason_node(state: CerberusState) -> CerberusState:
    cfg = get_config()
    client = genai.Client(api_key=cfg.gemini_api_key)

    for i, resource in enumerate(state["resources"]):
        state["resources"][i] = await classify_resource(resource, client, cfg.gemini_model)
        await asyncio.sleep(GEMINI_INTER_REQUEST_DELAY_SECONDS)

    # Belt-and-suspenders assertion (INV-RSN-01)
    for resource in state["resources"]:
        assert resource["decision"] is not None, (
            f"reason_node: decision is None for resource {resource.get('resource_id')}"
        )

    total_savings = sum(
        r["estimated_monthly_savings"] or 0.0
        for r in state["resources"]
        if r["decision"] in ("safe_to_stop", "safe_to_delete")
    )
    logger.info(
        "%d resources classified. $%.2f/month recoverable waste identified.",
        len(state["resources"]),
        total_savings,
    )

    return state
