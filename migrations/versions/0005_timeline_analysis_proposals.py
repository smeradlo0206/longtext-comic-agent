"""store timeline analysis candidates"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_timeline_analysis_proposals"
down_revision: str | None = "0004_storybible_resources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "timeline_analysis_proposals",
        sa.Column("proposal_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("input_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "input_hash", name="uq_timeline_analysis_project_input"),
    )
    op.create_index(
        "ix_timeline_analysis_proposals_project_id",
        "timeline_analysis_proposals",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_timeline_analysis_proposals_project_id", table_name="timeline_analysis_proposals"
    )
    op.drop_table("timeline_analysis_proposals")
