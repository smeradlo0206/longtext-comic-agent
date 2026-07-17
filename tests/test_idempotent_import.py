from comic_agent.services.document_parser import DocumentParser


def test_importing_same_document_twice_is_idempotent(temp_repository) -> None:  # type: ignore[no-untyped-def]
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text="第一章 开端\n\n第一段。\n\n第二段。",
    )

    first = temp_repository.import_parsed_document(parsed)
    second = temp_repository.import_parsed_document(parsed)

    assert first.status == "created"
    assert second.status == "existing"
    assert temp_repository.count_documents() == 1
    assert temp_repository.count_chunks() == 2
