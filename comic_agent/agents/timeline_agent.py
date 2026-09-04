"""Rules-first Timeline Agent with bounded pairwise LLM inference."""

import json
import re
from collections.abc import Iterable
from itertools import combinations

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.providers.openai_compatible import ProviderResponseError
from comic_agent.schemas.base import EvidenceRefV1, RecordStatus
from comic_agent.schemas.narrative import (
    ClaimProposalV1,
    EventProposalV1,
    TemporalRelation,
    TemporalRelationProposalV1,
)
from comic_agent.schemas.reliability import ProviderExecutionMetadataV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import (
    DuplicateCandidateType,
    DuplicateCandidateV1,
    TimelineAnalysisInputV1,
    TimelineAnalysisMode,
    TimelineAnalysisProposalV1,
    TimelineConflictCategory,
    TimelineConflictV1,
    TimelinePairInferenceV1,
)
from comic_agent.services.id_service import stable_id


class EventPairSelector:
    """Select a conservative, replaceable set of pairs for LLM evaluation."""

    def __init__(self, *, max_pairs: int = 64) -> None:
        if max_pairs < 1:
            raise ValueError("max_pairs must be at least 1")
        self._max_pairs = max_pairs

    def select(
        self,
        events: list[EventProposalV1],
        chunks_by_id: dict[str, SourceChunkV1],
    ) -> list[tuple[EventProposalV1, EventProposalV1]]:
        """Keep a bounded graph of adjacent and nearest shared-entity pairs."""

        del chunks_by_id  # Kept in the replaceable selector interface for richer policies.
        if len(events) < 2:
            return []
        all_pairs = list(combinations(events, 2))
        if len(all_pairs) <= self._max_pairs:
            return all_pairs

        adjacent = list(zip(events, events[1:], strict=False))
        if len(adjacent) >= self._max_pairs:
            return self._sample_across_story(adjacent, self._max_pairs)

        selected = list(adjacent)
        selected_ids = {(first.proposal_id, second.proposal_id) for first, second in selected}
        last_by_participant: dict[str, EventProposalV1] = {}
        last_by_location: dict[str, EventProposalV1] = {}
        related: list[tuple[EventProposalV1, EventProposalV1]] = []
        for event in events:
            previous_events = [
                last_by_participant[participant_id]
                for participant_id in event.participant_ids
                if participant_id in last_by_participant
            ]
            if event.location_id is not None and event.location_id in last_by_location:
                previous_events.append(last_by_location[event.location_id])
            for previous in previous_events:
                key = (previous.proposal_id, event.proposal_id)
                if key not in selected_ids:
                    selected_ids.add(key)
                    related.append((previous, event))
            for participant_id in event.participant_ids:
                last_by_participant[participant_id] = event
            if event.location_id is not None:
                last_by_location[event.location_id] = event

        remaining = self._max_pairs - len(selected)
        selected.extend(self._sample_across_story(related, remaining))
        return selected

    @staticmethod
    def _sample_across_story(
        pairs: list[tuple[EventProposalV1, EventProposalV1]],
        limit: int,
    ) -> list[tuple[EventProposalV1, EventProposalV1]]:
        if limit <= 0 or not pairs:
            return []
        if len(pairs) <= limit:
            return pairs
        if limit == 1:
            return [pairs[0]]
        indexes = [round(index * (len(pairs) - 1) / (limit - 1)) for index in range(limit)]
        return [pairs[index] for index in indexes]


