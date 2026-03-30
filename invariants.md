# INVARIANTS.md — Cerberus GCP Dev Environment Guardian

**Version:** 1.0
**Status:** Draft — pending engineer sign-off
**Project:** Cerberus — Agentic AI Hackathon
**Architecture:** Agent Loop (Candidate B) — LangGraph + Gemini 1.5 Pro + FastAPI + React

> Invariants are constraints, not goals. If any invariant is violated, the system is
> broken regardless of what else works. Every invariant below is traced to at least
> one requirement ID from the spec.

---

## Data Touch Point Map (Step 0)

| Touch point | What crosses the boundary |
|---|---|
| **Capture** | User submits project ID → LangGraph start state |
| **Scan** | GCP Compute/Billing APIs → raw resource records in state |
| **Enrich** | GCP IAM / Cloud Asset Inventory APIs → ownership fields appended to each record |
| **Reason** | Enriched record → Gemini 1.5 Pro → `{ decision, reasoning, estimated_savings }` per resource |
| **Approval** | LangGraph plan state → React UI table → human approve/reject signal → written back to state |
| **Execute** | Approved action list in state → GCP mutation APIs → actual resource changes |
| **Audit** | Every node transition and action outcome → append-only JSON log + LangSmith trace |
| **Credentials** | GCP service account key → env var / Secret Manager → GCP API calls only |

---

## SCAN NODE INVARIANTS

### INV-SCAN-01 — Resource fields are complete before leaving scan_node
**Traced to:** FR-SCAN-06
**Condition:** Every resource record emitted by `scan_node` must contain all six required fields: `resource_id`, `resource_type`, `region`, `creation_timestamp`, `last_activity_timestamp`, `estimated_monthly_cost`. Any record missing one or more fields must be dropped from state and logged as incomplete — it must not proceed to `enrich_node`.
**Category:** Data correctness
**Why this matters:** `reason_node` uses `last_activity_timestamp` for idle detection and `estimated_monthly_cost` for savings estimation. A missing field silently produces wrong LLM output — a $0 savings estimate or a non-idle classification on an actually-idle resource.
**Enforcement points:**
- `scan_node` exit: validate every record against the six-field schema. Drop and log records that fail. Only valid records enter state.
- `enrich_node` and `reason_node` must read fields via a schema-enforced accessor, not direct dict access.

---

### INV-SCAN-02 — Idle VM threshold is 5% CPU for ≥ 72 hours
**Traced to:** FR-SCAN-01
**Condition:** A GCE VM instance must be flagged `idle` in the scan record if and only if its average CPU utilisation is < 5% for a continuous period of ≥ 72 hours. No other threshold may be used.
**Category:** Data correctness
**Why this matters:** The idle flag is the primary signal `reason_node` uses to classify a VM as `safe_to_stop`. A wrong threshold (e.g. 10% or 24 hours) inflates or deflates the cleanup plan, making the demo's $500+/month savings claim unreliable.
**Enforcement points:**
- `scan_node` — Cloud Monitoring API query: metric `compute.googleapis.com/instance/cpu/utilization`, aggregation window 72h, threshold 0.05. The idle flag is set in this node and must not be overridden downstream.

---

### INV-SCAN-03 — Orphaned disks and unused IPs are identified in scan
**Traced to:** FR-SCAN-02, FR-SCAN-03
**Condition:** `scan_node` must include in its output all persistent disks with no VM attachment and all static external IPs with no forwarding rule or VM association. These must appear as distinct resource records with `resource_type: orphaned_disk` and `resource_type: unused_ip` respectively.
**Category:** Data correctness
**Why this matters:** If these resource types are missing from scan output, the downstream plan omits them entirely — the demo shows fewer findings and lower savings than the GCP project actually has.
**Enforcement points:**
- `scan_node`: separate API calls for disks (`compute.disks.list` filtered by no users) and IPs (`compute.addresses.list` filtered by status RESERVED, no users). Both lists merged into the unified resource list before state is written.

---

