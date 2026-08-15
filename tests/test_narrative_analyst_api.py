import json
from pathlib import Path
from typing import Any, TypeVar

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from comic_agent.config import get_settings
from comic_agent.main import create_app
from comic_agent.schemas.narrative import (
    ClaimProposalBatchV1,
    EntityProposalBatchV1,
    EventProposalBatchV1,
    KnowledgeStateProposalBatchV1,
    RelationshipSignalProposalBatchV1,
    StateChangeProposalBatchV1,
)

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)

PROJECT_PAYLOAD = {"project_id": "demo-project", "name": "Demo Project"}
SAMPLE_TEXT = """第一章 开端

林夏推开门。

陈野把伞递给林夏。

钟声从楼上传来。
"""

SUMMARY_FIELDS = (
    "project_id",
    "mode",
    "dry_run",
    "real_llm_requested",
    "real_llm_enabled",
    "real_llm_called",
    "provider_name",
    "model",
    "import_idempotent",
    "context_chunk_ids",
    "selected_chunk_metadata",
    "chunk_limit",
    "chunk_offset",
    "selected_chunks_count",
    "max_chars_per_chunk",
    "input_chars_total",
    "truncated_chunks_count",
    "agent_run_saved",
    "agent_run_id",
    "agent_run_status",
    "provider_result_id",
    "provider_success",
    "provider_error_diagnostics",
    "usage_prompt_tokens",
    "usage_completion_tokens",
    "usage_total_tokens",
    "output_schema",
    "schema_validation_passed",
    "evidence_validation_passed",
    "quote_matched",
    "char_range_matched",
    "error_message",
    "failure_category",
    "recommended_action",
    "manual_score",
    "manual_issue",
)


