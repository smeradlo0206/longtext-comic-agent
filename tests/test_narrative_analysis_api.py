"""API contracts for whole-document NarrativeAnalyst tasks."""

from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.config import get_settings
from comic_agent.main import create_app
from comic_agent.workflows.narrative_analyst_workflow import NarrativeAnalystWorkflow


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("ENABLE_REAL_LLM", "false")
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "false")
    get_settings.cache_clear()
    return TestClient(create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'analysis_api.db'}"))


def _import_document(client: TestClient) -> str:
    created = client.post(
        "/projects", json={"project_id": "project-1", "name": "Synthetic Project"}
    )
    assert created.status_code == 201
    imported = client.post(
        "/projects/project-1/documents/import",
        files={"file": ("synthetic.txt", b"Chapter 1\n\nSynthetic sentence.", "text/plain")},
    )
    assert imported.status_code == 201
    return imported.json()["document"]["document_id"]


def test_whole_document_analysis_api_is_dry_run_by_default_and_sanitized(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    document_id = _import_document(client)

    documents = client.get("/projects/project-1/documents")
    assert documents.status_code == 200
    assert documents.json() == [
        {
            "document_id": document_id,
            "filename": "synthetic.txt",
            "revision": 1,
        }
    ]

    created = client.post(
        f"/projects/project-1/documents/{document_id}/narrative-analysis-runs",
        json={"modes": ["event_extraction", "entity_extraction"]},
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["document_id"] == document_id
    assert payload["real_llm_requested"] is False
    assert payload["concurrency"] == 1
    assert payload["windows_total"] == 2
    assert "text" not in payload
    assert "raw_output" not in payload
    run_id = payload["analysis_run_id"]

    progress = client.get(f"/narrative-analysis-runs/{run_id}")
    result = client.get(f"/narrative-analysis-runs/{run_id}/result")
    resumed = client.post(f"/narrative-analysis-runs/{run_id}/resume")

    assert progress.status_code == 200
    assert progress.json()["status"] == "SUCCEEDED"
    assert progress.json()["windows_succeeded"] == 2
    assert progress.json()["windows_failed"] == 0
    assert result.status_code == 200
    assert result.json()["events"] == []
    assert "Synthetic sentence." not in result.text
    assert resumed.status_code == 202


def test_whole_document_analysis_api_rejects_manual_chunk_ids(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    document_id = _import_document(client)

    response = client.post(
        f"/projects/project-1/documents/{document_id}/narrative-analysis-runs",
        json={"modes": ["event_extraction"], "chunk_ids": ["chunk-should-not-be-accepted"]},
    )

    assert response.status_code == 422


def test_whole_document_analysis_rejects_real_request_when_server_llm_is_disabled(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    document_id = _import_document(client)

    response = client.post(
        f"/projects/project-1/documents/{document_id}/narrative-analysis-runs",
        json={"modes": ["event_extraction"], "real_llm_requested": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Real LLM is disabled by server settings; restart the API with ENABLE_REAL_LLM=true"
    )


class _FakeEventProvider:
    def __init__(self) -> None:
        self.calls = 0

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        self.calls += 1
        context = request["input_context"]
        assert isinstance(context, dict)
        chunks = context["source_chunks"]
        assert isinstance(chunks, list)
        first_chunk = chunks[0]
        assert isinstance(first_chunk, dict)
        return output_model.model_validate(
            {
                "batch_id": "event-batch-whole-1",
                "events": [
                    {
                        "proposal_id": "event-whole-1",
                        "event_type": "synthetic_action",
                        "summary": "Synthetic action",
                        "participant_ids": [],
                        "actor_resolution_status": "UNKNOWN",
                        "evidence_refs": [
                            {
                                "chunk_id": first_chunk["chunk_id"],
                                "quote_text": "Synthetic",
                            }
                        ],
                        "confidence": 0.8,
                        "reality_layer": "PRIMARY",
                    }
                ],
            }
        )


def test_whole_document_worker_uses_the_same_injected_provider_as_manual_mode(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ENABLE_REAL_LLM", "true")
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "false")
    get_settings.cache_clear()
    provider = _FakeEventProvider()
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'analysis_provider_api.db'}")
    app.state.narrative_analyst_provider = provider
    client = TestClient(app)
    document_id = _import_document(client)

    monkeypatch.setattr(
        NarrativeAnalystWorkflow,
        "_build_provider",
        lambda _: (_ for _ in ()).throw(AssertionError("unexpected provider fallback")),
    )
    created = client.post(
        f"/projects/project-1/documents/{document_id}/narrative-analysis-runs",
        json={"modes": ["event_extraction"], "real_llm_requested": True},
    )

    assert created.status_code == 201
    run_id = created.json()["analysis_run_id"]
    progress = client.get(f"/narrative-analysis-runs/{run_id}")
    result = client.get(f"/narrative-analysis-runs/{run_id}/result")
    windows = client.get(f"/narrative-analysis-runs/{run_id}/windows")

    assert provider.calls == 1
    assert progress.json()["status"] == "SUCCEEDED"
    assert result.json()["events"][0]["agent_run_ids"]
    assert windows.status_code == 200
    window = windows.json()["items"][0]
    assert window["agent_run_id"] == result.json()["events"][0]["agent_run_ids"][0]
    assert window["attempt_count"] == 1
    assert window["effective_max_chars_per_chunk"] == 1200
    assert window["previous_failure_category"] is None
    assert "Synthetic sentence." not in windows.text
    assert "raw_output" not in windows.text
