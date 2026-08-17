"""Alembic coverage for durable Timeline/Gate 3 idempotency records."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from comic_agent.config import get_settings


def test_alembic_upgrade_creates_timeline_gate3_runs_table(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'timeline-gate3-migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    command.upgrade(Config("alembic.ini"), "head")

    inspector = inspect(create_engine(database_url))
    assert {
        column["name"] for column in inspector.get_columns("timeline_gate3_runs")
    } == {
        "timeline_run_id",
        "project_id",
        "source_bundle_id",
        "idempotency_key",
        "status",
        "payload",
        "created_at",
        "updated_at",
    }
    unique_names = {
        item["name"] for item in inspector.get_unique_constraints("timeline_gate3_runs")
    }
    assert unique_names >= {
        "uq_timeline_gate3_project_bundle",
        "uq_timeline_gate3_idempotency",
    }
    assert "ix_timeline_gate3_runs_project_id" in {
        item["name"] for item in inspector.get_indexes("timeline_gate3_runs")
    }
    get_settings.cache_clear()
