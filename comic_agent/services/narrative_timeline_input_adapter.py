"""Build bounded Timeline input exclusively from Gate 2 approved Narrative output."""

from collections.abc import Sequence

from comic_agent.schemas import (
    ApprovedProposalBundleV1,
    CampusContentProfileProposalV1,
    ClaimProposalV1,
    ClaimType,
    EventProposalV1,
    NarrativeAnalysisReviewRouteV1,
    ReviewGate2RoutingDecision,
    SourceChunkV1,
    StateChangeProposalV1,
    TimelineAnalysisInputV1,
    TimelineAnalysisMode,
)
from comic_agent.schemas.base import EvidenceRefV1


class NarrativeTimelineInputAdapter:
    """Pure, deterministic adapter; it never invokes Timeline or writes canonical data."""

    def build(
        self,
        *,
        route: NarrativeAnalysisReviewRouteV1,
        profile_id: str,
        source_chunks: Sequence[SourceChunkV1],
    ) -> TimelineAnalysisInputV1:
        """Build v1.2 Timeline input only from the route's approved Proposal bundle."""

        if not isinstance(route, NarrativeAnalysisReviewRouteV1):
            raise ValueError("NarrativeTimelineInputAdapter accepts only a Gate 2 route")
        if route.decision != ReviewGate2RoutingDecision.APPROVED:
            raise ValueError("NarrativeTimelineInputAdapter requires a Gate 2 APPROVED route")
        bundle = route.approved_proposal_bundle
        if bundle is None:
            raise ValueError("NarrativeTimelineInputAdapter requires an approved proposal bundle")
        return self._from_bundle(bundle=bundle, profile_id=profile_id, source_chunks=source_chunks)

    def build_from_approved_bundle(
        self,
        *,
        route: NarrativeAnalysisReviewRouteV1,
        source_chunks: Sequence[SourceChunkV1],
        mode: TimelineAnalysisMode = TimelineAnalysisMode.RULES_ONLY,
    ) -> TimelineAnalysisInputV1:
        """Build normal Timeline input from Gate 2's typed approved bundle only."""

        if not isinstance(route, NarrativeAnalysisReviewRouteV1):
            raise ValueError("NarrativeTimelineInputAdapter accepts only a Gate 2 route")
        if route.decision != ReviewGate2RoutingDecision.APPROVED:
            raise ValueError("NarrativeTimelineInputAdapter requires a Gate 2 APPROVED route")
        bundle = route.approved_proposal_bundle
        if bundle is None:
            raise ValueError("NarrativeTimelineInputAdapter requires an approved proposal bundle")
        chunks = {chunk.chunk_id: chunk for chunk in source_chunks}
        if len(chunks) != len(source_chunks):
            raise ValueError("NarrativeTimelineInputAdapter source chunk ids must be unique")
        events: list[EventProposalV1] = [
            item.source.proposal
            for item in bundle.approved_proposals
            if isinstance(item.source.proposal, EventProposalV1)
        ]
        claims: list[ClaimProposalV1] = [
            item.source.proposal
            for item in bundle.approved_proposals
            if isinstance(item.source.proposal, ClaimProposalV1)
            and item.source.proposal.claim_type == ClaimType.FACTUAL_ASSERTION
        ]
        changes: list[StateChangeProposalV1] = [
            item.source.proposal
            for item in bundle.approved_proposals
            if isinstance(item.source.proposal, StateChangeProposalV1)
        ]
        for event in events:
            self._validate_evidence_scope(event.evidence_refs, chunks)
        for claim in claims:
            self._validate_evidence_scope(claim.evidence_refs, chunks)
        for change in changes:
            self._validate_evidence_scope(change.evidence_refs, chunks)
        return TimelineAnalysisInputV1(
            schema_version="1.3",
            project_id=bundle.project_id,
            source_approved_bundle_id=bundle.bundle_id,
            source_review_run_id=bundle.review_run_id,
            mode=mode,
            event_proposals=events,
            claim_proposals=claims,
            state_change_proposals=changes,
        )

    @staticmethod
    def _validate_evidence_scope(
        evidence_refs: Sequence[object],
        chunks: dict[str, SourceChunkV1],
    ) -> None:
        for evidence in evidence_refs:
            if not isinstance(evidence, EvidenceRefV1):
                raise ValueError("Approved proposal evidence must use EvidenceRefV1")
            chunk = chunks.get(evidence.chunk_id)
            if (
                chunk is None
                or evidence.quote_text is None
                or evidence.quote_text not in chunk.text
            ):
                raise ValueError(
                    "Approved proposal evidence must be present in supplied source provenance"
                )

    @staticmethod
    def _from_bundle(
        *,
        bundle: ApprovedProposalBundleV1,
        profile_id: str,
        source_chunks: Sequence[SourceChunkV1],
    ) -> TimelineAnalysisInputV1:
        chunks = {chunk.chunk_id: chunk for chunk in source_chunks}
        if len(chunks) != len(source_chunks):
            raise ValueError("NarrativeTimelineInputAdapter source chunk ids must be unique")
        profiles = [
            item.source.proposal
            for item in bundle.approved_proposals
            if isinstance(item.source.proposal, CampusContentProfileProposalV1)
            and item.source.proposal.proposal_id == profile_id
        ]
        if len(profiles) != 1:
            raise ValueError(
                "Campus content profile must be present exactly once in approved bundle"
            )
        profile = profiles[0]
        if profile.project_id != bundle.project_id:
            raise ValueError("Campus content profile project_id must match approved bundle")
        claims = [
            item.source.proposal
            for item in bundle.approved_proposals
            if isinstance(item.source.proposal, ClaimProposalV1)
            and item.source.proposal.claim_type == ClaimType.FACTUAL_ASSERTION
        ]
        claims_by_id = {
            claim.claim_id: claim
            for claim in claims
            if isinstance(claim.claim_id, str) and claim.claim_id
        }
        if len(claims_by_id) != len(claims):
            raise ValueError("Approved factual Claims require unique nonblank claim_id values")
        required_claims: list[ClaimProposalV1] = []
        for fact_id in profile.must_preserve_fact_ids:
            claim = claims_by_id.get(fact_id)
            if claim is None or not claim.evidence_refs:
                raise ValueError(
                    "Profile must_preserve_fact_ids require approved factual Claims with evidence"
                )
            required_claims.append(claim)
        selected = [*claims]
        events = [
            item.source.proposal
            for item in bundle.approved_proposals
            if isinstance(item.source.proposal, EventProposalV1)
        ]
        changes = [
            item.source.proposal
            for item in bundle.approved_proposals
            if isinstance(item.source.proposal, StateChangeProposalV1)
        ]
        provenance_proposals: list[
            CampusContentProfileProposalV1
            | ClaimProposalV1
            | EventProposalV1
            | StateChangeProposalV1
        ] = [profile, *selected, *events, *changes]
        for proposal in provenance_proposals:
            for evidence in proposal.evidence_refs:
                chunk = chunks.get(evidence.chunk_id)
                if (
                    chunk is None
                    or evidence.quote_text is None
                    or evidence.quote_text not in chunk.text
                ):
                    raise ValueError(
                        "Approved proposal evidence must be present in supplied source provenance"
                    )
        return TimelineAnalysisInputV1(
            schema_version="1.2",
            project_id=bundle.project_id,
            source_approved_bundle_id=bundle.bundle_id,
            source_review_run_id=bundle.review_run_id,
            source_content_profile_id=profile.proposal_id,
            event_proposals=events,
            claim_proposals=selected,
            state_change_proposals=changes,
        )
