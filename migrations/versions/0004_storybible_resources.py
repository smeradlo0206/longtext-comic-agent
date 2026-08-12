"""persist canonical StoryBible resources and candidate commit plans"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_storybible_resources"
down_revision: str | None = "0003_agent_run_trace_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_entity_profiles",
        sa.Column("profile_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("entity_kind", sa.String(length=32), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_plan_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_story_entity_profiles_project_id", "story_entity_profiles", ["project_id"]
    )

    op.create_table(
        "story_entity_states",
        sa.Column("state_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("profile_id", sa.String(length=128), nullable=False),
        sa.Column("valid_from_order", sa.Integer(), nullable=True),
        sa.Column("valid_until_order", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_plan_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_story_entity_states_project_id", "story_entity_states", ["project_id"])
    op.create_index("ix_story_entity_states_profile_id", "story_entity_states", ["profile_id"])

    op.create_table(
        "story_relationships",
        sa.Column("relationship_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("source_profile_id", sa.String(length=128), nullable=False),
        sa.Column("target_profile_id", sa.String(length=128), nullable=False),
        sa.Column("valid_from_order", sa.Integer(), nullable=True),
        sa.Column("valid_until_order", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_plan_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_story_relationships_project_id", "story_relationships", ["project_id"])
    op.create_index(
        "ix_story_relationships_source_profile_id",
        "story_relationships",
        ["source_profile_id"],
    )
    op.create_index(
        "ix_story_relationships_target_profile_id",
        "story_relationships",
        ["target_profile_id"],
    )

    op.create_table(
        "world_rules",
        sa.Column("rule_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_plan_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_world_rules_project_id", "world_rules", ["project_id"])

    op.create_table(
        "candidate_commit_plans",
        sa.Column("commit_plan_id", sa.String(length=128), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("source_proposal_id", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "content_hash", name="uq_commit_plan_project_hash"),
    )
    op.create_index(
        "ix_candidate_commit_plans_project_id", "candidate_commit_plans", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_commit_plans_project_id", table_name="candidate_commit_plans")
    op.drop_index("ix_world_rules_project_id", table_name="world_rules")
    op.drop_index(
        "ix_story_relationships_target_profile_id", table_name="story_relationships"
    )
    op.drop_index(
        "ix_story_relationships_source_profile_id", table_name="story_relationships"
    )
    op.drop_index("ix_story_relationships_project_id", table_name="story_relationships")
    op.drop_index("ix_story_entity_states_profile_id", table_name="story_entity_states")
    op.drop_index("ix_story_entity_states_project_id", table_name="story_entity_states")
    op.drop_index("ix_story_entity_profiles_project_id", table_name="story_entity_profiles")
    op.drop_table("candidate_commit_plans")
    op.drop_table("world_rules")
    op.drop_table("story_relationships")
    op.drop_table("story_entity_states")
    op.drop_table("story_entity_profiles")
