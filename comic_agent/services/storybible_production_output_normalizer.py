"""Deterministic output trust boundary for future production StoryBible execution."""

import json
from typing import Any

from comic_agent.schemas.base import EvidenceRefV1, RecordStatus
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ConflictV1,
    ProfileUpdateProposalV1,
    RelationshipUpdateProposalV1,
    StateUpdateProposalV1,
    StoryBibleCuratorProposalV1,
    StoryBibleProductionContextV1,
    StoryBibleProductionRunV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleUpdateProposalV1,
    WorldRuleV1,
)
from comic_agent.services.id_service import checksum_text, stable_id
from comic_agent.services.storybible_production_context import (
    canonical_storybible_snapshot_hash,
)

type StoryBibleUpdate = (
    ProfileUpdateProposalV1
    | StateUpdateProposalV1
    | RelationshipUpdateProposalV1
    | WorldRuleUpdateProposalV1
)
type StoryBibleResource = (
    StoryEntityProfileV1 | StoryEntityStateV1 | StoryRelationshipV1 | WorldRuleV1
)


class StoryBibleProductionOutputNormalizer:
    """Normalize one schema-valid but untrusted model proposal without side effects."""

    def normalize(
        self,
        raw: StoryBibleCuratorProposalV1,
        *,
        context: StoryBibleProductionContextV1,
        run: StoryBibleProductionRunV1,
    ) -> StoryBibleCuratorProposalV1:
        self._validate_lineage(raw, context, run)
        updates = list(raw.commit_plan.updates)
        self._reject_duplicate_local_ids(updates, project_id=context.project_id)
        normalized_evidence = _EvidenceGrounder(context)

        profile_map = self._build_profile_map(updates, context, run, normalized_evidence)
        resource_maps: dict[str, dict[str, str]] = {"profile": profile_map}
        normalized_updates: list[StoryBibleUpdate] = []
        semantic_owners: dict[tuple[str, str], str] = {}
        existing_ids = _existing_resource_ids(context)

        for update in updates:
            resource = _resource_for(update)
            kind, local_resource_id = _resource_identity(resource)
            normalized_resource = self._normalize_resource(
                resource,
                profile_map=profile_map,
                context=context,
                run=run,
                evidence=normalized_evidence,
                existing_ids=existing_ids,
            )
            normalized_resource_id = _resource_identity(normalized_resource)[1]
            resource_maps.setdefault(kind, {})[local_resource_id] = normalized_resource_id
            semantic_key = _canonical_json(_resource_semantic_payload(normalized_resource))
            owner_key = (kind, semantic_key)
            previous_owner = semantic_owners.get(owner_key)
            if previous_owner is not None and previous_owner != local_resource_id:
                raise ValueError(f"ambiguous duplicate new {kind} resources")
            semantic_owners[owner_key] = local_resource_id
            normalized_update_id = stable_id(
                "storybible-update",
                run.input_hash,
                kind,
                normalized_resource_id,
                semantic_key,
            )
            normalized_updates.append(
                _replace_update(
                    update,
                    update_id=normalized_update_id,
                    project_id=context.project_id,
                    resource=normalized_resource,
                    evidence_refs=normalized_evidence.normalize(update.evidence_refs),
                )
            )

        update_id_map = {
            raw_update.update_id: normalized_update.update_id
            for raw_update, normalized_update in zip(updates, normalized_updates, strict=True)
        }
        normalized_updates.sort(key=lambda item: item.update_id)
        normalized_conflicts = self._normalize_conflicts(
            raw.conflicts,
            update_id_map=update_id_map,
            context=context,
            run=run,
            evidence=normalized_evidence,
        )
        proposal_id = stable_id("storybible-proposal", run.input_hash)
        plan_id = stable_id("storybible-commit-plan", run.input_hash)
        plan_evidence = normalized_evidence.normalize(raw.commit_plan.evidence_refs)
        content_hash = _commit_plan_content_hash(
            project_id=context.project_id,
            updates=normalized_updates,
            evidence_refs=plan_evidence,
        )
        plan = CommitPlanV1(
            commit_plan_id=plan_id,
            project_id=context.project_id,
            source_proposal_id=proposal_id,
            content_hash=content_hash,
            updates=normalized_updates,
            evidence_refs=plan_evidence,
        )
        return StoryBibleCuratorProposalV1(
            proposal_id=proposal_id,
            project_id=context.project_id,
            status=raw.status,
            commit_plan=plan,
            conflicts=normalized_conflicts,
            evidence_refs=normalized_evidence.normalize(raw.evidence_refs),
            confidence=raw.confidence,
        )

    @staticmethod
    def _validate_lineage(
        raw: StoryBibleCuratorProposalV1,
        context: StoryBibleProductionContextV1,
        run: StoryBibleProductionRunV1,
    ) -> None:
        if raw.project_id != context.project_id:
            raise ValueError("StoryBible proposal belongs to another project")
        if raw.status != RecordStatus.CANDIDATE:
            raise ValueError("production StoryBible proposal must have CANDIDATE status")
        if raw.commit_plan.project_id != context.project_id:
            raise ValueError("StoryBible commit plan belongs to another project")
        if run.project_id != context.project_id:
            raise ValueError("StoryBible run and context project mismatch")
        if canonical_storybible_snapshot_hash(context.canonical_snapshot) != (
            context.canonical_storybible_snapshot_hash
        ):
            raise ValueError("StoryBible production context snapshot hash is invalid")
        if (
            run.gate2_approved_bundle_id != context.gate2_approved_bundle_id
            or run.approved_timeline_bundle_id != context.approved_timeline_bundle_id
            or run.canonical_storybible_snapshot_hash
            != context.canonical_storybible_snapshot_hash
        ):
            raise ValueError("StoryBible run does not match production context lineage")

    @staticmethod
    def _reject_duplicate_local_ids(
        updates: list[StoryBibleUpdate], *, project_id: str
    ) -> None:
        update_ids: set[str] = set()
        resource_ids: dict[str, set[str]] = {}
        for update in updates:
            resource = _resource_for(update)
            if update.project_id != project_id or resource.project_id != project_id:
                raise ValueError("StoryBible update or resource belongs to another project")
            if update.update_id in update_ids:
                raise ValueError(f"duplicate local update_id: {update.update_id}")
            update_ids.add(update.update_id)
            kind, resource_id = _resource_identity(resource)
            ids = resource_ids.setdefault(kind, set())
            if resource_id in ids:
                raise ValueError(f"duplicate local {kind}_id: {resource_id}")
            ids.add(resource_id)

    def _build_profile_map(
        self,
        updates: list[StoryBibleUpdate],
        context: StoryBibleProductionContextV1,
        run: StoryBibleProductionRunV1,
        evidence: "_EvidenceGrounder",
    ) -> dict[str, str]:
        existing = {item.profile_id for item in context.canonical_snapshot.profiles}
        result: dict[str, str] = {}
        semantic_owners: dict[str, str] = {}
        for update in updates:
            if not isinstance(update, ProfileUpdateProposalV1):
                continue
            profile = update.profile.model_copy(
                update={
                    "project_id": context.project_id,
                    "evidence_refs": evidence.normalize(update.profile.evidence_refs),
                }
            )
            if profile.profile_id in existing:
                result[profile.profile_id] = profile.profile_id
                continue
            semantic = _canonical_json(_resource_semantic_payload(profile))
            previous = semantic_owners.get(semantic)
            if previous is not None and previous != profile.profile_id:
                raise ValueError("ambiguous duplicate new profile resources")
            semantic_owners[semantic] = profile.profile_id
            result[profile.profile_id] = stable_id(
                "storybible-profile", context.project_id, run.input_hash, semantic
            )
        return result

    def _normalize_resource(
        self,
        resource: StoryBibleResource,
        *,
        profile_map: dict[str, str],
        context: StoryBibleProductionContextV1,
        run: StoryBibleProductionRunV1,
        evidence: "_EvidenceGrounder",
        existing_ids: dict[str, set[str]],
    ) -> StoryBibleResource:
        resource_evidence = evidence.normalize(resource.evidence_refs)
        if isinstance(resource, StoryEntityProfileV1):
            normalized_id = profile_map[resource.profile_id]
            return resource.model_copy(
                update={
                    "profile_id": normalized_id,
                    "project_id": context.project_id,
                    "evidence_refs": resource_evidence,
                }
            )
        if isinstance(resource, StoryEntityStateV1):
            profile_id = _resolve_profile_id(resource.profile_id, profile_map, context)
            self._validate_temporal_resource(resource, context)
            state_resource = resource.model_copy(
                update={
                    "project_id": context.project_id,
                    "profile_id": profile_id,
                    "evidence_refs": resource_evidence,
                }
            )
            normalized_id = _normalized_resource_id(
                "state", resource.state_id, state_resource, existing_ids, context, run
            )
            return state_resource.model_copy(update={"state_id": normalized_id})
        if isinstance(resource, StoryRelationshipV1):
            source_id = _resolve_profile_id(resource.source_profile_id, profile_map, context)
            target_id = _resolve_profile_id(resource.target_profile_id, profile_map, context)
            self._validate_temporal_resource(resource, context)
            relationship_resource = resource.model_copy(
                update={
                    "project_id": context.project_id,
                    "source_profile_id": source_id,
                    "target_profile_id": target_id,
                    "evidence_refs": resource_evidence,
                }
            )
            normalized_id = _normalized_resource_id(
                "relationship",
                resource.relationship_id,
                relationship_resource,
                existing_ids,
                context,
                run,
            )
            return relationship_resource.model_copy(update={"relationship_id": normalized_id})
        rule_resource = resource.model_copy(
            update={"project_id": context.project_id, "evidence_refs": resource_evidence}
        )
        normalized_id = _normalized_resource_id(
            "world-rule", resource.rule_id, rule_resource, existing_ids, context, run
        )
        return rule_resource.model_copy(update={"rule_id": normalized_id})

    @staticmethod
    def _validate_temporal_resource(
        resource: StoryEntityStateV1 | StoryRelationshipV1,
        context: StoryBibleProductionContextV1,
    ) -> None:
        trusted_ids = set(context.trusted_event_ids)
        event_fields = [resource.valid_from_event_id, resource.valid_until_event_id]
        if isinstance(resource, StoryEntityStateV1):
            event_fields.append(resource.triggering_event_id)
        if any(event_id is not None and event_id not in trusted_ids for event_id in event_fields):
            raise ValueError("StoryBible resource references an unapproved event")

        order_by_event = {
            item.event_id: item.resolved_order for item in context.trusted_event_order
        }
        has_total_order = bool(order_by_event) and all(
            value is not None for value in order_by_event.values()
        )
        pairs = (
            (resource.valid_from_event_id, resource.valid_from_order, "valid_from_order"),
            (resource.valid_until_event_id, resource.valid_until_order, "valid_until_order"),
        )
        for event_id, order, field_name in pairs:
            if not has_total_order and order is not None:
                raise ValueError(f"{field_name} is not allowed without a trusted total order")
            if order is not None:
                if event_id is None:
                    raise ValueError(f"{field_name} requires its event anchor")
                if order_by_event[event_id] != order:
                    raise ValueError(f"{field_name} does not match trusted event order")

        start = resource.valid_from_event_id
        end = resource.valid_until_event_id
        predecessors = {
            item.event_id: set(item.strict_predecessor_event_ids)
            for item in context.trusted_event_order
        }
        if start is not None and end is not None and end in predecessors.get(start, set()):
            raise ValueError("StoryBible temporal interval is reversed by approved Timeline")

    @staticmethod
    def _normalize_conflicts(
        conflicts: list[ConflictV1],
        *,
        update_id_map: dict[str, str],
        context: StoryBibleProductionContextV1,
        run: StoryBibleProductionRunV1,
        evidence: "_EvidenceGrounder",
    ) -> list[ConflictV1]:
        local_ids: set[str] = set()
        normalized: list[ConflictV1] = []
        for conflict in conflicts:
            if conflict.project_id != context.project_id:
                raise ValueError("StoryBible conflict belongs to another project")
            if conflict.conflict_id in local_ids:
                raise ValueError(f"duplicate local conflict_id: {conflict.conflict_id}")
            local_ids.add(conflict.conflict_id)
            try:
                affected = sorted({update_id_map[item] for item in conflict.affected_update_ids})
            except KeyError as error:
                raise ValueError("conflict references an unknown update_id") from error
            if len(affected) != len(conflict.affected_update_ids):
                raise ValueError("conflict contains duplicate affected_update_ids")
            refs = evidence.normalize(conflict.evidence_refs)
            semantic = _canonical_json(
                {
                    "category": conflict.category,
                    "summary": conflict.summary,
                    "affected_update_ids": affected,
                    "evidence_refs": [item.model_dump(mode="json") for item in refs],
                    "blocking": conflict.blocking,
                }
            )
            normalized.append(
                ConflictV1(
                    conflict_id=stable_id(
                        "storybible-conflict", context.project_id, run.input_hash, semantic
                    ),
                    project_id=context.project_id,
                    category=conflict.category,
                    summary=conflict.summary,
                    affected_update_ids=affected,
                    evidence_refs=refs,
                    blocking=conflict.blocking,
                )
            )
        return sorted(normalized, key=lambda item: item.conflict_id)


