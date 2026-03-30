# ARCHITECTURE.md
## Cerberus — GCP Dev Environment Guardian
### Agent Loop (Candidate B) — Selected Architecture

**Version:** 1.0  
**Status:** Approved for build  
**Context:** Agentic AI Hackathon — NexusTech Platform team  
**Last updated:** 2026-03-30

---

## 1. Problem framing

### What this system solves

Dev and sandbox GCP environments at NexusTech silently waste an estimated $10,500/month — roughly 30% of total GCP spend — because no single system correlates three signals that currently live in separate tools: who owns a resource, whether that person still works here, and what the resource is costing. Every existing tool answers one question in isolation. Cerberus is the correlation layer.

The system accepts a single natural-language command, performs a full scan of a target GCP development project, enriches each discovered resource with IAM ownership context, applies LLM reasoning to classify each resource and explain the classification in plain English, presents a human-approvable plan, re-validates current resource state immediately before execution, executes approved actions, and records a complete audit trail — without manual intervention between steps.

A secondary workflow handles IAM access requests: a new team member's access request is decomposed into minimum-privilege GCP permissions, evaluated against ownership and utilisation context, routed for human approval where warranted, provisioned automatically on approval, and scheduled for a 90-day review.

### What this system explicitly does not solve

- **Production project management.** Cerberus operates only on projects matching the `dev-*` pattern. Any project outside this allowlist is refused before any API call is made. This is a hard architectural boundary, not a configuration setting.
- **Multi-cloud or non-GCP environments.** The system is GCP-native. AWS and Azure are out of scope.
- **Security compliance reporting.** Audit log generation and LangSmith observability are in scope. Formal compliance report generation (SOC 2, ISO 27001 artefacts) is not.
- **Jira / ServiceNow integration.** External ticketing systems are future scope. The UI and local audit log are the only artefacts produced in v1.
- **Multi-project orchestration.** One project per agent invocation. Running across all eight `nexus-tech-dev-*` projects simultaneously is out of scope for v1.
- **Autonomous execution without human approval.** The system is designed to inform and assist human decision-making, not replace it. The approve_node is not bypassable under any condition.

---

## 2. Five key design decisions

### Decision 1: Agent Loop (LangGraph ReAct) over Pipeline or Multi-Head Council

**What was decided:** Build on a single LangGraph ReAct-style agent with a defined toolbox. The agent decides which tools to call, in what order, and when it has gathered sufficient information to classify a resource. LangSmith traces every tool call and reasoning step.

**Rationale:** The highest-consequence failure mode for this system is ownership false confidence — classifying a resource as owned by an active engineer when the ownership signal is stale, reassigned, or ambiguous. The Pipeline architecture handles this only through pre-programmed branching; if the primary label lookup fails, the fallback must be explicitly coded. The Agent Loop handles it through adaptive reasoning: if labels are absent or suspicious, the agent pursues IAM history, then audit logs, without a pre-programmed branch for each combination. For a system acting on real infrastructure owned by real people, the ability to express and resolve uncertainty is more valuable than deterministic execution.

LangSmith observability is also a first-class output for the hackathon demo. The full reasoning chain — every tool call, every LLM thought — is surfaced automatically. This is not achievable with the Pipeline without significant additional instrumentation.

**Alternatives rejected:**

- *Pipeline (Candidate A):* Rejected because ownership false confidence requires pre-programmed branching for every fallback case. The no-owner guardrail is not enforced by the architecture — it requires explicit code that can be forgotten or broken. Cross-resource reasoning (two resources from the same departed engineer) is structurally impossible. The Pipeline is the right choice when workflow is well-understood and stable; the ownership lookup space is neither.

- *Multi-Head Council (Candidate C):* Rejected on timeline grounds. The Cortex consensus logic — specifically, reconciling conflicting verdict *types* (not binary agree/disagree, but `safe_to_delete` vs `archive_first` vs `needs_review`) — cannot be fully designed, implemented, and tested within a seven-day sprint alongside UI, deployment, and demo preparation. C is the correct target end-state architecture as the system matures. It is not the correct v1 build target.

---

### Decision 2: revalidate_node between approve_node and execute_node

