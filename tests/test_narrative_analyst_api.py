import json
from pathlib import Path
from typing import Any, TypeVar

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from comic_agent.config import get_settings
from comic_agent.main import create_app
from comic_agent.schemas.narrative import ClaimProposalV1, EntityProposalV1, EventProposalV1

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
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[dict[str, object]] = []

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
        assert set(source_chunk) == {
            "chunk_id",
            "chapter_id",
            "char_start",
            "char_end",
            "text",
        }
        assert len(str(source_chunk["text"])) <= 5
        quote = str(source_chunk["text"])[:3]
        chunk_id = str(source_chunk["chunk_id"])

        if output_model is EventProposalV1:
            return output_model.model_validate(
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
                }
            )

        if output_model is EntityProposalV1:
            return output_model.model_validate(
                {
                    "proposal_id": "entity-console-1",
                    "entity_type": "CHARACTER",
                    "canonical_name": "林夏",
                    "aliases": ["秘密别名"],
                    "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
                    "confidence": 0.78,
                }
            )

        if output_model is ClaimProposalV1:
            return output_model.model_validate(
                {
                    "proposal_id": "claim-console-1",
                    "claim_type": "ASSERTION",
                    "claim_text": "林夏推开门。",
                    "source_type": "NARRATOR",
                    "source_id": None,
                    "target_event_id": None,
                    "verification_status": "UNVERIFIED",
                    "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote}],
                    "confidence": 0.68,
                    "reality_layer": "PRIMARY",
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


@pytest.mark.parametrize(
    ("mode", "schema_name", "checklist_key"),
    [
        ("event_extraction", "EventProposalV1", "is_event"),
        ("entity_extraction", "EntityProposalV1", "is_entity"),
        ("claim_extraction", "ClaimProposalV1", "is_claim"),
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
    assert detail_response.status_code == 200
    assert evidence_response.status_code == 200
    assert evidence_response.json()["items"]
    assert provider.calls == 1


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
    assert payload["proposal"]["claim_text"] == "林夏推开门。"
    assert "platform-secret-key" not in serialized
    assert "message.content" not in serialized
    assert "raw provider" not in serialized
    assert "林夏推开门。\n\n陈野把伞递给林夏。" not in serialized


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
    assert payload["aliases_count"] == 1
    assert "aliases" not in {key for key in payload if key != "proposal"}
    assert payload["proposal"]["aliases"] == ["秘密别名"]


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


def test_narrative_analyst_api_planned_mode_returns_400_without_provider_call(
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
                    "mode": "knowledge_state_extraction",
                    "chunk_limit": 1,
                    "real_llm_requested": True,
                },
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 400
    assert "not implemented" in response.json()["detail"]
    assert provider.calls == 0


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
