"""Deterministic validation for StoryBible proposals and commit plans."""

from collections.abc import Iterable
from typing import Any, Protocol

from comic_agent.schemas.base import EvidenceRefV1, RecordStatus
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ProfileUpdateProposalV1,
    RelationshipUpdateProposalV1,
    StateUpdateProposalV1,
    StoryBibleCuratorProposalV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleUpdateProposalV1,
    WorldRuleV1,
)


class EvidenceLookup(Protocol):
    """Minimal source-repository boundary needed to validate evidence."""

    def get_chunk(self, chunk_id: str) -> SourceChunkV1 | None:
        """Return a source chunk by id."""


type StoryBibleUpdate = (
    ProfileUpdateProposalV1
    | StateUpdateProposalV1
    | RelationshipUpdateProposalV1
    | WorldRuleUpdateProposalV1
)
type StoryBibleResource = (
    StoryEntityProfileV1 | StoryEntityStateV1 | StoryRelationshipV1 | WorldRuleV1
)


class StoryBibleValidator:
    """Validate traceability and plan-wide StoryBible invariants before writes."""

    def __init__(self, evidence_lookup: EvidenceLookup) -> None:
        self._evidence_lookup = evidence_lookup

    def validate_proposal(self, proposal: StoryBibleCuratorProposalV1) -> None:
        """Validate a proposal without promoting any of its candidate data."""

        if proposal.status != RecordStatus.CANDIDATE:
            raise ValueError("StoryBible curator proposal status must be CANDIDATE")
        if proposal.commit_plan.project_id != proposal.project_id:
            raise ValueError("proposal and commit plan must belong to the same project")
        if proposal.commit_plan.source_proposal_id != proposal.proposal_id:
            raise ValueError("commit plan source_proposal_id must match proposal_id")

        self.validate_evidence_refs(
            proposal.evidence_refs,
            project_id=proposal.project_id,
            owner="StoryBible curator proposal",
        )
        update_ids = {update.update_id for update in proposal.commit_plan.updates}
        for conflict in proposal.conflicts:
            if conflict.project_id != proposal.project_id:
                raise ValueError("conflict and proposal must belong to the same project")
            unknown_ids = set(conflict.affected_update_ids) - update_ids
            if unknown_ids:
                raise ValueError("conflict references an update outside its commit plan")
            self.validate_evidence_refs(
                conflict.evidence_refs,
                project_id=proposal.project_id,
                owner=f"conflict {conflict.conflict_id}",
            )
        self.validate_commit_plan(proposal.commit_plan)

    def validate_commit_plan(
        self,
        plan: CommitPlanV1,
        *,
        canonical_profiles: Iterable[StoryEntityProfileV1] | None = None,
        canonical_states: Iterable[StoryEntityStateV1] | None = None,
    ) -> None:
        """Validate a complete plan before CommitService performs its first write."""

        self.validate_evidence_refs(
            plan.evidence_refs,
            project_id=plan.project_id,
            owner=f"commit plan {plan.commit_plan_id}",
        )
        if not plan.updates:
            raise ValueError("commit plan must contain at least one update")

        update_ids: set[str] = set()
        resource_payloads: dict[tuple[str, str], dict[str, Any]] = {}
        identity_owners: dict[str, str] = {}
        state_values: dict[
            tuple[str, str],
            list[
                tuple[
                    str,
                    int | None,
                    int | None,
                    str | None,
                    str | None,
                    Any,
                ]
            ],
        ] = {}

        stored_profiles = list(canonical_profiles or ())
        for profile in stored_profiles:
            if profile.project_id != plan.project_id:
                raise ValueError("canonical validation profile belongs to another project")
            self._validate_profile_identity(profile, identity_owners)

        stored_states = list(canonical_states or ())
        for state in stored_states:
            if state.project_id != plan.project_id:
                raise ValueError("canonical validation state belongs to another project")
            self._validate_state(state, state_values)

        validate_profile_references = canonical_profiles is not None
        owned_profile_ids = {
            profile.profile_id for profile in stored_profiles
        } | {
            update.profile.profile_id
            for update in plan.updates
            if isinstance(update, ProfileUpdateProposalV1)
        }

        for update in plan.updates:
            if update.update_id in update_ids:
                raise ValueError(f"duplicate update_id: {update.update_id}")
            update_ids.add(update.update_id)

            resource = self._resource_for(update)
            self._validate_update_projects(plan, update, resource)
            self.validate_evidence_refs(
                update.evidence_refs,
                project_id=plan.project_id,
                owner=f"update {update.update_id}",
            )
            self.validate_evidence_refs(
                resource.evidence_refs,
                project_id=plan.project_id,
                owner=f"resource in update {update.update_id}",
            )
            if resource.status != RecordStatus.CANONICAL:
                raise ValueError("commit plan resources must have CANONICAL status")

            resource_key = self._resource_key(resource)
            resource_payload = resource.model_dump(mode="python")
            previous_payload = resource_payloads.get(resource_key)
            if previous_payload is not None:
                if previous_payload != resource_payload:
                    raise ValueError("incompatible updates target the same resource identity")
                raise ValueError("duplicate updates target the same resource identity")
            resource_payloads[resource_key] = resource_payload

            if isinstance(resource, StoryEntityProfileV1):
                self._validate_profile_identity(resource, identity_owners)
            elif isinstance(resource, StoryEntityStateV1):
                if (
                    validate_profile_references
                    and resource.profile_id not in owned_profile_ids
                ):
                    raise ValueError(
                        f"state references nonexistent profile: {resource.profile_id}"
                    )
                self._validate_state(resource, state_values)
            elif isinstance(resource, StoryRelationshipV1):
                if validate_profile_references:
                    missing_profile_ids = {
                        resource.source_profile_id,
                        resource.target_profile_id,
                    } - owned_profile_ids
                    if missing_profile_ids:
                        missing = ", ".join(sorted(missing_profile_ids))
                        raise ValueError(
                            f"relationship references nonexistent profile: {missing}"
                        )
                self._validate_interval(
                    resource.valid_from_order,
                    resource.valid_until_order,
                    "relationship",
                )

    def validate_evidence_refs(
        self,
        evidence_refs: Iterable[EvidenceRefV1],
        *,
        project_id: str | None = None,
        owner: str = "record",
    ) -> None:
        """Resolve and validate every evidence reference for an optional project."""

        references = list(evidence_refs)
        if not references:
            raise ValueError(f"{owner} is missing evidence")
        for evidence_ref in references:
            chunk = self._evidence_lookup.get_chunk(evidence_ref.chunk_id)
            if chunk is None:
                raise ValueError(f"EvidenceRef chunk not found: {evidence_ref.chunk_id}")
            if project_id is not None and chunk.project_id != project_id:
                raise ValueError("EvidenceRef chunk belongs to another project")
            self._validate_quote(evidence_ref, chunk)

    @staticmethod
    def _resource_for(update: StoryBibleUpdate) -> StoryBibleResource:
        if isinstance(update, ProfileUpdateProposalV1):
            return update.profile
        if isinstance(update, StateUpdateProposalV1):
            return update.state
        if isinstance(update, RelationshipUpdateProposalV1):
            return update.relationship
        return update.world_rule

    @staticmethod
    def _validate_update_projects(
        plan: CommitPlanV1,
        update: StoryBibleUpdate,
        resource: StoryBibleResource,
    ) -> None:
        if update.project_id != plan.project_id:
            raise ValueError("update and commit plan must belong to the same project")
        if resource.project_id != plan.project_id:
            raise ValueError("resource and commit plan must belong to the same project")

    @staticmethod
    def _resource_key(resource: StoryBibleResource) -> tuple[str, str]:
        if isinstance(resource, StoryEntityProfileV1):
            return "profile", resource.profile_id
        if isinstance(resource, StoryEntityStateV1):
            return "state", resource.state_id
        if isinstance(resource, StoryRelationshipV1):
            return "relationship", resource.relationship_id
        return "world_rule", resource.rule_id

    @staticmethod
    def _validate_profile_identity(
        profile: StoryEntityProfileV1,
        identity_owners: dict[str, str],
    ) -> None:
        for name in (profile.canonical_name, *profile.aliases):
            identity_key = name.strip().casefold()
            existing_profile_id = identity_owners.get(identity_key)
            if existing_profile_id is not None and existing_profile_id != profile.profile_id:
                raise ValueError("duplicate StoryBible identity belongs to multiple profiles")
            identity_owners[identity_key] = profile.profile_id

    def _validate_state(
        self,
        state: StoryEntityStateV1,
        state_values: dict[
            tuple[str, str],
            list[
                tuple[
                    str,
                    int | None,
                    int | None,
                    str | None,
                    str | None,
                    Any,
                ]
            ],
        ],
    ) -> None:
        self._validate_interval(state.valid_from_order, state.valid_until_order, "state")
        for attribute_path, value in self._flatten_state(state.state):
            fact_key = (state.profile_id, attribute_path)
            intervals = state_values.setdefault(fact_key, [])
            for (
                existing_state_id,
                valid_from_order,
                valid_until_order,
                valid_from_event_id,
                valid_until_event_id,
                existing_value,
            ) in intervals:
                if (
                    existing_state_id != state.state_id
                    and existing_value != value
                    and self._state_intervals_overlap(
                        valid_from_order,
                        valid_until_order,
                        valid_from_event_id,
                        valid_until_event_id,
                        state.valid_from_order,
                        state.valid_until_order,
                        state.valid_from_event_id,
                        state.valid_until_event_id,
                    )
                ):
                    raise ValueError(
                        "incompatible state values for the same entity, attribute, "
                        "and overlapping time interval"
                    )
            intervals.append(
                (
                    state.state_id,
                    state.valid_from_order,
                    state.valid_until_order,
                    state.valid_from_event_id,
                    state.valid_until_event_id,
                    value,
                )
            )

    @classmethod
    def _state_intervals_overlap(
        cls,
        left_start: int | None,
        left_end: int | None,
        left_start_event_id: str | None,
        left_end_event_id: str | None,
        right_start: int | None,
        right_end: int | None,
        right_start_event_id: str | None,
        right_end_event_id: str | None,
    ) -> bool:
        left_has_order = left_start is not None or left_end is not None
        right_has_order = right_start is not None or right_end is not None
        if left_has_order and right_has_order:
            return cls._intervals_overlap(left_start, left_end, right_start, right_end)

        left_event_anchor = (left_start_event_id, left_end_event_id)
        right_event_anchor = (right_start_event_id, right_end_event_id)
        left_has_event = any(left_event_anchor)
        right_has_event = any(right_event_anchor)
        if not left_has_order and not right_has_order:
            if left_has_event and right_has_event:
                return left_event_anchor == right_event_anchor
            return True

        if left_has_order:
            return not right_has_event
        return not left_has_event

    @staticmethod
    def _intervals_overlap(
        left_start: int | None,
        left_end: int | None,
        right_start: int | None,
        right_end: int | None,
    ) -> bool:
        """Return whether two inclusive, optionally unbounded order intervals overlap."""

        left_before_right = (
            left_end is not None and right_start is not None and left_end < right_start
        )
        right_before_left = (
            right_end is not None and left_start is not None and right_end < left_start
        )
        return not (left_before_right or right_before_left)

    @classmethod
    def _flatten_state(
        cls, state: dict[str, Any], prefix: str = ""
    ) -> Iterable[tuple[str, Any]]:
        for key in sorted(state):
            path = f"{prefix}.{key}" if prefix else key
            value = state[key]
            if isinstance(value, dict):
                yield from cls._flatten_state(value, path)
            else:
                yield path, value

    @staticmethod
    def _validate_interval(
        valid_from_order: int | None,
        valid_until_order: int | None,
        resource_name: str,
    ) -> None:
        if (
            valid_from_order is not None
            and valid_until_order is not None
            and valid_until_order < valid_from_order
        ):
            raise ValueError(
                f"{resource_name} valid_until_order must not precede valid_from_order"
            )

    @staticmethod
    def _validate_quote(evidence_ref: EvidenceRefV1, chunk: SourceChunkV1) -> None:
        if evidence_ref.quote_start is None:
            if evidence_ref.quote_text is not None and evidence_ref.quote_text not in chunk.text:
                raise ValueError("EvidenceRef quote_text does not match source chunk")
            return

        quote_end = evidence_ref.quote_end
        if quote_end is None:
            raise ValueError("EvidenceRef quote range is incomplete")
        if quote_end > len(chunk.text):
            raise ValueError("EvidenceRef quote range exceeds source chunk")
        source_quote = chunk.text[evidence_ref.quote_start : quote_end]
        if evidence_ref.quote_text is not None and evidence_ref.quote_text != source_quote:
            raise ValueError("EvidenceRef quote_text does not match source chunk")