### INV-SCAN-04 — Billing data is fetched per resource for current and prior month
**Traced to:** FR-SCAN-04
**Condition:** Every resource record must include `estimated_monthly_cost` derived from Cloud Billing API data for the current billing month and the previous billing month. A record with a hardcoded or zero cost is not valid unless the resource genuinely has zero spend.
**Category:** Data correctness
**Why this matters:** `reason_node` cites cost as quantitative evidence in its reasoning. A zero or missing cost produces reasoning that cannot satisfy FR-RSN-02's requirement to cite evidence.
**Enforcement points:**
- `scan_node`: Cloud Billing API call per resource (or batch by label). Cost field must be set from API response. If the API call fails, the resource is still included but `estimated_monthly_cost` is set to `null` and flagged — not silently zeroed.

---

## ENRICH NODE INVARIANTS

### INV-ENR-01 — Ownership classification uses the four-step lookup chain
**Traced to:** FR-ENR-01, FR-ENR-02, FR-ENR-03
**Condition:** `enrich_node` must attempt ownership resolution in this priority order: (1) GCP resource labels (`owner`, `team`, `created-by`), (2) Cloud Asset Inventory metadata, (3) IAM binding history, (4) Cloud Audit Log last mutation actor. The `ownership_status` field must be set to exactly one of: `active_owner`, `departed_owner`, `no_owner`. No other values are valid.
**Category:** Data correctness
**Why this matters:** If the lookup chain is skipped or short-circuited at step 1, resources with no labels are misclassified as `no_owner` even when IAM history would resolve them. This inflates the `needs_review` bucket and reduces demo impact.
**Enforcement points:**
- `enrich_node`: four explicit lookup functions called in order. Each function returns a result or `None`. The first non-`None` result wins. If all four return `None`, `ownership_status = no_owner`.
- `ownership_status` must be written to the resource record before `enrich_node` exits. A record with a missing `ownership_status` field must not enter `reason_node`.

---

### INV-ENR-02 — Active IAM membership check is always performed
**Traced to:** FR-ENR-02
**Condition:** For every resource where a candidate owner email is resolved, `enrich_node` must call the IAM API to confirm whether that email currently holds an active IAM binding in the project. The result of this check determines whether `ownership_status` is `active_owner` or `departed_owner`.
**Category:** Data correctness
**Why this matters:** An owner who left the team is one of Cerberus's primary signals for safe cleanup. If the IAM membership check is skipped, departed owners are misclassified as active — suppressing legitimate `safe_to_stop` recommendations.
**Enforcement points:**
- `enrich_node`: `check_iam_membership(email, project_id)` is called for every resolved owner. The result is stored in the resource record as `owner_iam_active: bool`.

---

### INV-ENR-03 — no_owner resources are flagged and blocked from auto-action
**Traced to:** FR-ENR-04, Guardrails §7 "No Owner = No Delete"
**Condition:** Any resource with `ownership_status = no_owner` must have a `flagged_for_review: true` field set by `enrich_node`. This flag must be checked by `reason_node` (forces `needs_review`) and by `execute_node` (blocks execution regardless of approval status).
**Category:** Security
**Why this matters:** Unowned resources must never be auto-deleted. This is a named guardrail in §7. A `no_owner` resource that reaches `execute_node` without being blocked is a guardrail bypass.
**Enforcement points:**
- `enrich_node`: set `flagged_for_review = True` when `ownership_status == no_owner`.
- `reason_node`: if `flagged_for_review == True`, output must be `needs_review`. System prompt enforces this. A separate post-LLM check validates: if `flagged_for_review` and decision != `needs_review`, override to `needs_review` and log the override.
- `execute_node`: pre-execution check iterates approved list. Any resource with `flagged_for_review == True` is skipped with `outcome: SKIPPED_GUARDRAIL` logged.

---

## REASON NODE INVARIANTS

### INV-RSN-01 — LLM output is one of four valid decisions only
**Traced to:** FR-RSN-01
**Condition:** `reason_node` must produce exactly one of `safe_to_stop`, `safe_to_delete`, `needs_review`, `skip` for every resource. Any other value is invalid. If Gemini returns an unrecognised classification, the resource must be reclassified as `needs_review` and a parse-failure event logged.
**Category:** Data correctness
**Why this matters:** `execute_node` switches on this field. An unrecognised value causes a silent skip or — worse — an unhandled code path. Either breaks demo reliability.
**Enforcement points:**
- `reason_node`: parse Gemini response. Validate decision against the four-value enum. On mismatch: set `needs_review`, log parse failure, continue. Do not raise an exception that halts the agent.

---

