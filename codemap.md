# Cerberus Codemap

## Project Root
- `.claude/`: Agent instructions and configuration.
- `.venv/`, `venv/`: Local and managed Python environments.
- `architecure.md`: High-level design document.
- `requirements.md`: Task-level project requirements.
- `invariants.md`: Hard guardrails for development.
- `CLAUDE.md`: System-level LLM context and rules.
- `pyproject.toml`, `requirements.txt`: Python dependency management.
- `frontend/`: UI implementation.
- `cerberus/`: Core application logic (backend).

## cerberus/ Backend Core
- **`api.py`**: FastAPI app and endpoints (`/run`, `/iam`, etc.).
- **`graph.py`**: LangGraph flow definition and node registration.
- **`state.py`**: CerberusState schema and initialization logic.
- **`config.py`**: Backend configuration settings and environment variable management.

- **`nodes/`**: Implementation of LangGraph nodes.
  - `scan_node.py`: List GCP resources.
  - `enrich_node.py`: Correlate ownership and last activity.
  - `reason_node.py`: Gemini-driven classification logic.
  - `approve_node.py`: HITL interrupt point.
  - `revalidate_node.py`: Pre-execution state verification.
  - `execute_node.py`: Live resource mutations (Stop/Delete/Archive).
  - `audit_node.py`: Final result logging.
  - `access_node.py`: Supplemental IAM synthesis logic.

- **`heads/`**: Specialized system heads.
  - `iam_head.py`: IAM ticket lifecycle, role creation, and revocation.
  - (Planned heads: `cost_head.py`, `security_head.py`)

- **`models/`**: Pydantic models and data schemas.
  - `iam_ticket.py`: IAM request and ticket structure.

- **`routes/`**: FastAPI route subsets (delegated by `api.py`).
  - `iam_routes.py`: IAM-specific API endpoints.
  - `cost_routes.py`: Cost-specific API endpoints.
  - `security_routes.py`: Security-specific API endpoints.
  - `ticket_routes.py`: Admin ticket queue endpoints.

- **`services/`**: Integration layer for external cloud providers.
  - `gcp_client.py`: Base GCP SDK wrappers.
  - `real_client.py`: Direct interactions with GCP API.

- **`tools/`**: Utilities and database clients.
  - `chroma_client.py`: Vector DB client for persistence of history and audit logs.
  - `gcp_retry.py`: Exponential backoff and retry handling for GCP API calls.

## frontend/ Frontend UI
- **`src/`**: React/TS source.
  - `App.tsx`: Main application entry and routing.
  - `components/`: Reusable UI elements (Tables, Progress Indicators, etc.).
  - `api.ts`: API client and request wrappers.
  - `types.ts`: TypeScript interfaces mirroring backend models.

## scripts/ Management & Deployment
- `seed_sandbox.py`: Script to populate the GCP project with demo resources.
- `init_chroma.py`: (Optional) Script to initialize vector database collections.
