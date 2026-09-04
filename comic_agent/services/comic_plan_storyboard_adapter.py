"""Bridge approved comic plans into the existing image-production proposal contract."""

from __future__ import annotations

from collections.abc import Mapping

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.comic_planning import PanelPlanV1
from comic_agent.schemas.comic_production import (
    ComicPanelProposalV1,
    ComicProductionRequestV1,
    ComicStoryboardProposalV1,
    IdentityAnchorMode,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.visual import PageSpecV1, PanelSpecV1, PanelTextOverlayV1
from comic_agent.services.context_builder import AgentContext
from comic_agent.services.id_service import checksum_text, stable_id
from comic_agent.services.visual_prompt_text import visual_expression_without_overlay_text

_TEXT_REGIONS = ("top_left", "top_right", "bottom_left", "bottom_right")


class ComicPlanStoryboardAdapter:
    """Adapt provider-neutral PanelPlan records without adding narrative facts."""

    adapter_id = "comic-plan-storyboard-adapter-v1"

    def adapt(
        self,
        *,
        context: AgentContext,
        document_id: str,
        request: ComicProductionRequestV1,
        reading_direction: str,
        panel_plans: list[PanelPlanV1],
        page_panel_counts: list[int] | None = None,
    ) -> ComicStoryboardProposalV1:
        if not panel_plans:
            raise ValueError("comic plan must contain at least one panel")
        panel_limit = request.panels_per_page * request.max_pages
        if len(panel_plans) > panel_limit:
            raise ValueError(f"comic plan exceeds the configured {panel_limit}-panel limit")
        if any(panel.project_id != context.project_id for panel in panel_plans):
            raise ValueError("comic plan and source context must belong to the same project")
        panel_ids = [panel.panel_id for panel in panel_plans]
        if len(panel_ids) != len(set(panel_ids)):
            raise ValueError("comic plan panel IDs must be unique")

        page_ranges = self._page_ranges(
            panel_count=len(panel_plans),
            request=request,
            page_panel_counts=page_panel_counts,
        )
        page_index_by_panel_order = {
            panel_order: page_index
            for page_index, (start, end) in enumerate(page_ranges)
            for panel_order in range(start, end)
        }

        chunks_by_id = {chunk.chunk_id: chunk for chunk in context.chunks}
        character_asset_ids = {
            asset.entity_id
            for asset in request.selected_assets
            if asset.role in {"character_identity", "character_outfit"}
        }
        missing_characters = sorted(
            {
                character_id
                for panel in panel_plans
                for character_id in panel.character_ids
                if character_id not in character_asset_ids
            }
        )
        if missing_characters and request.identity_anchor_mode == IdentityAnchorMode.AUTO:
            raise ValueError(
                "comic plan characters require selected identity assets: "
                + ", ".join(missing_characters)
            )

        proposal_id = stable_id(
            "planned-storyboard",
            context.project_id,
            document_id,
            checksum_text(request.model_dump_json()),
            *(str(count) for count in page_panel_counts or []),
            *panel_ids,
        )
        panel_proposals: list[ComicPanelProposalV1] = []
        last_panel_by_cast_and_place: dict[tuple[frozenset[str], str | None], str] = {}
        seen_panel_ids: set[str] = set()
        for order, plan in enumerate(panel_plans):
            source_quote = self._source_quote(plan.evidence_refs, chunks_by_id)
            page_index = page_index_by_panel_order[order]
            page_id = stable_id("page", proposal_id, page_index)
            explicit_parent = plan.previous_panel_reference
            if explicit_parent is not None and explicit_parent not in seen_panel_ids:
                raise ValueError(
                    f"panel {plan.panel_id} continuity reference must point to an earlier panel"
                )
            cast_and_place = (
                frozenset(plan.character_ids),
                plan.location_entity_id or plan.background,
            )
            inferred_parent = (
                last_panel_by_cast_and_place.get(cast_and_place) if plan.character_ids else None
            )
            continuity_parent = (
                explicit_parent or inferred_parent if request.continuity_enabled else None
            )
            must_show = self._must_show(plan)
            text_overlays = self._source_grounded_overlays(plan, source_quote)
            panel = PanelSpecV1(
                panel_id=plan.panel_id,
                page_id=page_id,
                scene_id=plan.scene_id,
                source_chunk_ids=list(
                    dict.fromkeys(evidence.chunk_id for evidence in plan.evidence_refs)
                ),
                story_time_ref=(
                    f"timeline:{plan.timeline_bundle_id}:" + ",".join(plan.related_event_ids)
                ),
                character_bindings={
                    f"character_{index + 1}": character_id
                    for index, character_id in enumerate(plan.character_ids)
                },
                shot_type=plan.shot_type,
                camera_angle=plan.camera_angle,
                must_show=must_show,
                must_not_show=[
                    "events, people, dialogue, or locations unsupported by approved evidence"
                ],
                reserved_text_regions=[],
                text_overlays=text_overlays,
            )
            panel_proposals.append(
                ComicPanelProposalV1(
                    panel=panel,
                    evidence_refs=list(plan.evidence_refs),
                    source_quote=source_quote,
                    visual_expression=visual_expression_without_overlay_text(
                        self._visual_expression(plan), text_overlays
                    ),
                    continuity_parent_panel_id=continuity_parent,
                )
            )
            seen_panel_ids.add(plan.panel_id)
            if plan.character_ids:
                last_panel_by_cast_and_place[cast_and_place] = plan.panel_id

        pages: list[PageSpecV1] = []
        for page_index, (start, end) in enumerate(page_ranges):
            page_panels = panel_proposals[start:end]
            chunk_ids = list(
                dict.fromkeys(
                    chunk_id
                    for proposal in page_panels
                    for chunk_id in proposal.panel.source_chunk_ids
                )
            )
            pages.append(
                PageSpecV1(
                    page_id=page_panels[0].panel.page_id,
                    project_id=context.project_id,
                    document_id=document_id,
                    chapter_ids=list(
                        dict.fromkeys(chunks_by_id[chunk_id].chapter_id for chunk_id in chunk_ids)
                    ),
                    source_chunk_ids=chunk_ids,
                    order=page_index,
                    panel_ids=[proposal.panel.panel_id for proposal in page_panels],
                    reading_direction=reading_direction,
                    layout="2x3" if request.panels_per_page == 6 else "grid",
                )
            )

        return ComicStoryboardProposalV1(
            proposal_id=proposal_id,
            project_id=context.project_id,
            document_id=document_id,
            planner_id=self.adapter_id,
            source_chunk_ids=list(
                dict.fromkeys(
                    chunk_id
                    for proposal in panel_proposals
                    for chunk_id in proposal.panel.source_chunk_ids
                )
            ),
            pages=pages,
            panels=panel_proposals,
        )

    @staticmethod
    def _page_ranges(
        *,
        panel_count: int,
        request: ComicProductionRequestV1,
        page_panel_counts: list[int] | None,
    ) -> list[tuple[int, int]]:
        if page_panel_counts is None:
            return [
                (start, min(start + request.panels_per_page, panel_count))
                for start in range(0, panel_count, request.panels_per_page)
            ]
        if not page_panel_counts or any(count < 1 for count in page_panel_counts):
            raise ValueError("page panel counts must contain only positive values")
        if len(page_panel_counts) > request.max_pages:
            raise ValueError("page panel counts exceed the configured maximum page count")
        if any(count > request.panels_per_page for count in page_panel_counts):
            raise ValueError("page panel count exceeds the configured panels per page")
        if sum(page_panel_counts) != panel_count:
            raise ValueError("page panel counts must account for every planned panel")
        ranges: list[tuple[int, int]] = []
        start = 0
        for count in page_panel_counts:
            end = start + count
            ranges.append((start, end))
            start = end
        return ranges

    @staticmethod
    def _source_quote(
        evidence_refs: list[EvidenceRefV1], chunks_by_id: Mapping[str, SourceChunkV1]
    ) -> str:
        excerpts: list[str] = []
        for evidence in evidence_refs:
            chunk = chunks_by_id.get(evidence.chunk_id)
            if chunk is None:
                raise ValueError(
                    f"comic plan evidence is outside source context: {evidence.chunk_id}"
                )
            chunk_text = chunk.text
            if evidence.quote_start is not None and evidence.quote_end is not None:
                if evidence.quote_end > len(chunk_text):
                    raise ValueError(
                        f"comic plan evidence range exceeds chunk: {evidence.chunk_id}"
                    )
                excerpt = chunk_text[evidence.quote_start : evidence.quote_end]
                if evidence.quote_text is not None and evidence.quote_text != excerpt:
                    raise ValueError(f"comic plan evidence quote mismatch: {evidence.chunk_id}")
            elif evidence.quote_text is not None:
                if evidence.quote_text not in chunk_text:
                    raise ValueError(f"comic plan evidence quote is absent: {evidence.chunk_id}")
                excerpt = evidence.quote_text
            else:
                excerpt = chunk_text
            if excerpt.strip() and excerpt not in excerpts:
                excerpts.append(excerpt)
        if not excerpts:
            raise ValueError("comic plan evidence contains no source text")
        return "\n".join(excerpts)

    @staticmethod
    def _must_show(plan: PanelPlanV1) -> list[str]:
        facts = [plan.narrative_beat]
        facts.extend(
            f"{character}: {action}" for character, action in plan.character_actions.items()
        )
        facts.extend(
            f"{character} expression: {expression}"
            for character, expression in plan.expressions.items()
        )
        if plan.background:
            facts.append(f"background: {plan.background}")
        facts.extend(f"object: {item}" for item in plan.objects)
        if plan.atmosphere:
            facts.append(f"atmosphere: {plan.atmosphere}")
        facts.extend(plan.continuity_notes)
        return list(dict.fromkeys(fact for fact in facts if fact.strip()))

    @classmethod
    def _visual_expression(cls, plan: PanelPlanV1) -> str:
        details = [
            f"Scene goal: {plan.panel_purpose}",
            f"Visible moment: {plan.narrative_beat}",
            f"Framing: {plan.composition}",
            f"Canvas ratio: {plan.aspect_ratio}",
            *cls._must_show(plan),
        ]
        return ". ".join(dict.fromkeys(details))

    @staticmethod
    def _source_grounded_overlays(plan: PanelPlanV1, source_quote: str) -> list[PanelTextOverlayV1]:
        candidates = [("dialogue", text) for text in plan.dialogue]
        candidates.extend(
            ("caption", text) for text in (plan.narration, plan.caption) if text is not None
        )
        overlays: list[PanelTextOverlayV1] = []
        seen: set[str] = set()
        for kind, text in candidates:
            if text in seen or text not in source_quote:
                continue
            seen.add(text)
            start = source_quote.index(text)
            overlays.append(
                PanelTextOverlayV1(
                    overlay_id=stable_id("overlay", plan.panel_id, len(overlays), text),
                    kind=kind,
                    text=text,
                    speaker_entity_id=(
                        plan.character_ids[0]
                        if kind == "dialogue" and len(plan.character_ids) == 1
                        else None
                    ),
                    source_quote_start=start,
                    source_quote_end=start + len(text),
                    preferred_region=_TEXT_REGIONS[len(overlays) % len(_TEXT_REGIONS)],
                )
            )
        return overlays