### INV-RSN-02 — Every decision includes a stored reasoning string ≤ 3 sentences
**Traced to:** FR-RSN-02, FR-RSN-04
**Condition:** Every resource classification must include a `reasoning` string of ≤ 3 sentences citing at least one quantitative piece of evidence (idle duration, ownership status, or monthly cost). The reasoning must be stored in LangGraph state. A classification with an empty, missing, or reasoning-free decision is invalid.
**Category:** Data correctness
**Why this matters:** The reasoning trace is the primary output judges evaluate. A missing or empty reasoning field means the demo's core value claim — "the agent explains every decision" — is broken on that resource.
**Enforcement points:**
- `reason_node` output schema: `{ decision, reasoning, estimated_savings }`. If `reasoning` is empty or absent after parsing: retry the Gemini call once. If still empty: set decision to `needs_review`, set `reasoning` to `"Reasoning unavailable — flagged for human review."`, log the failure.
- React UI approval table: `reasoning` column is non-optional. A row with no reasoning string is visually flagged with a warning indicator.

---

### INV-RSN-03 — Savings estimate is stored for every actionable classification
**Traced to:** FR-RSN-03, FR-RSN-05
**Condition:** Every resource classified as `safe_to_stop` or `safe_to_delete` must have an `estimated_monthly_savings` value (numeric, USD) stored in state. Resources classified `needs_review` or `skip` may have a zero or null savings value.
**Category:** Data correctness
**Why this matters:** The UI must display a dynamic total savings estimate (FR-UI-03). If individual savings values are missing, the total is wrong — the demo's headline number ("$1,200/month recovered") is the most visible output.
**Enforcement points:**
- `reason_node`: `estimated_monthly_savings` must be derived from `estimated_monthly_cost` in the resource record. If cost is null (billing API failed at scan), savings must be set to `0` and a note added to the reasoning string.
- `approve_node` (React UI): total savings counter sums only `safe_to_stop` and `safe_to_delete` resources that are currently in the approved state.

---

## APPROVE NODE INVARIANTS

### INV-UI-01 — Approval table shows all required columns
**Traced to:** FR-UI-01
**Condition:** The React approval table must render these columns for every resource row: Resource Name, Type, Region, Owner, Ownership Status, LLM Decision, Reasoning, Estimated Savings. No column may be silently omitted. A row with a missing column is a rendering defect.
**Category:** Operational
**Why this matters:** Judges review this table directly during the demo. A missing column (especially Reasoning or Ownership Status) undermines the demo's core claim about transparency and safe decision-making.
**Enforcement points:**
- React component: column definitions are a static constant. Any resource record missing a field must render a `—` placeholder, not a blank or undefined cell.

---

### INV-UI-02 — Execute button is inactive until at least one action is approved
**Traced to:** FR-UI-05
**Condition:** The Execute button must be disabled (`disabled` attribute set, visually greyed) when zero actions are in the approved state. It must become active only when ≥ 1 resource has been explicitly approved. Clicking a disabled Execute button must have no effect.
**Category:** Security
**Why this matters:** An active Execute button with no approvals is a UX path to accidental execution — a user could click it expecting nothing to happen, not knowing the state changed.
**Enforcement points:**
- React state: `approvedCount` derived from approval state. `<button disabled={approvedCount === 0}>`.
- `execute_node` server-side: validates `len(approved_actions) > 0` before processing. Returns error if called with empty list.

---

### INV-UI-03 — Dry-run preview is shown before live execution
**Traced to:** FR-UI-05, Guardrails §7 "Dry-Run Default"
**Condition:** When the user switches to live execution mode and clicks Execute, a dry-run preview modal must be shown listing the exact actions that will be taken before any GCP mutation API is called. The user must confirm this modal. No mutation may occur without this confirmation.
**Category:** Security
**Why this matters:** The dry-run default guardrail is listed explicitly in §7. Skipping the preview removes the last human checkpoint before irreversible GCP changes.
**Enforcement points:**
- React UI: `dry_run` toggle defaults to `true`. When toggled off, Execute triggers a confirmation modal. Modal dismissed without confirm = no API call made.
- FastAPI endpoint: `dry_run` flag passed from frontend. If `dry_run=true`, `execute_node` logs plan but makes no GCP calls.

---

## EXECUTE NODE INVARIANTS

