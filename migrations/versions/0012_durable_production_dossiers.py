"""persist immutable ProductionDossier payloads for human approval binding

Schema impact: stores non-canonical dossier payloads and a deterministic content
hash.  Downgrade deliberately refuses to discard any review/dossier material.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_durable_production_dossiers"
down_revision: str | None = "0011_human_review_production_authorization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "production_dossiers",
        sa.Column("dossier_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_production_dossiers_project_id", "production_dossiers", ["project_id"])
    op.create_index("ix_production_dossiers_document_id", "production_dossiers", ["document_id"])


def downgrade() -> None:
    bind = op.get_bind()
    dossier_count = bind.execute(sa.text("SELECT COUNT(*) FROM production_dossiers")).scalar_one()
    review_count = bind.execute(sa.text("SELECT COUNT(*) FROM human_review_runs")).scalar_one()
    if dossier_count or review_count:
        raise RuntimeError(
            "cannot downgrade durable dossier binding while human review material exists"
        )
    op.drop_index("ix_production_dossiers_document_id", table_name="production_dossiers")
    op.drop_index("ix_production_dossiers_project_id", table_name="production_dossiers")
    op.drop_table("production_dossiers")
