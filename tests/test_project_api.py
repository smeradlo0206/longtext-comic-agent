from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.main import create_app


def create_test_client(tmp_path: Path) -> TestClient:
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'project_api.db'}")
    return TestClient(app)


def test_create_project_accepts_console_payload(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.post(
            "/projects",
            json={"project_id": "demo-project", "name": "Demo Project"},
        )

    assert response.status_code == 201
    assert response.json() == {
        "project_id": "demo-project",
        "name": "Demo Project",
        "created": True,
    }


def test_create_project_is_idempotent_for_console_payload(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        first = client.post(
            "/projects",
            json={"project_id": "demo-project", "name": "Demo Project"},
        )
        second = client.post(
            "/projects",
            json={"project_id": "demo-project", "name": "Demo Project"},
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["created"] is True
    assert second.json() == {
        "project_id": "demo-project",
        "name": "Demo Project",
        "created": False,
    }


def test_create_project_rejects_blank_project_id(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.post(
            "/projects",
            json={"project_id": "", "name": "Demo Project"},
        )

    assert response.status_code in {400, 422}
