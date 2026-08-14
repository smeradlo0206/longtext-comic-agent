"""End-to-end automatic import and Gate 1 routing tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.main import create_app

PROJECT_PAYLOAD = {
    "id": "gate-project",
    "name": "Gate Project",
    "project_type": "LONG_NOVEL",
    "fidelity_mode": "CANON_STRICT",
    "output_format": "PAGES",
    "reading_direction": "LTR",
    "allow_new_events": False,
    "allow_new_dialogue": False,
    "allow_event_reordering": False,
    "allow_visual_compression": True,
    "allow_dialogue_splitting": True,
    "require_source_traceability": True,
    "max_auto_repairs": 3,
    "budget_limit": 100,
}

TEXT = "第一章 开始\n\n林夏走进门边。\n\n第二章 转折\n\n陈野打开了门。\n"


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'gate.db'}"))


def test_import_runs_gate1_before_persisting_and_returns_selection_data(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.post("/projects", json=PROJECT_PAYLOAD).status_code == 201
        response = client.post(
            "/projects/gate-project/documents/import",
            files={"file": ("source.txt", TEXT.encode("utf-8"), "text/plain")},
        )

        payload = response.json()
        document_id = payload["document"]["document_id"]
        selection = client.get(
            f"/projects/gate-project/documents/{document_id}/narrative-analysis-chapters"
        )

    assert response.status_code == 201
    assert payload["gate1"]["decision"] == "APPROVED"
    assert payload["gate1"]["routing_advice"]["action"] == "CONTINUE_TO_CONTEXT_BUILDER"
    assert payload["approved_chunk_bundle"]["chunk_ids"]
    assert selection.status_code == 200
    selection_payload = selection.json()
    assert selection_payload["eligible"] is True
    assert len(selection_payload["chapters"]) == 2
    assert all(
        chapter["available_chunk_count"] == chapter["chunk_count"]
        for chapter in selection_payload["chapters"]
    )


def test_gate1_rejection_does_not_persist_document_or_expose_source_text(tmp_path: Path) -> None:
    bad_text = "第一章\n\n正常段落。\ufffd\n"
    with _client(tmp_path) as client:
        assert client.post("/projects", json=PROJECT_PAYLOAD).status_code == 201
        response = client.post(
            "/projects/gate-project/documents/import",
            files={"file": ("bad.txt", bad_text.encode("utf-8"), "text/plain")},
        )
        documents = client.get("/projects/gate-project/documents")

    assert response.status_code == 422
    payload = response.json()
    assert payload["gate1"]["decision"] == "NEEDS_HUMAN_REVIEW"
    assert payload["gate1"]["routing_advice"]["action"] == "HOLD_FOR_HUMAN_REVIEW"
    assert bad_text not in response.text
    assert documents.json() == []


def test_same_approved_revision_import_is_idempotent(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.post("/projects", json=PROJECT_PAYLOAD).status_code == 201
        files = {"file": ("source.txt", TEXT.encode("utf-8"), "text/plain")}
        first = client.post("/projects/gate-project/documents/import", files=files)
        second = client.post(
            "/projects/gate-project/documents/import",
            files={"file": ("source.txt", TEXT.encode("utf-8"), "text/plain")},
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["status"] == "existing"
    assert second.json()["gate1"]["review_run_id"] == first.json()["gate1"]["review_run_id"]


def test_excessive_whitespace_import_is_review_blocked(tmp_path: Path) -> None:
    abnormal = "第一章 开始" + ("\n" * 5) + "正文。\n"
    with _client(tmp_path) as client:
        assert client.post("/projects", json=PROJECT_PAYLOAD).status_code == 201
        response = client.post(
            "/projects/gate-project/documents/import",
            files={"file": ("abnormal.txt", abnormal.encode("utf-8"), "text/plain")},
        )
        documents = client.get("/projects/gate-project/documents")

    assert response.status_code == 422
    payload = response.json()
    assert payload["gate1"]["decision"] == "NEEDS_HUMAN_REVIEW"
    assert payload["gate1"]["routing_advice"]["action"] == "HOLD_FOR_HUMAN_REVIEW"
    assert any(
        issue["code"] == "DOCUMENT_EXCESSIVE_WHITESPACE"
        and issue["severity"] == "REVIEW_REQUIRED"
        for issue in payload["gate1"]["issues"]
    )
    assert documents.json() == []
