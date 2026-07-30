import json
from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.main import create_app

PROJECT_PAYLOAD = {"project_id": "demo-project", "name": "Demo Project"}
SAMPLE_TEXT = """第一章 开端

林夏把铜钥匙放在桌上。

第二章 追踪

陈野沿着楼梯跑向天台。
"""


def create_test_client(tmp_path: Path) -> TestClient:
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'agent_run_api.db'}")
    return TestClient(app)


def setup_imported_project(client: TestClient, project_id: str = "demo-project") -> list[dict]:
    project_response = client.post("/projects", json=PROJECT_PAYLOAD | {"project_id": project_id})
    assert project_response.status_code == 201
    import_response = client.post(
        f"/projects/{project_id}/documents/import",
        files={"file": ("source.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")},
    )
    assert import_response.status_code == 201
    chapters_response = client.get(f"/projects/{project_id}/chapters")
    assert chapters_response.status_code == 200
    chunks_response = client.get(f"/chapters/{chapters_response.json()[0]['chapter_id']}/chunks")
    assert chunks_response.status_code == 200
    return chunks_response.json()


def test_agent_run_list_returns_empty_items_for_project_without_runs(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        project_response = client.post("/projects", json=PROJECT_PAYLOAD)
        assert project_response.status_code == 201

        response = client.get("/projects/demo-project/agent-runs")

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_run_mock_event_workflow_creates_auditable_agent_run(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        chunks = setup_imported_project(client)

        response = client.post(
            "/projects/demo-project/agent-runs/mock-event",
            json={"chunk_ids": [chunks[0]["chunk_id"]]},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "SUCCEEDED"
    assert payload["proposal"]["proposal_id"]
    assert payload["proposal"]["actor_resolution_status"] == "UNKNOWN"
    assert payload["evidence_validation_passed"] is True
    assert payload["error_message"] is None


def test_mock_event_workflow_rejects_missing_chunk_without_real_llm(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        project_response = client.post("/projects", json=PROJECT_PAYLOAD)
        assert project_response.status_code == 201

        response = client.post(
            "/projects/demo-project/agent-runs/mock-event",
            json={"chunk_ids": ["missing-chunk"]},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Chunk not found"


def test_agent_run_list_filters_by_project_and_sanitizes_payload(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        project_1_chunks = setup_imported_project(client, "project-1")
        project_2_chunks = setup_imported_project(client, "project-2")
        run_1 = client.post(
            "/projects/project-1/agent-runs/mock-event",
            json={"chunk_ids": [project_1_chunks[0]["chunk_id"]]},
        )
        run_2 = client.post(
            "/projects/project-2/agent-runs/mock-event",
            json={"chunk_ids": [project_2_chunks[0]["chunk_id"]]},
        )
        assert run_1.status_code == 201
        assert run_2.status_code == 201

        response = client.get("/projects/project-1/agent-runs")

    assert response.status_code == 200
    items = response.json()["items"]
    serialized = json.dumps(items, ensure_ascii=False)
    assert len(items) == 1
    assert items[0]["project_id"] == "project-1"
    assert items[0]["provider_name"] == "mock-llm"
    assert items[0]["provider_type"] == "MOCK"
    assert items[0]["evidence_validation_passed"] is True
    assert "secret" not in serialized.lower()
    assert "林夏把铜钥匙放在桌上" not in serialized


def test_get_agent_run_detail_includes_proposal_but_not_api_key(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        chunks = setup_imported_project(client)
        run_response = client.post(
            "/projects/demo-project/agent-runs/mock-event",
            json={"chunk_ids": [chunks[0]["chunk_id"]]},
        )
        assert run_response.status_code == 201
        agent_run_id = run_response.json()["agent_run_id"]

        response = client.get(f"/agent-runs/{agent_run_id}")

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["agent_run_id"] == agent_run_id
    assert payload["provider_result"]["provider_name"] == "mock-llm"
    assert payload["proposal"]["evidence_refs"][0]["chunk_id"] == chunks[0]["chunk_id"]
    assert payload["evidence_validation_passed"] is True
    assert "secret" not in serialized.lower()
    assert "林夏把铜钥匙放在桌上" not in serialized


def test_get_missing_agent_run_returns_404(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.get("/agent-runs/missing-agent-run")

    assert response.status_code == 404
    assert response.json()["detail"] == "AgentRun not found"


def test_get_agent_run_evidence_returns_short_quotes_only(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        chunks = setup_imported_project(client)
        run_response = client.post(
            "/projects/demo-project/agent-runs/mock-event",
            json={"chunk_ids": [chunks[0]["chunk_id"]]},
        )
        assert run_response.status_code == 201
        agent_run_id = run_response.json()["agent_run_id"]

        response = client.get(f"/agent-runs/{agent_run_id}/evidence")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["chunk_id"] == chunks[0]["chunk_id"]
    assert items[0]["validation_status"] == "passed"
    assert len(items[0]["quote"]) <= 40
    assert items[0]["quote"] in chunks[0]["text"]
