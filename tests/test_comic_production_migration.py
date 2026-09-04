"""Alembic coverage for idempotent comic production records."""

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from comic_agent.config import get_settings


def test_integrated_migration_graph_has_one_head() -> None:
    assert ScriptDirectory.from_config(Config("alembic.ini")).get_heads() == [
        "0011_merge_storybible_comic_heads"
    ]


def test_alembic_upgrade_creates_comic_production_runs_table(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite+pysqlite:///{tmp_path / 'comic-production-migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")

        inspector = inspect(create_engine(database_url))
        assert {column["name"] for column in inspector.get_columns("comic_production_runs")} == {
            "run_id",
            "project_id",
            "document_id",
            "request_hash",
            "status",
            "payload",
            "created_at",
            "updated_at",
        }
        assert "uq_comic_run_project_document_request" in {
            item["name"]
            for item in inspector.get_unique_constraints("comic_production_runs")
        }
        assert {
            "ix_comic_production_runs_project_id",
            "ix_comic_production_runs_document_id",
        }.issubset({item["name"] for item in inspector.get_indexes("comic_production_runs")})
    finally:
        get_settings.cache_clear()
