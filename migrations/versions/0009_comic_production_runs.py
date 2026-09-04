"""Persist idempotent long-text comic production runs."""

import sqlalchemy as sa
from alembic import op

revision = "0009_comic_production_runs"
down_revision = "0008_provider_circuit_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comic_production_runs",
        sa.Column("run_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "document_id",
            "request_hash",
            name="uq_comic_run_project_document_request",
        ),
    )
    op.create_index(
        "ix_comic_production_runs_project_id",
        "comic_production_runs",
        ["project_id"],
    )
    op.create_index(
        "ix_comic_production_runs_document_id",
        "comic_production_runs",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_comic_production_runs_document_id", table_name="comic_production_runs")
    op.drop_index("ix_comic_production_runs_project_id", table_name="comic_production_runs")
    op.drop_table("comic_production_runs")