class FakeNarrativeProvider:
    def __init__(self, *, max_text_length: int = 5) -> None:
        self.calls = 0
        self.requests: list[dict[str, object]] = []
        self.max_text_length = max_text_length

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        self.calls += 1
        self.requests.append(request)
        input_context = request["input_context"]
        assert isinstance(input_context, dict)
        source_chunks = input_context["source_chunks"]
        assert isinstance(source_chunks, list)
        source_chunk = source_chunks[0]
        assert isinstance(source_chunk, dict)
        expected_fields = {"chunk_id", "chapter_id", "text"}
        if output_model in {StateChangeProposalBatchV1, RelationshipSignalProposalBatchV1}:
            expected_fields = {
                "schema_version",
                "chunk_id",
                "document_id",
                "chapter_id",
                "project_id",
                "order",
                "text",
                "source_page",
                "char_start",
                "char_end",
                "checksum",
            }
        assert set(source_chunk) == expected_fields
        assert len(str(source_chunk["text"])) <= self.max_text_length
        quote = str(source_chunk["text"])[:3]
        chunk_id = str(source_chunk["chunk_id"])

        if output_model is EventProposalBatchV1:
            return output_model.model_validate(
                {
                    "batch_id": "event-batch-console-1",
                    "events": [
                        {
                            "proposal_id": "event-console-1",
                            "event_type": "demo_event",
                            "summary": "开门",
                            "participant_ids": [],
                            "actor_resolution_status": "UNKNOWN",
                            "location_id": None,
                            "evidence_refs": [
                                {
                                    "chunk_id": chunk_id,
                                    "quote_start": 0,
                                    "quote_end": len(quote),
                                    "quote_text": quote,
                                }
                            ],
                            "confidence": 0.88,
                            "reality_layer": "PRIMARY",
                        },
                        {
                            "proposal_id": "event-console-2",
                            "event_type": "second_event",
                            "summary": "门后异响",
                            "participant_ids": [],
                            "actor_resolution_status": "UNKNOWN",
                            "location_id": None,
                            "evidence_refs": [
                                {
                                    "chunk_id": chunk_id,
                                    "quote_start": 1,
                                    "quote_end": len(quote),
                                    "quote_text": quote[1:],
                                }
                            ],
                            "confidence": 0.76,
                            "reality_layer": "PRIMARY",
                        },
                    ],
                }
            )

        if output_model is EntityProposalBatchV1:
            return output_model.model_validate(
                {
                    "batch_id": "entity-batch-console-1",
                    "entities": [
                        {
                            "proposal_id": "entity-console-1",
                            "entity_type": "CHARACTER",
                            "canonical_name": "林夏",
                            "aliases": ["秘密别名"],
                            "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
                            "confidence": 0.78,
                        },
                        {
                            "proposal_id": "entity-console-2",
                            "entity_type": "ORGANIZATION",
                            "canonical_name": "旧馆社",
                            "aliases": [],
                            "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote[1:]}],
                            "confidence": 0.72,
                        },
                    ],
                }
            )

        if output_model is ClaimProposalBatchV1:
            return output_model.model_validate(
                {
                    "batch_id": "claim-batch-console-1",
                    "claims": [
                        {
                            "proposal_id": "claim-console-1",
                            "claim_type": "FACTUAL_ASSERTION",
                            "claim_text": "林夏推开门。",
                            "source_type": "NARRATOR",
                            "source_id": None,
                            "target_event_id": None,
                            "verification_status": "UNVERIFIED",
                            "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
                            "confidence": 0.68,
                            "reality_layer": "PRIMARY",
                            "temporal_scope": "PRESENT",
                        },
                        {
                            "proposal_id": "claim-console-2",
                            "claim_type": "INTERPRETATION",
                            "claim_text": "门后有异响。",
                            "source_type": "NARRATOR",
                            "source_id": None,
                            "target_event_id": None,
                            "verification_status": "UNVERIFIED",
                            "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote[1:]}],
                            "confidence": 0.61,
                            "reality_layer": "PRIMARY",
                            "temporal_scope": "PRESENT",
                        },
                    ],
                }
            )

        if output_model is KnowledgeStateProposalBatchV1:
            return output_model.model_validate(
                {
                    "batch_id": "knowledge-batch-console-1",
                    "states": [
                        {
                            "schema_version": "1.1",
                            "proposal_id": "knowledge-console-1",
                            "subject": {
                                "mention_text": "林夏",
                                "entity_proposal_id": None,
                                "resolution_status": "UNRESOLVED",
                            },
                            "target": {
                                "target_kind": "WORLD_FACT",
                                "target_text": "门后有路",
                                "proposal_id": None,
                                "proposal_schema": None,
                                "resolution_status": "UNRESOLVED",
                            },
                            "epistemic_status": "SUSPECTS",
                            "epistemic_basis": "INFERRED",
                            "reality_layer": "PRIMARY",
                            "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
                            "confidence": 0.71,
                        },
                        {
                            "schema_version": "1.1",
                            "proposal_id": "knowledge-console-2",
                            "subject": {
                                "mention_text": "陈野",
                                "entity_proposal_id": None,
                                "resolution_status": "UNRESOLVED",
                            },
                            "target": {
                                "target_kind": "WORLD_FACT",
                                "target_text": "钟声来自楼上",
                                "proposal_id": None,
                                "proposal_schema": None,
                                "resolution_status": "UNRESOLVED",
                            },
                            "epistemic_status": "HEARD",
                            "epistemic_basis": "HEARD",
                            "reality_layer": "PRIMARY",
                            "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote[1:]}],
                            "confidence": 0.72,
                        },
                    ],
                }
            )

        if output_model is StateChangeProposalBatchV1:
            return output_model.model_validate(
                {
                    "schema_version": "1.2",
                    "batch_id": "state-change-batch-console-1",
                    "changes": [
                        {
                            "schema_version": "1.2",
                            "proposal_id": "state-change-console-1",
                            "event": {
                                "event_summary": "林夏推开门",
                                "event_proposal_id": None,
                                "proposal_schema": None,
                                "resolution_status": "UNRESOLVED",
                            },
                            "target": {
                                "mention_text": "门",
                                "target_kind": "OBJECT",
                                "entity_proposal_id": None,
                                "proposal_schema": None,
                                "resolution_status": "UNRESOLVED",
                            },
                            "attribute_path": "accessibility",
                            "old_value": None,
                            "new_value": "开启",
                            "persistent": False,
                            "reality_layer": "PRIMARY",
                            "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
                            "new_value_evidence_indexes": [0],
                            "persistence_evidence_indexes": [],
                            "confidence": 0.83,
                        }
                    ],
                }
            )

        if output_model is RelationshipSignalProposalBatchV1:
            return output_model.model_validate(
                {
                    "schema_version": "1.0",
                    "batch_id": "relationship-signal-batch-console-1",
                    "signals": [],
                }
            )

        raise AssertionError(f"Unexpected output model: {output_model}")


def create_test_client(
    tmp_path: Path,
    monkeypatch,
    *,
    enable_real_llm: bool,
    provider: FakeNarrativeProvider | None = None,
) -> TestClient:
    monkeypatch.setenv("ENABLE_REAL_LLM", "true" if enable_real_llm else "false")
    monkeypatch.setenv("LLM_API_KEY", "platform-secret-key")
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "false")
    get_settings.cache_clear()
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'narrative_api.db'}")
    app.state.narrative_analyst_provider = provider
    return TestClient(app)


def setup_imported_project(client: TestClient) -> list[dict[str, Any]]:
    project_response = client.post("/projects", json=PROJECT_PAYLOAD)
    assert project_response.status_code == 201
    import_response = client.post(
        "/projects/demo-project/documents/import",
        files={"file": ("source.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")},
    )
    assert import_response.status_code == 201
    chapters_response = client.get("/projects/demo-project/chapters")
    assert chapters_response.status_code == 200
    chunks: list[dict[str, Any]] = []
    for chapter in chapters_response.json():
        chunks_response = client.get(f"/chapters/{chapter['chapter_id']}/chunks")
        assert chunks_response.status_code == 200
        chunks.extend(chunks_response.json())
    return chunks


