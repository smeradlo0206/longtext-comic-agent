# AGENTS.md

## Architecture Rules

- `comic_agent/schemas` Pydantic models are the only schema source of truth.
- Do not copy standalone schema definitions into Agent, API, or database modules.
- Agents may output Proposal objects only.
- Only `CommitService` may write canonical story data.
- Every canonical story fact must be traceable to `EvidenceRefV1`.
- `PanelSpecV1` must not contain provider-specific fields.
- `PromptSpecV1` may contain provider-specific fields.
- Agents must not read the whole database directly; use `ContextBuilder`.
- Unit tests must not call real LLMs or image APIs.
- All external model calls must go through Provider interfaces.
- All writes must be designed for idempotency.
- Every bug fix must add a regression test.
- Schema changes must update `schema_version` and migration notes.

## Commands

- Install: `uv sync`
- Test: `uv run pytest`
- Lint: `uv run ruff check .`
- Type check: `uv run mypy comic_agent`
- Start API: `uv run uvicorn comic_agent.main:app --reload`
- Start Docker Compose: `docker compose up -d`
- Export JSON Schema: `uv run python scripts/export_json_schemas.py`

## Pull Request Requirements

- Summarize the change.
- Link the related Issue.
- Mark schema compatibility impact.
- Mark database migration impact.
- List tests run.
- Do not include secrets.
- At least one reviewer must review core schema changes.
