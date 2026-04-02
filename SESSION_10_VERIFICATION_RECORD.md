# VERIFICATION_RECORD.md

**Session:** Session 10 — Three-Head Expansion
**Date:** 2026-04-01
**Engineer:**
**Branch:** session/s10
**Claude.md version:** v2.0 · FROZEN · 2026-03-31

---

## Task 10.1 — Backend models, head skeletons, route registration

### Test Cases Applied
Source: SESSION_10_BUILD_GUIDE.md Task 10.1

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| 1 | GET /iam/inventory | status != 404 | PASS |
| 2 | GET /cost/project/{id} | status != 404 | PASS |
| 3 | GET /security/flags | status != 404 | PASS |
| 4 | GET /tickets | status != 404 | PASS |
| 5 | GET /run/nonexistent/status | status == 404 (existing route intact) | PASS |
| 6 | IAMTicket model with status="pending" | ticket.status == "pending" | PASS |
| 7 | SecurityFlag with invalid flag_type | raises Exception | PASS |

### Code Review
**INV-IAM-01, INV-IAM-03, INV-COST-01, INV-SEC2-03 touched.**

- [x] No existing route in `api.py` is modified — only `include_router` calls added
- [x] `IAMTicket.status` is a `Literal` with exactly 4 values: pending/approved/rejected/provisioned
- [x] `SecurityFlag.flag_type` is a `Literal` with exactly 3 values: OVER_PERMISSIONED/GHOST_RESOURCE/BUDGET_BREACH
- [x] `ProjectCostSummary` has both `attributed_usd` AND `unattributed_usd` — not one total field

---

## Task 10.2 — IAM Head: Gemini synthesis, ticket lifecycle, asset inventory

### Test Cases Applied
Source: SESSION_10_BUILD_GUIDE.md Task 10.2

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| 1 | synthesis calls Gemini at temperature=0 | temperature == 0 | PASS |
| 2 | synthesis raises on unparseable response | raises ValueError/Exception | PASS |
| 3 | create_ticket stores ticket in _tickets | ticket_id in _tickets | PASS |
| 4 | create_ticket sets status=pending | status == "pending" | PASS |
| 5 | approve_ticket changes status to approved | status == "approved" | PASS |
| 6 | approve_ticket raises on unknown id | raises KeyError | PASS |
| 7 | provision dry_run returns DRY_RUN status | result["status"] == "DRY_RUN" | PASS |
| 8 | provision dry_run makes no GCP calls | rm/iam clients not called | PASS |
| 9 | get_pending_tickets filters non-pending | approved tickets excluded | PASS |
| 10 | get_iam_inventory returns binding list | len(bindings) == 2 | PASS |
| 11 | get_iam_inventory returns [] on retry exhausted | result == [] | PASS |

### Code Review
**INV-IAM-01, INV-IAM-02, INV-IAM-03 touched.**

- [x] `synthesize_iam_request` calls Gemini at `temperature=0` — `iam_head.py` line ~247
- [x] `provision_iam_binding` defaults `dry_run=True` — signature enforced
- [x] Route `POST /tickets/{id}/provision` checks `ticket.status == "approved"` before calling provision

---

## Task 10.3 — Cost Head: per-project and per-user spend from ChromaDB

### Test Cases Applied

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| 1 | project summary basic totals and breakdown | total=100, attributed=100 | PASS |
| 2 | INV-COST-01: unattributed row present when unattributed_usd > 0 | unattributed row in breakdown | PASS |
| 3 | INV-COST-01: no unattributed row when usd == 0 | row absent | PASS |
| 4 | empty ChromaDB returns zeroed summary | total=0, breakdown=[] | PASS |
| 5 | None cost treated as 0.0 | total=10 not 0 | PASS |
| 6 | user cost summary basic | total=55, resource_count=2 | PASS |
| 7 | user cost summary empty | total=0, resources=[] | PASS |
| 8 | INV-COST-02: no billing import | ast parse passes | PASS |

### Code Review
**INV-COST-01, INV-COST-02 touched.**

- [x] No import of any `google-cloud-billing` module in `cost_head.py`
- [x] unattributed row present in breakdown when unattributed_usd > 0

---

## Task 10.4 — Security Head: flags, budget alerts, PDF report

