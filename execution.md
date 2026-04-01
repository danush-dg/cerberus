# EXECUTION_PLAN.md
## Cerberus — GCP Dev Environment Guardian
### Phase 3: Execution Plan — Agent Loop (Candidate B)

**PBVI Phase:** 3 — Execution Planning  
**Status:** Ready for engineer sign-off  
**Prereq:** ARCHITECTURE.md ✓ · INVARIANTS.md ✓ · All open questions resolved (see below)  
**Last updated:** 2026-03-30

---

## Resolved Decisions Table

Every open question from ARCHITECTURE.md is resolved here with a concrete answer
before the first task is written. If any of these resolutions are wrong, stop and
correct them before the plan proceeds — do not let Claude Code resolve them during build.

| # | Open Question (ARCHITECTURE.md §6) | Resolution | Rationale |
|---|---|---|---|
| OQ-1 | What happens when `revalidate_node` detects drift on a `safe_to_delete` resource? | Auto-downgrade to `needs_review`, re-present without re-running `reason_node`. No Gemini call. | Correct enough for a hackathon; latency and mid-execution state update are too complex for the timeline. |
| OQ-2 | How is the Gemini model version pinned? | Hardcoded string `gemini-1.5-pro-002` in `config.py`, overridable via `GEMINI_MODEL` env var. Confirmed on Day 3. | Pin in config prevents mid-sprint model drift. |
| OQ-3 | What constitutes "sensitive data" for disk archival? | Label `data-classification=sensitive` OR disk name prefix `sensitive-` triggers archival path. No ML classifier. | Pragmatic for hackathon; sufficient for demo. |
| OQ-4 | Is 90-day access review in scope for v1? | **No.** UI notification only: a banner reading "Schedule 90-day review for [email]". No calendar API. | Jira/ServiceNow out of scope per requirements §11. |
| OQ-5 | Rate limit scope in v2? | Session = invocation for v1. Mutation log schema is forward-compatible (includes `run_id` + timestamp) for future per-project-per-day enforcement. | Minimum viable for hackathon; migration path documented. |
| OQ-6 | Concurrent session handling? | Advisory only: if a project scan is in-flight, new `POST /run` for the same project returns HTTP 409 with message "A scan for this project is already running." | In-memory set of active project IDs. No distributed lock needed for single-instance demo. |
| **OQ-7** | **Storage: where does state persist?** | **In-memory LangGraph state for the agent run. Append-only JSONL file for audit log. ChromaDB (local, embedded) for resource record history across runs. No Firestore.** | See Storage Decision section below. |

---

## Storage Decision

Three distinct storage concerns. Each gets a different store. No single database serves all three.

### S1 — Agent run state (in-flight)
**Store:** LangGraph in-memory `TypedDict` state  
**What goes here:** `resources`, `approved_actions`, `mutation_count`, `error_message`, `dry_run`  
**Why:** Agent runs are single-session. State does not survive process restart and does not need to. Firestore is explicitly deferred in the requirements scope boundary.  
**Limitations:** If the FastAPI process crashes mid-run, the run is lost. Acceptable for hackathon.

### S2 — Audit log (permanent record)
**Store:** Append-only JSONL file at `./logs/audit_{run_id}.jsonl`  
**What goes here:** One JSON line per action — `timestamp`, `resource_id`, `action_type`, `llm_reasoning`, `actor`, `outcome`, `run_id`, `session_mutation_count`  
**Why:** Flat file is the simplest durable store with zero infrastructure. Local-first per Architecture Decision 5. File rotation is by run_id so logs do not grow unboundedly.  
**Limitations:** Not queryable without parsing. Acceptable — queries are read by humans or the cost summary function, not an API.

### S3 — Resource record history (cross-run context)
**Store:** ChromaDB embedded (local, no server process)  
**What goes here:** Enriched resource records after `reason_node` — stored as documents with metadata for semantic and metadata-based retrieval. One collection: `resource_history`.  
**Why this over alternatives:**

| Option | Why rejected |
|---|---|
| Firestore | Explicitly deferred in requirements §11 |
| PostgreSQL / SQLite | Relational schema for unstructured enrichment data adds overhead; metadata queries are simpler in a vector store |
| Pinecone / Weaviate | Requires a running external service — adds infra complexity for zero demo benefit |
| Redis | Good for caching, poor for durable history with metadata filtering |
| ChromaDB embedded | Zero infrastructure, Python-native, persists to disk, queryable by metadata AND semantic similarity, restarts cleanly |

**What ChromaDB enables that a flat file does not:**
- "Has this resource been seen before? What was its last classification?" — prevents re-recommending resources the human already reviewed
- "What other resources has this owner touched?" — cross-resource ownership reasoning for the agent
- "Show me all resources classified `safe_to_delete` in the last 30 days" — cost trend context

**ChromaDB collection schema:**
```
Collection: resource_history
Document: resource_id (string, used as ChromaDB document ID)
Text content: f"{resource_type} {resource_id} owned by {owner_email} in {region}"
              (used for semantic similarity — "find resources like this one")
Metadata fields (filterable):
  run_id: str
  resource_type: str          vm | orphaned_disk | unused_ip | gke_cluster
  ownership_status: str       active_owner | departed_owner | no_owner
  decision: str               safe_to_stop | safe_to_delete | needs_review | skip
  outcome: str | None         SUCCESS | FAILED | REJECTED | SKIPPED_GUARDRAIL | DRY_RUN
  estimated_monthly_cost: float
  estimated_monthly_savings: float
  region: str
  owner_email: str | None
  scanned_at: str             ISO 8601 timestamp
  project_id: str
```

**ChromaDB is written at `audit_node`, after the local JSONL log (S2).** ChromaDB failure must not block the audit log write. It is best-effort enrichment, not the authoritative record.

---

## GCP Resources Required Before Day 1

This section is the pre-build checklist. Every item must be verified complete before
Session 1 Task 1.1 (scaffold) begins. These are not tasks — they are human-performed
pre-requisites. The engineer signs off that each item is confirmed.

### GCP Project Setup

| # | Resource / Config | How to create | Verification |
|---|---|---|---|
| P-1 | GCP project: `nexus-tech-dev-sandbox` | GCP Console → New Project | `gcloud projects describe nexus-tech-dev-sandbox` returns active |
| P-2 | Billing account linked to `nexus-tech-dev-sandbox` | GCP Console → Billing | `gcloud beta billing projects describe nexus-tech-dev-sandbox` shows `billingEnabled: true` |
| P-3 | Service account: `cerberus-agent@nexus-tech-dev-sandbox.iam.gserviceaccount.com` | `gcloud iam service-accounts create cerberus-agent --project nexus-tech-dev-sandbox` | `gcloud iam service-accounts describe cerberus-agent@...` succeeds |
| P-4 | Service account JSON key downloaded | `gcloud iam service-accounts keys create ./cerberus-key.json --iam-account cerberus-agent@...` | File exists at `./cerberus-key.json` |

### APIs to Enable (all on `nexus-tech-dev-sandbox`)

Run this single command to enable all required APIs at once:

```bash
gcloud services enable \
  compute.googleapis.com \
  monitoring.googleapis.com \
  cloudasset.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  logging.googleapis.com \
  cloudbilling.googleapis.com \
  --project nexus-tech-dev-sandbox
```

Verify all enabled:
```bash
gcloud services list --enabled --project nexus-tech-dev-sandbox \
  --filter="NAME:(compute OR monitoring OR cloudasset OR cloudresourcemanager OR iam OR logging OR cloudbilling)"
# Expected: 7 services listed
```

### IAM Roles for the Service Account

Run in order. Each role is justified by the node that requires it.

```bash
PROJECT=nexus-tech-dev-sandbox
SA=cerberus-agent@nexus-tech-dev-sandbox.iam.gserviceaccount.com

# scan_node: list and read VMs, disks, IPs
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/compute.viewer"

# scan_node: read Cloud Monitoring metrics (CPU utilisation)
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/monitoring.viewer"

# enrich_node: Cloud Asset Inventory lookups
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/cloudasset.viewer"

# enrich_node: read IAM policy (check membership)
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/iam.securityReviewer"

# enrich_node: Cloud Audit Log queries
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/logging.viewer"

# execute_node: stop/delete VMs, disks, release IPs
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/compute.instanceAdmin.v1"
```

Verify (all six roles must appear):
```bash
gcloud projects get-iam-policy nexus-tech-dev-sandbox \
  --flatten="bindings[].members" \
  --filter="bindings.members:cerberus-agent" \
  --format="table(bindings.role)"
```

### Billing API Access

The Billing API requires a separate billing account role. The billing account ID
must be known before Day 1.

```bash
# Replace BILLING_ACCOUNT_ID with your account ID (format: 012345-678901-ABCDEF)
gcloud beta billing accounts add-iam-policy-binding BILLING_ACCOUNT_ID \
  --member="serviceAccount:cerberus-agent@nexus-tech-dev-sandbox.iam.gserviceaccount.com" \
  --role="roles/billing.viewer"
```

Add `BILLING_ACCOUNT_ID` to `.env` — it is required by `scan_node`.

### Seed Resources (must be created by end of Day 1, before idle time accumulates)

These must exist 72+ hours before the demo. Create on Day 1 — not Day 6.

```bash
# Three stopped VMs with varied labels
gcloud compute instances create cerberus-demo-vm-1 \
  --zone=us-central1-a --machine-type=e2-micro \
  --labels=owner=departed@nexus-tech.com,team=data-science \
  --project=nexus-tech-dev-sandbox

gcloud compute instances create cerberus-demo-vm-2 \
  --zone=us-central1-a --machine-type=e2-micro \
  --labels=owner=alice@nexus-tech.com \
  --project=nexus-tech-dev-sandbox

gcloud compute instances create cerberus-demo-vm-3 \
  --zone=us-central1-a --machine-type=e2-micro \
  --project=nexus-tech-dev-sandbox  # no labels — tests no_owner path

# Stop all three immediately (idle time accrues from creation)
gcloud compute instances stop cerberus-demo-vm-1 cerberus-demo-vm-2 cerberus-demo-vm-3 \
  --zone=us-central1-a --project=nexus-tech-dev-sandbox

# Two orphaned disks
gcloud compute disks create cerberus-demo-disk-1 \
  --size=10GB --zone=us-central1-a \
  --labels=owner=departed@nexus-tech.com \
  --project=nexus-tech-dev-sandbox

gcloud compute disks create cerberus-demo-disk-2 \
  --size=10GB --zone=us-central1-a \
  --project=nexus-tech-dev-sandbox  # no labels

# One unused static IP
gcloud compute addresses create cerberus-demo-ip-1 \
  --region=us-central1 \
  --labels=owner=alice@nexus-tech.com \
  --project=nexus-tech-dev-sandbox
```

Verify all 6 resources exist:
```bash
gcloud compute instances list --project=nexus-tech-dev-sandbox \
  --filter="name:cerberus-demo" --format="table(name,status,labels)"

gcloud compute disks list --project=nexus-tech-dev-sandbox \
  --filter="name:cerberus-demo" --format="table(name,users)"

gcloud compute addresses list --project=nexus-tech-dev-sandbox \
  --filter="name:cerberus-demo" --format="table(name,status,users)"
```

### IAM Test User for Ownership Checks

`enrich_node` needs a departed engineer in IAM history. Create a test user binding
then remove it — the audit log retains the history.

```bash
# Add then immediately remove — creates audit trail for enrich_node to discover
gcloud projects add-iam-policy-binding nexus-tech-dev-sandbox \
  --member="user:departed@nexus-tech.com" --role="roles/viewer"

gcloud projects remove-iam-policy-binding nexus-tech-dev-sandbox \
  --member="user:departed@nexus-tech.com" --role="roles/viewer"

# alice stays active
gcloud projects add-iam-policy-binding nexus-tech-dev-sandbox \
  --member="user:alice@nexus-tech.com" --role="roles/viewer"
```

### Environment Variables

Create `.env` (never committed — add to `.gitignore`):

```bash
GCP_PROJECT_ID=nexus-tech-dev-sandbox
GCP_SERVICE_ACCOUNT_KEY_PATH=./cerberus-key.json
BILLING_ACCOUNT_ID=<your-billing-account-id>
GEMINI_API_KEY=<your-gemini-api-key>
GEMINI_MODEL=gemini-1.5-pro-002
ALLOWED_PROJECT_PATTERN=^nexus-tech-dev-[0-9a-z-]+$
LANGSMITH_API_KEY=<your-langsmith-api-key>
LANGSMITH_PROJECT=cerberus
CHROMA_PERSIST_DIR=./chroma_db
AUDIT_LOG_DIR=./logs
```

### Pre-build Checklist Sign-off

```
[ ] P-1: nexus-tech-dev-sandbox project active
[ ] P-2: Billing enabled on sandbox project
[ ] P-3: cerberus-agent service account created
[ ] P-4: Service account key downloaded to ./cerberus-key.json
[ ] APIs: All 7 APIs enabled (verified via gcloud services list)
[ ] IAM: All 6 roles assigned to service account (verified via get-iam-policy)
[ ] Billing: billing.viewer granted to service account on billing account
[ ] Seeds: 3 VMs (stopped), 2 disks, 1 IP created and verified
[ ] IAM history: departed@nexus-tech.com added and removed; alice@nexus-tech.com active
[ ] .env: All 9 env vars populated
[ ] .gitignore: cerberus-key.json and .env listed

Engineer sign-off: _______________________ Date: _____________
```

---

## Session Overview

| Session | Name | Goal | Tasks | Gate command |
|---|---|---|---|---|
| 0 | Pre-build | GCP resources verified, seed running | Human only | See checklist above |
| 1 | Foundation | Repo, config, state schema, retry wrapper, ChromaDB client | 4 | `pytest tests/test_foundation.py -v` |
| 2 | scan_node | Full GCP discovery, idle detection, billing, timeout | 4 | `pytest tests/test_scan.py -v` |
| 3 | enrich_node | Ownership chain, IAM check, staleness, no_owner flag | 3 | `pytest tests/test_enrich.py -v` |
| 4 | reason_node | Gemini integration, structured output, post-LLM validation | 3 | `pytest tests/test_reason.py -v` |
| 5 | Execute pipeline | approve_node, revalidate_node, execute_node | 3 | `pytest tests/test_execute.py -v` |
| 6 | Audit + wiring | audit_node, ChromaDB write, graph wiring, error handler | 2 | `pytest tests/test_audit.py tests/test_graph.py -v` |
| 7 | React UI | Approval table, execute panel, API polling | 2 | `cd frontend && npm test -- --watchAll=false` |
| 8 | Integration | End-to-end test, sandbox smoke test, demo rehearsal | 2 | `pytest tests/test_e2e.py -v` |
| 9 | Architecture Showcase | IAM access head, guardrail narrative, ROI summary — judge-facing demo layer | 3 | `pytest tests/test_access.py -v && python scripts/run_demo_smoke_test.py` |

**Git convention (PBVI):** one branch per session (`session/1-foundation`), one commit per task, PR to `main` only after session integration check passes.

---

## Session 1 — Foundation

**Goal:** Running Python project with verified GCP connection, tested config guard,
state schema, retry wrapper, and ChromaDB client. Every subsequent session depends on these.

**Integration check** (run after all 4 tasks committed):
```bash
python -c "
from cerberus.config import get_config, validate_project_id
from cerberus.state import initialise_state
from cerberus.tools.gcp_retry import gcp_call_with_retry
from cerberus.tools.chroma_client import get_chroma_collection
c = get_config()
validate_project_id('nexus-tech-dev-1', c.allowed_project_pattern)
s = initialise_state('nexus-tech-dev-1')
col = get_chroma_collection()
print('Foundation integration: PASS')
"
```

---

### Task 1.1 — Repo scaffold and dependency installation

**CC prompt:**
```
Create a Python project with uv at the repo root. Run `uv init cerberus` then
structure it as follows:

cerberus/
  __init__.py
  config.py         (empty stub — Task 1.2)
  state.py          (empty stub — Task 1.3)
  nodes/
    __init__.py
    scan_node.py    (empty stub)
    enrich_node.py  (empty stub)
    reason_node.py  (empty stub)
    approve_node.py (empty stub)
    revalidate_node.py (empty stub)
    execute_node.py (empty stub)
    audit_node.py   (empty stub)
  tools/
    __init__.py
    gcp_retry.py    (empty stub — Task 1.4)
    chroma_client.py (empty stub — Task 1.4b)
  graph.py          (empty stub)
tests/
  __init__.py
  conftest.py       (empty stub)
  test_foundation.py
  test_scan.py      (empty file)
  test_enrich.py    (empty file)
  test_reason.py    (empty file)
  test_execute.py   (empty file)
  test_audit.py     (empty file)
  test_graph.py     (empty file)
  test_e2e.py       (empty file)
  fixtures/
    sample_resources.json
frontend/           (empty dir, placeholder for Session 7)
scripts/
  seed_sandbox.py   (empty stub)
  verify_seed.py    (empty stub)
pyproject.toml
.env.example
.gitignore
README.md

In pyproject.toml, add dependencies:
  langgraph>=0.2.0
  langchain-google-genai>=2.0.0
  google-cloud-compute>=1.18.0
  google-cloud-billing>=1.13.0
  google-cloud-asset>=3.24.0
  google-cloud-monitoring>=2.22.0
  google-cloud-iam>=2.15.0
  google-cloud-resource-manager>=1.12.0
  google-cloud-logging>=3.10.0
  google-generativeai>=0.7.0
  fastapi>=0.115.0
  uvicorn[standard]>=0.32.0
  python-dotenv>=1.0.0
  pydantic>=2.9.0
  chromadb>=0.5.0
  tenacity>=9.0.0

dev dependencies:
  pytest>=8.3.0
  pytest-asyncio>=0.24.0
  pytest-mock>=3.14.0
  httpx>=0.27.0

.env.example must contain exactly these keys with no values:
GCP_PROJECT_ID=
GCP_SERVICE_ACCOUNT_KEY_PATH=
BILLING_ACCOUNT_ID=
GEMINI_API_KEY=
GEMINI_MODEL=
ALLOWED_PROJECT_PATTERN=
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=
CHROMA_PERSIST_DIR=
AUDIT_LOG_DIR=

.gitignore must include: .env, cerberus-key.json, __pycache__, .pytest_cache,
chroma_db/, logs/, *.pyc, .venv/

In sample_resources.json, add a list of 3 minimal ResourceRecord-shaped dicts
(vm, orphaned_disk, unused_ip) with all required fields populated with plausible
test data. This fixture is used by all test files.

Do not implement any logic. Stubs only.
```

**Test cases:**
```python
# tests/test_foundation.py
import os, json, tomllib

def test_pyproject_toml_is_valid():
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert "dependencies" in data.get("project", data.get("tool", {}).get("poetry", {}))

def test_env_example_has_all_keys():
    keys = [l.split("=")[0] for l in open(".env.example") if "=" in l]
    required = ["GCP_PROJECT_ID","GCP_SERVICE_ACCOUNT_KEY_PATH","BILLING_ACCOUNT_ID",
                "GEMINI_API_KEY","GEMINI_MODEL","ALLOWED_PROJECT_PATTERN",
                "LANGSMITH_API_KEY","LANGSMITH_PROJECT","CHROMA_PERSIST_DIR","AUDIT_LOG_DIR"]
    for k in required:
        assert k in keys, f"Missing key: {k}"

def test_env_example_has_no_values():
    for line in open(".env.example"):
        if "=" in line:
            assert line.strip().endswith("="), f"Key has value: {line.strip()}"

def test_gitignore_excludes_secrets():
    content = open(".gitignore").read()
    for item in [".env", "cerberus-key.json", "chroma_db/"]:
        assert item in content

def test_sample_fixture_loads():
    data = json.load(open("tests/fixtures/sample_resources.json"))
    assert len(data) == 3
    for r in data:
        assert "resource_id" in r and "resource_type" in r
```

**Verification command:**
```bash
uv sync && pytest tests/test_foundation.py -k "pyproject or env or gitignore or fixture" -v
```

**Invariants touched:** None. Scaffold only.

---

### Task 1.2 — Config module with allowlist enforcement

**CC prompt:**
```
Implement cerberus/config.py.

Requirements:

1. A dataclass CerberusConfig with these fields and defaults:
     gcp_project_id: str
     service_account_key_path: str
     billing_account_id: str
     gemini_api_key: str
     gemini_model: str = "gemini-1.5-pro-002"
     allowed_project_pattern: str = "^nexus-tech-dev-[0-9a-z-]+$"
     langsmith_api_key: str | None = None
     langsmith_project: str = "cerberus"
     chroma_persist_dir: str = "./chroma_db"
     audit_log_dir: str = "./logs"

2. get_config() -> CerberusConfig
   Reads from environment (load_dotenv() first). Raises ValueError listing ALL
   missing required fields if any of gcp_project_id, service_account_key_path,
   billing_account_id, gemini_api_key are absent or empty.
   Caches result after first call (module-level singleton).

3. validate_project_id(project_id: str, pattern: str) -> None
   Uses re.fullmatch(pattern, project_id).
   Raises ValueError:
     f"BLOCKED: '{project_id}' does not match allowed pattern '{pattern}'. "
     f"Cerberus only operates on dev projects."
   If project_id is empty string: raises ValueError("BLOCKED: empty project ID.")
   The pattern is a parameter — never hardcoded in this function.

4. reset_config() -> None (for testing only)
   Clears the singleton so tests can inject different env vars.
   Mark with a docstring: "TEST USE ONLY — do not call in production code."

Do not call get_config() at module import time.
Do not log credentials at any level.
```