def import_text_and_collect_chunks(
    client: TestClient,
    *,
    project_id: str,
    filename: str,
    text: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import_response = client.post(
        f"/projects/{project_id}/documents/import",
        files={"file": (filename, text.encode("utf-8"), "text/plain")},
    )
    assert import_response.status_code == 201
    import_payload = import_response.json()
    document_id = import_payload["document"]["document_id"]

    chapters_response = client.get(f"/projects/{project_id}/chapters")
    assert chapters_response.status_code == 200

    chunks: list[dict[str, Any]] = []
    for chapter in chapters_response.json():
        if chapter["document_id"] != document_id:
            continue
        chunks_response = client.get(f"/chapters/{chapter['chapter_id']}/chunks")
        assert chunks_response.status_code == 200
        chunks.extend(chunks_response.json())
    assert chunks
    return import_payload, chunks


@pytest.mark.parametrize(
    ("mode", "schema_name", "checklist_key"),
    [
        ("event_extraction", "EventProposalBatchV1", "events_cover_major_plot_points"),
        ("entity_extraction", "EntityProposalBatchV1", "entities_cover_major_entities"),
        ("claim_extraction", "ClaimProposalBatchV1", "claims_cover_major_claims"),
        (
            "knowledge_state_extraction",
            "KnowledgeStateProposalBatchV1",
            "knowledge_states_cover_explicit_epistemic_states",
        ),
    ],
)
def test_narrative_analyst_api_supports_implemented_modes(
    tmp_path: Path,
    monkeypatch,
    mode: str,
    schema_name: str,
    checklist_key: str,
) -> None:
    provider = FakeNarrativeProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": mode,
                    "chunk_ids": [chunks[0]["chunk_id"]],
                    "chunk_limit": 1,
                    "chunk_offset": 0,
                    "max_chars_per_chunk": 5,
                    "real_llm_requested": True,
                },
            )
            payload = response.json()
            detail_response = client.get(f"/agent-runs/{payload['agent_run_id']}")
            evidence_response = client.get(f"/agent-runs/{payload['agent_run_id']}/evidence")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 201
    for field in SUMMARY_FIELDS:
        assert field in payload
    assert payload["mode"] == mode
    assert payload["output_schema"] == schema_name
    assert payload["real_llm_called"] is True
    assert payload["agent_run_saved"] is True
    assert payload["agent_run_status"] == "SUCCEEDED"
    assert payload["provider_success"] is True
    assert payload["schema_validation_passed"] is True
    assert payload["evidence_validation_passed"] is True
    assert payload["quote_matched"] is True
    assert payload["proposal"] is not None
    assert payload["manual_review_checklist"][checklist_key] is None
    if mode == "event_extraction":
        assert payload["proposal"]["batch_id"] == "event-batch-console-1"
        assert len(payload["proposal"]["events"]) == 2
        assert payload["batch_id"] == "event-batch-console-1"
        assert payload["events_count"] == 2
        assert payload["event_proposal_ids"] == ["event-console-1", "event-console-2"]
        assert payload["primary_event_type"] == "demo_event"
        assert payload["primary_event_summary"] == "开门"
        assert payload["event_evidence_results"] == [
            {
                "proposal_id": "event-console-1",
                "event_type": "demo_event",
                "evidence_chunk_id": chunks[0]["chunk_id"],
                "quote_matched": True,
                "char_range_matched": True,
            },
            {
                "proposal_id": "event-console-2",
                "event_type": "second_event",
                "evidence_chunk_id": chunks[0]["chunk_id"],
                "quote_matched": True,
                "char_range_matched": True,
            },
        ]
        assert detail_response.json()["proposal"]["events"][1]["proposal_id"] == "event-console-2"
        assert detail_response.json()["output_proposal_ids"] == [
            "event-console-1",
            "event-console-2",
        ]
        assert len(evidence_response.json()["items"]) == 2
        assert evidence_response.json()["items"][0]["event_type"] == "demo_event"
    if mode == "entity_extraction":
        assert payload["proposal"]["batch_id"] == "entity-batch-console-1"
        assert len(payload["proposal"]["entities"]) == 2
        assert payload["batch_id"] == "entity-batch-console-1"
        assert payload["entities_count"] == 2
        assert payload["entity_proposal_ids"] == ["entity-console-1", "entity-console-2"]
        assert payload["entity_evidence_results"] == [
            {
                "proposal_id": "entity-console-1",
                "entity_type": "CHARACTER",
                "creature_subtype": None,
                "evidence_chunk_id": chunks[0]["chunk_id"],
                "quote_matched": True,
                "char_range_matched": None,
            },
            {
                "proposal_id": "entity-console-2",
                "entity_type": "ORGANIZATION",
                "creature_subtype": None,
                "evidence_chunk_id": chunks[0]["chunk_id"],
                "quote_matched": True,
                "char_range_matched": None,
            },
        ]
        assert detail_response.json()["output_proposal_ids"] == [
            "entity-console-1",
            "entity-console-2",
        ]
        assert len(evidence_response.json()["items"]) == 2
        assert evidence_response.json()["items"][0]["entity_type"] == "CHARACTER"
    if mode == "claim_extraction":
        assert payload["proposal"]["batch_id"] == "claim-batch-console-1"
        assert len(payload["proposal"]["claims"]) == 2
        assert payload["batch_id"] == "claim-batch-console-1"
        assert payload["claims_count"] == 2
        assert payload["claim_proposal_ids"] == ["claim-console-1", "claim-console-2"]
        assert payload["claim_evidence_results"] == [
            {
                "proposal_id": "claim-console-1",
                "claim_type": "FACTUAL_ASSERTION",
                "source_type": "NARRATOR",
                "temporal_scope": "PRESENT",
                "evidence_chunk_id": chunks[0]["chunk_id"],
                "quote_matched": True,
                "char_range_matched": None,
            },
            {
                "proposal_id": "claim-console-2",
                "claim_type": "INTERPRETATION",
                "source_type": "NARRATOR",
                "temporal_scope": "PRESENT",
                "evidence_chunk_id": chunks[0]["chunk_id"],
                "quote_matched": True,
                "char_range_matched": None,
            },
        ]
        assert detail_response.json()["output_proposal_ids"] == [
            "claim-console-1",
            "claim-console-2",
        ]
        assert len(evidence_response.json()["items"]) == 2
        assert evidence_response.json()["items"][0]["claim_type"] == "FACTUAL_ASSERTION"
        assert evidence_response.json()["items"][0]["source_type"] == "NARRATOR"
        assert evidence_response.json()["items"][0]["temporal_scope"] == "PRESENT"
    if mode == "knowledge_state_extraction":
        assert payload["proposal"]["batch_id"] == "knowledge-batch-console-1"
        assert len(payload["proposal"]["states"]) == 2
        assert payload["batch_id"] == "knowledge-batch-console-1"
        assert payload["states_count"] == 2
        assert payload["state_proposal_ids"] == ["knowledge-console-1", "knowledge-console-2"]
        assert detail_response.json()["output_proposal_ids"] == [
            "knowledge-console-1",
            "knowledge-console-2",
        ]
        assert len(evidence_response.json()["items"]) == 2
        assert evidence_response.json()["items"][0]["epistemic_status"] == "SUSPECTS"
        assert evidence_response.json()["items"][0]["subject_resolution_status"] == "UNRESOLVED"
        assert evidence_response.json()["items"][0]["target_resolution_status"] == "UNRESOLVED"
    assert detail_response.status_code == 200
    assert evidence_response.status_code == 200
    assert evidence_response.json()["items"]
    assert provider.calls == 1


