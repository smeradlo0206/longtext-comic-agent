"""Proposal-only StoryBible curator backed by a structured LLM provider."""

import json

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.base import RecordStatus
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ConflictV1,
    StoryBibleContextV1,
    StoryBibleCuratorProposalV1,
)
from comic_agent.services.storybible_content_hash import with_computed_content_hash
from comic_agent.services.storybible_event_order import (
    apply_event_orders_to_plan,
    assign_event_orders,
)


class StoryBibleCurator:
    """Turn bounded StoryBible context into a schema-validated candidate proposal.

    The provider output is only a draft: this class then deterministically fills
    state/relationship story orders from the confirmed temporal relations in the
    context, replaces any provider-chosen commit-plan content hash with a
    deterministic SHA-256 content hash, and downgrades low-confidence drafts into
    blocking review conflicts. The result is still a CANDIDATE proposal only; the
    curator never writes canonical data.
    """

    spec = AgentSpec(
        agent_id="storybible-curator",
        version="1.0",
        reads=["StoryBibleContextV1"],
        output_schema="StoryBibleCuratorProposalV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=3,
        confidence_threshold=0.7,
    )

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def run(
        self,
        context: StoryBibleContextV1,
        chunk_texts: dict[str, str] | None = None,
    ) -> StoryBibleCuratorProposalV1:
        """Generate a candidate without accessing or writing canonical storage."""

        response = self._provider.structured_generate(
            self._request(context, chunk_texts or {}),
            StoryBibleCuratorProposalV1,
        )
        proposal = self._finalize(response, context)
        return proposal.model_copy(update={"status": RecordStatus.CANDIDATE})

    def _finalize(
        self,
        draft: StoryBibleCuratorProposalV1,
        context: StoryBibleContextV1,
    ) -> StoryBibleCuratorProposalV1:
        """Apply deterministic post-processing before the candidate is returned."""

        event_ids = [event.proposal_id for event in context.event_proposals]
        event_orders = assign_event_orders(context.temporal_relation_proposals, event_ids)
        ordered_plan = apply_event_orders_to_plan(draft.commit_plan, event_orders)
        hashed_plan = with_computed_content_hash(ordered_plan)

        conflicts = list(draft.conflicts)
        if draft.confidence < self.spec.confidence_threshold:
            conflicts.append(self._low_confidence_conflict(draft, hashed_plan))
        return draft.model_copy(
            update={"commit_plan": hashed_plan, "conflicts": conflicts}
        )

    def _low_confidence_conflict(
        self,
        draft: StoryBibleCuratorProposalV1,
        plan: CommitPlanV1,
    ) -> ConflictV1:
        """Build the deterministic blocking conflict for a low-confidence draft."""

        conflict_id = f"{draft.project_id}:conf_low_confidence"
        for existing in draft.conflicts:
            if existing.conflict_id == conflict_id:
                return existing
        return ConflictV1(
            conflict_id=conflict_id,
            project_id=draft.project_id,
            category="LOW_CONFIDENCE",
            summary=(
                f"Curator confidence {draft.confidence} is below the "
                f"threshold {self.spec.confidence_threshold}; review required."
            ),
            affected_update_ids=[update.update_id for update in plan.updates],
            evidence_refs=draft.evidence_refs,
            blocking=True,
        )

    _EVIDENCE_REF_SCHEMA: dict[str, object] = {
        "type": "object",
        "properties": {
            "chunk_id": {"type": "string", "description": "Source chunk id from context"},
            "quote_text": {
                "type": "string",
                "description": "Quoted excerpt copied exactly from the source chunk",
            },
        },
        "required": ["chunk_id"],
    }

    _PROFILE_SCHEMA: dict[str, object] = {
        "type": "object",
        "properties": {
            "profile_id": {"type": "string"},
            "project_id": {"type": "string"},
            "entity_kind": {"type": "string", "enum": ["PERSON", "ORGANIZATION", "LOCATION"]},
            "canonical_name": {"type": "string"},
            "aliases": {"type": "array", "items": {"type": "string"}},
            "attributes": {"type": "object"},
            "revision": {"type": "integer", "minimum": 1},
            "evidence_refs": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/definitions/evidence_ref"},
            },
        },
        "required": [
            "profile_id",
            "project_id",
            "entity_kind",
            "canonical_name",
            "evidence_refs",
        ],
    }

    _STATE_SCHEMA: dict[str, object] = {
        "type": "object",
        "properties": {
            "state_id": {"type": "string"},
            "project_id": {"type": "string"},
            "profile_id": {"type": "string"},
            "state": {"type": "object"},
            "triggering_event_id": {"type": "string"},
            "valid_from_event_id": {"type": "string"},
            "valid_until_event_id": {"type": "string"},
            "valid_from_order": {"type": "integer"},
            "valid_until_order": {"type": "integer"},
            "revision": {"type": "integer", "minimum": 1},
            "evidence_refs": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/definitions/evidence_ref"},
            },
        },
        "required": ["state_id", "project_id", "profile_id", "evidence_refs"],
    }

    _RELATIONSHIP_SCHEMA: dict[str, object] = {
        "type": "object",
        "properties": {
            "relationship_id": {"type": "string"},
            "project_id": {"type": "string"},
            "source_profile_id": {"type": "string"},
            "target_profile_id": {"type": "string"},
            "relationship_type": {"type": "string"},
            "attributes": {"type": "object"},
            "valid_from_event_id": {"type": "string"},
            "valid_until_event_id": {"type": "string"},
            "valid_from_order": {"type": "integer"},
            "valid_until_order": {"type": "integer"},
            "revision": {"type": "integer", "minimum": 1},
            "evidence_refs": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/definitions/evidence_ref"},
            },
        },
        "required": [
            "relationship_id",
            "project_id",
            "source_profile_id",
            "target_profile_id",
            "relationship_type",
            "evidence_refs",
        ],
    }

    _WORLD_RULE_SCHEMA: dict[str, object] = {
        "type": "object",
        "properties": {
            "rule_id": {"type": "string"},
            "project_id": {"type": "string"},
            "name": {"type": "string"},
            "statement": {"type": "string"},
            "scope": {"type": "string"},
            "revision": {"type": "integer", "minimum": 1},
            "evidence_refs": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/definitions/evidence_ref"},
            },
        },
        "required": ["rule_id", "project_id", "name", "statement", "evidence_refs"],
    }

    _CONFLICT_SCHEMA: dict[str, object] = {
        "type": "object",
        "properties": {
            "conflict_id": {"type": "string"},
            "project_id": {"type": "string"},
            "category": {"type": "string"},
            "summary": {"type": "string"},
            "affected_update_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "evidence_refs": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/definitions/evidence_ref"},
            },
            "blocking": {"type": "boolean"},
        },
        "required": [
            "conflict_id",
            "project_id",
            "category",
            "summary",
            "affected_update_ids",
            "evidence_refs",
        ],
    }

    def _update_variants(self) -> dict[str, object]:
        """Return the four concrete update shapes of the StoryBible update union."""

        def wrapped(resource_schema: dict[str, object], resource_key: str) -> dict[str, object]:
            return {
                "type": "object",
                "properties": {
                    "update_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "evidence_refs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/definitions/evidence_ref"},
                    },
                    resource_key: resource_schema,
                },
                "required": ["update_id", "project_id", resource_key, "evidence_refs"],
            }

        return {
            "profile_update": wrapped(self._PROFILE_SCHEMA, "profile"),
            "state_update": wrapped(self._STATE_SCHEMA, "state"),
            "relationship_update": wrapped(self._RELATIONSHIP_SCHEMA, "relationship"),
            "world_rule_update": wrapped(self._WORLD_RULE_SCHEMA, "world_rule"),
        }

    def _output_schema(self) -> dict[str, object]:
        variants = self._update_variants()
        return {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string", "description": "Unique proposal id"},
                "project_id": {"type": "string", "description": "Project id from the context"},
                "commit_plan": {
                    "type": "object",
                    "properties": {
                        "commit_plan_id": {"type": "string"},
                        "project_id": {"type": "string"},
                        "source_proposal_id": {
                            "type": "string",
                            "description": "Same as the top-level proposal_id",
                        },
                        "updates": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "oneOf": [
                                    variants["profile_update"],
                                    variants["state_update"],
                                    variants["relationship_update"],
                                    variants["world_rule_update"],
                                ]
                            },
                        },
                        "evidence_refs": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"$ref": "#/definitions/evidence_ref"},
                        },
                    },
                    "required": [
                        "commit_plan_id",
                        "project_id",
                        "source_proposal_id",
                        "updates",
                        "evidence_refs",
                    ],
                },
                "conflicts": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/conflict"},
                },
                "evidence_refs": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/definitions/evidence_ref"},
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["proposal_id", "project_id", "commit_plan", "evidence_refs", "confidence"],
            "definitions": {
                "evidence_ref": self._EVIDENCE_REF_SCHEMA,
                "conflict": self._CONFLICT_SCHEMA,
                **variants,
            },
        }

    _SYSTEM_PROMPT = (
        "You are a StoryBible Curator for a long-text comic pipeline. Your goal is to "
        "keep the story world consistent for image generation: characters, "
        "organizations, locations, their relationships, world rules, and time-bound "
        "states.\n\n"
        "The user message contains, in order:\n"
        "1. A JSON context object with reviewed upstream proposals "
        "(entity_proposals, event_proposals, state_change_proposals, "
        "temporal_relation_proposals) and existing canonical StoryBible resources "
        "(profiles, states, relationships, world_rules).\n"
        "2. Source chunk texts, each labeled with its chunk id.\n\n"
        "Produce ONE StoryBibleCuratorProposalV1 candidate as a JSON object.\n\n"
        "CURATION RULES:\n"
        "1. CONSOLIDATE, DO NOT RE-EXTRACT. Prefer the reviewed proposals as your "
        "facts and reuse their exact ids. Map entity_type to profile entity_kind: "
        "CHARACTER -> PERSON, ORGANIZATION -> ORGANIZATION, LOCATION -> LOCATION. "
        "Entities with other entity_type (OBJECT, PROP, CREATURE, ABILITY, CONCEPT) "
        "must NOT become profiles; record their facts as state attributes (e.g. "
        "possession.holder) on person profiles. When an entity matches an existing "
        "canonical profile by name or alias, reuse that profile_id and set revision "
        "to the existing revision plus one; otherwise create a new profile.\n"
        "2. STATES FROM STATE CHANGES. For each state_change_proposal emit a "
        "StateUpdateProposalV1: profile_id resolves the change target; state.state "
        "is {\"<attribute_path>\": <new_value>}; triggering_event_id and "
        "valid_from_event_id take the change's event id. Leave valid_from_order and "
        "valid_until_order null; the system assigns them from temporal relations. "
        "For non-persistent changes also set valid_until_event_id when the "
        "follow-up event is known. Never create two states for the same "
        "profile+attribute with overlapping intervals.\n"
        "3. TEMPORAL ORDERING. Read temporal_relation_proposals BEFORE/AFTER chains "
        "to decide which event precedes which; never invent an order the relations "
        "do not support.\n"
        "4. RELATIONSHIPS. For durable, chunk-supported connections between people "
        "and organizations (family, alliance, enmity, membership, location-of) emit "
        "a RelationshipUpdateProposalV1 whose source/target profile ids exist in the "
        "context or in this plan. Set valid_from_event_id when the relationship "
        "starts; leave the order fields null.\n"
        "5. WORLD RULES. For explicit, source-supported setting rules (laws of the "
        "world, magic systems, recurring customs) emit a WorldRuleUpdateProposalV1 "
        "with name, statement, and optional scope.\n"
        "6. CONFLICTS. When you detect duplicate identities, contradictory state "
        "values, or missing evidence, emit ConflictV1 entries whose "
        "affected_update_ids list update ids from this plan. Never silently merge "
        "two distinct identities.\n"
        "7. EVIDENCE. Every evidence_ref uses chunk_id plus quote_text copied "
        "EXACTLY from a source chunk, character by character, with no "
        "quote_start/quote_end. Every update, resource, plan, and conflict must "
        "carry at least one evidence_ref.\n"
        "8. IDS. All ids must start with \"{project_id}:\" and be unique within the "
        "plan. Use the exact project_id value from the context JSON.\n"
        "9. Return ONLY the JSON object, no markdown, no explanation.\n\n"
        "Output JSON schema:\n"
    )

    def _request(
        self, context: StoryBibleContextV1, chunk_texts: dict[str, str]
    ) -> dict[str, object]:
        context_json = json.dumps(
            context.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        )

        user_parts = [context_json]
        for chunk_id, text in chunk_texts.items():
            user_parts.append(f"\n--- SOURCE CHUNK {chunk_id} ---\n{text}")

        return {
            "messages": [
                {
                    "role": "system",
                    "content": self._SYSTEM_PROMPT
                    + json.dumps(self._output_schema(), ensure_ascii=False, indent=2),
                },
                {
                    "role": "user",
                    "content": "\n".join(user_parts),
                },
            ]
        }
