| **CERBERUS** GCP Dev Environment Guardian Structured Requirements Specification  │  Agentic AI Hackathon |
| --- |

| **Version** 1.0 | **Status** Draft | **Team** NexusTech Platform | **Context** Hackathon Deliverable |
| --- | --- | --- | --- |

# 1. Executive Summary

Cerberus is a production-grade agentic AI system that acts as an autonomous GCP Dev Environment Guardian. Given a single user command, it performs a full scan of a GCP development project, enriches findings with IAM ownership context, applies LLM reasoning to generate a safe cleanup plan, presents the plan for human approval, executes approved actions, and records a complete audit trail — all without manual intervention between steps.

The core insight driving Cerberus: IAM management and cost optimization are not separate problems. Idle resources are frequently owned by engineers who have left the team or the company. An agent that combines both signals makes smarter, safer decisions than any pure cost tool.

| **Dimension** | **Value** |
| --- | --- |
| **Problem** | Dev/sandbox GCP environments silently waste 20–30% of cloud spend due to idle resources and orphaned infrastructure owned by departed team members. |
| **Solution** | One-command AI agent: scan → enrich with IAM context → LLM reasoning → human approval → execute → audit. |
| **Primary Users** | Senior Cloud Platform Engineers, DevOps leads, and Cloud Admins managing multi-project GCP environments. |
| **Hackathon Category** | Agentic AI — satisfies Autonomy, Independent Decision-Making, LLM Reasoning, Guardrails, MCP Integration, Observability, and Cloud Deployment criteria. |
| **Estimated Business Value** | Identifies ≥ $500/month in waste per project; targets 20% reduction in dev environment spend; reduces IAM request resolution from ~45 min to ~5 min. |

# 2. Problem Statement

## 2.1  Operational Context

The reference environment for Cerberus is NexusTech, a 50-engineer AI/ML startup with the following GCP footprint:

| **Production Project** | nexus-tech-prod — fully managed, no Cerberus scope |
| --- | --- |
| **Dev / Sandbox Projects** | nexus-tech-dev-* — 8 projects, primary Cerberus operating surface |
| **Monthly GCP Spend** | $35,000 total; ~30% ($10,500) estimated waste in dev environments |
| **Team Scope** | 50+ engineers across Data Science, ML Engineering, DevOps, and Platform roles |

## 2.2  Pain Points

| **Pain Point** | **Symptom** | **Root Cause** |
| --- | --- | --- |
| **Cost Waste** | Idle VMs, orphaned disks, unused IPs burning $10K+/month | No automated lifecycle management; manual cleanup is slow and ad hoc |
| **IAM Chaos** | New joiners wait days for access; leavers retain access indefinitely | Ticket-driven IAM process with no enforcement or auto-expiry |
| **No Ownership Context** | Cost tools flag resources for deletion with no indication of who owns them or whether deletion is safe | IAM and billing data are siloed; no correlation layer |
| **Audit Gaps** | Compliance reviews require manual evidence collection | Actions are performed ad hoc with no structured audit trail |

## 2.3  Representative Daily Incidents

- Data Scientist requests bigquery.admin on dev-project-3 — overly broad, takes 45 min to process manually.

- DevOps engineer asks for deletion of orphaned GKE cluster in dev-project-5 — unknown owner, no one acts.

- Finance raises budget alert on dev-project-7 at 150% of allocated spend — root cause unclear.

- Security audit flags a service account with owner-level permissions in a dev project — remediation undefined.

# 3. Solution Overview

## 3.1  Agent Identity

| **Name** | Cerberus |
| --- | --- |
| **Tagline** | Three heads are better than one: Access, Cost, Security |
| **Mythology** | Guardian of the underworld — the three-headed dog that controls entry and exit; extended metaphor for controlling GCP resource lifecycle |
| **Primary Workflow** | One command → full GCP scan → IAM enrichment → LLM reasoning → human approval → execution → audit log |

## 3.2  The Agent Loop (End-to-End)

The following five-step loop is triggered by a single user prompt such as "Analyze dev-project-X":

| USER:  "Analyze dev-project-X" STEP 1  ── GCP Scan (real API calls)             → Discover idle VMs, orphaned disks, unused static IPs             → Pull billing data per resource STEP 2  ── IAM Enrichment             → Who owns each resource? (labels + IAM + Cloud Asset Inventory)             → Is the owner still on the team? Still active? STEP 3  ── LLM Reasoning (Gemini 1.5 Pro)             → Per resource: safe_to_stop │ safe_to_delete │ needs_review │ skip             → Explains WHY in plain English (≤ 3 sentences, always cites evidence)             → Estimates monthly savings STEP 4  ── React UI: Present Plan             → Table of findings with reasoning visible             → Approve / reject individual actions             → Total savings estimate displayed STEP 5  ── Execute + Audit             → Executes approved actions via GCP APIs             → Logs every action to audit trail             → Shows before/after cost summary |
| --- |

## 3.3  Why This Is Genuinely Agentic

| **Criterion** | **How Cerberus Satisfies It** | **Evidence** |
| --- | --- | --- |
| **Autonomy** | Single command triggers full scan → plan → execute with no manual hand-holding between steps. | Steps 1–5 run in sequence without user input until the approval gate. |
| **Independent Decision-Making** | LLM weighs idle time, ownership context, and resource type to arrive at a classification — not a hardcoded rule. | reason_node produces a per-resource decision with reasoning, not a lookup table. |
| **LLM-Powered Reasoning** | Gemini 1.5 Pro is in the loop at reason_node and explains every decision in natural language. | Reasoning IS the output — not a side effect. Judges can inspect it directly. |

# 4. Functional Requirements

## 4.1  GCP Scanning (scan_node)

| **Requirement ID** | **Description** |
| --- | --- |
| **FR-SCAN-01** | Agent MUST discover all GCE VM instances in the target project and flag those with CPU utilization < 5% for ≥ 72 hours as idle. |
| **FR-SCAN-02** | Agent MUST identify all persistent disks not attached to any VM instance as orphaned. |
| **FR-SCAN-03** | Agent MUST identify all static external IP addresses not in use. |
| **FR-SCAN-04** | Agent MUST retrieve per-resource billing data for the current and previous billing month. |
| **FR-SCAN-05** | Agent MUST surface GKE clusters with zero node utilization as idle. |
| **FR-SCAN-06** | Scan results MUST include resource ID, type, region, creation timestamp, last-activity timestamp, and estimated monthly cost. |

## 4.2  IAM Enrichment (enrich_node)

| **Requirement ID** | **Description** |
| --- | --- |
| **FR-ENR-01** | Agent MUST resolve the owner of each discovered resource via GCP resource labels (owner, team, created-by) and Cloud Asset Inventory. |
| **FR-ENR-02** | Agent MUST cross-reference resolved owner email against the current IAM policy to determine if the owner retains active access. |
| **FR-ENR-03** | Agent MUST classify ownership as: active_owner, departed_owner, or no_owner. |
| **FR-ENR-04** | Resources with no_owner classification MUST be flagged for human review and MUST NOT be auto-deleted. |
| **FR-ENR-05** | Enrichment results MUST be appended to the scan record for downstream reasoning. |

## 4.3  LLM Reasoning (reason_node)

| **Requirement ID** | **Description** |
| --- | --- |
| **FR-RSN-01** | Gemini 1.5 Pro MUST evaluate each enriched resource and output one of: safe_to_stop, safe_to_delete, needs_review, skip. |
| **FR-RSN-02** | Each decision MUST include a plain-English explanation of ≤ 3 sentences citing the evidence used (idle time, ownership status, cost). |
| **FR-RSN-03** | Agent MUST estimate monthly savings for each resource classified as safe_to_stop or safe_to_delete. |
| **FR-RSN-04** | The reasoning trace MUST be stored and surfaced in the UI approval panel. |
| **FR-RSN-05** | Agent MUST aggregate total estimated monthly savings across all resources in the plan. |

## 4.4  Human Approval UI (approve_node)

| **Requirement ID** | **Description** |
| --- | --- |
| **FR-UI-01** | React UI MUST display all findings in a sortable table with columns: Resource Name, Type, Region, Owner, Ownership Status, LLM Decision, Reasoning, Estimated Savings. |
| **FR-UI-02** | Each row MUST include Approve and Reject controls; bulk approve/reject MUST be supported. |
| **FR-UI-03** | Total estimated monthly savings MUST be displayed dynamically as the user approves/rejects individual items. |
| **FR-UI-04** | A collapsible Reasoning Trace Panel MUST expose the full LangSmith trace for each resource. |
| **FR-UI-05** | Execute button MUST be inactive until at least one action is approved; a dry-run preview MUST be shown before execution. |