class _EvidenceGrounder:
    def __init__(self, context: StoryBibleProductionContextV1) -> None:
        self._project_id = context.project_id
        self._allowed_chunk_ids = set(context.source_chunk_ids)
        self._chunks = {chunk.chunk_id: chunk for chunk in context.source_chunks}

    def normalize(self, values: list[EvidenceRefV1]) -> list[EvidenceRefV1]:
        normalized = [self._normalize_one(value) for value in values]
        keyed = {_canonical_json(item.model_dump(mode="json")): item for item in normalized}
        return [keyed[key] for key in sorted(keyed)]

    def _normalize_one(self, ref: EvidenceRefV1) -> EvidenceRefV1:
        if ref.chunk_id not in self._allowed_chunk_ids:
            raise ValueError("EvidenceRef chunk is outside trusted production scope")
        chunk = self._chunks.get(ref.chunk_id)
        if chunk is None:
            raise ValueError("EvidenceRef chunk is unavailable in production context")
        if chunk.project_id != self._project_id:
            raise ValueError("EvidenceRef chunk belongs to another project")
        if ref.quote_start is None:
            if ref.quote_text is None:
                raise ValueError("production EvidenceRef requires an exact quote or span")
            first = chunk.text.find(ref.quote_text)
            if first < 0:
                raise ValueError("EvidenceRef quote_text does not match source chunk")
            if chunk.text.find(ref.quote_text, first + 1) >= 0:
                raise ValueError("EvidenceRef quote_text is ambiguous without offsets")
            return EvidenceRefV1(
                chunk_id=ref.chunk_id,
                quote_start=first,
                quote_end=first + len(ref.quote_text),
                quote_text=ref.quote_text,
            )
        if ref.quote_end is None or ref.quote_end > len(chunk.text):
            raise ValueError("EvidenceRef quote range exceeds source chunk")
        source_quote = chunk.text[ref.quote_start : ref.quote_end]
        if ref.quote_text is not None and ref.quote_text != source_quote:
            raise ValueError("EvidenceRef quote_text does not match source chunk")
        return EvidenceRefV1(
            chunk_id=ref.chunk_id,
            quote_start=ref.quote_start,
            quote_end=ref.quote_end,
            quote_text=source_quote,
        )


