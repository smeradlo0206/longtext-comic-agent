from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from comic_agent.config import get_settings
from comic_agent.main import create_app
from comic_agent.services.document_parser import DocumentParser

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


def create_project(client: TestClient, project_id: str = "project-1") -> None:
    payload = PROJECT_PAYLOAD | {"id": project_id}
    response = client.post("/projects", json=payload)
    assert response.status_code == 201


def parse_long_fixture(project_id: str = "project-1"):
    return DocumentParser().parse_txt(
        project_id=project_id,
        filename="long_mixed_chapters.txt",
        text=LONG_FIXTURE.read_text(encoding="utf-8"),
        mime_type="text/plain",
    )


def import_long_fixture(client: TestClient, project_id: str = "project-1") -> dict[str, object]:
    response = client.post(
        f"/projects/{project_id}/documents/import",
        files={
            "file": (
                "long_mixed_chapters.txt",
                LONG_FIXTURE.read_bytes(),
                "text/plain",
            )
        },
    )
    assert response.status_code == 201
    return response.json()


def assert_chunk_matches_parser(expected, actual: dict[str, object]) -> None:
    assert actual["chunk_id"] == expected.chunk_id
    assert actual["order"] == expected.order
    assert actual["text"] == expected.text
    assert actual["char_start"] == expected.char_start
    assert actual["char_end"] == expected.char_end
    assert actual["checksum"] == expected.checksum


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


def test_txt_upload_over_demo_char_limit_returns_413(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("INTERNAL_DEMO_MAX_IMPORT_CHARS", "10")
    get_settings.cache_clear()
    try:
        with create_test_client(tmp_path) as client:
            create_project(client)

            response = client.post(
                "/projects/project-1/documents/import",
                files={"file": ("source.txt", b"01234567890", "text/plain")},
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 413
    assert response.json()["detail"] == "TXT exceeds demo import character limit"


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


def test_import_then_query_project_chapters_preserves_order(tmp_path: Path) -> None:
    expected = parse_long_fixture()
    with create_test_client(tmp_path) as client:
        create_project(client)
        import_payload = import_long_fixture(client)

        chapters_response = client.get("/projects/project-1/chapters")

    assert chapters_response.status_code == 200
    chapters = chapters_response.json()
    assert len(chapters) == len(expected.chapters)
    assert [chapter["order"] for chapter in chapters] == list(range(len(expected.chapters)))
    assert [chapter["title"] for chapter in chapters] == [
        chapter.title for chapter in expected.chapters
    ]
    assert {chapter["project_id"] for chapter in chapters} == {"project-1"}
    assert {chapter["document_id"] for chapter in chapters} == {
        import_payload["document"]["document_id"]
    }


def test_import_then_query_chapter_chunks_preserves_order_and_content(tmp_path: Path) -> None:
    expected = parse_long_fixture()
    expected_chunks_by_order = {chunk.order: chunk for chunk in expected.chunks}
    returned_orders: list[int] = []

    with create_test_client(tmp_path) as client:
        create_project(client)
        import_payload = import_long_fixture(client)
        chapters_response = client.get("/projects/project-1/chapters")
        assert chapters_response.status_code == 200
        chapters = chapters_response.json()

        for chapter in chapters:
            chunks_response = client.get(f"/chapters/{chapter['chapter_id']}/chunks")
            assert chunks_response.status_code == 200
            chunks = chunks_response.json()

            assert [chunk["order"] for chunk in chunks] == sorted(
                chunk["order"] for chunk in chunks
            )
            assert {chunk["chapter_id"] for chunk in chunks} == {chapter["chapter_id"]}
            assert {chunk["document_id"] for chunk in chunks} == {
                import_payload["document"]["document_id"]
            }
            for chunk in chunks:
                expected_chunk = expected_chunks_by_order[chunk["order"]]
                assert_chunk_matches_parser(expected_chunk, chunk)
                returned_orders.append(chunk["order"])

    assert returned_orders == list(range(LONG_EXPECTED_CHUNKS))


def test_get_single_chunk_matches_parser_result(tmp_path: Path) -> None:
    expected = parse_long_fixture()
    selected_chunks = [
        expected.chunks[0],
        expected.chunks[len(expected.chunks) // 2],
        expected.chunks[-1],
    ]

    with create_test_client(tmp_path) as client:
        create_project(client)
        import_long_fixture(client)

        responses = [client.get(f"/chunks/{chunk.chunk_id}") for chunk in selected_chunks]

    for expected_chunk, response in zip(selected_chunks, responses, strict=True):
        assert response.status_code == 200
        assert_chunk_matches_parser(expected_chunk, response.json())


def test_get_missing_chunk_returns_404(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        response = client.get("/chunks/missing-chunk-id")

    assert response.status_code == 404
    assert response.json()["detail"] == "Chunk not found"


def test_query_chapters_for_empty_project_returns_empty_list(tmp_path: Path) -> None:
    with create_test_client(tmp_path) as client:
        create_project(client)

        response = client.get("/projects/project-1/chapters")

    assert response.status_code == 200
    assert response.json() == []


def test_queries_do_not_leak_between_projects(tmp_path: Path) -> None:
    project_1_expected = parse_long_fixture(project_id="project-1")
    project_2_expected = DocumentParser().parse_txt(
        project_id="project-2",
        filename="project_2.txt",
        text="第一章 项目二\n\n项目二第一段。\n\n项目二第二段。",
        mime_type="text/plain",
    )

    with create_test_client(tmp_path) as client:
        create_project(client, "project-1")
        create_project(client, "project-2")
        import_long_fixture(client, "project-1")
        project_2_import = client.post(
            "/projects/project-2/documents/import",
            files={
                "file": (
                    "project_2.txt",
                    "第一章 项目二\n\n项目二第一段。\n\n项目二第二段。".encode(),
                    "text/plain",
                )
            },
        )
        assert project_2_import.status_code == 201

        project_1_chapters_response = client.get("/projects/project-1/chapters")
        project_2_chapters_response = client.get("/projects/project-2/chapters")
        assert project_1_chapters_response.status_code == 200
        assert project_2_chapters_response.status_code == 200
        project_1_chapters = project_1_chapters_response.json()
        project_2_chapters = project_2_chapters_response.json()

        project_1_chunks_response = client.get(
            f"/chapters/{project_1_chapters[0]['chapter_id']}/chunks"
        )
        project_2_chunks_response = client.get(
            f"/chapters/{project_2_chapters[0]['chapter_id']}/chunks"
        )

    assert [chapter["project_id"] for chapter in project_1_chapters] == [
        "project-1"
    ] * len(project_1_expected.chapters)
    assert [chapter["title"] for chapter in project_1_chapters] == [
        chapter.title for chapter in project_1_expected.chapters
    ]
    assert [chapter["project_id"] for chapter in project_2_chapters] == ["project-2"]
    assert [chapter["title"] for chapter in project_2_chapters] == [
        chapter.title for chapter in project_2_expected.chapters
    ]
    assert project_1_chunks_response.status_code == 200
    assert project_2_chunks_response.status_code == 200
    assert {chunk["project_id"] for chunk in project_1_chunks_response.json()} == {"project-1"}
    assert {chunk["project_id"] for chunk in project_2_chunks_response.json()} == {"project-2"}