## 4.5  Execution (execute_node)

| **Requirement ID** | **Description** |
| --- | --- |
| **FR-EXE-01** | Agent MUST stop (not delete) idle VMs upon approval; deletion requires a separate, explicit approval flow. |
| **FR-EXE-02** | Agent MUST release unused static IPs upon approval. |
| **FR-EXE-03** | Agent MUST flag orphaned disks for review and archive to Coldline Storage if they contain sensitive data (detected by Security Head analysis). |
| **FR-EXE-04** | Each execution step MUST be verified via GCP API before proceeding to the next. |
| **FR-EXE-05** | Agent MUST respect the rate limit of max 10 mutations per session (see Guardrails). |

## 4.6  Audit Trail (audit_node)

| **Requirement ID** | **Description** |
| --- | --- |
| **FR-AUD-01** | Every action — including rejected ones — MUST be logged with: timestamp, resource ID, action type, LLM reasoning, actor (human or agent), and outcome. |
| **FR-AUD-02** | Audit log MUST be exposed in the React UI as a real-time feed during execution. |
| **FR-AUD-03** | Audit log MUST be persisted to a local file and transmitted to LangSmith for observability. |
| **FR-AUD-04** | A before/after cost summary MUST be generated at the conclusion of each agent run. |

## 4.7  IAM Access Management (Access Head)

| **Requirement ID** | **Description** |
| --- | --- |
| **FR-IAM-01** | Access Head MUST accept natural-language IAM access requests (e.g., "I need BigQuery read access for fraud_transactions") and decompose them into specific GCP permissions. |
| **FR-IAM-02** | Access Head MUST apply the Principle of Least Privilege — synthesizing custom IAM roles rather than assigning overly broad predefined roles where possible. |
| **FR-IAM-03** | Custom roles MUST be scoped to specific resources via IAM Conditions (resource-level, not project-level, where the API supports it). |
| **FR-IAM-04** | Provisioning workflow MUST include: custom role creation → role binding → budget alert setup → 90-day access review scheduling → team documentation update. |
| **FR-IAM-05** | High-risk IAM changes (owner role, wildcard permissions) MUST trigger an escalation requiring team lead + security lead approval with a 4-hour auto-deny timeout. |

# 5. Non-Functional Requirements

| **Requirement ID** | **Category** | **Description** |
| --- | --- | --- |
| **NFR-01** | Performance | scan_node MUST complete discovery across a project with up to 100 resources in ≤ 60 seconds. |
| **NFR-02** | Performance | reason_node LLM calls MUST complete per-resource reasoning in ≤ 10 seconds per resource; full plan generation ≤ 3 minutes for 20 resources. |
| **NFR-03** | Reliability | Agent MUST handle GCP API rate limit errors with exponential backoff and retry (max 3 attempts). |
| **NFR-04** | Reliability | If any node fails, the agent MUST halt execution, log the error, and surface a human-readable failure message in the UI. |
| **NFR-05** | Security | Cerberus service account MUST follow least-privilege — granted only the GCP roles required for its specific scan and mutation operations. |
| **NFR-06** | Security | No GCP credentials MUST be stored in code or client-accessible configuration; credentials MUST be injected via environment variables or Secret Manager. |
| **NFR-07** | Usability | A first-time user MUST be able to run the full demo scenario with no prior Cerberus training, following only the README. |
| **NFR-08** | Observability | Full LangSmith trace MUST be available for every agent run, showing all node transitions, tool calls, and LLM inputs/outputs. |
| **NFR-09** | Deployability | Backend MUST deploy to Cloud Run; frontend MUST deploy to Firebase Hosting. Both MUST be reproducible via a single deploy script. |

# 6. Architecture

## 6.1  Tech Stack

| **Layer** | **Technology** | **Rationale** |
| --- | --- | --- |
| **LLM** | Gemini 1.5 Pro | All-GCP narrative consistency; strong function calling; native GCP integration. |
| **Agent Framework** | LangGraph | Structured node graph; built-in trace visibility for demo; conditional edges for guardrail handling. |
| **GCP APIs** | Python google-cloud-* libraries | Compute Engine, IAM, Billing, Cloud Asset Inventory — official SDK, stable, well-documented. |
| **Frontend** | React + Vite | Component-based approval UI; real-time audit log feed; reasoning trace panel. |
| **Backend** | FastAPI (Python) | Thin API layer between React UI and LangGraph agent; async-friendly. |
| **Observability** | LangSmith (free tier) | Full agent trace; decision point inspection; easy to demo during presentation. |
| **MCP Integration** | GCP IAM + Billing as MCP tools | Satisfies extra-credit criterion naturally; enables future extensibility to Jira, ServiceNow, PagerDuty. |
| **Deployment** | Cloud Run + Firebase Hosting | Same GCP project as demo sandbox; zero external dependencies; consistent narrative. |

## 6.2  LangGraph Node Architecture

| ┌─────────────┐ │   START     │  ← User input: "Analyze dev-project-X" └──────┬──────┘        │ ┌──────▼──────┐ │  scan_node  │  ← Compute, Disks, IPs — real GCP API calls └──────┬──────┘        │ ┌──────▼──────┐ │ enrich_node │  ← IAM API + Cloud Asset Inventory │ (ownership) │    Who owns it? Still active? └──────┬──────┘        │ ┌──────▼──────┐ │ reason_node │  ← Gemini LLM │ (LLM loop)  │    Per-resource decision + plain-English explanation └──────┬──────┘        │ ┌──────▼──────┐  ◄── React UI (approve / reject individual items) │approve_node │  ← Human-in-the-loop guardrail │   (HITL)    │    NEVER auto-executes without approval └──────┬──────┘        │ ┌──────▼──────┐ │execute_node │  ← GCP mutation APIs │   (act)     │    Stop VM, release IP, archive disk └──────┬──────┘        │ ┌──────▼──────┐ │  audit_node │  ← LangSmith trace + local audit log │  (observe)  │    Every action logged with reasoning + outcome └─────────────┘ |
| --- |

## 6.3  Multi-Agent Sub-Architecture (Three Heads)

For the full multi-agent implementation, the Cerberus Cortex orchestrates three specialized sub-agents:

| **Sub-Agent** | **Responsibilities** |
| --- | --- |
| **Access Head (IAM Guardian)** | IAM request decomposition, least-privilege role synthesis, custom role creation, access review scheduling, high-risk escalation. |
| **Cost Head (Budget Hound)** | Daily cost sweep, idle resource detection, right-sizing recommendations, budget alert management, savings estimation. |
| **Se****curity Head** | audit log analysis. |
| **Cerberus Cortex (Orchestrator)** | Multi-agent consensus for high-risk actions (quorum voting), session rate limiting, human escalation routing, final action decision. |

## 6.4  MCP Server Architecture

| Cerberus Cortex (Orchestrator)     │     ├── MCP Server: GCP IAM Manager     │   ├── List / grant / revoke roles     │   ├── Create custom roles     │   ├── Analyze permission usage     │   └── Generate IAM access reports     │     ├── MCP Server: GCP Cost Optimizer     │   ├── Query billing data     │   ├── Identify waste and idle resources     │   ├── Set and manage budget alerts     │   └── Recommend right-sizing actions     │     ├── MCP Server: GCP Security Scanner     │   ├── Analyze audit logs for anomalies     │     └── MCP Server: Ticketing (future)         ├── Create / update tickets         ├── Approval workflows         └── Audit trail integration |
| --- |

# 7. Guardrails & Safety Requirements

Guardrails are a first-class feature of Cerberus, not an afterthought. The system must be safe enough to run against real, active development projects.

