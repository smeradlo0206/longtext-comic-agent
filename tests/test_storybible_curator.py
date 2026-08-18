import json
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from comic_agent.agents.storybible_curator import StoryBibleCurator
from comic_agent.schemas.base import RecordStatus
from comic_agent.schemas.narrative import EntityProposalV1
from comic_agent.schemas.review import (
    ApprovedProposalBundleV1,
    ApprovedProposalItemV1,
    NarrativeAnalysisReviewRouteV1,
    ReviewableProposalEnvelopeV1,
    ReviewableProposalMode,
    ReviewGate2RoutingDecision,
    ReviewGate2RunStatus,
)
from comic_agent.schemas.storybible import (
    ProfileUpdateProposalV1,
    StoryBibleCanonicalKind,
    StoryBibleContextV1,
    StoryBibleCuratorProposalV1,
    StoryBibleIdentityBindingV1,
)
from comic_agent.schemas.timeline import (
    ApprovedTimelineBundleV1,
    NarrativeTimelineReviewRouteV1,
    ReviewGate3Decision,
)

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


def _candidate_payload(*, status: str = "CANONICAL") -> dict[str, Any]:
    evidence = {"chunk_id": "chunk-1"}
    profile = {
        "profile_id": "profile-1",
        "project_id": "project-1",
        "entity_kind": "PERSON",
        "canonical_name": "Lin Xia",
        "evidence_refs": [evidence],
    }
    update = {
        "update_id": "update-1",
        "project_id": "project-1",
        "profile": profile,
        "evidence_refs": [evidence],
    }
    return {
        "proposal_id": "curator-1",
        "project_id": "project-1",
        "status": status,
        "commit_plan": {
            "commit_plan_id": "plan-1",
            "project_id": "project-1",
            "source_proposal_id": "curator-1",
            "content_hash": "hash-1",
            "updates": [update],
            "evidence_refs": [evidence],
        },
        "evidence_refs": [evidence],
        "confidence": 0.9,
    }


class RecordingProvider:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.request: dict[str, object] | None = None
        self.output_model: type[BaseModel] | None = None

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        self.request = request
        self.output_model = output_model
        return output_model.model_validate(self.response)


def _approved_context(
    *, entity_proposals: list[EntityProposalV1] | None = None
) -> StoryBibleContextV1:
    entities = entity_proposals or []
    approved_items = [
        ApprovedProposalItemV1(
            source=ReviewableProposalEnvelopeV1(
                mode=ReviewableProposalMode.ENTITY_EXTRACTION,
                proposal_schema="EntityProposalV1",
                proposal=entity,
                agent_run_ids=[f"agent-{entity.proposal_id}"],
                aggregated_evidence_refs=entity.evidence_refs,
            ),
            review_decision_id=f"decision-{entity.proposal_id}",
        )
        for entity in entities
    ]
    gate2_bundle = ApprovedProposalBundleV1(
        bundle_id="bundle-gate2",
        project_id="project-1",
        document_id="document-1",
        analysis_run_id="analysis-1",
        review_run_id="review-1",
        policy_id="policy-1",
        approved_proposals=approved_items,
        review_decision_ids=[item.review_decision_id for item in approved_items],
    )
    gate2_route = NarrativeAnalysisReviewRouteV1(
        analysis_run_id="analysis-1",
        review_run_id="review-1",
        decision=ReviewGate2RoutingDecision.APPROVED,
        review_status=ReviewGate2RunStatus.COMPLETED,
        total_count=len(approved_items),
        approved_count=len(approved_items),
        rejected_count=0,
        held_count=0,
        approved_proposal_bundle=gate2_bundle,
    )
    gate3_bundle = ApprovedTimelineBundleV1(
        bundle_id="bundle-gate3",
        project_id="project-1",
        source_approved_proposal_bundle_id=gate2_bundle.bundle_id,
        source_gate2_review_id=gate2_bundle.review_run_id,
        source_gate2_route_id=gate2_route.analysis_run_id,
        timeline_run_id="timeline-1",
        gate3_review_id="gate3-review-1",
        gate3_route_id="gate3-route-1",
        evidence_refs=[{"chunk_id": "chunk-1"}],
    )
    gate3_route = NarrativeTimelineReviewRouteV1(
        route_id="gate3-route-1",
        review_id="gate3-review-1",
        timeline_run_id="timeline-1",
        route=ReviewGate3Decision.APPROVED,
        approved_timeline_bundle_id=gate3_bundle.bundle_id,
        approved_timeline_bundle=gate3_bundle,
    )
    return StoryBibleContextV1(
        project_id="project-1",
        gate2_route=gate2_route,
        gate3_route=gate3_route,
        entity_proposals=entities,
        identity_bindings=[
            StoryBibleIdentityBindingV1(
                source_schema="EntityProposalV1",
                source_proposal_id=entity.proposal_id,
                canonical_kind=StoryBibleCanonicalKind.PROFILE,
                canonical_id=f"project-1:profile:{entity.proposal_id}",
                project_id="project-1",
            )
            for entity in entities
        ],
        source_chunk_ids=["chunk-1"],
    )


