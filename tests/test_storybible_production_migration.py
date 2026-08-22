"""Alembic coverage for production StoryBible execution checkpoints."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from comic_agent.config import get_settings


def test_alembic_upgrade_creates_storybible_production_run_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'storybible-production-migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    command.upgrade(Config("alembic.ini"), "head")

    inspector = inspect(create_engine(database_url))
    assert {
        column["name"]
        for column in inspector.get_columns("storybible_production_runs")
    } == {
        "run_id",
        "project_id",
        "gate2_approved_bundle_id",
        "approved_timeline_bundle_id",
        "input_hash",
        "status",
        "payload",
        "created_at",
        "updated_at",
    }
    assert {
        item["name"]
        for item in inspector.get_unique_constraints("storybible_production_runs")
    } >= {"uq_storybible_production_project_input"}
    assert {
        item["name"] for item in inspector.get_indexes("storybible_production_runs")
    } >= {
        "ix_storybible_production_runs_project_id",
        "ix_storybible_production_runs_gate2_approved_bundle_id",
        "ix_storybible_production_runs_approved_timeline_bundle_id",
    }
    get_settings.cache_clear()