| **Guardrail** | **Requirement** | **Implementation Approach** |
| --- | --- | --- |
| **Production Protection** | Agent MUST refuse to operate on any project whose ID does not match the dev-* allowlist pattern. | Project ID validation at START node before any API call; hard exit with user-facing error. |
| **Human Approval Required** | Agent MUST NOT execute any mutation without explicit human approval in the approve_node. | approve_node is always in the LangGraph path; no conditional bypass exists. |
| **No Owner = No Delete** | Resources classified as no_owner MUST be flagged for human review and MUST NOT be classified as safe_to_delete. | Guardrail enforced in reason_node system prompt and validated before execute_node. |
| **Session Rate Limit** | Agent MUST enforce a maximum of 10 mutations per session across all resource types. | Mutation counter tracked in LangGraph state; execute_node halts and notifies user when limit reached. |
| **Dry-Run Default** | Agent MUST default to dry-run mode; explicit user confirmation is required to switch to live execution. | UI toggle defaults to dry-run; live execution requires a secondary confirmation dialog. |
| **Audit Trail** | Every action — including approvals, rejections, and dry-run plans — MUST be logged with timestamp, resource, reasoning, and actor. | audit_node records to local JSON log and LangSmith simultaneously. |
| **Quorum for High-Risk** | Actions classified as high-risk (e.g., deleting resources with sensitive data, granting owner-level IAM) MUST require multi-head consensus (2 of 3 sub-agents agree). | CerberusGuardrails.quorum_required_actions enforced in Cortex before escalation to approve_node. |
| **Data-Sensitive Archival** | Resources identified as containing PII or sensitive data by the Security Head MUST be archived to Coldline Storage before deletion. | Security Head analysis runs in parallel with Cost Head; archival step inserted into execution chain before delete. |

# 8. Primary Use Case: New Data Scientist Onboarding

This scenario demonstrates the Access Head workflow and IAM synthesis capabilities.

## 8.1  Scenario

| **Actor** | Alice — new Data Scientist on the fraud-detection team |
| --- | --- |
| **Project** | nexus-tech-dev-3 |
| **Request** | Access to BigQuery datasets, Vertex AI notebooks, Cloud Storage buckets, and Pub/Sub topics |
| **Expected Outcome** | Minimum-privilege custom IAM role provisioned automatically with budget guardrails, access review schedule, and team documentation updated |

## 8.2  Access Request Decomposition

| **Resource** | **Requested Access** | **Cerberus Synthesized Permission** |
| --- | --- | --- |
| **BigQuery****: ****fraud_transactions** | Read | bigquery.datasets.get, bigquery.tables.getData |
| **BigQuery****: ****model_predictions** | Write | bigquery.tables.updateData |
| **Vertex AI Notebooks** | Create in us-central1 | vertexai.notebooks.create (region-scoped) |
| **Cloud Storage: gs://fraud-models-dev/** | Read/Write | storage.objects.* scoped to gs://fraud-models-dev/* |
| **Pub/Sub: model-deployments topic** | Publish | pubsub.topics.publish (specific topic ARN only) |

## 8.3  Provisioning Steps (Automated)

- Create custom IAM role fraud-detection-data-scientist-dev in nexus-tech-dev-3

- Bind role to alice@nexustech.ai with IAM Conditions scoping to specific resources

- Create Vertex AI notebook instance with team labels (team=fraud-detection, owner=alice)

- Set up budget alert for Alice's resources ($500/month limit, notify at 80%)

- Schedule 90-day access review in calendar

- Update team onboarding documentation in Confluence

# 9. Success Metrics

| **Metric** | **Target** |
| --- | --- |
| **Agent loop executes end-to-end** | Zero manual intervention required from scan initiation through audit log completion. |
| **LLM reasoning quality** | Each decision explained in ≤ 3 sentences, always citing at least one piece of quantitative evidence (hours idle, cost, owner status). |
| **Demo stability** | Agent runs cleanly 3× in a row on demo day on the designated GCP sandbox. |
| **Guardrail reliability** | Zero mutations to production projects (nexus-tech-prod or any non-dev-* project) in any test run. |
| **Waste identification** | Identifies ≥ $500/month in recoverable waste on the demo GCP sandbox. |
| **IAM resolution time** | Access provisioning workflow completes in ≤ 5 minutes (vs. ~45 minutes manually). |
| **Observability** | Full LangSmith trace visible and inspectable for every demo run without additional configuration. |
| **Cost reduction target** | Dev environment waste reduced from ~30% to ≤ 10% of GCP spend over 30-day measurement period. |

# 10. One-Week Build Plan

| **Day** | **Focus Area** | **Key Deliverables** |
| --- | --- | --- |
| **Day 1** | GCP Foundation | GCP sandbox setup; Python API wiring for VMs, disks, IPs, IAM owners, and billing data; credentials and auth verified. |
| **Day 2** | LangGraph Skeleton | 5-node graph wired up; mock data flowing end-to-end; state management confirmed; conditional edges working. |
| **Day 3** | Gemini Integration | reason_node connected to Gemini 1.5 Pro; prompt engineering for per-resource decisions; reasoning quality validated on mock data. |
| **Day 4** | React UI | Resource table with approve/reject; reasoning trace panel; audit log feed; dry-run toggle; savings estimate display. |
| **Day 5** | Guardrails + Observability | All 6 guardrails implemented and tested; LangSmith integration live; dry-run mode verified; rate limiting confirmed. |
| **Day 6** | Deployment + Demo Data | Cloud Run backend deploy; Firebase Hosting frontend deploy; demo GCP sandbox seeded with realistic idle resources; README written. |
| **Day 7** | Polish + Demo Prep | Demo script dry-run 3×; edge case fixes; 5-minute pitch prepared; architecture diagram finalized. |

# 11. Explicitly Out of Scope

The following features are intentionally excluded to maintain build quality and demo clarity within the hackathon timeline:

| **Feature** | **Reason for Exclusion** |
| --- | --- |
| **Security compliance reporting** | Hard to demo compellingly in 5 minutes; adds implementation complexity with low visible impact. |
| **Jira / ****ServiceNow**** integration** | Adds external setup friction with near-zero demo impact for evaluators. |
| **Slack bot interface** | React UI is faster to build and easier to demo visually in a live presentation. |
| **Firestore**** / persistent state** | In-memory LangGraph state is sufficient; Firestore adds infrastructure with no demo value. |
| **Multi-project orchestration** | One project done exceptionally well is more compelling than three projects done poorly. |
| **Non-GCP cloud providers (AWS/Azure)** | All-GCP narrative is cleaner and consistent with Gemini + Cloud Run deployment choice. |

# 12. Demo Script (5 Minutes)

| **Scene** | **Content** |
| --- | --- |
| **Scene 1 — The Problem (45s)** | Show GCP console: 8 idle VMs, 3 orphaned disks, $1,800 in monthly dev waste. Emphasize: "I have no idea who owns half of these." Human problem, not a tooling problem. |
| **Scene 2 — Agent Activation (30s)** | Type "Analyze dev-project-3" in the React UI. Watch LangSmith trace light up in real-time as nodes execute sequentially. Narrate each node transition. |
| **Scene 3 — LLM Reasoning (2m)** | Show the reasoning panel: "This VM is idle 5 days and owned by someone who left the team — Gemini says safe to stop, saving $140/mo." Then: "This disk has no owner — flagged for review, not auto-deleted. That is the guardrail working." |
| **Scene 4 — Approve and Execute (1m)** | Approve 5 of 8 actions. Click Execute. Watch audit log populate in real-time. Show before/after savings: $1,200/month recovered. |
| **Scene 5 — Observability and Wrap (45s)** | Switch to LangSmith — show full agent trace, decision points, tool calls. Close: "Every decision the agent made is inspectable. This is production-grade cloud AI." |

# 13. Hackathon Criteria Mapping

| **Criterion** | **How Cerberus Delivers It** | **Status** |
| --- | --- | --- |
| **Autonomy** | One prompt → full scan → plan → execute with no hand-holding | Core ✅ |
| **Independent Decision-Making** | LLM weighs 3+ signals per resource (idle time, ownership, cost) to decide action — not a hardcoded rule | Core ✅ |
| **LLM-Powered Reasoning** | Gemini 1.5 Pro active at reason_node; explains every decision in natural language | Core ✅ |
| **Guardrails (Extra Credit)** | 6 distinct safety mechanisms: production protection, HITL, no-owner-no-delete, rate limit, dry-run, audit trail | Extra Credit ✅ |
| **MCP Integration (Extra Credit)** | GCP IAM + Billing exposed as MCP tools; extensible to Jira, ServiceNow, PagerDuty | Extra Credit ✅ |
| **Observability (Extra Credit)** | LangSmith trace shows full agent reasoning path, all tool calls, all decision points | Extra Credit ✅ |
| **Cloud Deployment (Extra Credit)** | Cloud Run (backend) + Firebase Hosting (frontend) — same GCP project as demo sandbox | Extra Credit ✅ |

