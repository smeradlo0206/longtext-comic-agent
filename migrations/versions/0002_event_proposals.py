"""store candidate event proposals"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_event_proposals"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_proposals",
        sa.Column("proposal_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("source_chunk_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_chunk_id", "agent_id", name="uq_event_proposal_chunk_agent"),
    )
    op.create_index("ix_event_proposals_project_id", "event_proposals", ["project_id"])
    op.create_index("ix_event_proposals_source_chunk_id", "event_proposals", ["source_chunk_id"])


def downgrade() -> None:
    op.drop_index("ix_event_proposals_source_chunk_id", table_name="event_proposals")
    op.drop_index("ix_event_proposals_project_id", table_name="event_proposals")
    op.drop_table("event_proposals")
