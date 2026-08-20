from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.main import create_app


def test_health_endpoint(tmp_path: Path) -> None:
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_console_legacy_readiness_probe_is_not_a_404(tmp_path: Path) -> None:
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    with TestClient(app) as client:
        response = client.get("/demo/status")

    assert response.status_code == 200
    assert response.json() == {"status": "available"}


def test_project_import_and_chunk_queries(tmp_path: Path) -> None:
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
    with TestClient(app) as client:
        project_response = client.post(
            "/projects",
            json={
                "id": "project-1",
                "name": "Golden Novel",
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
            },
        )
        assert project_response.status_code == 201

        source = Path("tests/golden_novel/source.txt")
        with source.open("rb") as file:
            import_response = client.post(
                "/projects/project-1/documents/import",
                files={"file": ("source.txt", file, "text/plain")},
            )
        assert import_response.status_code == 201

        chapters_response = client.get("/projects/project-1/chapters")
        assert chapters_response.status_code == 200
        chapters = chapters_response.json()
        assert chapters

        chunks_response = client.get(f"/chapters/{chapters[0]['chapter_id']}/chunks")
        assert chunks_response.status_code == 200
        chunks = chunks_response.json()
        assert chunks

        chunk_response = client.get(f"/chunks/{chunks[0]['chunk_id']}")
        assert chunk_response.status_code == 200
        assert chunk_response.json()["text"] == "林夏站在操场边，鞋尖沾着雨水。"