# 14. IAM Access Request Workflow

This section specifies the end-to-end workflow executed by the Cerberus GCP Admin Agent when a user requests read or write access to a GCP resource. The workflow is context-enriched: before making any access decision, the agent retrieves the requester’s ticket and historical metadata, ingests signals from the Cost Optimization Agent, and analyzes live resource state — including VM activity, ownership, and team/project affiliation — to produce a justified, least-privilege IAM recommendation and a full set of output artifacts.

| **Scope:  **This workflow applies to GCP dev/sandbox projects only (nexus-tech-dev-*). Production project access requests require a separate elevated-approval workflow. |
| --- |

| **Dimension** | **Value** |
| --- | --- |
| **Trigger** | User submits a read or write access request to a GCP resource via the Cerberus UI or ticketing system. |
| **Primary ****Agent** | GCP Admin Agent (Access Head) — orchestrated by the Cerberus Cortex. |
| **Supporting Agent** | Cost Optimization Agent (Cost Head) — provides resource utilisation signals and ownership context. |
| **Output: IAM Provisioning** | Live GCP API call to create and bind a custom IAM role with minimum required permissions and IAM Conditions. |
| **Output: Access Decision Report** | Structured document capturing decision, evidence, role definition, conditions, approver, and justification. |
| **Output: Ticket Update** | Source ticket updated with decision outcome, provisioned role name, conditions, and plain-English reasoning summary. |
| **Output: Audit Log Entry** | Every action — approval, denial, escalation, provisioning — logged with timestamp, actor, resource, and LangSmith trace reference. |

## 14.1  Five-Phase Agent Loop

The workflow executes autonomously across five sequential phases, with a mandatory human-approval gate before any IAM mutation is applied:

| TRIGGER:  User submits access request (read / write) for a GCP resource PHASE 1  -- Ticket Retrieval & Requester Profiling             -> Fetch ticket: requester email, role/designation, team, project             -> Pull historical IAM metadata: prior grants, reviews, violations             -> Classify request risk: LOW / MEDIUM / HIGH PHASE 2  -- Cost Agent Signal Ingestion             -> Query Cost Optimization Agent for target resource utilisation             -> Ingest: CPU/memory usage, idle flags, cost-per-resource, owner labels             -> Merge into Enriched Resource Context Record PHASE 3  -- Resource State Analysis             -> Evaluate Compute Engine VMs: RUNNING_ACTIVE / RUNNING_IDLE / STOPPED             -> Resolve ownership: active_owner / departed_owner / no_owner             -> Determine team affiliation and project sensitivity classification PHASE 4  -- IAM Recommendation Engine (Gemini LLM)             -> Score request against: user role, project requirements, PoLP             -> Synthesize minimum-privilege custom IAM role with IAM Conditions             -> Route to: AUTO_APPROVE / HUMAN_REVIEW / ESCALATE / DENY PHASE 5  -- Approval Gate & Execution             -> Present decision + reasoning to approver in Cerberus UI             -> On approval: provision IAM role, update ticket, write audit log             -> Generate Access Decision Report |
| --- |

## 14.2  Phase 1 — Ticket Retrieval & Requester Profiling

The agent first retrieves the source ticket to build a complete requester profile, then pulls historical metadata logs. This context is the foundation for all subsequent reasoning.

### Ticket Fields Retrieved

| **Field** | **Description** |
| --- | --- |
| **requester_email** | Corporate email of the requesting user (e.g., alice@nexustech.ai). |
| **requester_role** | Current job title / designation (e.g., Data Scientist, ML Engineer, DevOps Lead). |
| **requester_team** | Team membership at time of request (e.g., fraud-detection, platform-engineering). |
| **target_resource** | Full GCP resource path, type, and name (e.g., projects/nexus-tech-dev-3/instances/gce-fraud-ml-01). |
| **access_type** | Requested level: read, write, or read/write. |
| **justification** | Free-text business justification provided by the requester. |
| **requested_duration** | Temporary (with expiry date) or permanent. |

### Historical Metadata Logs Retrieved

| **Log Type** | **Purpose** |
| --- | --- |
| **Prior IAM grants** | All roles previously granted to this user across dev projects — identifies access creep. |
| **Access review outcomes** | Results of scheduled 90-day access reviews — flags users with overdue reviews. |
| **Policy violation history** | Prior IAM violations or unauthorised access attempts linked to this user. |
| **Resource interaction logs** | Cloud Audit Log entries showing which resources this user actually accessed in the last 90 days. |
| **Team membership history** | Team transitions recorded in the identity system — surfaces recently departed members requesting lingering access. |

### Risk Classification

| **Risk Tier** | **Trigger Criteria** | **Routing** |
| --- | --- | --- |
| **LOW** | Standard role; no prior violations; team affiliation confirmed; resource in known project scope. | Eligible for auto-approval after LLM reasoning. Human notified, not blocked. |
| **MEDIUM** | Write to sensitive dataset; overdue access review; access creep; new team member; cross-team resource. | Requires explicit human approval in Cerberus UI before provisioning. |
| **HIGH** | Owner-level/wildcard permissions; prior violations; no_owner resource; production-adjacent scope. | Escalated to team lead + security lead. 4-hour auto-deny. Agent does not proceed. |

## 14.3  Phase 2 — Cost Agent Signal Ingestion

The GCP Admin Agent queries the Cost Optimization Agent (Cost Head) to retrieve current resource utilisation data. Access decisions are informed by actual usage context, not just the stated request. The merged output forms the Enriched Resource Context Record passed to all downstream phases.

| **Signal** | **GCP Source** | **Purpose in Access Decision** |
| --- | --- | --- |
| **VM instance ****state** | Compute Engine Instances API | Determines if the resource is actively running or idle. |
| **CPU / memory utilisation (7-day ****avg****)** | Cloud Monitoring metrics API | Low utilisation on a resource where write access is requested raises a review flag. |
| **Resource cost**** per month** | Cloud Billing API | High-cost resources warrant additional scrutiny for write access. |
| **Owner labels** | GCP Resource Labels + Asset Inventory | Identifies declared owner for cross-referencing with IAM records. |
| **Idle flag** | Cost Head internal classification | Boolean: resource already flagged for cleanup. If true, write access includes a reviewer note. |
| **Last active timestamp** | Cloud Audit Logs | Surfaces resources unused for N days; informs whether access is genuinely needed now. |

## 14.4  Phase 3 — Resource State Analysis

### Compute Engine VM State Evaluation

| **VM State** | **Agent Interpretation ****&**** Action** |
| --- | --- |
| **RUNNING — high utilisation (****>**** 40%)** | Resource actively in use. Write access request is plausible. Proceed to ownership check. |
| **RUNNING — low utilisation (****<**** ****10%)** | Underutilised despite running. Agent notes discrepancy; write access requires additional justification. |
| **IDLE (flagged by Cost Agent)** | Negligible activity for 72+ hours. Write access flagged for human review — may indicate a misrouted request. |
| **STOPPED** | Read access may be granted for archival purposes. Write access requires explicit justification and MEDIUM risk routing. |
| **UNKNOWN** | State cannot be determined. Request elevated to MEDIUM risk tier regardless of prior classification. |

### Ownership Resolution

Ownership is resolved via a four-step priority-ordered lookup chain: (1) GCP resource labels (owner, created-by, team), (2) Cloud Asset Inventory resource metadata, (3) IAM binding history, (4) Cloud Audit Logs last mutation actor.

| **Ownership Status** | **Defini****tion** | **Impact on Access Decision** |
| --- | --- | --- |
| **active_owner** | Owner resolved; currently holds active IAM membership. | Normal processing. Owner can be contacted for context if needed. |
| **departed_owner** | Owner resolved but no longer holds active IAM membership. | Risk elevated to MEDIUM. Requester must provide explicit justification. Owner’s permissions reviewed in parallel. |
| **no_owner** | Owner cannot be determined via any lookup method. | Access request BLOCKED. Resource flagged for human review. Agent does not proceed to IAM recommendation. |

| **Guardrail:  **Resources classified as no_owner are never auto-approved or auto-denied. They are always routed to human review — consistent with the Cerberus core safety principle that unowned resources require human judgment before any access change. |
| --- |

### Team & Project Affiliation

