"""persist human review authorization and explicit production lineage

Schema impact: adds non-canonical human_review_runs and explicit human-review
lineage columns to production execution checkpoints. Legacy approved-bundle
columns remain readable but become nullable for HUMAN_APPROVED runs.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_human_review_production_authorization"
down_revision: str | None = "0010_storybible_review_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "human_review_runs",
        sa.Column("review_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("dossier_id", sa.String(length=128), nullable=False),
        sa.Column("dossier_hash", sa.String(length=128), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("dossier_id", name="uq_human_review_dossier"),
    )
    op.create_index("ix_human_review_runs_project_id", "human_review_runs", ["project_id"])
    op.create_index("ix_human_review_runs_dossier_id", "human_review_runs", ["dossier_id"])

    with op.batch_alter_table("storybible_production_runs") as batch:
        batch.alter_column(
            "gate2_approved_bundle_id", existing_type=sa.String(length=128), nullable=True
        )
        batch.alter_column(
            "approved_timeline_bundle_id", existing_type=sa.String(length=128), nullable=True
        )
        batch.add_column(sa.Column("human_review_id", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("production_dossier_id", sa.String(length=128), nullable=True))
        batch.add_column(
            sa.Column("narrative_execution_bundle_id", sa.String(length=128), nullable=True)
        )
        batch.add_column(
            sa.Column("timeline_review_material_id", sa.String(length=128), nullable=True)
        )
    op.create_index(
        "ix_storybible_production_runs_human_review_id",
        "storybible_production_runs",
        ["human_review_id"],
    )
    op.create_index(
        "ix_storybible_production_runs_production_dossier_id",
        "storybible_production_runs",
        ["production_dossier_id"],
    )
    op.create_index(
        "ix_storybible_production_runs_narrative_execution_bundle_id",
        "storybible_production_runs",
        ["narrative_execution_bundle_id"],
    )
    op.create_index(
        "ix_storybible_production_runs_timeline_review_material_id",
        "storybible_production_runs",
        ["timeline_review_material_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_storybible_production_runs_timeline_review_material_id",
        table_name="storybible_production_runs",
    )
    op.drop_index(
        "ix_storybible_production_runs_narrative_execution_bundle_id",
        table_name="storybible_production_runs",
    )
    op.drop_index(
        "ix_storybible_production_runs_production_dossier_id",
        table_name="storybible_production_runs",
    )
    op.drop_index(
        "ix_storybible_production_runs_human_review_id",
        table_name="storybible_production_runs",
    )
    with op.batch_alter_table("storybible_production_runs") as batch:
        batch.drop_column("timeline_review_material_id")
        batch.drop_column("narrative_execution_bundle_id")
        batch.drop_column("production_dossier_id")
        batch.drop_column("human_review_id")
        batch.alter_column(
            "approved_timeline_bundle_id", existing_type=sa.String(length=128), nullable=False
        )
        batch.alter_column(
            "gate2_approved_bundle_id", existing_type=sa.String(length=128), nullable=False
        )
    op.drop_index("ix_human_review_runs_dossier_id", table_name="human_review_runs")
    op.drop_index("ix_human_review_runs_project_id", table_name="human_review_runs")
    op.drop_table("human_review_runs")
