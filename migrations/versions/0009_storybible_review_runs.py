"""persist deterministic StoryBible review and frozen bundle checkpoints

Schema impact: adds StoryBibleReviewResultV1 and ApprovedStoryBibleBundleV1
persistence without changing the StoryBible production run state machine.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_storybible_review_runs"
down_revision: str | None = "0008_storybible_production_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storybible_review_runs",
        sa.Column("review_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("source_storybible_run_id", sa.String(length=128), nullable=False),
        sa.Column("proposal_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("bundle_id", sa.String(length=128), nullable=True),
        sa.Column("snapshot_hash", sa.String(length=128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "source_storybible_run_id",
            name="uq_storybible_review_source_run",
        ),
        sa.UniqueConstraint("bundle_id", name="uq_storybible_review_bundle"),
    )
    op.create_index(
        "ix_storybible_review_runs_project_id",
        "storybible_review_runs",
        ["project_id"],
    )
    op.create_index(
        "ix_storybible_review_runs_source_storybible_run_id",
        "storybible_review_runs",
        ["source_storybible_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_storybible_review_runs_source_storybible_run_id",
        table_name="storybible_review_runs",
    )
    op.drop_index(
        "ix_storybible_review_runs_project_id",
        table_name="storybible_review_runs",
    )
    op.drop_table("storybible_review_runs")
