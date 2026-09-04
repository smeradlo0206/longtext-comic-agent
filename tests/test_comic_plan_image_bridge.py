"""Regression coverage for Comic Planning to local FLUX.2 handoff."""

from pathlib import Path

import pytest
from PIL import Image

from comic_agent.database.base import Base
from comic_agent.database.session import make_engine, make_session_factory
from comic_agent.repositories.comic_production_repository import ComicProductionRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.comic_planning import PanelPlanV1
from comic_agent.schemas.comic_production import (
    ComicProductionRequestV1,
    IdentityAnchorMode,
)
from comic_agent.schemas.image_workflow import GenerationSettings, SelectedAsset
from comic_agent.schemas.source import FidelityMode, ProjectSpecV1, ProjectType
from comic_agent.services.comic_plan_storyboard_adapter import ComicPlanStoryboardAdapter
from comic_agent.services.comic_production_coordinator import ComicProductionCoordinator
from comic_agent.services.context_builder import ContextBuilder
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.long_text_comic_compiler import LongTextComicCompiler
from flux2_agent.catalog import write_catalog
from flux2_agent.queueing import QueueStore


def _project() -> ProjectSpecV1:
    return ProjectSpecV1(
        id="project-1",
        name="Planned comic",
        project_type=ProjectType.LONG_NOVEL,
        fidelity_mode=FidelityMode.CANON_STRICT,
        output_format="PAGES",
        reading_direction="LTR",
        allow_new_events=False,
        allow_new_dialogue=False,
        allow_event_reordering=False,
        allow_visual_compression=True,
        allow_dialogue_splitting=True,
        require_source_traceability=True,
        max_auto_repairs=2,
        budget_limit=None,
    )


def _assets() -> list[SelectedAsset]:
    return [
        SelectedAsset(
            slot="CHAR_A",
            asset_id="asset-001",
            entity_id="character.lin",
            role="character_identity",
            description="Lin's canonical face, hair, body, and clothes",
            display_name="Lin",
        ),
        SelectedAsset(
            slot="SCENE_A",
            asset_id="asset-002",
            entity_id="location.tea-room",
            role="scene",
            description="The canonical tea room layout",
            display_name="tea room",
        ),
    ]


def _request(document_id: str) -> ComicProductionRequestV1:
    return ComicProductionRequestV1(
        document_id=document_id,
        panels_per_page=6,
        max_pages=1,
        comic_style="fully colored manga with consistent clean linework",
        global_prompt="keep character identity and room layout consistent",
        selected_assets=_assets(),
        generation=GenerationSettings(width=256, height=256, steps=1, attempts=1),
    )


def _source():  # type: ignore[no-untyped-def]
    return DocumentParser().parse_txt(
        project_id="project-1",
        filename="story.txt",
        text='Lin enters the tea room and says "Hello."',
    )


def _panel(panel_id: str, evidence: EvidenceRefV1) -> PanelPlanV1:
    return PanelPlanV1(
        panel_id=panel_id,
        project_id="project-1",
        scene_id="scene-1",
        index=0,
        storybible_bundle_id="storybible-1",
        timeline_bundle_id="timeline-1",
        panel_purpose="Show the approved arrival event",
        narrative_beat="Lin enters the tea room",
        aspect_ratio="1:1",
        shot_type="MEDIUM",
        camera_angle="EYE_LEVEL",
        composition="Lin crosses the doorway on the left",
        character_ids=["character.lin"],
        character_actions={"character.lin": "enters the tea room"},
        expressions={"character.lin": "calm"},
        background="tea room",
        location_entity_id="location.tea-room",
        objects=["teacup"],
        atmosphere="quiet evening",
        dialogue=["Hello."],
        continuity_notes=["Keep Lin's clothes and the doorway unchanged"],
        related_event_ids=["event-1"],
        evidence_refs=[evidence],
    )


def test_planned_panels_compile_to_flux_workflow_with_assets_and_continuity() -> None:
    parsed = _source()
    chunk = parsed.chunks[0]
    evidence = EvidenceRefV1(
        chunk_id=chunk.chunk_id,
        quote_start=0,
        quote_end=len(chunk.text),
        quote_text=chunk.text,
    )
    panels = [_panel("panel-1", evidence), _panel("panel-2", evidence)]
    context = ContextBuilder().from_chunks("project-1", parsed.chunks)
    request = _request(parsed.document.document_id)

    proposal = ComicPlanStoryboardAdapter().adapt(
        context=context,
        document_id=parsed.document.document_id,
        request=request,
        reading_direction="LTR",
        panel_plans=panels,
    )
    manifest = LongTextComicCompiler().compile(
        project=_project(),
        request=request,
        context=context,
        proposal=proposal,
    )

    assert proposal.planner_id == "comic-plan-storyboard-adapter-v1"
    assert proposal.panels[1].continuity_parent_panel_id == "panel-1"
    assert proposal.panels[0].panel.text_overlays[0].text == "Hello."
    assert [reference.asset_id for reference in manifest.workflow_job.shots[0].references] == [
        "asset-001",
        "asset-002",
    ]
    assert "Lin enters the tea room" in manifest.workflow_job.shots[0].prompt
    assert "provider" not in proposal.panels[0].panel.model_dump()
    assert manifest.prompt_specs[0].provider == "local-flux2-klein"


