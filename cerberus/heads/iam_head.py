# from __future__ import annotations

# import json
# import logging
# import uuid
# from datetime import datetime, timezone

# from google import genai
# from google.genai import types
# from google.cloud import resourcemanager_v3

# from cerberus.config import CerberusConfig
# from cerberus.models.iam_ticket import IAMBinding, IAMRequest, IAMTicket, SynthesizedIAMPlan
# from cerberus.tools.gcp_retry import CerberusRetryExhausted, gcp_call_with_retry

# logger = logging.getLogger(__name__)

# # ---------------------------------------------------------------------------
# # Module-level in-memory ticket store (same pattern as active_runs in api.py)
# # ---------------------------------------------------------------------------

# _tickets: dict[str, IAMTicket] = {}


# # ---------------------------------------------------------------------------
# # Gemini synthesis
# # ---------------------------------------------------------------------------

# _SYSTEM_PROMPT = (
#     "You are a GCP IAM analyst. Convert a natural language access request "
#     "into a structured IAM plan. Output ONLY valid JSON matching this schema: "
#     f"{SynthesizedIAMPlan.model_json_schema()}. "
#     "Choose the minimum-privilege role that satisfies the request. "
#     "Never suggest roles/owner or roles/editor unless explicitly requested and justified."
# )


# async def synthesize_iam_request(
#     request: IAMRequest, config: CerberusConfig
# ) -> SynthesizedIAMPlan:
#     """Call Gemini to produce a structured IAM plan from natural language.

#     INV-IAM-01: synthesis must complete before any ticket is created.
#     """
#     client = genai.Client(api_key=config.gemini_api_key)
#     user_prompt = (
#         f"Request: {request.natural_language_request}\n"
#         f"Requester: {request.requester_email}\n"
#         f"Project: {request.project_id}"
#     )

#     def _call() -> str:
#         response = client.models.generate_content(
#             model=config.gemini_model,
#             contents=user_prompt,
#             config=types.GenerateContentConfig(
#                 system_instruction=_SYSTEM_PROMPT,
#                 temperature=0,
#                 response_mime_type="application/json",
#             ),
#         )
#         return response.text

#     raw_text = gcp_call_with_retry(_call)

#     try:
#         parsed = json.loads(raw_text)
#     except (json.JSONDecodeError, TypeError) as exc:
#         raise ValueError(f"IAM synthesis failed: unparseable response — {exc}") from exc

#     parsed["raw_request"] = request.natural_language_request
#     parsed["synthesized_at"] = datetime.now(timezone.utc).isoformat()
#     parsed.setdefault("requester_email", request.requester_email)
#     parsed.setdefault("project_id", request.project_id)

#     return SynthesizedIAMPlan(**parsed)


# # ---------------------------------------------------------------------------
# # Ticket lifecycle
# # ---------------------------------------------------------------------------


# async def create_ticket(plan: SynthesizedIAMPlan) -> IAMTicket:
#     ticket_id = str(uuid.uuid4())
#     ticket = IAMTicket(
#         ticket_id=ticket_id,
#         plan=plan,
#         status="pending",
#         created_at=datetime.now(timezone.utc).isoformat(),
#     )
#     _tickets[ticket_id] = ticket
#     logger.info("IAM ticket %s created for %s", ticket_id, plan.requester_email)
#     return ticket


# async def get_pending_tickets() -> list[IAMTicket]:
#     return [t for t in _tickets.values() if t.status == "pending"]


# async def approve_ticket(ticket_id: str, reviewer_email: str) -> IAMTicket:
#     if ticket_id not in _tickets:
#         raise KeyError(f"Ticket {ticket_id} not found")
#     ticket = _tickets[ticket_id]
#     ticket.status = "approved"
#     ticket.reviewed_at = datetime.now(timezone.utc).isoformat()
#     ticket.reviewed_by = reviewer_email
#     logger.info("IAM ticket %s approved by %s", ticket_id, reviewer_email)
#     return ticket


# async def provision_iam_binding(ticket: IAMTicket, dry_run: bool = True) -> dict:
#     """Provision (or preview) an IAM binding for an approved ticket.

#     INV-IAM-02: dry_run=True is the default — live provisioning requires explicit False.
#     """
#     if dry_run:
#         return {
#             "status": "DRY_RUN",
#             "would_add": (
#                 f"{ticket.plan.requester_email} → {ticket.plan.role} "
#                 f"on {ticket.plan.project_id}"
#             ),
#             "ticket_id": ticket.ticket_id,
#         }

