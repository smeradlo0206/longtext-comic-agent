from comic_agent.schemas.source import SourceChapterV1, SourceChunkV1, SourceDocumentV1
from comic_agent.services.document_parser import DocumentParser


def parse_source(
    project_id: str = "project-1",
    filename: str = "demo.txt",
    text: str = "第一章 开端\n\n第一段。\n\n第二段。",
):
    return DocumentParser().parse_txt(
        project_id=project_id,
        filename=filename,
        text=text,
    )


def test_import_persists_document_chapters_chunks(temp_repository) -> None:  # type: ignore[no-untyped-def]
    parsed = parse_source(
        text=(
            "第一章 开端\n\n"
            "第一段。\n\n"
            "第二段。\n\n"
            "第二章 转折\n\n"
            "第三段。"
        )
    )

    result = temp_repository.import_parsed_document(parsed)
    chapters = temp_repository.list_chapters("project-1")
    chunks = temp_repository.list_document_chunks(parsed.document.document_id)
    first_chunk = temp_repository.get_chunk(parsed.chunks[0].chunk_id)

    assert result.status == "created"
    assert result.document.model_dump(mode="json") == parsed.document.model_dump(mode="json")
    assert [chapter.model_dump(mode="json") for chapter in result.chapters] == [
        chapter.model_dump(mode="json") for chapter in parsed.chapters
    ]
    assert [chunk.model_dump(mode="json") for chunk in result.chunks] == [
        chunk.model_dump(mode="json") for chunk in parsed.chunks
    ]
    assert [chapter.model_dump(mode="json") for chapter in chapters] == [
        chapter.model_dump(mode="json") for chapter in parsed.chapters
    ]
    assert [chunk.model_dump(mode="json") for chunk in chunks] == [
        chunk.model_dump(mode="json") for chunk in parsed.chunks
    ]
    assert first_chunk is not None
    assert first_chunk.model_dump(mode="json") == parsed.chunks[0].model_dump(mode="json")


def test_payload_round_trips_full_pydantic_data(temp_repository) -> None:  # type: ignore[no-untyped-def]
    parsed = parse_source(
        text=(
            "第一章 开端\n\n"
            "第一段有中文标点。\n\n"
            "第二段 has English and 2026-07-27.\n\n"
            "第二章 转折\n\n"
            "第三段。"
        )
    )

    first = temp_repository.import_parsed_document(parsed)
    second = temp_repository.import_parsed_document(parsed)
    chapters = temp_repository.list_chapters("project-1")
    chunks = temp_repository.list_document_chunks(parsed.document.document_id)
    chunk = temp_repository.get_chunk(parsed.chunks[1].chunk_id)

    restored_document = SourceDocumentV1.model_validate(second.document.model_dump(mode="json"))
    restored_chapter = SourceChapterV1.model_validate(chapters[0].model_dump(mode="json"))
    assert chunk is not None
    restored_chunk = SourceChunkV1.model_validate(chunk.model_dump(mode="json"))

    assert first.status == "created"
    assert second.status == "existing"
    assert restored_document.model_dump(mode="json") == parsed.document.model_dump(mode="json")
    assert restored_chapter.model_dump(mode="json") == parsed.chapters[0].model_dump(mode="json")
    assert restored_chunk.model_dump(mode="json") == parsed.chunks[1].model_dump(mode="json")
    assert restored_document.schema_version == "1.0"
    assert restored_document.project_id == "project-1"
    assert restored_document.document_id == parsed.document.document_id
    assert restored_chapter.schema_version == "1.0"
    assert restored_chapter.project_id == "project-1"
    assert restored_chapter.document_id == parsed.document.document_id
    assert restored_chapter.chapter_id == parsed.chapters[0].chapter_id
    assert restored_chunk.schema_version == "1.0"
    assert restored_chunk.project_id == "project-1"
    assert restored_chunk.document_id == parsed.document.document_id
    assert restored_chunk.chapter_id == parsed.chunks[1].chapter_id
    assert restored_chunk.chunk_id == parsed.chunks[1].chunk_id
    assert restored_chunk.order == 1
    assert restored_chunk.text == "第二段 has English and 2026-07-27."
    assert restored_chunk.char_start == parsed.chunks[1].char_start
    assert restored_chunk.char_end == parsed.chunks[1].char_end
    assert restored_chunk.checksum == parsed.chunks[1].checksum
    assert [chunk.model_dump(mode="json") for chunk in chunks] == [
        chunk.model_dump(mode="json") for chunk in parsed.chunks
    ]


