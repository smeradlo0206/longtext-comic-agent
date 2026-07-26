from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.main import create_app


PROJECT_PAYLOAD = {
    "id": "project-1",
    "name": "TXT Import Project",
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


SAMPLE_TEXT = """第一章 开端

林夏站在操场边，鞋尖沾着雨水。

第二章 转折

她把伞递给陈野。
"""


def create_test_client(tmp_path: Path) -> TestClient:
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    return TestClient(app)


def create_project(client: TestClient) -> None:
    response = client.post("/projects", json=PROJECT_PAYLOAD)
    assert response.status_code == 201


def test_utf8_txt_upload_imports_document(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        create_project(client)

        response = client.post(
            "/projects/project-1/documents/import",
            files={"file": ("source.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "created"
    assert "document" in payload
    assert "chapters_count" in payload
    assert "chunks_count" in payload
    assert payload["chapters_count"] > 0
    assert payload["chunks_count"] > 0
    assert payload["document"]["filename"] == "source.txt"
    assert payload["document"]["project_id"] == "project-1"


def test_non_txt_upload_returns_415(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        create_project(client)

        response = client.post(
            "/projects/project-1/documents/import",
            files={"file": ("source.pdf", b"%PDF-1.7", "application/pdf")},
        )

    assert response.status_code == 415
    assert "TXT" in response.json()["detail"]


def test_empty_txt_upload_returns_400(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        create_project(client)

        response = client.post(
            "/projects/project-1/documents/import",
            files={"file": ("source.txt", b"", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file is empty"


def test_non_utf8_txt_upload_returns_400(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        create_project(client)

        response = client.post(
            "/projects/project-1/documents/import",
            files={"file": ("source.txt", b"\xff\xfe\x00\x00", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "TXT file must be UTF-8 encoded"


def test_repeated_txt_upload_is_idempotent(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        create_project(client)
        files = {"file": ("source.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")}

        first = client.post("/projects/project-1/documents/import", files=files)
        second = client.post(
            "/projects/project-1/documents/import",
            files={"file": ("source.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")},
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["status"] == "created"
    assert second.json()["status"] == "existing"
    assert second.json()["chapters_count"] > 0
    assert second.json()["chunks_count"] > 0