**What was decided:** A `revalidate_node` is inserted between the human approval gate and execution. This node re-fetches current GCP state for each approved resource and diffs it against the approved snapshot. Three outcomes: (1) no drift — proceed; (2) partial drift — re-present only drifted rows for re-approval; (3) full drift — surface a warning and require a fresh scan.

**Rationale:** The requirements document does not address the gap between plan approval and execution. LangGraph serialises agent state at the approval gate. When execution resumes — which may be seconds or minutes later — the agent operates against the approved snapshot, not current GCP state. In a live development environment, a VM that was idle at scan time may be running a batch job by execution time. Stopping it would be a correctness failure, not a code bug.

The 10-second latency cost of re-validation is acceptable and is actively useful on demo day: it can be narrated explicitly ("before touching anything, Cerberus verifies the world hasn't changed since you approved") and reinforced with a UI progress indicator. This turns a potential awkward pause into a visible safety feature.

**Alternatives rejected:**

- *Timestamp warning (warn if >5 min since scan):* Rejected because it informs the user of potential drift without resolving it. A human reading a stale-data warning still has to decide whether to proceed, and they have no mechanism to check which resources have drifted without re-running the scan manually. It adds cognitive load without adding safety.

- *Execute against approved snapshot:* Rejected because the consequence of acting on stale data in this domain is not recoverable in all cases. Stopping a VM is recoverable; releasing a static IP that another service has taken a dependency on since scan time may not be. "Acceptable risk for a dev environment" is a valid position in general, but not for a system whose primary value proposition is that it can be trusted to act safely on real infrastructure.

---

### Decision 3: Session boundary = one agent invocation

**What was decided:** The 10-mutation rate limit is scoped to a single agent invocation. The mutation counter lives in LangGraph state. It initialises to zero when the user submits an "Analyze" command and is destroyed when the session completes. A new "Analyze" command starts a fresh invocation with a fresh counter.

**Rationale:** This definition is unambiguous, trivially implementable (counter in LangGraph state), and naturally auditable (the LangSmith trace for an invocation shows exactly how many mutations were made). It aligns with how users will think about the system: "I ran Cerberus on dev-project-3" is a natural unit of work.

The alternative definitions (per user per hour, per project per day) require server-side state that survives page refreshes and concurrent sessions — infrastructure that adds complexity without commensurate safety benefit at the scale of a single-project hackathon demo.

**Alternatives rejected:**

- *Per user per hour:* Rejected because it requires a persistent session store (database or cache) that is out of scope for the v1 build. It also creates a confusing user experience: a user who hits the limit mid-invocation and waits an hour expects a fresh slate, but the hour boundary may fall mid-plan.

- *Per project per day:* Rejected for the same infrastructure reasons. Additionally, it would prevent the three consecutive demo runs required by the success metrics if any single run uses more than 3–4 mutations.

---

### Decision 4: temperature=0 and structured JSON output at reason_node

**What was decided:** All Gemini calls at `reason_node` use `temperature=0` and require structured JSON output conforming to a defined schema: `decision` (enum), `reasoning` (string, ≤3 sentences), `evidence` (array, minimum one quantitative item), `estimated_monthly_saving` (number). The `no_owner` → `needs_review` mapping is enforced in the system prompt and validated in code before the result enters LangGraph state.

**Rationale:** Non-determinism in LLM reasoning is the most significant demo stability risk for Candidate B. The same resource classified differently across two consecutive runs is not just an inconvenience — it is a trust-destroying event for a system that asks engineers to approve actions against their infrastructure. `temperature=0` eliminates sampling variance. Structured output eliminates parsing ambiguity. Validating the `no_owner` → `needs_review` rule in code (not just in the prompt) ensures the guardrail survives prompt drift or unexpected model behaviour.

The three-sentence reasoning constraint is both a quality guardrail and a UI constraint: the approval table must display reasoning inline, and unbounded text breaks the layout.

**Alternatives rejected:**

- *Free-text reasoning with post-hoc parsing:* Rejected because parsing LLM free text for structured fields (decision classification, savings estimate) introduces a failure surface that cannot be unit tested. A structured output schema contract can be tested; a regex over free text cannot be reliably maintained.