def test_dialogue_copy_exists_only_in_overlay_not_image_prompts() -> None:
    dialogue = "同学，欢迎来到中国科大！"
    source_text = (
        "九月清晨，研究生新生林夏拿着报到材料、拖着蓝色行李箱走进校园，"
        f"红马甲志愿者陈舟迎上来，笑着说：“{dialogue}”"
    )
    parsed = DocumentParser().parse_txt(
        project_id="project-1", filename="story.txt", text=source_text
    )
    chunk = parsed.chunks[0]
    evidence = EvidenceRefV1(chunk_id=chunk.chunk_id, quote_text=chunk.text)
    context = ContextBuilder().from_chunks("project-1", parsed.chunks)
    request = _request(parsed.document.document_id)
    panel = _panel("panel-1", evidence).model_copy(
        update={"narrative_beat": source_text, "dialogue": [dialogue]}
    )

    proposal = ComicPlanStoryboardAdapter().adapt(
        context=context,
        document_id=parsed.document.document_id,
        request=request,
        reading_direction="LTR",
        panel_plans=[panel],
    )
    manifest = LongTextComicCompiler().compile(
        project=_project(), request=request, context=context, proposal=proposal
    )

    proposed_panel = proposal.panels[0]
    assert proposed_panel.panel.text_overlays[0].text == dialogue
    assert dialogue not in proposed_panel.visual_expression
    assert "报到材料" not in proposed_panel.visual_expression
    assert "纯色硬壳资料夹" in proposed_panel.visual_expression
    assert "做出自然交流的表情和手势" in proposed_panel.visual_expression
    assert dialogue not in manifest.workflow_job.shots[0].prompt
    assert dialogue not in manifest.prompt_specs[0].provider_prompt
    assert LongTextComicCompiler.compiler_id == "longtext-comic-compiler-v11"


def test_planned_panel_rejects_untraceable_evidence() -> None:
    parsed = _source()
    chunk = parsed.chunks[0]
    bad_evidence = EvidenceRefV1(
        chunk_id=chunk.chunk_id,
        quote_start=0,
        quote_end=3,
        quote_text="bad",
    )
    context = ContextBuilder().from_chunks("project-1", parsed.chunks)

    with pytest.raises(ValueError, match="evidence quote mismatch"):
        ComicPlanStoryboardAdapter().adapt(
            context=context,
            document_id=parsed.document.document_id,
            request=_request(parsed.document.document_id),
            reading_direction="LTR",
            panel_plans=[_panel("panel-1", bad_evidence)],
        )


def test_planned_panel_allows_text_defined_character_when_identity_anchors_are_off() -> None:
    parsed = _source()
    chunk = parsed.chunks[0]
    evidence = EvidenceRefV1(chunk_id=chunk.chunk_id, quote_text=chunk.text)
    context = ContextBuilder().from_chunks("project-1", parsed.chunks)
    request = _request(parsed.document.document_id).model_copy(
        update={
            "selected_assets": [_assets()[1]],
            "identity_anchor_mode": IdentityAnchorMode.OFF,
        }
    )

    proposal = ComicPlanStoryboardAdapter().adapt(
        context=context,
        document_id=parsed.document.document_id,
        request=request,
        reading_direction="LTR",
        panel_plans=[_panel("panel-1", evidence)],
    )

    assert proposal.panels[0].panel.character_bindings == {
        "character_1": "character.lin"
    }


def test_planned_panel_requires_character_asset_when_identity_anchors_are_auto() -> None:
    parsed = _source()
    chunk = parsed.chunks[0]
    evidence = EvidenceRefV1(chunk_id=chunk.chunk_id, quote_text=chunk.text)
    context = ContextBuilder().from_chunks("project-1", parsed.chunks)
    request = _request(parsed.document.document_id).model_copy(
        update={
            "selected_assets": [_assets()[1]],
            "identity_anchor_mode": IdentityAnchorMode.AUTO,
        }
    )

    with pytest.raises(ValueError, match="require selected identity assets"):
        ComicPlanStoryboardAdapter().adapt(
            context=context,
            document_id=parsed.document.document_id,
            request=request,
            reading_direction="LTR",
            panel_plans=[_panel("panel-1", evidence)],
        )


def test_coordinator_enqueues_planned_panels_idempotently(tmp_path: Path) -> None:
    reference_root = tmp_path / "inputs" / "references"
    reference_root.mkdir(parents=True)
    Image.new("RGB", (16, 16), "white").save(reference_root / "character.png")
    Image.new("RGB", (16, 16), "gray").save(reference_root / "room.png")
    write_catalog(tmp_path)

    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'comic.db'}")
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    source_repository = SourceRepository(session)
    queue = QueueStore(tmp_path / "queue")
    coordinator = ComicProductionCoordinator(
        workspace=tmp_path,
        source_repository=source_repository,
        production_repository=ComicProductionRepository(session),
        queue_store=queue,
    )
    try:
        parsed = _source()
        source_repository.create_project(_project())
        source_repository.import_parsed_document(parsed)
        chunk = parsed.chunks[0]
        evidence = EvidenceRefV1(
            chunk_id=chunk.chunk_id,
            quote_start=0,
            quote_end=len(chunk.text),
            quote_text=chunk.text,
        )
        kwargs = {
            "project_id": "project-1",
            "request": _request(parsed.document.document_id),
            "panel_plans": [_panel("panel-1", evidence)],
        }

        first = coordinator.compile_planned_and_enqueue(**kwargs)
        second = coordinator.compile_planned_and_enqueue(**kwargs)

        assert first.run_id == second.run_id
        assert first.manifest.proposal.planner_id == "comic-plan-storyboard-adapter-v1"
        assert len(queue.list_items("pending")) == 1
    finally:
        session.close()
        engine.dispose()