| **Check** | **Logic** |
| --- | --- |
| **Team affiliation match** | Compare requester team against the resource’s team label. Mismatch triggers a cross-team access flag (MEDIUM risk minimum). |
| **Project scope validation** | Confirm target resource resides in a project where the requester’s team has an established IAM footprint. |
| **Sensitivity classification** | Classify project as STANDARD, SENSITIVE, or RESTRICTED based on data labels and PII indicators. RESTRICTED requires Security Head sign-off. |
| **Active team membership** | Cross-reference requester email against current team roster. Confirms the user is still an active member of the team they claim. |

## 14.5  Phase 4 — IAM Recommendation Engine (LLM Reasoning)

With the Enriched Resource Context Record complete, Gemini 1.5 Pro evaluates the access request and generates a justified IAM recommendation. The LLM weighs all enriched signals against the Principle of Least Privilege to synthesize the narrowest permission set that satisfies the legitimate need.

### Decision Outcomes

| **Decision** | **Trigger Conditions** | **Agent Action** |
| --- | --- | --- |
| **AUTO_APPROVE** | Risk LOW; team match confirmed; VM active; owner active; permissions within role baseline. | Synthesize custom role. Route to approve_node for team lead notification (non-blocking). Provision on acknowledgment. |
| **HUMAN_REVIEW** | Risk MEDIUM; cross-team access, idle VM, departed owner, write to sensitive dataset, or access creep detected. | Present full reasoning + evidence to designated approver in Cerberus UI. Block provisioning until explicit approval. |
| **ESCALATE** | Risk HIGH; owner-level permissions; prior violations; no_owner resource; RESTRICTED project. | Route to team lead + security lead. 4-hour auto-deny. Agent generates escalation summary with evidence bundle. |
| **DENY** | Permissions exceed any legitimate need; resource in production scope; fundamental PoLP violation. | Immediate denial with documented reasoning. Ticket closed. Audit log written. No escalation path. |

### LLM Reasoning Output (AccessDecisionReasoning)

| AccessDecisionReasoning {   decision:          "HUMAN_REVIEW"   risk_tier:         "MEDIUM"   confidence:        0.82   evidence_summary: [     "VM gce-fraud-ml-01 is RUNNING but CPU utilisation is 12.4% over 7 days.",     "Resource owner bob@nexustech.ai departed the team on 2025-02-14.",     "Alice has no prior IAM grants in nexus-tech-dev-3 (first-time access).",     "Team affiliation matches: alice is active on fraud-detection team."   ]   recommended_role:  "fraud-ds-gce-readwrite-dev3-alice"   permissions:       ["compute.instances.get", "compute.instances.start",                       "compute.instances.stop", "compute.instances.setMetadata"]   conditions:        ["resource.name == gce-fraud-ml-01", "expiry: 2025-06-27"]   justification:    "Alice is an active fraud-detection team member requesting write                     access to a team-project VM. Low CPU utilisation (12.4%) and a                     departed prior owner warrant human review. Permissions are scoped                     to the specific instance only." } |
| --- |

## 14.6  Phase 5 — Approval Gate, Provisioning & Output Artifacts

### Provisioning Steps (On Approval)

- Create custom IAM role in the target project with synthesized permissions and IAM Conditions.

- Bind role to requester email with resource-level and time-bound conditions as specified.

- Set up a budget alert for the requester’s resource usage ($500/month default, configurable per team).

- Schedule a 90-day access review — creates a review ticket automatically.

- Update the source ticket: decision, role name, conditions, expiry (if temporary), reasoning summary.

- Write audit log entry (see below).

- Send confirmation to requester with access summary and getting-started link.

### Audit Log Entry Format

| AuditLogEntry {   timestamp:      "2025-03-27T09:14:32Z"   workflow_id:    "WF-20250327-1042"   ticket_id:      "CERB-1042"   actor:          "cerberus-admin-agent"   action:         "IAM_ROLE_PROVISIONED"   resource:       "projects/nexus-tech-dev-3/instances/gce-fraud-ml-01"   requester:      "alice@nexustech.ai"   role_granted:   "fraud-ds-gce-readwrite-dev3-alice"   conditions:     ["resource-scoped", "expiry:2025-06-27"]   approver:       "charlie@nexustech.ai (team lead)"   approval_ts:    "2025-03-27T09:11:05Z"   reasoning_ref:  "langsmith://trace/WF-20250327-1042"   outcome:        "SUCCESS" } |
| --- |

## 14.7  Functional Requirements

| **Req**** ID** | **Phase** | **Requirement** | **Priority** |
| --- | --- | --- | --- |
| **FR-WF-01** | Phase 1 | Agent MUST retrieve all ticket fields and pull requester’s historical IAM metadata before beginning analysis. | MUST |
| **FR-WF-02** | Phase 1 | Agent MUST classify each request as LOW, MEDIUM, or HIGH risk before proceeding to Phase 2. | MUST |
| **FR-WF-03** | Phase 2 | Agent MUST query the Cost Optimization Agent; a stale cost record (> 24 hours) MUST trigger a fresh API pull. | MUST |
| **FR-WF-04** | Phase 2 | Agent MUST merge ticket data and cost signals into a single Enriched Resource Context Record before Phase 3. | MUST |
| **FR-WF-05** | Phase 3 | Agent MUST evaluate VM instance state and classify as RUNNING_ACTIVE, RUNNING_IDLE, STOPPED, or UNKNOWN. | MUST |
| **FR-WF-06** | Phase 3 | Agent MUST resolve resource ownership via the four-step lookup chain. Resources with no_owner status MUST be blocked from IAM recommendation and flagged for human review. | MUST |
| **FR-WF-07** | Phase 3 | Agent MUST determine team and project affiliation and flag cross-team access as MEDIUM risk minimum. | MUST |
| **FR-WF-08** | Phase 4 | LLM MUST produce a structured AccessDecisionReasoning object citing at least two pieces of quantitative evidence. | MUST |
| **FR-WF-09** | Phase 4 | Agent MUST synthesize a custom IAM role with minimum required permissions and resource-level IAM Conditions. Predefined broad roles MUST NOT be assigned where narrower alternatives exist. | MUST |
| **FR-WF-10** | Phase 5 | No IAM mutation MUST be applied without explicit human approval through the Cerberus UI. | MUST |
| **FR-WF-11** | Phase 5 | On approval, agent MUST execute all seven provisioning steps in sequence, verifying each before proceeding. | MUST |
| **FR-WF-12** | Phase 5 | Agent MUST generate an Access Decision Report and audit log entry for every workflow execution, regardless of outcome. | MUST |

## 14.8  Illustrative Scenario

| **Ticket ID** | CERB-1042 |
| --- | --- |
| **Requester** | alice@nexustech.ai — Data Scientist, fraud-detection team |
| **Target Resource** | projects/nexus-tech-dev-3/instances/gce-fraud-ml-01 |
| **Access Type** | Read/Write |
| **Justification** | Need to run and configure ML training jobs on the fraud detection pipeline VM. |

| Phase 1: Risk initially LOW. Elevated to MEDIUM (first-time access, write requested). Phase 2: VM RUNNING. CPU 12.4% (7d avg). Monthly cost $142. Owner: bob@nexustech.ai. Phase 3: VM state = RUNNING_IDLE. Owner: departed_owner (left 2025-02-14). Team match: confirmed. Phase 4: Decision = HUMAN_REVIEW. Role: fraud-ds-gce-readwrite-dev3-alice.          Conditions: resource-scoped to gce-fraud-ml-01, expiry 2025-06-27.          Justification: Active team member; low utilisation and departed owner warrant review. Phase 5: Approved by charlie@nexustech.ai (09:11 UTC). IAM role provisioned.          Budget alert set. 90-day review scheduled. Ticket updated. Audit log written. |
| --- |

# 15. Architecture Candidates

Three structurally different approaches to the Cerberus problem. Each reflects a different set of priorities and a different bet about where complexity is better to absorb. They are evaluated on the same eight dimensions to make tradeoffs explicit.

## 15.1  Architecture 1 — The Pipeline (Linear Chain)

### What It Is

A strictly sequential, stateless pipeline where each stage hands enriched data to the next. No agent framework — discrete Python functions or microservices chained together. Each stage reads input, does one thing, writes output.

| GCP Scanner     ↓ Ownership Enricher     ↓ Decision Engine (LLM — one Gemini call per resource)     ↓ Approval UI  ←→  Human     ↓ Executor     ↓ Audit Logger |
| --- |

### Key Technology Choices

