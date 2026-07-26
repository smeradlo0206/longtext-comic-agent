from comic_agent.services.document_parser import DocumentParser


def test_parser_detects_chinese_chapters() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text=(
            "第一章 开端\n\n"
            "第一段。\n\n"
            "第2章 转折\n\n"
            "第二段。\n\n"
            "第十章 尾声\n\n"
            "第三段。"
        ),
    )

    assert [chapter.title for chapter in parsed.chapters] == [
        "第一章 开端",
        "第2章 转折",
        "第十章 尾声",
    ]
    assert [chunk.text for chunk in parsed.chunks] == ["第一段。", "第二段。", "第三段。"]


def test_parser_detects_english_chapters() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text=(
            "Chapter 1 Arrival\n\n"
            "The train stopped.\n\n"
            "chapter 2 Departure\n\n"
            "It left.\n\n"
            "CHAPTER 3 Return\n\n"
            "It came back."
        ),
    )

    assert [chapter.title for chapter in parsed.chapters] == [
        "Chapter 1 Arrival",
        "chapter 2 Departure",
        "CHAPTER 3 Return",
    ]
    assert [chunk.text for chunk in parsed.chunks] == [
        "The train stopped.",
        "It left.",
        "It came back.",
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


def test_parser_handles_empty_and_blank_text_without_chunks() -> None:
    parser = DocumentParser()

    empty = parser.parse_txt(project_id="project-1", filename="empty.txt", text="")
    blank = parser.parse_txt(project_id="project-1", filename="blank.txt", text=" \n\n\t\n")

    assert [chapter.title for chapter in empty.chapters] == ["Default Chapter"]
    assert empty.chunks == []
    assert [chapter.title for chapter in blank.chapters] == ["Default Chapter"]
    assert blank.chunks == []


def test_parser_preserves_paragraph_order_and_nonblank_text() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text="第一章 开端\n\nA\n\n\nB\n\n\n\nC",
    )

    assert [chunk.text for chunk in parsed.chunks] == ["A", "B", "C"]


def test_chunk_order_is_continuous_across_chapters() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text="第一章 开端\n\nA\n\nB\n\n第二章 转折\n\nC\n\nD",
    )

    assert [chunk.text for chunk in parsed.chunks] == ["A", "B", "C", "D"]
    assert [chunk.order for chunk in parsed.chunks] == [0, 1, 2, 3]


def test_char_offsets_slice_normalized_text_back_to_chunk_text() -> None:
    text = "第一章 开端\r\n\r\nA line\r\nstill same paragraph\r\n\r\nB paragraph"
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text=text,
    )

    assert [chunk.text for chunk in parsed.chunks] == [
        "A line\nstill same paragraph",
        "B paragraph",
    ]
    for chunk in parsed.chunks:
        assert chunk.char_start is not None
        assert chunk.char_end is not None
        assert normalized[chunk.char_start : chunk.char_end] == chunk.text


def test_crlf_text_parses_like_lf_text() -> None:
    lf_text = "第一章 开端\n\nA\n\n第二章 转折\n\nB"
    crlf_text = lf_text.replace("\n", "\r\n")

    lf = DocumentParser().parse_txt("project-1", "demo.txt", lf_text)
    crlf = DocumentParser().parse_txt("project-1", "demo.txt", crlf_text)

    assert [chapter.title for chapter in crlf.chapters] == [
        chapter.title for chapter in lf.chapters
    ]
    assert [chunk.text for chunk in crlf.chunks] == [chunk.text for chunk in lf.chunks]
    assert [chunk.char_start for chunk in crlf.chunks] == [chunk.char_start for chunk in lf.chunks]
    assert [chunk.char_end for chunk in crlf.chunks] == [chunk.char_end for chunk in lf.chunks]


def test_checksum_and_chunk_ids_are_stable_for_same_text() -> None:
    parser = DocumentParser()
    first = parser.parse_txt("project-1", "demo.txt", "第一章 开端\n\nA")
    second = parser.parse_txt("project-1", "demo.txt", "第一章 开端\n\nA")

    assert first.document.checksum == second.document.checksum
    assert [chunk.checksum for chunk in first.chunks] == [chunk.checksum for chunk in second.chunks]
    assert [chunk.chunk_id for chunk in first.chunks] == [chunk.chunk_id for chunk in second.chunks]


def test_checksum_changes_when_content_changes() -> None:
    parser = DocumentParser()
    first = parser.parse_txt("project-1", "demo.txt", "第一章 开端\n\nA")
    second = parser.parse_txt("project-1", "demo.txt", "第一章 开端\n\nB")

    assert first.document.checksum != second.document.checksum
    assert first.chunks[0].checksum != second.chunks[0].checksum
    assert first.chunks[0].chunk_id != second.chunks[0].chunk_id
