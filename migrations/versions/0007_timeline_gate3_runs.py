"""persist idempotent Timeline Gate 3 work records"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_timeline_gate3_runs"
down_revision: str | None = "0006_narrative_analysis_recovery_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "timeline_gate3_runs",
        sa.Column("timeline_run_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("source_bundle_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "source_bundle_id",
            name="uq_timeline_gate3_project_bundle",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_timeline_gate3_idempotency"),
    )
    op.create_index("ix_timeline_gate3_runs_project_id", "timeline_gate3_runs", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_timeline_gate3_runs_project_id", table_name="timeline_gate3_runs")
    op.drop_table("timeline_gate3_runs")
