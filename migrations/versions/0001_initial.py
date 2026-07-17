"""initial source and workflow tables"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("project_type", sa.String(length=64), nullable=False),
        sa.Column("fidelity_mode", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "source_documents",
        sa.Column("document_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "checksum", name="uq_document_project_checksum"),
    )
    op.create_table(
        "source_chapters",
        sa.Column("chapter_id", sa.String(length=128), primary_key=True),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("start_chunk_order", sa.Integer(), nullable=False),
        sa.Column("end_chunk_order", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "source_chunks",
        sa.Column("chunk_id", sa.String(length=128), primary_key=True),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("chapter_id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("document_id", "order", name="uq_chunk_document_order"),
    )
    op.create_table(
        "workflow_runs",
        sa.Column("workflow_run_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_runs",
        sa.Column("agent_run_id", sa.String(length=128), primary_key=True),
        sa.Column("workflow_run_id", sa.String(length=128), nullable=True),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_runs")
    op.drop_table("workflow_runs")
    op.drop_table("source_chunks")
    op.drop_table("source_chapters")
    op.drop_table("source_documents")
    op.drop_table("projects")