- *temperature=0.2 for "more natural" reasoning:* Rejected. The marginal improvement in reasoning naturalness does not justify the demo stability risk. Judges reading the reasoning panel will not notice the difference; a classification flip between demo runs will be immediately visible.

---

### Decision 5: LangSmith as the audit trail, supplemented by local JSON log

**What was decided:** Every agent run produces two audit records simultaneously: a LangSmith trace (capturing all node transitions, tool calls, LLM inputs/outputs, and decision points) and a local append-only JSON file (capturing action, resource, reasoning, actor, outcome, and timestamp per event). Both are written by `audit_node`. The LangSmith trace is the primary artefact for judge inspection; the local JSON log is the primary artefact for compliance review.

**Rationale:** LangSmith free tier provides full agent trace visibility with minimal instrumentation overhead — it is effectively free in terms of build time for a LangGraph-based agent. The trace is inspectable in real time during the demo, which is a significant presentation asset. The local JSON log provides a fallback audit record that does not depend on network connectivity to LangSmith and is easier to parse programmatically for the before/after cost summary.

**Alternatives rejected:**

- *LangSmith only:* Rejected because LangSmith is an external service with network dependency. If LangSmith is unavailable during the demo, the observability story collapses entirely. The local JSON log is a 20-line addition that eliminates this single point of failure.

- *Firestore persistent state:* Rejected as explicitly out of scope in the requirements document. In-memory LangGraph state is sufficient for v1; Firestore adds infrastructure with no demo value.

---

## 3. Challenge my decisions

### Challenge to Decision 1: Agent Loop

**Strongest argument against:** The Agent Loop's adaptive ownership reasoning is only as good as the system prompt that encodes it. If the prompt is subtly wrong — if the agent's chain-of-thought about a borderline ownership case reaches the wrong conclusion — the error is invisible until a resource is misclassified. With a Pipeline, the ownership lookup logic is in Python: it can be unit tested, the failure case is a raised exception, and the fix is a one-line code change. With the Agent Loop, the failure is in a reasoning trace: the fix is a prompt change whose effect on other cases is unknown. For a security-sensitive system, this is a significant reliability regression.

**Assessment: Valid, but accepted.** The challenge is correct that prompt-driven guardrails are less reliable than code-enforced guardrails. This is why the `no_owner` → `needs_review` rule is validated in code after `reason_node` returns, not only in the prompt. The structural weakness of the Agent Loop on guardrail reliability is real; the mitigation is to identify every guardrail that can be enforced in code and enforce it there, using the prompt only for reasoning that genuinely requires LLM judgement. The tradeoff is accepted because the Pipeline's inability to handle fallback ownership lookups adaptively is a worse failure mode for this specific domain.

---

### Challenge to Decision 2: revalidate_node

**Strongest argument against:** The revalidate_node assumes that re-fetching resource state immediately before execution is sufficient to prevent acting on stale data. It is not. In a live development environment, a VM could transition from idle to active in the seconds between revalidation and the actual stop API call. The revalidate_node reduces the drift window but does not close it. If the guarantee being offered is "Cerberus verifies current state before acting," the guarantee is weaker than it sounds, and communicating that nuance during a demo risks undermining the safety story entirely.

**Assessment: Valid, but the conclusion is rejected.** The challenge is technically correct — revalidation reduces drift exposure to a sub-second window rather than eliminating it. However, the relevant comparison is not "revalidation vs. perfect consistency" but "revalidation vs. no revalidation." Without the node, the drift window is the full time between scan and execution, which may be minutes. With it, the drift window is the round-trip time of a single GCP API call. For a dev environment cleanup tool — not a financial transaction system — a sub-second race condition is an acceptable residual risk. The safety claim should be scoped accurately in the UI ("state verified at execution time") rather than overstated.

---

### Challenge to Decision 3: Session = invocation

**Strongest argument against:** "One agent invocation" is not a meaningful safety boundary if invocations are cheap to create. A user who hits the 10-mutation limit can type "Analyze dev-project-3" again immediately, start a new invocation with a fresh counter, and execute 10 more mutations. Over 10 minutes they could execute 60 mutations. The rate limit as designed protects against a single runaway invocation, not against a user deliberately circumventing it through repeated invocations. For a system with production-adjacent blast radius, this is a meaningful gap.