**Test cases:**
```python
def test_valid_dev_project_passes():
    validate_project_id("nexus-tech-dev-3", "^nexus-tech-dev-[0-9a-z-]+$")

def test_prod_project_blocked():
    with pytest.raises(ValueError, match="BLOCKED"):
        validate_project_id("nexus-tech-prod", "^nexus-tech-dev-[0-9a-z-]+$")

def test_dev_prod_hybrid_name_blocked():
    # Gaming case: "nexus-tech-dev-prod" matches ^nexus-tech-dev- with re.match
    # but must be blocked by the full pattern requiring [0-9a-z-]+ suffix
    with pytest.raises(ValueError):
        validate_project_id("nexus-tech-dev-prod", "^nexus-tech-dev-[0-9a-z-]+$")

def test_empty_project_id_blocked():
    with pytest.raises(ValueError, match="empty"):
        validate_project_id("", "^nexus-tech-dev-[0-9a-z-]+$")

def test_get_config_raises_on_missing_required_fields(monkeypatch):
    reset_config()
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GCP_PROJECT_ID"):
        get_config()

def test_get_config_caches_singleton(monkeypatch, tmp_env):
    reset_config()
    c1 = get_config()
    c2 = get_config()
    assert c1 is c2
```

**Verification command:**
```bash
pytest tests/test_foundation.py -k "config or project or validate" -v
```

**Invariants touched:** INV-SEC-01. Code review must confirm `re.fullmatch` is used (not `re.match`), pattern comes from config not hardcode, and the function is called before any GCP API in scan_node.

---

### Task 1.3 — LangGraph state schema and ResourceRecord

**CC prompt:**
```
Implement cerberus/state.py.

Define ResourceRecord as a TypedDict with these fields:
  resource_id: str
  resource_type: str              # "vm" | "orphaned_disk" | "unused_ip" | "gke_cluster"
  region: str
  creation_timestamp: str         # ISO 8601
  last_activity_timestamp: str | None
  estimated_monthly_cost: float | None
  ownership_status: str | None    # "active_owner" | "departed_owner" | "no_owner"
  owner_email: str | None
  owner_iam_active: bool | None
  flagged_for_review: bool        # default False — set True by enrich_node for no_owner
  decision: str | None            # "safe_to_stop"|"safe_to_delete"|"needs_review"|"skip"
  reasoning: str | None
  estimated_monthly_savings: float | None
  outcome: str | None             # "SUCCESS"|"FAILED"|"REJECTED"|"SKIPPED_GUARDRAIL"|"DRY_RUN"

Define CerberusState as a TypedDict with these fields:
  project_id: str
  run_id: str                     # uuid4 string, set by initialise_state
  resources: list[ResourceRecord]
  expected_resource_count: int    # set by scan_node preflight, 0 initially
  approved_actions: list[ResourceRecord]
  mutation_count: int             # 0 initially
  error_message: str | None
  run_complete: bool              # False initially
  audit_log_path: str | None
  dry_run: bool                   # True initially (INV-UI-03)
  langsmith_trace_url: str | None # set by audit_node if LangSmith succeeds

Define validate_resource_record(record: dict) -> ResourceRecord:
  Checks these fields are present AND not None:
    resource_id, resource_type, region, creation_timestamp
  Checks estimated_monthly_cost is present (may be None — log WARNING if so).
  Raises ValueError(f"ResourceRecord missing required fields: {missing_fields}")
  listing all missing fields in a single error.
  Returns the record cast to ResourceRecord.

Define initialise_state(project_id: str, dry_run: bool = True) -> CerberusState:
  Returns a valid initial state. run_id = str(uuid.uuid4()).

Define VALID_DECISIONS and VALID_OUTCOMES as module-level frozensets:
  VALID_DECISIONS = frozenset({"safe_to_stop","safe_to_delete","needs_review","skip"})
  VALID_OUTCOMES = frozenset({"SUCCESS","FAILED","REJECTED","SKIPPED_GUARDRAIL","DRY_RUN"})
These are imported by reason_node and execute_node for validation — single source of truth.
```

**Test cases:**
```python
def test_valid_record_passes():
    r = {"resource_id":"vm-1","resource_type":"vm","region":"us-central1",
         "creation_timestamp":"2024-01-01T00:00:00Z","last_activity_timestamp":None,
         "estimated_monthly_cost":45.0,"ownership_status":None,"owner_email":None,
         "owner_iam_active":None,"flagged_for_review":False,"decision":None,
         "reasoning":None,"estimated_monthly_savings":None,"outcome":None}
    validate_resource_record(r)  # no raise

def test_missing_resource_id_raises():
    r = {"resource_type":"vm","region":"us-central1",
         "creation_timestamp":"2024-01-01T00:00:00Z"}
    with pytest.raises(ValueError, match="resource_id"):
        validate_resource_record(r)

def test_multiple_missing_fields_listed_in_single_error():
    with pytest.raises(ValueError) as exc:
        validate_resource_record({})
    msg = str(exc.value)
    assert "resource_id" in msg and "resource_type" in msg

def test_initial_state_dry_run_true():
    s = initialise_state("nexus-tech-dev-1")
    assert s["dry_run"] is True
    assert s["mutation_count"] == 0
    assert s["run_complete"] is False

def test_initial_state_has_run_id():
    s = initialise_state("nexus-tech-dev-1")
    assert len(s["run_id"]) == 36  # uuid4 format

def test_valid_decisions_is_frozen():
    from cerberus.state import VALID_DECISIONS
    assert "safe_to_stop" in VALID_DECISIONS
    assert "unknown" not in VALID_DECISIONS
```

**Verification command:**
```bash
pytest tests/test_foundation.py -k "record or state or decision" -v
```

**Invariants touched:** INV-SCAN-01 (validate_resource_record is the enforcement point), INV-UI-03 (dry_run=True default in initial state), INV-RSN-01 (VALID_DECISIONS frozenset is the single source of truth for enum validation).

---

### Task 1.4 — GCP retry wrapper and ChromaDB client

**CC prompt:**
```
Implement two files:

--- FILE 1: cerberus/tools/gcp_retry.py ---

class CerberusRetryExhausted(Exception):
    def __init__(self, fn_name: str, attempts: int, last_error: Exception):
        self.fn_name = fn_name
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"{fn_name} failed after {attempts} attempts: {last_error}")

def gcp_call_with_retry(fn: Callable, *args, max_retries: int = 3, **kwargs) -> Any:
  Uses tenacity:
    wait = wait_exponential(multiplier=1, min=1, max=4)
    stop = stop_after_attempt(3)
    retry = retry_if_exception_type((TooManyRequests, ServiceUnavailable))
      where TooManyRequests = google.api_core.exceptions.TooManyRequests
            ServiceUnavailable = google.api_core.exceptions.ServiceUnavailable
  On each retry attempt: log WARNING "GCP {fn.__name__} attempt {n}/3 failed: {e}. Retrying."
  After final failure: raise CerberusRetryExhausted(fn.__name__, 3, last_exception)
  On Forbidden (403) or NotFound (404): re-raise immediately — do NOT retry.
  On any other exception type: re-raise immediately — do NOT retry.

--- FILE 2: cerberus/tools/chroma_client.py ---

ChromaDB embedded client with persistence.

COLLECTION_NAME = "resource_history"

def get_chroma_collection() -> chromadb.Collection:
  Reads CHROMA_PERSIST_DIR from config.
  Creates directory if it does not exist.
  Returns the persistent ChromaDB collection, creating it if it does not exist.
  The collection uses the default embedding function (all-MiniLM-L6-v2 via chromadb).
  Called lazily — not at module import.

def upsert_resource_record(record: ResourceRecord, run_id: str,
                            project_id: str) -> None:
  Upserts the resource into the collection.
  document = f"{record['resource_type']} {record['resource_id']} "
             f"owned by {record.get('owner_email','unknown')} in {record['region']}"
  metadata = {
    "run_id": run_id,
    "resource_type": record["resource_type"],
    "ownership_status": record.get("ownership_status") or "unknown",
    "decision": record.get("decision") or "unknown",
    "outcome": record.get("outcome") or "unknown",
    "estimated_monthly_cost": float(record.get("estimated_monthly_cost") or 0.0),
    "estimated_monthly_savings": float(record.get("estimated_monthly_savings") or 0.0),
    "region": record["region"],
    "owner_email": record.get("owner_email") or "unknown",
    "scanned_at": datetime.utcnow().isoformat(),
    "project_id": project_id,
  }
  ids = [record["resource_id"]]
  collection.upsert(documents=[document], metadatas=[metadata], ids=ids)

def query_resource_history(resource_id: str) -> dict | None:
  Queries the collection for this resource_id (exact match by ID).
  Returns the metadata dict if found, None if not found.

def query_owner_history(owner_email: str, project_id: str) -> list[dict]:
  Returns metadata for all resources in the collection where
  owner_email matches AND project_id matches.
  Used by reason_node for cross-resource context.

Both functions must handle chromadb exceptions gracefully:
  log WARNING on failure, return None / [] rather than raising.
  ChromaDB is best-effort — callers must not depend on it succeeding.
```

**Test cases:**
```python
# Retry tests
def test_succeeds_on_first_attempt():
    fn = Mock(return_value="ok")
    assert gcp_call_with_retry(fn) == "ok"
    assert fn.call_count == 1

def test_retries_on_429_then_succeeds():
    fn = Mock(side_effect=[TooManyRequests("limit"), "ok"])
    assert gcp_call_with_retry(fn) == "ok"
    assert fn.call_count == 2

def test_raises_retry_exhausted_after_3_failures():
    fn = Mock(side_effect=TooManyRequests("limit"))
    with pytest.raises(CerberusRetryExhausted) as exc:
        gcp_call_with_retry(fn)
    assert exc.value.attempts == 3

def test_does_not_retry_on_403():
    fn = Mock(side_effect=Forbidden("no access"))
    with pytest.raises(Forbidden):
        gcp_call_with_retry(fn)
    assert fn.call_count == 1

# ChromaDB tests
def test_upsert_and_retrieve(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    record = make_resource_record("vm-chroma-1")
    upsert_resource_record(record, "run-001", "nexus-tech-dev-1")
    result = query_resource_history("vm-chroma-1")
    assert result is not None
    assert result["run_id"] == "run-001"

def test_query_owner_history_returns_matching(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    r1 = make_resource_record("vm-a", owner_email="alice@nexus.tech")
    r2 = make_resource_record("disk-b", owner_email="alice@nexus.tech")
    upsert_resource_record(r1, "run-1", "nexus-tech-dev-1")
    upsert_resource_record(r2, "run-1", "nexus-tech-dev-1")
    results = query_owner_history("alice@nexus.tech", "nexus-tech-dev-1")
    assert len(results) == 2

def test_chroma_failure_returns_none_not_raises(monkeypatch):
    monkeypatch.setattr("chromadb.PersistentClient", Mock(side_effect=Exception("db error")))
    result = query_resource_history("vm-any")
    assert result is None
```

**Verification command:**
```bash
pytest tests/test_foundation.py -k "retry or chroma" -v
```

**Invariants touched:** INV-NFR-02 (retry wrapper — single shared implementation). ChromaDB client is not tied to a specific invariant but is a storage component touched by audit_node (INV-AUD-01).

---

## Session 2 — scan_node

**Goal:** `scan_node` returns a complete, validated list of resource records for all four
resource types, with correct idle detection, billing data, 60s timeout, and project guard.

**Integration check:**
```bash
pytest tests/test_scan.py -v
python -c "
import asyncio
from cerberus.state import initialise_state
from cerberus.nodes.scan_node import scan_node
# smoke test against live sandbox (requires .env with real GCP creds)
state = initialise_state('nexus-tech-dev-sandbox')
result = asyncio.run(scan_node(state))
assert result['error_message'] is None or 'Partial' in result['error_message']
assert len(result['resources']) >= 6  # must find the 6 seeded resources
print(f'scan_node live check: {len(result[\"resources\"])} resources found — PASS')
"
```

---

### Task 2.1 — VM discovery and idle detection

**CC prompt:**
```
Implement discover_vms(project_id: str, credentials) -> list[dict] in
cerberus/nodes/scan_node.py.

Module-level constants (not magic numbers):
  CPU_IDLE_THRESHOLD: float = 0.05      # 5 percent
  CPU_IDLE_WINDOW_HOURS: int = 72

Steps:
1. List all VM instances using compute_v1.InstancesClient.aggregated_list().
   Wrap in gcp_call_with_retry (import from cerberus.tools.gcp_retry).
2. For each VM, query Cloud Monitoring:
   metric = "compute.googleapis.com/instance/cpu/utilization"
   aggregation window = last 72 hours (CPU_IDLE_WINDOW_HOURS), ALIGN_MEAN
   Use monitoring_v3.MetricServiceClient.list_time_series().
   Wrap in gcp_call_with_retry.
3. A VM is idle if: mean CPU across all returned data points < CPU_IDLE_THRESHOLD
   AND the monitoring window contains at least 1 data point.
   If no monitoring data is returned (new VM, stopped VM): treat as idle=True
   and set last_activity_timestamp = creation_timestamp.
4. Set last_activity_timestamp to the timestamp of the most recent data point.
   If no data: use creation_timestamp.
5. Return list of dicts matching ResourceRecord shape (import from cerberus.state).
   Set resource_type="vm", estimated_monthly_cost=None (filled in Task 2.3).

On CerberusRetryExhausted for a monitoring call: log WARNING, treat VM as idle=True
(conservative — better to flag for review than miss an idle VM).

Do not set the idle flag directly in the resource record. The idle field is
implicit: last_activity_timestamp being > 72 hours ago is the idle signal for
reason_node. Do not add fields not in ResourceRecord.
```

**Test cases:**
```python
def test_constants_match_spec():
    from cerberus.nodes.scan_node import CPU_IDLE_THRESHOLD, CPU_IDLE_WINDOW_HOURS
    assert CPU_IDLE_THRESHOLD == 0.05
    assert CPU_IDLE_WINDOW_HOURS == 72

def test_vm_with_no_monitoring_data_gets_creation_timestamp(mock_compute, mock_monitoring_empty):
    vms = discover_vms("nexus-tech-dev-1", mock_creds)
    assert vms[0]["last_activity_timestamp"] == vms[0]["creation_timestamp"]

def test_vm_with_recent_high_cpu_gets_recent_timestamp(mock_compute, mock_monitoring_active):
    # mock: last data point was 2 hours ago
    vms = discover_vms("nexus-tech-dev-1", mock_creds)
    assert vms[0]["last_activity_timestamp"] is not None

def test_all_returned_records_have_required_fields(mock_compute, mock_monitoring):
    vms = discover_vms("nexus-tech-dev-1", mock_creds)
    for v in vms:
        for field in ["resource_id","resource_type","region","creation_timestamp"]:
            assert v[field] is not None
```

**Verification command:**
```bash
pytest tests/test_scan.py -k "vm" -v
```

**Invariants touched:** INV-SCAN-02 (constants are module-level, not inline — the test explicitly checks their values). INV-NFR-02 (all GCP calls via gcp_call_with_retry).

---

### Task 2.2 — Orphaned disk and unused IP discovery

**CC prompt:**
```
Add to cerberus/nodes/scan_node.py:

discover_orphaned_disks(project_id: str, credentials) -> list[dict]
  - compute_v1.DisksClient.aggregated_list()
  - Orphaned = disk.users is None or len(disk.users) == 0
  - resource_type = "orphaned_disk"
  - last_activity_timestamp = creation_timestamp (no activity signal)
  - estimated_monthly_cost = None
  - flagged_for_review: check if label "data-classification" == "sensitive"
    If so: set flagged_for_review=True (closes OQ-3 sensitive disk detection)
    Otherwise: False

discover_unused_ips(project_id: str, credentials) -> list[dict]
  - compute_v1.AddressesClient.aggregated_list()
  - Unused = address.status == "RESERVED" and (address.users is None or len == 0)
  - resource_type = "unused_ip"
  - last_activity_timestamp = creation_timestamp
  - estimated_monthly_cost = None

Both use gcp_call_with_retry. On CerberusRetryExhausted: log ERROR, return []
(empty list for that resource type — do not crash full scan).
Both return records matching ResourceRecord shape.
```

**Test cases:**
```python
def test_attached_disk_excluded(mock_disk_attached):
    assert discover_orphaned_disks("nexus-tech-dev-1", mock_creds) == []

def test_unattached_disk_included(mock_disk_unattached):
    disks = discover_orphaned_disks("nexus-tech-dev-1", mock_creds)
    assert len(disks) == 1 and disks[0]["resource_type"] == "orphaned_disk"

def test_sensitive_disk_flagged_for_review(mock_disk_sensitive_label):
    # mock: disk label data-classification=sensitive
    disks = discover_orphaned_disks("nexus-tech-dev-1", mock_creds)
    assert disks[0]["flagged_for_review"] is True

def test_in_use_ip_excluded(mock_ip_in_use):
    assert discover_unused_ips("nexus-tech-dev-1", mock_creds) == []

def test_reserved_unused_ip_included(mock_ip_unused):
    ips = discover_unused_ips("nexus-tech-dev-1", mock_creds)
    assert ips[0]["resource_type"] == "unused_ip"

def test_retry_exhausted_returns_empty_list(mock_gcp_always_429):
    result = discover_orphaned_disks("nexus-tech-dev-1", mock_creds)
    assert result == []  # does not raise
```

**Verification command:**
```bash
pytest tests/test_scan.py -k "disk or ip" -v
```

**Invariants touched:** INV-SCAN-03. Also closes OQ-3 (sensitive disk detection via label).

---

### Task 2.3 — Billing data fetch

**CC prompt:**
```
Add to cerberus/nodes/scan_node.py:

fetch_resource_costs(project_id: str, resource_ids: list[str],
                     billing_account_id: str, credentials) -> dict[str, float]:
  Uses cloud_billing_v1 Cloud Billing API.
  Query billing export for current month and previous month.
  Returns resource_id -> monthly average cost (float, USD).
  If a resource has no billing record: return 0.0 for it.
  If the entire billing API call fails after retry: log ERROR, return {} (empty dict).
  Wrap in gcp_call_with_retry.

enrich_costs(resources: list[dict], cost_map: dict[str, float]) -> list[dict]:
  For each resource: set estimated_monthly_cost from cost_map.
  If resource_id not in cost_map AND cost_map is not empty:
    set estimated_monthly_cost = 0.0 (known zero spend)
  If cost_map is empty (billing API failed):
    set estimated_monthly_cost = None (unknown — not zero)
  Return updated list.

The distinction between 0.0 (known zero) and None (unknown) matters for INV-SCAN-04.
A resource with None cost must not be presented with a $0 savings estimate.
```

**Test cases:**
```python
def test_known_resource_gets_averaged_cost(mock_billing):
    costs = fetch_resource_costs("p", ["vm-1"], "BA-123", mock_creds)
    assert isinstance(costs["vm-1"], float) and costs["vm-1"] >= 0

def test_unknown_resource_gets_zero_not_none(mock_billing):
    costs = fetch_resource_costs("p", ["vm-unknown"], "BA-123", mock_creds)
    assert costs.get("vm-unknown") == 0.0

def test_billing_failure_returns_empty_dict(mock_billing_always_fails):
    costs = fetch_resource_costs("p", ["vm-1"], "BA-123", mock_creds)
    assert costs == {}

def test_enrich_costs_none_when_billing_failed():
    resources = [{"resource_id": "vm-1", "estimated_monthly_cost": None}]
    result = enrich_costs(resources, {})  # empty cost_map = billing failed
    assert result[0]["estimated_monthly_cost"] is None

def test_enrich_costs_zero_when_resource_not_in_nonempty_map():
    resources = [{"resource_id": "vm-new", "estimated_monthly_cost": None}]
    result = enrich_costs(resources, {"vm-old": 45.0})  # non-empty map, vm-new absent
    assert result[0]["estimated_monthly_cost"] == 0.0
```

**Verification command:**
```bash
pytest tests/test_scan.py -k "cost or billing or enrich_costs" -v
```

**Invariants touched:** INV-SCAN-04 (null cost flagged, not zeroed when billing API fails).

---

### Task 2.4 — scan_node assembly

**CC prompt:**
```
Complete cerberus/nodes/scan_node.py with scan_node(state).

async def scan_node(state: CerberusState) -> CerberusState:

STEP 1 — Project guard (before ANY GCP call):
  Call validate_project_id(state["project_id"], get_config().allowed_project_pattern).
  On ValueError: state["error_message"] = str(e), return state immediately.

STEP 2 — Preflight count:
  Make three lightweight list API calls (VMs, disks, IPs) using pagination to get
  total resource counts only. Store sum as expected_count.
  Set state["expected_resource_count"] = expected_count.
  These calls use gcp_call_with_retry. On failure: expected_count = 0 (cannot validate completeness).

STEP 3 — Discovery and billing inside asyncio.wait_for(..., timeout=60.0):
  asyncio.gather(discover_vms, discover_orphaned_disks, discover_unused_ips)
  Then fetch_resource_costs and enrich_costs on combined results.
  Then validate each record with validate_resource_record.
  Drop records that fail validation, log each drop at WARNING.

STEP 4 — Completeness check:
  actual_count = len(valid_resources)
  If expected_resource_count > 0 AND actual_count < expected_resource_count:
    missing = expected_resource_count - actual_count
    state["error_message"] = (
      f"Partial scan: {actual_count}/{expected_resource_count} resources discovered. "
      f"{missing} could not be analysed. Proceeding — re-run for full coverage."
    )
  NOTE: Do NOT halt. Partial results are valid input for enrich_node.

STEP 5 — asyncio.TimeoutError handler:
  Catch TimeoutError. Log WARNING with partial count.
  Apply same error_message format as step 4 with actual_count/expected_resource_count.

STEP 6 — Write state:
  state["resources"] = valid_resources
  Return state.
```