#     # Live provisioning — get current policy, add binding, set policy back.
#     rm_client = resourcemanager_v3.ProjectsClient()
#     project_name = f"projects/{ticket.plan.project_id}"

#     def _get_policy():
#         return rm_client.get_iam_policy(
#             request={"resource": project_name}
#         )

#     policy = gcp_call_with_retry(_get_policy)

#     new_binding = resourcemanager_v3.types.Binding(
#         role=ticket.plan.role,
#         members=[f"user:{ticket.plan.requester_email}"],
#     )
#     policy.bindings.append(new_binding)

#     def _set_policy():
#         return rm_client.set_iam_policy(
#             request={"resource": project_name, "policy": policy}
#         )

#     gcp_call_with_retry(_set_policy)
#     ticket.status = "provisioned"
#     logger.info("IAM ticket %s provisioned (live)", ticket.ticket_id)
#     return {"status": "SUCCESS", "ticket_id": ticket.ticket_id}


# # ---------------------------------------------------------------------------
# # Asset inventory
# # ---------------------------------------------------------------------------


# async def get_iam_inventory(project_id: str, credentials) -> list[IAMBinding]:
#     """Return all IAM bindings for the project.

#     Wraps GCP call in gcp_call_with_retry. Returns [] on CerberusRetryExhausted.
#     """
#     rm_client = resourcemanager_v3.ProjectsClient(credentials=credentials)
#     project_name = f"projects/{project_id}"

#     def _get_policy():
#         return rm_client.get_iam_policy(request={"resource": project_name})

#     try:
#         policy = gcp_call_with_retry(_get_policy)
#     except CerberusRetryExhausted:
#         logger.warning("get_iam_inventory: GCP retries exhausted for %s", project_id)
#         return []

#     bindings: list[IAMBinding] = []
#     for binding in policy.bindings:
#         for member in binding.members:
#             if member.startswith("user:"):
#                 binding_type = "user"
#                 identity = member[len("user:"):]
#             elif member.startswith("serviceAccount:"):
#                 binding_type = "serviceAccount"
#                 identity = member[len("serviceAccount:"):]
#             elif member.startswith("group:"):
#                 binding_type = "group"
#                 identity = member[len("group:"):]
#             else:
#                 continue
#             bindings.append(
#                 IAMBinding(
#                     identity=identity,
#                     role=binding.role,
#                     project_id=project_id,
#                     binding_type=binding_type,
#                 )
#             )
#     return bindings


from __future__ import annotations
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from google import genai
from google.genai import types
from google.cloud import resourcemanager_v3, iam_admin_v1
from google.oauth2 import service_account
from cerberus.config import CerberusConfig, get_config
from cerberus.models.iam_ticket import IAMBinding, IAMRequest, IAMTicket, SynthesizedIAMPlan
from cerberus.tools.gcp_retry import CerberusRetryExhausted, gcp_call_with_retry
from cerberus.tools.chroma_client import upsert_iam_ticket, query_iam_history, query_all_iam_history
from cerberus.nodes.enrich_node import check_iam_last_activity, STALENESS_THRESHOLD_DAYS

logger = logging.getLogger(__name__)
_tickets: dict[str, IAMTicket] = {}

_SYSTEM_PROMPT = (
    "You are a GCP IAM security expert. The user has given a custom role name and a description "
    "of what access they need. Your job is to determine the minimum set of real GCP IAM permissions "
    "that satisfy the request.\n"
    "STRICT RULES:\n"
    "1. Output ONLY valid, officially documented GCP IAM permissions. Each permission must follow "
    "the exact pattern '<service>.<resource>.<verb>' (e.g. bigquery.tables.get, storage.objects.list).\n"
    "2. NEVER invent permissions. Only use permissions from the official GCP IAM permissions reference.\n"
    "3. For BigQuery read access use: bigquery.datasets.get, bigquery.tables.get, bigquery.tables.getData, "
    "bigquery.tables.list, bigquery.jobs.create.\n"
    "4. For Storage read access use: storage.objects.get, storage.objects.list, storage.buckets.get.\n"
    "5. For Compute read access use: compute.instances.get, compute.instances.list.\n"
    "6. Return JSON with: justification (string, max 300 chars), permissions (list of strings)."
)


