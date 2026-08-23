"""Human-approved StoryBible execution preparation uses only fake local collaborators."""

from datetime import UTC, datetime
from threading import Lock
from typing import Any

import pytest

from comic_agent.config import Settings
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.human_review import (
    HumanReviewDecision,
    HumanReviewLineageV1,
    HumanReviewRunV1,
)
from comic_agent.schemas.narrative import EventProposalV1, TemporalRelationProposalV1
from comic_agent.schemas.review import (
    NarrativeExecutionStatus,
    ReviewableProposalEnvelopeV1,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    HumanApprovedStoryBibleProductionContextV1,
    HumanApprovedStoryBibleProductionExecutionFailureCode,
    HumanApprovedStoryBibleProductionLineageV1,
    ProductionDossierNarrativeSummaryV1,
    ProductionDossierProvenanceV1,
    ProductionDossierTimelineSummaryV1,
    ProductionDossierV1,
    ProfileUpdateProposalV1,
    StoryBibleCanonicalSnapshotV1,
    StoryBibleCuratorProposalV1,
    StoryBibleProductionAuthorizationKind,
    StoryBibleProductionRunStatus,
    StoryBibleProductionRunV1,
    StoryEntityProfileV1,
)
from comic_agent.schemas.timeline import ReviewGate3Decision, TimelineAnalysisProposalV1
from comic_agent.schemas.workflow import AgentRunV1
from comic_agent.services.human_approved_storybible_production_execution_adapter import (
    HumanApprovedStoryBibleProductionExecutionAdapter,
)
from comic_agent.services.production_dossier_identity import production_dossier_content_hash
from comic_agent.services.storybible_production_coordinator import (
    StoryBibleProductionCoordinator,
)
from comic_agent.services.storybible_production_output_normalizer import (
    StoryBibleProductionOutputNormalizer,
)


def _context() -> HumanApprovedStoryBibleProductionContextV1:
    chunk = SourceChunkV1(
        chunk_id="chunk-1",
        project_id="project-1",
        document_id="document-1",
        chapter_id="chapter-1",
        order=0,
        text="Xia Ming arrived.",
        checksum="safe",
    )
    evidence = EvidenceRefV1(chunk_id=chunk.chunk_id, quote_text=chunk.text)
    first = EventProposalV1(
        proposal_id="event-1",
        event_type="ARRIVAL",
        summary="Xia Ming arrived.",
        evidence_refs=[evidence],
        confidence=0.9,
        reality_layer=RealityLayer.PRIMARY,
    )
    second = EventProposalV1(
        proposal_id="event-2",
        event_type="BELL",
        summary="The bell rang.",
        evidence_refs=[evidence],
        confidence=0.9,
        reality_layer=RealityLayer.PRIMARY,
    )
    relation = TemporalRelationProposalV1(
        proposal_id="relation-1",
        source_event_id=first.proposal_id,
        target_event_id=second.proposal_id,
        relation="BEFORE",
        evidence_refs=[evidence],
        confidence=0.9,
    )
    return HumanApprovedStoryBibleProductionContextV1(
        project_id="project-1",
        human_review_id="human-review-1",
        human_review_decision="APPROVE",
        reviewer_id="reviewer-1",
        review_time=datetime(2026, 8, 23, tzinfo=UTC),
        dossier_id="dossier-1",
        narrative_execution_bundle_id="narrative-execution-1",
        timeline_review_material_id="timeline-material-1",
        narrative_analysis_run_id="analysis-run-1",
        timeline_run_id="timeline-run-1",
        human_approved_events=[first, second],
        human_approved_temporal_relations=[relation],
        narrative_execution_status=NarrativeExecutionStatus.SUCCEEDED,
        timeline_review_status=ReviewGate3Decision.NEEDS_HUMAN_REVIEW,
        evidence_refs=[evidence],
        source_chunk_ids=[chunk.chunk_id],
        source_chunks=[chunk],
        canonical_snapshot=StoryBibleCanonicalSnapshotV1(project_id="project-1"),
    )


