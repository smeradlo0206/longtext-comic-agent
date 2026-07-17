from comic_agent.services.document_parser import DocumentParser


def test_parser_detects_chinese_chapters() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text="第一章 开端\n\n第一段。\n\n第二章 转折\n\n第二段。",
    )

    assert [chapter.title for chapter in parsed.chapters] == ["第一章 开端", "第二章 转折"]
    assert [chunk.text for chunk in parsed.chunks] == ["第一段。", "第二段。"]


def test_parser_detects_english_chapters() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text="Chapter 1 Arrival\n\nThe train stopped.\n\nChapter 2 Departure\n\nIt left.",
    )

    assert [chapter.title for chapter in parsed.chapters] == [
        "Chapter 1 Arrival",
        "Chapter 2 Departure",
    ]


def test_parser_uses_default_chapter_when_no_heading_exists() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text="Only one paragraph.\n\nStill same chapter.",
    )

    assert len(parsed.chapters) == 1
    assert parsed.chapters[0].title == "Default Chapter"
    assert [chunk.text for chunk in parsed.chunks] == [
        "Only one paragraph.",
        "Still same chapter.",
    ]


def test_parser_preserves_paragraph_order_and_nonblank_text() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text="第一章 开端\n\nA\n\n\nB\n\nC",
    )

    assert [chunk.text for chunk in parsed.chunks] == ["A", "B", "C"]


def test_checksum_is_stable() -> None:
    parser = DocumentParser()
    first = parser.parse_txt("project-1", "demo.txt", "第一章 开端\n\nA")
    second = parser.parse_txt("project-1", "demo.txt", "第一章 开端\n\nA")

    assert first.document.checksum == second.document.checksum
    assert [chunk.checksum for chunk in first.chunks] == [chunk.checksum for chunk in second.chunks]