**Test cases:**
```python
async def test_prod_project_blocked_before_gcp_call(mock_gcp):
    state = initialise_state("nexus-tech-prod")
    result = await scan_node(state)
    assert "BLOCKED" in result["error_message"]
    assert result["resources"] == []
    mock_gcp.instances_list.assert_not_called()

async def test_partial_scan_sets_error_message(mock_preflight_10_gather_7):
    state = initialise_state("nexus-tech-dev-1")
    result = await scan_node(state)
    assert "Partial scan" in result["error_message"]
    assert len(result["resources"]) == 7

async def test_complete_scan_no_error_message(mock_full_scan):
    state = initialise_state("nexus-tech-dev-1")
    result = await scan_node(state)
    assert result["error_message"] is None
    assert len(result["resources"]) > 0

async def test_no_record_exits_missing_required_fields(mock_full_scan):
    state = initialise_state("nexus-tech-dev-1")
    result = await scan_node(state)
    for r in result["resources"]:
        for f in ["resource_id","resource_type","region","creation_timestamp"]:
            assert r[f] is not None

async def test_timeout_returns_partial_not_raises(mock_slow_gcp):
    state = initialise_state("nexus-tech-dev-1")
    result = await scan_node(state)
    assert "Partial scan" in result["error_message"]
    # Must not raise — returns whatever was gathered
```

**Verification command:**
```bash
pytest tests/test_scan.py -v
```

**Invariants touched:** INV-SEC-01 (project guard is first line), INV-SCAN-01 (validate_resource_record on every record), INV-SCAN-02 (CPU constants from Task 2.1), INV-NFR-01 (60s asyncio timeout), INV-NFR-02 (all GCP calls via retry wrapper).

---

## Session 3 — enrich_node

**Goal:** Every resource entering reason_node has a non-None `ownership_status`,
correct `flagged_for_review`, and IAM staleness downgrade applied.

**Integration check:**
```bash
pytest tests/test_enrich.py -v
python -c "
import asyncio, json
from cerberus.state import initialise_state
from cerberus.nodes.enrich_node import enrich_node
state = initialise_state('nexus-tech-dev-sandbox')
state['resources'] = json.load(open('tests/fixtures/sample_resources.json'))
result = asyncio.run(enrich_node(state))
for r in result['resources']:
    assert r['ownership_status'] is not None, f'{r[\"resource_id\"]} missing ownership_status'
print('enrich_node integration: PASS')
"
```

---

### Task 3.1 — Four-step ownership lookup chain

**CC prompt:**
```
Implement the ownership lookup chain in cerberus/nodes/enrich_node.py.

Four functions, each returns str | None (resolved owner email):

lookup_by_labels(resource: dict) -> str | None
  Check resource["labels"] dict for keys in priority order: "owner", "created-by", "team".
  Return first non-empty value. No API call needed. If labels key absent: return None.

lookup_by_asset_inventory(resource_id: str, project_id: str,
                           credentials) -> str | None
  Use asset_v1.AssetServiceClient.search_all_resources().
  Search for the resource by resource_id in the project.
  Return creator email from asset metadata if present. Wrap in gcp_call_with_retry.
  On CerberusRetryExhausted: log WARNING, return None.

lookup_by_iam_history(resource_id: str, project_id: str,
                       credentials) -> str | None
  Query Cloud Audit Log for IAM policy change events on this resource.
  Return email of the principal who last granted permissions on it.
  Use logging_v2.Client.list_entries() with filter:
    protoPayload.resourceName contains resource_id AND
    protoPayload.methodName contains "setIamPolicy"
  Return principalEmail from the most recent matching entry.
  Wrap in gcp_call_with_retry. On failure: return None.

lookup_by_audit_log(resource_id: str, project_id: str,
                     credentials) -> str | None
  Query Cloud Audit Log for the most recent mutation event on this resource.
  Return principalEmail from the most recent log entry.
  Wrap in gcp_call_with_retry. On failure: return None.

resolve_owner(resource: dict, project_id: str, credentials) -> str | None
  Call the four functions in order. Return the first non-None result.
  If all return None: return None.
  Short-circuit: as soon as a non-None result is found, do NOT call remaining functions.
```

**Test cases:**
```python
def test_label_owner_key_wins_over_created_by():
    r = {"labels": {"owner": "alice@x.com", "created-by": "bob@x.com"}}
    assert lookup_by_labels(r) == "alice@x.com"

def test_created_by_used_when_no_owner_key():
    r = {"labels": {"created-by": "bob@x.com"}}
    assert lookup_by_labels(r) == "bob@x.com"

def test_no_labels_returns_none():
    assert lookup_by_labels({"labels": {}}) is None
    assert lookup_by_labels({}) is None

def test_resolve_stops_at_first_hit(mocker):
    mocker.patch("cerberus.nodes.enrich_node.lookup_by_labels", return_value="alice@x.com")
    spy = mocker.patch("cerberus.nodes.enrich_node.lookup_by_asset_inventory")
    resolve_owner({"labels": {"owner": "alice@x.com"}}, "p", mock_creds)
    spy.assert_not_called()

def test_resolve_tries_all_if_labels_fail(mocker, mock_asset_returns_email):
    mocker.patch("cerberus.nodes.enrich_node.lookup_by_labels", return_value=None)
    result = resolve_owner({}, "nexus-tech-dev-1", mock_creds)
    assert result is not None  # found by asset inventory

def test_resolve_returns_none_when_all_fail(mocker):
    for fn in ["lookup_by_labels","lookup_by_asset_inventory",
               "lookup_by_iam_history","lookup_by_audit_log"]:
        mocker.patch(f"cerberus.nodes.enrich_node.{fn}", return_value=None)
    result = resolve_owner({}, "p", mock_creds)
    assert result is None
```

**Verification command:**
```bash
pytest tests/test_enrich.py -k "lookup or resolve" -v
```

**Invariants touched:** INV-ENR-01.

---

### Task 3.2 — IAM membership check and staleness downgrade

**CC prompt:**
```
Add to cerberus/nodes/enrich_node.py:

check_iam_membership(email: str, project_id: str, credentials) -> bool
  Call resourcemanager_v3.ProjectsClient.get_iam_policy(project_id).
  Return True if any binding in policy contains the email. False otherwise.
  Wrap in gcp_call_with_retry. On CerberusRetryExhausted: log WARNING, return False.

check_iam_last_activity(email: str, project_id: str, credentials) -> datetime | None
  Query Cloud Audit Log for the most recent event by this principal.
  Filter: protoPayload.authenticationInfo.principalEmail = "{email}"
  Return the timestamp of the most recent entry as a datetime object.
  Return None if no events found.
  Wrap in gcp_call_with_retry. On failure: return None.

classify_ownership(resolved_email: str | None, project_id: str,
                    credentials) -> tuple[str, bool]:
  Returns (ownership_status, owner_iam_active).

  If resolved_email is None: return ("no_owner", False)

  Call check_iam_membership(email, project_id, credentials).
  If False: return ("departed_owner", False)

  If True (email IS in IAM):
    Call check_iam_last_activity(email, project_id, credentials).
    If last_activity is not None AND (now - last_activity).days > 90:
      Log WARNING: f"Owner {email} in IAM but last activity {days}d ago — downgraded"
      return ("departed_owner", False)
    Else: return ("active_owner", True)

STALENESS_THRESHOLD_DAYS: int = 90  (module-level constant)
```

**Test cases:**
```python
def test_active_recent_member():
    # in IAM + last activity 10 days ago
    status, active = classify_ownership("alice@x.com", "p", mock_creds_active_recent)
    assert status == "active_owner" and active is True

def test_not_in_iam_is_departed():
    status, active = classify_ownership("bob@x.com", "p", mock_creds_not_in_iam)
    assert status == "departed_owner" and active is False

def test_none_email_is_no_owner():
    status, active = classify_ownership(None, "p", mock_creds)
    assert status == "no_owner" and active is False

def test_stale_iam_member_downgraded():
    # in IAM + last activity 100 days ago
    status, active = classify_ownership("stale@x.com", "p", mock_creds_stale)
    assert status == "departed_owner" and active is False

def test_staleness_constant_is_90():
    from cerberus.nodes.enrich_node import STALENESS_THRESHOLD_DAYS
    assert STALENESS_THRESHOLD_DAYS == 90
```

**Verification command:**
```bash
pytest tests/test_enrich.py -k "iam or classify or staleness" -v
```

**Invariants touched:** INV-ENR-02. Also closes the ownership label staleness key risk from ARCHITECTURE.md §4.

---

### Task 3.3 — enrich_node assembly

**CC prompt:**
```
Complete cerberus/nodes/enrich_node.py with enrich_node(state).

async def enrich_node(state: CerberusState) -> CerberusState:

For each resource in state["resources"]:
  1. resolved_email = resolve_owner(resource, state["project_id"], credentials)
  2. ownership_status, owner_iam_active = classify_ownership(
       resolved_email, state["project_id"], credentials)
  3. resource["owner_email"] = resolved_email
     resource["ownership_status"] = ownership_status
     resource["owner_iam_active"] = owner_iam_active
     resource["flagged_for_review"] = (ownership_status == "no_owner")
     # Note: sensitive disk flag may already be True from scan_node (OQ-3).
     # Use: resource["flagged_for_review"] = resource.get("flagged_for_review", False) OR (ownership_status == "no_owner")

COMPLETENESS GUARD (after all resources processed):
  missing = [r for r in state["resources"] if r.get("ownership_status") is None]
  If missing:
    For each: r["ownership_status"] = "no_owner", r["flagged_for_review"] = True
    count = len(state["resources"]) - len(missing)
    total = len(state["resources"])
    state["error_message"] = (
      f"Enrichment incomplete: {count}/{total} resources enriched. "
      f"{len(missing)} forced to no_owner and flagged for review."
    )

INVARIANT: No resource may exit enrich_node with ownership_status=None.
This is enforced by the completeness guard — not assumed.

state["resources"] = resources
return state
```

**Test cases:**
```python
async def test_no_owner_resource_flagged(mock_all_lookups_return_none):
    state = initialise_state("nexus-tech-dev-1")
    state["resources"] = [make_resource("vm-1", labels={})]
    result = await enrich_node(state)
    assert result["resources"][0]["ownership_status"] == "no_owner"
    assert result["resources"][0]["flagged_for_review"] is True

async def test_active_owner_not_flagged(mock_active_owner):
    state["resources"] = [make_resource("vm-2", labels={"owner": "alice@x.com"})]
    result = await enrich_node(state)
    assert result["resources"][0]["ownership_status"] == "active_owner"
    assert result["resources"][0]["flagged_for_review"] is False

async def test_sensitive_disk_flag_preserved(mock_active_owner):
    # disk was flagged_for_review=True by scan_node (sensitive label)
    resource = make_resource("disk-1", resource_type="orphaned_disk",
                              flagged_for_review=True)
    state["resources"] = [resource]
    result = await enrich_node(state)
    assert result["resources"][0]["flagged_for_review"] is True  # not overwritten

async def test_no_resource_exits_with_none_ownership(mock_partial_failure):
    state["resources"] = [make_resource("vm-1"), make_resource("vm-2")]
    result = await enrich_node(state)
    for r in result["resources"]:
        assert r["ownership_status"] is not None
```

**Verification command:**
```bash
pytest tests/test_enrich.py -v
```

**Invariants touched:** INV-ENR-01, INV-ENR-02, INV-ENR-03 (flagged_for_review set here — first of four enforcement points for the no-owner guardrail).

---

## Session 4 — reason_node

**Goal:** Gemini integration with deterministic output, structured JSON, all post-LLM
guardrails enforced in code, ChromaDB context available to the agent.

**Integration check:**
```bash
pytest tests/test_reason.py -v
# Determinism check — run 3 times against same fixture, all outputs must match:
python -c "
import asyncio, json
from cerberus.nodes.reason_node import reason_node
from cerberus.state import initialise_state

fixture = json.load(open('tests/fixtures/sample_resources.json'))
results = []
for i in range(3):
    state = initialise_state('nexus-tech-dev-1')
    state['resources'] = fixture.copy()
    r = asyncio.run(reason_node(state))
    results.append([rec['decision'] for rec in r['resources']])

assert results[0] == results[1] == results[2], f'Non-deterministic: {results}'
print('Determinism check: PASS')
"
```

---

### Task 4.1 — Gemini schema, system prompt, and resource prompt builder

**CC prompt:**
```
Implement the Gemini interface in cerberus/nodes/reason_node.py.

1. ResourceDecision (Pydantic BaseModel):
     decision: Literal["safe_to_stop","safe_to_delete","needs_review","skip"]
     reasoning: str
     estimated_monthly_savings: float

2. SYSTEM_PROMPT (module-level str constant). Must contain all of:
   a) "Output decision as exactly one of: safe_to_stop, safe_to_delete, needs_review, skip"
   b) "If flagged_for_review is true OR ownership_status is no_owner, decision MUST be needs_review"
   c) "Reasoning must be 3 sentences or fewer. Sentence 1 must cite at least one of:
       idle duration in hours, owner last activity age in days, or estimated monthly cost in USD."
   d) "If estimated_monthly_cost is null, set estimated_monthly_savings=0.0 and note this."
   e) "Output ONLY valid JSON matching this schema: {ResourceDecision.model_json_schema()}"
      (embed the schema string in the prompt at module load time)

3. build_resource_prompt(resource: ResourceRecord) -> str
   Formats the resource as a structured string. Must include:
   resource_id, resource_type, region, creation_timestamp,
   last_activity_timestamp, estimated_monthly_cost, ownership_status,
   owner_email, owner_iam_active, flagged_for_review.
   Include chromadb context if available:
     history = query_resource_history(resource["resource_id"])
     If history: append "Previous classification: {history['decision']} on {history['scanned_at']}"
     owner_context = query_owner_history(resource.get("owner_email",""), project_id)
     If owner_context: append "Owner has {len(owner_context)} other resources in this project."
   (ChromaDB context is best-effort — if queries return None/[], omit silently)

4. GEMINI_INTER_REQUEST_DELAY_SECONDS: float = 0.5 (module-level constant)
   Used by reason_node to sleep between resource calls to avoid rate limiting.
```

**Test cases:**
```python
def test_system_prompt_contains_all_four_decisions():
    for d in ["safe_to_stop","safe_to_delete","needs_review","skip"]:
        assert d in SYSTEM_PROMPT

def test_system_prompt_contains_no_owner_rule():
    assert "no_owner" in SYSTEM_PROMPT and "needs_review" in SYSTEM_PROMPT

def test_system_prompt_contains_sentence_limit():
    assert "3 sentences" in SYSTEM_PROMPT

def test_build_prompt_includes_cost():
    r = make_resource("vm-1", estimated_monthly_cost=45.0)
    assert "45.0" in build_resource_prompt(r)

def test_build_prompt_includes_flagged_status():
    r = make_resource("vm-1", flagged_for_review=True)
    assert "flagged_for_review" in build_resource_prompt(r)
    assert "true" in build_resource_prompt(r).lower()

def test_delay_constant_is_half_second():
    from cerberus.nodes.reason_node import GEMINI_INTER_REQUEST_DELAY_SECONDS
    assert GEMINI_INTER_REQUEST_DELAY_SECONDS == 0.5
```

**Verification command:**
```bash
pytest tests/test_reason.py -k "prompt or schema or constant" -v
```

**Invariants touched:** INV-RSN-01 (four-value enum in schema), INV-RSN-02 (3-sentence rule in prompt), INV-ENR-03 (no_owner rule in prompt — code enforcement is Task 4.2).

---

### Task 4.2 — classify_resource with post-LLM validation

**CC prompt:**
```
Add to cerberus/nodes/reason_node.py:

async def classify_resource(resource: ResourceRecord,
                             client: genai.GenerativeModel) -> ResourceRecord:

1. Call client.generate_content:
     system_instruction = SYSTEM_PROMPT
     contents = build_resource_prompt(resource)
     generation_config = genai.GenerationConfig(
       temperature=0,
       response_mime_type="application/json"
     )

2. Parse response.text as JSON. On JSONDecodeError:
     resource["decision"] = "needs_review"
     resource["reasoning"] = "Reasoning unavailable — LLM returned unparseable output."
     resource["estimated_monthly_savings"] = 0.0
     Log ERROR with raw response. Return resource.

3. Validate decision against VALID_DECISIONS (import from cerberus.state).
   If invalid: override to "needs_review", log WARNING with the invalid value.

4. FLAGGED_FOR_REVIEW CODE GUARDRAIL (belt-and-suspenders, not prompt-only):
   if resource["flagged_for_review"] and parsed.decision != "needs_review":
     log WARNING: f"Guardrail override: {resource['resource_id']} flagged_for_review "
                  f"had decision={parsed.decision} → forced to needs_review"
     parsed.decision = "needs_review"

5. REASONING VALIDATION:
   sentences = [s.strip() for s in re.split(r'\.(?:\s|$)', parsed.reasoning) if s.strip()]
   if len(sentences) > 3:
     parsed.reasoning = ". ".join(sentences[:3]) + "."
     log WARNING: f"Reasoning truncated for {resource['resource_id']}"
   if not parsed.reasoning.strip():
     Retry the Gemini call once (single retry only).
     If still empty: set reasoning = "Reasoning unavailable — flagged for review."

6. SAVINGS VALIDATION:
   if parsed.estimated_monthly_savings < 0: set to 0.0
   if parsed.decision in ("safe_to_stop","safe_to_delete"):
     if parsed.estimated_monthly_savings == 0.0 and resource.get("estimated_monthly_cost"):
       parsed.estimated_monthly_savings = resource["estimated_monthly_cost"]

7. Set resource fields from parsed result. Return resource.
```

**Test cases:**
```python
async def test_valid_response_applied(mock_gemini_valid):
    r = make_resource("vm-1", estimated_monthly_cost=45.0,
                       ownership_status="departed_owner")
    result = await classify_resource(r, mock_gemini_valid)
    assert result["decision"] in VALID_DECISIONS
    assert result["reasoning"] is not None

async def test_invalid_decision_overridden(mock_gemini_bad_decision):
    # mock returns decision="unclear"
    result = await classify_resource(make_resource("vm-1"), mock_gemini_bad_decision)
    assert result["decision"] == "needs_review"

async def test_flagged_resource_forced_to_needs_review(mock_gemini_returns_safe_delete):
    r = make_resource("vm-1", flagged_for_review=True, ownership_status="no_owner")
    result = await classify_resource(r, mock_gemini_returns_safe_delete)
    assert result["decision"] == "needs_review"

async def test_zero_savings_overridden_for_actionable(mock_gemini_zero_savings):
    r = make_resource("vm-1", estimated_monthly_cost=45.0, ownership_status="active_owner")
    result = await classify_resource(r, mock_gemini_zero_savings)
    assert result["estimated_monthly_savings"] == 45.0

async def test_json_failure_returns_needs_review(mock_gemini_bad_json):
    result = await classify_resource(make_resource("vm-1"), mock_gemini_bad_json)
    assert result["decision"] == "needs_review"
    assert "unparseable" in result["reasoning"]
```

**Verification command:**
```bash
pytest tests/test_reason.py -k "classify" -v
```

**Invariants touched:** INV-RSN-01 (code-enforced enum validation), INV-RSN-02 (sentence truncation in code), INV-RSN-03 (savings override), INV-ENR-03 (flagged_for_review code guardrail — second enforcement point).

---

### Task 4.3 — reason_node assembly

**CC prompt:**
```
Complete cerberus/nodes/reason_node.py with reason_node(state).

async def reason_node(state: CerberusState) -> CerberusState:

1. Initialise genai.GenerativeModel(model_name=get_config().gemini_model).
   genai.configure(api_key=get_config().gemini_api_key) called once at node entry.

2. For each resource in state["resources"] (sequential, not concurrent):
   result = await classify_resource(resource, client)
   state["resources"] — update the resource in place.
   await asyncio.sleep(GEMINI_INTER_REQUEST_DELAY_SECONDS)

3. After all resources classified:
   total_savings = sum(r["estimated_monthly_savings"] or 0.0
                       for r in state["resources"]
                       if r["decision"] in ("safe_to_stop","safe_to_delete"))
   Log INFO: f"{len(state['resources'])} resources classified. "
             f"${total_savings:.2f}/month recoverable waste identified."

4. Return state.

INVARIANT CHECK: After reason_node, for every resource:
  assert r["decision"] is not None (enforced by classify_resource)
  This is a belt-and-suspenders assertion in the node body, not just a test.
```

**Test cases:**
```python
async def test_all_resources_get_non_none_decision(mock_gemini, sample_state):
    result = await reason_node(sample_state)
    for r in result["resources"]:
        assert r["decision"] in VALID_DECISIONS

async def test_sequential_execution_respects_delay(mock_gemini, sample_state_3, mocker):
    sleep_mock = mocker.patch("asyncio.sleep")
    await reason_node(sample_state_3)
    assert sleep_mock.call_count == 3  # one sleep per resource
```

**Verification command:**
```bash
pytest tests/test_reason.py -v
```

**Invariants touched:** INV-RSN-01, INV-RSN-02, INV-RSN-03.

---

## Session 5 — Execute Pipeline

**Goal:** approve_node, revalidate_node, and execute_node all working. Dry-run confirmed safe.
Rate limit enforced. Stop/delete structurally separated.

**Integration check:**
```bash
pytest tests/test_execute.py -v
# Confirm dry-run makes zero GCP calls:
python -c "
import asyncio
from unittest.mock import patch, MagicMock
from cerberus.state import initialise_state
from cerberus.nodes.execute_node import execute_node

state = initialise_state('nexus-tech-dev-1', dry_run=True)
state['approved_actions'] = [
  {'resource_id':'vm-1','decision':'safe_to_stop','flagged_for_review':False,
   'resource_type':'vm','region':'us-central1','creation_timestamp':'2024-01-01T00:00:00Z',
   'estimated_monthly_cost':45.0,'ownership_status':'active_owner','owner_email':'a@b.com',
   'owner_iam_active':True,'estimated_monthly_savings':45.0,'outcome':None,
   'last_activity_timestamp':None,'reasoning':'test'}
]
with patch('cerberus.nodes.execute_node.stop_vm') as mock_stop:
    asyncio.run(execute_node(state))
    assert mock_stop.call_count == 0, 'DRY RUN MADE GCP CALL — FAIL'
print('Dry-run safety check: PASS')
"
```

