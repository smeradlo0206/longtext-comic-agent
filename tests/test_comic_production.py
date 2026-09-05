import json
import os
import stat
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from comic_agent.agents.long_text_storyboard import LongTextStoryboardAgent
from comic_agent.config import get_settings
from comic_agent.database.base import Base
from comic_agent.database.session import make_engine, make_session_factory
from comic_agent.main import create_app
from comic_agent.repositories.comic_production_repository import ComicProductionRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.comic_production import (
    ComicProductionRequestV1,
    DialogueLayoutSettingsV1,
    IdentityAnchorMode,
)
from comic_agent.schemas.image_workflow import GenerationSettings, SelectedAsset
from comic_agent.schemas.source import FidelityMode, ProjectSpecV1, ProjectType
from comic_agent.services.comic_page_composer import ComicPageComposer
from comic_agent.services.comic_production_coordinator import ComicProductionCoordinator
from comic_agent.services.context_builder import ContextBuilder
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.long_text_comic_compiler import LongTextComicCompiler
from flux2_agent.catalog import load_catalog, write_catalog
from flux2_agent.planning import build_plan
from flux2_agent.queueing import QueueStore
from flux2_agent.workflow import run_workflow


def source_text(paragraphs: int = 18) -> str:
    body = [
        f"傍晚第{index}分钟，林夏和陈野沿着旧图书馆走廊寻找蓝色文件夹。"
        for index in range(paragraphs)
    ]
    return "第一章 旧馆\n\n" + "\n\n".join(body)


def selected_asset() -> SelectedAsset:
    return SelectedAsset(
        slot="CHAR_A",
        asset_id="asset-001",
        entity_id="character.lin-xia",
        role="character_identity",
        description="林夏的固定角色身份、脸型、发型和服装",
        display_name="林夏",
    )


def request(document_id: str) -> ComicProductionRequestV1:
    return ComicProductionRequestV1(
        document_id=document_id,
        panels_per_page=6,
        max_pages=2,
        comic_style="完整上色的日系校园漫画，统一线条与柔和自然光",
        global_prompt="严格按原文顺序呈现，每次只生成一张独立分镜",
        quality_constraints=["角色身份一致", "不得在图中绘制分格边框或文字"],
        selected_assets=[selected_asset()],
        generation=GenerationSettings(width=256, height=256, steps=1, attempts=1),
    )


