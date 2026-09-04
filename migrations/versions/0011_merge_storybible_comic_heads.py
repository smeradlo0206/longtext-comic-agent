"""Merge StoryBible and comic production migration branches."""

from collections.abc import Sequence

revision: str = "0011_merge_storybible_comic_heads"
down_revision: tuple[str, str] = (
    "0009_comic_production_runs",
    "0010_storybible_review_runs",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the two schema branches without changing tables."""


def downgrade() -> None:
    """Split the migration graph without changing tables."""