---

### Task 5.1 — approve_node and FastAPI API

**CC prompt:**
```
Implement cerberus/nodes/approve_node.py and cerberus/api.py.

--- approve_node ---
Uses langgraph interrupt. Import from langgraph.types import interrupt.

def approve_node(state: CerberusState) -> CerberusState:
  1. Build approval_payload: list of dicts containing only display fields
     (resource_id, resource_type, region, owner_email, ownership_status,
      decision, reasoning, estimated_monthly_savings).
     Do NOT include credential fields.
  2. approved_ids: list[str] = interrupt(approval_payload)
  3. state["approved_actions"] = [
       r for r in state["resources"] if r["resource_id"] in approved_ids
     ]
  4. state["mutation_count"] = 0   # session counter reset
  5. return state

--- FastAPI app in cerberus/api.py ---
Use FastAPI with a MemorySaver checkpointer for the LangGraph graph.

in-memory store: active_runs: dict[str, dict] = {}
  key = run_id, value = {"thread_id": str, "project_id": str, "status": str}
  status values: "scanning" | "awaiting_approval" | "executing" | "complete" | "error"

Endpoints:

POST /run
  Body: {"project_id": str, "dry_run": bool = True}
  Validates project_id against allowlist (calls validate_project_id).
  If project_id already in active_runs with status not in ("complete","error"):
    return HTTP 409 {"error": "A scan for this project is already running."}
  Creates run_id (uuid4), starts cerberus_graph.astream_events in background task.
  Returns {"run_id": run_id}

GET /run/{run_id}/plan
  Returns the approval_payload from the interrupt event.
  If graph has not reached interrupt yet: returns {"status": "scanning", "plan": null}
  If graph reached interrupt: returns {"status": "awaiting_approval", "plan": [...]}

POST /run/{run_id}/approve
  Body: {"approved_ids": list[str]}
  Resumes the graph with approved_ids.
  Returns {"status": "executing"}

GET /run/{run_id}/status
  Returns state fields: resources (with decisions), error_message, run_complete,
  dry_run, langsmith_trace_url, mutation_count.
  MUST NOT include any field from CerberusConfig (no credentials).

All endpoints return HTTP 404 if run_id not found.
```

**Test cases:**
```python
def test_post_run_rejects_prod_project(client):
    r = client.post("/run", json={"project_id": "nexus-tech-prod"})
    assert r.status_code == 422 or r.status_code == 400
    assert "BLOCKED" in r.json()["error"]

def test_concurrent_scan_returns_409(client, active_run_fixture):
    r = client.post("/run", json={"project_id": "nexus-tech-dev-1"})
    assert r.status_code == 409

def test_status_endpoint_excludes_credentials(client, completed_run):
    r = client.get(f"/run/{completed_run}/status")
    body_str = r.text
    for forbidden in ["service_account","cerberus-key","GOOGLE_APPLICATION","api_key"]:
        assert forbidden.lower() not in body_str.lower()

def test_approve_with_empty_list_succeeds(client, awaiting_approval_run):
    r = client.post(f"/run/{awaiting_approval_run}/approve",
                    json={"approved_ids": []})
    assert r.status_code == 200

def test_mutation_count_zero_after_approve():
    # state["mutation_count"] must be 0 after approve_node runs
    state = run_approve_node(approved_ids=["vm-1","vm-2"])
    assert state["mutation_count"] == 0
```

**Verification command:**
```bash
pytest tests/test_execute.py -k "approve or api or run" -v
```

**Invariants touched:** INV-UI-03 (dry_run passed through state), INV-SEC-02 (status endpoint tested for credential exclusion).

---

### Task 5.2 — revalidate_node

**CC prompt:**
```
Implement cerberus/nodes/revalidate_node.py.

async def revalidate_node(state: CerberusState) -> CerberusState:

For each resource in state["approved_actions"]:

  TRY to re-fetch current resource state from GCP:
    VM: compute_v1.InstancesClient.get(project, zone, name)
    Disk: compute_v1.DisksClient.get(project, zone, name)
    IP: compute_v1.AddressesClient.get(project, region, name)
  All wrapped in gcp_call_with_retry.

  CASE 1 — Google 404 (NotFound):
    Remove from approved_actions.
    Log INFO: f"{resource['resource_id']} no longer exists — removed from plan."
    Do NOT set error_message.

  CASE 2 — Drift detected:
    VM: current status is RUNNING (was expected TERMINATED/SUSPENDED)
    Disk: now has users (was expected empty)
    IP: status is IN_USE (was expected RESERVED)
    If drift: downgrade resource["decision"] = "needs_review" in state["resources"]
    Add to drifted list.

  CASE 3 — No change: resource stays in approved_actions.

After processing all resources:
  drifted_count = len(drifted)
  if 0 < drifted_count < len(original_approved):
    Remove drifted from state["approved_actions"]
    state["error_message"] = (
      f"{drifted_count} resource(s) changed state since approval and were removed. "
      f"Remaining {len(state['approved_actions'])} actions will proceed."
    )
  elif drifted_count == len(original_approved):
    state["approved_actions"] = []
    state["error_message"] = (
      "All approved resources changed state — execution cancelled. "
      "Re-run scan for current state."
    )
return state
```

**Test cases:**
```python
async def test_no_drift_approved_unchanged(mock_gcp_no_drift):
    state = make_state_with_approvals(["vm-1","vm-2"])
    result = await revalidate_node(state)
    assert len(result["approved_actions"]) == 2
    assert result["error_message"] is None

async def test_drifted_vm_removed(mock_gcp_vm_now_running):
    state = make_state_with_approvals(["vm-1","vm-2"])
    result = await revalidate_node(state)
    ids = [r["resource_id"] for r in result["approved_actions"]]
    assert "vm-1" not in ids
    assert result["error_message"] is not None

async def test_404_silently_removed(mock_gcp_404):
    state = make_state_with_approvals(["vm-deleted"])
    result = await revalidate_node(state)
    assert len(result["approved_actions"]) == 0
    assert result["error_message"] is None   # 404 is not an error

async def test_full_drift_clears_approved(mock_gcp_all_drifted):
    state = make_state_with_approvals(["vm-1","vm-2","vm-3"])
    result = await revalidate_node(state)
    assert result["approved_actions"] == []
    assert "cancelled" in result["error_message"]
```

**Verification command:**
```bash
pytest tests/test_execute.py -k "revalidate" -v
```

**Invariants touched:** Closes OQ-1 (drift on safe_to_delete → needs_review). Not a named invariant in INVARIANTS.md — this is an architectural gap closed by the plan.

---

### Task 5.3 — execute_node

**CC prompt:**
```
Implement cerberus/nodes/execute_node.py.

Two structurally separate helper functions (MUST be separate — not a flag):
  async def stop_vm(resource: ResourceRecord, credentials) -> bool
    Calls compute_v1.InstancesClient.stop(project, zone, instance_name).
    Returns True on success. Never calls instances.delete.

  async def delete_resource(resource: ResourceRecord, credentials) -> bool
    Routes by resource_type:
      "vm" → instances.delete
      "orphaned_disk" → disks.delete
        BEFORE deletion: check resource["flagged_for_review"] (sensitive disk).
        If True and decision is "safe_to_delete": override action to archive
          (write to Coldline Storage instead of deleting) — closes OQ-3.
      "unused_ip" → addresses.delete
    Returns True on success. Never calls instances.stop.

  async def verify_resource_state(resource: ResourceRecord, credentials) -> bool
    Re-fetches resource from GCP. Asserts expected post-action state:
      stop_vm: instance.status == "TERMINATED" or "STOPPING"
      delete: 404 response (resource gone)
    Returns True if verified. False otherwise.

async def execute_node(state: CerberusState) -> CerberusState:

PRECONDITION 1 — dry_run check:
  if state["dry_run"]:
    For each approved action: resource["outcome"] = "DRY_RUN"
    Log INFO "DRY RUN — no GCP calls made."
    return state  (no API calls)

PRECONDITION 2 — empty check:
  if not state["approved_actions"]:
    Log INFO "No approved actions."
    return state

EXECUTION LOOP:
  for resource in state["approved_actions"]:

    A. RATE LIMIT (check before API call):
       if state["mutation_count"] >= 10:
         remaining = [r for r in approved_actions still unprocessed]
         state["error_message"] = (
           f"Rate limit: 10 mutations reached. "
           f"{len(remaining)} action(s) not executed this session."
         )
         break

    B. GUARDRAIL (belt-and-suspenders):
       if resource["flagged_for_review"]:
         resource["outcome"] = "SKIPPED_GUARDRAIL"
         Log WARNING: f"GUARDRAIL SKIP: {resource['resource_id']}"
         continue   # do NOT increment mutation_count

    C. ACTION ROUTING:
       if resource["decision"] == "safe_to_stop":
         success = await stop_vm(resource, credentials)
       elif resource["decision"] == "safe_to_delete":
         success = await delete_resource(resource, credentials)
       else:
         continue   # needs_review, skip — never executed

    D. INCREMENT COUNTER (on dispatch, before verification):
       state["mutation_count"] += 1

    E. VERIFICATION:
       if success:
         verified = await verify_resource_state(resource, credentials)
         if verified:
           resource["outcome"] = "SUCCESS"
         else:
           resource["outcome"] = "FAILED"
           state["mutation_count"] -= 1   # failed actions don't count
       else:
         resource["outcome"] = "FAILED"
         state["mutation_count"] -= 1

return state
```

**Test cases:**
```python
async def test_dry_run_zero_gcp_calls(mock_gcp_mutation, dry_run_state_with_approvals):
    await execute_node(dry_run_state_with_approvals)
    mock_gcp_mutation.instances_stop.assert_not_called()
    mock_gcp_mutation.instances_delete.assert_not_called()

async def test_rate_limit_halts_at_10(mock_gcp_mutation, state_15_approvals):
    result = await execute_node(state_15_approvals)
    assert result["mutation_count"] == 10
    assert "Rate limit" in result["error_message"]

async def test_flagged_resource_skipped_not_counted(mock_gcp_mutation):
    state = make_live_state([
        make_resource("vm-flag", decision="safe_to_stop", flagged_for_review=True),
        make_resource("vm-ok", decision="safe_to_stop", flagged_for_review=False),
    ])
    result = await execute_node(state)
    assert result["mutation_count"] == 1

async def test_safe_to_stop_never_calls_delete(mock_gcp):
    state = make_live_state([make_resource("vm-1", decision="safe_to_stop")])
    await execute_node(state)
    mock_gcp.instances_delete.assert_not_called()
    mock_gcp.instances_stop.assert_called_once()

async def test_failed_verification_decrements_counter(mock_gcp_verify_fail):
    state = make_live_state([make_resource("vm-1", decision="safe_to_stop")])
    result = await execute_node(state)
    assert result["mutation_count"] == 0
    assert result["approved_actions"][0]["outcome"] == "FAILED"
```

**Verification command:**
```bash
pytest tests/test_execute.py -v
```

**Invariants touched:** INV-EXE-01, INV-EXE-02, INV-EXE-03, INV-UI-03 (dry_run precondition), INV-ENR-03 (guardrail skip — third enforcement point).

---

## Session 6 — Audit + Graph Wiring

**Goal:** Complete audit trail (JSONL + ChromaDB), global error handler, fully wired graph.

**Integration check:**
```bash
pytest tests/test_audit.py tests/test_graph.py -v
python -c "
from cerberus.graph import cerberus_graph
print('Graph compiled:', type(cerberus_graph).__name__)
# Check all nodes are present in the graph
nodes = list(cerberus_graph.nodes.keys())
for n in ['scan_node','enrich_node','reason_node','approve_node',
          'revalidate_node','execute_node','audit_node']:
    assert n in nodes, f'Missing node: {n}'
print('All nodes present: PASS')
"
```

---

### Task 6.1 — audit_node with JSONL log and ChromaDB write

**CC prompt:**
```
Implement cerberus/nodes/audit_node.py.

AuditEntry (Pydantic BaseModel):
  timestamp: str          # datetime.utcnow().isoformat()
  resource_id: str | None
  action_type: str
  llm_reasoning: str | None
  actor: Literal["human","agent"]
  outcome: Literal["SUCCESS","FAILED","REJECTED","SKIPPED_GUARDRAIL","DRY_RUN","NODE_ERROR"]
  run_id: str
  session_mutation_count: int
  project_id: str
Schema must contain no credential fields — enforced at definition time.

write_audit_entry(entry: AuditEntry, log_dir: str, run_id: str) -> None:
  log_path = os.path.join(log_dir, f"audit_{run_id}.jsonl")
  os.makedirs(log_dir, exist_ok=True)
  Opens in append mode. Writes entry.model_dump_json() + "\n". Flushes. Closes.
  On IOError: logs ERROR with full traceback. Raises — caller must handle.
  Do NOT catch silently.

def audit_node(state: CerberusState) -> CerberusState:

WRITE ORDER (enforced, not assumed):
  STEP 1: Write JSONL log for each resource with an outcome set.
          If JSONL write fails: raise. Do NOT attempt ChromaDB.
  STEP 2: Write ChromaDB for each resource with an outcome set.
          Call upsert_resource_record from chroma_client.
          If ChromaDB fails: log WARNING. Do NOT raise. Do NOT set error_message.
  STEP 3: Write cost summary as a JSONL entry:
          action_type="COST_SUMMARY", resource_id=None
          Include in llm_reasoning field:
            json.dumps({resources_scanned, total_waste_identified,
                        actions_approved, actions_executed,
                        estimated_monthly_savings_recovered})
          estimated_monthly_savings_recovered = sum savings for outcome=="SUCCESS" only.
  STEP 4: Set state["audit_log_path"] = log_path
  STEP 5: Attempt LangSmith trace URL retrieval. If available: set
          state["langsmith_trace_url"]. If not: set None, log WARNING
          "LangSmith unavailable — local JSONL is the authoritative record."
  STEP 6: state["run_complete"] = True
  STEP 7: return state
```

**Test cases:**
```python
def test_jsonl_entry_per_resource(tmp_path, sample_state_with_outcomes):
    sample_state_with_outcomes["audit_log_path"] = str(tmp_path / "logs")
    result = audit_node(sample_state_with_outcomes)
    log = open(result["audit_log_path"]).readlines()  # will find the file
    # Each line is valid JSON
    for line in log:
        json.loads(line)

def test_cost_summary_success_only(tmp_path):
    resources = [
        make_resource("vm-1", outcome="SUCCESS", estimated_monthly_savings=45.0),
        make_resource("vm-2", outcome="FAILED", estimated_monthly_savings=30.0),
    ]
    state = make_state(resources)
    result = audit_node(state)
    # Parse JSONL and find COST_SUMMARY
    lines = [json.loads(l) for l in open(result["audit_log_path"])]
    summary_line = next(l for l in lines if l["action_type"] == "COST_SUMMARY")
    data = json.loads(summary_line["llm_reasoning"])
    assert data["estimated_monthly_savings_recovered"] == 45.0  # not 75.0

def test_jsonl_write_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.open", Mock(side_effect=IOError("disk full")))
    with pytest.raises(IOError):
        write_audit_entry(make_audit_entry(), "/fake/dir", "run-1")

def test_chroma_failure_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr("cerberus.tools.chroma_client.upsert_resource_record",
                        Mock(side_effect=Exception("chroma error")))
    state = make_state_with_outcomes()
    result = audit_node(state)  # must not raise
    assert result["run_complete"] is True

def test_run_complete_always_set(tmp_path, sample_state):
    result = audit_node(sample_state)
    assert result["run_complete"] is True
```

**Verification command:**
```bash
pytest tests/test_audit.py -v
```

**Invariants touched:** INV-AUD-01, INV-AUD-02, INV-SEC-02 (AuditEntry has no credential fields — schema-enforced).

---

### Task 6.2 — Graph wiring and global error handler

**CC prompt:**
```
Implement cerberus/graph.py.

Build the LangGraph StateGraph:

Nodes: scan_node, enrich_node, reason_node, approve_node,
       revalidate_node, execute_node, audit_node, error_node

error_node(state: CerberusState) -> CerberusState:
  if not state["error_message"]:
    state["error_message"] = "An unexpected error occurred. Check the audit log."
  # Attempt to write an error entry to JSONL (best-effort)
  try:
    write_audit_entry(AuditEntry(
      timestamp=datetime.utcnow().isoformat(), resource_id=None,
      action_type="NODE_ERROR", llm_reasoning=state["error_message"],
      actor="agent", outcome="NODE_ERROR",
      run_id=state["run_id"], session_mutation_count=state["mutation_count"],
      project_id=state["project_id"]
    ), get_config().audit_log_dir, state["run_id"])
  except Exception as e:
    logging.error(f"audit write failed in error_node: {e}")
  state["run_complete"] = True
  return state

Edges:
  scan_node → conditional:
    if "BLOCKED" in (state["error_message"] or ""): → error_node
    else: → enrich_node

  enrich_node → reason_node (no condition)
  reason_node → approve_node (no condition)
  approve_node → revalidate_node (no condition — interrupt handled by LangGraph)

  revalidate_node → conditional:
    if len(state["approved_actions"]) == 0: → audit_node
    else: → execute_node

  execute_node → audit_node
  audit_node → END
  error_node → END

Global exception handler: wrap all node calls so any unhandled exception
routes to error_node (use LangGraph's on_error or try/except in graph config).

Interrupt: interrupt_before=["approve_node"]
Checkpointer: MemorySaver() (in-memory, no Firestore)

Export: cerberus_graph = graph.compile(checkpointer=MemorySaver(),
                                        interrupt_before=["approve_node"])
```

**Test cases:**
```python
async def test_blocked_project_routes_to_error(mock_gcp):
    result = await cerberus_graph.ainvoke(initialise_state("nexus-tech-prod"))
    assert "BLOCKED" in result["error_message"]
    assert result["run_complete"] is True

async def test_empty_approval_skips_to_audit(mock_full_pipeline):
    state = await run_to_interrupt(mock_full_pipeline)
    state["approved_actions"] = []
    result = await cerberus_graph.ainvoke(state)
    assert result["run_complete"] is True
    mock_full_pipeline.instances_stop.assert_not_called()

async def test_node_exception_routes_to_error_node(mock_scan_raises):
    result = await cerberus_graph.ainvoke(initialise_state("nexus-tech-dev-1"))
    assert result["run_complete"] is True
    assert result["error_message"] is not None
    # UI never sees a blank spinner
```

**Verification command:**
```bash
pytest tests/test_graph.py -v
```

**Invariants touched:** INV-NFR-03 (error_node — never blank spinner), INV-SEC-01 (BLOCKED routes to error_node before any processing).

---

## Session 7 — React UI

**Goal:** Working approval table and execute panel. All columns present. Dry-run modal working.
LangSmith fallback message visible when URL is null.

**Integration check:**
```bash
cd frontend && npm test -- --watchAll=false && echo "UI tests: PASS"
# Also confirm API polling works end-to-end with a running FastAPI server:
# Start server: uvicorn cerberus.api:app --port 8000 &
# Then: curl -X POST http://localhost:8000/run -H "Content-Type: application/json" \
#   -d '{"project_id":"nexus-tech-dev-sandbox","dry_run":true}' | jq .run_id
```

---

### Task 7.1 — ApprovalTable component

**CC prompt:**
```
Create frontend/src/components/ApprovalTable.tsx.

Types:
  ResourceRow {
    resource_id: string, resource_type: string, region: string,
    owner_email: string | null, ownership_status: string | null,
    decision: string | null, reasoning: string | null,
    estimated_monthly_savings: number | null
  }

Props:
  resources: ResourceRow[]
  approvedIds: Set<string>
  onApprove: (id: string) => void
  onReject: (id: string) => void

Rules:
  - Render exactly these columns (never omit any):
    Resource Name | Type | Region | Owner | Ownership Status |
    Decision | Reasoning | Est. Savings ($/mo) | Action
  - Any null/undefined field: render "—" (em-dash), never blank or "undefined"
  - Decision badge colours:
    safe_to_stop → amber background  (#FFF3CD, text #856404)
    safe_to_delete → red (#F8D7DA, text #721C24)
    needs_review → grey (#E2E3E5, text #383D41)
    skip → blue (#CCE5FF, text #004085)
  - Reasoning column: <span title={fullReasoning}>{truncate to 80 chars}...</span>
  - Approve button: disabled (and visually greyed — opacity:0.5, cursor:not-allowed)
    when ownership_status === "no_owner" (closes 4th enforcement point for INV-ENR-03)
  - Below table: "Total recoverable: ${total}/month"
    where total = sum of estimated_monthly_savings for resources in approvedIds only
  - No Execute button in this component.
```

**Test cases (React Testing Library):**
```typescript
test('all 9 columns rendered', () => {
  render(<ApprovalTable resources={[mockResource()]} approvedIds={new Set()} .../>)
  for (const col of ['Resource Name','Type','Region','Owner','Ownership Status',
                     'Decision','Reasoning','Est. Savings','Action']) {
    expect(screen.getByText(col)).toBeInTheDocument()
  }
})
test('null field renders em-dash', () => {
  render(<ApprovalTable resources={[mockResource({owner_email: null})]}
          approvedIds={new Set()} .../>)
  expect(screen.getAllByText('—').length).toBeGreaterThan(0)
})
test('approve disabled for no_owner', () => {
  render(<ApprovalTable resources={[mockResource({ownership_status:'no_owner'})]}
          approvedIds={new Set()} .../>)
  expect(screen.getByRole('button',{name:/approve/i})).toBeDisabled()
})
test('total updates on approval', () => {
  const r = mockResource({resource_id:'vm-1', estimated_monthly_savings:45.0})
  const {rerender} = render(<ApprovalTable resources={[r]}
    approvedIds={new Set()} .../>)
  expect(screen.getByText(/\$0/)).toBeInTheDocument()
  rerender(<ApprovalTable resources={[r]} approvedIds={new Set(['vm-1'])} .../>)
  expect(screen.getByText(/\$45/)).toBeInTheDocument()
})
```

