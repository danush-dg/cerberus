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
| INV-AUD-02 | 6 | 6.1 |
| INV-SEC-01 | 1, 2, 6 | 1.2, 2.4, 6.2 |
| INV-SEC-02 | 5, 6 | 5.1, 6.1 |
| INV-NFR-01 | 2 | 2.4 |
| INV-NFR-02 | 1 | 1.4 |
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
| Concurrent session conflict | Task 5.1: 409 response in POST /run |
| evidence field not validated against scan data | **Not closed** — flagged as prompt evaluation item (Day 4 task) |