def _dossier() -> ProductionDossierV1:
    context = _context()
    candidates = [
        ReviewableProposalEnvelopeV1(
            mode="event_extraction",
            proposal_schema="EventProposalV1",
            proposal=event,
            agent_run_ids=["agent-run-1"],
            aggregated_evidence_refs=event.evidence_refs,
        )
        for event in context.human_approved_events
    ]
    timeline_candidate = TimelineAnalysisProposalV1(
        proposal_id="timeline-candidate-1",
        project_id=context.project_id,
        temporal_relations=context.human_approved_temporal_relations,
        evidence_refs=context.evidence_refs,
        confidence=0.9,
    )
    return ProductionDossierV1(
        dossier_id=context.dossier_id,
        project_id=context.project_id,
        document_id="document-1",
        narrative_execution_bundle_id=context.narrative_execution_bundle_id,
        timeline_review_material_id=context.timeline_review_material_id,
        evidence_refs=context.evidence_refs,
        narrative_summary=ProductionDossierNarrativeSummaryV1(
            execution_status=context.narrative_execution_status,
            candidates=candidates,
            evidence_refs=context.evidence_refs,
        ),
        timeline_summary=ProductionDossierTimelineSummaryV1(
            timeline_candidate=timeline_candidate,
            temporal_relations=context.human_approved_temporal_relations,
            review_status=context.timeline_review_status,
            evidence_refs=context.evidence_refs,
        ),
        provenance=ProductionDossierProvenanceV1(
            narrative_analysis_run_id=context.narrative_analysis_run_id,
            gate1_review_id="gate1-review-1",
            timeline_run_id=context.timeline_run_id,
            source_chunk_ids=context.source_chunk_ids,
        ),
    )


class _RunRepository:
    def __init__(self) -> None:
        self.run: StoryBibleProductionRunV1 | None = None

    def reserve_human_approved_run(
        self,
        production_input: Any,
        *,
        lineage: HumanApprovedStoryBibleProductionLineageV1,
        model_identity: str,
    ) -> StoryBibleProductionRunV1:
        if self.run is None:
            now = datetime.now(UTC)
            self.run = StoryBibleProductionRunV1(
                schema_version="1.2",
                run_id="human-storybible-run-1",
                project_id=production_input.project_id,
                gate2_approved_bundle_id=production_input.gate2_approved_bundle_id,
                approved_timeline_bundle_id=production_input.approved_timeline_bundle_id,
                human_review_id=production_input.human_review_id,
                production_dossier_id=production_input.production_dossier_id,
                narrative_execution_bundle_id=production_input.narrative_execution_bundle_id,
                timeline_review_material_id=production_input.timeline_review_material_id,
                canonical_storybible_snapshot_hash=(
                    production_input.canonical_storybible_snapshot_hash
                ),
                input_hash="human-input-1",
                model_identity=model_identity,
                status=StoryBibleProductionRunStatus.RESERVED,
                authorization_kind=StoryBibleProductionAuthorizationKind.HUMAN_APPROVED,
                human_approved_lineage=lineage,
                created_at=now,
                updated_at=now,
            )
        return self.run

    def get_run(self, _: str) -> StoryBibleProductionRunV1 | None:
        return self.run

    def claim_execution(self, _: str) -> bool:
        assert self.run is not None
        if self.run.status != StoryBibleProductionRunStatus.RESERVED:
            return False
        self.run = self.run.model_copy(
            update={
                "status": StoryBibleProductionRunStatus.RUNNING,
                "provider_request_count": 1,
                "updated_at": datetime.now(UTC),
            }
        )
        return True

    def save_success(
        self, _: str, *, curator_proposal: Any, agent_run_id: str
    ) -> StoryBibleProductionRunV1:
        assert self.run is not None
        self.run = self.run.model_copy(
            update={
                "status": StoryBibleProductionRunStatus.SUCCEEDED,
                "curator_proposal": curator_proposal,
                "agent_run_id": agent_run_id,
            }
        )
        return self.run

    def save_failure(self, run_id: str, **kwargs: Any) -> StoryBibleProductionRunV1:
        del run_id, kwargs
        raise AssertionError("the success-path fake must not record a failure")


