.PHONY: install test lint typecheck api compose-up compose-config schema

install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy comic_agent

api:
	uv run uvicorn comic_agent.main:app --reload

compose-up:
	docker compose up -d

compose-config:
	docker compose config

schema:
	uv run python scripts/export_json_schemas.py
