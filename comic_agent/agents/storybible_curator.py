"""Proposal-only StoryBible curator backed by a structured LLM provider."""

import json

from comic_agent.agents.specs import AgentSpec
from comic_agent.providers.llm import LLMProvider
from comic_agent.schemas.base import RecordStatus
from comic_agent.schemas.reliability import ProviderExecutionMetadataV1
from comic_agent.schemas.storybible import StoryBibleContextV1, StoryBibleCuratorProposalV1


class StoryBibleCurator:
    """Turn bounded StoryBible context into a schema-validated candidate proposal."""

    spec = AgentSpec(
        agent_id="storybible-curator",
        version="1.1",
        reads=["StoryBibleContextV1"],
        output_schema="StoryBibleCuratorProposalV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=8,
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
        return response.model_copy(update={"status": RecordStatus.CANDIDATE})

    def last_execution_metadata(self) -> ProviderExecutionMetadataV1 | None:
        """Expose only the Provider's allowlisted execution metadata."""

        getter = getattr(self._provider, "last_execution_metadata", None)
        value = getter() if callable(getter) else None
        return value if isinstance(value, ProviderExecutionMetadataV1) else None

    def execution_history(self) -> list[ProviderExecutionMetadataV1]:
        """Expose a copy of the Provider's allowlisted local usage history."""

        getter = getattr(self._provider, "execution_history", None)
        values = getter() if callable(getter) else []
        return [value for value in values if isinstance(value, ProviderExecutionMetadataV1)]

    _EVIDENCE_REF_SCHEMA: dict[str, object] = {
        "type": "object",
        "properties": {
            "chunk_id": {"type": "string", "description": "Source chunk id from context"},
            "quote_start": {"type": "integer", "description": "Start offset in chunk text"},
            "quote_end": {"type": "integer", "description": "End offset in chunk text"},
            "quote_text": {"type": "string", "description": "Quoted excerpt from source"},
        },
        "required": ["chunk_id"],
    }

    _OUTPUT_SCHEMA: dict[str, object] = {
        "type": "object",
        "properties": {
            "proposal_id": {"type": "string", "description": "Unique proposal id, e.g. prop_1"},
            "project_id": {"type": "string", "description": "Project id from the context"},
            "commit_plan": {
                "type": "object",
                "properties": {
                    "commit_plan_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "source_proposal_id": {"type": "string"},
                    "content_hash": {
                        "type": "string",
                        "description": "Short content hash, e.g. h1",
                    },
                    "evidence_refs": {
                        "type": "array",
                        "items": {"$ref": "#/definitions/evidence_ref"},
                    },
                    "updates": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "oneOf": [
                                {
                                    "type": "object",
                                    "properties": {
                                        "update_id": {"type": "string"},
                                        "project_id": {"type": "string"},
                                        "evidence_refs": {
                                            "type": "array",
                                            "items": {"$ref": "#/definitions/evidence_ref"},
                                        },
                                        "profile": {
                                            "type": "object",
                                            "properties": {
                                                "profile_id": {"type": "string"},
                                                "project_id": {"type": "string"},
                                                "entity_kind": {
                                                    "type": "string",
                                                    "enum": [
                                                        "PERSON",
                                                        "ORGANIZATION",
                                                        "LOCATION",
                                                    ],
                                                },
                                                "canonical_name": {"type": "string"},
                                                "aliases": {
                                                    "type": "array",
                                                    "items": {"type": "string"},
                                                },
                                                "attributes": {"type": "object"},
                                                "revision": {"type": "integer"},
                                                "evidence_refs": {
                                                    "type": "array",
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
                                        },
                                    },
                                    "required": [
                                        "update_id",
                                        "project_id",
                                        "profile",
                                        "evidence_refs",
                                    ],
                                },
                                {
                                    "type": "object",
                                    "properties": {
                                        "update_id": {"type": "string"},
                                        "project_id": {"type": "string"},
                                        "evidence_refs": {
                                            "type": "array",
                                            "items": {"$ref": "#/definitions/evidence_ref"},
                                        },
                                        "state": {
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
                                                "revision": {"type": "integer"},
                                        "evidence_refs": {
                                            "type": "array",
                                            "items": {"$ref": "#/definitions/evidence_ref"},
                                        },
                                            },
                                            "required": [
                                                "state_id",
                                                "project_id",
                                                "profile_id",
                                                "evidence_refs",
                                            ],
                                        },
                                    },
                                    "required": [
                                        "update_id",
                                        "project_id",
                                        "state",
                                        "evidence_refs",
                                    ],
                                },
                            ],
                        },
                    },
                },
                "required": [
                    "commit_plan_id",
                    "project_id",
                    "source_proposal_id",
                    "content_hash",
                    "updates",
                    "evidence_refs",
                ],
            },
            "conflicts": {"type": "array", "items": {"type": "object"}},
            "evidence_refs": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/definitions/evidence_ref"},
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["proposal_id", "project_id", "commit_plan", "evidence_refs", "confidence"],
        "definitions": {"evidence_ref": _EVIDENCE_REF_SCHEMA},
    }
    # The provider-facing contract is generated from the schema source of truth.  Keeping the
    # assignment beside the historical literal makes the compatibility change explicit while
    # ensuring relationship and world-rule updates cannot drift out of the actual contract.
    _OUTPUT_SCHEMA = StoryBibleCuratorProposalV1.model_json_schema()

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
                    "content": (
                        "You are a StoryBible Curator. Read the source chunks below and produce "
                        "one StoryBibleCuratorProposalV1 candidate as a JSON object.\n\n"
                        "CRITICAL RULES:\n"
                        "1. Extract EVERY person, organization, and location from the source "
                        "chunks.\n"
                        "2. For each entity, produce a ProfileUpdateProposalV1 in "
                        "commit_plan.updates.\n"
                        "3. For observable state (location, status), produce a "
                        "StateUpdateProposalV1.\n"
                        "   Each state MUST have a unique attribute_path per profile. "
                        "Do NOT create\n"
                        "   two states for the same profile+attribute with overlapping intervals.\n"
                        "   Leave valid_from_order/valid_until_order as null if order is unknown.\n"
                        "4. evidence_ref MUST use chunk_id + quote_text. Do NOT include "
                        "quote_start/quote_end.\n"
                        "   quote_text MUST be copied EXACTLY from the source chunk, "
                        "character by character.\n"
                        "5. commit_plan: commit_plan_id, project_id, "
                        "source_proposal_id=same as top proposal_id,\n"
                        "   content_hash (any short string like \"h1\"), updates "
                        "(non-empty!), evidence_refs (non-empty!).\n"
                        "6. Top-level: proposal_id, project_id, evidence_refs "
                        "(non-empty!), confidence (0.0-1.0).\n"
                        "7. No empty arrays. ALL ids MUST start with project_id + colon, e.g.\n"
                        "   \"{project_id}:prof_name\", \"{project_id}:upd_1\". Use the EXACT\n"
                        "   project_id value from the context JSON above.\n"
                        "8. Return ONLY the JSON object, no markdown, no explanation.\n\n"
                        "Output JSON schema:\n"
                        + json.dumps(self._OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
                    ),
                },
                {
                    "role": "user",
                    "content": "\n".join(user_parts),
                },
            ]
        }
