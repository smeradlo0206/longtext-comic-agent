"""persist bounded narrative-analysis recovery attempt audits"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_narrative_analysis_recovery_attempts"
down_revision: str | None = "0004_storybible_resources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "narrative_analysis_recovery_attempts",
        sa.Column("attempt_id", sa.String(length=128), primary_key=True),
        sa.Column("root_analysis_run_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_recovery_attempt_key"),
    )
    op.create_index(
        "ix_narrative_analysis_recovery_attempts_root_analysis_run_id",
        "narrative_analysis_recovery_attempts",
        ["root_analysis_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_narrative_analysis_recovery_attempts_root_analysis_run_id",
        table_name="narrative_analysis_recovery_attempts",
    )
    op.drop_table("narrative_analysis_recovery_attempts")
