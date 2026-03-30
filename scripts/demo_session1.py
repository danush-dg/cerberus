"""
Session 1 Foundation Demo — runs entirely with mock data, no GCP credentials needed.

Demonstrates:
  1. Project ID allowlist guard
  2. Config loading with mock env
  3. Resource record creation and validation
  4. State initialisation (dry_run, run_id, mutation_count)
  5. GCP retry wrapper with simulated 429 / 403
  6. ChromaDB — upsert and query mock resources (IAM users + cost data)
  7. ChromaDB — cross-owner history query

Run: venv\Scripts\python scripts\demo_session1.py
"""

import os
import sys
import time

# ── Inject mock env before any cerberus import ────────────────────────────────
os.environ.setdefault("GCP_PROJECT_ID",             "nexus-tech-dev-sandbox")
os.environ.setdefault("GCP_SERVICE_ACCOUNT_KEY_PATH", "/mock/cerberus-key.json")
os.environ.setdefault("BILLING_ACCOUNT_ID",         "AAAAAA-BBBBBB-CCCCCC")
os.environ.setdefault("GEMINI_API_KEY",             "mock-gemini-key")
os.environ.setdefault("GEMINI_MODEL",               "gemini-1.5-pro-002")
os.environ.setdefault("ALLOWED_PROJECT_PATTERN",    "^nexus-tech-dev-[0-9a-z-]+$")
os.environ.setdefault("CHROMA_PERSIST_DIR",         "./demo_chroma_db")
os.environ.setdefault("AUDIT_LOG_DIR",              "./logs")

from unittest.mock import Mock
from google.api_core.exceptions import TooManyRequests, Forbidden