| **Component** | **Choice** |
| --- | --- |
| **Scanner** | Python google-cloud-compute / billing libraries; outputs flat resource list |
| **Enricher** | GCP IAM API + Cloud Asset Inventory; appends owner fields to each record |
| **Decision Engine** | Single Gemini API call per resource with structured JSON output; no looping |
| **Approval UI** | React table; approve / reject per row; totals displayed |
| **Executor** | GCP mutation APIs; sequential; stops at rate limit |
| **Audit Logger** | Append-only JSON file; one entry per action |
| **Orchestration** | None — plain Python function calls or FastAPI endpoints |
| **State** | In-memory dict passed between stages; no persistence layer |

### What It Makes Easy

- Debugging. At any stage you can inspect exactly what data entered and what came out.

- Testing each stage in isolation — mock inputs, assert outputs.

- Swapping individual components. Replace the LLM, change ownership lookup logic, or add a new resource type without touching adjacent stages.

- Build speed. No framework abstractions to learn or fight. Fastest path to a working demo.

### What It Makes Hard

- Handling partial failures mid-pipeline. If enrichment fails for one resource, the pipeline has no clean recovery path short of restarting.

- Fallback logic. If the primary ownership lookup returns nothing, the pipeline cannot decide to try IAM history next — that branch must be pre-programmed.

- Cross-resource reasoning. Each LLM call is independent. The model cannot observe that two resources appear related and reason about them as a unit.

- Re-runs after rejection. If a human rejects an action and wants more context, there is no mechanism to re-enrich that single resource without restarting from scratch.

### Constraints Satisfied

| **Constraint** | **Status** |
| --- | --- |
| **Production protection (project-ID ****allowlist****)** | Satisfied — gate at scanner entry |
| **Human approval required (HITL)** | Satisfied — approval UI is a stage in the chain |
| **Dry-run default** | Satisfied — simply do not invoke the executor stage |
| **Audit trail** | Satisfied — audit logger is the final stage |
| **Session rate limiting** | Satisfied — counter in the executor |
| **No owner = flag, not delete** | Partially satisfied — requires explicit branching; not natural to the model |
| **LLM reasoning across related resources** | Not satisfied — each call is isolated; no shared context between resource decisions |

### What You Give Up vs. the Other Options

Compared to the Agent Loop: the pipeline cannot adapt its execution path based on what it discovers. It cannot decide mid-run to try an alternative lookup or collect more information before classifying a resource. Every decision tree must be pre-programmed.

Compared to the Multi-Head Council: there is no separation of cost, ownership, and security concerns. A single LLM prompt carries all three, which produces muddier reasoning as the prompt grows and makes it harder to improve one concern without affecting others.

## 15.2  Architecture 2 — The Agent Loop (Autonomous Reasoner)

### What It Is

A single LLM agent — built on LangGraph with a ReAct-style execution loop — that has access to a toolbox and decides for itself what to call, in what order, and when it has gathered enough information to produce a recommendation. The agent is given a goal and tools; the LLM determines the execution path.

| Goal: "Analyse dev-project-3 and produce a cleanup plan" Tools available to the agent:   list_compute_resources(project_id)   get_billing_data(resource_id)   lookup_owner_by_label(resource_id)   lookup_owner_by_iam_history(resource_id)   lookup_owner_by_audit_log(resource_id)   check_iam_membership(email)   classify_resource(enriched_record)  →  decision + reasoning   flag_for_review(resource_id, reason) Human approval gate — hard interrupt; agent cannot bypass LangSmith traces every tool call and reasoning step |
| --- |

### Key Technology Choices

| **Component** | **Choice** |
| --- | --- |
| **Agent framework** | LangGraph — structured node graph with conditional edges; built-in trace visibility |
| **LLM** | Gemini 1.5 Pro with function calling; ReAct prompt pattern |
| **Tool layer** | Python functions wrapping GCP client libraries; each tool is a LangGraph node |
| **Observability** | LangSmith free tier — every tool call, LLM input/output, and decision step traced |
| **Approval UI** | React — hard interrupt in LangGraph; agent state serialised and handed off |
| **State** | LangGraph state object; enriched context record built incrementally by the agent |
| **Audit trail** | LangSmith trace is the audit trail; supplemented by local append-only log |

### What It Makes Easy

- Handling the messy middle cases. If the primary ownership lookup returns nothing, the agent decides to try IAM history next — without that fallback being pre-programmed.

- Cross-resource reasoning. The agent can notice that two resources appear related and reason about them together in a single classification call.

- The observability story. LangSmith surfaces the full reasoning chain — every tool call, every LLM thought — making the agent’s decision process inspectable and auditable by default.

- Applying the “no owner = flag for review” guardrail. The LLM applies this as a rule it reasons about contextually rather than a hard code branch.

### What It Makes Hard

- Reliability and predictability. An agent that decides its own execution path can also decide wrong. The same resource may be classified differently across two runs depending on how the LLM reasons through it.

- Bounding cost and latency. A pipeline with 20 resources makes a predictable number of LLM calls. An agent may make 3× that number if it decides to run additional lookups. Cost per run is harder to estimate.

- Testing. You cannot unit test “what the agent decides to do next” in a straightforward way. You are testing emergent behaviour, which requires evaluation harnesses rather than simple assertions.

- Demo stability. Nondeterminism is a real risk for a live presentation. The agent may take a different path on the third demo run than on the first.

### Constraints Satisfied

| **Constraint** | **Status** |
| --- | --- |
| **Production protection** | Satisfied — enforced in the list_compute_resources tool; hard check before any scan |
| **Human approval required (HITL)** | Satisfied — hard interrupt node in LangGraph; agent state is paused, not bypassed |
| **No owner = flag, not delete** | Satisfied naturally — LLM reasoning applies the rule contextually, not as a code branch |
| **Dry-run default** | Satisfied — execution tool simply no-ops in dry-run mode |
| **Audit trail** | Satisfied — LangSmith trace + local log |
| **Session rate limiting** | Partially satisfied — mutation counter in the execution tool, but LLM call count is unbounded |
| **Demo stability across 3 runs** | Partially satisfied — LLM temperature can be set to 0, but tool call path may still vary |

### What You Give Up vs. the Other Options

Compared to the Pipeline: you give up predictability and ease of debugging. When the agent produces a wrong classification, tracing why requires reading through a LangSmith reasoning chain rather than inspecting a deterministic function output. Failures are emergent, not localised.

Compared to the Multi-Head Council: a single agent carrying the full context of cost, ownership, and security reasoning will eventually produce muddier decisions as complexity grows. It has no natural boundary between what it knows about cost and what it knows about risk. Every new concern adds to the prompt context rather than being handled by a dedicated component.

## 15.3  Architecture 3 — The Multi-Head Council (Specialised Agents + Orchestrator)

### What It Is

Three specialised sub-agents — Cost Head, Access Head, Security Head — each with a narrow domain of concern, coordinated by a central Cortex. Each head operates with its own tools and prompt context. The Cortex aggregates their verdicts and applies consensus rules before routing to the human approval gate.

| Cortex (orchestrator)   │   +-- Cost Head     →  "Is this idle? What does it cost? Recommend stop/delete?"   │   Tools: list_vms, get_billing, get_utilisation, flag_idle   │   +-- Access Head   →  "Who owns this? Are they active? What access do they hold?"   │   Tools: lookup_owner, check_iam_membership, get_access_history   │   +-- Security Head →  "Sensitive data? Safe to delete? Any policy violations?"       Tools: classify_data_sensitivity, scan_policy, check_compliance Cortex logic:   - Aggregates three verdicts per resource   - Applies quorum rule for high-risk actions (2 of 3 heads must agree)   - Routes conflicting verdicts to human review   - Passes consensus to approval gate |
| --- |

### Key Technology Choices

| **Component** | **Choice** |
| --- | --- |
| **Agent framework** | LangGraph multi-agent graph; one subgraph per head; Cortex as the supervisor node |
| **LLM** | Gemini 1.5 Pro; same model with distinct system prompts per head |
| **MCP integration** | GCP IAM + Billing exposed as MCP servers; each head’s tools map naturally to an MCP server |
| **Cortex consensus logic** | Deterministic rules applied over structured head verdicts; not LLM-driven |
| **State** | Shared LangGraph state object; each head appends its verdict; Cortex reads all three |
| **Observability** | LangSmith traces each head independently; Cortex decision is a separate trace node |
| **Approval UI** | React; full multi-head verdict visible per resource — approver sees all three perspectives |