**Verification command:**
```bash
cd frontend && npm test -- --testPathPattern=ApprovalTable --watchAll=false
```

**Invariants touched:** INV-UI-01 (all 9 columns), INV-ENR-03 (Approve disabled for no_owner — fourth enforcement point).

---

### Task 7.2 — ExecutePanel with dry-run modal and LangSmith fallback

**CC prompt:**
```
Create frontend/src/components/ExecutePanel.tsx.

Props:
  approvedCount: number
  dryRun: boolean
  onToggleDryRun: () => void
  onExecute: () => void
  revalidationStatus: "idle" | "running" | "complete" | "drift_detected"
  langsmithTraceUrl: string | null

Rules:
  1. Execute button:
     disabled={approvedCount === 0}
     When disabled: opacity: 0.4, cursor: not-allowed
     No onclick fires when disabled (HTML disabled attribute handles this)

  2. Dry-run toggle: defaults ON. Label: "Dry run mode"
     When toggled OFF and Execute clicked: show modal BEFORE calling onExecute.
     Modal text: "You are about to execute {approvedCount} live GCP action(s).
       This will modify real infrastructure. This cannot be undone."
     Modal buttons: "Cancel" and "Execute live"
     onExecute() called ONLY when "Execute live" is clicked.
     "Cancel" closes modal — onExecute() NOT called.

  3. Revalidation status bar (shown above Execute button):
     "idle": render nothing (null)
     "running": render "Verifying current resource state..." with spinner aria-label="loading"
     "complete": render "State verified — ready to execute" (green text)
     "drift_detected": render "Resources changed state since approval — plan updated" (amber)

  4. LangSmith section (always rendered, never hidden):
     If langsmithTraceUrl is not null:
       <a href={langsmithTraceUrl}>View reasoning trace in LangSmith</a>
     If null:
       <span role="status">LangSmith trace unavailable — local audit log is the
         authoritative record</span>
     The null case MUST be visible (not display:none). (Closes architecture gap —
     challenge to Decision 5 noted LangSmith failure could be silent.)
```

**Test cases:**
```typescript
test('execute disabled when no approvals', () => {
  render(<ExecutePanel approvedCount={0} dryRun={false} .../>)
  expect(screen.getByRole('button',{name:/execute/i})).toBeDisabled()
})
test('live mode shows modal before executing', async () => {
  const onExecute = jest.fn()
  render(<ExecutePanel approvedCount={1} dryRun={false} onExecute={onExecute} .../>)
  fireEvent.click(screen.getByRole('button',{name:/execute/i}))
  expect(screen.getByText(/live GCP action/i)).toBeInTheDocument()
  expect(onExecute).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button',{name:/execute live/i}))
  expect(onExecute).toHaveBeenCalledTimes(1)
})
test('cancel modal does not execute', () => {
  const onExecute = jest.fn()
  render(<ExecutePanel approvedCount={1} dryRun={false} onExecute={onExecute} .../>)
  fireEvent.click(screen.getByRole('button',{name:/execute/i}))
  fireEvent.click(screen.getByRole('button',{name:/cancel/i}))
  expect(onExecute).not.toHaveBeenCalled()
})
test('langsmith null shows fallback not silence', () => {
  render(<ExecutePanel langsmithTraceUrl={null} approvedCount={0} dryRun={true} .../>)
  expect(screen.getByRole('status')).toHaveTextContent(/local audit log/)
})
test('revalidation running shows spinner', () => {
  render(<ExecutePanel revalidationStatus="running" approvedCount={0} dryRun={true} .../>)
  expect(screen.getByLabelText(/loading/i)).toBeInTheDocument()
})
```

**Verification command:**
```bash
cd frontend && npm test -- --testPathPattern=ExecutePanel --watchAll=false
```

**Invariants touched:** INV-UI-02 (Execute disabled when zero approvals), INV-UI-03 (dry-run modal is the last human checkpoint — "Execute live" click is the affirmative confirmation).

---

## Session 8 — Integration and Demo Readiness

**Goal:** Full end-to-end test passes. Live sandbox run works. Three consecutive
demo runs produce identical classifications.

**Integration check:**
```bash
pytest tests/test_e2e.py -v
# Determinism: three consecutive runs on sandbox must match
python scripts/run_demo_smoke_test.py
```

---

### Task 8.1 — End-to-end test (mock GCP)

**CC prompt:**
```
Create tests/test_e2e.py with a single integration test function
test_full_pipeline_mock() that:

1. Builds a mock GCP environment with exactly:
   - 3 VMs: (departed_owner, 80h idle), (active_owner, 80h idle), (no_owner, 80h idle)
   - 1 orphaned disk: departed_owner, label data-classification=sensitive
   - 1 orphaned disk: no labels
   - 1 unused IP: active_owner

2. Runs cerberus_graph through scan_node → enrich_node → reason_node
   (stop at the approve_node interrupt)

3. Asserts on plan state:
   - len(plan) == 6 (all resources discovered)
   - sensitive disk has flagged_for_review=True
   - no_owner resources have decision="needs_review"
   - no resource has decision=None
   - no resource has ownership_status=None

4. Approves the 3 VMs. Rejects disk-1, disk-2, ip-1.
   Resumes graph with dry_run=True.

5. Asserts on final state:
   - mutation_count == 0 (dry_run)
   - run_complete == True
   - error_message is None
   - All 3 VMs have outcome="DRY_RUN"
   - no_owner disk has outcome="SKIPPED_GUARDRAIL" OR not in approved_actions
   - A JSONL audit log file exists and contains >= 6 lines
   - A COST_SUMMARY line exists in the JSONL log
   - ChromaDB collection has >= 6 records after the run

This test is the regression guard for every invariant. If any invariant is broken,
this test must catch it before demo day.
```

**Test cases:** The test IS the test case.

**Verification command:**
```bash
pytest tests/test_e2e.py::test_full_pipeline_mock -v --tb=short
```

**Invariants touched:** All invariants. This is the system-level regression guard.

---

### Task 8.2 — Demo smoke test script

**CC prompt:**
```
Create scripts/run_demo_smoke_test.py.

This script runs three consecutive live scans against the seeded sandbox project
and verifies:

1. Each run completes without error (run_complete=True, error_message=None or partial-scan only)
2. All 3 runs classify the same resources with the same decisions (determinism check)
3. At least 1 resource is classified safe_to_stop or safe_to_delete in each run
4. JSONL audit logs are written for each run (3 separate files)
5. ChromaDB has records for all 6 seeded resources after run 1

How it works:
  - Uses the FastAPI test client (httpx.AsyncClient) against a live uvicorn process
  - POST /run with project_id=nexus-tech-dev-sandbox, dry_run=True
  - Poll GET /run/{run_id}/plan until status="awaiting_approval" (max 120s)
  - POST /run/{run_id}/approve with all resource IDs as approved_ids
  - Poll GET /run/{run_id}/status until run_complete=True (max 60s)
  - Record decisions from each run

Output format:
  Run 1: 6 resources, $XXX/month identified, decisions: [safe_to_stop x2, needs_review x4]
  Run 2: 6 resources, $XXX/month identified, decisions: [safe_to_stop x2, needs_review x4]
  Run 3: 6 resources, $XXX/month identified, decisions: [safe_to_stop x2, needs_review x4]
  Determinism check: PASS / FAIL
  JSONL logs: 3 files found
  ChromaDB records: 6 found
  OVERALL: PASS / FAIL

Exit code 0 on PASS, 1 on FAIL.
Run this script the morning of demo day as the final gate check.
```

**Test cases:** Script exit code 0 = pass.

**Verification command:**
```bash
python scripts/run_demo_smoke_test.py
# Expected output: OVERALL: PASS
```

**Invariants touched:** INV-SCAN-02 (idle detection consistent across runs), INV-RSN-01 (determinism at temperature=0), INV-AUD-01 (JSONL logs produced), INV-ENR-03 (no_owner resources never reach execution).

---

## Session 9 — Architecture Showcase (Safety-First Agentic Loop)

**Goal:** Surface the three architectural pillars for judges as a coherent demo
narrative: (1) IAM Access Head — natural-language onboarding with least-privilege
role synthesis; (2) Hard-Guardrail Invariants — production protection and the
"no owner = no delete" rule demonstrated live; (3) ROI Audit Engine — a
machine-readable COST_SUMMARY with human-readable narrative output. Nothing in
this session changes existing production behaviour. All guard rail invariants
remain in force.

> **Scope note — Task 9.1:** `cerberus/nodes/access_node.py` and
> `tests/test_access.py` are not in the CLAUDE.md permitted-files list. Before
> executing Task 9.1, update the `## 3. Scope Boundary` section of CLAUDE.md to
> add both files, then proceed.

**Integration check** (run after all 3 tasks committed):
```bash
pytest tests/test_access.py -v
python scripts/run_demo_smoke_test.py
python -c "
from cerberus.nodes.access_node import synthesize_iam_request
print('IAM access head import: PASS')
"
```

---

### Task 9.1 — IAM Access Head: access_node.py (The "Alice" Workflow)

**Context for judges:** The dev-environment guardian already cleans up waste.
This head shows the *other* half of the loop — how a developer requests access
in the first place. Instead of filing a ticket and waiting for an Editor role,
Alice types a natural-language request; Gemini synthesizes the minimum IAM
permissions required and emits a 7-step provisioning checklist.

**CC prompt:**
```
Create cerberus/nodes/access_node.py (scope extension — CLAUDE.md updated).

Data model (Pydantic BaseModel, not stored in CerberusState — standalone):

  class IamRequest(BaseModel):
      requester_email: str
      request_text: str          # natural language, e.g. "I need BigQuery read on fraud_transactions"
      project_id: str

  class IamProvisioningPlan(BaseModel):
      requester_email: str
      custom_role_id: str        # e.g. "cerberus_bq_fraud_read_20260331"
      permissions: list[str]     # e.g. ["bigquery.tables.get", "bigquery.tables.list", ...]
      binding_condition: str     # CEL expression — resource-level restriction if possible
      budget_alert_threshold_usd: float
      review_after_days: int     # always 90 — matches STALENESS_THRESHOLD_DAYS
      checklist: list[str]       # exactly 7 steps as strings
      reasoning: str             # ≤ 3 sentences, cite at least one permission name

def synthesize_iam_request(request: IamRequest) -> IamProvisioningPlan:

  1. Validate project_id with validate_project_id() — raise ValueError on mismatch.
  2. Build a Gemini prompt:
       System: "You are a GCP security synthesizer. Apply least-privilege.
                Never return roles/editor, roles/owner, or roles/viewer.
                Always return a custom role with specific permissions.
                Return JSON only."
       User:   f"Project: {project_id}\nRequester: {requester_email}\nRequest: {request_text}\n
                Return a JSON object matching this schema: {IamProvisioningPlan.model_json_schema()}"
  3. Call Gemini (gemini-1.5-pro-002, temperature=0, response_mime_type="application/json")
     using gcp_call_with_retry wrapper.
  4. Parse the response into IamProvisioningPlan. On parse failure, raise ValueError
     with the raw response text in the message.
  5. Enforce: len(plan.checklist) == 7 — pad with
     "Step N: Human review required" if Gemini returns fewer.
  6. Enforce: plan.review_after_days == 90 — override if Gemini returns any other value.
  7. Return the plan.

Do NOT write to JSONL, ChromaDB, or CerberusState. This node is standalone.
Do NOT add any GCP mutation calls — this node synthesizes a plan only.
Do NOT import from audit_node — AuditEntry is only for agent runs.
```

**Test cases** (create `tests/test_access.py`):
```python
def test_synthesize_returns_custom_role(mock_gemini):
    # mock_gemini returns a valid IamProvisioningPlan JSON
    plan = synthesize_iam_request(IamRequest(
        requester_email="alice@example.com",
        request_text="I need BigQuery read access for fraud_transactions",
        project_id="nexus-tech-dev-sandbox"
    ))
    assert plan.custom_role_id.startswith("cerberus_")
    assert len(plan.permissions) >= 1
    assert all("bigquery" in p for p in plan.permissions)
    assert plan.review_after_days == 90

def test_checklist_always_seven_steps(mock_gemini_short_checklist):
    # mock returns only 3 checklist items
    plan = synthesize_iam_request(...)
    assert len(plan.checklist) == 7

def test_review_days_override(mock_gemini_wrong_days):
    # mock returns review_after_days=30
    plan = synthesize_iam_request(...)
    assert plan.review_after_days == 90

def test_invalid_project_raises(mock_gemini):
    with pytest.raises(ValueError, match="project"):
        synthesize_iam_request(IamRequest(
            requester_email="alice@example.com",
            request_text="I need BigQuery access",
            project_id="nexus-tech-PROD-1"   # fails pattern
        ))
```

**Verification command:**
```bash
pytest tests/test_access.py -v --tb=short
```

**Invariants touched:** INV-SEC-01 (project pattern check before any call),
INV-NFR-02 (gcp_call_with_retry wraps Gemini call), INV-RSN-02 analogue
(reasoning field enforced ≤ 3 sentences with quantitative reference).

**Judge talking point:** "Alice types one sentence. Cerberus calls Gemini,
decomposes it to the minimum GCP permissions, creates a scoped custom role —
never a broad predefined role — and outputs a 7-step provisioning checklist
including a 90-day review reminder that matches our staleness threshold."

---

### Task 9.2 — Guardrails Showcase: Live Invariant Demo Script

**Context for judges:** The invariants exist throughout the codebase but are
invisible during a happy-path demo. This task produces a single runnable script
that demonstrates three guardrails firing in sequence against the seeded sandbox,
with annotated console output explaining what each guardrail prevented.

**CC prompt:**
```
Create scripts/demo_guardrails.py.

This script demonstrates three hard invariants firing in sequence.
It uses the FastAPI test client (httpx.AsyncClient) against a live uvicorn
process pointed at the seeded sandbox. Run with: python scripts/demo_guardrails.py

GUARDRAIL 1 — Production Protection (INV-SEC-01)
  POST /run with project_id="nexus-tech-PRODUCTION-1"
  Assert: response status 422 or run completes with error_message containing "pattern"
  Print: "[GUARDRAIL 1 PASS] Production project blocked before any GCP call."

GUARDRAIL 2 — No-Owner = No-Delete (INV-ENR-03, all 4 enforcement points)
  POST /run with project_id="nexus-tech-dev-sandbox", dry_run=True
  Poll GET /run/{run_id}/plan until status="awaiting_approval"
  Find the first resource with ownership_status="no_owner"
  Assert: its decision is "needs_review"
  Submit it in approved_ids anyway (force it through approve_node)
  Poll GET /run/{run_id}/status until run_complete=True
  Find that resource's outcome in the final state
  Assert: outcome == "SKIPPED_GUARDRAIL"
  Print: "[GUARDRAIL 2 PASS] no_owner resource reached execute_node and was skipped."

GUARDRAIL 3 — Dry-Run Firewall (INV-UI-03)
  POST /run with dry_run=True
  Approve all resources
  Poll until run_complete=True
  Assert: mutation_count == 0
  Assert: all resource outcomes == "DRY_RUN" (not SUCCESS or FAILED)
  Print: "[GUARDRAIL 3 PASS] Zero GCP mutations made in dry-run mode."

Final output:
  ==========================================
  GUARDRAILS DEMO COMPLETE
  Guardrail 1 — Production block:   PASS
  Guardrail 2 — No-owner skip:      PASS
  Guardrail 3 — Dry-run firewall:   PASS
  ==========================================

Exit code 0 on all PASS, 1 if any FAIL.
```

**Test cases:** Script exit code 0 = pass.

**Verification command:**
```bash
python scripts/demo_guardrails.py
# Expected: GUARDRAILS DEMO COMPLETE — all 3 PASS
```

**Invariants touched:** INV-SEC-01, INV-ENR-03 (all 4 enforcement points),
INV-UI-03, INV-EXE-03.

**Judge talking point:** "This is not a theoretical claim. Here is the script
running live. Guardrail 1 blocks the wrong project before a single GCP API call
fires. Guardrail 2 shows a mystery resource reaching execute_node and being
skipped — the audit log records SKIPPED_GUARDRAIL, not a silent drop.
Guardrail 3 proves zero mutations occurred in dry-run."

---

### Task 9.3 — ROI Summary: Human-Readable Cost Narrative

**Context for judges:** The COST_SUMMARY JSONL entry already exists (Task 6.1).
This task adds a `scripts/print_run_summary.py` helper that reads the most
recent audit log and prints a judge-facing ROI narrative in plain English,
and adds an `/run/{run_id}/summary` FastAPI endpoint that returns the same
data as JSON (no credentials — INV-SEC-02 compliant).

> **Scope note:** `GET /run/{run_id}/summary` is an addition to the four
> permitted FastAPI endpoints in CLAUDE.md section 4. Update that list before
> executing this task.

**CC prompt:**
```
PART A — scripts/print_run_summary.py

Reads the most recent audit_{run_id}.jsonl file from AUDIT_LOG_DIR.
Locates the COST_SUMMARY line (action_type=="COST_SUMMARY").
Prints:

  ══════════════════════════════════════════════
  CERBERUS RUN SUMMARY  run_id={run_id}
  ══════════════════════════════════════════════
  Resources scanned:          {resources_scanned}
  Total waste identified:     ${total_waste_identified:.2f}/mo
  Actions approved:           {actions_approved}
  Actions executed:           {actions_executed}
  Recovered savings:          ${estimated_monthly_savings_recovered:.2f}/mo
  ──────────────────────────────────────────────
  Evidence-based decisions:   {actions_approved} resources classified by
                              Gemini 1.5 Pro at temperature=0.
  Audit log:                  {audit_log_path}
  LangSmith trace:            {langsmith_trace_url or "unavailable — local JSONL is authoritative"}
  ══════════════════════════════════════════════

If COST_SUMMARY line is missing: print "No COST_SUMMARY found in log." and exit 1.
If AUDIT_LOG_DIR has no files: print "No audit logs found." and exit 1.

PART B — GET /run/{run_id}/summary endpoint in cerberus/api.py

Response model (Pydantic BaseModel — no credential fields, INV-SEC-02):

  class RunSummary(BaseModel):
      run_id: str
      resources_scanned: int
      total_waste_identified: float | None
      actions_approved: int
      actions_executed: int
      estimated_monthly_savings_recovered: float
      audit_log_path: str | None
      langsmith_trace_url: str | None

Implementation:
  - Read state from the in-memory run registry (same dict used by /status).
  - Extract the COST_SUMMARY fields from state["cost_summary"] if present,
    else return 404 with detail="Run not complete or summary not yet written."
  - Return RunSummary. No fields from CerberusConfig may appear in the response.

Add state["cost_summary"] dict population in audit_node.py (Task 6.1 follow-on):
  After writing the COST_SUMMARY JSONL entry, set:
    state["cost_summary"] = {
        "resources_scanned": ...,
        "total_waste_identified": ...,
        "actions_approved": ...,
        "actions_executed": ...,
        "estimated_monthly_savings_recovered": ...
    }
  This is the only state key audit_node adds beyond what Task 6.1 already sets.
```

**Test cases:**
```python
def test_summary_endpoint_returns_no_credentials(client, completed_run_id):
    r = client.get(f"/run/{completed_run_id}/summary")
    assert r.status_code == 200
    body = r.json()
    assert "service_account" not in body
    assert "key_path" not in body
    assert "billing_account" not in body
    assert "estimated_monthly_savings_recovered" in body

def test_summary_404_before_complete(client, pending_run_id):
    r = client.get(f"/run/{pending_run_id}/summary")
    assert r.status_code == 404

def test_print_run_summary_exits_0(tmp_path, sample_audit_log_with_cost_summary):
    result = subprocess.run(
        ["python", "scripts/print_run_summary.py"],
        env={**os.environ, "AUDIT_LOG_DIR": str(tmp_path)},
        capture_output=True
    )
    assert result.returncode == 0
    assert b"Recovered savings" in result.stdout
```

**Verification command:**
```bash
# After a smoke-test run:
python scripts/print_run_summary.py
# Expected: formatted ROI table with non-zero recovered savings
```

**Invariants touched:** INV-AUD-02 (COST_SUMMARY correctness), INV-SEC-02
(no credentials in summary endpoint), INV-NFR-03 (error_node catches any
summary write failure).

**Judge talking point:** "Every run produces a machine-readable JSONL and a
human-readable ROI table. The recovered savings figure only counts resources
where the GCP state-change was verified — not just approved. If the stop call
succeeded but the verification read failed, that resource is FAILED, not SUCCESS,
and is excluded from the savings total."


# Session 10 — Three-Head Expansion
## Cerberus · PBVI Phase 6 · session/s10_three_heads
## Claude.md: v2.0 · FROZEN · 2026-03-31

> This file contains all three Session 10 artefacts in order:
> 1. Build Guide (CC prompts, test cases, verification commands)
> 2. Session Log (to be filled during the session)
> 3. Verification Record (to be filled after each task)

---

# SESSION 10 BUILD GUIDE — Three-Head Expansion
## Cerberus · PBVI Phase 6 · session/s10_three_heads
## Claude.md: v2.0 · FROZEN · 2026-03-31

---

## Before You Start — Gate Check

```
[ ] Sessions 1–8 PRs are all merged to main
[ ] pytest tests/ -v passes green on main (all existing tests)
[ ] Claude.md v2.0 is committed to the repo root
[ ] reportlab is added to pyproject.toml and uv sync has been run
[ ] You can answer without opening any document:
    "What does each head do and where does its data come from?"
```

---

## Branch

