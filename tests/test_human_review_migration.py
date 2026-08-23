"""Alembic coverage for durable, non-canonical human production approval."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from comic_agent.config import get_settings


def test_alembic_upgrade_creates_human_review_and_explicit_production_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'human-review-migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    command.upgrade(Config("alembic.ini"), "head")

    inspector = inspect(create_engine(database_url))
    assert {
        column["name"] for column in inspector.get_columns("human_review_runs")
    } == {
        "review_id",
        "project_id",
        "dossier_id",
        "dossier_hash",
        "decision",
        "payload",
        "created_at",
    }
    assert {
        item["name"] for item in inspector.get_unique_constraints("human_review_runs")
    } >= {"uq_human_review_dossier"}
    production_columns = {
        column["name"]: column for column in inspector.get_columns("storybible_production_runs")
    }
    for name in (
        "human_review_id",
        "production_dossier_id",
        "narrative_execution_bundle_id",
        "timeline_review_material_id",
    ):
        assert name in production_columns
    assert production_columns["gate2_approved_bundle_id"]["nullable"] is True
    assert production_columns["approved_timeline_bundle_id"]["nullable"] is True
    assert {
        column["name"] for column in inspector.get_columns("production_dossiers")
    } == {
        "dossier_id",
        "project_id",
        "document_id",
        "content_hash",
        "payload",
        "created_at",
    }
    get_settings.cache_clear()


def test_human_review_authorization_migration_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'human-review-round-trip.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    engine = create_engine(database_url)

    command.upgrade(config, "head")
    assert "human_review_runs" in inspect(engine).get_table_names()
    assert "production_dossiers" in inspect(engine).get_table_names()

    command.downgrade(config, "0010_storybible_review_runs")
    assert "human_review_runs" not in inspect(engine).get_table_names()
    assert "production_dossiers" not in inspect(engine).get_table_names()
    production_columns = {
        column["name"] for column in inspect(engine).get_columns("storybible_production_runs")
    }
    assert "human_review_id" not in production_columns

    command.upgrade(config, "head")
    assert "human_review_runs" in inspect(engine).get_table_names()
    get_settings.cache_clear()


def test_downgrade_refuses_to_discard_existing_human_review_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'human-review-downgrade.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    engine = create_engine(database_url)

    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO human_review_runs "
            "(review_id, project_id, dossier_id, dossier_hash, decision, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "review-1",
                "project-1",
                "dossier-1",
                "hash-1",
                "APPROVE",
                "{}",
                "2026-08-23T00:00:00+00:00",
            ),
        )

    with pytest.raises(RuntimeError, match="cannot downgrade durable dossier binding"):
        command.downgrade(config, "0011_human_review_production_authorization")
    assert "production_dossiers" in inspect(engine).get_table_names()
    get_settings.cache_clear()