### What It Makes Easy

- Evolving each concern independently. The Cost Head can be improved — new resource types, better utilisation thresholds — without touching the Security Head’s logic.

- Genuine multi-perspective review for high-risk decisions. A resource that looks cheap to delete (Cost Head agrees) but contains PII (Security Head flags) is caught structurally, not by a hardcoded rule.

- MCP integration. Each head’s tool surface is the natural place to expose a GCP capability as an MCP server. The separation of concerns maps directly onto the MCP server architecture.

- Inspectable reasoning. You can point at exactly which head produced a given verdict and why. The human approver sees three independent perspectives, not one opaque recommendation.

### What It Makes Hard

- Build complexity. This is the hardest of the three to assemble. Coordinating multiple agents, defining clean interfaces between the Cortex and each head, and handling the case where a head fails or produces an ambiguous verdict all require significant upfront design.

- The Cortex consensus logic. How does the Cortex weight conflicting verdicts? What happens when the Cost Head says “safe to delete” and the Security Head says “archive first”? That logic is non-trivial and is the hardest single piece to get right.

- Latency. Three heads running per resource — even in parallel — is slower than one agent or one pipeline. 20 resources × 3 heads × LLM call latency adds up quickly.

- Debugging multi-agent failures. A wrong recommendation may originate in any of the three heads or in the Cortex aggregation. Tracing across multiple reasoning chains simultaneously is harder than tracing a single agent.

### Constraints Satisfied

| **Constraint** | **Status** |
| --- | --- |
| **Production protection** | Satisfied — Cortex validates project ID before invoking any head |
| **Human approval required (HITL)** | Satisfied — approval gate sits after Cortex consensus, before execution |
| **No owner = flag, not delete** | Satisfied structurally — Access Head is responsible for this verdict; Cortex enforces it |
| **Sensitive data before deletion** | Satisfied structurally — Security Head classification runs before any delete recommendation |
| **Quorum for high-risk actions** | Satisfied — Cortex enforces 2-of-3 agreement rule before escalating to human |
| **MCP integration (extra credit)** | Fully satisfied — each head maps naturally to one MCP server |
| **Demo stability across 3 runs** | Partially satisfied — three agents coordinating introduces more failure points than one |
| **One-week build timeline** | Not fully satisfied — this is the architecture that is most at risk of being incomplete at demo time |

### What You Give Up vs. the Other Options

Compared to the Pipeline: you give up simplicity and build speed. The multi-head design requires upfront decisions about how concerns are divided — and that division will sometimes be the wrong cut. Some decisions genuinely span all three concerns simultaneously.

Compared to the Agent Loop: you give up the flexibility of a single agent that can reason holistically. The multi-head design forces every decision to be routed through the Cortex aggregation layer, which adds latency and a new source of failure. An agent can fluidly cross concern boundaries; the council cannot.

## 15.4  Comparison Summary

Colour coding: green = favourable for the Cerberus use case, amber = neutral or context-dependent, red = unfavourable.

|  | **Pipeline** | **Agent Loop** | **Multi-Head Council** |
| --- | --- | --- | --- |
| **Build complexity** | Low | Medium | High |
| **Predictability** | High | Low | Medium |
| **Handles messy cases** | Poorly | Well | Well |
| **Debuggability** | High | Medium | Low |
| **Separation of concerns** | None | None | Strong |
| **Demo reliability** | High | Medium | Medium |
| **Scales with complexity** | Poorly | Moderately | Well |
| **Guardrails feel natural** | No — bolted on | Yes — reasoned | Yes — structural |

**Core ****tradeoff****: ***the** Pipeline gives certainty at the cost of rigidity. The Agent Loop gives adaptability at the cost of predictability. The Multi-Head Council gives clean architecture at the cost of build time. The choice depends on which failure mode you are most afraid o**f.*

# 16. Architecture Candidates — Detailed Evaluation

Three fundamentally different architectural approaches were evaluated for Cerberus. Each represents a distinct bet on where complexity should live and what failure modes are acceptable. This section documents each candidate in full so the selected architecture can be understood in context of the alternatives considered.

## 16.1  Candidate A — The Pipeline (Linear Chain)

### What it is

A strictly sequential, stateless processing chain where each stage accepts enriched data from the previous stage, performs a single responsibility, and passes output forward. No agent framework — only discrete Python functions or microservices chained in fixed order. The LLM is called once per resource at the reasoning stage with a structured prompt and returns a structured JSON classification. Nothing loops back.

| GCP Scanner     ↓ Ownership Enricher     ↓ Decision Engine  (Gemini — one call per resource, structured in/out)     ↓ Approval UI  (React table: approve / reject rows)     ↓ Executor     ↓ Audit Logger |
| --- |

Technology choices are deliberately conservative: Python scripts, direct Gemini API calls, FastAPI to serve the UI, flat JSON or SQLite for inter-stage state. No orchestration framework.

### What it makes easy

- Debugging — at any point, the exact data that entered and left a stage can be inspected independently.

- Failure isolation — if ownership enrichment breaks, the scanner output is unaffected and still valid.

- Testing each stage in isolation with known inputs and expected outputs.

- Extending a single stage (e.g. swapping the LLM, adding a new resource type) without touching the rest of the chain.

- Build speed — no framework abstractions to learn or fight; a competent Python developer can wire this in a day.

### What it makes hard

- Handling the messy middle cases. The pipeline assumes resources flow cleanly through all stages. In practice, some ownership lookups fail and require fallback methods, some decisions need context from earlier stages not passed forward, and some resources will be ambiguous in ways the fixed sequence cannot anticipate.

- The approval loop is awkward. If a human rejects an action and wants more context, or new information surfaces mid-approval, the pipeline has no way to re-run partial stages without restarting from scratch.

- Cross-resource reasoning. Each LLM call is independent, so the model cannot reason about related resources together (e.g. a disk and VM that appear to be part of the same abandoned experiment).

- The no-owner guardrail requires explicit branching logic rather than emerging naturally from the process, which introduces a special-case code path that can be forgotten or broken.

### Constraints satisfied

| **Guardrail / Constraint** | **Status** | **Notes** |
| --- | --- | --- |
| Production protection | **Satisfies** | Project-ID allowlist gate added at the scanner stage before any API calls proceed. |
| Human approval required | **Satisfies** | Approval is a discrete stage in the chain; executor cannot run without its output. |
| Dry-run default | **Satisfies** | Executor stage is simply not invoked in dry-run mode. |
| Audit trail | **Satisfies** | Each stage writes a log entry before passing control to the next. |
| Session rate limiting | **Satisfies** | Mutation counter tracked in executor stage; halts and alerts at limit. |
| No owner = no delete | **Partially** | Requires explicit branching in the enrichment stage; not enforced by the architecture itself. |
| LLM cross-resource reasoning | **Does not** | Each resource is processed independently. The LLM has no awareness of related resources in the same scan. |

### What you give up vs. the other candidates

Compared to Candidate B: you lose the ability for the system to decide its own next step when it encounters an unexpected situation. A resource that needs a second lookup, or a decision that depends on context discovered mid-process, has no recovery path. The pipeline does exactly what it was programmed to do — no more.

Compared to Candidate C: you lose any separation of concerns at the reasoning level. Cost, ownership, and security considerations are all collapsed into a single LLM prompt per resource with no structural boundary between them.

## 16.2  Candidate B — The Agent Loop (Autonomous Reasoner)

### What it is

A single LLM agent — built on LangGraph — given a goal and a toolbox, and left to decide which tools to call, in what order, and when it has enough information to produce a cleanup recommendation. The agent builds up its enriched context incrementally through its own reasoning rather than following a prescribed sequence.

| Goal: "Analyse dev-project-3 and produce a cleanup plan" Available tools:   list_compute_resources(project_id)   get_billing_data(resource_id)   lookup_owner(resource_id)          ← tries labels first, then IAM history   check_iam_membership(email)   classify_resource(resource_data)   ← returns decision + plain-English reasoning   flag_for_review(resource_id, reason) Agent decides: which tools to call, in what order, when to stop. Hard interrupt: approval gate — agent hands plan to UI, waits for human. LangSmith traces every tool call and reasoning step. |
| --- |

Technology: LangGraph ReAct-style agent, Gemini 1.5 Pro, GCP Python client libraries wrapped as tools, React approval UI, LangSmith for full trace observability.

### What it makes easy