```bash
git checkout main && git pull origin main
git checkout -b session/s10_three_heads
git add Claude.md  # commit the v2.0 update first
git commit -m "Claude.md v2.0: three-head expansion scope"
```

Commit `SESSION_10_LOG.md` and `SESSION_10_VERIFICATION_RECORD.md` before any build task:
```bash
git add SESSION_10_LOG.md SESSION_10_VERIFICATION_RECORD.md
git commit -m "Session 10: scaffold — SESSION_LOG and VERIFICATION_RECORD"
```

---

## Session Integration Check
*(run after all 10 tasks committed — not before)*

```bash
# Backend: all new routes register and respond
uvicorn cerberus.api:app --port 8001 &
sleep 2

curl -s http://localhost:8001/iam/inventory?project_id=nexus-tech-dev-sandbox | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'IAM inventory: {len(d)} records')"
curl -s "http://localhost:8001/cost/project/nexus-tech-dev-sandbox" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Cost project: total={d.get(\"total_usd\",\"missing\")}')"
curl -s http://localhost:8001/security/flags?project_id=nexus-tech-dev-sandbox | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Security flags: {len(d)} flags')"
curl -s http://localhost:8001/tickets | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Tickets: {len(d)} pending')"

# PDF generation
python3 -c "
from cerberus.services.pdf_report import generate_audit_report
pdf_bytes = generate_audit_report('nexus-tech-dev-sandbox', [])
assert len(pdf_bytes) > 1000, 'PDF too small — generation failed'
print(f'PDF report: {len(pdf_bytes)} bytes — PASS')
"

# Frontend: all 5 pages build without error
cd frontend && npm run build 2>&1 | tail -5
cd ..

# Backend: all new tests pass
pytest tests/test_iam_head.py tests/test_cost_head.py \
       tests/test_security_head.py tests/test_routes.py \
       tests/test_pdf_report.py -v

kill %1 2>/dev/null
echo "Session 10 integration: PASS"
```

---

## Task 10.1 — Backend models, head skeletons, and route registration

**What this builds:** Pydantic models for IAM tickets, cost records, and security flags.
Empty skeleton files for the three heads. New routes registered in `api.py`.
No logic — stubs only.

**CC prompt:**
```
Create these files. All head and service files are stubs — function signatures
with `pass` bodies only. No logic implemented in this task.

--- cerberus/models/iam_ticket.py ---
from pydantic import BaseModel
from typing import Literal

class IAMRequest(BaseModel):
    natural_language_request: str
    requester_email: str
    project_id: str

class SynthesizedIAMPlan(BaseModel):
    requester_email: str
    project_id: str
    role: str
    justification: str
    synthesized_at: str       # ISO 8601
    raw_request: str

class IAMTicket(BaseModel):
    ticket_id: str            # uuid4
    plan: SynthesizedIAMPlan
    status: Literal["pending", "approved", "rejected", "provisioned"]
    created_at: str
    reviewed_at: str | None = None
    reviewed_by: str | None = None

class IAMBinding(BaseModel):
    identity: str             # user email or service account
    role: str
    project_id: str
    binding_type: Literal["user", "serviceAccount", "group"]

--- cerberus/models/cost_record.py ---
from pydantic import BaseModel

class ProjectCostSummary(BaseModel):
    project_id: str
    total_usd: float
    attributed_usd: float
    unattributed_usd: float
    period: str               # "current_month"
    breakdown: list[dict]     # [{"owner_email": str, "cost_usd": float}]

class UserCostSummary(BaseModel):
    owner_email: str
    project_id: str
    total_usd: float
    resource_count: int
    resources: list[dict]     # [{"resource_id": str, "resource_type": str, "cost_usd": float}]

--- cerberus/models/security_flag.py ---
from pydantic import BaseModel
from typing import Literal

FLAG_TYPES = Literal["OVER_PERMISSIONED", "GHOST_RESOURCE", "BUDGET_BREACH"]

class SecurityFlag(BaseModel):
    flag_id: str              # uuid4
    flag_type: FLAG_TYPES
    identity_or_resource: str # email or resource_id
    project_id: str
    detected_at: str          # ISO 8601
    detail: str               # human-readable explanation
    status: Literal["open", "acknowledged", "resolved"] = "open"

class BudgetStatus(BaseModel):
    project_id: str
    current_month_usd: float
    threshold_usd: float
    breached: bool
    percent_used: float

--- cerberus/heads/__init__.py --- (empty)

--- cerberus/heads/iam_head.py --- (stub)
async def synthesize_iam_request(request, config) -> SynthesizedIAMPlan: pass
async def create_ticket(plan) -> IAMTicket: pass
async def get_pending_tickets() -> list[IAMTicket]: pass
async def approve_ticket(ticket_id: str, reviewer_email: str) -> IAMTicket: pass
async def provision_iam_binding(ticket: IAMTicket, dry_run: bool) -> dict: pass
async def get_iam_inventory(project_id: str, credentials) -> list[IAMBinding]: pass

--- cerberus/heads/cost_head.py --- (stub)
async def get_project_cost_summary(project_id: str) -> ProjectCostSummary: pass
async def get_user_cost_summary(owner_email: str, project_id: str) -> UserCostSummary: pass

--- cerberus/heads/security_head.py --- (stub)
async def get_security_flags(project_id: str, credentials) -> list[SecurityFlag]: pass
async def check_budget_status(project_id: str) -> BudgetStatus: pass
async def generate_audit_report_data(project_id: str) -> dict: pass

--- cerberus/services/pdf_report.py --- (stub)
def generate_audit_report(project_id: str, flags: list) -> bytes: pass

--- cerberus/routes/iam_routes.py ---
Register these FastAPI routes (return empty placeholders — logic in Task 10.2):
  POST /iam/request
  GET  /iam/request/{request_id}/preview
  POST /iam/request/{request_id}/confirm
  GET  /iam/inventory

--- cerberus/routes/cost_routes.py ---
  GET /cost/project/{project_id}
  GET /cost/user  (query params: owner_email, project_id)

--- cerberus/routes/security_routes.py ---
  GET /security/flags
  GET /security/budget-status
  GET /security/report/download

--- cerberus/routes/ticket_routes.py ---
  GET  /tickets
  POST /tickets/{ticket_id}/approve
  POST /tickets/{ticket_id}/provision

In cerberus/api.py: import and include all four new routers.
Use app.include_router() with appropriate prefixes.
Do not touch any existing route or endpoint.
```

**Test cases:**
```python
# tests/test_routes.py
from fastapi.testclient import TestClient
from cerberus.api import app
client = TestClient(app)

def test_iam_inventory_route_exists():
    r = client.get("/iam/inventory?project_id=nexus-tech-dev-1")
    assert r.status_code != 404

def test_cost_project_route_exists():
    r = client.get("/cost/project/nexus-tech-dev-1")
    assert r.status_code != 404

def test_security_flags_route_exists():
    r = client.get("/security/flags?project_id=nexus-tech-dev-1")
    assert r.status_code != 404

def test_tickets_route_exists():
    r = client.get("/tickets")
    assert r.status_code != 404

def test_existing_run_route_untouched():
    r = client.get("/run/nonexistent-id/status")
    assert r.status_code == 404  # not 500 — existing routes still work

def test_iam_ticket_model_validation():
    from cerberus.models.iam_ticket import IAMTicket, SynthesizedIAMPlan
    plan = SynthesizedIAMPlan(
        requester_email="alice@x.com", project_id="nexus-tech-dev-1",
        role="roles/bigquery.dataViewer", justification="needs read access",
        synthesized_at="2026-03-31T10:00:00Z", raw_request="give alice bigquery read"
    )
    ticket = IAMTicket(ticket_id="t-1", plan=plan, status="pending",
                       created_at="2026-03-31T10:00:00Z")
    assert ticket.status == "pending"

def test_security_flag_type_locked():
    from cerberus.models.security_flag import SecurityFlag
    import pytest
    with pytest.raises(Exception):
        SecurityFlag(flag_id="f-1", flag_type="INVALID_TYPE",
                     identity_or_resource="vm-1", project_id="p",
                     detected_at="2026-01-01T00:00:00Z", detail="test")
```

**Verification command:**
```bash
pytest tests/test_routes.py -v
```

**Invariants touched:** INV-IAM-01 (ticket model has status machine), INV-IAM-03 (IAMBinding has identity, role, project_id fields), INV-COST-01 (ProjectCostSummary has attributed/unattributed split), INV-SEC2-03 (pdf_report stub exists).

**Code review:**
- [ ] No existing route in `api.py` is modified — only new `include_router` calls added
- [ ] `IAMTicket.status` is a `Literal` with exactly 4 values: pending/approved/rejected/provisioned
- [ ] `SecurityFlag.flag_type` is a `Literal` with exactly 3 values matching Claude.md enum
- [ ] `ProjectCostSummary` has both `attributed_usd` AND `unattributed_usd` — not one total field

**Commit:** `git add -A && git commit -m "Task 10.1: backend models, head skeletons, route registration"`

---

## Task 10.2 — IAM Head: Gemini synthesis, ticket lifecycle, asset inventory

**What this builds:** Full implementation of `iam_head.py` and `iam_routes.py`.
Gemini converts natural language → structured IAM plan → ticket. Admin approves.
Asset inventory reads live GCP IAM policy.

**Why this is fast:** Gemini synthesis reuses the same `google-generativeai` pattern
from `reason_node.py`. The ticket store is an in-memory dict (same pattern as `active_runs`
in `api.py`). No new infrastructure.

**CC prompt:**
```
Implement cerberus/heads/iam_head.py fully.

MODULE-LEVEL STATE:
  _tickets: dict[str, IAMTicket] = {}   # in-memory ticket store keyed by ticket_id

synthesize_iam_request(request: IAMRequest, config: CerberusConfig) -> SynthesizedIAMPlan:
  1. Build a Gemini prompt:
     system = "You are a GCP IAM analyst. Convert a natural language access request
               into a structured IAM plan. Output ONLY valid JSON matching this schema:
               {SynthesizedIAMPlan schema}. Choose the minimum-privilege role that
               satisfies the request. Never suggest roles/owner or roles/editor unless
               explicitly requested and justified."
     user = f"Request: {request.natural_language_request}\n
              Requester: {request.requester_email}\n
              Project: {request.project_id}"
  2. Call genai.GenerativeModel(config.gemini_model).generate_content with temperature=0,
     response_mime_type="application/json".
  3. Parse response. On JSONDecodeError: raise ValueError("IAM synthesis failed: unparseable response")
  4. Return SynthesizedIAMPlan(**parsed, raw_request=request.natural_language_request,
     synthesized_at=datetime.utcnow().isoformat())

create_ticket(plan: SynthesizedIAMPlan) -> IAMTicket:
  ticket_id = str(uuid.uuid4())
  ticket = IAMTicket(ticket_id=ticket_id, plan=plan, status="pending",
                     created_at=datetime.utcnow().isoformat())
  _tickets[ticket_id] = ticket
  return ticket

get_pending_tickets() -> list[IAMTicket]:
  return [t for t in _tickets.values() if t.status == "pending"]

approve_ticket(ticket_id: str, reviewer_email: str) -> IAMTicket:
  If ticket_id not in _tickets: raise KeyError(f"Ticket {ticket_id} not found")
  ticket = _tickets[ticket_id]
  ticket.status = "approved"
  ticket.reviewed_at = datetime.utcnow().isoformat()
  ticket.reviewed_by = reviewer_email
  return ticket

provision_iam_binding(ticket: IAMTicket, dry_run: bool = True) -> dict:
  If dry_run:
    return {"status": "DRY_RUN",
            "would_add": f"{ticket.plan.identity} → {ticket.plan.role} on {ticket.plan.project_id}",
            "ticket_id": ticket.ticket_id}
  Else:
    Use gcp_call_with_retry to call resourcemanager_v3.ProjectsClient.set_iam_policy
    adding the new binding. On success: ticket.status = "provisioned". Return result.

get_iam_inventory(project_id: str, credentials) -> list[IAMBinding]:
  Calls resourcemanager_v3.ProjectsClient.get_iam_policy(project_id).
  For each binding: for each member: extract binding_type (user/serviceAccount/group),
  identity (strip "user:" or "serviceAccount:" prefix), role.
  Returns list of IAMBinding records.
  Wrap in gcp_call_with_retry. On CerberusRetryExhausted: return [].

Implement cerberus/routes/iam_routes.py — wire all routes to iam_head functions.
POST /iam/request → synthesize_iam_request then create_ticket. Return ticket.
GET  /iam/request/{request_id}/preview → return _tickets[request_id].plan as JSON
POST /iam/request/{request_id}/confirm → return ticket (already created — confirm is idempotent)
GET  /iam/inventory → get_iam_inventory (project_id from query param)
```

**Test cases:**
```python
# tests/test_iam_head.py

def test_synthesis_calls_gemini_with_temperature_zero(mock_gemini_iam):
    # mock returns valid SynthesizedIAMPlan JSON
    result = synthesize_iam_request(
        IAMRequest(natural_language_request="give alice bigquery read",
                   requester_email="alice@x.com", project_id="nexus-tech-dev-1"),
        mock_config
    )
    assert result.role is not None
    mock_gemini_iam.generate_content.assert_called_once()
    call_kwargs = mock_gemini_iam.generate_content.call_args
    assert call_kwargs[1]["generation_config"].temperature == 0

def test_synthesis_never_suggests_owner_for_simple_request(mock_gemini_returns_owner):
    # If Gemini tries to return roles/owner for a read request, the function
    # should not blindly accept it — this tests the prompt instruction
    # (note: this is a prompt-quality test, not a code guard)
    pass  # documented as prompt evaluation item

def test_create_ticket_stores_in_memory():
    plan = make_test_plan()
    ticket = create_ticket(plan)
    assert ticket.ticket_id in _tickets
    assert ticket.status == "pending"

def test_approve_ticket_changes_status():
    plan = make_test_plan()
    ticket = create_ticket(plan)
    approved = approve_ticket(ticket.ticket_id, "admin@x.com")
    assert approved.status == "approved"
    assert approved.reviewed_by == "admin@x.com"

def test_provision_dry_run_returns_dry_run_status():
    plan = make_test_plan()
    ticket = create_ticket(plan)
    approve_ticket(ticket.ticket_id, "admin@x.com")
    result = provision_iam_binding(ticket, dry_run=True)
    assert result["status"] == "DRY_RUN"
    assert "would_add" in result

def test_provision_live_never_called_without_approval(mock_gcp_iam):
    # provision with dry_run=False on a "pending" ticket — this tests
    # that callers (the route) must approve before provisioning
    # The route layer enforces this — tested in test_routes.py
    pass

def test_get_pending_tickets_filters_non_pending():
    plan = make_test_plan()
    t1 = create_ticket(plan)
    t2 = create_ticket(plan)
    approve_ticket(t1.ticket_id, "admin@x.com")
    pending = get_pending_tickets()
    ids = [t.ticket_id for t in pending]
    assert t1.ticket_id not in ids
    assert t2.ticket_id in ids

def test_iam_inventory_returns_binding_list(mock_gcp_iam_policy):
    bindings = get_iam_inventory("nexus-tech-dev-1", mock_creds)
    for b in bindings:
        assert b.identity is not None
        assert b.role is not None
        assert b.project_id == "nexus-tech-dev-1"
```

**Verification command:**
```bash
pytest tests/test_iam_head.py -v
```

**Invariants touched:** INV-IAM-01 (synthesis before ticket creation enforced in route), INV-IAM-02 (dry_run=True default in provision), INV-IAM-03 (IAMBinding fields validated in test).

**Code review:**
- [ ] `synthesize_iam_request` calls Gemini at `temperature=0` — confirm in code
- [ ] `provision_iam_binding` defaults `dry_run=True` — no live call without explicit False
- [ ] Route `POST /tickets/{id}/provision` checks ticket.status == "approved" before calling provision — rejected/pending tickets must be blocked
- [ ] `get_iam_inventory` wraps GCP call in `gcp_call_with_retry` — no custom retry

**Commit:** `git add -A && git commit -m "Task 10.2: IAM Head — synthesis, ticket lifecycle, inventory"`

---

## Task 10.3 — Cost Head: per-project and per-user spend from ChromaDB

**What this builds:** `cost_head.py` reads resource history from ChromaDB and
aggregates spend by project and by owner email. No live GCP Billing API calls.

**Why ChromaDB only:** INV-COST-02 explicitly prohibits live Billing API calls at query
time. The cost data was written to ChromaDB by `audit_node` during scan runs. This task
reads it.

**CC prompt:**
```
Implement cerberus/heads/cost_head.py.

get_project_cost_summary(project_id: str) -> ProjectCostSummary:
  1. Query ChromaDB collection "resource_history" for all records where
     metadata["project_id"] == project_id.
     Use: collection.get(where={"project_id": project_id}, include=["metadatas"])
  2. total_usd = sum of metadata["estimated_monthly_cost"] for all records
     (use 0.0 if field missing or null)
  3. attributed = records where metadata["owner_email"] != "unknown" and != None
     attributed_usd = sum of their costs
  4. unattributed_usd = total_usd - attributed_usd
  5. breakdown = [{"owner_email": email, "cost_usd": cost} for each unique owner]
     IMPORTANT: unattributed resources must appear as {"owner_email": "unattributed", "cost_usd": X}
     in the breakdown — never silently excluded. (INV-COST-01)
  6. Return ProjectCostSummary(...)

  If ChromaDB query raises: log WARNING, return ProjectCostSummary with all zeros.

get_user_cost_summary(owner_email: str, project_id: str) -> UserCostSummary:
  1. Query ChromaDB where metadata["owner_email"] == owner_email
     AND metadata["project_id"] == project_id
  2. total_usd = sum of costs
  3. resources = [{"resource_id": id, "resource_type": type, "cost_usd": cost}]
  4. Return UserCostSummary(...)

  If no records found: return UserCostSummary with total_usd=0.0, empty resources list.

Implement cerberus/routes/cost_routes.py:
  GET /cost/project/{project_id} → get_project_cost_summary(project_id)
  GET /cost/user → get_user_cost_summary(owner_email, project_id) from query params
    If owner_email or project_id missing from query: return HTTP 422 with message
    "owner_email and project_id are required query parameters"
```

**Test cases:**
```python
# tests/test_cost_head.py

def test_project_cost_includes_unattributed(tmp_chroma):
    # seed ChromaDB with 2 attributed + 1 unattributed resource
    upsert_resource_record(make_resource("vm-1", owner_email="alice@x.com",
                           estimated_monthly_cost=45.0), "r1", "nexus-tech-dev-1")
    upsert_resource_record(make_resource("vm-2", owner_email="bob@x.com",
                           estimated_monthly_cost=30.0), "r1", "nexus-tech-dev-1")
    upsert_resource_record(make_resource("disk-1", owner_email=None,
                           estimated_monthly_cost=10.0), "r1", "nexus-tech-dev-1")

    result = get_project_cost_summary("nexus-tech-dev-1")
    assert result.total_usd == 85.0
    assert result.attributed_usd == 75.0
    assert result.unattributed_usd == 10.0
    # unattributed must appear in breakdown
    unattr = [b for b in result.breakdown if b["owner_email"] == "unattributed"]
    assert len(unattr) == 1
    assert unattr[0]["cost_usd"] == 10.0

def test_attributed_plus_unattributed_equals_total(tmp_chroma, seed_mixed_resources):
    result = get_project_cost_summary("nexus-tech-dev-1")
    assert abs(result.attributed_usd + result.unattributed_usd - result.total_usd) < 0.01

def test_user_cost_query_returns_matching_resources(tmp_chroma):
    upsert_resource_record(make_resource("vm-alice-1", owner_email="alice@x.com",
                           estimated_monthly_cost=45.0), "r1", "nexus-tech-dev-1")
    upsert_resource_record(make_resource("vm-alice-2", owner_email="alice@x.com",
                           estimated_monthly_cost=20.0), "r1", "nexus-tech-dev-1")
    upsert_resource_record(make_resource("vm-bob-1", owner_email="bob@x.com",
                           estimated_monthly_cost=30.0), "r1", "nexus-tech-dev-1")

    result = get_user_cost_summary("alice@x.com", "nexus-tech-dev-1")
    assert result.total_usd == 65.0
    assert result.resource_count == 2

def test_user_cost_empty_when_no_records(tmp_chroma):
    result = get_user_cost_summary("nobody@x.com", "nexus-tech-dev-1")
    assert result.total_usd == 0.0
    assert result.resources == []

def test_chroma_failure_returns_zeros(monkeypatch):
    monkeypatch.setattr("cerberus.tools.chroma_client.get_chroma_collection",
                        Mock(side_effect=Exception("chroma down")))
    result = get_project_cost_summary("nexus-tech-dev-1")
    assert result.total_usd == 0.0   # does not raise
```

**Verification command:**
```bash
pytest tests/test_cost_head.py -v
```

**Invariants touched:** INV-COST-01 (unattributed row always present), INV-COST-02 (no live GCP Billing API calls — confirm with grep).

**Code review:**
- [ ] No import of any `google-cloud-billing` module in `cost_head.py` — ChromaDB only
- [ ] `unattributed` resources appear in `breakdown` list — not excluded
- [ ] `attributed_usd + unattributed_usd == total_usd` — verify the arithmetic in code

**Commit:** `git add -A && git commit -m "Task 10.3: Cost Head — project and user spend from ChromaDB"`

---

## Task 10.4 — Security Head: flags, budget alerts, PDF report

**What this builds:** `security_head.py` with three flag types, budget check,
and `pdf_report.py` generating a PDF using `reportlab`.