def _existing_resource_ids(context: StoryBibleProductionContextV1) -> dict[str, set[str]]:
    snapshot = context.canonical_snapshot
    return {
        "profile": {item.profile_id for item in snapshot.profiles},
        "state": {item.state_id for item in snapshot.states},
        "relationship": {item.relationship_id for item in snapshot.relationships},
        "world-rule": {item.rule_id for item in snapshot.world_rules},
    }


def _resolve_profile_id(
    local_id: str,
    profile_map: dict[str, str],
    context: StoryBibleProductionContextV1,
) -> str:
    if local_id in profile_map:
        return profile_map[local_id]
    canonical_ids = {item.profile_id for item in context.canonical_snapshot.profiles}
    if local_id in canonical_ids:
        return local_id
    raise ValueError(f"StoryBible resource references unknown profile: {local_id}")


def _normalized_resource_id(
    kind: str,
    local_id: str,
    resource: StoryBibleResource,
    existing_ids: dict[str, set[str]],
    context: StoryBibleProductionContextV1,
    run: StoryBibleProductionRunV1,
) -> str:
    if local_id in existing_ids[kind]:
        return local_id
    semantic = _canonical_json(_resource_semantic_payload(resource))
    return stable_id(f"storybible-{kind}", context.project_id, run.input_hash, semantic)