class TimelineAgent:
    """Keep deterministic checks separate from pairwise LLM time judgments."""

    PROMPT_VERSION = "timeline-pair-v2.1"
    spec = AgentSpec(
        agent_id="timeline-agent",
        version="2.1",
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
        self._provider_request_count = 0
        self._execution_history: list[ProviderExecutionMetadataV1] = []

    @property
    def provider_request_count(self) -> int:
        """Return the exact number of Provider requests in the latest run."""

        return self._provider_request_count

    def execution_history(self) -> list[ProviderExecutionMetadataV1]:
        """Return allowlisted usage metadata for calls made by the latest run."""

        return list(self._execution_history)

    def provider_execution_history(self) -> list[ProviderExecutionMetadataV1]:
        """Return all Provider calls, including capability probes, for accounting."""

        getter = getattr(self._provider, "execution_history", None)
        values = getter() if callable(getter) else []
        return [value for value in values if isinstance(value, ProviderExecutionMetadataV1)]

    @property
    def cache_identity(self) -> dict[str, str]:
        """Return agent-controlled inputs relevant to a cached LLM result."""

        return {
            "agent_id": self.spec.agent_id,
            "agent_version": self.spec.version,
            "prompt_version": self.PROMPT_VERSION,
            "provider_model": self._provider_model,
        }

    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: Iterable[SourceChunkV1] = (),
    ) -> TimelineAnalysisProposalV1:
        """Analyze supplied candidates without database access or canonical writes."""

        self._provider_request_count = 0
        self._execution_history = []
        chunks_by_id = {chunk.chunk_id: chunk for chunk in source_chunks}
        temporal_relations = (
            self._unknown_relations(input_context.event_proposals)
            if input_context.mode == TimelineAnalysisMode.RULES_ONLY or not self._llm_enabled
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
        evidence_refs = self._pair_evidence(first, second, chunks_by_id)
        request = self._request_for_pair(first, second, chunks_by_id, evidence_refs)
        try:
            response = self._generate_pair(request)
            self._validate_evidence_indexes(response, evidence_refs)
        except ProviderResponseError as exc:
            if not self._is_schema_failure(exc):
                raise
            repair_request = self._request_for_pair(
                first,
                second,
                chunks_by_id,
                evidence_refs,
                repair_diagnostics=self._safe_repair_diagnostics(exc),
            )
            response = self._generate_pair(repair_request)
            self._validate_evidence_indexes(response, evidence_refs)
        relation = TemporalRelation(response.relation)
        selected_evidence = [evidence_refs[index] for index in response.evidence_indexes]
        return TemporalRelationProposalV1(
            proposal_id=stable_id(
                "temporal-v2", first.proposal_id, second.proposal_id, relation
            ),
            source_event_id=first.proposal_id,
            target_event_id=second.proposal_id,
            relation=relation,
            evidence_refs=selected_evidence,
            confidence=response.confidence,
            reasoning_summary=response.reasoning_summary,
        )

    def _generate_pair(self, request: dict[str, object]) -> TimelinePairInferenceV1:
        assert self._provider is not None
        self._provider_request_count += 1
        try:
            return self._provider.structured_generate(request, TimelinePairInferenceV1)
        finally:
            getter = getattr(self._provider, "last_execution_metadata", None)
            metadata = getter() if callable(getter) else None
            if isinstance(metadata, ProviderExecutionMetadataV1):
                self._execution_history.append(metadata)

    @staticmethod
    def _validate_evidence_indexes(
        response: TimelinePairInferenceV1,
        evidence_refs: list[EvidenceRefV1],
    ) -> None:
        if any(index >= len(evidence_refs) for index in response.evidence_indexes):
            raise ProviderResponseError(
                "Timeline evidence selection failed validation",
                diagnostics={
                    "schema_error_field_paths": ["evidence_indexes"],
                    "schema_error_rule_codes": ["TIMELINE_EVIDENCE_INDEX_OUT_OF_RANGE"],
                    "expected_output_schema": "TimelinePairInferenceV1",
                },
            )

    @staticmethod
    def _safe_repair_diagnostics(exc: ProviderResponseError) -> dict[str, list[str]]:
        diagnostics: dict[str, list[str]] = {}
        patterns = {
            "schema_error_field_paths": r"[A-Za-z0-9_.\[\]-]{1,256}",
            "schema_error_rule_codes": r"[A-Z][A-Z0-9_]{0,255}",
        }
        for key, pattern in patterns.items():
            value = exc.diagnostics.get(key)
            if isinstance(value, list):
                diagnostics[key] = [
                    item
                    for item in value
                    if isinstance(item, str) and re.fullmatch(pattern, item)
                ][:32]
        return diagnostics

    @staticmethod
    def _is_schema_failure(exc: ProviderResponseError) -> bool:
        return any(
            key in exc.diagnostics
            for key in (
                "schema_error_field_paths",
                "schema_error_rule_codes",
                "schema_error_kind",
            )
        )

    @staticmethod
    def _pair_evidence(
        first: EventProposalV1,
        second: EventProposalV1,
        chunks_by_id: dict[str, SourceChunkV1],
    ) -> list[EvidenceRefV1]:
        evidence_refs: list[EvidenceRefV1] = []
        for event in (first, second):
            for evidence_ref in event.evidence_refs:
                if (
                    evidence_ref.chunk_id in chunks_by_id
                    and evidence_ref not in evidence_refs
                ):
                    evidence_refs.append(evidence_ref)
        return evidence_refs

    def _request_for_pair(
        self,
        first: EventProposalV1,
        second: EventProposalV1,
        chunks_by_id: dict[str, SourceChunkV1],
        evidence_refs: list[EvidenceRefV1],
        *,
        repair_diagnostics: dict[str, list[str]] | None = None,
    ) -> dict[str, object]:
        evidence_chunks: list[dict[str, str]] = []
        seen_chunk_ids: set[str] = set()
        for event in (first, second):
            for evidence_ref in event.evidence_refs:
                chunk_id = evidence_ref.chunk_id
                if chunk_id not in seen_chunk_ids and chunk_id in chunks_by_id:
                    seen_chunk_ids.add(chunk_id)
                    evidence_chunks.append(
                        {"chunk_id": chunk_id, "text": chunks_by_id[chunk_id].text}
                    )
        return {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are TimelineAgent V2.1. Judge ONLY Event A relative to Event B "
                        "from the supplied records and exact evidence allowlist. Narrative "
                        "or chapter "
                        "order is not story-time evidence. Never invent facts, dates, or "
                        "causal order. Claims are not established events. If evidence is "
                        "insufficient, ambiguous, "
                        "or an unanchored flashback, return UNKNOWN. Allowed relation values are "
                        "BEFORE, AFTER, SIMULTANEOUS, OVERLAPS, UNKNOWN. A non-UNKNOWN relation "
                        "must select one or more integer indexes from evidence_allowlist. "
                        "Do not return proposal ids, event ids, quotes, offsets, or source text. "
                        "reasoning_summary must be a short evidence-grounded "
                        "summary, "
                        "not hidden reasoning. Return only one JSON object matching: "
                        + json.dumps(
                            TimelinePairInferenceV1.model_json_schema(),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "event_a": first.model_dump(mode="json", exclude={"evidence_refs"}),
                            "event_b": second.model_dump(mode="json", exclude={"evidence_refs"}),
                            "evidence_allowlist": [
                                {"index": index, "evidence_ref": item.model_dump(mode="json")}
                                for index, item in enumerate(evidence_refs)
                            ],
                            "evidence_chunks": evidence_chunks,
                            "repair_diagnostics": repair_diagnostics,
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

    @staticmethod
    def _input_key(input_context: TimelineAnalysisInputV1) -> tuple[object, ...]:
        return (
            input_context.mode,
            tuple(proposal.proposal_id for proposal in input_context.event_proposals),
            tuple(
                proposal.proposal_id
                for proposal in input_context.claim_proposals
            ),
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
                first.subject_id is not None
                and first.predicate is not None
                and first.subject_id == second.subject_id
                and first.predicate == second.predicate
                and first.object_value != second.object_value
                and first.reality_layer == second.reality_layer
            ):
                first_id = first.proposal_id
                second_id = second.proposal_id
                conflicts.append(
                    TimelineConflictV1(
                        conflict_id=stable_id("claim-conflict", first_id, second_id),
                        project_id=input_context.project_id,
                        category=TimelineConflictCategory.CONTRADICTORY_CLAIMS,
                        summary=(
                            f"Claims {first_id} and {second_id} assign "
                            "different values "
                            f"to {first.subject_id}.{first.predicate}."
                        ),
                        affected_proposal_ids=[first_id, second_id],
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
                first_id = first_claim.proposal_id
                second_id = second_claim.proposal_id
                duplicates.append(
                    DuplicateCandidateV1(
                        candidate_id=stable_id(
                            "duplicate-claim", first_id, second_id
                        ),
                        project_id=input_context.project_id,
                        candidate_type=DuplicateCandidateType.CLAIM,
                        proposal_ids=[first_id, second_id],
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
        if claim.subject_id is None or claim.predicate is None:
            return (
                "modern",
                claim.claim_type,
                claim.claim_text.casefold().strip(),
                claim.source_type,
                claim.source_id,
                claim.target_event_id,
                claim.reality_layer,
            )
        return (
            "legacy",
            claim.subject_id,
            claim.predicate,
            claim.object_value,
            claim.asserted_by_entity_id,
            claim.reality_layer,
        )