class _HumanReviewRepository:
    def __init__(
        self,
        dossier: ProductionDossierV1,
        decision: HumanReviewDecision = HumanReviewDecision.APPROVE,
    ) -> None:
        self._dossier = dossier
        self._decision = decision

    def get_by_review_id(self, review_id: str) -> HumanReviewRunV1 | None:
        context = _context()
        if review_id != context.human_review_id:
            return None
        return HumanReviewRunV1(
            review_id=context.human_review_id,
            project_id=context.project_id,
            dossier_id=context.dossier_id,
            dossier_hash=production_dossier_content_hash(self._dossier),
            decision=self._decision,
            reviewer_id=context.reviewer_id,
            created_at=context.review_time,
            lineage=HumanReviewLineageV1(
                source_dossier_id=context.dossier_id,
                narrative_execution_bundle_id=context.narrative_execution_bundle_id,
                timeline_review_material_id=context.timeline_review_material_id,
            ),
        )


class _DossierRepository:
    def __init__(self, dossier: ProductionDossierV1 | None = None) -> None:
        self.dossier = dossier or _dossier()

    def get_by_dossier_id(self, dossier_id: str) -> ProductionDossierV1 | None:
        return self.dossier if dossier_id == self.dossier.dossier_id else None


class _ContextLoader:
    def __init__(self, context: HumanApprovedStoryBibleProductionContextV1 | None = None) -> None:
        self.context = context or _context()

    def load(self, *, review: Any, dossier: Any) -> HumanApprovedStoryBibleProductionContextV1:
        assert review.dossier_id == dossier.dossier_id
        return self.context


class _AgentRuns:
    def save_agent_run(self, value: AgentRunV1) -> AgentRunV1:
        return value

    def get_agent_run(self, _: str) -> AgentRunV1 | None:
        return None


class _Curator:
    class spec:
        max_context_chunks = 3

    def __init__(self) -> None:
        self.calls = 0
        self._lock = Lock()

    def run(self, _: Any, __: Any) -> StoryBibleCuratorProposalV1:
        with self._lock:
            self.calls += 1
        evidence = EvidenceRefV1(chunk_id="chunk-1", quote_text="Xia Ming arrived.")
        profile = StoryEntityProfileV1(
            profile_id="profile-local",
            project_id="project-1",
            entity_kind="PERSON",
            canonical_name="Xia Ming",
            evidence_refs=[evidence],
        )
        update = ProfileUpdateProposalV1(
            update_id="update-local",
            project_id="project-1",
            profile=profile,
            evidence_refs=[evidence],
        )
        return StoryBibleCuratorProposalV1(
            proposal_id="proposal-local",
            project_id="project-1",
            commit_plan=CommitPlanV1(
                commit_plan_id="plan-local",
                project_id="project-1",
                source_proposal_id="proposal-local",
                content_hash="untrusted",
                updates=[update],
                evidence_refs=[evidence],
            ),
            evidence_refs=[evidence],
            confidence=0.8,
        )


def _adapter(
    *,
    decision: HumanReviewDecision = HumanReviewDecision.APPROVE,
    context: HumanApprovedStoryBibleProductionContextV1 | None = None,
    dossier: ProductionDossierV1 | None = None,
    review_dossier: ProductionDossierV1 | None = None,
) -> tuple[HumanApprovedStoryBibleProductionExecutionAdapter, _RunRepository]:
    runs = _RunRepository()
    durable_dossier = dossier or _dossier()
    return (
        HumanApprovedStoryBibleProductionExecutionAdapter(
            runs,
            _HumanReviewRepository(review_dossier or durable_dossier, decision),  # type: ignore[arg-type]
            _DossierRepository(durable_dossier),  # type: ignore[arg-type]
            _ContextLoader(context),  # type: ignore[arg-type]
        ),
        runs,
    )


