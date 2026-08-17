"""Persist source-free Provider circuit-breaker state."""

import sqlalchemy as sa
from alembic import op

revision = "0008_provider_circuit_states"
down_revision = "0007_timeline_gate3_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_circuit_states",
        sa.Column("provider_key", sa.String(length=128), primary_key=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("provider_circuit_states")