def project(project_id: str = "comic-project") -> ProjectSpecV1:
    return ProjectSpecV1(
        id=project_id,
        name="Comic project",
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


def prepare_source(project_id: str = "comic-project"):
    return DocumentParser().parse_txt(
        project_id=project_id,
        filename="novel.txt",
        text=source_text(),
    )


def test_extractive_storyboard_preserves_exact_evidence_and_cross_page_order() -> None:
    parsed = prepare_source()
    comic_request = request(parsed.document.document_id)
    context = ContextBuilder().from_chunks("comic-project", parsed.chunks)

    proposal = LongTextStoryboardAgent().propose(
        context=context,
        document_id=parsed.document.document_id,
        request=comic_request,
        reading_direction="LTR",
    )

    assert len(proposal.pages) == 2
    assert len(proposal.panels) == 12
    assert proposal.pages[0].panel_ids == [item.panel.panel_id for item in proposal.panels[:6]]
    assert proposal.pages[1].panel_ids == [item.panel.panel_id for item in proposal.panels[6:]]
    chunks = {chunk.chunk_id: chunk for chunk in parsed.chunks}
    for item in proposal.panels:
        evidence = item.evidence_refs[0]
        chunk = chunks[evidence.chunk_id]
        assert chunk.text[evidence.quote_start : evidence.quote_end] == evidence.quote_text
        assert evidence.quote_text == item.source_quote


def test_dialogue_is_extracted_verbatim_and_lettered_after_generation(
    tmp_path: Path,
) -> None:
    parsed = DocumentParser().parse_txt(
        project_id="comic-project",
        filename="dialogue.txt",
        text="第一章 客厅\n\n女生说：“窗外很美。”",
    )
    asset = selected_asset().model_copy(
        update={
            "entity_id": "character.girl",
            "display_name": "女生",
            "description": "女生固定身份",
        }
    )
    comic_request = ComicProductionRequestV1(
        document_id=parsed.document.document_id,
        panels_per_page=1,
        max_pages=1,
        comic_style="完整上色的日系室内漫画",
        global_prompt="每次只生成一格，不在底图生成文字",
        selected_assets=[asset],
        generation=GenerationSettings(width=256, height=256, steps=1, attempts=1),
        dialogue_layout=DialogueLayoutSettingsV1(enabled=True),
    )
    context = ContextBuilder().from_chunks("comic-project", parsed.chunks)
    proposal = LongTextStoryboardAgent().propose(
        context=context,
        document_id=parsed.document.document_id,
        request=comic_request,
        reading_direction="LTR",
    )
    overlay = proposal.panels[0].panel.text_overlays[0]
    assert overlay.text == "窗外很美。"
    assert overlay.speaker_entity_id == "character.girl"
    chunk = next(item for item in parsed.chunks if item.chunk_id in proposal.source_chunk_ids)
    assert chunk.text[overlay.source_quote_start : overlay.source_quote_end] == overlay.text

    manifest = LongTextComicCompiler().compile(
        project=project(),
        request=comic_request,
        context=context,
        proposal=proposal,
    )
    run_root = tmp_path / "run"
    run_root.mkdir()
    panel_id = proposal.panels[0].panel.panel_id
    Image.new("RGB", (256, 256), (40, 100, 160)).save(run_root / f"{panel_id}.png")
    (run_root / "result.json").write_text(
        json.dumps(
            {
                "status": "succeeded",
                "shots": [
                    {
                        "shot_id": panel_id,
                        "status": "succeeded",
                        "output": f"{panel_id}.png",
                    }
                ],
                "performance": {
                    "latency_budget_seconds": 60.0,
                    "end_to_end_seconds": 1.0,
                    "single_image_seconds": 1.0,
                    "stages": {},
                },
            }
        ),
        encoding="utf-8",
    )

    artifacts = ComicPageComposer().compose(run_root=run_root, manifest=manifest)
    result = json.loads((run_root / "result.json").read_text(encoding="utf-8"))
    assert artifacts[0].file == "page-001.png"
    assert (run_root / f"lettered-{panel_id}.png").is_file()
    assert result["lettered_panels"][0]["overlay_count"] == 1


def test_character_display_name_gender_overrides_negative_description_terms() -> None:
    comic_request = request("doc-test")
    comic_request = comic_request.model_copy(
        update={
            "selected_assets": [
                selected_asset().model_copy(
                    update={
                        "slot": "CHAR_MALE",
                        "entity_id": "character.male",
                        "display_name": "男生",
                        "description": "成年男性，不能女性化",
                    }
                ),
                selected_asset().model_copy(
                    update={
                        "slot": "CHAR_FEMALE",
                        "asset_id": "asset-002",
                        "entity_id": "character.female",
                        "display_name": "女生",
                        "description": "成年女性",
                    }
                ),
            ]
        }
    )

    assert LongTextStoryboardAgent._character_bindings("女孩低头喝茶。", comic_request) == {
        "CHAR_FEMALE": "character.female"
    }


def test_compiler_keeps_provider_fields_out_of_panels_and_continuity_across_pages() -> None:
    parsed = prepare_source()
    comic_request = request(parsed.document.document_id)
    context = ContextBuilder().from_chunks("comic-project", parsed.chunks)
    proposal = LongTextStoryboardAgent().propose(
        context=context,
        document_id=parsed.document.document_id,
        request=comic_request,
        reading_direction="LTR",
    )

    manifest = LongTextComicCompiler().compile(
        project=project(),
        request=comic_request,
        context=context,
        proposal=proposal,
    )

    assert "provider" not in proposal.panels[0].panel.model_dump()
    assert manifest.prompt_specs[0].provider == "local-flux2-klein"
    assert manifest.workflow_job.shots[0].continuity_from is None
    assert proposal.panels[6].continuity_parent_panel_id == proposal.panels[5].panel.panel_id
    assert manifest.workflow_job.shots[6].continuity_from is None
    assert [item.asset_id for item in manifest.workflow_job.shots[6].references] == [
        "asset-001"
    ]
    assert manifest.workflow_job.shots[6].seed == manifest.workflow_job.shots[5].seed
    assert "当前画面恰好表现 1 名不同角色：林夏" in manifest.workflow_job.shots[0].prompt
    assert manifest.prompt_specs[6].provider_options["seed_lineage_from"] == (
        proposal.panels[5].panel.panel_id
    )
    assert [shot.shot_id for shot in manifest.workflow_job.shots] == [
        item.panel.panel_id for item in proposal.panels
    ]


def test_compiler_adds_one_auto_identity_anchor_per_character_entity() -> None:
    parsed = prepare_source()
    comic_request = ComicProductionRequestV1.model_validate(
        request(parsed.document.document_id).model_dump(mode="json")
        | {"identity_anchor_mode": IdentityAnchorMode.AUTO}
    )
    context = ContextBuilder().from_chunks("comic-project", parsed.chunks)
    proposal = LongTextStoryboardAgent().propose(
        context=context,
        document_id=parsed.document.document_id,
        request=comic_request,
        reading_direction="LTR",
    )

    manifest = LongTextComicCompiler().compile(
        project=project(),
        request=comic_request,
        context=context,
        proposal=proposal,
    )

    assert len(manifest.workflow_job.identity_anchors) == 1
    anchor = manifest.workflow_job.identity_anchors[0]
    assert anchor.entity_id == "character.lin-xia"
    assert anchor.asset_id == "asset-001"
    assert anchor.width == 256
    assert anchor.height == 256
    assert manifest.prompt_specs[0].provider_options["identity_anchor_ids"] == [
        anchor.anchor_id
    ]
    assert all(shot.continuity_from is None for shot in manifest.workflow_job.shots)
    assert len({shot.seed for shot in manifest.workflow_job.shots}) == len(
        manifest.workflow_job.shots
    )


def test_continuity_reconnects_non_adjacent_matching_cast_and_scene() -> None:
    parsed = DocumentParser().parse_txt(
        project_id="comic-project",
        filename="alternating.txt",
        text=(
            "第一章 客厅\n\n男生走进客厅。\n\n女生喝茶。\n\n男生坐下。\n\n"
            "两人开始交谈。\n\n女生看向窗外。\n\n两人一起喝茶。"
        ),
    )
    assets = [
        SelectedAsset(
            slot="CHAR_MALE",
            asset_id="male-001",
            entity_id="character.male",
            role="character_identity",
            description="成年男性主角",
            display_name="男生",
        ),
        SelectedAsset(
            slot="CHAR_FEMALE",
            asset_id="female-001",
            entity_id="character.female",
            role="character_identity",
            description="成年女性主角",
            display_name="女生",
        ),
        SelectedAsset(
            slot="SCENE_ROOM",
            asset_id="room-001",
            entity_id="location.living-room",
            role="scene",
            description="客厅布局",
            display_name="客厅",
        ),
    ]
    comic_request = ComicProductionRequestV1(
        document_id=parsed.document.document_id,
        panels_per_page=6,
        max_pages=1,
        comic_style="完整上色的日系室内漫画",
        global_prompt="保持身份与空间连续，每次生成一格",
        selected_assets=assets,
        generation=GenerationSettings(width=256, height=256, steps=1, attempts=1),
    )
    context = ContextBuilder().from_chunks("comic-project", parsed.chunks)
    proposal = LongTextStoryboardAgent().propose(
        context=context,
        document_id=parsed.document.document_id,
        request=comic_request,
        reading_direction="LTR",
    )
    manifest = LongTextComicCompiler().compile(
        project=project(),
        request=comic_request,
        context=context,
        proposal=proposal,
    )

    assert proposal.panels[2].continuity_parent_panel_id == proposal.panels[0].panel.panel_id
    assert proposal.panels[5].continuity_parent_panel_id == proposal.panels[3].panel.panel_id
    assert manifest.workflow_job.shots[2].continuity_from is None
    assert manifest.workflow_job.shots[2].seed == manifest.workflow_job.shots[0].seed
    assert manifest.workflow_job.shots[5].continuity_from == proposal.panels[3].panel.panel_id
    assert [item.asset_id for item in manifest.workflow_job.shots[5].references] == [
        "male-001",
        "female-001",
        "room-001",
    ]


def test_coordinator_is_idempotent_and_composes_two_pages(tmp_path: Path) -> None:
    reference_root = tmp_path / "inputs" / "references"
    reference_root.mkdir(parents=True)
    Image.new("RGB", (16, 16), "white").save(reference_root / "character.png")
    write_catalog(tmp_path)
    catalog = load_catalog(tmp_path)
    assert catalog.references[0].asset_id == "asset-001"

    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'comic.db'}")
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    source_repository = SourceRepository(session)
    production_repository = ComicProductionRepository(session)
    queue_store = QueueStore(tmp_path / "queue")
    coordinator = ComicProductionCoordinator(
        workspace=tmp_path,
        source_repository=source_repository,
        production_repository=production_repository,
        queue_store=queue_store,
    )
    try:
        source_repository.create_project(project())
        parsed = prepare_source()
        source_repository.import_parsed_document(parsed)
        comic_request = request(parsed.document.document_id)

        first = coordinator.compile_and_enqueue(project_id="comic-project", request=comic_request)
        second = coordinator.compile_and_enqueue(project_id="comic-project", request=comic_request)

        assert first.run_id == second.run_id
        assert len(queue_store.list_items("pending")) == 1
        item = queue_store.claim_next("test-worker")
        assert item is not None
        plan = build_plan(tmp_path, item.job, catalog)

        class FakeBackend:
            settings = item.job.generation

            def generate(self, shot, seed, *, continuity_path=None):  # type: ignore[no-untyped-def]
                return Image.new("RGB", (8, 8), (seed % 255, 64, 128))

        run_root = run_workflow(
            item.job,
            plan,
            tmp_path / "runs",
            backend=FakeBackend(),  # type: ignore[arg-type]
        )
        queue_store.succeed(item, run_root)
        completed = coordinator.refresh(first.run_id)

        assert str(completed.status) == "SUCCEEDED"
        assert [artifact.file for artifact in completed.page_artifacts] == [
            "page-001.png",
            "page-002.png",
        ]
        assert (run_root / "production-manifest.json").is_file()
        if os.name != "nt":
            assert stat.S_IMODE(run_root.stat().st_mode) == 0o700
        for filename in (
            "page-001.png",
            "page-002.png",
            "production-manifest.json",
        ):
            if os.name != "nt":
                assert stat.S_IMODE((run_root / filename).stat().st_mode) == 0o600
        with Image.open(run_root / "page-001.png") as page:
            assert page.size == (24, 16)
    finally:
        session.close()
        engine.dispose()


def test_comic_api_compiles_one_idempotent_queue_item(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    reference_root = tmp_path / "inputs" / "references"
    reference_root.mkdir(parents=True)
    Image.new("RGB", (16, 16), "white").save(reference_root / "character.png")
    write_catalog(tmp_path)
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("IMAGE_QUEUE_ROOT", "queue")
    get_settings.cache_clear()
    try:
        app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'api.db'}")
        with TestClient(app) as client:
            created = client.post("/projects", json=project().model_dump(mode="json"))
            assert created.status_code == 201
            imported = client.post(
                "/projects/comic-project/documents/import",
                files={"file": ("novel.txt", source_text().encode(), "text/plain")},
            )
            assert imported.status_code == 201
            document_id = imported.json()["document"]["document_id"]
            payload = request(document_id).model_dump(mode="json")

            first = client.post("/projects/comic-project/comic-runs", json=payload)
            second = client.post("/projects/comic-project/comic-runs", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["run_id"] == second.json()["run_id"]
        assert first.json()["status"] == "QUEUED"
        assert len(list((tmp_path / "queue" / "pending").glob("*.json"))) == 1
    finally:
        get_settings.cache_clear()