def test_human_approved_context_prepares_and_executes_with_preserved_lineage() -> None:
    adapter, runs = _adapter()
    result = adapter.build_and_reserve(
        project_id="project-1", human_review_id="human-review-1", model_identity="fake-curator-v1"
    )

    assert result.failure_code is None
    assert result.prepared is not None
    prepared = result.prepared
    assert prepared.context.trusted_evidence_refs == _context().evidence_refs
    assert prepared.run.human_approved_lineage is not None
    assert prepared.run.human_approved_lineage.dossier_id == "dossier-1"

    curator = _Curator()
    coordinator = StoryBibleProductionCoordinator(
        input_builder=object(),  # type: ignore[arg-type]
        run_repository=runs,  # type: ignore[arg-type]
        curator=curator,  # type: ignore[arg-type]
        output_normalizer=StoryBibleProductionOutputNormalizer(),
        agent_run_repository=_AgentRuns(),  # type: ignore[arg-type]
        settings=Settings(_env_file=None, enable_real_llm=True),
    )
    completed = coordinator.run_prepared(
        prepared=prepared,
        model_identity="fake-curator-v1",
        real_llm_requested=True,
    )

    assert completed.status == StoryBibleProductionRunStatus.SUCCEEDED
    assert curator.calls == 1
    assert completed.human_approved_lineage == prepared.run.human_approved_lineage
    assert completed.human_approved_lineage is not None
    assert completed.human_approved_lineage.human_review_id == "human-review-1"


def test_rejected_or_changes_requested_review_never_prepares_execution() -> None:
    for decision in (HumanReviewDecision.REJECT, HumanReviewDecision.REQUEST_CHANGES):
        adapter, _ = _adapter(decision=decision)
        result = adapter.build_and_reserve(
            project_id="project-1",
            human_review_id="human-review-1",
            model_identity="fake-curator-v1",
        )
        assert (
            result.failure_code
            == HumanApprovedStoryBibleProductionExecutionFailureCode.HUMAN_REVIEW_NOT_APPROVED
        )
        assert result.prepared is None


def test_forged_context_from_loader_is_rejected_without_execution() -> None:
    adapter, _ = _adapter(context=_context().model_copy(update={"project_id": "project-2"}))
    result = adapter.build_and_reserve(
        project_id="project-1", human_review_id="human-review-1", model_identity="fake-curator-v1"
    )

    assert (
        result.failure_code
        == HumanApprovedStoryBibleProductionExecutionFailureCode.INVALID_HUMAN_APPROVED_CONTEXT
    )
    assert result.prepared is None


def test_caller_cannot_supply_a_forged_dossier_derived_context() -> None:
    adapter, _ = _adapter()

    with pytest.raises(TypeError):
        adapter.build_and_reserve(_context(), model_identity="fake-curator-v1")  # type: ignore[call-arg]


def test_dossier_payload_hash_mismatch_never_reserves_production() -> None:
    approved = _dossier()
    tampered = approved.model_copy(
        update={
            "provenance": approved.provenance.model_copy(
                update={"gate1_review_id": "tampered-gate1-review"}
            )
        }
    )
    adapter, runs = _adapter(dossier=tampered, review_dossier=approved)

    result = adapter.build_and_reserve(
        project_id="project-1", human_review_id="human-review-1", model_identity="fake-curator-v1"
    )

    assert result.failure_code == "INVALID_HUMAN_APPROVED_CONTEXT"
    assert runs.run is None


def test_legacy_input_remains_legacy_authorized() -> None:
    from comic_agent.schemas.storybible import StoryBibleProductionInputV1

    value = StoryBibleProductionInputV1(
        project_id="project-1",
        gate2_approved_bundle_id="gate2-1",
        approved_timeline_bundle_id="timeline-1",
        canonical_storybible_snapshot_hash="snapshot-1",
    )

    assert value.authorization_kind == StoryBibleProductionAuthorizationKind.LEGACY_APPROVED
    assert value.human_approved_lineage is None