def _resource_semantic_payload(resource: StoryBibleResource) -> dict[str, Any]:
    payload = resource.model_dump(mode="json")
    for field in ("profile_id", "state_id", "relationship_id", "rule_id", "project_id"):
        payload.pop(field, None)
    return payload


def _resource_for(update: StoryBibleUpdate) -> StoryBibleResource:
    if isinstance(update, ProfileUpdateProposalV1):
        return update.profile
    if isinstance(update, StateUpdateProposalV1):
        return update.state
    if isinstance(update, RelationshipUpdateProposalV1):
        return update.relationship
    return update.world_rule


def _resource_identity(resource: StoryBibleResource) -> tuple[str, str]:
    if isinstance(resource, StoryEntityProfileV1):
        return "profile", resource.profile_id
    if isinstance(resource, StoryEntityStateV1):
        return "state", resource.state_id
    if isinstance(resource, StoryRelationshipV1):
        return "relationship", resource.relationship_id
    return "world-rule", resource.rule_id


def _replace_update(
    update: StoryBibleUpdate,
    *,
    update_id: str,
    project_id: str,
    resource: StoryBibleResource,
    evidence_refs: list[EvidenceRefV1],
) -> StoryBibleUpdate:
    common = {
        "update_id": update_id,
        "project_id": project_id,
        "evidence_refs": evidence_refs,
    }
    if isinstance(update, ProfileUpdateProposalV1):
        assert isinstance(resource, StoryEntityProfileV1)
        return ProfileUpdateProposalV1(**common, profile=resource)
    if isinstance(update, StateUpdateProposalV1):
        assert isinstance(resource, StoryEntityStateV1)
        return StateUpdateProposalV1(**common, state=resource)
    if isinstance(update, RelationshipUpdateProposalV1):
        assert isinstance(resource, StoryRelationshipV1)
        return RelationshipUpdateProposalV1(**common, relationship=resource)
    assert isinstance(resource, WorldRuleV1)
    return WorldRuleUpdateProposalV1(**common, world_rule=resource)


def _commit_plan_content_hash(
    *,
    project_id: str,
    updates: list[StoryBibleUpdate],
    evidence_refs: list[EvidenceRefV1],
) -> str:
    return checksum_text(
        _canonical_json(
            {
                "schema_version": "1.0",
                "project_id": project_id,
                "updates": [item.model_dump(mode="json") for item in updates],
                "evidence_refs": [item.model_dump(mode="json") for item in evidence_refs],
            }
        )
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
