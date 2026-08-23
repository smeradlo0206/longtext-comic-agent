"""Database models for the MVP fact source."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from comic_agent.database.base import Base


class ProjectModel(Base):
    """Stored project record."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_type: Mapped[str] = mapped_column(String(64), nullable=False)
    fidelity_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class SourceDocumentModel(Base):
    """Stored source document metadata."""

    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("project_id", "checksum", name="uq_document_project_checksum"),
    )

    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class SourceChapterModel(Base):
    """Stored source chapter boundary."""

    __tablename__ = "source_chapters"

    chapter_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    start_chunk_order: Mapped[int] = mapped_column(Integer, nullable=False)
    end_chunk_order: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class SourceChunkModel(Base):
    """Stored source chunk text and traceability metadata."""

    __tablename__ = "source_chunks"
    __table_args__ = (UniqueConstraint("document_id", "order", name="uq_chunk_document_order"),)

    chunk_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    chapter_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class EventProposalModel(Base):
    """Stored candidate event proposed by an agent, never canonical story data."""

    __tablename__ = "event_proposals"
    __table_args__ = (
        UniqueConstraint("source_chunk_id", "agent_id", name="uq_event_proposal_chunk_agent"),
    )

    proposal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    source_chunk_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class TimelineAnalysisProposalModel(Base):
    """Stored candidate output of a whole-text timeline analysis run."""

    __tablename__ = "timeline_analysis_proposals"
    __table_args__ = (
        UniqueConstraint("project_id", "input_hash", name="uq_timeline_analysis_project_input"),
    )

    proposal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class WorkflowRunModel(Base):
    """Stored workflow run shell."""

    __tablename__ = "workflow_runs"

    workflow_run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class AgentRunModel(Base):
    """Stored agent run shell."""

    __tablename__ = "agent_runs"

    agent_run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    source_chunk_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    output_proposal_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workflow_run_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    agent_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class StoryEntityProfileModel(Base):
    """Stored canonical StoryBible entity profile."""

    __tablename__ = "story_entity_profiles"

    profile_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    last_plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class StoryEntityStateModel(Base):
    """Stored canonical, time-bound StoryBible entity state."""

    __tablename__ = "story_entity_states"

    state_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    profile_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    valid_from_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_until_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    last_plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class StoryRelationshipModel(Base):
    """Stored canonical, time-bound relationship between StoryBible profiles."""

    __tablename__ = "story_relationships"

    relationship_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    source_profile_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    target_profile_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    valid_from_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_until_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    last_plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class WorldRuleModel(Base):
    """Stored canonical StoryBible world rule."""

    __tablename__ = "world_rules"

    rule_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    last_plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class CandidateCommitPlanModel(Base):
    """Stored candidate plan awaiting CommitService processing."""

    __tablename__ = "candidate_commit_plans"
    __table_args__ = (
        UniqueConstraint("project_id", "content_hash", name="uq_commit_plan_project_hash"),
    )

    commit_plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    source_proposal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class NarrativeAnalysisRunModel(Base):
    """Persistent parent record for a resumable whole-document analysis task."""

    __tablename__ = "narrative_analysis_runs"

    analysis_run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class NarrativeAnalysisWindowModel(Base):
    """Persistent state for one mode over one planned source window."""

    __tablename__ = "narrative_analysis_windows"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id",
            "mode",
            "window_index",
            name="uq_analysis_window_mode_index",
        ),
    )

    analysis_window_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(64), nullable=False)
    window_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_run_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NarrativeAnalysisRecoveryAttemptModel(Base):
    """Append-only, noncanonical recovery attempt audit record."""

    __tablename__ = "narrative_analysis_recovery_attempts"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_recovery_attempt_key"),)

    attempt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    root_analysis_run_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TimelineGate3RunModel(Base):
    """Idempotent non-canonical Timeline/Gate 3 work record."""

    __tablename__ = "timeline_gate3_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "source_bundle_id", name="uq_timeline_gate3_project_bundle"),
        UniqueConstraint("idempotency_key", name="uq_timeline_gate3_idempotency"),
    )

    timeline_run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    source_bundle_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderCircuitStateModel(Base):
    """Persisted source-free Provider health/circuit state."""

    __tablename__ = "provider_circuit_states"

    provider_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoryBibleProductionRunModel(Base):
    """Idempotent non-canonical production StoryBible execution checkpoint."""

    __tablename__ = "storybible_production_runs"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "input_hash", name="uq_storybible_production_project_input"
        ),
    )

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    gate2_approved_bundle_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    approved_timeline_bundle_id: Mapped[str] = mapped_column(
        String(128), index=True, nullable=False
    )
    input_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoryBibleReviewRunModel(Base):
    """Deterministic review checkpoint with an optional insert-once frozen bundle."""

    __tablename__ = "storybible_review_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_storybible_run_id",
            name="uq_storybible_review_source_run",
        ),
        UniqueConstraint("bundle_id", name="uq_storybible_review_bundle"),
    )

    review_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    source_storybible_run_id: Mapped[str] = mapped_column(
        String(128), index=True, nullable=False
    )
    proposal_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    bundle_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snapshot_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
