# Claude.md — v1.0 · FROZEN · 2026-03-30

---

## 1. System Intent

Cerberus is a single-command GCP dev environment guardian: it scans a target
`nexus-tech-dev-*` project, enriches resources with IAM ownership context,
calls Gemini 1.5 Pro to classify each resource, presents a human-approvable plan,
re-validates resource state before execution, executes approved actions, and
writes a complete audit trail. It operates exclusively on dev projects. It never
touches production. Success is a demo-ready agent that runs three consecutive
times on a seeded sandbox and produces identical classifications, a visible
reasoning trace, and a correct JSONL audit log — without crashing, hanging, or
making a single GCP mutation call in dry-run mode.

---

## 2. Hard Invariants

Every invariant below is never negotiable. If a task prompt conflicts with any
invariant, the invariant wins. Stop, flag the conflict, and do not resolve it
silently.

**INV-SCAN-01:** Every resource record emitted by `scan_node` must contain all
four required fields (`resource_id`, `resource_type`, `region`,
`creation_timestamp`) as non-None values before it enters `enrich_node`.
Records missing any required field must be dropped from state and logged at
WARNING level. They must not proceed. This is never negotiable.

**INV-SCAN-02:** A GCE VM is flagged idle if and only if its average CPU
utilisation is below `CPU_IDLE_THRESHOLD` (0.05) for a continuous window of
`CPU_IDLE_WINDOW_HOURS` (72) hours. These values are module-level constants in
`scan_node.py`. No other threshold or window may be used. This is never
negotiable.

**INV-SCAN-03:** `scan_node` must include all persistent disks with no VM
attachment (`resource_type="orphaned_disk"`) and all static external IPs with
no forwarding rule or VM association (`resource_type="unused_ip"`) as distinct
records. If a disk carries label `data-classification=sensitive`, it must have
`flagged_for_review=True` set by `scan_node`. This is never negotiable.

**INV-SCAN-04:** Every resource record must have `estimated_monthly_cost` set
from the Cloud Billing API response. If the billing API call fails after retries,
`estimated_monthly_cost` must be `None` — not `0.0`. A resource with `None` cost
is valid and must not be presented with a zero savings estimate. A hardcoded or
silently zeroed cost is a violation. This is never negotiable.

**INV-ENR-01:** `enrich_node` must attempt ownership resolution in this exact
priority order: (1) GCP resource labels (`owner`, `created-by`, `team`),
(2) Cloud Asset Inventory, (3) IAM binding history, (4) Cloud Audit Log last
mutation actor. The first non-`None` result wins. If all four return `None`,
`ownership_status` is `"no_owner"`. No resource may exit `enrich_node` with
`ownership_status=None`. This is never negotiable.

**INV-ENR-02:** For every resource where a candidate owner email is resolved,
`enrich_node` must call the IAM API to confirm whether that email currently holds
an active IAM binding in the project. If the owner is in the IAM policy but their
last IAM activity timestamp is more than `STALENESS_THRESHOLD_DAYS` (90) days ago,
their `ownership_status` must be downgraded to `"departed_owner"`. This staleness
check is mandatory. This is never negotiable.

**INV-ENR-03:** Any resource with `ownership_status="no_owner"` must have
`flagged_for_review=True` set by `enrich_node`. This flag must be enforced at
four independent points: (1) `enrich_node` sets it; (2) `reason_node` overrides
`decision` to `"needs_review"` in code if the flag is True, regardless of what
Gemini returned; (3) `execute_node` skips any resource with the flag set,
logging `outcome="SKIPPED_GUARDRAIL"`; (4) the React `ApprovalTable` disables the
Approve button for `no_owner` resources. All four must be implemented. Failing any
one of them is a guardrail violation. This is never negotiable.

**INV-RSN-01:** `reason_node` must produce exactly one of `"safe_to_stop"`,
`"safe_to_delete"`, `"needs_review"`, `"skip"` for every resource. These four
values are defined in `VALID_DECISIONS` (a `frozenset` in `state.py`) — the
single source of truth. If Gemini returns a value outside this set, the resource
must be set to `"needs_review"` and a parse-failure event logged. This is never
negotiable.

**INV-RSN-02:** Every resource classification must include a `reasoning` string
of three sentences or fewer, citing at least one quantitative value (idle duration
in hours, owner IAM inactivity in days, or estimated monthly cost in USD). The
reasoning must be stored in LangGraph state. If `reasoning` is empty or absent
after parsing, the Gemini call must be retried once. If still empty, set
`reasoning = "Reasoning unavailable — flagged for human review."` and set
`decision = "needs_review"`. This is never negotiable.

