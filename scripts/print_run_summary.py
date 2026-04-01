"""
scripts/print_run_summary.py — Print a human-readable ROI summary from the most
recent Cerberus audit log.

Usage:
    python scripts/print_run_summary.py

    # Or point at a specific log directory:
    AUDIT_LOG_DIR=./logs python scripts/print_run_summary.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def find_latest_audit_log(log_dir: str) -> Path | None:
    """Return the most recently modified audit_*.jsonl file, or None."""
    log_path = Path(log_dir)
    if not log_path.exists():
        return None
    logs = sorted(log_path.glob("audit_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def extract_cost_summary(log_file: Path) -> dict | None:
    """Read JSONL and return the COST_SUMMARY entry payload, or None."""
    with open(log_file, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("action_type") == "COST_SUMMARY":
                raw = entry.get("llm_reasoning", "{}")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return None
    return None


def extract_run_meta(log_file: Path) -> tuple[str, str]:
    """Return (run_id, langsmith_trace_url) from the first entry in the log."""
    run_id = log_file.stem.replace("audit_", "")
    langsmith_url = "unavailable — local JSONL is authoritative"
    return run_id, langsmith_url


def main() -> int:
    log_dir = os.environ.get("AUDIT_LOG_DIR", "./logs")
    log_file = find_latest_audit_log(log_dir)

    if log_file is None:
        print("No audit logs found.")
        print(f"  (looked in: {os.path.abspath(log_dir)})")
        return 1

    summary = extract_cost_summary(log_file)
    if summary is None:
        print("No COST_SUMMARY found in log.")
        print(f"  (log file: {log_file})")
        return 1

    run_id, langsmith_url = extract_run_meta(log_file)

    resources_scanned              = summary.get("resources_scanned", 0)
    total_waste_identified         = summary.get("total_waste_identified") or 0.0
    actions_approved               = summary.get("actions_approved", 0)
    actions_executed               = summary.get("actions_executed", 0)
    savings_recovered              = summary.get("estimated_monthly_savings_recovered") or 0.0

    W = 46
    print()
    print("=" * W)
    print(f"  CERBERUS RUN SUMMARY  run_id={run_id[:8]}...")
    print("=" * W)
    print(f"  {'Resources scanned:':<28} {resources_scanned}")
    print(f"  {'Total waste identified:':<28} ${total_waste_identified:,.2f}/mo")
    print(f"  {'Actions approved:':<28} {actions_approved}")
    print(f"  {'Actions executed:':<28} {actions_executed}")
    print(f"  {'Recovered savings:':<28} ${savings_recovered:,.2f}/mo")
    print("-" * W)
    print(f"  Evidence-based decisions:   {actions_approved} resource(s) classified by")
    print(f"  {'':26} Gemini at temperature=0.")
    print(f"  {'Audit log:':<28} {log_file}")
    print(f"  {'LangSmith trace:':<28} {langsmith_url}")
    print("=" * W)
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