def test_narrative_analyst_api_treats_an_empty_knowledge_batch_as_success(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeEmptyKnowledgeProvider(FakeNarrativeProvider):
        def structured_generate(
            self,
            request: dict[str, object],
            output_model: type[OutputModelT],
        ) -> OutputModelT:
            self.calls += 1
            self.requests.append(request)
            assert output_model is KnowledgeStateProposalBatchV1
            return output_model.model_validate({"batch_id": "knowledge-batch-empty", "states": []})

    provider = FakeEmptyKnowledgeProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "knowledge_state_extraction",
                    "chunk_ids": [chunks[0]["chunk_id"]],
                    "chunk_limit": 1,
                    "real_llm_requested": True,
                },
            )
            payload = response.json()
            detail = client.get(f"/agent-runs/{payload['agent_run_id']}")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 201
    assert payload["agent_run_status"] == "SUCCEEDED"
    assert payload["states_count"] == 0
    assert payload["state_proposal_ids"] == []
    assert payload["evidence_validation_passed"] is True
    assert payload["quote_matched"] is None
    assert detail.json()["output_proposal_ids"] == []


def test_narrative_analyst_api_event_batch_quote_mismatch_is_classified(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeBatchMismatchProvider(FakeNarrativeProvider):
        def structured_generate(
            self,
            request: dict[str, object],
            output_model: type[OutputModelT],
        ) -> OutputModelT:
            self.calls += 1
            input_context = request["input_context"]
            assert isinstance(input_context, dict)
            source_chunks = input_context["source_chunks"]
            assert isinstance(source_chunks, list)
            source_chunk = source_chunks[0]
            assert isinstance(source_chunk, dict)
            if output_model is EventProposalBatchV1:
                return output_model.model_validate(
                    {
                        "batch_id": "event-batch-mismatch",
                        "events": [
                            {
                                "proposal_id": "event-ok",
                                "event_type": "demo_event",
                                "summary": "开门",
                                "participant_ids": [],
                                "actor_resolution_status": "UNKNOWN",
                                "location_id": None,
                                "evidence_refs": [
                                    {"chunk_id": source_chunk["chunk_id"], "quote_text": "林夏"}
                                ],
                                "confidence": 0.7,
                                "reality_layer": "PRIMARY",
                            },
                            {
                                "proposal_id": "event-bad",
                                "event_type": "bad_event",
                                "summary": "不存在事件",
                                "participant_ids": [],
                                "actor_resolution_status": "UNKNOWN",
                                "location_id": None,
                                "evidence_refs": [
                                    {
                                        "chunk_id": source_chunk["chunk_id"],
                                        "quote_text": "not present in visible input",
                                    }
                                ],
                                "confidence": 0.7,
                                "reality_layer": "PRIMARY",
                            },
                        ],
                    }
                )
            raise AssertionError(f"Unexpected output model: {output_model}")

    provider = FakeBatchMismatchProvider(max_text_length=80)
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "event_extraction",
                    "chunk_ids": [chunks[0]["chunk_id"]],
                    "max_chars_per_chunk": 80,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    summary_only = dict(payload)
    summary_only.pop("proposal", None)
    summary_only.pop("manual_review_checklist", None)
    serialized_summary = json.dumps(summary_only, ensure_ascii=False)
    assert response.status_code == 201
    assert payload["events_count"] == 2
    assert payload["evidence_validation_passed"] is False
    assert payload["quote_matched"] is False
    assert payload["failure_category"] == "QUOTE_NOT_MATCHED"
    assert payload["event_evidence_results"][1]["quote_matched"] is False
    assert "not present in visible input" not in serialized_summary


@pytest.mark.parametrize(
    ("mode", "output_model", "batch_payload", "count_key", "results_key"),
    [
        (
            "entity_extraction",
            EntityProposalBatchV1,
            {
                "batch_id": "entity-batch-mismatch",
                "entities": [
                    {
                        "proposal_id": "entity-ok",
                        "entity_type": "CHARACTER",
                        "canonical_name": "林夏",
                        "aliases": [],
                        "evidence_refs": [{"chunk_id": "chunk-id", "quote_text": "林夏"}],
                        "confidence": 0.7,
                    },
                    {
                        "proposal_id": "entity-bad",
                        "entity_type": "LOCATION",
                        "canonical_name": "不存在地点",
                        "aliases": [],
                        "evidence_refs": [
                            {"chunk_id": "chunk-id", "quote_text": "not present in visible input"}
                        ],
                        "confidence": 0.7,
                    },
                ],
            },
            "entities_count",
            "entity_evidence_results",
        ),
        (
            "claim_extraction",
            ClaimProposalBatchV1,
            {
                "batch_id": "claim-batch-mismatch",
                "claims": [
                    {
                        "proposal_id": "claim-ok",
                        "claim_type": "FACTUAL_ASSERTION",
                        "claim_text": "林夏推开门。",
                        "source_type": "NARRATOR",
                        "source_id": None,
                        "target_event_id": None,
                        "verification_status": "UNVERIFIED",
                        "evidence_refs": [{"chunk_id": "chunk-id", "quote_text": "林夏"}],
                        "confidence": 0.7,
                        "reality_layer": "PRIMARY",
                        "temporal_scope": "PRESENT",
                    },
                    {
                        "proposal_id": "claim-bad",
                        "claim_type": "DENIAL",
                        "claim_text": "不存在主张。",
                        "source_type": "NARRATOR",
                        "source_id": None,
                        "target_event_id": None,
                        "verification_status": "UNVERIFIED",
                        "evidence_refs": [
                            {"chunk_id": "chunk-id", "quote_text": "not present in visible input"}
                        ],
                        "confidence": 0.7,
                        "reality_layer": "PRIMARY",
                        "temporal_scope": "PRESENT",
                    },
                ],
            },
            "claims_count",
            "claim_evidence_results",
        ),
    ],
)
def test_narrative_analyst_api_entity_and_claim_batch_quote_mismatch_is_classified(
    tmp_path: Path,
    monkeypatch,
    mode: str,
    output_model: type[BaseModel],
    batch_payload: dict[str, object],
    count_key: str,
    results_key: str,
) -> None:
    class FakeBatchMismatchProvider(FakeNarrativeProvider):
        def structured_generate(
            self,
            request: dict[str, object],
            requested_output_model: type[OutputModelT],
        ) -> OutputModelT:
            self.calls += 1
            input_context = request["input_context"]
            assert isinstance(input_context, dict)
            source_chunks = input_context["source_chunks"]
            assert isinstance(source_chunks, list)
            source_chunk = source_chunks[0]
            assert isinstance(source_chunk, dict)
            assert requested_output_model is output_model
            payload = json.loads(json.dumps(batch_payload))
            collection_key = "entities" if "entities" in payload else "claims"
            for item in payload[collection_key]:
                item["evidence_refs"][0]["chunk_id"] = source_chunk["chunk_id"]
            return requested_output_model.model_validate(payload)

    provider = FakeBatchMismatchProvider(max_text_length=80)
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": mode,
                    "chunk_ids": [chunks[0]["chunk_id"]],
                    "max_chars_per_chunk": 80,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    summary_only = dict(payload)
    summary_only.pop("proposal", None)
    summary_only.pop("manual_review_checklist", None)
    serialized_summary = json.dumps(summary_only, ensure_ascii=False)
    assert response.status_code == 201
    assert payload[count_key] == 2
    assert payload["evidence_validation_passed"] is False
    assert payload["quote_matched"] is False
    assert payload["failure_category"] == "QUOTE_NOT_MATCHED"
    assert payload[results_key][1]["quote_matched"] is False
    assert "not present in visible input" not in serialized_summary


def test_narrative_analyst_api_claim_summary_is_sanitized_but_proposal_is_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeNarrativeProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "claim_extraction",
                    "chunk_ids": [chunks[0]["chunk_id"]],
                    "max_chars_per_chunk": 5,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert response.status_code == 201
    assert "claim_text" not in {key for key in payload if key != "proposal"}
    assert payload["claims_count"] == 2
    assert payload["proposal"]["claims"][0]["claim_text"] == "林夏推开门。"
    assert "platform-secret-key" not in serialized
    assert "message.content" not in serialized
    assert "raw provider" not in serialized
    assert "林夏推开门。\n\n陈野把伞递给林夏。" not in serialized


def test_narrative_analyst_api_normalizes_unique_claim_evidence_across_three_chunks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeGlobalOffsetProvider:
        def structured_generate(
            self,
            request: dict[str, object],
            output_model: type[OutputModelT],
        ) -> OutputModelT:
            input_context = request["input_context"]
            assert isinstance(input_context, dict)
            source_chunks = input_context["source_chunks"]
            assert isinstance(source_chunks, list)
            assert output_model is ClaimProposalBatchV1
            second_chunk = source_chunks[1]
            assert isinstance(second_chunk, dict)
            return output_model.model_validate(
                {
                    "batch_id": "claim-batch-normalized",
                    "claims": [
                        {
                            "proposal_id": "claim-normalized",
                            "claim_type": "FACTUAL_ASSERTION",
                            "claim_text": "A source states the unique claim.",
                            "temporal_scope": "PRESENT",
                            "source_type": "NARRATOR",
                            "source_id": None,
                            "target_event_id": None,
                            "verification_status": "UNVERIFIED",
                            "evidence_refs": [
                                {
                                    "chunk_id": "incorrect-source-chunk",
                                    "quote_start": 999,
                                    "quote_end": 1017,
                                    "quote_text": "UNIQUE_TARGET_CLAIM",
                                }
                            ],
                            "confidence": 0.8,
                            "reality_layer": "PRIMARY",
                        }
                    ],
                }
            )

    provider = FakeGlobalOffsetProvider()
    source_text = (
        "Chapter 1\n\nFIRST_CHUNK_ONLY.\n\n"
        "SECOND_CHUNK UNIQUE_TARGET_CLAIM appears here.\n\n"
        "THIRD_CHUNK_ONLY."
    )
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            project_response = client.post("/projects", json=PROJECT_PAYLOAD)
            assert project_response.status_code == 201
            _, chunks = import_text_and_collect_chunks(
                client,
                project_id="demo-project",
                filename="three_chunks.txt",
                text=source_text,
            )
            assert len(chunks) == 3
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "claim_extraction",
                    "chunk_ids": [chunk["chunk_id"] for chunk in chunks],
                    "max_chars_per_chunk": 80,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    evidence = payload["proposal"]["claims"][0]["evidence_refs"][0]
    assert response.status_code == 201
    assert evidence["chunk_id"] == chunks[1]["chunk_id"]
    assert evidence["quote_start"] == 13
    assert evidence["quote_end"] == 32
    assert payload["evidence_validation_passed"] is True
    assert payload["quote_matched"] is True
    assert payload["char_range_matched"] is True
    assert payload["evidence_normalization"] == {
        "rebound_chunk_ids": 1,
        "rebased_quote_ranges": 1,
        "cleared_quote_ranges": 0,
    }


def test_narrative_analyst_api_entity_summary_counts_aliases_without_listing_them(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeNarrativeProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "entity_extraction",
                    "chunk_ids": [chunks[0]["chunk_id"]],
                    "max_chars_per_chunk": 5,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    assert response.status_code == 201
    assert payload["entities_count"] == 2
    assert "aliases" not in {key for key in payload if key != "proposal"}
    assert payload["proposal"]["entities"][0]["aliases"] == ["秘密别名"]


def test_narrative_analyst_api_respects_explicit_chunk_ids_after_multiple_imports(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeNarrativeProvider(max_text_length=80)
    old_text = "Chapter 1\n\nOLD_SOURCE_ALPHA should never reach the provider."
    new_text = (
        "Chapter 1\n\n"
        "NEW_SOURCE_BETA selected current import preview stays short and safe "
        "with additional words beyond the preview budget."
    )
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            project_response = client.post("/projects", json=PROJECT_PAYLOAD)
            assert project_response.status_code == 201
            _, old_chunks = import_text_and_collect_chunks(
                client,
                project_id="demo-project",
                filename="old_source.txt",
                text=old_text,
            )
            _, new_chunks = import_text_and_collect_chunks(
                client,
                project_id="demo-project",
                filename="new_source.txt",
                text=new_text,
            )

            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "event_extraction",
                    "chunk_ids": [new_chunks[0]["chunk_id"]],
                    "chunk_limit": 1,
                    "chunk_offset": 0,
                    "max_chars_per_chunk": 80,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    provider_context = provider.requests[0]["input_context"]
    assert isinstance(provider_context, dict)
    provider_chunks = provider_context["source_chunks"]
    assert isinstance(provider_chunks, list)
    assert response.status_code == 201
    assert provider.calls == 1
    assert payload["context_chunk_ids"] == [new_chunks[0]["chunk_id"]]
    assert payload["selected_chunk_metadata"][0]["chunk_id"] == new_chunks[0]["chunk_id"]
    assert payload["selected_chunk_metadata"][0]["document_id"] == new_chunks[0]["document_id"]
    assert payload["selected_chunk_metadata"][0]["chapter_id"] == new_chunks[0]["chapter_id"]
    assert payload["selected_chunk_metadata"][0]["chapter_title"] == "Chapter 1"
    assert payload["selected_chunk_metadata"][0]["preview"].startswith(
        "NEW_SOURCE_BETA selected current import"
    )
    assert len(payload["selected_chunk_metadata"][0]["preview"]) <= 60
    assert payload["selected_chunk_metadata"][0]["preview_length"] <= 60
    assert payload["selected_chunk_metadata"][0]["text_length"] == len(new_chunks[0]["text"])
    assert "NEW_SOURCE_BETA" in str(provider_chunks[0]["text"])
    assert new_chunks[0]["text"] not in json.dumps(payload, ensure_ascii=False)
    assert old_chunks[0]["chunk_id"] not in payload["context_chunk_ids"]
    assert "OLD_SOURCE_ALPHA" not in json.dumps(provider.requests, ensure_ascii=False)


def test_narrative_analyst_api_rejects_cross_project_chunk_id_without_provider_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeNarrativeProvider(max_text_length=80)
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            project_a = client.post(
                "/projects",
                json={"project_id": "project-a", "name": "Project A"},
            )
            project_b = client.post(
                "/projects",
                json={"project_id": "project-b", "name": "Project B"},
            )
            assert project_a.status_code == 201
            assert project_b.status_code == 201
            _, project_a_chunks = import_text_and_collect_chunks(
                client,
                project_id="project-a",
                filename="project_a.txt",
                text="Chapter 1\n\nPROJECT_A_ONLY chunk text.",
            )

            response = client.post(
                "/projects/project-b/agent-runs/narrative-analyst",
                json={
                    "mode": "event_extraction",
                    "chunk_ids": [project_a_chunks[0]["chunk_id"]],
                    "max_chars_per_chunk": 80,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code in {400, 404}
    assert provider.calls == 0
    serialized = json.dumps(response.json(), ensure_ascii=False)
    assert "PROJECT_A_ONLY" not in serialized
    assert "platform-secret-key" not in serialized
    assert "message.content" not in serialized


def test_narrative_analyst_api_offset_fallback_returns_selected_chunk_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeNarrativeProvider(max_text_length=80)
    first_text = "Chapter 1\n\nFIRST_IMPORT_ALPHA appears first by project order."
    second_text = (
        "Chapter 1\n\n"
        "SECOND_IMPORT_BETA selected fallback preview stays short and safe "
        "with additional words beyond the preview budget."
    )
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            project_response = client.post("/projects", json=PROJECT_PAYLOAD)
            assert project_response.status_code == 201
            first_import, first_chunks = import_text_and_collect_chunks(
                client,
                project_id="demo-project",
                filename="first_source.txt",
                text=first_text,
            )
            second_import, second_chunks = import_text_and_collect_chunks(
                client,
                project_id="demo-project",
                filename="second_source.txt",
                text=second_text,
            )

            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "event_extraction",
                    "chunk_limit": 1,
                    "chunk_offset": 1,
                    "max_chars_per_chunk": 80,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert response.status_code == 201
    assert payload["context_chunk_ids"] == [second_chunks[0]["chunk_id"]]
    assert payload["selected_chunk_metadata"][0]["chunk_id"] == second_chunks[0]["chunk_id"]
    assert payload["selected_chunk_metadata"][0]["preview"].startswith(
        "SECOND_IMPORT_BETA selected fallback preview"
    )
    assert len(payload["selected_chunk_metadata"][0]["preview"]) <= 60
    assert first_chunks[0]["text"] not in serialized
    assert second_chunks[0]["text"] not in serialized
    assert first_import["document"]["document_id"] != second_import["document"]["document_id"]
    assert "raw provider" not in serialized
    assert "message.content" not in serialized
    assert "platform-secret-key" not in serialized
    assert provider.calls == 1


def test_narrative_analyst_api_unknown_mode_returns_400_without_provider_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeNarrativeProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "unknown_mode",
                    "chunk_limit": 1,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 400
    assert "Unsupported NarrativeAnalyst mode" in response.json()["detail"]
    assert provider.calls == 0


def test_narrative_analyst_api_runs_state_change_batch_with_fake_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeNarrativeProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "state_change_extraction",
                    "chunk_limit": 1,
                    "max_chars_per_chunk": 5,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    assert response.status_code == 201
    assert payload["output_schema"] == "StateChangeProposalBatchV1"
    assert payload["error_message"] is None
    assert payload["agent_run_status"] == "SUCCEEDED"
    assert payload["changes_count"] == 1
    assert payload["change_proposal_ids"] == ["state-change-console-1"]
    assert payload["agent_run_status"] == "SUCCEEDED"
    assert provider.calls == 1


def test_narrative_analyst_api_runs_relationship_signal_empty_batch_with_fake_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeNarrativeProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "relationship_signal_extraction",
                    "chunk_limit": 1,
                    "max_chars_per_chunk": 5,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    assert response.status_code == 201
    assert payload["output_schema"] == "RelationshipSignalProposalBatchV1"
    assert payload["agent_run_status"] == "SUCCEEDED"
    assert payload["relationship_signals_count"] == 0
    assert payload["relationship_signal_proposal_ids"] == []
    assert provider.calls == 1


def test_narrative_analyst_api_rejects_chunk_limit_over_three(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeNarrativeProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "event_extraction",
                    "chunk_limit": 4,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 400
    assert "chunk_limit cannot exceed 3" in response.json()["detail"]
    assert provider.calls == 0


def test_narrative_analyst_api_dry_run_does_not_call_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeNarrativeProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "event_extraction",
                    "chunk_ids": [chunks[0]["chunk_id"]],
                    "max_chars_per_chunk": 5,
                    "real_llm_requested": False,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    assert response.status_code == 201
    assert payload["dry_run"] is True
    assert payload["real_llm_called"] is False
    assert payload["agent_run_saved"] is False
    assert payload["proposal"] is None
    assert provider.calls == 0


def test_narrative_analyst_api_real_request_requires_enabled_setting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeNarrativeProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=False,
            provider=provider,
        ) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "claim_extraction",
                    "chunk_ids": [chunks[0]["chunk_id"]],
                    "max_chars_per_chunk": 5,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    assert response.status_code == 201
    assert payload["agent_run_status"] == "FAILED"
    assert payload["real_llm_called"] is False
    assert payload["provider_success"] is False
    assert payload["agent_run_saved"] is True
    assert "ENABLE_REAL_LLM is false" in payload["error_message"]
    assert provider.calls == 0


def test_narrative_analyst_api_entity_timeout_keeps_requested_mode_and_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeEntityTimeoutProvider(FakeNarrativeProvider):
        def structured_generate(
            self,
            request: dict[str, object],
            output_model: type[OutputModelT],
        ) -> OutputModelT:
            self.calls += 1
            assert output_model is EntityProposalBatchV1
            raise TimeoutError("LLM provider timeout")

    provider = FakeEntityTimeoutProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "entity_extraction",
                    "chunk_ids": [chunks[0]["chunk_id"]],
                    "max_chars_per_chunk": 5,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert response.status_code == 201
    assert payload["mode"] == "entity_extraction"
    assert payload["output_schema"] == "EntityProposalBatchV1"
    assert payload["agent_run_status"] == "FAILED"
    assert payload["provider_success"] is False
    assert payload["failure_category"] == "PROVIDER_TIMEOUT"
    assert payload["proposal"] is None
    assert provider.calls == 1
    assert "EventProposalBatchV1" not in serialized
    assert "platform-secret-key" not in serialized
    assert "message.content" not in serialized


def test_narrative_analyst_api_can_select_chunks_from_project_offset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeNarrativeProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=True,
            provider=provider,
        ) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/narrative-analyst",
                json={
                    "mode": "event_extraction",
                    "chunk_limit": 1,
                    "chunk_offset": 1,
                    "max_chars_per_chunk": 5,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    assert response.status_code == 201
    assert payload["context_chunk_ids"] == [chunks[1]["chunk_id"]]
    assert provider.calls == 1
