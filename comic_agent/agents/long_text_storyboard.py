"""Proposal-only deterministic storyboard planning for bounded long-text context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import ceil

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.comic_production import (
    ComicPanelProposalV1,
    ComicPlannerMode,
    ComicProductionRequestV1,
    ComicStoryboardProposalV1,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.visual import PageSpecV1, PanelSpecV1, PanelTextOverlayV1
from comic_agent.services.context_builder import AgentContext
from comic_agent.services.id_service import checksum_text, stable_id

_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+(?:[。！？!?；;][”」』\"]?|$)")
_SHOT_TYPES = ("wide establishing shot", "medium shot", "medium close-up", "close-up")
_CAMERA_ANGLES = ("eye level", "three-quarter view", "eye level", "slight low angle")
_DIALOGUE_RE = re.compile(r"[“「『\"]([^”」』\"]{1,500})[”」』\"]")
_TEXT_REGIONS = ("top_left", "top_right", "top_left", "top_right")


@dataclass(frozen=True)
class _SourceExcerpt:
    chunk: SourceChunkV1
    quote: str
    start: int
    end: int


class LongTextStoryboardAgent:
    """Create an extractive, evidence-backed storyboard proposal without database access."""

    agent_id = "deterministic-extractive-storyboard-v4"

    def propose(
        self,
        *,
        context: AgentContext,
        document_id: str,
        request: ComicProductionRequestV1,
        reading_direction: str,
    ) -> ComicStoryboardProposalV1:
        if request.planner_mode != ComicPlannerMode.DETERMINISTIC_EXTRACTIVE:
            raise ValueError("LLM_PROPOSAL requires an explicitly configured storyboard provider")
        if context.project_id == "" or not context.chunks:
            raise ValueError("storyboard planning requires non-empty bounded source context")
        if any(chunk.project_id != context.project_id for chunk in context.chunks):
            raise ValueError("storyboard context contains a cross-project source chunk")
        if any(chunk.document_id != document_id for chunk in context.chunks):
            raise ValueError("storyboard context contains a different source document")

        excerpts = [
            excerpt
            for chunk in context.chunks
            for excerpt in self._chunk_excerpts(chunk)
        ]
        if not excerpts:
            raise ValueError("selected source context contains no visualizable text")
        panel_limit = request.panels_per_page * request.max_pages
        selected = self._sample_in_order(excerpts, min(panel_limit, len(excerpts)))
        request_fingerprint = checksum_text(request.model_dump_json())
        proposal_id = stable_id(
            "storyboard",
            context.project_id,
            document_id,
            request_fingerprint,
            *[item.chunk.chunk_id for item in selected],
        )

        panels: list[ComicPanelProposalV1] = []
        last_panel_by_cast: dict[tuple[frozenset[str], str | None], str] = {}
        active_scene_entity_id: str | None = None
        for index, excerpt in enumerate(selected):
            page_index = index // request.panels_per_page
            page_id = stable_id("page", proposal_id, page_index)
            panel_id = stable_id("panel", proposal_id, index, excerpt.chunk.chunk_id)
            character_bindings = self._character_bindings(excerpt.quote, request)
            current_bindings = set(character_bindings.values())
            for asset in request.selected_assets:
                if (
                    asset.role == "scene"
                    and asset.display_name
                    and asset.display_name in excerpt.quote
                ):
                    active_scene_entity_id = asset.entity_id
            cast_key = (frozenset(current_bindings), active_scene_entity_id)
            parent_id = (
                last_panel_by_cast.get(cast_key)
                if request.continuity_enabled and current_bindings
                else None
            )
            panel = PanelSpecV1(
                panel_id=panel_id,
                page_id=page_id,
                scene_id=stable_id("scene", proposal_id, excerpt.chunk.chapter_id),
                source_chunk_ids=[excerpt.chunk.chunk_id],
                story_time_ref=f"source-order:{excerpt.chunk.order}",
                character_bindings=character_bindings,
                shot_type=_SHOT_TYPES[index % len(_SHOT_TYPES)],
                camera_angle=_CAMERA_ANGLES[index % len(_CAMERA_ANGLES)],
                must_show=[excerpt.quote],
                must_not_show=["events, people, dialogue, or locations unsupported by the source"],
                reserved_text_regions=[],
                text_overlays=self._text_overlays(
                    excerpt=excerpt,
                    request=request,
                    panel_id=panel_id,
                ),
            )
            panels.append(
                ComicPanelProposalV1(
                    panel=panel,
                    evidence_refs=[
                        EvidenceRefV1(
                            chunk_id=excerpt.chunk.chunk_id,
                            quote_start=excerpt.start,
                            quote_end=excerpt.end,
                            quote_text=excerpt.quote,
                        )
                    ],
                    source_quote=excerpt.quote,
                    visual_expression=(
                        "把这段原文中明确发生的动作、人物状态和环境转化为一个自然的"
                        "单幅漫画镜头；不要在画面中排版或复写原文文字：" + excerpt.quote
                    ),
                    continuity_parent_panel_id=parent_id,
                )
            )
            if current_bindings:
                last_panel_by_cast[cast_key] = panel_id

        pages: list[PageSpecV1] = []
        page_count = ceil(len(panels) / request.panels_per_page)
        chunks_by_id = {chunk.chunk_id: chunk for chunk in context.chunks}
        for page_index in range(page_count):
            page_panels = panels[
                page_index * request.panels_per_page : (page_index + 1)
                * request.panels_per_page
            ]
            chunk_ids = list(
                dict.fromkeys(
                    chunk_id
                    for item in page_panels
                    for chunk_id in item.panel.source_chunk_ids
                )
            )
            chapter_ids = list(
                dict.fromkeys(chunks_by_id[chunk_id].chapter_id for chunk_id in chunk_ids)
            )
            pages.append(
                PageSpecV1(
                    page_id=page_panels[0].panel.page_id,
                    project_id=context.project_id,
                    document_id=document_id,
                    chapter_ids=chapter_ids,
                    source_chunk_ids=chunk_ids,
                    order=page_index,
                    panel_ids=[item.panel.panel_id for item in page_panels],
                    reading_direction=reading_direction,
                    layout="2x3" if request.panels_per_page == 6 else "grid",
                )
            )

        return ComicStoryboardProposalV1(
            proposal_id=proposal_id,
            project_id=context.project_id,
            document_id=document_id,
            planner_id=self.agent_id,
            source_chunk_ids=[chunk.chunk_id for chunk in context.chunks],
            pages=pages,
            panels=panels,
        )

    @staticmethod
    def _text_overlays(
        *,
        excerpt: _SourceExcerpt,
        request: ComicProductionRequestV1,
        panel_id: str,
    ) -> list[PanelTextOverlayV1]:
        overlays: list[PanelTextOverlayV1] = []
        character_assets = [
            item
            for item in request.selected_assets
            if item.role in {"character_identity", "character_outfit"}
        ]
        for index, match in enumerate(_DIALOGUE_RE.finditer(excerpt.quote)):
            before = excerpt.quote[: match.start()]
            named = [
                (before.rfind(item.display_name), item)
                for item in character_assets
                if item.display_name and item.display_name in before
            ]
            speaker = max(named, key=lambda candidate: candidate[0])[1].entity_id if named else None
            if speaker is None and len(character_assets) == 1:
                speaker = character_assets[0].entity_id
            text_start = excerpt.start + match.start(1)
            overlays.append(
                PanelTextOverlayV1(
                    overlay_id=stable_id("overlay", panel_id, index, match.group(1)),
                    kind="dialogue",
                    text=match.group(1),
                    speaker_entity_id=speaker,
                    source_quote_start=text_start,
                    source_quote_end=text_start + len(match.group(1)),
                    preferred_region=_TEXT_REGIONS[index % len(_TEXT_REGIONS)],
                )
            )
        return overlays

    @staticmethod
    def _chunk_excerpts(chunk: SourceChunkV1) -> list[_SourceExcerpt]:
        excerpts: list[_SourceExcerpt] = []
        for match in _SENTENCE_RE.finditer(chunk.text):
            raw = match.group(0)
            left_trim = len(raw) - len(raw.lstrip())
            right_trim = len(raw) - len(raw.rstrip())
            start = match.start() + left_trim
            end = match.end() - right_trim
            if end <= start:
                continue
            excerpts.append(
                _SourceExcerpt(
                    chunk=chunk,
                    quote=chunk.text[start:end],
                    start=start,
                    end=end,
                )
            )
        return excerpts

    @staticmethod
    def _sample_in_order(
        excerpts: list[_SourceExcerpt],
        count: int,
    ) -> list[_SourceExcerpt]:
        if count >= len(excerpts):
            return excerpts
        if count == 1:
            return [excerpts[0]]
        selected: list[_SourceExcerpt] = []
        for bucket in range(count):
            start = bucket * len(excerpts) // count
            end = max(start + 1, (bucket + 1) * len(excerpts) // count)
            candidates = excerpts[start:end]
            if bucket == 0:
                selected.append(candidates[0])
                continue
            if bucket == count - 1:
                selected.append(candidates[-1])
                continue
            selected.append(
                max(
                    enumerate(candidates),
                    key=lambda item: (
                        LongTextStoryboardAgent._visual_score(item[1].quote),
                        -item[0],
                    ),
                )[1]
            )
        return selected

    @staticmethod
    def _visual_score(quote: str) -> int:
        action_terms = (
            "醒",
            "起身",
            "穿",
            "整理",
            "走",
            "坐",
            "站",
            "推开",
            "拿",
            "放",
            "看",
            "抬眼",
            "倒",
            "喝",
            "举杯",
            "交谈",
            "说",
            "笑",
            "伸手",
            "walk",
            "sit",
            "stand",
            "look",
            "drink",
            "pour",
            "open",
        )
        actor_terms = ("男生", "女生", "女孩", "少女", "男人", "两人", "两个人", "他", "她")
        score = sum(3 for term in action_terms if term.lower() in quote.lower())
        score += sum(2 for term in actor_terms if term in quote)
        if any(term in quote for term in ("没有", "只有", "仍沉在", "不应该")):
            score -= 3
        return score

    @staticmethod
    def _character_bindings(
        quote: str,
        request: ComicProductionRequestV1,
    ) -> dict[str, str]:
        character_assets = [
            asset
            for asset in request.selected_assets
            if asset.role in {"character_identity", "character_outfit"}
        ]
        if any(term in quote for term in ("两人", "两个人", "双方")):
            return {asset.slot: asset.entity_id for asset in character_assets}

        bindings: dict[str, str] = {}
        for asset in character_assets:
            label = asset.display_name or ""
            description = asset.description
            gender_markers = ("男", "女", "少年", "少女", "先生", "小姐")
            gender_source = (
                label if any(term in label for term in gender_markers) else description
            )
            male_coded = any(term in gender_source for term in ("男", "少年", "先生"))
            female_coded = any(term in gender_source for term in ("女", "少女", "小姐"))
            literal_match = bool(label and label in quote)
            male_match = male_coded and any(
                term in quote for term in ("男生", "男人", "少年", "他")
            )
            female_match = female_coded and any(
                term in quote for term in ("女生", "女孩", "少女", "她")
            )
            if literal_match or male_match or female_match:
                bindings[asset.slot] = asset.entity_id
        return bindings