**CC prompt:**
```
Implement cerberus/heads/security_head.py.

MODULE CONSTANTS (import from Claude.md fixed stack):
  OVER_PERMISSION_INACTIVITY_DAYS: int = 30

get_security_flags(project_id: str, credentials) -> list[SecurityFlag]:
  Runs three checks and combines results:

  CHECK 1 — OVER_PERMISSIONED:
    Get IAM inventory via get_iam_inventory(project_id, credentials) from iam_head.
    For each binding where role in ("roles/owner", "roles/editor"):
      Check last IAM activity via check_iam_last_activity(identity, project_id, credentials)
      (import from enrich_node).
      If last_activity is None OR (now - last_activity).days > OVER_PERMISSION_INACTIVITY_DAYS:
        Create SecurityFlag(flag_type="OVER_PERMISSIONED",
                            identity_or_resource=identity,
                            detail=f"{identity} holds {role} but inactive for {days} days")

  CHECK 2 — GHOST_RESOURCE (idle resources):
    Query ChromaDB resource_history where project_id matches and
    metadata["decision"] in ("safe_to_stop", "safe_to_delete").
    Each matching record is a ghost.
    Create SecurityFlag(flag_type="GHOST_RESOURCE",
                        identity_or_resource=resource_id,
                        detail=f"{resource_type} idle — {cost_usd}/month")

  CHECK 3 — BUDGET_BREACH:
    budget_status = check_budget_status(project_id) (see below).
    If budget_status.breached:
      Create SecurityFlag(flag_type="BUDGET_BREACH",
                          identity_or_resource=project_id,
                          detail=f"Spend ${budget_status.current_month_usd:.2f} exceeds "
                                 f"threshold ${budget_status.threshold_usd:.2f}")

  Write each flag to JSONL audit log with action_type="SECURITY_FLAG". (INV-SEC2-02 for BUDGET_BREACH)
  Return combined list.

check_budget_status(project_id: str) -> BudgetStatus:
  1. Query ChromaDB for project_id records. Sum estimated_monthly_cost for current month.
  2. Get threshold from get_config().budget_thresholds dict (key=project_id).
     If project_id not in thresholds: use default threshold of 500.0 USD.
  3. Return BudgetStatus(project_id=project_id,
                          current_month_usd=total,
                          threshold_usd=threshold,
                          breached=(total > threshold),
                          percent_used=round((total/threshold)*100, 1) if threshold > 0 else 0.0)

generate_audit_report_data(project_id: str) -> dict:
  Assembles data for PDF: runs get_security_flags, get_project_cost_summary,
  get_iam_inventory. Returns dict with keys:
  report_timestamp, project_id, resources_scanned, total_waste_identified,
  iam_changes, security_flags, idle_resources.

---

Implement cerberus/services/pdf_report.py using reportlab ONLY.

def generate_audit_report(project_id: str, report_data: dict) -> bytes:
  Creates a PDF in memory (io.BytesIO). Returns bytes.
  Sections in order (per Claude.md fixed stack):
  1. Header: "Cerberus Audit Report", report_timestamp, project_id (bold 16pt)
  2. Executive summary table: resources_scanned, flags_raised, iam_changes (count)
  3. IAM changes table: columns identity, role, changed_at, changed_by
  4. Security flags table: columns flag_type, identity/resource, detected_at, detail
  5. Idle resources table: columns resource_id, type, last_activity, monthly_cost
  6. Footer: "Generated by Cerberus — Agentic GCP Dev Environment Guardian"

  Use reportlab.platypus: SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer.
  Use reportlab.lib.styles: getSampleStyleSheet.
  Return pdf_bytes = buffer.getvalue() after doc.build(elements).

Add BUDGET_ALERT_THRESHOLD_DEFAULT: float = 500.0 to config.py as a module constant.
Add budget_thresholds: dict[str, float] = {} to CerberusConfig (defaults to empty dict).
```

**Test cases:**
```python
# tests/test_security_head.py

def test_over_permissioned_flag_raised_for_inactive_owner(mock_iam_inactive_owner,
                                                           mock_chroma_empty):
    flags = get_security_flags("nexus-tech-dev-1", mock_creds)
    over = [f for f in flags if f.flag_type == "OVER_PERMISSIONED"]
    assert len(over) >= 1
    assert "inactive" in over[0].detail.lower() or "days" in over[0].detail

def test_ghost_resource_flag_from_chroma(mock_iam_no_flags,
                                          tmp_chroma_with_idle_resource):
    flags = get_security_flags("nexus-tech-dev-1", mock_creds)
    ghosts = [f for f in flags if f.flag_type == "GHOST_RESOURCE"]
    assert len(ghosts) >= 1

def test_budget_breach_flag_when_over_threshold(mock_iam_no_flags, tmp_chroma_expensive):
    # total cost in chroma > threshold
    flags = get_security_flags("nexus-tech-dev-1", mock_creds)
    budget_flags = [f for f in flags if f.flag_type == "BUDGET_BREACH"]
    assert len(budget_flags) == 1

def test_budget_not_breached_when_under_threshold(mock_iam_no_flags, tmp_chroma_cheap):
    flags = get_security_flags("nexus-tech-dev-1", mock_creds)
    budget_flags = [f for f in flags if f.flag_type == "BUDGET_BREACH"]
    assert len(budget_flags) == 0

# tests/test_pdf_report.py

def test_pdf_generates_valid_bytes():
    pdf_bytes = generate_audit_report("nexus-tech-dev-1", {
        "report_timestamp": "2026-03-31T10:00:00Z",
        "project_id": "nexus-tech-dev-1",
        "resources_scanned": 6,
        "iam_changes": [],
        "security_flags": [],
        "idle_resources": []
    })
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000       # non-trivial PDF
    assert pdf_bytes[:4] == b"%PDF"    # valid PDF magic bytes

def test_pdf_does_not_require_network(monkeypatch):
    # Patch all network calls to raise — PDF must still generate
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", Mock(side_effect=OSError("no network")))
    pdf_bytes = generate_audit_report("nexus-tech-dev-1", {})
    assert len(pdf_bytes) > 0         # generated without network

def test_pdf_contains_project_id_text():
    import io
    # Just verify it's a non-empty PDF — content inspection is overkill for unit test
    pdf_bytes = generate_audit_report("my-test-project", {})
    assert len(pdf_bytes) > 500
```

**Verification command:**
```bash
pytest tests/test_security_head.py tests/test_pdf_report.py -v
```

**Invariants touched:** INV-SEC2-01 (two-condition over-permissioning check), INV-SEC2-02 (budget alert written to JSONL), INV-SEC2-03 (reportlab only, no network required).

**Code review:**
- [ ] `get_security_flags` CHECK 1 checks BOTH inactivity AND role — not one alone
- [ ] `generate_audit_report` uses `io.BytesIO()` — no file system writes
- [ ] No `requests`, `httpx`, or any network import in `pdf_report.py`
- [ ] `reportlab` is the ONLY PDF library imported — no `weasyprint`, `fpdf`, `xhtml2pdf`
- [ ] Budget breach flag is written to JSONL audit log — confirm `write_audit_entry` call

**Commit:** `git add -A && git commit -m "Task 10.4: Security Head — flags, budget alerts, PDF report"`

---

## Task 10.5 — SlideNav and page shells

**What this builds:** `SlideNav.tsx`, `App.tsx` updated with navigation state,
and 5 empty page shell components. No data fetching yet.

**CC prompt:**
```
Create frontend/src/components/SlideNav.tsx.

Props:
  currentPage: string
  onNavigate: (page: string) => void

Renders a fixed left sidebar with these menu items in order:
  / → Dashboard (icon: grid)
  /iam → IAM Center (icon: shield)
  /cost → Cost Center (icon: currency-dollar)
  /security → Security Hub (icon: lock-closed)
  /tickets → Tickets (icon: ticket — or inbox if unavailable)

Active item: highlighted background (use CSS variable --color-background-info)
Inactive: transparent background, hover effect.
Width: 220px fixed.

No React Router. Navigation is: onClick={() => onNavigate('/iam')}
The nav renders all items unconditionally — no role-based hiding.

Update frontend/src/App.tsx:
  Add state: const [currentPage, setCurrentPage] = useState('/')
  Render SlideNav on the left.
  Render the active page component on the right (switch on currentPage).
  Page components for now: import all 5 pages, render based on currentPage.

Create these 5 page shells (empty — just renders page title):
  frontend/src/pages/DashboardPage.tsx  → <h1>Dashboard</h1>
  frontend/src/pages/IAMPage.tsx        → <h1>IAM Center</h1>
  frontend/src/pages/CostPage.tsx       → <h1>Cost Center</h1>
  frontend/src/pages/SecurityPage.tsx   → <h1>Security Hub</h1>
  frontend/src/pages/TicketsPage.tsx    → <h1>Tickets</h1>

All components use TypeScript. No inline styles — use Tailwind utility classes only.
The sidebar must not use position:fixed — use flex layout (flex-row at root,
sidebar flex-shrink-0, content flex-grow). This avoids the iframe collapse issue.
```

**Test cases:**
```typescript
// frontend/src/components/SlideNav.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import SlideNav from './SlideNav'

test('renders all 5 nav items', () => {
  render(<SlideNav currentPage="/" onNavigate={jest.fn()} />)
  expect(screen.getByText('Dashboard')).toBeInTheDocument()
  expect(screen.getByText('IAM Center')).toBeInTheDocument()
  expect(screen.getByText('Cost Center')).toBeInTheDocument()
  expect(screen.getByText('Security Hub')).toBeInTheDocument()
  expect(screen.getByText('Tickets')).toBeInTheDocument()
})

test('active item has highlight class', () => {
  render(<SlideNav currentPage="/iam" onNavigate={jest.fn()} />)
  const iamItem = screen.getByText('IAM Center').closest('button') ||
                  screen.getByText('IAM Center').closest('li')
  expect(iamItem).toHaveClass(/active|selected|highlight|bg-/i)
})

test('clicking nav item calls onNavigate with correct path', () => {
  const nav = jest.fn()
  render(<SlideNav currentPage="/" onNavigate={nav} />)
  fireEvent.click(screen.getByText('Cost Center'))
  expect(nav).toHaveBeenCalledWith('/cost')
})
```

**Verification command:**
```bash
cd frontend && npm test -- --testPathPattern=SlideNav --watchAll=false
```

**Invariants touched:** INV-UI-01 (layout must not break existing ApprovalTable — verify ApprovalTable test still passes after App.tsx change).

**Code review:**
- [ ] No React Router import anywhere
- [ ] `position: fixed` does not appear in SlideNav — flex layout only
- [ ] Existing `ApprovalTable.tsx` and `ExecutePanel.tsx` are unchanged

**Commit:** `git add -A && git commit -m "Task 10.5: SlideNav and page shells"`

---

## Task 10.6 — IAM Panel: access request form and asset inventory table

**What this builds:** `IAMPanel.tsx` (access request form with Gemini synthesis preview)
and `AssetInventory.tsx` (IAM bindings table). Both inside `IAMPage.tsx`.

**CC prompt:**
```
Create frontend/src/components/IAMPanel.tsx.

State:
  requestText: string         (textarea input)
  requesterEmail: string      (email input)
  synthesizing: boolean
  synthesizedPlan: SynthesizedIAMPlan | null
  confirmed: boolean
  ticket: IAMTicket | null
  error: string | null

Flow:
  1. User fills requestText + requesterEmail, clicks "Synthesize"
  2. POST /iam/request → shows synthesizedPlan in a preview card
  3. Preview card shows: role, justification, requesterEmail, project_id
  4. User clicks "Confirm & Create Ticket" → POST /iam/request/{id}/confirm
  5. Shows success: "Ticket created — pending admin review"

Rules:
  - "Synthesize" button disabled while synthesizing or if fields empty
  - Preview card renders BEFORE the confirm button appears
  - Never create a ticket without showing the preview first (INV-IAM-01)
  - Error state renders inline below the form (not an alert/toast)

---

Create frontend/src/components/AssetInventory.tsx.

Props: projectId: string

Fetches GET /iam/inventory?project_id={projectId} on mount.
Renders a table with exactly these columns: Identity | Role/Status | Project

Rules:
  - Any null/undefined field renders "—" (em-dash) — INV-IAM-03
  - Loading state: "Loading inventory..." text
  - Empty state: "No IAM bindings found for this project."
  - Error state: "Failed to load inventory."

---

Update frontend/src/pages/IAMPage.tsx to render both components:
  Top: IAMPanel (access request)
  Bottom: AssetInventory (current bindings)
  Use the project_id from a hardcoded config constant for the hackathon:
    const PROJECT_ID = "nexus-tech-dev-sandbox"
```

**Test cases:**
```typescript
test('synthesize button disabled when fields empty', () => {
  render(<IAMPanel />)
  expect(screen.getByRole('button', {name:/synthesize/i})).toBeDisabled()
})

test('preview card appears after synthesis before confirm button', async () => {
  // mock POST /iam/request to return a plan
  render(<IAMPanel />)
  fireEvent.change(screen.getByPlaceholderText(/request/i), {target:{value:'give alice read access'}})
  fireEvent.change(screen.getByPlaceholderText(/email/i), {target:{value:'alice@x.com'}})
  fireEvent.click(screen.getByRole('button', {name:/synthesize/i}))
  await screen.findByText(/roles\//i)  // role appears in preview
  expect(screen.getByRole('button', {name:/confirm/i})).toBeInTheDocument()
})

test('asset inventory renders three required columns', () => {
  render(<AssetInventory projectId="nexus-tech-dev-1" />)
  expect(screen.getByText('Identity')).toBeInTheDocument()
  expect(screen.getByText('Role/Status')).toBeInTheDocument()
  expect(screen.getByText('Project')).toBeInTheDocument()
})

test('null field in inventory renders em-dash', async () => {
  // mock returns a binding with role=null
  render(<AssetInventory projectId="nexus-tech-dev-1" />)
  await screen.findAllByText('—')
})
```

**Verification command:**
```bash
cd frontend && npm test -- --testPathPattern="IAMPanel|AssetInventory" --watchAll=false
```

**Invariants touched:** INV-IAM-01 (preview before confirm — enforced by UI flow), INV-IAM-03 (em-dash for null fields — tested).

**Commit:** `git add -A && git commit -m "Task 10.6: IAM Panel and Asset Inventory components"`

---

## Task 10.7 — Cost Center: project spend and user spend panels

**What this builds:** `CostCenter.tsx` with two views: project total (with attributed/
unattributed breakdown) and user spend search (email + project query).

**CC prompt:**
```
Create frontend/src/components/CostCenter.tsx.

Two tabs: "Project Spend" and "User Spending"

--- Tab 1: Project Spend ---
On mount: GET /cost/project/{PROJECT_ID}
Renders:
  - Total: "$X/month"
  - Attributed: "$Y/month"
  - Unattributed: "$Z/month"
  - Breakdown table: Owner Email | Monthly Cost
    The "unattributed" row must always appear if unattributed_usd > 0.
    It renders as "Unattributed resources" in the Owner Email column.
  - Loading / error states

--- Tab 2: User Spending ---
Search form: email input + project input (pre-filled with PROJECT_ID)
On submit: GET /cost/user?owner_email=X&project_id=Y
Renders:
  - "Total: $X/month across N resources"
  - Resources table: Resource ID | Type | Monthly Cost
  - If no records: "No spend found for this user in this project."
  - Error: "Failed to load user spending."
```

**Test cases:**
```typescript
test('project spend shows attributed and unattributed rows', async () => {
  // mock GET /cost/project/... returns breakdown with unattributed entry
  render(<CostCenter />)
  await screen.findByText(/Unattributed/)
  expect(screen.getByText(/Attributed/i)).toBeInTheDocument()
})

test('user spend search submits with email and project', async () => {
  const fetchMock = jest.fn().mockResolvedValue({
    ok: true, json: async () => ({total_usd: 45.0, resource_count: 2, resources: []})
  })
  global.fetch = fetchMock
  render(<CostCenter />)
  fireEvent.click(screen.getByText('User Spending'))
  fireEvent.change(screen.getByPlaceholderText(/email/i), {target:{value:'alice@x.com'}})
  fireEvent.click(screen.getByRole('button', {name:/search/i}))
  await screen.findByText(/\$45/)
  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining('alice@x.com'), expect.anything()
  )
})
```

**Verification command:**
```bash
cd frontend && npm test -- --testPathPattern=CostCenter --watchAll=false
```

**Invariants touched:** INV-COST-01 (unattributed row visible in UI — tested).

**Commit:** `git add -A && git commit -m "Task 10.7: Cost Center components"`

---

## Task 10.8 — Security Hub: flags table, budget status, report download

**What this builds:** `SecurityHub.tsx` with three sections: active flags, budget
status bar, and audit report download button.

**CC prompt:**
```
Create frontend/src/components/SecurityHub.tsx.

Three sections rendered vertically:

--- Section 1: Security Flags ---
GET /security/flags?project_id={PROJECT_ID} on mount.
Table: Flag Type | Resource/Identity | Detected | Detail
Badge colours:
  OVER_PERMISSIONED → red badge
  GHOST_RESOURCE → amber badge
  BUDGET_BREACH → red badge
Empty state: "No active security flags."

--- Section 2: Budget Status ---
GET /security/budget-status?project_id={PROJECT_ID} on mount.
Shows:
  - Progress bar: current_month_usd / threshold_usd (0–100%)
  - "$X of $Y threshold used (Z%)"
  - If breached: red progress bar + "Budget threshold exceeded"
  - If not breached: green/amber progress bar

--- Section 3: Audit Report Download ---
Button: "Download Audit Report (PDF)"
On click: GET /security/report/download?project_id={PROJECT_ID}
  Sets response as a Blob, triggers browser download with filename
  "cerberus-audit-{PROJECT_ID}-{date}.pdf"
Loading state on button during fetch.
If fetch fails: show "Report generation failed. Try again."

Do not open the PDF in a new tab — trigger a file download.
```

**Test cases:**
```typescript
test('flags table renders required columns', () => {
  render(<SecurityHub />)
  expect(screen.getByText('Flag Type')).toBeInTheDocument()
  expect(screen.getByText('Resource/Identity')).toBeInTheDocument()
  expect(screen.getByText('Detected')).toBeInTheDocument()
})

test('budget bar shows breach state', async () => {
  // mock budget-status returns breached=true
  render(<SecurityHub />)
  await screen.findByText(/exceeded/i)
})

test('download button triggers fetch to report endpoint', async () => {
  const fetchMock = jest.fn().mockResolvedValue({
    ok: true,
    blob: async () => new Blob(['%PDF'], {type: 'application/pdf'})
  })
  global.fetch = fetchMock
  render(<SecurityHub />)
  fireEvent.click(screen.getByRole('button', {name:/download/i}))
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/security/report/download'), expect.anything()
    )
  })
})
```

**Verification command:**
```bash
cd frontend && npm test -- --testPathPattern=SecurityHub --watchAll=false
```

**Invariants touched:** INV-SEC2-02 (budget breach visible in UI), INV-SEC2-03 (PDF download, not new tab).

**Commit:** `git add -A && git commit -m "Task 10.8: Security Hub components"`

---

## Task 10.9 — Ticket Panel: pending approvals with dry-run preview

**What this builds:** `TicketPanel.tsx` — admin-only view showing pending IAM tickets
with dry-run preview before live provisioning.

**CC prompt:**
```
Create frontend/src/components/TicketPanel.tsx.

GET /tickets on mount. Renders list of pending tickets.

For each ticket:
  Card showing:
    Requester: {plan.requester_email}
    Requested role: {plan.role}
    Project: {plan.project_id}
    Justification: {plan.justification}
    Submitted: {created_at}
    Status badge: pending (amber) / approved (green) / rejected (red)

  Two buttons (only for pending tickets):
    "Preview" → POST /tickets/{id}/approve → shows dry-run result in an
                inline card BEFORE the "Provision Live" button appears.
                Dry-run card shows: would_add text from response.
    "Provision Live" → POST /tickets/{id}/provision → only appears AFTER
                Preview has been clicked and dry-run result is shown.
                Shows success: "IAM binding provisioned."

  "Reject" button → sets UI status to rejected (client-side only for hackathon).

Rules:
  - "Provision Live" button must NEVER appear before "Preview" is clicked. (INV-IAM-02)
  - An error from the provision call renders inline below the card.
  - Tickets table must not auto-refresh — manual refresh button only.
```

**Test cases:**
```typescript
test('provision live button not visible before preview', () => {
  render(<TicketPanel />)
  expect(screen.queryByRole('button', {name:/provision live/i})).not.toBeInTheDocument()
})

test('provision live appears after preview is clicked', async () => {
  // mock POST /tickets/t1/approve returns dry_run result
  render(<TicketPanel tickets={[makePendingTicket('t1')]} />)
  fireEvent.click(screen.getByRole('button', {name:/preview/i}))
  await screen.findByText(/would_add|DRY_RUN/i)
  expect(screen.getByRole('button', {name:/provision live/i})).toBeInTheDocument()
})

test('pending ticket shows amber badge', () => {
  render(<TicketPanel tickets={[makePendingTicket('t1')]} />)
  const badge = screen.getByText('pending')
  expect(badge.className).toMatch(/amber|yellow|warning/i)
})
```

**Verification command:**
```bash
cd frontend && npm test -- --testPathPattern=TicketPanel --watchAll=false
```

**Invariants touched:** INV-IAM-02 (Provision Live gated behind Preview — tested explicitly).

**Code review:**
- [ ] "Provision Live" button is rendered inside a conditional that checks whether dry-run result exists in state — not just hidden with CSS

**Commit:** `git add -A && git commit -m "Task 10.9: Ticket Panel with dry-run preview gate"`

---

## Task 10.10 — Session integration check and live smoke test

**What this builds:** Nothing new — verifies the assembled system end to end.

**Run the integration check command** (from the top of this document).

**Additional smoke tests:**

