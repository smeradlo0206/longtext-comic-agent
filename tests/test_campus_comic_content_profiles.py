"""Campus content-profile and approved Narrative-to-Timeline boundary tests."""

from typing import TypeVar

import pytest
from pydantic import BaseModel, ValidationError

from comic_agent.agents.narrative_analyst import NarrativeAnalyst
from comic_agent.schemas import (
    ApprovedProposalBundleV1,
    ApprovedProposalItemV1,
    CampusAudience,
    CampusComicTone,
    CampusContentProfileProposalV1,
    CampusContentType,
    ClaimProposalV1,
    ComicBeatProposalV1,
    NarrativeAnalysisResultV1,
    NarrativeAnalysisReviewRouteV1,
    ReviewableProposalEnvelopeV1,
    ReviewGate2RoutingDecision,
    ReviewGate2RunStatus,
    SourceChunkV1,
)
from comic_agent.services.id_service import checksum_text
from comic_agent.services.narrative_timeline_input_adapter import NarrativeTimelineInputAdapter


def _evidence() -> dict[str, object]:
    return {"chunk_id": "chunk-1", "quote_text": "活动将于9月1日在礼堂举行"}


def _chunk() -> SourceChunkV1:
    text = "活动将于9月1日在礼堂举行"
    return SourceChunkV1(
        chunk_id="chunk-1", project_id="project-1", document_id="document-1",
        chapter_id="chapter-1", order=0, text=text, checksum=checksum_text(text),
    )


def _claim(claim_id: str = "fact-date") -> ClaimProposalV1:
    return ClaimProposalV1(
        proposal_id="claim-date", claim_id=claim_id, claim_type="FACTUAL_ASSERTION",
        claim_text="活动日期为9月1日", temporal_scope="PRESENT", source_type="NARRATOR",
        verification_status="SUPPORTED", evidence_refs=[_evidence()], confidence=0.9,
        reality_layer="PRIMARY",
    )


def _profile(fact_id: str = "fact-date") -> CampusContentProfileProposalV1:
    return CampusContentProfileProposalV1(
        proposal_id="profile-1", project_id="project-1", content_type="event_promotion",
        audience=["student"], must_preserve_fact_ids=[fact_id], tone="lively",
        page_budget=4, evidence_refs=[_evidence()], confidence=0.9,
    )


def test_campus_profile_schema_contract_boundaries() -> None:
    for content_type in CampusContentType:
        profile = _profile().model_copy(update={"content_type": content_type})
        assert profile.content_type == content_type
    for audience in CampusAudience:
        assert audience in _profile().model_copy(update={"audience": [audience]}).audience
    for tone in CampusComicTone:
        assert _profile().model_copy(update={"tone": tone}).tone == tone
    assert _profile().model_copy(update={"page_budget": 1}).page_budget == 1
    assert _profile().model_copy(update={"page_budget": 24}).page_budget == 24
    for update in (
        {"page_budget": 0},
        {"page_budget": 25},
        {"status": "APPROVED"},
        {"must_preserve_fact_ids": []},
        {"must_preserve_fact_ids": ["fact-date", "fact-date"]},
        {"evidence_refs": []},
    ):
        with pytest.raises(ValidationError):
            CampusContentProfileProposalV1.model_validate(_profile().model_dump() | update)


def test_comic_beat_schema_contract_boundaries() -> None:
    base = {
        "proposal_id": "beat-1", "project_id": "project-1", "content_profile_id": "profile-1",
        "beat_index": 1, "purpose": "INTRO", "source_fact_ids": ["fact-date"],
        "visual_intent": "校园活动公告", "must_show": ["活动名称"], "must_not_show": ["未证实获奖"],
        "evidence_refs": [_evidence()], "confidence": 0.8,
    }
    assert ComicBeatProposalV1.model_validate(base).beat_index == 1
    for update in (
        {"source_fact_ids": []},
        {"beat_index": 0},
        {"status": "CANONICAL"},
        {"must_show": ["x", "x"]},
        {"must_not_show": ["x", "x"]},
        {"must_show": ["x"], "must_not_show": ["x"]},
    ):
        with pytest.raises(ValidationError):
            ComicBeatProposalV1.model_validate(base | update)


def test_historical_narrative_result_without_campus_profiles_remains_readable() -> None:
    result = NarrativeAnalysisResultV1.model_validate(
        {
            "schema_version": "1.4",
            "analysis_run_id": "analysis-legacy",
            "events": [],
            "entities": [],
            "claims": [],
            "knowledge_states": [],
            "state_changes": [],
            "relationship_signals": [],
        }
    )
    assert result.campus_content_profiles == []


OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class _ProfileProvider:
    def __init__(self, profile: dict[str, object]) -> None:
        self.profile = profile
        self.calls = 0

    def structured_generate(
        self, request: dict[str, object], output_model: type[OutputModelT]
    ) -> OutputModelT:
        self.calls += 1
        return output_model.model_validate(self.profile)