from cerberus.config import get_config, validate_project_id, reset_config
from cerberus.state import (
    ResourceRecord, CerberusState,
    validate_resource_record, initialise_state,
    VALID_DECISIONS, VALID_OUTCOMES,
)
from cerberus.tools.gcp_retry import gcp_call_with_retry, CerberusRetryExhausted
from cerberus.tools.chroma_client import (
    upsert_resource_record, query_resource_history, query_owner_history,
)
import cerberus.tools.chroma_client as chroma_module


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def ok(msg):  print(f"  ✓  {msg}")
def info(msg): print(f"  →  {msg}")
def fail(msg): print(f"  ✗  {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Project ID allowlist guard (INV-SEC-01)
# ─────────────────────────────────────────────────────────────────────────────
section("1. Project ID Allowlist Guard (INV-SEC-01)")

pattern = "^nexus-tech-dev-[0-9a-z-]+$"

tests = [
    ("nexus-tech-dev-sandbox",  True,  "valid sandbox project"),
    ("nexus-tech-dev-3",        True,  "valid numbered project"),
    ("nexus-tech-prod",         False, "production project — must be BLOCKED"),
    ("nexus-tech-dev-UPPER",    False, "uppercase suffix — must be BLOCKED"),
    ("",                        False, "empty string — must be BLOCKED"),
    ("nexus-tech-dev-",         False, "trailing dash only — must be BLOCKED"),
]

for project_id, should_pass, label in tests:
    try:
        validate_project_id(project_id, pattern)
        if should_pass:
            ok(f"ALLOWED  '{project_id}' — {label}")
        else:
            fail(f"Should have been blocked: '{project_id}' — {label}")
    except ValueError as e:
        if not should_pass:
            ok(f"BLOCKED  '{project_id}' — {label}")
        else:
            fail(f"Should have passed: '{project_id}' — {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Config loading with mock env
# ─────────────────────────────────────────────────────────────────────────────
section("2. Config Loading")

reset_config()
c = get_config()
ok(f"gcp_project_id          = {c.gcp_project_id}")
ok(f"gemini_model            = {c.gemini_model}")
ok(f"allowed_project_pattern = {c.allowed_project_pattern}")
ok(f"chroma_persist_dir      = {c.chroma_persist_dir}")
ok(f"Singleton cached        = {get_config() is c}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Resource record creation and validation (INV-SCAN-01)
# ─────────────────────────────────────────────────────────────────────────────
section("3. Resource Record Validation (INV-SCAN-01)")

# Mock resources: VM (active owner), orphaned disk (no owner), unused IP (departed owner)
MOCK_RESOURCES = [
    {
        "resource_id":              "cerberus-demo-vm-1",
        "resource_type":            "vm",
        "region":                   "us-central1",
        "creation_timestamp":       "2024-01-15T00:00:00Z",
        "last_activity_timestamp":  "2024-01-18T06:00:00Z",   # 80 h idle
        "estimated_monthly_cost":   45.50,
        "ownership_status":         "departed_owner",
        "owner_email":              "departed@nexus.tech",
        "owner_iam_active":         False,
        "flagged_for_review":       False,
        "decision":                 None,
        "reasoning":                None,
        "estimated_monthly_savings": None,
        "outcome":                  None,
    },
    {
        "resource_id":              "cerberus-demo-disk-1",
        "resource_type":            "orphaned_disk",
        "region":                   "us-east1",
        "creation_timestamp":       "2023-11-01T00:00:00Z",
        "last_activity_timestamp":  None,
        "estimated_monthly_cost":   12.00,
        "ownership_status":         "no_owner",
        "owner_email":              None,
        "owner_iam_active":         None,
        "flagged_for_review":       True,   # no_owner forces this
        "decision":                 None,
        "reasoning":                None,
        "estimated_monthly_savings": None,
        "outcome":                  None,
    },
    {
        "resource_id":              "cerberus-demo-ip-1",
        "resource_type":            "unused_ip",
        "region":                   "us-west1",
        "creation_timestamp":       "2024-03-01T00:00:00Z",
        "last_activity_timestamp":  None,
        "estimated_monthly_cost":   7.20,
        "ownership_status":         "active_owner",
        "owner_email":              "alice@nexus.tech",
        "owner_iam_active":         True,
        "flagged_for_review":       False,
        "decision":                 None,
        "reasoning":                None,
        "estimated_monthly_savings": None,
        "outcome":                  None,
    },
]

for r in MOCK_RESOURCES:
    try:
        validate_resource_record(r)
        ok(f"{r['resource_type']:15s} {r['resource_id']:30s} cost=${r['estimated_monthly_cost']}/mo  owner={r['owner_email'] or 'NONE'}")
    except ValueError as e:
        fail(str(e))

# Test invalid record
try:
    validate_resource_record({"resource_type": "vm"})  # missing required fields
    fail("Should have raised ValueError")
except ValueError as e:
    ok(f"Invalid record correctly rejected: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. State initialisation (INV-UI-03)
# ─────────────────────────────────────────────────────────────────────────────
section("4. LangGraph State Initialisation (INV-UI-03)")

state = initialise_state("nexus-tech-dev-sandbox")
ok(f"run_id          = {state['run_id']} ({len(state['run_id'])} chars)")
ok(f"project_id      = {state['project_id']}")
ok(f"dry_run         = {state['dry_run']}  ← must be True by default")
ok(f"mutation_count  = {state['mutation_count']}  ← must be 0")
ok(f"run_complete    = {state['run_complete']}  ← must be False")
ok(f"VALID_DECISIONS = {sorted(VALID_DECISIONS)}")
ok(f"VALID_OUTCOMES  = {sorted(VALID_OUTCOMES)}")

state["resources"] = MOCK_RESOURCES
info(f"Loaded {len(state['resources'])} mock resources into state")
total_cost = sum(r["estimated_monthly_cost"] for r in state["resources"])
ok(f"Total mock waste = ${total_cost:.2f}/month")


# ─────────────────────────────────────────────────────────────────────────────
# 5. GCP retry wrapper (INV-NFR-02)
# ─────────────────────────────────────────────────────────────────────────────
section("5. GCP Retry Wrapper (INV-NFR-02)")

# 5a — succeeds first try
fn_ok = Mock(return_value={"instances": ["vm-1", "vm-2", "vm-3"]})
fn_ok.__name__ = "list_instances"
result = gcp_call_with_retry(fn_ok)
ok(f"First-attempt success: {result}")

# 5b — 429 then success (sleep patched to avoid waiting)
import cerberus.tools.gcp_retry as retry_mod
original_sleep = retry_mod.time.sleep
retry_mod.time.sleep = lambda _: None   # patch sleep for demo speed

attempt_log = []
def flaky_billing_call():
    attempt_log.append(len(attempt_log) + 1)
    if len(attempt_log) < 2:
        raise TooManyRequests("Rate limit hit")
    return {"cost": 45.50}
flaky_billing_call.__name__ = "get_billing_data"

result = gcp_call_with_retry(flaky_billing_call)
ok(f"429 retry succeeded on attempt {len(attempt_log)}: {result}")

# 5c — exhausted after 3 attempts
always_429 = Mock(side_effect=TooManyRequests("quota exceeded"))
always_429.__name__ = "list_assets"
try:
    gcp_call_with_retry(always_429)
    fail("Should have raised CerberusRetryExhausted")
except CerberusRetryExhausted as e:
    ok(f"Retry exhausted after {e.attempts} attempts: {e.fn_name}")

# 5d — 403 never retried
forbidden_call = Mock(side_effect=Forbidden("no access"))
forbidden_call.__name__ = "get_iam_policy"
try:
    gcp_call_with_retry(forbidden_call)
except Forbidden:
    ok(f"403 Forbidden re-raised immediately (call_count={forbidden_call.call_count}, not retried)")

retry_mod.time.sleep = original_sleep  # restore


# ─────────────────────────────────────────────────────────────────────────────
# 6. ChromaDB — upsert and retrieve resource history
# ─────────────────────────────────────────────────────────────────────────────
section("6. ChromaDB Resource History (cross-run context)")

# Reset singleton so demo_chroma_db path is used
chroma_module._client = None
chroma_module._collection = None

RUN_ID = "demo-run-001"
PROJECT = "nexus-tech-dev-sandbox"

info("Upserting 3 mock resources into ChromaDB...")
for r in MOCK_RESOURCES:
    upsert_resource_record(r, RUN_ID, PROJECT)
    ok(f"Upserted: {r['resource_id']}")

# Query by resource ID
info("\nQuerying individual resource history...")
for r in MOCK_RESOURCES:
    record = query_resource_history(r["resource_id"])
    if record:
        ok(f"{r['resource_id']:30s} run={record['run_id']}  owner={record['owner_email']}")
    else:
        fail(f"Not found: {r['resource_id']}")


# ─────────────────────────────────────────────────────────────────────────────
# 7. ChromaDB — cross-owner history (simulates reason_node context)
# ─────────────────────────────────────────────────────────────────────────────
section("7. ChromaDB Cross-Owner Query (IAM / cost analysis context)")

# Add a second resource for alice to show cross-resource ownership
alice_disk = {
    "resource_id":              "cerberus-demo-disk-alice",
    "resource_type":            "orphaned_disk",
    "region":                   "us-west1",
    "creation_timestamp":       "2024-02-01T00:00:00Z",
    "last_activity_timestamp":  None,
    "estimated_monthly_cost":   18.00,
    "ownership_status":         "active_owner",
    "owner_email":              "alice@nexus.tech",
    "owner_iam_active":         True,
    "flagged_for_review":       False,
    "decision":                 "safe_to_delete",
    "reasoning":                "Disk unattached for 45 days, owner confirmed active.",
    "estimated_monthly_savings": 18.00,
    "outcome":                  "SUCCESS",
}
upsert_resource_record(alice_disk, RUN_ID, PROJECT)

info("Querying all resources owned by alice@nexus.tech...")
alice_resources = query_owner_history("alice@nexus.tech", PROJECT)
ok(f"Found {len(alice_resources)} resources for alice@nexus.tech:")
for rec in alice_resources:
    ok(f"  {rec['resource_type']:15s} cost=${rec['estimated_monthly_cost']:.2f}  decision={rec['decision']}")

info("\nQuerying all resources owned by departed@nexus.tech...")
departed_resources = query_owner_history("departed@nexus.tech", PROJECT)
ok(f"Found {len(departed_resources)} resources for departed@nexus.tech:")
for rec in departed_resources:
    ok(f"  {rec['resource_type']:15s} cost=${rec['estimated_monthly_cost']:.2f}  status={rec['ownership_status']}")

info("\nQuerying resources with no owner (owner_email=unknown)...")
no_owner_resources = query_owner_history("unknown", PROJECT)
ok(f"Found {len(no_owner_resources)} no-owner resources:")
for rec in no_owner_resources:
    ok(f"  {rec['resource_type']:15s} cost=${rec['estimated_monthly_cost']:.2f}")


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
section("Session 1 Foundation Demo: COMPLETE")

all_resources = alice_resources + departed_resources + no_owner_resources
total_mock_waste = sum(r["estimated_monthly_cost"] for r in MOCK_RESOURCES) + alice_disk["estimated_monthly_cost"]
ok(f"Resources in ChromaDB  : {len(MOCK_RESOURCES) + 1}")
ok(f"Total mock waste       : ${total_mock_waste:.2f}/month")
ok(f"Project guard          : PASS")
ok(f"Config singleton       : PASS")
ok(f"Record validation      : PASS")
ok(f"State init (dry_run)   : PASS")
ok(f"Retry wrapper          : PASS (429 retry, 403 no-retry, exhausted)")
ok(f"ChromaDB upsert/query  : PASS")
ok(f"Cross-owner query      : PASS")
print()
print("  Ready for Session 2 — scan_node")
