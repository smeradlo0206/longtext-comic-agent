"""One-command TXT-and-photo-reference comic production.

Example:
    uv run python scripts/run_photo_reference_comic.py \
      --input story.txt --reference gate.png --reference teaching-building.jpg
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comic_agent.database.base import Base
from comic_agent.database.session import make_engine, make_session_factory
from comic_agent.repositories.comic_production_repository import ComicProductionRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.comic_planning import PanelPlanV1
from comic_agent.schemas.comic_production import (
    ComicProductionRequestV1,
    ComicRunStatus,
    DialogueLayoutSettingsV1,
    IdentityAnchorMode,
)
from comic_agent.schemas.image_workflow import (
    GenerationSettings,
    ReferenceLibraryPolicy,
    SelectedAsset,
    VisualQASettings,
)
from comic_agent.schemas.source import FidelityMode, ProjectSpecV1, ProjectType, SourceChunkV1
from comic_agent.services.comic_production_coordinator import ComicProductionCoordinator
from comic_agent.services.document_parser import DocumentParser, ParsedDocument
from comic_agent.services.review_gate1_service import ReviewGate1Service, build_review_gate1_input
from flux2_agent.catalog import load_catalog, sha256_file, update_reference_metadata, write_catalog
from flux2_agent.queueing import QueueStore, run_queue_worker

_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+(?:[。！？!?；;][”」』\"]?|$)")
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_SHOT_TYPES = ("WIDE", "MEDIUM", "MEDIUM_CLOSE_UP", "WIDE", "CLOSE_UP", "MEDIUM")
_CAMERA_ANGLES = (
    "EYE_LEVEL",
    "THREE_QUARTER",
    "EYE_LEVEL",
    "SLIGHT_LOW",
    "EYE_LEVEL",
    "HIGH_ANGLE",
)
_COMPOSITIONS = (
    "OPEN_BALANCE",
    "RULE_OF_THIRDS",
    "LAYERED_DEPTH",
    "DIAGONAL",
    "CLOSE_FOCUS",
    "CENTERED",
)


@dataclass(frozen=True)
class SourceExcerpt:
    chunk_id: str
    quote: str
    start: int
    end: int


@dataclass(frozen=True)
class ReferenceBinding:
    asset_id: str
    entity_id: str
    slot: str
    marker: str
    role: str
    description: str


def _project(project_id: str, name: str) -> ProjectSpecV1:
    return ProjectSpecV1(
        id=project_id,
        name=name,
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
        max_auto_repairs=3,
        budget_limit=None,
    )


def _safe_stem(path: Path) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", path.stem).strip("-").lower()
    return value or "photo-reference-comic"


def _input_fingerprint(source: Path, references: list[Path]) -> str:
    digest = hashlib.sha256()
    digest.update(source.read_bytes())
    for reference in references:
        digest.update(b"\0")
        digest.update(sha256_file(reference).encode("ascii"))
    return digest.hexdigest()[:16]


def _default_output_dir(source: Path, references: list[Path]) -> Path:
    return (
        ROOT
        / "artifacts"
        / "photo-reference-comic"
        / (f"{_safe_stem(source)}-{_input_fingerprint(source, references)}")
    )


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def _copy_reference(source: Path, destination: Path) -> None:
    if destination.exists():
        if sha256_file(source) != sha256_file(destination):
            raise ValueError(
                f"reference destination already contains a different image: {destination}"
            )
    else:
        shutil.copy2(source, destination)
    destination.chmod(0o600)


def _prepare_references(
    workspace: Path,
    scene_references: list[Path],
    character_reference: Path | None,
) -> list[ReferenceBinding]:
    reference_root = workspace / "inputs" / "references"
    _ensure_private_directory(reference_root)
    staged: list[tuple[str, str, str, str, str, str]] = []
    for index, source in enumerate(scene_references, start=1):
        destination = reference_root / f"scene-reference-{index:02d}{source.suffix.lower()}"
        _copy_reference(source, destination)
        staged.append(
            (
                destination.name,
                f"visual-reference.scene-{index:02d}",
                f"scene-photo-reference-{index:02d}",
                f"SCENE_{index:02d}",
                "scene",
                (
                    "Use this supplied photograph as the primary source for architecture, "
                    "road and spatial perspective, vegetation, materials, natural lighting, "
                    "and photographic color relationships."
                ),
            )
        )
    if character_reference is not None:
        destination = reference_root / (f"style-reference-01{character_reference.suffix.lower()}")
        _copy_reference(character_reference, destination)
        staged.append(
            (
                destination.name,
                "visual-reference.character-style",
                "character-style-reference",
                "STYLE_CHARACTER",
                "style",
                (
                    "Use this as a recurring visual character-design guide: clean elegant "
                    "linework, dark wavy hair, glasses, and a dark suit silhouette when a "
                    "featured adult male is supported by the source. Do not introduce people, "
                    "actions, text, or events merely because they appear in this reference."
                ),
            )
        )

    write_catalog(workspace)
    catalog = load_catalog(workspace)
    by_name = {item.filename: item for item in catalog.references}
    bindings: list[ReferenceBinding] = []
    for filename, entity_id, marker, slot, role, description in staged:
        asset = by_name[filename]
        update_reference_metadata(
            workspace,
            asset.asset_id,
            lifecycle="approved",
            entity_id=entity_id,
            intended_role=role,
            is_canonical=True,
            notes=(
                "One-command character reference applied to all panels."
                if role == "style"
                else "One-command scene reference assigned to consecutive comic pages."
            ),
        )
        bindings.append(
            ReferenceBinding(
                asset_id=asset.asset_id,
                entity_id=entity_id,
                slot=slot,
                marker=marker,
                role=role,
                description=description,
            )
        )
    return bindings


def _excerpts(chunks: list[SourceChunkV1]) -> list[SourceExcerpt]:
    result: list[SourceExcerpt] = []
    for chunk in chunks:
        for match in _SENTENCE_RE.finditer(chunk.text):
            raw = match.group(0)
            left = len(raw) - len(raw.lstrip())
            right = len(raw) - len(raw.rstrip())
            start = match.start() + left
            end = match.end() - right
            quote = chunk.text[start:end]
            if quote:
                result.append(SourceExcerpt(chunk.chunk_id, quote, start, end))
    if not result:
        raise ValueError("source TXT has no visualizable text")
    return result


def _select_in_order(excerpts: list[SourceExcerpt], count: int) -> list[SourceExcerpt]:
    """Sample all source stages in order, repeating evidence only when necessary."""

    if count < 1:
        raise ValueError("panel count must be positive")
    if len(excerpts) == 1:
        return excerpts * count
    selected: list[SourceExcerpt] = []
    for index in range(count):
        source_index = min(len(excerpts) - 1, index * len(excerpts) // count)
        selected.append(excerpts[source_index])
    return selected


def _reference_for_page(
    page_index: int, *, max_pages: int, references: list[ReferenceBinding]
) -> ReferenceBinding:
    scene_references = [reference for reference in references if reference.role == "scene"]
    reference_index = min(
        len(scene_references) - 1,
        page_index * len(scene_references) // max_pages,
    )
    return scene_references[reference_index]


def _build_panels(
    *,
    parsed: ParsedDocument,
    project_id: str,
    references: list[ReferenceBinding],
    panels_per_page: int,
    max_pages: int,
) -> list[PanelPlanV1]:
    panel_count = panels_per_page * max_pages
    selected = _select_in_order(_excerpts(parsed.chunks), panel_count)
    panels: list[PanelPlanV1] = []
    for index, excerpt in enumerate(selected):
        page_index = index // panels_per_page
        reference = _reference_for_page(page_index, max_pages=max_pages, references=references)
        panels.append(
            PanelPlanV1(
                panel_id=f"photo-panel-{index + 1:03d}",
                project_id=project_id,
                scene_id=f"photo-page-{page_index + 1:03d}",
                index=index,
                storybible_bundle_id=f"photo-reference-proposal-{project_id}",
                timeline_bundle_id=f"photo-reference-proposal-{project_id}",
                panel_purpose="Translate exact source evidence into one complete campus scene.",
                narrative_beat=(
                    "仅表现当前原文支持的一个可见时刻，不增加人物、动作或事件：" + excerpt.quote
                ),
                aspect_ratio="1:1",
                shot_type=_SHOT_TYPES[index % len(_SHOT_TYPES)],
                camera_angle=_CAMERA_ANGLES[index % len(_CAMERA_ANGLES)],
                composition=_COMPOSITIONS[index % len(_COMPOSITIONS)],
                background=(
                    f"{reference.marker}: the supplied photograph is the primary visual "
                    "source for this page's campus environment; retain its realistic space, "
                    "architecture, materials, vegetation, lighting, and colors."
                ),
                location_entity_id=reference.entity_id,
                atmosphere="Natural, bright, documentary campus atmosphere.",
                related_event_ids=[f"photo-reference-event-{index + 1:03d}"],
                evidence_refs=[
                    EvidenceRefV1(
                        chunk_id=excerpt.chunk_id,
                        quote_start=excerpt.start,
                        quote_end=excerpt.end,
                        quote_text=excerpt.quote,
                    )
                ],
            )
        )
    return panels


def _selected_assets(references: list[ReferenceBinding]) -> list[SelectedAsset]:
    return [
        SelectedAsset(
            slot=reference.slot,
            asset_id=reference.asset_id,
            entity_id=reference.entity_id,
            role=reference.role,
            description=reference.description,
            display_name=reference.marker,
        )
        for reference in references
    ]


def _request(
    *,
    document_id: str,
    references: list[ReferenceBinding],
    panels_per_page: int,
    max_pages: int,
    width: int,
    height: int,
    steps: int,
    device: str,
) -> ComicProductionRequestV1:
    return ComicProductionRequestV1(
        document_id=document_id,
        panels_per_page=panels_per_page,
        max_pages=max_pages,
        comic_style=(
            "Photo-led cinematic campus comic illustration with realistic architecture, "
            "natural color, material detail, and restrained clean character linework."
        ),
        global_prompt=(
            "Generate one edge-to-edge scene per panel. The assigned reference photograph "
            "has priority for the environment's architectural proportions, road axis, "
            "vegetation, materials, lighting, and color. Do not render readable text, "
            "labels, banners, signage, grids, borders, speech bubbles, watermarks, or "
            "unsupported story facts. Treat any reference-image signage as blank architecture."
        ),
        quality_constraints=[
            "The supplied photograph is the primary visual source for each page's environment",
            "Only the reference assigned to the current page may be used for that panel",
            "The optional character reference may guide visual design but must not add cast",
            "People, actions, and objects must be supported by the exact source evidence",
            (
                "Faces, hands, bodies, architecture, and environmental space must be "
                "structurally complete"
            ),
            (
                "Each generated panel is a single unframed scene; deterministic composition "
                "creates the 2x3 page"
            ),
        ],
        selected_assets=_selected_assets(references),
        reference_policy=ReferenceLibraryPolicy(mode="APPROVED_LIBRARY", require_canonical=True),
        generation=GenerationSettings(
            width=width,
            height=height,
            steps=steps,
            guidance_scale=1.0,
            seed=2026090401,
            attempts=1,
            device=device,
        ),
        visual_qa=VisualQASettings(
            enabled=True,
            latency_budget_seconds=1800.0,
            min_dynamic_range=0.12,
            min_edge_energy=0.015,
            min_reference_similarity=0.01,
            max_auto_repairs=1,
        ),
        dialogue_layout=DialogueLayoutSettingsV1(enabled=False),
        continuity_enabled=False,
        identity_anchor_mode=IdentityAnchorMode.OFF,
    )


def _write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    path.chmod(0o600)


def run(args: argparse.Namespace) -> dict[str, object]:
    source = args.input.resolve()
    scene_references = [path.resolve() for path in args.reference]
    character_reference = (
        args.character_reference.resolve() if args.character_reference is not None else None
    )
    all_references = scene_references + (
        [character_reference] if character_reference is not None else []
    )
    if not source.is_file():
        raise FileNotFoundError(f"input TXT not found: {source}")
    if source.suffix.lower() != ".txt":
        raise ValueError("input must be a .txt file")
    if not 1 <= len(scene_references) <= 3:
        raise ValueError("provide one to three --reference images")
    if len(all_references) > 3:
        raise ValueError("a character reference allows at most two scene --reference images")
    for reference in all_references:
        if not reference.is_file():
            raise FileNotFoundError(f"reference image not found: {reference}")
        if reference.suffix.lower() not in _IMAGE_SUFFIXES:
            raise ValueError(f"unsupported reference image type: {reference.name}")

    workspace = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else _default_output_dir(source, all_references)
    )
    _ensure_private_directory(workspace)
    fingerprint = _input_fingerprint(source, all_references)
    project_id = f"photo-reference-{fingerprint}"
    bindings = _prepare_references(workspace, scene_references, character_reference)
    text = source.read_text(encoding="utf-8")
    parsed = DocumentParser().parse_txt(
        project_id=project_id,
        filename=source.name,
        text=text,
        storage_uri=source.as_uri(),
    )
    panels = _build_panels(
        parsed=parsed,
        project_id=project_id,
        references=bindings,
        panels_per_page=args.panels_per_page,
        max_pages=args.max_pages,
    )
    request = _request(
        document_id=parsed.document.document_id,
        references=bindings,
        panels_per_page=args.panels_per_page,
        max_pages=args.max_pages,
        width=args.width,
        height=args.height,
        steps=args.steps,
        device=args.device,
    )
    _write_json(workspace / "panels.json", [panel.model_dump(mode="json") for panel in panels])
    _write_json(workspace / "request.json", request.model_dump(mode="json"))

    runtime = workspace / ".runtime"
    _ensure_private_directory(runtime)
    engine = make_engine(f"sqlite+pysqlite:///{(runtime / 'comic-production.db').as_posix()}")
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    try:
        source_repository = SourceRepository(session)
        source_repository.create_project(
            _project(project_id, f"Photo reference comic {source.stem}")
        )
        gate1 = ReviewGate1Service().review(
            build_review_gate1_input(parsed=parsed, normalized_text=text)
        )
        if str(gate1.decision) != "APPROVED":
            raise ValueError(f"source review Gate 1 blocked import: {gate1.decision}")
        imported = source_repository.import_reviewed_document(parsed, gate1)
        request = request.model_copy(update={"document_id": imported.document.document_id})
        queue = QueueStore(runtime / "image-queue")
        coordinator = ComicProductionCoordinator(
            workspace=workspace,
            source_repository=source_repository,
            production_repository=ComicProductionRepository(session),
            queue_store=queue,
        )
        production_run = coordinator.compile_planned_and_enqueue(
            project_id=project_id,
            request=request,
            panel_plans=panels,
            page_panel_counts=[args.panels_per_page] * args.max_pages,
        )
        if not args.compile_only and production_run.status != ComicRunStatus.SUCCEEDED:
            run_queue_worker(
                queue,
                workspace,
                workspace,
                model_path=args.model_path,
                offline=args.offline,
                max_jobs=1,
            )
            production_run = coordinator.refresh(production_run.run_id)
        pages = [artifact.model_dump(mode="json") for artifact in production_run.page_artifacts]
        result = {
            "status": str(production_run.status),
            "workspace": str(workspace),
            "run_id": production_run.run_id,
            "panel_count": len(panels),
            "page_count": len(pages) if pages else args.max_pages,
            "pages": pages,
            "references": [
                {
                    "asset_id": reference.asset_id,
                    "entity_id": reference.entity_id,
                    "role": reference.role,
                    "page_orders": [
                        page
                        for page in range(args.max_pages)
                        if reference.role == "style"
                        or _reference_for_page(
                            page, max_pages=args.max_pages, references=bindings
                        ).asset_id
                        == reference.asset_id
                    ],
                }
                for reference in bindings
            ],
            "performance": (
                production_run.performance.model_dump(mode="json")
                if production_run.performance
                else None
            ),
        }
        _write_json(workspace / "summary.json", result)
        return result
    finally:
        session.close()
        engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="source TXT")
    parser.add_argument(
        "--reference",
        type=Path,
        action="append",
        required=True,
        help="scene reference image; repeat in the page order to use",
    )
    parser.add_argument(
        "--character-reference",
        type=Path,
        help="optional character design reference applied to every generated panel",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="artifact directory; defaults to a stable path under artifacts/photo-reference-comic",
    )
    parser.add_argument("--max-pages", type=int, default=4, choices=range(1, 21))
    parser.add_argument("--panels-per-page", type=int, default=6, choices=range(1, 7))
    parser.add_argument("--model-path", type=Path, default=Path("models/FLUX.2-klein-4B"))
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--offline", action="store_true", default=True)
    parser.add_argument("--online", dest="offline", action="store_false")
    parser.add_argument(
        "--compile-only", action="store_true", help="validate and enqueue without loading FLUX"
    )
    return parser.parse_args()


def main() -> int:
    try:
        result = run(parse_args())
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(json.dumps({"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