- Handling the messy cases the pipeline cannot. If the primary ownership lookup returns nothing, the agent can try the IAM history lookup next without pre-programmed fallback logic.

- Cross-resource reasoning. The agent can recognise that two resources appear related and reason about them as a unit.

- Richer needs_review explanations. The agent can produce a detailed rationale drawing on whatever it found across multiple tool calls, not just what a fixed prompt template received.

- The no-owner guardrail is naturally enforced through the model's reasoning given a well-crafted system prompt, rather than through branching code.

- Observability story is strong. LangSmith surfaces every decision point, every tool call, every reasoning step as the audit trail.

### What it makes hard

- Reliability and predictability. An agent that decides its own execution path can also decide wrong. The same resource may be classified differently across two runs depending on how the model reasons through it. This is a significant risk for demo stability.

- Cost and latency bounding. A pipeline with 50 resources makes a predictable number of LLM calls. An agent might make 3x that number if it decides to pursue additional lookups. There is no natural ceiling without external enforcement.

- Testing. You cannot unit test what the agent decides to do next in a straightforward way. You are testing emergent behaviour, which requires evaluation harnesses rather than unit assertions.

- Debugging a failure requires reading a reasoning trace rather than inspecting deterministic stage inputs and outputs.

### Constraints satisfied

| **Guardrail / Con****straint** | **Status** | **Notes** |
| --- | --- | --- |
| Production protection | **Satisfies** | Hard gate enforced before the agent is invoked: project ID validated against allowlist. |
| Human approval required | **Satisfies** | Hard interrupt in the LangGraph graph; the agent cannot transition to execution without human approval signal. |
| No owner = no delete | **Satisfies** | Enforced through system prompt instruction; agent applies this as a reasoning rule contextually, not just a code branch. |
| Audit trail | **Satisfies** | LangSmith captures full trace including tool calls, LLM inputs/outputs, and decision points. |
| Dry-run default | **Satisfies** | Execution tool is withheld from the agent’s toolbox in dry-run mode. |
| Session rate limiting | **Partially** | Mutation count can be tracked in external state and injected as a tool guard, but the agent itself has no native awareness of a session limit. |
| Demo stability | **Partially** | Non-determinism in agent reasoning is a real risk for live demo runs. Temperature settings and constrained prompts mitigate but do not eliminate this. |

### What you give up vs. the other candidates

Compared to Candidate A: you give up the predictability and debuggability of a deterministic sequence. When the agent behaves unexpectedly, identifying why requires reading a reasoning trace rather than inspecting a stage boundary. The mental model is harder to hand off to a new team member.

Compared to Candidate C: you give up structural separation of concerns. A single agent carrying cost, ownership, and security reasoning in one context will eventually produce muddled decisions as complexity grows, because it has no natural way to keep those concerns from bleeding into each other. Complexity accumulates inside the prompt and the tool set rather than being architected into distinct components.

## 16.3  Candidate C — The Multi-Head Council (Specialised Agents + Orchestrator)

### What it is

Three specialised sub-agents, each with a narrow domain of concern, coordinated by a central Cortex that decides when to invoke which head, synthesises their outputs, and applies consensus rules before routing to the human approval gate.

| Cerberus Cortex  (orchestrator — LangGraph multi-agent graph)   ├── Cost Head:     “Is this resource idle? What does it cost? Stop or delete?”   ├── Access Head:   “Who owns this? Still active? What access do they hold?”   └── Security Head: “Audit Logs / Flag the tickets ?” Each head: own tools + own system prompt + own structured verdict output Cortex: aggregates verdicts → applies quorum rule → routes to approval gate High-risk actions require 2-of-3 head agreement before escalating to human. |
| --- |

Technology: LangGraph multi-agent graph, Gemini 1.5 Pro (one instance per head or shared with distinct system prompts), MCP servers exposing GCP IAM and Billing as tool interfaces, React approval UI, Firestore for cross-session state if needed.

### What it makes easy

- Evolving each concern independently. The Cost Head’s idle-detection logic can be improved without touching the Security Head. A new resource type is onboarded by updating the relevant head’s tools, not the whole system.

- High-risk decisions benefit from genuine multi-perspective review. A resource that looks cheap to delete (Cost Head agrees) but contains PII (Security Head flags) is caught not through a hardcoded rule, but through conflicting verdicts the Cortex must resolve.

- The system’s reasoning is inspectable and explainable at the concern level. A reviewer can see exactly which head produced a given verdict and why, rather than reading a single opaque reasoning trace.

- MCP integration is architecturally natural. Each head’s tool interface is the obvious place to expose GCP capabilities as MCP servers, satisfying that criterion without shoehorning it in.

- Scales well as Cerberus grows. Adding a Compliance Head or a Cost-Anomaly Head is additive — the Cortex interface does not change.

### What it makes hard

- Build complexity. This is the hardest of the three to assemble within a one-week sprint. Clean interfaces between the Cortex and each head, handling head failures, and defining the quorum logic all require significant upfront design investment.

- The Cortex consensus logic is itself a hard problem. What does 2-of-3 agreement mean when the Cost Head says “safe to delete” and the Security Head says “archive first”? The Cortex must make a meta-decision about how to weight conflicting domain verdicts — and that logic is not simple.

- Inter-agent communication adds latency. Three heads running sequentially on 20 resources is meaningfully slower than a single agent or pipeline.

- Debugging a multi-agent failure requires tracing across multiple simultaneous reasoning chains. The failure may originate in a head, in the Cortex, or in the interaction between them.

- Premature decomposition risk. The division of concerns into three heads is an upfront design decision that may be the wrong cut. Some decisions require all three perspectives simultaneously and do not fit neatly into any single head’s remit.

### Constraints satisfied

| **Guardrail /**** Constraint** | **Status** | **Notes** |
| --- | --- | --- |
| Production protection | **Satisfies** | Enforced at the Cortex level before any head is invoked. |
| Human approval required | **Satisfies** | Cortex routes to approval gate; no head can trigger execution directly. |
| No owner = no delete | **Satisfies** | Access Head is specifically responsible for ownership resolution; its verdict blocks the action if ownership is unresolvable. |
| Sensitive data archival | **Satisfies** | Security Head identifies PII and injects an archival step into the execution chain before any delete action is approved. |
| Quorum for high-risk actions | **Satisfies** | Cortex enforces 2-of-3 head consensus before escalating. Structurally enforced, not prompt-dependent. |
| Audit trail | **Satisfies** | Each head’s verdict is logged separately, giving a per-concern audit record in addition to the overall action log. |
| MCP integration | **Satisfies** | Each head’s GCP tools are the natural MCP server boundary. |
| One-week build timeline | **Does not** | Realistically, the Cortex consensus logic and clean head interfaces cannot be fully built and tested in seven days alongside the UI, deployment, and demo prep. |
| Demo stability | **Partially** | Three coordinating agents introduce more points of failure than the other candidates. Requires robust fallback handling per head. |

### What you give up vs. the other candidates

Compared to Candidate A: you give up build simplicity and speed entirely. The pipeline can be production-ready in one day; the council requires the full sprint just to reach a working skeleton.

Compared to Candidate B: you give up the holistic reasoning flexibility of a single agent. The multi-head design forces an upfront decision about how concerns are divided, and that division will sometimes be the wrong cut — some decisions genuinely require all three perspectives simultaneously, and routing that through the Cortex adds friction rather than reducing it.

## 16.4  Selection Rationale

The three candidates represent a clear spectrum:

| **Pipeline** | Certainty at the cost of rigidity. Right choice if predictability and debuggability are the primary concerns and the workflow is well-understood and stable. |
| --- | --- |

| **Agent Loop** | Adaptability at the cost of predictability. Right choice if handling edge cases and messy data is more important than deterministic behaviour, and the team can absorb non-determinism. |
| --- | --- |

| **Multi-Head** | Clean architecture at the cost of build time. Right choice if the system is expected to grow significantly in scope and the investment in separation of concerns will compound over time. |
| --- | --- |

*The selected architecture for Cerberus v1 is the **Agent Loop (Candidate B), with the Multi-Head Council as the target end-state architecture. **The Agent Loop is buildable within the hackathon timeline, satisfies all core guardrails, and produces the observability story required for the demo. The Cortex/hea**d structure from Candidate C is introduced progressively as the system matures beyond the initial sprint.*

Cerberus  —  Three signals. One guardian. Zero wasted cloud spend.