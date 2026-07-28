"""add input and output links to agent runs"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_agent_run_trace_columns"
down_revision: str | None = "0002_event_proposals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("project_id", sa.String(length=128), nullable=True))
    op.add_column("agent_runs", sa.Column("source_chunk_id", sa.String(length=128), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("output_proposal_id", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_agent_runs_project_id", "agent_runs", ["project_id"])
    op.create_index("ix_agent_runs_source_chunk_id", "agent_runs", ["source_chunk_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_source_chunk_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_project_id", table_name="agent_runs")
    op.drop_column("agent_runs", "output_proposal_id")
    op.drop_column("agent_runs", "source_chunk_id")
    op.drop_column("agent_runs", "project_id")