def test_curator_returns_only_a_schema_valid_candidate() -> None:
    provider = RecordingProvider(_candidate_payload())
    curator = StoryBibleCurator(provider)

    proposal = curator.run(_approved_context())

    assert isinstance(proposal, StoryBibleCuratorProposalV1)
    assert proposal.commit_plan.project_id == "project-1"
    assert proposal.status == RecordStatus.CANDIDATE
    assert provider.output_model is StoryBibleCuratorProposalV1


def test_curator_sends_only_bounded_context_to_provider() -> None:
    provider = RecordingProvider(_candidate_payload(status="CANDIDATE"))
    curator = StoryBibleCurator(provider)
    context = _approved_context()

    curator.run(context)

    assert provider.request is not None
    messages = provider.request["messages"]
    assert isinstance(messages, list)
    user_message = messages[1]
    assert isinstance(user_message, dict)
    assert json.loads(str(user_message["content"])) == context.model_dump(
        mode="json", exclude={"gate2_route", "gate3_route"}
    )
    assert "database" not in str(provider.request).casefold()


def test_curator_spec_forbids_canonical_writes() -> None:
    assert StoryBibleCurator.spec.can_write_canonical_data is False
    assert StoryBibleCurator.spec.reads == ["StoryBibleContextV1"]
    assert StoryBibleCurator.spec.output_schema == "StoryBibleCuratorProposalV1"
    assert StoryBibleCurator.spec.max_context_chunks == 3


def test_storybible_context_requires_both_existing_gate_routes() -> None:
    context = _approved_context()
    rejected_gate3 = context.gate3_route.model_copy(
        update={
            "route": ReviewGate3Decision.REJECTED,
            "approved_timeline_bundle": None,
            "approved_timeline_bundle_id": None,
        }
    )
    with pytest.raises(ValueError, match="APPROVED Gate 3"):
        StoryBibleContextV1(
            project_id=context.project_id,
            gate2_route=context.gate2_route,
            gate3_route=rejected_gate3,
            entity_proposals=[],
            source_chunk_ids=["chunk-1"],
        )


def test_curator_maps_reviewed_proposal_ids_to_durable_storybible_ids() -> None:
    entity = EntityProposalV1(
        proposal_id="entity-1",
        entity_type="CHARACTER",
        canonical_name="Lin Xia",
        evidence_refs=[{"chunk_id": "chunk-1"}],
        confidence=0.95,
    )
    response = _candidate_payload()
    response["commit_plan"]["updates"][0]["profile"]["profile_id"] = "entity-1"
    provider = RecordingProvider(response)

    proposal = StoryBibleCurator(provider).run(_approved_context(entity_proposals=[entity]))

    update = proposal.commit_plan.updates[0]
    assert isinstance(update, ProfileUpdateProposalV1)
    assert update.source_proposal_id == "entity-1"
    assert update.profile.profile_id.startswith("project-1:profile:")
    assert proposal.identity_bindings[0].canonical_id == update.profile.profile_id