def test_campus_profile_mode_uses_only_supplied_factual_claims_and_source_evidence() -> None:
    provider = _ProfileProvider(_profile().model_dump(mode="json"))
    profile = NarrativeAnalyst(provider).run(
        "campus_content_profile",
        {
            "project_id": "project-1", "source_chunk_ids": ["chunk-1"],
            "source_chunks": [_chunk()], "claim_proposals": [_claim()],
            "claim_project_ids": {"fact-date": "project-1"},
        },
    )
    assert profile.must_preserve_fact_ids == ["fact-date"]
    assert provider.calls == 1


@pytest.mark.parametrize("fact_id, claim, projects", [
    ("missing", _claim(), {"fact-date": "project-1"}),
    ("fact-date", _claim(), {"fact-date": "other-project"}),
    ("fact-date", _claim().model_copy(update={"evidence_refs": []}), {"fact-date": "project-1"}),
])
def test_campus_profile_mode_rejects_unusable_fact_references(
    fact_id: str, claim: ClaimProposalV1, projects: dict[str, str]
) -> None:
    provider = _ProfileProvider(_profile(fact_id).model_dump(mode="json"))
    with pytest.raises(ValueError):
        NarrativeAnalyst(provider).run(
            "campus_content_profile",
            {
                "project_id": "project-1",
                "source_chunk_ids": ["chunk-1"],
                "source_chunks": [_chunk()],
                "claim_proposals": [claim],
                "claim_project_ids": projects,
            },
        )


def _approved_route(
    profile: CampusContentProfileProposalV1, claim: ClaimProposalV1
) -> NarrativeAnalysisReviewRouteV1:
    items = [
        ApprovedProposalItemV1(
            source=ReviewableProposalEnvelopeV1(
                mode="campus_content_profile",
                proposal_schema="CampusContentProfileProposalV1",
                proposal=profile,
                agent_run_ids=["agent-profile"],
                aggregated_evidence_refs=profile.evidence_refs,
            ),
            review_decision_id="decision-profile",
        ),
        ApprovedProposalItemV1(source=ReviewableProposalEnvelopeV1(
            mode="claim_extraction", proposal_schema="ClaimProposalV1", proposal=claim,
            agent_run_ids=["agent-claim"], aggregated_evidence_refs=claim.evidence_refs,
        ), review_decision_id="decision-claim"),
    ]
    bundle = ApprovedProposalBundleV1(
        bundle_id="bundle-1", project_id="project-1", document_id="document-1",
        analysis_run_id="analysis-1", review_run_id="review-1", policy_id="policy-1",
        approved_proposals=items, review_decision_ids=["decision-profile", "decision-claim"],
    )
    return NarrativeAnalysisReviewRouteV1(
        analysis_run_id="analysis-1", review_run_id="review-1", decision="APPROVED",
        review_status="COMPLETED", total_count=2, approved_count=2, rejected_count=0,
        held_count=0, approved_proposal_bundle=bundle,
    )


def test_approved_bundle_profile_builds_stable_timeline_input_with_fact_claim() -> None:
    route = _approved_route(_profile(), _claim())
    adapter = NarrativeTimelineInputAdapter()
    first = adapter.build(route=route, profile_id="profile-1", source_chunks=[_chunk()])
    second = adapter.build(route=route, profile_id="profile-1", source_chunks=[_chunk()])
    assert first.schema_version == "1.2"
    assert [claim.claim_id for claim in first.claim_proposals] == ["fact-date"]
    assert first.source_approved_bundle_id == "bundle-1"
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_adapter_rejects_raw_aggregate_and_profile_missing_from_bundle() -> None:
    with pytest.raises(ValueError):
        NarrativeTimelineInputAdapter().build(
            route=object(),  # type: ignore[arg-type]
            profile_id="profile-1",
            source_chunks=[_chunk()],
        )
    with pytest.raises(ValueError):
        NarrativeTimelineInputAdapter().build(
            route=_approved_route(_profile(), _claim()),
            profile_id="profile-not-in-bundle",
            source_chunks=[_chunk()],
        )


@pytest.mark.parametrize("decision,status", [
    (ReviewGate2RoutingDecision.REJECTED, ReviewGate2RunStatus.COMPLETED),
    (ReviewGate2RoutingDecision.NEEDS_HUMAN_REVIEW, ReviewGate2RunStatus.NEEDS_HUMAN_REVIEW),
    (ReviewGate2RoutingDecision.FAILED, ReviewGate2RunStatus.FAILED),
])
def test_adapter_rejects_nonapproved_routes_without_timeline_call(
    decision: ReviewGate2RoutingDecision, status: ReviewGate2RunStatus
) -> None:
    route = _approved_route(_profile(), _claim()).model_copy(
        update={
            "decision": decision,
            "review_status": status,
            "approved_proposal_bundle": None,
            "approved_count": 0,
            "rejected_count": (
                2 if decision == ReviewGate2RoutingDecision.REJECTED else 0
            ),
            "held_count": (
                2 if decision == ReviewGate2RoutingDecision.NEEDS_HUMAN_REVIEW else 0
            ),
        }
    )
    with pytest.raises(ValueError):
        NarrativeTimelineInputAdapter().build(
            route=route, profile_id="profile-1", source_chunks=[_chunk()]
        )