def test_importing_same_document_twice_is_idempotent(temp_repository) -> None:  # type: ignore[no-untyped-def]
    parsed = parse_source()

    first = temp_repository.import_parsed_document(parsed)
    second = temp_repository.import_parsed_document(parsed)

    assert first.status == "created"
    assert second.status == "existing"
    assert temp_repository.count_documents() == 1
    assert temp_repository.count_chunks() == 2
    assert second.document.document_id == first.document.document_id
    assert len(second.chunks) == len(first.chunks)


def test_same_text_in_different_projects_is_independent(temp_repository) -> None:  # type: ignore[no-untyped-def]
    text = "第一章 开端\n\n共同文本第一段。\n\n共同文本第二段。"
    first_project = parse_source(project_id="project-1", filename="demo.txt", text=text)
    second_project = parse_source(project_id="project-2", filename="demo.txt", text=text)

    first = temp_repository.import_parsed_document(first_project)
    second = temp_repository.import_parsed_document(second_project)

    assert first.status == "created"
    assert second.status == "created"
    assert first.document.project_id == "project-1"
    assert second.document.project_id == "project-2"
    assert first.document.document_id != second.document.document_id
    assert temp_repository.count_documents() == 2
    assert [chapter.project_id for chapter in temp_repository.list_chapters("project-1")] == [
        "project-1"
    ]
    assert [chapter.project_id for chapter in temp_repository.list_chapters("project-2")] == [
        "project-2"
    ]
    assert [chunk.project_id for chunk in temp_repository.list_document_chunks(first.document.document_id)] == [
        "project-1",
        "project-1",
    ]
    assert [chunk.project_id for chunk in temp_repository.list_document_chunks(second.document.document_id)] == [
        "project-2",
        "project-2",
    ]


def test_same_project_different_content_creates_new_document(temp_repository) -> None:  # type: ignore[no-untyped-def]
    first_parsed = parse_source(
        text="第一章 开端\n\nA 段。\n\nB 段。",
    )
    second_parsed = parse_source(
        text="第一章 开端\n\nA 段。\n\nB 段。\n\nC 段。",
    )

    first = temp_repository.import_parsed_document(first_parsed)
    second = temp_repository.import_parsed_document(second_parsed)

    assert first.status == "created"
    assert second.status == "created"
    assert first.document.checksum != second.document.checksum
    assert first.document.document_id != second.document.document_id
    assert temp_repository.count_documents() == 2
    assert temp_repository.count_chunks() == len(first_parsed.chunks) + len(second_parsed.chunks)


def test_same_project_same_content_different_filename_behavior_is_documented(
    temp_repository,
) -> None:  # type: ignore[no-untyped-def]
    text = "第一章 开端\n\n同一内容第一段。\n\n同一内容第二段。"
    first_parsed = parse_source(filename="demo-a.txt", text=text)
    second_parsed = parse_source(filename="demo-b.txt", text=text)

    first = temp_repository.import_parsed_document(first_parsed)
    second = temp_repository.import_parsed_document(second_parsed)

    # Current idempotency key is project_id + document.checksum, not filename.
    assert first.status == "created"
    assert second.status == "existing"
    assert second.document.document_id == first.document.document_id
    assert second.document.filename == "demo-a.txt"
    assert temp_repository.count_documents() == 1
    assert temp_repository.count_chunks() == len(first_parsed.chunks)