### INV-EXE-01 — VMs are stopped, not deleted, on first approval
**Traced to:** FR-EXE-01
**Condition:** `execute_node` must call the VM stop API (`instances.stop`) for resources classified `safe_to_stop`. It must never call the VM delete API (`instances.delete`) unless the resource is explicitly classified `safe_to_delete` AND has gone through a separate explicit delete-approval flow.
**Category:** Security
**Why this matters:** Stopping a VM is reversible. Deleting it is not. The requirements explicitly mandate stop-not-delete for idle VMs. Calling delete where stop is required is an unrecoverable data loss event.
**Enforcement points:**
- `execute_node`: action router maps `safe_to_stop` → `instances.stop` only. The `instances.delete` call path is only reachable for `safe_to_delete` resources. These two code paths must be structurally separate — not a flag on the same function.

---

### INV-EXE-02 — Each execution step is verified via GCP API before proceeding
**Traced to:** FR-EXE-04
**Condition:** After each GCP mutation call, `execute_node` must call a read API to confirm the expected state change occurred before moving to the next action. If the verification call shows the resource is still in its prior state, the action must be marked `FAILED` in the audit log and the next action must still proceed (no full halt on single-action failure).
**Category:** Operational
**Why this matters:** GCP mutation APIs are eventually consistent. A fire-and-forget execution loop may log success while the resource never actually changed — producing a false before/after cost summary.
**Enforcement points:**
- `execute_node`: after `instances.stop(resource_id)`, call `instances.get(resource_id)` and assert `status == TERMINATED`. On assertion failure: log `outcome: FAILED`, continue loop.

---

### INV-EXE-03 — Session mutation rate limit is enforced at 10
**Traced to:** FR-EXE-05, Guardrails §7 "Session Rate Limit"
**Condition:** `execute_node` must not execute more than 10 GCP mutations per session. When the counter reaches 10, the execution loop must halt, log a rate-limit event, and surface a message in the UI. Remaining approved actions are not executed in this session.
**Category:** Security
**Why this matters:** This is an explicit guardrail in §7. An unbounded execution loop on a real GCP project can cause unintended large-scale changes.
**Enforcement points:**
- LangGraph state: `mutation_count: int` initialised to 0 at session start. `execute_node` increments before each mutation and checks before each mutation: `if mutation_count >= 10: halt`.
- The check must occur before the API call, not after.

---

## AUDIT NODE INVARIANTS

### INV-AUD-01 — Every action produces a complete log entry
**Traced to:** FR-AUD-01
**Condition:** Every agent action — including approved mutations, rejected actions (human said no), dry-run plan entries, guardrail skips, and node failures — must produce an audit log entry with these fields: `timestamp`, `resource_id`, `action_type`, `llm_reasoning`, `actor` (`human` or `agent`), `outcome`. An action with no log entry is undefined behaviour.
**Category:** Operational
**Why this matters:** The audit trail is both the compliance record and the demo's observability story. A gap in the log means a judge cannot reconstruct what the agent did — undermining the "production-grade" claim.
**Enforcement points:**
- `audit_node`: called after every node transition that produces an action. Log write is synchronous — not fire-and-forget.
- Outcome values must be one of: `SUCCESS`, `FAILED`, `REJECTED`, `SKIPPED_GUARDRAIL`, `DRY_RUN`.

---

### INV-AUD-02 — Before/after cost summary is generated at run end
**Traced to:** FR-AUD-04
**Condition:** At the conclusion of every agent run (whether or not any actions were executed), `audit_node` must produce a cost summary record containing: `resources_scanned`, `total_waste_identified`, `actions_approved`, `actions_executed`, `estimated_monthly_savings_recovered`. This record must be surfaced in the React UI.
**Category:** Operational
**Why this matters:** The demo script (§12 Scene 4) explicitly shows "before/after savings: $1,200/month recovered." If the summary is missing or miscalculated, the demo's headline moment fails.
**Enforcement points:**
- `audit_node`: cost summary computed from LangGraph state at run end. `estimated_monthly_savings_recovered` sums `estimated_monthly_savings` for all resources with `outcome: SUCCESS` only — not approved-but-failed actions.

---

## SECURITY INVARIANTS