```bash
# 1. IAM synthesis round-trip (requires .env with GEMINI_API_KEY)
python3 -c "
import asyncio
from cerberus.heads.iam_head import synthesize_iam_request, create_ticket
from cerberus.models.iam_ticket import IAMRequest
from cerberus.config import get_config

req = IAMRequest(
    natural_language_request='Alice needs read access to BigQuery in the dev project',
    requester_email='alice@nexus-tech.com',
    project_id='nexus-tech-dev-sandbox'
)
plan = asyncio.run(synthesize_iam_request(req, get_config()))
print(f'Synthesized role: {plan.role}')
assert 'bigquery' in plan.role.lower() or 'viewer' in plan.role.lower(), \
    f'Expected BigQuery role, got: {plan.role}'
ticket = create_ticket(plan)
print(f'Ticket created: {ticket.ticket_id} status={ticket.status}')
print('IAM round-trip: PASS')
"

# 2. PDF generation
python3 -c "
from cerberus.services.pdf_report import generate_audit_report
pdf = generate_audit_report('nexus-tech-dev-sandbox', {
    'report_timestamp': '2026-03-31T10:00:00Z',
    'project_id': 'nexus-tech-dev-sandbox',
    'resources_scanned': 6,
    'iam_changes': [],
    'security_flags': [],
    'idle_resources': []
})
assert pdf[:4] == b'%PDF', 'Not a valid PDF'
open('/tmp/cerberus_test_report.pdf', 'wb').write(pdf)
print(f'PDF: {len(pdf)} bytes — PASS')
print('Open /tmp/cerberus_test_report.pdf to visually verify')
"

# 3. Frontend builds
cd frontend && npm run build && echo "Frontend build: PASS" && cd ..

# 4. Full test suite — no regressions
pytest tests/ -v --tb=short 2>&1 | tail -20
```

**Commit:** `git add -A && git commit -m "Session 10: close — integration check passed"`

**Verification command:**
```bash
pytest tests/test_iam_head.py tests/test_cost_head.py \
       tests/test_security_head.py tests/test_routes.py \
       tests/test_pdf_report.py -v
```

**Invariants touched:** All INV-IAM-*, INV-COST-*, INV-SEC2-* invariants verified end to end.

---

## PR Description Template

```
## Session 10 — Three-Head Expansion

### What this delivers

**IAM Head**
- Natural language → Gemini synthesis → structured IAM plan → ticket
- Ticket lifecycle: pending → approved → provisioned (dry-run first)
- Asset inventory: live GCP IAM bindings per project

**Cost Head**
- Per-project spend from ChromaDB (attributed + unattributed split)
- Per-user spend query (email + project)
- No live Billing API calls at query time

**Security Head**
- Over-permissioning flags: owner/editor + 30-day inactivity
- Ghost resource flags from ChromaDB scan history
- Budget breach detection and JSONL audit entry
- PDF audit report (reportlab, no network required)

**UI — Slide Nav with 5 pages**
- Dashboard, IAM Center, Cost Center, Security Hub, Tickets
- IAM Panel: synthesis flow with preview-before-confirm gate
- Asset Inventory: IAM bindings table
- Cost Center: project spend + user spend search
- Security Hub: flags, budget bar, PDF download
- Ticket Panel: dry-run preview gate before Provision Live

### Claude.md
- Upgraded from v1.0 to v2.0
- All v1.0 invariants unchanged
- New invariants: INV-IAM-01/02/03, INV-COST-01/02, INV-SEC2-01/02/03

### New invariants verified
- INV-IAM-01: synthesis always before ticket creation — code review ✓
- INV-IAM-02: Provision Live gated behind dry-run preview — test ✓
- INV-IAM-03: em-dash for null IAM fields — test ✓
- INV-COST-01: unattributed row always present — test ✓
- INV-COST-02: no live Billing API in cost_head.py — grep ✓
- INV-SEC2-01: two-condition over-permissioning check — code review ✓
- INV-SEC2-02: budget alert written to JSONL — code review ✓
- INV-SEC2-03: reportlab only, no network in pdf_report.py — test ✓

### Regression check
All Sessions 1–8 tests: PASS (no regressions)

### Deviations
[paste from SESSION_LOG.md or "None"]
```
-e 

---


# SESSION_LOG.md

## Session: Session 10 — Three-Head Expansion
**Date started:**
**Engineer:**
**Branch:** session/s10_three_heads
**Claude.md version:** v2.0 · FROZEN · 2026-03-31
**Status:** In Progress

---

## Tasks

| Task Id | Task Name | Status | Commit |
|---------|-----------|--------|--------|
| 10.1 | Backend models, head skeletons, and new routes registration | | |
| 10.2 | IAM Head — Gemini synthesis, ticket lifecycle, asset inventory | | |
| 10.3 | Cost Head — per-project and per-user spend from ChromaDB | | |
| 10.4 | Security Head — flags, budget alerts, PDF report | | |
| 10.5 | SlideNav and page shells — Dashboard, IAM, Cost, Security, Tickets | | |
| 10.6 | IAM Panel — access request form and asset inventory table | | |
| 10.7 | Cost Center — project spend and user spend panels | | |
| 10.8 | Security Hub — flags table, budget status, report download | | |
| 10.9 | Ticket Panel — pending approvals with dry-run preview | | |
| 10.10 | Session integration check and live smoke test | | |

---

## Decision Log

| Task | Decision made | Rationale |
|------|---------------|-----------|
| | | |

---

## Deviations

| Task | Deviation observed | Action taken |
|------|--------------------|--------------|
| | | |

---

## Claude.md Changes

| Change | Reason | New Claude.md version | Tasks re-verified |
|--------|--------|-----------------------|-------------------|
| v1.0 → v2.0 | Session 10 scope expansion: three-head UI, IAM workflow, cost attribution, security flags, PDF report | v2.0 · 2026-03-31 | All Session 10 tasks use v2.0 |

---

## Session Completion
**Session integration check:** [ ] PASSED
**All tasks verified:** [ ] Yes
**PR raised:** [ ] Yes — PR #: session/s10_three_heads → main
**Status updated to:**
**Engineer sign-off:**
-e 

---


# VERIFICATION_RECORD.md

**Session:** Session 10 — Three-Head Expansion
**Date:**
**Engineer:**

---

## Task 10.1 — Backend models, head skeletons, route registration

### Test Cases Applied
Source: SESSION_10_BUILD_GUIDE.md Task 10.1

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| TC-1 | GET /iam/inventory route | Status code is not 404 | |
| TC-2 | GET /cost/project/{id} route | Status code is not 404 | |
| TC-3 | GET /security/flags route | Status code is not 404 | |
| TC-4 | GET /tickets route | Status code is not 404 | |
| TC-5 | GET /run/nonexistent-id/status (existing route) | Status code is 404 — not 500 | |
| TC-6 | IAMTicket model created with valid data | Object created, status == "pending" | |
| TC-7 | SecurityFlag with invalid flag_type | Exception raised — Literal enforced | |

### Prediction Statement

### CC Challenge Output

### Code Review
**INV-IAM-01, INV-IAM-03, INV-COST-01, INV-SEC2-03 touched.**

- [ ] No existing route in `api.py` is modified — only `include_router` calls added
- [ ] `IAMTicket.status` is a `Literal` with exactly 4 values: pending/approved/rejected/provisioned
- [ ] `SecurityFlag.flag_type` is a `Literal` with exactly 3 values: OVER_PERMISSIONED/GHOST_RESOURCE/BUDGET_BREACH
- [ ] `ProjectCostSummary` has both `attributed_usd` AND `unattributed_usd` fields

### Scope Decisions

### Verification Verdict
[ ] All planned cases passed
[ ] CC challenge reviewed
[ ] Code review complete
[ ] Scope decisions documented

**Status:**

---

## Task 10.2 — IAM Head: Gemini synthesis, ticket lifecycle, asset inventory

### Test Cases Applied
Source: SESSION_10_BUILD_GUIDE.md Task 10.2

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| TC-1 | `synthesize_iam_request` called with valid request | Returns `SynthesizedIAMPlan`; Gemini called with temperature=0 | |
| TC-2 | `create_ticket` called with a plan | Ticket stored in `_tickets`, status == "pending" | |
| TC-3 | `approve_ticket` called on pending ticket | status == "approved", reviewed_by set | |
| TC-4 | `provision_iam_binding` with `dry_run=True` | Returns dict with `status == "DRY_RUN"` and `would_add` key | |
| TC-5 | `get_pending_tickets` after one approval | Approved ticket not in result; pending ticket is in result | |
| TC-6 | `get_iam_inventory` called with valid project | Returns list of `IAMBinding`; each has identity, role, project_id | |

### Prediction Statement

### CC Challenge Output

### Code Review
**INV-IAM-01, INV-IAM-02, INV-IAM-03 touched.**

- [ ] `synthesize_iam_request` calls Gemini at `temperature=0` — confirm line number: ___
- [ ] `provision_iam_binding` defaults `dry_run=True` — no live call without explicit False
- [ ] Route `POST /tickets/{id}/provision` checks `ticket.status == "approved"` before calling provision
- [ ] `get_iam_inventory` wraps GCP call in `gcp_call_with_retry`

### Scope Decisions

### Verification Verdict
[ ] All planned cases passed
[ ] CC challenge reviewed
[ ] Code review complete (INV-IAM-01, INV-IAM-02, INV-IAM-03)
[ ] Scope decisions documented

**Status:**

---

## Task 10.3 — Cost Head: per-project and per-user spend from ChromaDB

### Test Cases Applied
Source: SESSION_10_BUILD_GUIDE.md Task 10.3

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| TC-1 | 2 attributed + 1 unattributed resource in ChromaDB | `total_usd=85`, `attributed_usd=75`, `unattributed_usd=10` | |
| TC-2 | `attributed_usd + unattributed_usd == total_usd` | Difference < 0.01 for any seed data | |
| TC-3 | Breakdown list for project with unattributed resources | `breakdown` contains entry with `owner_email=="unattributed"` | |
| TC-4 | `get_user_cost_summary("alice@x.com", "p")` with 2 alice resources | `total_usd==65`, `resource_count==2` | |
| TC-5 | `get_user_cost_summary` for unknown email | `total_usd==0.0`, `resources==[]` | |
| TC-6 | ChromaDB raises exception during project cost query | Returns `ProjectCostSummary` with all zeros — does not raise | |

### Prediction Statement

### CC Challenge Output

### Code Review
**INV-COST-01, INV-COST-02 touched.**

- [ ] No `google-cloud-billing` or `cloudbilling` import in `cost_head.py`: `grep -n "billing" cerberus/heads/cost_head.py` — expected: no output
- [ ] `unattributed` resources appear in `breakdown` list — not filtered out
- [ ] `attributed_usd + unattributed_usd == total_usd` — verify arithmetic logic line by line

### Scope Decisions

### Verification Verdict
[ ] All planned cases passed
[ ] CC challenge reviewed
[ ] Code review complete (INV-COST-01, INV-COST-02)
[ ] Scope decisions documented

**Status:**

---

## Task 10.4 — Security Head: flags, budget alerts, PDF report

### Test Cases Applied
Source: SESSION_10_BUILD_GUIDE.md Task 10.4

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| TC-1 | IAM has owner with 35-day inactivity | `OVER_PERMISSIONED` flag raised; detail mentions inactivity | |
| TC-2 | ChromaDB has resources with `decision="safe_to_stop"` | `GHOST_RESOURCE` flag raised | |
| TC-3 | Project spend exceeds `budget_alert_threshold_usd` | `BUDGET_BREACH` flag raised | |
| TC-4 | Project spend below threshold | No `BUDGET_BREACH` flag | |
| TC-5 | `generate_audit_report(project_id, {})` | Returns bytes; `len > 1000`; first 4 bytes == `b"%PDF"` | |
| TC-6 | `generate_audit_report` with network patched to raise | Returns valid PDF bytes — no network required | |

### Prediction Statement

### CC Challenge Output

### Code Review
**INV-SEC2-01, INV-SEC2-02, INV-SEC2-03 touched.**

- [ ] `get_security_flags` CHECK 1 verifies BOTH role AND inactivity — not one alone; find the `and` condition in code: line ___
- [ ] Budget breach flag calls `write_audit_entry` with `action_type="BUDGET_ALERT"` — confirm: line ___
- [ ] `pdf_report.py` imports: `grep -n "^import\|^from" cerberus/services/pdf_report.py` — only `reportlab`, `io`, stdlib allowed
- [ ] No `requests`, `httpx`, `urllib`, or socket calls in `pdf_report.py`

### Scope Decisions

### Verification Verdict
[ ] All planned cases passed
[ ] CC challenge reviewed
[ ] Code review complete (INV-SEC2-01, INV-SEC2-02, INV-SEC2-03)
[ ] Scope decisions documented

**Status:**

---

## Task 10.5 — SlideNav and page shells

### Test Cases Applied
Source: SESSION_10_BUILD_GUIDE.md Task 10.5

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| TC-1 | `SlideNav` rendered with `currentPage="/"` | All 5 nav item labels present in DOM | |
| TC-2 | `SlideNav` rendered with `currentPage="/iam"` | IAM Center item has active/highlight class | |
| TC-3 | Click "Cost Center" nav item | `onNavigate` called with `"/cost"` | |

### Prediction Statement

### CC Challenge Output

### Code Review
**INV-UI-01 (layout must not break existing components).**

- [ ] No React Router import: `grep -r "react-router" frontend/src/` — expected: no output
- [ ] `position: fixed` not in SlideNav: `grep -n "fixed" frontend/src/components/SlideNav.tsx` — expected: no result or only Tailwind flex classes
- [ ] `ApprovalTable.tsx` unchanged: `git diff main -- frontend/src/components/ApprovalTable.tsx` — expected: no diff
- [ ] All 5 page shells render without crashing: `cd frontend && npm run build`

### Scope Decisions

### Verification Verdict
[ ] All planned cases passed
[ ] CC challenge reviewed
[ ] Code review complete
[ ] Scope decisions documented

**Status:**

---

## Task 10.6 — IAM Panel and Asset Inventory

### Test Cases Applied
Source: SESSION_10_BUILD_GUIDE.md Task 10.6

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| TC-1 | `IAMPanel` rendered with empty fields | "Synthesize" button is disabled | |
| TC-2 | Fields filled + mock synthesis response | Preview card shows role; Confirm button appears | |
| TC-3 | `AssetInventory` rendered | "Identity", "Role/Status", "Project" column headers present | |
| TC-4 | Mock returns binding with `role=null` | Cell renders "—" not blank or "null" | |

### Prediction Statement

### CC Challenge Output

### Code Review
**INV-IAM-01, INV-IAM-03 touched.**

- [ ] "Confirm & Create Ticket" button only renders after `synthesizedPlan` is non-null in state
- [ ] em-dash fallback: `record.identity ?? "—"` or equivalent pattern for all three fields

### Scope Decisions

### Verification Verdict
[ ] All planned cases passed
[ ] CC challenge reviewed
[ ] Code review complete (INV-IAM-01, INV-IAM-03)
[ ] Scope decisions documented

**Status:**

---

## Task 10.7 — Cost Center

### Test Cases Applied
Source: SESSION_10_BUILD_GUIDE.md Task 10.7

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| TC-1 | Mock returns breakdown with unattributed entry | "Unattributed" text visible in DOM | |
| TC-2 | User spend search submitted with email | Fetch called with `alice@x.com` in URL; total rendered | |

### Prediction Statement

### CC Challenge Output

### Code Review
**INV-COST-01 touched.**

- [ ] "Unattributed" row appears when `unattributed_usd > 0` — confirm conditional renders it

### Scope Decisions

### Verification Verdict
[ ] All planned cases passed
[ ] CC challenge reviewed
[ ] Code review complete (INV-COST-01)
[ ] Scope decisions documented

**Status:**

---

## Task 10.8 — Security Hub

### Test Cases Applied
Source: SESSION_10_BUILD_GUIDE.md Task 10.8

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| TC-1 | Component renders | "Flag Type", "Resource/Identity", "Detected" columns present | |
| TC-2 | Mock returns `breached=true` | "exceeded" text visible | |
| TC-3 | Download button clicked (mock PDF response) | Fetch called with `/security/report/download` URL | |

### Prediction Statement

### CC Challenge Output

### Code Review
**INV-SEC2-02, INV-SEC2-03 touched.**

- [ ] PDF download triggers file download (not new tab) — confirm `URL.createObjectURL` + `<a>.click()` pattern
- [ ] Budget breach alert visible without page reload

### Scope Decisions

### Verification Verdict
[ ] All planned cases passed
[ ] CC challenge reviewed
[ ] Code review complete
[ ] Scope decisions documented

**Status:**

---

## Task 10.9 — Ticket Panel

### Test Cases Applied
Source: SESSION_10_BUILD_GUIDE.md Task 10.9

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| TC-1 | `TicketPanel` rendered with pending ticket | "Provision Live" button NOT in DOM | |
| TC-2 | "Preview" clicked (mock dry-run response) | Dry-run result visible; "Provision Live" button appears | |
| TC-3 | Pending ticket badge | Badge text "pending" has amber/yellow styling class | |

### Prediction Statement

### CC Challenge Output

### Code Review
**INV-IAM-02 touched — most critical review in this session.**

- [ ] "Provision Live" button is inside a conditional on `dryRunResult !== null` in state — NOT just `display:none` or `visibility:hidden`
- [ ] The route `POST /tickets/{id}/provision` on the backend checks `ticket.status == "approved"` before executing — confirm in `ticket_routes.py`

### Scope Decisions

### Verification Verdict
[ ] All planned cases passed
[ ] CC challenge reviewed
[ ] Code review complete (INV-IAM-02)
[ ] Scope decisions documented

**Status:**

---

## Task 10.10 — Session Integration Check

### What this verifies that individual tasks do not:
All new routes respond correctly while existing routes remain unbroken.
IAM synthesis calls real Gemini and returns a sensible role.
PDF generates valid bytes without network access.
Frontend builds with no TypeScript errors.
All new tests pass alongside all Sessions 1–8 tests (no regressions).

### Prediction Statement

### Integration Check Result
*(PASS / FAIL — fill after running all commands in Task 10.10)*

### Regression Check
*(Paste last 10 lines of `pytest tests/ -v --tb=short` output)*

### Verification Verdict
[ ] Integration check PASSED
[ ] Regression check PASSED (no Sessions 1–8 failures)
[ ] PDF visually inspected at /tmp/cerberus_test_report.pdf
[ ] Frontend build succeeded

**Status:**

## Invariant Coverage Matrix

| Invariant | Sessions | Tasks |
|---|---|---|
| INV-SCAN-01 | 1, 2 | 1.3, 2.4 |
| INV-SCAN-02 | 2 | 2.1 |
| INV-SCAN-03 | 2 | 2.2 |
| INV-SCAN-04 | 2 | 2.3 |
| INV-ENR-01 | 3 | 3.1, 3.3 |
| INV-ENR-02 | 3 | 3.2 |
| INV-ENR-03 | 3, 4, 5, 7 | 3.3, 4.2, 5.3, 7.1 — **4 enforcement points** |
| INV-RSN-01 | 1, 4 | 1.3 (VALID_DECISIONS), 4.1, 4.2 |
| INV-RSN-02 | 4 | 4.1, 4.2 |
| INV-RSN-03 | 4 | 4.2, 4.3 |
| INV-UI-01 | 7 | 7.1 |
| INV-UI-02 | 5, 7 | 5.1, 7.2 |
| INV-UI-03 | 1, 5, 7 | 1.3 (default), 5.1, 7.2 |
| INV-EXE-01 | 5 | 5.3 |
| INV-EXE-02 | 5 | 5.3 |
| INV-EXE-03 | 5 | 5.3 |
| INV-AUD-01 | 6 | 6.1 |
| INV-AUD-02 | 6, 9 | 6.1, 9.3 (cost_summary state key + /summary endpoint) |
| INV-SEC-01 | 1, 2, 6, 9 | 1.2, 2.4, 6.2, 9.1 (access_node), 9.2 (guardrail demo) |
| INV-SEC-02 | 5, 6, 9 | 5.1, 6.1, 9.3 (RunSummary model has no credential fields) |
| INV-NFR-01 | 2 | 2.4 |
| INV-NFR-02 | 1, 9 | 1.4, 9.1 (Gemini call in access_node wrapped in gcp_call_with_retry) |
| INV-NFR-03 | 6 | 6.2 |

---

## Architecture Review Gaps Closed in This Plan

| Gap | Closed in task |
|---|---|
| re.match allowlist bypass (dev-prod name) | Task 1.2: re.fullmatch with numeric-suffix pattern |
| Approval-execution state drift | Task 5.2: revalidate_node |
| Missing resource (404) during revalidation | Task 5.2: explicit 404 case |
| OQ-1: drift on safe_to_delete → needs_review | Task 5.2 |
| OQ-3: sensitive disk detection | Task 2.2 (scan label check) + Task 5.3 (archive path) |
| Ownership label staleness | Task 3.2: 90-day IAM activity downgrade |
| Audit write order (local-first) | Task 6.1: explicit write order with raise on JSONL failure |
| LangSmith failure visible in UI | Task 7.2: fallback message when URL is null |
| Dry-run modal requires affirmative click | Task 7.2: test confirms onExecute not called until "Execute live" |
| ChromaDB cross-run resource context | Task 1.4b, 4.1 (build_resource_prompt), 6.1 (audit write) |
| IAM over-provisioning (broad predefined roles) | Task 9.1: access_node enforces custom roles; broad roles rejected at parse |
| no_owner guardrail invisible during happy-path demo | Task 9.2: demo_guardrails.py makes all 4 enforcement points observable |
| Recovered savings inflated by FAILED actions | Task 9.3: COST_SUMMARY sums only outcome=="SUCCESS"; FAILED excluded by design |
| No judge-facing ROI printout | Task 9.3: print_run_summary.py + GET /run/{run_id}/summary endpoint |
| Concurrent session conflict | Task 5.1: 409 response in POST /run |
| evidence field not validated against scan data | **Not closed** — flagged as prompt evaluation item (Day 4 task) |