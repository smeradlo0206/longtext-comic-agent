"""Rules-first Timeline Agent with bounded pairwise LLM inference."""

import json
from collections.abc import Iterable
from itertools import combinations

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.base import EvidenceRefV1, RecordStatus
from comic_agent.schemas.narrative import (
    ClaimProposalV1,
    EventProposalV1,
    TemporalRelation,
    TemporalRelationProposalV1,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import (
    DuplicateCandidateType,
    DuplicateCandidateV1,
    TemporalRelationLLMResultV1,
    TimelineAnalysisInputV1,
    TimelineAnalysisMode,
    TimelineAnalysisProposalV1,
    TimelineConflictCategory,
    TimelineConflictV1,
)
from comic_agent.services.id_service import stable_id


class EventPairSelector:
    """Select a conservative, replaceable set of pairs for LLM evaluation."""

    def select(
        self,
        events: list[EventProposalV1],
        chunks_by_id: dict[str, SourceChunkV1],
    ) -> list[tuple[EventProposalV1, EventProposalV1]]:
        """Keep only explicitly requested or locally related event pairs."""

        if len(events) == 2:
            return [(events[0], events[1])]

        selected: list[tuple[EventProposalV1, EventProposalV1]] = []
        for first, second in combinations(events, 2):
            if self._related(first, second, chunks_by_id):
                selected.append((first, second))
        return selected

    @staticmethod
    def _related(
        first: EventProposalV1,
        second: EventProposalV1,
        chunks_by_id: dict[str, SourceChunkV1],
    ) -> bool:
        if set(first.participant_ids) & set(second.participant_ids):
            return True
        if first.location_id is not None and first.location_id == second.location_id:
            return True
        first_chapters = {
            chunks_by_id[reference.chunk_id].chapter_id
            for reference in first.evidence_refs
            if reference.chunk_id in chunks_by_id
        }
        second_chapters = {
            chunks_by_id[reference.chunk_id].chapter_id
            for reference in second.evidence_refs
            if reference.chunk_id in chunks_by_id
        }
        return bool(first_chapters & second_chapters)


class TimelineAgent:
    """Keep deterministic checks separate from pairwise LLM time judgments."""

    PROMPT_VERSION = "timeline-pair-v2.0"
    spec = AgentSpec(
        agent_id="timeline-agent",
        version="2.0",
        reads=["EventProposalV1", "ClaimProposalV1", "StateChangeProposalV1"],
        output_schema="TimelineAnalysisProposalV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=2,
        confidence_threshold=0.0,
    )

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        provider_model: str = "unconfigured",
        llm_enabled: bool = True,
        pair_selector: EventPairSelector | None = None,
    ) -> None:
        self._provider = provider
        self._provider_model = provider_model
        self._llm_enabled = llm_enabled
        self._pair_selector = pair_selector or EventPairSelector()

    @property
    def cache_identity(self) -> dict[str, str]:
        """Return agent-controlled inputs relevant to a cached LLM result."""

        return {
            "agent_id": self.spec.agent_id,
            "agent_version": self.spec.version,
            "prompt_version": self.PROMPT_VERSION,
            "provider_model": self._provider_model,
            "llm_enabled": str(self._llm_enabled),
        }

    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: Iterable[SourceChunkV1] = (),
    ) -> TimelineAnalysisProposalV1:
        """Analyze supplied candidates without database access or canonical writes."""

        chunks_by_id = {chunk.chunk_id: chunk for chunk in source_chunks}
        temporal_relations = (
            self._unknown_relations(input_context.event_proposals)
            if (
                input_context.mode == TimelineAnalysisMode.RULES_ONLY
                or not self._llm_enabled
            )
            else self._llm_relations(input_context.event_proposals, chunks_by_id)
        )
        return TimelineAnalysisProposalV1(
            proposal_id=stable_id(
                "timeline", input_context.project_id, self._input_key(input_context)
            ),
            project_id=input_context.project_id,
            status=RecordStatus.CANDIDATE,
            temporal_relations=temporal_relations,
            conflicts=self._conflicts(input_context),
            duplicate_candidates=self._duplicates(input_context),
            evidence_refs=self._all_evidence(input_context),
            confidence=1.0,
        )

    def _llm_relations(
        self,
        events: list[EventProposalV1],
        chunks_by_id: dict[str, SourceChunkV1],
    ) -> list[TemporalRelationProposalV1]:
        if self._provider is None:
            raise RuntimeError("TimelineAgent LLM mode requires an LLMProvider")
        return [
            self._infer_pair(first, second, chunks_by_id)
            for first, second in self._pair_selector.select(events, chunks_by_id)
        ]

    def _infer_pair(
        self,
        first: EventProposalV1,
        second: EventProposalV1,
        chunks_by_id: dict[str, SourceChunkV1],
    ) -> TemporalRelationProposalV1:
        assert self._provider is not None
        evidence_by_id = self._evidence_by_id(first, second)
        response = self._provider.structured_generate(
            self._request_for_pair(first, second, evidence_by_id),
            TemporalRelationLLMResultV1,
        )
        selected_evidence = []
        for evidence_id in response.supporting_evidence_ids:
            evidence_ref = evidence_by_id.get(evidence_id)
            if evidence_ref is None:
                raise ValueError(f"LLM selected unknown evidence id: {evidence_id}")
            if evidence_ref not in selected_evidence:
                selected_evidence.append(evidence_ref)
        return TemporalRelationProposalV1(
            proposal_id=stable_id(
                "temporal-v2", first.proposal_id, second.proposal_id, response.relation
            ),
            source_event_id=first.proposal_id,
            target_event_id=second.proposal_id,
            relation=response.relation,
            evidence_refs=selected_evidence,
            confidence=response.confidence,
            reasoning_summary=response.reasoning_summary,
        )

    @staticmethod
    def _evidence_by_id(
        first: EventProposalV1,
        second: EventProposalV1,
    ) -> dict[str, EvidenceRefV1]:
        """Give the provider stable choices while retaining original evidence locally."""

        evidence_by_id: dict[str, EvidenceRefV1] = {}
        for event_label, event in (("event_a", first), ("event_b", second)):
            for index, evidence_ref in enumerate(event.evidence_refs):
                evidence_by_id[f"{event_label}_evidence_{index}"] = evidence_ref
        return evidence_by_id

    def _request_for_pair(
        self,
        first: EventProposalV1,
        second: EventProposalV1,
        evidence_by_id: dict[str, EvidenceRefV1],
    ) -> dict[str, object]:
        evidence_options = [
            {
                "evidence_id": evidence_id,
                "chunk_id": evidence_ref.chunk_id,
                "quote_text": evidence_ref.quote_text,
            }
            for evidence_id, evidence_ref in evidence_by_id.items()
        ]
        return {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are TimelineAgent V2. Judge ONLY Event A relative to Event B from "
                        "the supplied records and existing evidence options. You may only select "
                        "supporting_evidence_ids from those options; never create chunk ids, "
                        "offsets, quotes, or evidence ids. Narrative, chapter, chunk, and input "
                        "order are not story-time evidence. Never invent facts, dates, or causal "
                        "order. Claims are "
                        "not established events. If evidence is insufficient, ambiguous, "
                        "or an unanchored flashback, return UNKNOWN. Allowed relation values are "
                        "BEFORE, AFTER, SIMULTANEOUS, OVERLAPS, UNKNOWN. A non-UNKNOWN relation "
                        "must select one or more supporting_evidence_ids. UNKNOWN may select none. "
                        "reasoning_summary must be a short evidence-grounded "
                        "summary, "
                        "not hidden reasoning. Return only one JSON object matching: "
                        + json.dumps(
                            TemporalRelationLLMResultV1.model_json_schema(),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "event_a": {
                                "event_id": first.proposal_id,
                                "summary": first.summary,
                                "evidence": [
                                    option
                                    for option in evidence_options
                                    if str(option["evidence_id"]).startswith("event_a_")
                                ],
                            },
                            "event_b": {
                                "event_id": second.proposal_id,
                                "summary": second.summary,
                                "evidence": [
                                    option
                                    for option in evidence_options
                                    if str(option["evidence_id"]).startswith("event_b_")
                                ],
                            },
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ]
        }

    @staticmethod
    def _all_evidence(input_context: TimelineAnalysisInputV1) -> list[EvidenceRefV1]:
        evidence_refs: list[EvidenceRefV1] = []
        for proposal in input_context.event_proposals:
            for evidence_ref in proposal.evidence_refs:
                if evidence_ref not in evidence_refs:
                    evidence_refs.append(evidence_ref)
        for claim_proposal in input_context.claim_proposals:
            for evidence_ref in claim_proposal.evidence_refs:
                if evidence_ref not in evidence_refs:
                    evidence_refs.append(evidence_ref)
        for state_change_proposal in input_context.state_change_proposals:
            for evidence_ref in state_change_proposal.evidence_refs:
                if evidence_ref not in evidence_refs:
                    evidence_refs.append(evidence_ref)
        return evidence_refs

    def _input_key(self, input_context: TimelineAnalysisInputV1) -> tuple[object, ...]:
        return (
            input_context.mode,
            self.PROMPT_VERSION,
            self.spec.version,
            self._provider_model,
            self._llm_enabled,
            tuple(proposal.proposal_id for proposal in input_context.event_proposals),
            tuple(proposal.claim_id for proposal in input_context.claim_proposals),
            tuple(proposal.proposal_id for proposal in input_context.state_change_proposals),
        )

    @staticmethod
    def _unknown_relations(events: list[EventProposalV1]) -> list[TemporalRelationProposalV1]:
        return [
            TemporalRelationProposalV1(
                proposal_id=stable_id(
                    "temporal", source.proposal_id, target.proposal_id, "UNKNOWN"
                ),
                source_event_id=source.proposal_id,
                target_event_id=target.proposal_id,
                relation=TemporalRelation.UNKNOWN,
                confidence=0.0,
            )
            for source, target in combinations(events, 2)
        ]

    def _conflicts(self, input_context: TimelineAnalysisInputV1) -> list[TimelineConflictV1]:
        conflicts = self._missing_event_conflicts(input_context)
        conflicts.extend(self._contradictory_claim_conflicts(input_context))
        return conflicts

    @staticmethod
    def _missing_event_conflicts(
        input_context: TimelineAnalysisInputV1,
    ) -> list[TimelineConflictV1]:
        known_event_ids = {proposal.proposal_id for proposal in input_context.event_proposals}
        return [
            TimelineConflictV1(
                conflict_id=stable_id("timeline-conflict", change.proposal_id),
                project_id=input_context.project_id,
                category=TimelineConflictCategory.MISSING_EVENT_REFERENCE,
                summary=(
                    f"State-change proposal {change.proposal_id} references missing event "
                    f"{change.event_id}."
                ),
                affected_proposal_ids=[change.proposal_id],
                evidence_refs=change.evidence_refs,
            )
            for change in input_context.state_change_proposals
            if change.event_id not in known_event_ids
        ]

    @staticmethod
    def _contradictory_claim_conflicts(
        input_context: TimelineAnalysisInputV1,
    ) -> list[TimelineConflictV1]:
        conflicts = []
        for first, second in combinations(input_context.claim_proposals, 2):
            if (
                first.subject_id == second.subject_id
                and first.predicate == second.predicate
                and first.object_value != second.object_value
                and first.reality_layer == second.reality_layer
            ):
                conflicts.append(
                    TimelineConflictV1(
                        conflict_id=stable_id("claim-conflict", first.claim_id, second.claim_id),
                        project_id=input_context.project_id,
                        category=TimelineConflictCategory.CONTRADICTORY_CLAIMS,
                        summary=(
                            f"Claims {first.claim_id} and {second.claim_id} assign "
                            "different values "
                            f"to {first.subject_id}.{first.predicate}."
                        ),
                        affected_proposal_ids=[first.claim_id, second.claim_id],
                        evidence_refs=[*first.evidence_refs, *second.evidence_refs],
                    )
                )
        return conflicts

    @staticmethod
    def _duplicates(input_context: TimelineAnalysisInputV1) -> list[DuplicateCandidateV1]:
        duplicates: list[DuplicateCandidateV1] = []
        for first, second in combinations(input_context.event_proposals, 2):
            if TimelineAgent._event_key(first) == TimelineAgent._event_key(second):
                duplicates.append(
                    DuplicateCandidateV1(
                        candidate_id=stable_id(
                            "duplicate-event", first.proposal_id, second.proposal_id
                        ),
                        project_id=input_context.project_id,
                        candidate_type=DuplicateCandidateType.EVENT,
                        proposal_ids=[first.proposal_id, second.proposal_id],
                        reason=(
                            "Exact event type, summary, participants, location, and "
                            "reality layer match."
                        ),
                        evidence_refs=[*first.evidence_refs, *second.evidence_refs],
                        confidence=1.0,
                    )
                )
        for first_claim, second_claim in combinations(input_context.claim_proposals, 2):
            if TimelineAgent._claim_key(first_claim) == TimelineAgent._claim_key(second_claim):
                duplicates.append(
                    DuplicateCandidateV1(
                        candidate_id=stable_id(
                            "duplicate-claim", first_claim.claim_id, second_claim.claim_id
                        ),
                        project_id=input_context.project_id,
                        candidate_type=DuplicateCandidateType.CLAIM,
                        proposal_ids=[first_claim.claim_id, second_claim.claim_id],
                        reason="Exact subject, predicate, value, source, and reality layer match.",
                        evidence_refs=[*first_claim.evidence_refs, *second_claim.evidence_refs],
                        confidence=1.0,
                    )
                )
        return duplicates

    @staticmethod
    def _event_key(event: EventProposalV1) -> tuple[object, ...]:
        return (
            event.event_type,
            event.summary.casefold().strip(),
            tuple(sorted(event.participant_ids)),
            event.location_id,
            event.reality_layer,
        )

    @staticmethod
    def _claim_key(claim: ClaimProposalV1) -> tuple[object, ...]:
        return (
            claim.subject_id,
            claim.predicate,
            claim.object_value,
            claim.asserted_by_entity_id,
            claim.reality_layer,
        )