### INV-SEC-01 — Production project is blocked at scan_node entry
**Traced to:** Guardrails §7 "Production Protection", FR-SCAN-01
**Condition:** `scan_node` must validate the `project_id` in state against the dev allowlist pattern (`nexus-tech-dev-*`) before making any GCP API call. If the project ID does not match, the agent must hard-exit with a user-facing error message. No GCP call of any kind may be made against a non-allowlisted project.
**Category:** Security
**Why this matters:** A mis-typed or maliciously supplied project ID could run the full agent loop — scan, enrich, reason, execute — against the production project. This is the most catastrophic possible failure mode.
**Enforcement points:**
- `scan_node` entry: `assert re.match(r'^nexus-tech-dev-', project_id)`. On failure: write error to audit log, return terminal state to UI, raise no further GCP calls.
- Allowlist pattern is a config constant, not hardcoded in the assertion.

---

### INV-SEC-02 — GCP credentials never reach the client
**Traced to:** NFR-06
**Condition:** GCP service account credentials must never appear in any client-accessible surface: FastAPI response bodies, React UI state, browser-visible API responses, URL parameters, or audit log entries rendered to the frontend.
**Category:** Security
**Why this matters:** Exposed credentials in a browser give anyone with devtools full GCP API access. This is an immediate and silent security failure — there is no observable indicator until damage is done.
**Enforcement points:**
- FastAPI: credentials loaded via `os.environ` or Secret Manager only. Never serialised into any Pydantic response model.
- LangGraph state: no field in the state schema holds credential values.
- `audit_node`: log entry schema explicitly excludes any field that could contain credential data.

---

## NON-FUNCTIONAL INVARIANTS

### INV-NFR-01 — scan_node completes within 60 seconds for ≤ 100 resources
**Traced to:** NFR-01
**Condition:** `scan_node` must complete its full resource discovery (VMs, disks, IPs, billing) within 60 seconds for a project containing up to 100 resources. If the 60-second limit is exceeded, `scan_node` must return whatever results it has collected so far, log a timeout event, and continue the pipeline with partial results — it must not block indefinitely.
**Category:** Operational
**Why this matters:** Demo flow (§12) requires the agent to visibly progress through nodes in real-time. A scan that hangs kills the demo narrative.
**Enforcement points:**
- `scan_node`: asyncio timeout wrapper at 60s. Partial results are valid pipeline input. Timeout event logged with count of resources retrieved.

---

### INV-NFR-02 — GCP API failures trigger exponential backoff with max 3 retries
**Traced to:** NFR-03
**Condition:** Every GCP API call in every node must be wrapped in a retry handler implementing exponential backoff (1s, 2s, 4s) with a maximum of 3 attempts. After 3 failures, the affected resource must be skipped and the failure logged — the agent must not halt the full run.
**Category:** Operational
**Why this matters:** GCP rate limit errors (429) are common in demo environments with rapid sequential API calls. A single unhandled 429 that crashes the agent mid-demo is unacceptable.
**Enforcement points:**
- Shared utility: `gcp_call_with_retry(fn, *args, max_retries=3)` used by all nodes. Not implemented per-node ad hoc.

---

### INV-NFR-03 — Node failure surfaces a human-readable message in the UI
**Traced to:** NFR-04
**Condition:** If any LangGraph node raises an unhandled exception, the agent must catch it at the graph level, write a failure event to the audit log, and surface a human-readable error message in the React UI ("Step X failed: [reason]"). The UI must not show a raw stack trace or remain in a loading/spinner state indefinitely.
**Category:** Operational
**Why this matters:** A demo where the UI freezes on a spinner with no message is worse than a graceful failure. Judges need to see the system handle failure cleanly.
**Enforcement points:**
- LangGraph graph: global error handler node at graph exit. Catches exceptions from all nodes. Writes to audit log. Sets `error_message` field in state. React UI: polls for `error_message` and renders it prominently if set.

---

## Scope Boundary — What These Invariants Do NOT Cover

The following are explicitly out of scope for this hackathon build. Any requirement touching these areas is deferred:

| Deferred area | Source in spec | Reason |
|---|---|---|
| IAM access management workflow (Phase 1–5) | §14, FR-WF-01 to FR-WF-12 | Separate full agent — exceeds one-week timeline |
| FR-IAM-01 to FR-IAM-05 (Access Head) | §4.7 | Part of multi-head council (Candidate C) — post-hackathon |
| Multi-head council consensus / Cortex | §6.3, §15.3 | Candidate C deferred; Candidate B selected |
| Firestore / persistent cross-session state | §11 | Explicitly excluded in spec |
| Jira / ServiceNow / Slack integration | §11 | Explicitly excluded in spec |
| Multi-project orchestration | §11 | Explicitly excluded in spec |
| Security Head (audit log anomaly analysis) | §6.3 | Partial — basic audit log only, no anomaly detection |
| LangSmith integration (NFR-08) | §5 | Best-effort; not an invariant — cannot be enforced in code |
| Cloud Run + Firebase deployment (NFR-09) | §5 | Delivery target, not a runtime constraint |

