import json
from pathlib import Path
from typing import TypeVar

from fastapi.testclient import TestClient
from pydantic import BaseModel

from comic_agent.config import get_settings
from comic_agent.main import create_app

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)

PROJECT_PAYLOAD = {"project_id": "demo-project", "name": "Demo Project"}
SAMPLE_TEXT = """第一章 开端

林夏推开门。

陈野把伞递给林夏。

钟声从楼上传来。

两人走向旧馆。
"""


class FakeEventProvider:
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
        chunk_id = str(input_context["source_chunk_ids"][0])  # type: ignore[index]
        chunk = input_context["source_chunks"][0]  # type: ignore[index]
        assert isinstance(chunk, dict)
        quote = str(chunk["text"])[:3]
        return output_model.model_validate(
            {
                "batch_id": "event-batch-demo-real-event",
                "events": [
                    {
                        "proposal_id": "proposal-demo-real-event",
                        "event_type": "demo_event",
                        "summary": "林夏推开门。",
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
                ],
            }
        )


def create_test_client(
    tmp_path: Path,
    monkeypatch,
    *,
    enable_real_llm: bool = True,
    require_access_code: bool = True,
    provider: FakeEventProvider | None = None,
) -> TestClient:
    monkeypatch.setenv("ENABLE_REAL_LLM", "true" if enable_real_llm else "false")
    monkeypatch.setenv("LLM_API_KEY", "platform-secret-key")
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", str(require_access_code).lower())
    monkeypatch.setenv("INTERNAL_DEMO_ACCESS_CODE", "secret-demo-code")
    get_settings.cache_clear()
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'real_event_demo.db'}")
    app.state.real_event_provider = provider
    return TestClient(app)


def setup_imported_project(client: TestClient) -> list[dict]:
    project_response = client.post("/projects", json=PROJECT_PAYLOAD)
    assert project_response.status_code == 201
    import_response = client.post(
        "/projects/demo-project/documents/import",
        files={"file": ("source.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")},
    )
    assert import_response.status_code == 201
    chapters_response = client.get("/projects/demo-project/chapters")
    assert chapters_response.status_code == 200
    chunks: list[dict] = []
    for chapter in chapters_response.json():
        chunks_response = client.get(f"/chapters/{chapter['chapter_id']}/chunks")
        assert chunks_response.status_code == 200
        chunks.extend(chunks_response.json())
    return chunks


def test_real_event_api_rejects_missing_access_code(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeEventProvider()
    try:
        with create_test_client(tmp_path, monkeypatch, provider=provider) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/real-event",
                json={"chunk_ids": [chunks[0]["chunk_id"]]},
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid demo access code"
    assert provider.calls == 0


def test_real_event_api_rejects_wrong_access_code(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeEventProvider()
    try:
        with create_test_client(tmp_path, monkeypatch, provider=provider) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/real-event",
                headers={"X-Demo-Access-Code": "wrong-code"},
                json={"chunk_ids": [chunks[0]["chunk_id"]]},
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 401
    assert provider.calls == 0


def test_real_event_api_limits_chunk_count_to_three(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeEventProvider()
    try:
        with create_test_client(tmp_path, monkeypatch, provider=provider) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/real-event",
                headers={"X-Demo-Access-Code": "secret-demo-code"},
                json={"chunk_ids": [chunk["chunk_id"] for chunk in chunks[:4]]},
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "real-event chunk_ids cannot exceed 3"
    assert provider.calls == 0


def test_real_event_api_returns_sanitized_success_with_fake_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeEventProvider()
    try:
        with create_test_client(tmp_path, monkeypatch, provider=provider) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/real-event",
                headers={"X-Demo-Access-Code": "secret-demo-code"},
                json={
                    "chunk_ids": [chunks[0]["chunk_id"]],
                    "api_key": "user-supplied-secret",
                },
            )
            runs_response = client.get("/projects/demo-project/agent-runs")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 201
    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["agent_run_status"] == "SUCCEEDED"
    assert payload["provider_success"] is True
    assert payload["output_schema"] == "EventProposalBatchV1"
    assert payload["schema_validation_passed"] is True
    assert payload["batch_id"] == "event-batch-demo-real-event"
    assert payload["events_count"] == 1
    assert payload["event_proposal_ids"] == ["proposal-demo-real-event"]
    assert payload["proposal_id"] == "proposal-demo-real-event"
    assert payload["confidence"] == 0.88
    assert payload["actor_resolution_status"] == "UNKNOWN"
    assert payload["evidence_validation_passed"] is True
    assert payload["evidence_chunk_id"] == chunks[0]["chunk_id"]
    assert payload["quote_matched"] is True
    assert payload["char_range_matched"] is True
    assert payload["error_message"] is None
    assert "platform-secret-key" not in serialized
    assert "user-supplied-secret" not in serialized
    assert "林夏推开门" not in serialized
    assert runs_response.status_code == 200
    assert "platform-secret-key" not in json.dumps(runs_response.json(), ensure_ascii=False)


def test_real_event_api_skips_access_code_when_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeEventProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            require_access_code=False,
            provider=provider,
        ) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/real-event",
                json={"chunk_ids": [chunks[0]["chunk_id"]]},
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 201
    assert response.json()["agent_run_status"] == "SUCCEEDED"
    assert provider.calls == 1


def test_real_event_api_disabled_llm_saves_failed_agent_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = FakeEventProvider()
    try:
        with create_test_client(
            tmp_path,
            monkeypatch,
            enable_real_llm=False,
            provider=provider,
        ) as client:
            chunks = setup_imported_project(client)
            response = client.post(
                "/projects/demo-project/agent-runs/real-event",
                headers={"X-Demo-Access-Code": "secret-demo-code"},
                json={"chunk_ids": [chunks[0]["chunk_id"]]},
            )
            agent_run_id = response.json()["agent_run_id"]
            detail_response = client.get(f"/agent-runs/{agent_run_id}")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 201
    assert response.json()["agent_run_status"] == "FAILED"
    assert response.json()["provider_success"] is False
    assert "disabled" in response.json()["error_message"]
    assert provider.calls == 0
    serialized_detail = json.dumps(detail_response.json(), ensure_ascii=False)
    assert "platform-secret-key" not in serialized_detail
