from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


BUDGET_ALERT_THRESHOLD_DEFAULT: float = 500.0


@dataclass
class CerberusConfig:
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
    budget_thresholds: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.budget_thresholds is None:
            self.budget_thresholds = {}


_config: CerberusConfig | None = None


def get_config() -> CerberusConfig:
    global _config
    if _config is not None:
        return _config
    load_dotenv()
    required_env_vars = [
        "GCP_PROJECT_ID",
        "GCP_SERVICE_ACCOUNT_KEY_PATH",
        "BILLING_ACCOUNT_ID",
        "GEMINI_API_KEY",
    ]
    missing = [k for k in required_env_vars if not os.environ.get(k, "").strip()]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    _config = CerberusConfig(
        gcp_project_id=os.environ["GCP_PROJECT_ID"],
        service_account_key_path=os.environ["GCP_SERVICE_ACCOUNT_KEY_PATH"],
        billing_account_id=os.environ["BILLING_ACCOUNT_ID"],
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-1.5-pro-002"),
        allowed_project_pattern=os.environ.get("ALLOWED_PROJECT_PATTERN", "^nexus-tech-dev-[0-9a-z-]+$"),
        langsmith_api_key=os.environ.get("LANGSMITH_API_KEY") or None,
        langsmith_project=os.environ.get("LANGSMITH_PROJECT", "cerberus"),
        chroma_persist_dir=os.environ.get("CHROMA_PERSIST_DIR", "./chroma_db"),
        audit_log_dir=os.environ.get("AUDIT_LOG_DIR", "./logs"),
    )
    return _config


def validate_project_id(project_id: str, pattern: str) -> None:
    if not project_id:
        raise ValueError("BLOCKED: empty project ID.")
    if not re.fullmatch(pattern, project_id):
        raise ValueError(
            f"BLOCKED: '{project_id}' does not match allowed pattern '{pattern}'. "
            f"Cerberus only operates on dev projects."
        )


def reset_config() -> None:
    """TEST USE ONLY — do not call in production code."""
    global _config
    _config = None