**INV-RSN-03:** Every resource classified `"safe_to_stop"` or `"safe_to_delete"`
must have a non-`None`, non-negative `estimated_monthly_savings` value derived
from `estimated_monthly_cost`. If Gemini returns `0.0` savings for an actionable
decision on a resource with known non-zero cost, override savings to
`estimated_monthly_cost`. This is never negotiable.

**INV-UI-01:** The React `ApprovalTable` must render exactly these columns for
every resource row, with no column ever silently omitted: Resource Name, Type,
Region, Owner, Ownership Status, Decision, Reasoning, Est. Savings ($/mo), Action.
Any `null` or `undefined` field must render `"—"` (em-dash). This is never
negotiable.

**INV-UI-02:** The Execute button must be `disabled` (HTML attribute set, opacity
0.4, `cursor: not-allowed`) when `approvedCount === 0`. No onclick event fires
when the button is disabled. This is never negotiable.

**INV-UI-03:** `dry_run` defaults to `True` in `initialise_state`. When the user
switches to live execution and clicks Execute, a confirmation modal must be shown
listing the exact action count before any GCP mutation API is called. `onExecute()`
is called only when the user explicitly clicks "Execute live" in the modal. Clicking
"Cancel" closes the modal without calling `onExecute()`. This is never negotiable.

**INV-EXE-01:** `execute_node` must call `instances.stop` for `"safe_to_stop"`
resources and the appropriate delete API for `"safe_to_delete"` resources. These
are structurally separate functions (`stop_vm` and `delete_resource`) with no
shared code path. `instances.delete` must never be callable from `stop_vm`.
`instances.stop` must never be callable from `delete_resource`. This is never
negotiable.

**INV-EXE-02:** After each GCP mutation call, `execute_node` must call a read API
to confirm the expected state change before proceeding to the next action. If
verification fails, the action must be marked `outcome="FAILED"` and
`mutation_count` decremented. Execution continues with the next action. This is
never negotiable.

**INV-EXE-03:** `execute_node` must not execute more than 10 GCP mutations per
session. The rate limit check happens before each API call, not after. The counter
is `state["mutation_count"]`, initialised to `0` in `approve_node`. When the
counter reaches 10, the loop halts and a user-facing message is set in
`error_message`. Remaining approved actions are not executed. This is never
negotiable.

**INV-AUD-01:** Every agent action — approved mutations, rejected actions, dry-run
entries, guardrail skips, and node failures — must produce an audit log entry in
the JSONL file with these fields: `timestamp`, `resource_id`, `action_type`,
`llm_reasoning`, `actor`, `outcome`, `run_id`, `session_mutation_count`,
`project_id`. The JSONL write is synchronous and blocking. On `IOError`, the
exception must propagate — the write must not be caught silently. This is never
negotiable.

**INV-AUD-02:** At the conclusion of every agent run, `audit_node` must produce
a `COST_SUMMARY` JSONL entry containing: `resources_scanned`,
`total_waste_identified`, `actions_approved`, `actions_executed`,
`estimated_monthly_savings_recovered`. The recovered savings sum must include only
resources with `outcome="SUCCESS"` — not approved-but-failed actions. This is
never negotiable.

**INV-SEC-01:** `scan_node` must call `validate_project_id` using `re.fullmatch`
with the pattern from config before making any GCP API call. Pattern:
`^nexus-tech-dev-[0-9a-z-]+$`. On failure, `error_message` is set and the
function returns immediately. No GCP call of any kind may be made against a
project that does not match the pattern. This is never negotiable.

**INV-SEC-02:** GCP service account credentials must never appear in any
client-accessible surface: FastAPI response bodies, React UI state,
browser-visible API responses, URL parameters, or JSONL audit log entries. The
`AuditEntry` Pydantic model must contain no credential fields. The
`GET /run/{run_id}/status` endpoint must return no fields from `CerberusConfig`.
This is never negotiable.

**INV-NFR-01:** `scan_node` must complete its full resource discovery within 60
seconds for up to 100 resources. This is enforced with `asyncio.wait_for(...,
timeout=60.0)`. On `TimeoutError`, partial results are returned with a warning in
`error_message`. The node must not block indefinitely. This is never negotiable.

**INV-NFR-02:** Every GCP API call in every node must be wrapped in
`gcp_call_with_retry` (defined in `cerberus/tools/gcp_retry.py`). No node may
implement its own retry logic. Retry policy: exponential backoff (1s, 2s, 4s),
maximum 3 attempts, retry only on HTTP 429 and 503. On 403 or 404: re-raise
immediately. After 3 failures: raise `CerberusRetryExhausted`. This is never
negotiable.

**INV-NFR-03:** If any LangGraph node raises an unhandled exception, `error_node`
must catch it, write a `NODE_ERROR` JSONL entry, set `error_message` in state, and
set `run_complete=True`. The React UI must never display a raw stack trace or
remain in an indefinite loading state. This is never negotiable.