**Assessment: Valid.** The challenge is correct. The session-as-invocation boundary is the right choice for v1 build simplicity, but it should not be presented to judges as a robust safety mechanism. It should be presented as a safeguard against accidental runaway in a single session — which is what it actually is. The stronger rate limit (per-project-per-day with persistent state) is a v2 item and should be noted explicitly in the open questions section.

---

### Challenge to Decision 4: temperature=0 and structured output

**Strongest argument against:** `temperature=0` eliminates sampling variance but does not eliminate systematic bias. If the model has a systematic tendency to classify borderline cases as `safe_to_delete` rather than `needs_review` — which is unknowable from the prompt alone — then `temperature=0` locks in that bias rather than averaging over it. A higher temperature would at least produce variance that could surface the ambiguity. The determinism guarantee is meaningful only if the model's zero-temperature output for every case is correct. There is no mechanism in the current design to validate this before the demo runs.

**Assessment: Valid on the theoretical claim, rejected on the practical conclusion.** The argument is correct that temperature=0 does not guarantee correctness — it guarantees repeatability. However, the alternative (higher temperature producing variance) makes the demo *less* safe, not more: a judge who sees two different classifications for the same resource in two consecutive runs loses confidence in the system entirely. The mitigation for systematic bias is not temperature tuning — it is prompt evaluation against a test set of resources before demo day. That evaluation is a Day 5 task in the build plan and should be treated as a blocking activity, not an optional polish item.

---

### Challenge to Decision 5: LangSmith + local JSON

**Strongest argument against:** Two simultaneous audit destinations creates a consistency problem: if `audit_node` writes to LangSmith successfully but the local JSON write fails (disk full, permissions error), the two records diverge silently. In a compliance context, a partial audit record is worse than no audit record — it creates ambiguity about which record is authoritative. The design should designate one record as the source of truth and treat the other as a best-effort copy, with explicit failure handling that does not allow silent divergence.

**Assessment: Valid.** The challenge identifies a real implementation gap. The resolution is: the local JSON log is the authoritative audit record; LangSmith is the observability and demo artefact. `audit_node` must write the local JSON record first and treat its success as a precondition for proceeding. LangSmith write failure should be logged as a warning but must not halt execution or invalidate the audit record. This ordering must be explicit in the implementation, not assumed.

---

## 4. Key risks

**Ownership label staleness** — the four-step ownership lookup chain resolves an `active_owner` classification, but a resource label pointing to a reassigned email address and a label pointing to a current engineer produce identical output. The agent has no signal that a label is stale. This is the highest-consequence risk in the system: a misclassification here leads to stopping a resource that is actively in use. Mitigation: cross-reference the resolved owner email's last IAM activity timestamp; if last activity is >90 days ago, downgrade to `needs_review` regardless of IAM membership status.

**Non-determinism under prompt drift** — Gemini model updates between build day and demo day could change zero-temperature output for borderline cases. The structured output schema provides some protection, but the reasoning content and classification for edge cases may shift. Mitigation: pin the Gemini model version used during development; run the full test scenario the morning of demo day and treat any classification change as a blocking issue.

**revalidate_node latency as a demo friction point** — the 10-second re-scan window before execution creates a visible pause in the demo flow. Without UI feedback, this reads as the system hanging. Mitigation: implement a "Verifying current state..." progress indicator in the React UI from day one; script the narration for this pause explicitly in the demo run-through.

**Partial scan surfacing as complete** — if GCP API rate limits cause `enrich_node` to fail for a subset of resources after retries are exhausted, the current design halts and surfaces an error. The risk is that the error message is not clear enough for a user to understand what happened and what to do next. A user who dismisses the error and proceeds with a manually reduced plan believes they have addressed the full project. Mitigation: the error message must include the exact count of successfully enriched resources, the count of failed resources, and a recommended action ("re-run the scan or proceed with the partial plan — 3 resources were not analysed").

---

## 5. Key assumptions

**GCP API access is pre-configured and verified before Day 1.** The build plan allocates Day 1 to GCP foundation work. If credentials, service account permissions, or API enablement are not confirmed working by end of Day 1, the Day 2 LangGraph skeleton cannot be wired to real data, and the entire build timeline shifts right.