async def synthesize_iam_request(request: IAMRequest, config: CerberusConfig) -> SynthesizedIAMPlan:
    """Synthesize minimum-privilege permissions for a custom role from natural language.

    The user-supplied role name is used as the custom role identifier.
    Gemini generates only the permissions, not the role name.
    """
    client = genai.Client(api_key=config.gemini_api_key)
    user_prompt = (
        f"Custom role name: {request.role}\n"
        f"Requester: {request.requester_email}\n"
        f"Project: {request.project_id}\n"
        f"Access needed: {request.natural_language_request}\n\n"
        f"List the minimum real GCP IAM permissions required for this access. "
        f"Return JSON with: justification (string), permissions (list of valid GCP permission strings)."
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

    parsed = json.loads(gcp_call_with_retry(_call))
    parsed["raw_request"] = request.natural_language_request
    parsed["synthesized_at"] = datetime.now(timezone.utc).isoformat()
    parsed["requester_email"] = request.requester_email
    parsed["project_id"] = request.project_id
    parsed["role"] = request.role  # user-supplied custom role name
    return SynthesizedIAMPlan(**parsed)

async def create_ticket(plan: SynthesizedIAMPlan) -> IAMTicket:
    tid = str(uuid.uuid4())
    ticket = IAMTicket(ticket_id=tid, plan=plan, status="pending", created_at=datetime.now(timezone.utc).isoformat())
    _tickets[tid] = ticket
    try:
        upsert_iam_ticket({
            "ticket_id": tid,
            "requester_email": plan.requester_email,
            "project_id": plan.project_id,
            "role": plan.role,
            "status": "pending",
            "created_at": ticket.created_at,
            "justification": plan.justification,
            "permissions": plan.permissions,
            "raw_request": plan.raw_request,
            "synthesized_at": plan.synthesized_at,
        })
    except Exception as e:
        logger.warning("create_ticket: ChromaDB failed: %s", e)
    return ticket

async def get_pending_tickets() -> list[IAMTicket]:
    return [t for b, t in _tickets.items() if t.status == "pending"]

async def approve_ticket(ticket_id: str, reviewer_email: str) -> IAMTicket:
    if ticket_id not in _tickets: raise KeyError(ticket_id)
    ticket = _tickets[ticket_id]
    ticket.status = "approved"
    ticket.reviewed_at = datetime.now(timezone.utc).isoformat()
    ticket.reviewed_by = reviewer_email
    try:
        upsert_iam_ticket({
            "ticket_id": ticket_id,
            "requester_email": ticket.plan.requester_email,
            "project_id": ticket.plan.project_id,
            "role": ticket.plan.role,
            "status": "approved",
            "created_at": ticket.created_at,
            "justification": ticket.plan.justification,
            "permissions": ticket.plan.permissions,
            "raw_request": ticket.plan.raw_request,
            "synthesized_at": ticket.plan.synthesized_at,
            "reviewed_at": ticket.reviewed_at,
            "reviewed_by": ticket.reviewed_by,
        })
    except Exception as e:
        logger.warning("approve_ticket: ChromaDB failed: %s", e)
    return ticket

async def reject_ticket(ticket_id: str, reviewer_email: str) -> IAMTicket:
    if ticket_id not in _tickets: raise KeyError(ticket_id)
    ticket = _tickets[ticket_id]
    ticket.status = "rejected"
    ticket.reviewed_at = datetime.now(timezone.utc).isoformat()
    ticket.reviewed_by = reviewer_email
    try:
        upsert_iam_ticket({
            "ticket_id": ticket_id,
            "requester_email": ticket.plan.requester_email,
            "project_id": ticket.plan.project_id,
            "role": ticket.plan.role,
            "status": "rejected",
            "created_at": ticket.created_at,
            "justification": ticket.plan.justification,
            "permissions": ticket.plan.permissions,
            "raw_request": ticket.plan.raw_request,
            "synthesized_at": ticket.plan.synthesized_at,
            "reviewed_at": ticket.reviewed_at,
            "reviewed_by": ticket.reviewed_by,
        })
    except Exception as e:
        logger.warning("reject_ticket: ChromaDB failed: %s", e)
    return ticket

async def revoke_iam_binding(ticket_id: str, actor_email: str) -> dict:
    """Revoke an IAM binding and record the change in ChromaDB ('deletion')."""
    if ticket_id not in _tickets: raise KeyError(ticket_id)
    ticket = _tickets[ticket_id]
    config = get_config()
    credentials = service_account.Credentials.from_service_account_file(config.service_account_key_path, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    rm_client = resourcemanager_v3.ProjectsClient(credentials=credentials)
    project_name = f"projects/{ticket.plan.project_id}"
    
    # Live revocation: remove the specific member from the role's binding
    try:
        policy = gcp_call_with_retry(lambda: rm_client.get_iam_policy(request={"resource": project_name}))
        for binding in policy.bindings:
            if binding.role == ticket.plan.role:
                member_str = f"user:{ticket.plan.requester_email}"
                if member_str in binding.members:
                    binding.members.remove(member_str)
                    break
        gcp_call_with_retry(lambda: rm_client.set_iam_policy(request={"resource": project_name, "policy": policy}))
        
        ticket.status = "revoked"
        # Update persistence
        upsert_iam_ticket({"ticket_id": ticket_id, "requester_email": ticket.plan.requester_email, "project_id": ticket.plan.project_id, "role": ticket.plan.role, "status": "revoked", "created_at": ticket.created_at, "justification": f"Revoked by {actor_email}"})
        return {"status": "SUCCESS", "message": f"Binding for {ticket.plan.requester_email} revoked."}
    except Exception as e:
        logger.error("Revocation failed for ticket %s: %s", ticket_id, e)
        return {"status": "FAILED", "error": str(e)}

def _clean_role_id(name: str) -> str:
    """Convert a user-supplied name into a valid GCP custom role ID (alphanumeric + underscores)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name.strip())


def _create_custom_role_with_retry(
    iam_client: iam_admin_v1.IAMClient,
    project_id: str,
    role_id: str,
    title: str,
    description: str,
    permissions: list[str],
) -> str:
    """Create (or update) a project-level custom role, stripping invalid permissions on failure.

    Returns the full role resource name.
    """
    parent = f"projects/{project_id}"
    full_name = f"{parent}/roles/{role_id}"

    # Check if the role already exists — if so, update it.
    try:
        existing = iam_client.get_role(request={"name": full_name})
        updated = iam_client.update_role(
            request={
                "name": full_name,
                "role": iam_admin_v1.types.Role(
                    included_permissions=permissions,
                    title=title,
                    description=description,
                ),
                "update_mask": {"paths": ["included_permissions", "title", "description"]},
            }
        )
        logger.info("Updated existing custom role %s", full_name)
        return full_name
    except Exception:
        pass  # role doesn't exist yet — create it

    remaining = list(permissions)
    for attempt in range(len(permissions) + 1):
        if not remaining:
            raise ValueError("No valid GCP permissions remain after filtering — cannot create custom role.")
        try:
            iam_client.create_role(
                request={
                    "parent": parent,
                    "role_id": role_id,
                    "role": iam_admin_v1.types.Role(
                        title=title,
                        description=description,
                        included_permissions=remaining,
                        stage=iam_admin_v1.types.Role.RoleLaunchStage.GA,
                    ),
                }
            )
            logger.info("Created custom role %s with %d permissions", full_name, len(remaining))
            return full_name
        except Exception as exc:
            msg = str(exc)
            # Parse "Permission X is not valid" from the GCP error message.
            match = re.search(r"Permission ([^\s]+) is not valid", msg)
            if match:
                bad = match.group(1)
                logger.warning("Stripping invalid permission %s and retrying", bad)
                remaining = [p for p in remaining if p != bad]
            else:
                raise

    raise ValueError("Failed to create custom role after stripping invalid permissions.")


async def provision_iam_binding(ticket: IAMTicket, dry_run: bool = True) -> dict:
    """Create a project-level custom GCP role and bind it to the requester.

    The role name is the user-supplied identifier (cleaned to a valid role ID).
    Permissions come from the Gemini-synthesized plan.
    Invalid permissions are stripped automatically and a retry is attempted.
    """
    role_id = _clean_role_id(ticket.plan.role)
    project_id = ticket.plan.project_id
    full_role_name = f"projects/{project_id}/roles/{role_id}"

    if dry_run:
        return {
            "status": "DRY_RUN",
            "role": full_role_name,
            "permissions": ticket.plan.permissions,
        }

    config = get_config()
    credentials = service_account.Credentials.from_service_account_file(
        config.service_account_key_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )

    # Step 1: Create (or update) the custom role.
    iam_client = iam_admin_v1.IAMClient(credentials=credentials)
    role_name = _create_custom_role_with_retry(
        iam_client=iam_client,
        project_id=project_id,
        role_id=role_id,
        title=ticket.plan.role,
        description=(ticket.plan.justification or "")[:300],
        permissions=ticket.plan.permissions,
    )

    # Step 2: Bind the custom role to the requester.
    rm_client = resourcemanager_v3.ProjectsClient(credentials=credentials)
    project_name = f"projects/{project_id}"
    policy = gcp_call_with_retry(
        lambda: rm_client.get_iam_policy(request={"resource": project_name})
    )
    policy.bindings.add(
        role=role_name,
        members=[f"user:{ticket.plan.requester_email}"],
    )
    gcp_call_with_retry(
        lambda: rm_client.set_iam_policy(request={"resource": project_name, "policy": policy})
    )
    logger.info("Provisioned %s → %s on %s", ticket.plan.requester_email, role_name, project_id)

    try:
        upsert_iam_ticket({
            "ticket_id": ticket.ticket_id,
            "requester_email": ticket.plan.requester_email,
            "project_id": project_id,
            "role": role_name,
            "status": "provisioned",
            "created_at": ticket.created_at,
            "justification": ticket.plan.justification,
        })
    except Exception as e:
        logger.warning("Failed to persist ticket to ChromaDB: %s", e)

    return {"status": "SUCCESS", "role": role_name}


def load_tickets_from_chroma() -> None:
    """Restore _tickets from ChromaDB on server startup or first request."""
    records = query_all_iam_history()
    for rec in records:
        tid = rec.get("ticket_id")
        if not tid or tid in _tickets:
            continue
        try:
            permissions_raw = rec.get("permissions", "[]")
            permissions = json.loads(permissions_raw) if permissions_raw else []
            plan = SynthesizedIAMPlan(
                requester_email=rec.get("requester_email", ""),
                project_id=rec.get("project_id", ""),
                role=rec.get("role", ""),
                permissions=permissions,
                justification=rec.get("justification", ""),
                synthesized_at=rec.get("synthesized_at") or rec.get("created_at", ""),
                raw_request=rec.get("raw_request", ""),
            )
            ticket = IAMTicket(
                ticket_id=tid,
                plan=plan,
                status=rec.get("status", "pending"),
                created_at=rec.get("created_at", ""),
                reviewed_at=rec.get("reviewed_at") or None,
                reviewed_by=rec.get("reviewed_by") or None,
            )
            _tickets[tid] = ticket
        except Exception as e:
            logger.warning("load_tickets_from_chroma: failed to restore ticket %s: %s", tid, e)
    logger.info("load_tickets_from_chroma: restored %d ticket(s) from ChromaDB", len(_tickets))


async def get_iam_inventory(project_id: str, credentials) -> list[IAMBinding]:
    rm_client = resourcemanager_v3.ProjectsClient(credentials=credentials)
    policy = gcp_call_with_retry(lambda: rm_client.get_iam_policy(request={"resource": f"projects/{project_id}"}))
    
    # FETCH PERSISTENT RECORDS FROM CHROMADB
    history = query_iam_history(project_id)
    
    bindings = []
    now = datetime.now(timezone.utc)
    seen_in_gcp = set()

    # Step 1: Process live GCP bindings
    for b in policy.bindings:
        for m in b.members:
            if not m.startswith("user:") and not m.startswith("serviceAccount:"): continue
            m_type = "user" if m.startswith("user:") else "serviceAccount"
            email = m[len(m_type)+1:]
            seen_in_gcp.add((email, b.role))
            
            # Live activity check for status (Stale/Active/Departed)
            last_activity = check_iam_last_activity(email, project_id, credentials)
            
            last_act_str, days_inact_str, status = "Never", "0d", "Active"
            
            if last_activity:
                last_act_str = last_activity.split("T")[0] if isinstance(last_activity, str) else last_activity.strftime("%Y-%m-%d")
                days_inactive = (now - (datetime.fromisoformat(last_activity.replace("Z", "+00:00")) if isinstance(last_activity, str) else last_activity)).days
                days_inact_str = f"{days_inactive}d"
                if days_inactive > STALENESS_THRESHOLD_DAYS:
                    status = "Stale"
            else:
                # No activity in logs — if in GCP but no activity, check history for 'Departed' context
                # (Departed means they used to have a ticket or record but shouldn't be here now)
                status = "Active" # Default if no logs

            # Merge metadata from history if available
            for t in history:
                if t["requester_email"] == email and t["role"] == b.role:
                    if t["status"] == "revoked": status = "Active (Re-provisioned)"
                    break
            
            bindings.append(IAMBinding(
                identity=email, role=b.role, project_id=project_id, 
                binding_type=m_type, status=status, 
                last_activity=last_act_str, days_inactive=days_inact_str
            ))

    # Step 2: Inject historical records that are NO LONGER in GCP (Revoked or Deleted)
    for t in history:
        email = t["requester_email"]
        role = t["role"]
        if (email, role) not in seen_in_gcp:
            created_dt = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
            days_inact = (now - created_dt).days
            bindings.append(IAMBinding(
                identity=email, role=role, project_id=project_id,
                binding_type="user", status="Revoked" if t["status"] == "revoked" else "Inactive/Departed",
                last_activity=t["created_at"].split("T")[0],
                days_inactive=f"{days_inact}d"
            ))
            
    return bindings