---

## 3. Scope Boundary

### Files CC is permitted to create or modify

```
cerberus/__init__.py
cerberus/config.py
cerberus/state.py
cerberus/graph.py
cerberus/api.py
cerberus/nodes/__init__.py
cerberus/nodes/scan_node.py
cerberus/nodes/enrich_node.py
cerberus/nodes/reason_node.py
cerberus/nodes/approve_node.py
cerberus/nodes/revalidate_node.py
cerberus/nodes/execute_node.py
cerberus/nodes/audit_node.py
cerberus/tools/__init__.py
cerberus/tools/gcp_retry.py
cerberus/tools/chroma_client.py
tests/__init__.py
tests/conftest.py
tests/test_foundation.py
tests/test_scan.py
tests/test_enrich.py
tests/test_reason.py
tests/test_execute.py
tests/test_audit.py
tests/test_graph.py
tests/test_e2e.py
tests/fixtures/sample_resources.json
frontend/src/components/ApprovalTable.tsx
frontend/src/components/ExecutePanel.tsx
frontend/src/App.tsx
frontend/src/types.ts
frontend/src/api.ts
frontend/package.json
frontend/tsconfig.json
scripts/seed_sandbox.py
scripts/verify_seed.py
scripts/run_demo_smoke_test.py
pyproject.toml
.env.example
.gitignore
README.md
```

CC must not create any file not listed above without explicit instruction.

### What CC must never do

**Never create or modify:**
- Any file outside the list above
- A second Pydantic model for `AuditEntry` — there is exactly one, in `audit_node.py`
- A second definition of `VALID_DECISIONS` or `VALID_OUTCOMES` — these are defined once in `state.py` and imported everywhere
- Any migration file, Alembic config, or database schema file — there is no relational database in this system
- Any `docker-compose.yml`, `Dockerfile`, or container config — deployment is Cloud Run, not local containers
- `.env` — this file is never generated by CC; it is created by the engineer from `.env.example`
- `cerberus-key.json` or any GCP credential file

**Never use these technologies:**
- Firestore, Datastore, or any GCP-managed database — in-memory state and local JSONL only
- SQLite, PostgreSQL, MySQL, or any relational database
- Pinecone, Weaviate, Qdrant, or any external vector database — ChromaDB embedded only
- Redis or Memcached
- Jira, ServiceNow, Slack, or any ticketing/messaging integration
- Google Calendar API
- AWS or Azure SDKs
- Any LangGraph checkpointer other than `MemorySaver` — specifically not `SqliteSaver`, `AsyncSqliteSaver`, or `FirestoreSaver`
- Any GCP API not listed in the Fixed Stack below — if a task seems to require a new API, stop and flag it
- `langchain` core chains or agents — LangGraph only; `langchain-google-genai` is used only for the Gemini embedding model if needed; all LLM calls go through `google-generativeai` directly

**Never silently resolve a conflict:**
- If a task prompt conflicts with an invariant: state which invariant is violated and stop. Do not implement the task and add a comment.
- If a task asks for a technology not in the Fixed Stack: flag it, do not substitute silently.
- If a task asks CC to write to `.env` or any credential file: refuse and explain why.
- If a task asks for retry logic inside a node function: redirect to `gcp_call_with_retry`. Duplicate retry logic is a violation of INV-NFR-02.

**Never add unsolicited dependencies:**
- Do not add any package to `pyproject.toml` not listed in the Fixed Stack
- Do not install packages at runtime (`subprocess.run(["pip", ...])` is forbidden)
- Do not import from a package not in `pyproject.toml`

**Approval gate enforcement:**
- `approve_node` uses `langgraph.types.interrupt`. It must never be implemented as a polling loop, a sleep, or a direct API call. The interrupt mechanism is the only permitted implementation.
- The Execute button in `ExecutePanel.tsx` must never be enabled by default or programmatically enabled without the modal confirmation flow.

---

## 4. Fixed Stack

All versions are minimum versions unless marked exact (`==`). CC must use these
exact package names. Do not substitute aliases, forks, or equivalent libraries.

### Python runtime

```
python >= 3.11
package manager: uv
```

### Core Python dependencies (`pyproject.toml` — exact names)

```
langgraph >= 0.2.0
langchain-google-genai >= 2.0.0        # used for embeddings only if needed
google-generativeai >= 0.7.0           # all Gemini LLM calls use this SDK directly
google-cloud-compute >= 1.18.0
google-cloud-billing >= 1.13.0
google-cloud-asset >= 3.24.0
google-cloud-monitoring >= 2.22.0
google-cloud-iam >= 2.15.0
google-cloud-resource-manager >= 1.12.0
google-cloud-logging >= 3.10.0
fastapi >= 0.115.0
uvicorn[standard] >= 0.32.0
python-dotenv >= 1.0.0
pydantic >= 2.9.0
chromadb >= 0.5.0
tenacity >= 9.0.0
```

