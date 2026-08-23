"""Alembic coverage for deterministic StoryBible review persistence."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from comic_agent.config import get_settings


def test_alembic_upgrade_creates_storybible_review_run_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'storybible-review-migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    command.upgrade(Config("alembic.ini"), "head")

    inspector = inspect(create_engine(database_url))
    table = "storybible_review_runs"
    assert {column["name"] for column in inspector.get_columns(table)} == {
        "review_id",
        "project_id",
        "source_storybible_run_id",
        "proposal_hash",
        "status",
        "bundle_id",
        "snapshot_hash",
        "payload",
        "created_at",
        "updated_at",
        "frozen_at",
    }
    assert {item["name"] for item in inspector.get_unique_constraints(table)} >= {
        "uq_storybible_review_source_run",
        "uq_storybible_review_bundle",
    }
    assert {item["name"] for item in inspector.get_indexes(table)} >= {
        "ix_storybible_review_runs_project_id",
        "ix_storybible_review_runs_source_storybible_run_id",
    }
    get_settings.cache_clear()


def test_storybible_review_migration_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'storybible-review-round-trip.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    engine = create_engine(database_url)

    command.upgrade(config, "head")
    assert "storybible_review_runs" in inspect(engine).get_table_names()

    command.downgrade(config, "0009_storybible_production_runs")
    assert "storybible_review_runs" not in inspect(engine).get_table_names()
    assert "storybible_production_runs" in inspect(engine).get_table_names()

    command.upgrade(config, "head")
    assert "storybible_review_runs" in inspect(engine).get_table_names()
    get_settings.cache_clear()