**Resource labels are present on a sufficient subset of demo sandbox resources.** The ownership lookup chain prioritises GCP resource labels (`owner`, `created-by`, `team`). If the demo sandbox resources have no labels, the agent falls back to IAM history and audit logs for every resource — which is slower, less reliable, and produces weaker confidence scores. The demo scenario requires at least some resources with clear label ownership and at least some with departed-owner labels to demonstrate the full classification range.

**Gemini 1.5 Pro function calling is stable at temperature=0 for structured output.** The reasoning quality and structured output reliability have not been tested at scale against the specific resource classification prompt. This assumption must be validated on Day 3 (Gemini integration day) against the full range of resource types in the demo sandbox before proceeding to UI work.

**The demo sandbox can be seeded with realistic idle resources.** The success metrics require identifying ≥$500/month in recoverable waste. This requires the sandbox to contain resources that have been idle for ≥72 hours at the time of the demo, with realistic billing data attached. Seeding this sandbox (Day 6 in the build plan) cannot be left until the day before — idle time must be accumulated in advance.

**LangSmith free tier is available and accessible from Cloud Run.** The observability story depends on LangSmith. If the free tier has changed, if the Cloud Run egress to LangSmith is blocked, or if the LangSmith trace UI has changed materially, the demo's "inspectable reasoning" scene collapses. Verify LangSmith connectivity from Cloud Run on Day 6 deployment, not Day 7 demo prep.

---

## 6. Open questions

**What happens when revalidate_node detects drift on a resource that was approved as `safe_to_delete`?** The current design re-presents drifted rows for re-approval. But if the resource's state has changed from idle to active, should the agent automatically downgrade the classification to `needs_review` before re-presenting, or should it re-run the full `reason_node` chain for that resource? Re-running reason_node is more correct but adds latency and requires a mechanism to update LangGraph state mid-execution. This needs a design decision before the execute_node is built.

**How is the Gemini model version pinned?** The build plan does not specify which exact Gemini 1.5 Pro model version string is used in API calls. Model updates between build and demo day are a real risk (see Key Risks). The model version should be pinned in configuration, not resolved dynamically, and the pin should be documented here once confirmed on Day 3.

**What constitutes a "sensitive data" signal for the orphaned disk archival path?** FR-EXE-03 requires orphaned disks containing sensitive data to be archived to Coldline Storage rather than deleted. The Security Head (Candidate C) was the intended mechanism for this classification. In Candidate B, this classification must come from `reason_node`'s toolbox or a dedicated tool call. The specific signals (disk labels, data classification tags, naming conventions) that trigger the archival path are not defined. This must be resolved before `execute_node` handles disk actions.

**Is the 90-day access review scheduling in scope for v1?** The IAM provisioning workflow (Section 8.3 of the requirements) lists "schedule 90-day access review in calendar" as a provisioning step. The calendar integration target (Google Calendar, Jira, Confluence) is undefined, and Jira/ServiceNow are explicitly out of scope. This step is either a UI notification only (trivial) or a real calendar integration (non-trivial). The answer determines whether the Access Head workflow is complete or partial at demo time.

**Should the rate limit be scoped per-project-per-day in v2?** The current session-as-invocation boundary does not prevent a user from circumventing the 10-mutation limit through repeated invocations (see Challenge to Decision 3). A per-project-per-day limit enforced with persistent server-side state would close this gap. This requires a lightweight database or cache (Redis, Firestore) and is a v2 item — but the data model for it should be designed now so that `execute_node`'s mutation logging is forward-compatible with a persistent counter.

**How are concurrent sessions handled?** The requirements do not address what happens if two users run Cerberus against the same project simultaneously. Both sessions would scan the same resources, generate potentially conflicting plans, and could approve conflicting actions — for example, both sessions approving the deletion of the same disk. This is a low-probability event for a hackathon demo but a real operational risk. A project-level lock (advisory, not blocking) would surface the conflict to the second user without preventing them from proceeding. This is unspecified and should be resolved before a production deployment.

---

*Cerberus — three signals. One guardian. Zero wasted cloud spend.*