### Dev dependencies

```
pytest >= 8.3.0
pytest-asyncio >= 0.24.0
pytest-mock >= 3.14.0
httpx >= 0.27.0
```

### Frontend

```
react >= 18.0.0
typescript >= 5.0.0
vite >= 5.0.0             # build tool
@testing-library/react >= 14.0.0
@testing-library/jest-dom >= 6.0.0
vitest >= 1.0.0           # test runner (not Jest — Vite project uses Vitest)
```

### LangGraph internals

```
Checkpointer: MemorySaver (from langgraph.checkpoint.memory)
Interrupt mechanism: interrupt (from langgraph.types)
Graph class: StateGraph (from langgraph.graph)
State type: TypedDict (from typing_extensions or typing)
```

### Gemini configuration

```
Model: gemini-1.5-pro-002             # exact string, loaded from GEMINI_MODEL env var
Temperature: 0                         # all reason_node calls
response_mime_type: "application/json" # all reason_node calls
Inter-request delay: 0.5 seconds       # GEMINI_INTER_REQUEST_DELAY_SECONDS constant
```

### ChromaDB configuration

```
Client: chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
Collection name: "resource_history"    # exact string, do not vary
Embedding function: default (all-MiniLM-L6-v2 via chromadb)
Write point: audit_node only           # never written from any other node
```

### Storage

```
Agent run state:   LangGraph in-memory TypedDict — no persistence
Audit log:         Append-only JSONL — one file per run_id
                   Path: {AUDIT_LOG_DIR}/audit_{run_id}.jsonl
Resource history:  ChromaDB embedded — persists to {CHROMA_PERSIST_DIR}/
```

### GCP APIs used (complete list — no others permitted)

```
compute.googleapis.com          # VMs, disks, IPs
monitoring.googleapis.com       # CPU utilisation metrics
cloudasset.googleapis.com       # ownership resolution step 2
cloudresourcemanager.googleapis.com  # IAM policy read
iam.googleapis.com              # IAM membership check
logging.googleapis.com          # audit log and IAM history queries
cloudbilling.googleapis.com     # per-resource cost data
```

### Environment variables (exact names — no variations)

```
GCP_PROJECT_ID                  # target project for the current run
GCP_SERVICE_ACCOUNT_KEY_PATH    # path to service account JSON key
BILLING_ACCOUNT_ID              # GCP billing account ID (format: XXXXXX-XXXXXX-XXXXXX)
GEMINI_API_KEY                  # Gemini API key
GEMINI_MODEL                    # default: gemini-1.5-pro-002
ALLOWED_PROJECT_PATTERN         # default: ^nexus-tech-dev-[0-9a-z-]+$
LANGSMITH_API_KEY               # optional — LangSmith observability
LANGSMITH_PROJECT               # default: cerberus
CHROMA_PERSIST_DIR              # default: ./chroma_db
AUDIT_LOG_DIR                   # default: ./logs
```

### Module-level constants (exact names and values — do not rename)

```python
# cerberus/nodes/scan_node.py
CPU_IDLE_THRESHOLD: float = 0.05
CPU_IDLE_WINDOW_HOURS: int = 72

# cerberus/nodes/enrich_node.py
STALENESS_THRESHOLD_DAYS: int = 90

# cerberus/nodes/reason_node.py
GEMINI_INTER_REQUEST_DELAY_SECONDS: float = 0.5

# cerberus/state.py
VALID_DECISIONS: frozenset = frozenset({"safe_to_stop","safe_to_delete","needs_review","skip"})
VALID_OUTCOMES: frozenset = frozenset({"SUCCESS","FAILED","REJECTED","SKIPPED_GUARDRAIL","DRY_RUN"})
```

### FastAPI endpoints (exact paths — do not add routes)

```
POST /run                    start a new agent run
GET  /run/{run_id}/plan      return current approval payload (poll until available)
POST /run/{run_id}/approve   resume graph with approved_ids
GET  /run/{run_id}/status    return run state (no credentials)
```

### Ownership lookup priority (exact order — do not reorder)

```
1. GCP resource labels: "owner" key, then "created-by", then "team"
2. Cloud Asset Inventory search
3. IAM binding history (Cloud Audit Log — setIamPolicy events)
4. Cloud Audit Log last mutation actor
```

### Outcome values (exact strings — import from VALID_OUTCOMES in state.py)

```
SUCCESS | FAILED | REJECTED | SKIPPED_GUARDRAIL | DRY_RUN
```

---

*Any deviation from this document during build requires stopping, returning to
Claude Desktop, updating the relevant planning artifact, and producing a new
versioned Claude.md. Never edit this file inline during Phase 6.*