---

## Requirements Coverage Summary

| Requirement ID | Invariant(s) | Status |
|---|---|---|
| FR-SCAN-01 | INV-SCAN-02, INV-SEC-01 | Covered |
| FR-SCAN-02 | INV-SCAN-03 | Covered |
| FR-SCAN-03 | INV-SCAN-03 | Covered |
| FR-SCAN-04 | INV-SCAN-04 | Covered |
| FR-SCAN-05 | INV-SCAN-03 (extend to GKE) | Covered |
| FR-SCAN-06 | INV-SCAN-01 | Covered |
| FR-ENR-01 | INV-ENR-01 | Covered |
| FR-ENR-02 | INV-ENR-02 | Covered |
| FR-ENR-03 | INV-ENR-01 | Covered |
| FR-ENR-04 | INV-ENR-03 | Covered |
| FR-ENR-05 | INV-SCAN-01 (field appended before exit) | Covered |
| FR-RSN-01 | INV-RSN-01 | Covered |
| FR-RSN-02 | INV-RSN-02 | Covered |
| FR-RSN-03 | INV-RSN-03 | Covered |
| FR-RSN-04 | INV-RSN-02 | Covered |
| FR-RSN-05 | INV-RSN-03 | Covered |
| FR-UI-01 | INV-UI-01 | Covered |
| FR-UI-02 | INV-UI-01 (row controls) | Covered |
| FR-UI-03 | INV-RSN-03 (savings total) | Covered |
| FR-UI-04 | INV-RSN-02 (reasoning stored in state) | Covered |
| FR-UI-05 | INV-UI-02, INV-UI-03 | Covered |
| FR-EXE-01 | INV-EXE-01 | Covered |
| FR-EXE-02 | INV-EXE-03 (unused IP release) | Covered |
| FR-EXE-03 | INV-ENR-03 (orphaned disk → flagged_for_review) | Covered |
| FR-EXE-04 | INV-EXE-02 | Covered |
| FR-EXE-05 | INV-EXE-03 | Covered |
| FR-AUD-01 | INV-AUD-01 | Covered |
| FR-AUD-02 | INV-AUD-01 (real-time feed) | Covered |
| FR-AUD-03 | INV-AUD-01 (local file) | Covered |
| FR-AUD-04 | INV-AUD-02 | Covered |
| FR-IAM-01 to FR-IAM-05 | — | Deferred (see scope boundary) |
| NFR-01 | INV-NFR-01 | Covered |
| NFR-02 | INV-RSN-02 (retry on empty reasoning) | Partial |
| NFR-03 | INV-NFR-02 | Covered |
| NFR-04 | INV-NFR-03 | Covered |
| NFR-05 | INV-SEC-02 (least-privilege SA) | Covered |
| NFR-06 | INV-SEC-02 | Covered |
| NFR-07 | — | README quality — not an invariant |
| NFR-08 | — | LangSmith — best-effort, not enforceable |
| NFR-09 | — | Deployment target — not a runtime invariant |
| Guardrail: Production protection | INV-SEC-01 | Covered |
| Guardrail: Human approval required | INV-UI-02, INV-UI-03 | Covered |
| Guardrail: No owner = no delete | INV-ENR-03 | Covered |
| Guardrail: Session rate limit | INV-EXE-03 | Covered |
| Guardrail: Dry-run default | INV-UI-03 | Covered |
| Guardrail: Audit trail | INV-AUD-01 | Covered |
| Guardrail: Quorum for high-risk | — | Deferred (requires multi-head council) |
| Guardrail: Data-sensitive archival | INV-ENR-03 (flagged_for_review) | Partial |
| FR-WF-01 to FR-WF-12 | — | Deferred (IAM workflow, §14) |

---

## Sign-off

| Role | Name | Date | Status |
|---|---|---|---|
| Engineer | | | ☐ Pending |
