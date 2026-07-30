from pathlib import Path

from comic_agent.services.document_parser import DocumentParser

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


def test_parser_detects_standalone_roman_numeral_chapters_without_toc_matches() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text=(
            "CONTENTS\n\n"
            " CHAPTER I Arrival\n"
            " CHAPTER II Rescue\n\n"
            "CHAPTER I\n\n"
            "Arrival body.\n\n"
            "CHAPTER II\n\n"
            "Rescue body."
        ),
    )

    assert [chapter.title for chapter in parsed.chapters] == ["CHAPTER I", "CHAPTER II"]
    assert [chunk.text for chunk in parsed.chunks] == ["Arrival body.", "Rescue body."]


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


def test_parser_handles_long_mixed_chapter_document() -> None:
    text = LONG_FIXTURE.read_text(encoding="utf-8")

    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="long_mixed_chapters.txt",
        text=text,
    )

    assert [chapter.title for chapter in parsed.chapters] == LONG_EXPECTED_TITLES
    assert len(parsed.chapters) == 8
    assert len(parsed.chunks) == LONG_EXPECTED_CHUNKS
    assert [chunk.order for chunk in parsed.chunks] == list(range(LONG_EXPECTED_CHUNKS))
    assert all(chunk.text.strip() for chunk in parsed.chunks)
    assert "她在笔记里写下 Chapter 9 is not a heading." in [
        chunk.text for chunk in parsed.chunks
    ]
    assert "他说，第一章并不等于真相。" in [chunk.text for chunk in parsed.chunks]


def test_parser_char_ranges_slice_back_to_normalized_text() -> None:
    text = LONG_FIXTURE.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="long_mixed_chapters.txt",
        text=text,
    )

    for chunk in parsed.chunks:
        assert chunk.char_start is not None
        assert chunk.char_end is not None
        assert normalized[chunk.char_start : chunk.char_end] == chunk.text


def test_parser_is_stable_for_repeated_parse() -> None:
    text = LONG_FIXTURE.read_text(encoding="utf-8")
    parser = DocumentParser()

    first = parser.parse_txt("project-1", "long_mixed_chapters.txt", text)
    second = parser.parse_txt("project-1", "long_mixed_chapters.txt", text)

    assert first.document.checksum == second.document.checksum
    assert [chunk.chunk_id for chunk in first.chunks] == [
        chunk.chunk_id for chunk in second.chunks
    ]
    assert [chunk.checksum for chunk in first.chunks] == [
        chunk.checksum for chunk in second.chunks
    ]
    assert [chunk.order for chunk in first.chunks] == [chunk.order for chunk in second.chunks]


def test_parser_normalizes_crlf_without_changing_chunk_semantics() -> None:
    lf_text = LONG_FIXTURE.read_text(encoding="utf-8")
    crlf_text = lf_text.replace("\n", "\r\n")

    lf = DocumentParser().parse_txt("project-1", "long_mixed_chapters.txt", lf_text)
    crlf = DocumentParser().parse_txt("project-1", "long_mixed_chapters.txt", crlf_text)
    crlf_normalized = crlf_text.replace("\r\n", "\n").replace("\r", "\n")

    assert [chapter.title for chapter in crlf.chapters] == [
        chapter.title for chapter in lf.chapters
    ]
    assert [chunk.text for chunk in crlf.chunks] == [chunk.text for chunk in lf.chunks]
    assert [chunk.checksum for chunk in crlf.chunks] == [
        chunk.checksum for chunk in lf.chunks
    ]
    for chunk in crlf.chunks:
        assert chunk.char_start is not None
        assert chunk.char_end is not None
        assert crlf_normalized[chunk.char_start : chunk.char_end] == chunk.text
