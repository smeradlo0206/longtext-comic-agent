"""persist production StoryBible execution checkpoints"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_storybible_production_runs"
down_revision: str | None = "0007_timeline_gate3_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storybible_production_runs",
        sa.Column("run_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("gate2_approved_bundle_id", sa.String(length=128), nullable=False),
        sa.Column("approved_timeline_bundle_id", sa.String(length=128), nullable=False),
        sa.Column("input_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "input_hash",
            name="uq_storybible_production_project_input",
        ),
    )
    op.create_index(
        "ix_storybible_production_runs_project_id",
        "storybible_production_runs",
        ["project_id"],
    )
    op.create_index(
        "ix_storybible_production_runs_gate2_approved_bundle_id",
        "storybible_production_runs",
        ["gate2_approved_bundle_id"],
    )
    op.create_index(
        "ix_storybible_production_runs_approved_timeline_bundle_id",
        "storybible_production_runs",
        ["approved_timeline_bundle_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_storybible_production_runs_approved_timeline_bundle_id",
        table_name="storybible_production_runs",
    )
    op.drop_index(
        "ix_storybible_production_runs_gate2_approved_bundle_id",
        table_name="storybible_production_runs",
    )
    op.drop_index(
        "ix_storybible_production_runs_project_id",
        table_name="storybible_production_runs",
    )
    op.drop_table("storybible_production_runs")
