"""Schema contract for local, human-reviewed reference-asset intake."""

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from comic_agent.schemas.base import StrictBaseModel


class AssetType(StrEnum):
    """Bounded kinds of reference assets; these are not production prompts."""

    POSE_REFERENCE = "POSE_REFERENCE"
    EXPRESSION_REFERENCE = "EXPRESSION_REFERENCE"
    CHARACTER_REFERENCE = "CHARACTER_REFERENCE"
    THREE_D_POSE_SOURCE = "3D_POSE_SOURCE"
    OTHER_REFERENCE = "OTHER_REFERENCE"


class UseMode(StrEnum):
    """Whether an asset may be considered for production after human review."""

    PRODUCTION_CANDIDATE = "PRODUCTION_CANDIDATE"
    REFERENCE_ONLY = "REFERENCE_ONLY"


class RightsStatus(StrEnum):
    """Verified license state, kept separate from a human review decision."""

    VERIFIED_CC0 = "VERIFIED_CC0"
    VERIFIED_PUBLIC_DOMAIN = "VERIFIED_PUBLIC_DOMAIN"
    ATTRIBUTION_REQUIRED = "ATTRIBUTION_REQUIRED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    REJECTED = "REJECTED"


class ReviewStatus(StrEnum):
    """Local reviewer decision; collection never creates APPROVED records."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    REJECTED = "REJECTED"


_ERA_TAGS = frozenset({"modern", "ancient", "neutral"})
_COMPOSITION_TAGS = frozenset(
    {
        "front_view",
        "side_view",
        "back_view",
        "three_quarter_view",
        "close_up",
        "medium_shot",
        "wide_shot",
        "high_angle",
        "low_angle",
        "single_person",
        "two_person",
        "group",
    }
)
_ACTION_OR_EXPRESSION_TAGS = frozenset(
    {
        "standing",
        "walking",
        "running",
        "sitting",
        "reading",
        "writing",
        "typing",
        "talking",
        "listening",
        "pointing",
        "waving",
        "holding_phone",
        "holding_umbrella",
        "holding_bag",
        "opening_door",
        "handing_object",
        "receiving_object",
        "hugging",
        "arguing",
        "falling",
        "crouching",
        "hiding",
        "looking_back",
        "ancient_standing",
        "walking_in_robe",
        "bowing",
        "kneeling",
        "sitting_on_floor",
        "holding_sword",
        "drawing_sword",
        "sword_duel",
        "riding_horse",
        "holding_scroll",
        "serving_tea",
        "carrying_lantern",
        "cloak_walking",
        "two_person_confrontation",
        "neutral",
        "happy",
        "smiling",
        "laughing",
        "surprised",
        "worried",
        "nervous",
        "sad",
        "crying",
        "angry",
        "embarrassed",
        "tired",
        "focused",
        "determined",
        "suspicious",
    }
)


class AssetManifestV1(StrictBaseModel):
    """Portable audit record for a downloaded asset or a reference-only link.

    Runtime manifests live outside Git.  The model intentionally has no provider
    response, credential, cookie, or absolute local path field.
    """

    schema_version: Literal["1.0"] = "1.0"
    asset_id: str = Field(min_length=1, max_length=160)
    source_id: str = Field(min_length=1, max_length=500)
    source_site: str = Field(min_length=1, max_length=120)
    source_api_or_package_url: str = Field(min_length=1, max_length=2048)
    original_asset_url: str | None = Field(default=None, max_length=2048)
    original_page_url: str = Field(min_length=1, max_length=2048)
    creator: str | None = Field(default=None, max_length=500)
    title: str | None = Field(default=None, max_length=500)
    license_code: str | None = Field(default=None, max_length=100)
    license_url: str | None = Field(default=None, max_length=2048)
    attribution_text: str | None = Field(default=None, max_length=1000)
    asset_type: AssetType
    use_mode: UseMode
    rights_status: RightsStatus
    review_status: ReviewStatus = ReviewStatus.PENDING
    local_relative_path: str | None = Field(default=None, max_length=512)
    thumbnail_relative_path: str | None = Field(default=None, max_length=512)
    checksum: str | None = Field(default=None, min_length=64, max_length=64)
    bytes_size: int | None = Field(default=None, ge=0)
    tags: list[str] = Field(min_length=4, max_length=32)
    search_query: str = Field(min_length=1, max_length=300)
    collected_at: datetime
    reviewed_at: datetime | None = None
    reviewer_note: str | None = Field(default=None, max_length=2000)

    @field_validator("local_relative_path", "thumbnail_relative_path")
    @classmethod
    def relative_path_only(cls, value: str | None) -> str | None:
        """Reject machine-specific and traversal paths from portable manifests."""

        if value is None:
            return value
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
            raise ValueError("asset paths must be safe relative paths")
        return path.as_posix()

    @field_validator("tags")
    @classmethod
    def controlled_tag_minimum(cls, value: list[str]) -> list[str]:
        """Require auditable classification dimensions without generating labels."""

        if len(value) != len(set(value)):
            raise ValueError("tags must be unique")
        tag_set = set(value)
        if not tag_set & _ERA_TAGS:
            raise ValueError("tags require one modern, ancient, or neutral era tag")
        if not tag_set & _COMPOSITION_TAGS:
            raise ValueError("tags require one composition tag")
        if not tag_set & _ACTION_OR_EXPRESSION_TAGS:
            raise ValueError("tags require one controlled action or expression tag")
        if not any(tag.startswith("source:") for tag in tag_set):
            raise ValueError("tags require a source tag")
        if not any(tag.startswith("license:") for tag in tag_set):
            raise ValueError("tags require a license tag")
        return value

    @model_validator(mode="after")
    def validate_storage_and_review(self) -> "AssetManifestV1":
        """Keep review decisions and local storage auditable and non-destructive."""

        if self.local_relative_path is not None and (
            self.checksum is None or self.bytes_size is None
        ):
            raise ValueError("downloaded assets require path, checksum, and bytes_size together")
        if self.checksum is not None and self.local_relative_path is None:
            raise ValueError("a checksum requires a downloaded local asset path")
        if self.review_status == ReviewStatus.APPROVED and self.reviewed_at is None:
            raise ValueError("approved assets require reviewed_at")
        if self.review_status in {ReviewStatus.REFERENCE_ONLY, ReviewStatus.REJECTED} and (
            self.reviewed_at is None
        ):
            raise ValueError("reviewed assets require reviewed_at")
        if (
            self.review_status == ReviewStatus.REJECTED
            and self.rights_status != RightsStatus.REJECTED
        ):
            raise ValueError("rejected review status requires rejected rights status")
        return self