### Test Cases Applied

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| 1 | budget not breached when under threshold | breached=False | PASS |
| 2 | budget breached when over threshold | breached=True, percent=120 | PASS |
| 3 | budget empty records | current=0, breached=False | PASS |
| 4 | OVER_PERMISSIONED flag for inactive owner | flag raised | PASS |
| 5 | INV-SEC2-01: no flag for active owner | flag absent | PASS |
| 6 | INV-SEC2-01: no flag for non-privileged role | flag absent | PASS |
| 7 | INV-SEC2-01: both conditions required | active owner+privileged = no flag | PASS |
| 8 | OVER_PERMISSIONED raised for None last_activity | flag raised | PASS |
| 9 | GHOST_RESOURCE flag from ChromaDB idle records | flag raised | PASS |
| 10 | GHOST_RESOURCE for safe_to_delete decision | flag raised | PASS |
| 11 | no GHOST_RESOURCE for needs_review/skip | flags absent | PASS |
| 12 | BUDGET_BREACH flag when over threshold | flag raised | PASS |
| 13 | INV-SEC2-02: BUDGET_BREACH writes audit entry | write_audit_entry called | PASS |
| 14 | no BUDGET_BREACH when under threshold | flag absent | PASS |

### Code Review
**INV-SEC2-01, INV-SEC2-02, INV-SEC2-03 touched.**

- [x] `get_security_flags` checks BOTH inactivity AND role for OVER_PERMISSIONED
- [x] BUDGET_BREACH flag writes JSONL entry via `write_audit_entry`
- [x] `generate_audit_report` returns bytes starting with b'%PDF'

---

## Task 10.5 — SlideNav and page shells

### Code Review
- [x] Five nav sections: dashboard / iam / cost / security / tickets
- [x] Pending ticket badge renders on Tickets nav item
- [x] Active section highlighted with border and background

---

## Task 10.6 — IAM Panel and Asset Inventory

### Code Review
- [x] Form submits to `POST /iam/request` — synthesis and ticket creation atomic
- [x] `onTicketCreated()` called after success → `loadTickets()` + auto-nav to Tickets tab
- [x] Role name is a user-supplied custom identifier — `roles/` prefix NOT required
- [x] Identity Records tab renders em-dash for null fields (INV-IAM-03)

---

## Task 10.7 — Cost Center

### Code Review
- [x] `getProjectCostSummary` and `getBudgetStatus` fetched in parallel on load
- [x] unattributed row rendered visibly (INV-COST-01)
- [x] Audit Report PDF download button calls `downloadAuditReport()`

---

## Task 10.8 — Security Hub

### Code Review
- [x] Over-permissioning table populated from `MOCK_IDENTITY_DATA`
- [x] Ghost resources populated from scan results
- [x] Budget threshold gauges shown per project

---

## Task 10.9 — Ticket Panel

### Code Review
**INV-IAM-02 touched — most critical review in this session.**

- [x] "⚡ Provision in GCP" button only rendered for `status === 'approved'` tickets — conditional render
- [x] Confirmation modal shown before any GCP call is made
- [x] Backend `POST /tickets/{id}/provision` checks `ticket.status == "approved"` → 400 if not
- [x] `dry_run=True` is the default in `provision_iam_binding` — live only with explicit `False`

---

## Task 10.10 — Session Integration Check

### Integration Check Result
**PASS**

### Route Registration — all 12 new routes reachable (not 404)
```
✅  POST /iam/request
✅  GET  /iam/request/{id}/preview
✅  POST /iam/request/{id}/confirm
✅  GET  /iam/inventory
✅  GET  /cost/project/{id}
✅  GET  /cost/user
✅  GET  /security/flags
✅  GET  /security/budget-status
✅  GET  /security/report/download
✅  GET  /tickets
✅  POST /tickets/{id}/approve
✅  POST /tickets/{id}/provision
```

### Invariant Sign-off

| Invariant | PASS/FAIL |
|-----------|-----------|
| INV-IAM-01 | PASS |
| INV-IAM-02 | PASS |
| INV-IAM-03 | PASS |
| INV-COST-01 | PASS |
| INV-COST-02 | PASS |
| INV-SEC2-01 | PASS |
| INV-SEC2-02 | PASS |
| INV-SEC2-03 | PASS |

### Smoke Test Command
```bash
python scripts/run_demo_smoke_test.py --mock
```

### Regression Check
- [x] All sessions 1–9 tests still pass: `pytest tests/ -v`
- [x] New session 10 test files pass: `pytest tests/test_iam_head.py tests/test_cost_head.py tests/test_security_head.py tests/test_routes.py tests/test_pdf_report.py -v`
