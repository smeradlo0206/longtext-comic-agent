"""Document parsing MVP for TXT sources."""

import re
from dataclasses import dataclass

from comic_agent.schemas.source import SourceChapterV1, SourceChunkV1, SourceDocumentV1
from comic_agent.services.id_service import checksum_text, stable_id

_CHINESE_NUMERAL = "零〇一二三四五六七八九十百千万两0-9０-９"
_TITLE_MAX_CHARS = 80
_MIN_SENTENCE_CHUNK_CHARS = 800
_MAX_CHARS_PER_CHUNK = 1200
_MAX_SENTENCE_LOOKAHEAD_CHARS = 1500
_SENTENCE_ENDINGS = frozenset("。！？；”’。!?;.")
_NOISE_PREFIX_RE = re.compile(r"^(?:正文卷|正文|VIP章节|免费章节)\s*")
CHAPTER_RE = re.compile(
    rf"^(?:"
    rf"(?:第[{_CHINESE_NUMERAL}]+[章节回卷篇]|卷[{_CHINESE_NUMERAL}]+)"
    rf"(?:\s+\S.*)?"
    rf"|(?:楔子|序章|前言|引子)(?:\s+\S.*)?"
    rf"|Chapter\s+\d+\b(?:\s+\S.*)?"
    rf"|Chapter\s+[IVXLCDM]+"
    rf")$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedDocument:
    """Parsed source document plus chapter and chunk records."""

    document: SourceDocumentV1
    chapters: list[SourceChapterV1]
    chunks: list[SourceChunkV1]


@dataclass(frozen=True)
class _ChapterDraft:
    title: str
    start: int
    end: int
    order: int


class DocumentParser:
    """Parse source files into traceable document, chapter, and chunk schemas."""

    def parse_txt(
        self,
        project_id: str,
        filename: str,
        text: str,
        mime_type: str = "text/plain",
        storage_uri: str | None = None,
    ) -> ParsedDocument:
        """Parse a TXT document while preserving source order."""

        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        checksum = checksum_text(normalized)
        document_id = stable_id("doc", project_id, filename, checksum)
        document = SourceDocumentV1(
            document_id=document_id,
            project_id=project_id,
            filename=filename,
            mime_type=mime_type,
            checksum=checksum,
            storage_uri=storage_uri or f"mock://sources/{document_id}/{filename}",
            revision=1,
        )

        drafts = self._find_chapters(normalized)
        chunks: list[SourceChunkV1] = []
        chapters: list[SourceChapterV1] = []
        for draft in drafts:
            chapter_chunks = self._chunks_for_chapter(
                project_id=project_id,
                document_id=document_id,
                chapter_title=draft.title,
                chapter_order=draft.order,
                text=normalized,
                start=draft.start,
                end=draft.end,
                starting_order=len(chunks),
            )
            chapter_id = stable_id("chapter", document_id, draft.order, draft.title)
            if chapter_chunks:
                start_order = chapter_chunks[0].order
                end_order = chapter_chunks[-1].order
            else:
                start_order = len(chunks)
                end_order = len(chunks)
            for chunk in chapter_chunks:
                chunks.append(chunk.model_copy(update={"chapter_id": chapter_id}))
            chapters.append(
                SourceChapterV1(
                    chapter_id=chapter_id,
                    document_id=document_id,
                    project_id=project_id,
                    title=draft.title,
                    order=draft.order,
                    start_chunk_order=start_order,
                    end_chunk_order=end_order,
                )
            )
        return ParsedDocument(document=document, chapters=chapters, chunks=chunks)

    def parse_docx(self, project_id: str, filename: str, data: bytes) -> ParsedDocument:
        """Reserve DOCX support for a later parser implementation."""

        raise NotImplementedError("DOCX parsing is reserved for a later MVP slice")

    def parse_pdf(self, project_id: str, filename: str, data: bytes) -> ParsedDocument:
        """Reserve PDF support for a later parser implementation."""

        raise NotImplementedError("PDF parsing is reserved for a later MVP slice")

    def _find_chapters(self, text: str) -> list[_ChapterDraft]:
        headings = self._find_heading_lines(text)
        if not headings:
            return [_ChapterDraft(title="Default Chapter", start=0, end=len(text), order=0)]

        drafts: list[_ChapterDraft] = []
        for index, (title, _title_start, body_start) in enumerate(headings):
            next_start = headings[index + 1][1] if index + 1 < len(headings) else len(text)
            drafts.append(
                _ChapterDraft(
                    title=title,
                    start=body_start,
                    end=next_start,
                    order=index,
                )
            )
        return drafts

    def _find_heading_lines(self, text: str) -> list[tuple[str, int, int]]:
        headings: list[tuple[str, int, int]] = []
        offset = 0
        for line in text.splitlines(keepends=True):
            title = self._normalize_heading(line)
            if title is not None:
                headings.append((title, offset, offset + len(line)))
            offset += len(line)
        if offset < len(text):
            title = self._normalize_heading(text[offset:])
            if title is not None:
                headings.append((title, offset, len(text)))
        return headings

    def _normalize_heading(self, line: str) -> str | None:
        title = line.strip().lstrip("\ufeff").strip()
        title = re.sub(r"[\s\u3000]+", " ", title)
        title = _NOISE_PREFIX_RE.sub("", title).strip()
        if not title or len(title) > _TITLE_MAX_CHARS:
            return None
        if CHAPTER_RE.fullmatch(title) is None:
            return None
        return title

    def _chunks_for_chapter(
        self,
        project_id: str,
        document_id: str,
        chapter_title: str,
        chapter_order: int,
        text: str,
        start: int,
        end: int,
        starting_order: int,
    ) -> list[SourceChunkV1]:
        body = text[start:end]
        chunks: list[SourceChunkV1] = []
        for paragraph_start, paragraph_text in self._paragraph_spans(body):
            for span_start, span_end in self._split_long_span(paragraph_text):
                chunk_text = paragraph_text[span_start:span_end].strip("\n")
                if not chunk_text.strip():
                    continue
                leading_newlines = len(paragraph_text[span_start:span_end]) - len(
                    paragraph_text[span_start:span_end].lstrip("\n")
                )
                trailing_newlines = len(paragraph_text[span_start:span_end]) - len(
                    paragraph_text[span_start:span_end].rstrip("\n")
                )
                char_start = start + paragraph_start + span_start + leading_newlines
                char_end = start + paragraph_start + span_end - trailing_newlines
                order = starting_order + len(chunks)
                chunks.append(
                    SourceChunkV1(
                        chunk_id=stable_id(
                            "chunk",
                            document_id,
                            order,
                            checksum_text(chunk_text),
                        ),
                        document_id=document_id,
                        chapter_id=stable_id("chapter", document_id, chapter_order, chapter_title),
                        project_id=project_id,
                        order=order,
                        text=chunk_text,
                        source_page=None,
                        char_start=char_start,
                        char_end=char_end,
                        checksum=checksum_text(chunk_text),
                    )
                )
        return chunks

    def _paragraph_spans(self, body: str) -> list[tuple[int, str]]:
        spans: list[tuple[int, str]] = []
        for match in re.finditer(r"\S(?:.*(?:\n(?!\s*\n).*)*)", body):
            raw_text = match.group(0)
            leading_newlines = len(raw_text) - len(raw_text.lstrip("\n"))
            trailing_newlines = len(raw_text) - len(raw_text.rstrip("\n"))
            paragraph_text = raw_text.strip("\n")
            if not paragraph_text.strip():
                continue
            paragraph_start = match.start() + leading_newlines
            paragraph_end = match.end() - trailing_newlines
            spans.append((paragraph_start, body[paragraph_start:paragraph_end]))
        return spans

    def _split_long_span(self, text: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        start = 0
        while start < len(text):
            remaining = len(text) - start
            if remaining <= _MAX_CHARS_PER_CHUNK:
                spans.append((start, len(text)))
                break

            split_at = self._find_sentence_boundary(text, start)
            spans.append((start, split_at))
            start = split_at
            while start < len(text) and text[start] == "\n":
                start += 1
        return spans

    def _find_sentence_boundary(self, text: str, start: int) -> int:
        preferred_start = min(start + _MIN_SENTENCE_CHUNK_CHARS, len(text))
        preferred_end = min(start + _MAX_CHARS_PER_CHUNK, len(text))
        for index in range(preferred_end - 1, preferred_start - 1, -1):
            if text[index] in _SENTENCE_ENDINGS:
                return index + 1

        lookahead_end = min(start + _MAX_SENTENCE_LOOKAHEAD_CHARS, len(text))
        for index in range(preferred_end, lookahead_end):
            if text[index] in _SENTENCE_ENDINGS:
                return min(index + 1, start + _MAX_CHARS_PER_CHUNK)

        return min(start + _MAX_CHARS_PER_CHUNK, len(text))
