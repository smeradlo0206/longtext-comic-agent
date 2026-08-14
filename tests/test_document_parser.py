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
        text=("第一章 开端\n\n第一段。\n\n第2章 转折\n\n第二段。\n\n第十章 尾声\n\n第三段。"),
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


def test_parser_detects_webnovel_prefixed_chapters() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="webnovel.txt",
        text=(
            "正文 第一章 蟒雀吞龙\n\n"
            "第一段。\n\n"
            "正文 第二章 源纹\n\n"
            "第二段。\n\n"
            "正文 第一百六十章 风雷成，夭夭伤\n\n"
            "第三段。"
        ),
    )

    assert [chapter.title for chapter in parsed.chapters] == [
        "第一章 蟒雀吞龙",
        "第二章 源纹",
        "第一百六十章 风雷成，夭夭伤",
    ]
    assert [chunk.text for chunk in parsed.chunks] == ["第一段。", "第二段。", "第三段。"]


def test_parser_detects_webnovel_volume_and_preface_headings() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="webnovel.txt",
        text=(
            "\ufeff楔子\n\n"
            "楔子正文。\n\n"
            "序章\n\n"
            "序章正文。\n\n"
            "卷一 少年游\n\n"
            "卷一正文。\n\n"
            "第一卷 少年游\n\n"
            "第一卷正文。\n\n"
            "第一篇 开端\n\n"
            "第一篇正文。"
        ),
    )

    assert [chapter.title for chapter in parsed.chapters] == [
        "楔子",
        "序章",
        "卷一 少年游",
        "第一卷 少年游",
        "第一篇 开端",
    ]


def test_parser_detects_hui_and_section_headings() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="webnovel.txt",
        text=(
            "第一回 风起\n\n"
            "第一回正文。\n\n"
            "第1回 风起\n\n"
            "第1回正文。\n\n"
            "第一节 课堂\n\n"
            "第一节正文。\n\n"
            "第1节 课堂\n\n"
            "第1节正文。"
        ),
    )

    assert [chapter.title for chapter in parsed.chapters] == [
        "第一回 风起",
        "第1回 风起",
        "第一节 课堂",
        "第1节 课堂",
    ]


def test_parser_does_not_detect_chapter_words_inside_body() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="body.txt",
        text=(
            "他说，第一章并不等于真相。\n\n"
            "她在笔记里写下 Chapter 9 is not a heading.\n\n"
            "他翻到第一章时已经天亮。\n\n"
            "“正文 第一章”这几个字只是出现在对话里。"
        ),
    )

    assert [chapter.title for chapter in parsed.chapters] == ["Default Chapter"]
    assert [chunk.text for chunk in parsed.chunks] == [
        "他说，第一章并不等于真相。",
        "她在笔记里写下 Chapter 9 is not a heading.",
        "他翻到第一章时已经天亮。",
        "“正文 第一章”这几个字只是出现在对话里。",
    ]


def test_parser_does_not_treat_english_sentence_as_chapter_heading() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="english-sentence.txt",
        text=(
            "第二章 旧图书馆\n\n"
            "Chapter 2 is written here only to test English chapter detection.\n\n"
            "正文仍属于第二章。"
        ),
    )

    assert [chapter.title for chapter in parsed.chapters] == ["第二章 旧图书馆"]
    assert parsed.chapters[0].start_chunk_order == 0
    assert parsed.chapters[0].end_chunk_order == len(parsed.chunks) - 1
    assert len(parsed.chunks) >= 1


def test_golden_fixture_second_chapter_is_not_empty() -> None:
    text = Path("tests/golden_novel/source.txt").read_text(encoding="utf-8")
    parsed = DocumentParser().parse_txt(
        project_id="project-1", filename="source.txt", text=text
    )

    second = next(chapter for chapter in parsed.chapters if "第二章" in chapter.title)
    assert any(chunk.chapter_id == second.chapter_id for chunk in parsed.chunks)


def test_parser_preserves_existing_long_mixed_fixture() -> None:
    text = LONG_FIXTURE.read_text(encoding="utf-8")

    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="long_mixed_chapters.txt",
        text=text,
    )

    assert [chapter.title for chapter in parsed.chapters] == LONG_EXPECTED_TITLES
    assert len(parsed.chunks) == LONG_EXPECTED_CHUNKS


def test_parser_splits_long_webnovel_paragraph_into_reasonable_chunks() -> None:
    long_body = "少年望向山门，听见钟声回荡。" * 240
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="webnovel.txt",
        text=f"第一章 蟒雀吞龙\n\n{long_body}",
    )

    assert [chapter.title for chapter in parsed.chapters] == ["第一章 蟒雀吞龙"]
    assert len(parsed.chunks) >= 3
    assert all(0 < len(chunk.text) <= 1200 for chunk in parsed.chunks)
    assert [chunk.order for chunk in parsed.chunks] == list(range(len(parsed.chunks)))


def test_parser_prefers_sentence_boundaries_for_long_chunks() -> None:
    long_body = "他停下脚步，确认石阶尽头仍有灯火。" * 260
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="webnovel.txt",
        text=f"第一章 蟒雀吞龙\n\n{long_body}",
    )

    assert len(parsed.chunks) >= 3
    sentence_endings = tuple("。！？；”’")
    non_final_chunks = parsed.chunks[:-1]
    assert non_final_chunks
    assert sum(chunk.text.endswith(sentence_endings) for chunk in non_final_chunks) >= (
        len(non_final_chunks) - 1
    )


def test_parser_char_ranges_survive_long_paragraph_splitting() -> None:
    text = "第一章 蟒雀吞龙\r\n\r\n" + ("少年走过长街，风声从檐下掠过。" * 230)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="webnovel.txt",
        text=text,
    )

    assert len(parsed.chunks) >= 3
    for chunk in parsed.chunks:
        assert chunk.char_start is not None
        assert chunk.char_end is not None
        assert normalized[chunk.char_start : chunk.char_end] == chunk.text


def test_parser_preserves_blank_paragraph_chunking_for_short_text() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text="第一章 蟒雀吞龙\n\n第一段。\n\n第二段。\n\n第三段。",
    )

    assert [chunk.text for chunk in parsed.chunks] == ["第一段。", "第二段。", "第三段。"]
    assert [chunk.order for chunk in parsed.chunks] == [0, 1, 2]


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
    assert "她在笔记里写下 Chapter 9 is not a heading." in [chunk.text for chunk in parsed.chunks]
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
    assert [chunk.chunk_id for chunk in first.chunks] == [chunk.chunk_id for chunk in second.chunks]
    assert [chunk.checksum for chunk in first.chunks] == [chunk.checksum for chunk in second.chunks]
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
    assert [chunk.checksum for chunk in crlf.chunks] == [chunk.checksum for chunk in lf.chunks]
    for chunk in crlf.chunks:
        assert chunk.char_start is not None
        assert chunk.char_end is not None
        assert crlf_normalized[chunk.char_start : chunk.char_end] == chunk.text
