from pathlib import Path

import pytest
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

LONG_FIXTURE = Path("tests/fixtures/import/long_mixed_chapters.txt")
LONG_EXPECTED_TITLES = [
    "第一章 旧馆门口",
    "Chapter 1 Notice Board",
    "第2章 报名表",
    "chapter 2 Night Route",
    "第三章 地下书库",
    "CHAPTER 3 Archive Log",
    "第十章 尾声前的更正",
    "第十一章 清晨复核",
]
LONG_EXPECTED_CHUNKS = 40
FIRST_CHAPTER_CHUNKS = [
    "19:20，林夏站在旧图书馆门口，雨水沿着玻璃门滑下来。",
    "校园智能体创意赛的报名通知贴在公告栏上，报名截止写着 2026-04-18 17:00。",
    "她拨通了值班电话 010-61881234，却只听见自动语音提示。",
    "陈野发来邮件：hello.library@example.edu，主题是“夜间记录确认”。",
    "她在笔记里写下 Chapter 9 is not a heading.",
]


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


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("source.pdf", "application/pdf"),
        ("source.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("source.md", "text/markdown"),
    ],
)
def test_non_txt_upload_returns_415(
    tmp_path: Path,
    filename: str,
    content_type: str,
) -> None:
    with create_test_client(tmp_path) as client:
        create_project(client)

        response = client.post(
            "/projects/project-1/documents/import",
            files={"file": (filename, b"not a txt document", content_type)},
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


def test_whitespace_only_txt_upload_returns_400(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        create_project(client)

        response = client.post(
            "/projects/project-1/documents/import",
            files={"file": ("source.txt", b"   \n\n   ", "text/plain")},
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


def test_import_long_utf8_txt_success(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        create_project(client)

        response = client.post(
            "/projects/project-1/documents/import",
            files={
                "file": (
                    "long_mixed_chapters.txt",
                    LONG_FIXTURE.read_bytes(),
                    "text/plain",
                )
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert set(payload) >= {"status", "document", "chapters_count", "chunks_count"}
    assert payload["status"] == "created"
    assert payload["document"]["filename"] == "long_mixed_chapters.txt"
    assert payload["document"]["project_id"] == "project-1"
    assert payload["chapters_count"] == len(LONG_EXPECTED_TITLES)
    assert payload["chunks_count"] == LONG_EXPECTED_CHUNKS


def test_import_same_long_txt_twice_returns_existing(tmp_path: Path) -> None:
    content = LONG_FIXTURE.read_bytes()
    with create_test_client(tmp_path) as client:
        create_project(client)

        first = client.post(
            "/projects/project-1/documents/import",
            files={"file": ("long_mixed_chapters.txt", content, "text/plain")},
        )
        second = client.post(
            "/projects/project-1/documents/import",
            files={"file": ("long_mixed_chapters.txt", content, "text/plain")},
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["status"] == "created"
    assert second.json()["status"] == "existing"
    assert second.json()["chapters_count"] == first.json()["chapters_count"]
    assert second.json()["chunks_count"] == first.json()["chunks_count"]


def test_import_then_query_chapters_and_chunks(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        create_project(client)
        import_response = client.post(
            "/projects/project-1/documents/import",
            files={
                "file": (
                    "long_mixed_chapters.txt",
                    LONG_FIXTURE.read_bytes(),
                    "text/plain",
                )
            },
        )
        assert import_response.status_code == 201

        chapters_response = client.get("/projects/project-1/chapters")
        assert chapters_response.status_code == 200
        chapters = chapters_response.json()

        first_chapter_id = chapters[0]["chapter_id"]
        chunks_response = client.get(f"/chapters/{first_chapter_id}/chunks")
        assert chunks_response.status_code == 200
        chunks = chunks_response.json()

        first_chunk_response = client.get(f"/chunks/{chunks[0]['chunk_id']}")

    assert [chapter["title"] for chapter in chapters] == LONG_EXPECTED_TITLES
    assert [chapter["order"] for chapter in chapters] == list(range(len(LONG_EXPECTED_TITLES)))
    assert [chunk["text"] for chunk in chunks] == FIRST_CHAPTER_CHUNKS
    assert [chunk["order"] for chunk in chunks] == list(range(len(FIRST_CHAPTER_CHUNKS)))
    assert first_chunk_response.status_code == 200
    assert first_chunk_response.json()["text"] == FIRST_CHAPTER_CHUNKS[0]
