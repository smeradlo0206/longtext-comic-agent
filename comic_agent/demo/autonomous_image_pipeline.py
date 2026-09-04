"""Private, unattended PanelPlan-to-FLUX execution for the demo entrypoint."""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from dataclasses import dataclass
from math import ceil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

from comic_agent.database.base import Base
from comic_agent.database.session import make_engine, make_session_factory
from comic_agent.repositories.comic_production_repository import ComicProductionRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.comic_planning import PanelPlanV1
from comic_agent.schemas.comic_production import (
    ComicProductionRequestV1,
    ComicProductionRunV1,
    DialogueLayoutSettingsV1,
    IdentityAnchorMode,
)
from comic_agent.schemas.image_workflow import (
    GenerationSettings,
    ReferenceLibraryPolicy,
    ReferenceRole,
    SelectedAsset,
    VisualQASettings,
)
from comic_agent.schemas.source import FidelityMode, ProjectSpecV1, ProjectType
from comic_agent.schemas.storybible import ApprovedStoryBibleBundleV1, StoryEntityKind
from comic_agent.services.comic_letterer import DEFAULT_FONT_CANDIDATES
from comic_agent.services.comic_production_coordinator import ComicProductionCoordinator
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.review_gate1_service import ReviewGate1Service, build_review_gate1_input
from flux2_agent.catalog import load_catalog, update_reference_metadata, write_catalog
from flux2_agent.queueing import QueueStore, run_queue_worker

_OPENING_SCENE_ID = "visual-reference.opening-scene"
_LATER_SCENE_ID = "visual-reference.later-scene"
_OPENING_SCENE_LABEL = "绿树环绕的大学校门入口广场"
_LATER_SCENE_LABEL = "绿树环绕的大学校内道路与教学楼"


@dataclass(frozen=True)
class AutonomousImageResult:
    """Rendered production checkpoint plus deterministic reference decisions."""

    run: ComicProductionRunV1
    reference_bindings: list[dict[str, str]]
    signage_overlays: list[dict[str, object]]


class AutonomousImagePipeline:
    """Compile trusted panels and drain their local FLUX job without manual handoff."""

    def __init__(
        self,
        *,
        model_path: Path,
        offline: bool = True,
        width: int = 1024,
        height: int = 1024,
        steps: int = 4,
        device: str = "cuda:0",
    ) -> None:
        self._model_path = model_path.resolve()
        self._offline = offline
        self._width = width
        self._height = height
        self._steps = steps
        self._device = device

    def run(
        self,
        *,
        source_path: Path,
        artifact_dir: Path,
        panels: list[PanelPlanV1],
        storybible: ApprovedStoryBibleBundleV1,
        character_reference: Path | None,
        scene_reference: Path | None,
        later_scene_reference: Path | None = None,
        sanitize_opening_scene_reference: bool = False,
        pages_per_reference: int | None = None,
        opening_scene_signage: str | None = None,
        opening_scene_signage_font: Path | None = None,
        execute: bool = True,
    ) -> AutonomousImageResult:
        if not panels:
            raise ValueError("autonomous image production requires at least one panel")
        project_id = panels[0].project_id
        if any(panel.project_id != project_id for panel in panels):
            raise ValueError("all autonomous image panels must belong to one project")
        if storybible.project_id != project_id:
            raise ValueError("panels and StoryBible must belong to the same project")
        if later_scene_reference is not None and scene_reference is None:
            raise ValueError("later scene reference requires an opening scene reference")
        if pages_per_reference is not None and pages_per_reference < 1:
            raise ValueError("pages per reference must be positive")
        if pages_per_reference is not None and later_scene_reference is None:
            raise ValueError("pages per reference requires two scene references")
        if opening_scene_signage is not None and scene_reference is None:
            raise ValueError("opening scene signage requires an opening scene reference")
        if opening_scene_signage_font is not None and opening_scene_signage is None:
            raise ValueError("opening scene signage font requires opening scene signage")
        if opening_scene_signage_font is not None and not opening_scene_signage_font.is_file():
            raise FileNotFoundError(
                f"opening scene signage font not found: {opening_scene_signage_font}"
            )
        if (
            character_reference is None
            and scene_reference is None
            and later_scene_reference is None
        ):
            raise ValueError("at least one character or scene reference is required")

        workspace = artifact_dir.resolve()
        self._private_directory(workspace)
        reference_root = workspace / "inputs" / "references"
        self._private_directory(reference_root)
        copied = self._copy_references(
            reference_root,
            character_reference=character_reference,
            scene_reference=scene_reference,
            later_scene_reference=later_scene_reference,
            sanitize_opening_scene_reference=sanitize_opening_scene_reference,
        )
        write_catalog(workspace)
        routed_panels = self._route_scene_references(panels, copied)
        page_panel_counts = self._page_panel_counts(
            panel_count=len(routed_panels),
            pages_per_reference=pages_per_reference,
            has_two_scene_references={"scene_opening", "scene_later"}.issubset(copied),
        )
        selected_assets, bindings = self._approve_and_bind(
            workspace=workspace,
            copied=copied,
            panels=routed_panels,
            storybible=storybible,
        )

        runtime_root = workspace / ".runtime"
        self._private_directory(runtime_root)
        database_path = runtime_root / "image-production.db"
        engine = make_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
        Base.metadata.create_all(engine)
        if database_path.exists():
            os.chmod(database_path, 0o600)
        session = make_session_factory(engine)()
        queue = QueueStore(runtime_root / "image-queue")
        try:
            source_repository = SourceRepository(session)
            source_repository.create_project(self._project(project_id))
            source = source_path.resolve()
            text = source.read_text(encoding="utf-8")
            parsed = DocumentParser().parse_txt(
                project_id=project_id,
                filename=source.name,
                text=text,
                storage_uri=source.as_uri(),
            )
            gate1 = ReviewGate1Service().review(
                build_review_gate1_input(parsed=parsed, normalized_text=text)
            )
            if str(gate1.decision) != "APPROVED":
                raise ValueError(f"autonomous image source Gate 1 blocked: {gate1.decision}")
            imported = source_repository.import_reviewed_document(parsed, gate1)
            request = self._request(
                document_id=imported.document.document_id,
                panels=routed_panels,
                assets=selected_assets,
                page_panel_counts=page_panel_counts,
                opening_scene_signage=opening_scene_signage,
            )
            coordinator = ComicProductionCoordinator(
                workspace=workspace,
                source_repository=source_repository,
                production_repository=ComicProductionRepository(session),
                queue_store=queue,
            )
            run = coordinator.compile_planned_and_enqueue(
                project_id=project_id,
                request=request,
                panel_plans=routed_panels,
                page_panel_counts=page_panel_counts,
            )
            signage_overlays: list[dict[str, object]] = []
            if execute:
                if not self._model_path.is_dir():
                    raise FileNotFoundError(f"FLUX model directory not found: {self._model_path}")
                completed = run_queue_worker(
                    queue,
                    workspace,
                    workspace,
                    model_path=self._model_path,
                    offline=self._offline,
                    max_jobs=1,
                )
                if not completed or completed[0].status != "succeeded":
                    error = completed[0].error if completed else "worker did not claim the job"
                    raise RuntimeError(f"autonomous FLUX worker failed: {error}")
                if opening_scene_signage is not None:
                    run_root = completed[0].run_root
                    if run_root is None:
                        raise RuntimeError("succeeded FLUX run did not provide an artifact root")
                    opening_panel_count = ceil(len(routed_panels) / 2)
                    signage_overlays = self._apply_opening_scene_signage(
                        run_root=Path(run_root),
                        panel_ids=[panel.panel_id for panel in routed_panels[:opening_panel_count]],
                        text=opening_scene_signage,
                        font_path=opening_scene_signage_font,
                    )
                run = coordinator.refresh(run.run_id)
            self._harden_tree(workspace)
            return AutonomousImageResult(
                run=run,
                reference_bindings=bindings,
                signage_overlays=signage_overlays,
            )
        finally:
            session.close()
            engine.dispose()

    @staticmethod
    def _project(project_id: str) -> ProjectSpecV1:
        return ProjectSpecV1(
            id=project_id,
            name="Autonomous comic image production",
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

    def _request(
        self,
        *,
        document_id: str,
        panels: list[PanelPlanV1],
        assets: list[SelectedAsset],
        page_panel_counts: list[int] | None,
        opening_scene_signage: str | None,
    ) -> ComicProductionRequestV1:
        panels_per_page = max(page_panel_counts) if page_panel_counts else 6
        max_pages = (
            len(page_panel_counts)
            if page_panel_counts
            else max(1, ceil(len(panels) / panels_per_page))
        )
        signage_instruction = (
            " For opening-gate scenes, retain a centered, uncluttered horizontal lintel "
            "area for deterministic school-name lettering; do not generate any characters "
            "or other signage on that lintel."
            if opening_scene_signage
            else ""
        )
        return ComicProductionRequestV1(
            document_id=document_id,
            panels_per_page=panels_per_page,
            max_pages=max_pages,
            comic_style=(
                "polished cinematic cel-shaded illustration, clean stable linework, rich but "
                "natural colors, expressive faces, coherent realistic spaces"
            ),
            global_prompt=(
                "Each image depicts only its specified moment as one continuous edge-to-edge "
                "scene. Preserve approved story facts and use each registered reference only "
                "for its declared visual role. Keep open environmental space around the people."
                + signage_instruction
            ),
            quality_constraints=[
                "one image fills the entire canvas with one continuous scene",
                "keep recurring identities and locations visually consistent",
                "hands, faces, bodies, architecture, and props must be structurally complete",
                "background surfaces remain visually calm and naturally connected",
                "faces and important gestures remain unobstructed and easy to read",
                *(
                    [
                        "opening-gate lintels are clean architectural surfaces without "
                        "model-generated text or watermarks"
                    ]
                    if opening_scene_signage
                    else []
                ),
            ],
            selected_assets=assets,
            reference_policy=ReferenceLibraryPolicy(
                mode="APPROVED_LIBRARY", require_canonical=True
            ),
            generation=GenerationSettings(
                width=self._width,
                height=self._height,
                steps=self._steps,
                device=self._device,
                attempts=2,
            ),
            visual_qa=VisualQASettings(
                enabled=True,
                latency_budget_seconds=max(180.0, len(panels) * 30.0),
                min_reference_similarity=0.01,
                max_auto_repairs=3,
            ),
            dialogue_layout=DialogueLayoutSettingsV1(
                enabled=True,
                min_font_size=24,
                max_font_size=40,
                bubble_padding=20,
                max_bubble_width_ratio=0.42,
            ),
            continuity_enabled=True,
            identity_anchor_mode=(
                IdentityAnchorMode.AUTO
                if any(asset.role == "character_identity" for asset in assets)
                else IdentityAnchorMode.OFF
            ),
        )

    @classmethod
    def _approve_and_bind(
        cls,
        *,
        workspace: Path,
        copied: dict[str, Path],
        panels: list[PanelPlanV1],
        storybible: ApprovedStoryBibleBundleV1,
    ) -> tuple[list[SelectedAsset], list[dict[str, str]]]:
        catalog = load_catalog(workspace)
        by_filename = {item.filename: item for item in catalog.references}
        profiles = {entity.profile_id: entity for entity in storybible.entities}
        character_ids = Counter(
            character_id for panel in panels for character_id in panel.character_ids
        )
        location_ids = Counter(
            panel.location_entity_id for panel in panels if panel.location_entity_id
        )
        selected: list[SelectedAsset] = []
        decisions: list[dict[str, str]] = []

        for kind, path in copied.items():
            reference = by_filename[path.name]
            role: ReferenceRole
            if kind == "character":
                matching = [
                    entity_id
                    for entity_id, _ in character_ids.most_common()
                    if entity_id in profiles
                    and profiles[entity_id].entity_kind == StoryEntityKind.PERSON
                ]
                if matching:
                    entity_id = matching[0]
                    role = "character_identity"
                    display_name = profiles[entity_id].canonical_name
                    reason = "most frequent approved panel character"
                else:
                    entity_id = "visual-reference.character-style"
                    role = "style"
                    display_name = None
                    reason = "no approved panel character; safely bound as global style"
                slot = "CHARACTER_REFERENCE"
                description = (
                    "Preserve the reference character design when the approved panel contains "
                    "that character; otherwise use only its manga rendering language."
                )
            elif kind in {"scene_opening", "scene_later"}:
                is_opening = kind == "scene_opening"
                entity_id = _OPENING_SCENE_ID if is_opening else _LATER_SCENE_ID
                role = "scene"
                display_name = _OPENING_SCENE_LABEL if is_opening else _LATER_SCENE_LABEL
                reason = (
                    "explicitly routed to the opening half"
                    if is_opening
                    else "explicitly routed to the later half"
                )
                slot = "OPENING_SCENE_REFERENCE" if is_opening else "LATER_SCENE_REFERENCE"
                description = (
                    "Preserve the supplied entrance architecture, gate proportions, road axis, "
                    "greenery, and photographic color relationships."
                    if is_opening
                    else "Preserve the supplied campus architecture, paths, greenery, spatial "
                    "depth, and photographic color relationships."
                )
            else:
                matching = [
                    entity_id
                    for entity_id, _ in location_ids.most_common()
                    if entity_id in profiles
                    and profiles[entity_id].entity_kind == StoryEntityKind.LOCATION
                ]
                entity_id = matching[0] if matching else "visual-reference.primary-scene"
                role = "scene"
                display_name = profiles[entity_id].canonical_name if entity_id in profiles else None
                reason = (
                    "most frequent approved panel location"
                    if matching
                    else "no approved location mapping; used as the sole scene reference"
                )
                slot = "SCENE_REFERENCE"
                description = (
                    "Preserve the supplied campus location architecture, entrance proportions, "
                    "spatial layout, greenery, and color palette."
                )
            update_reference_metadata(
                workspace,
                reference.asset_id,
                lifecycle="approved",
                entity_id=entity_id,
                intended_role=role,
                is_canonical=True,
                notes=f"Automatically classified: {reason}",
            )
            selected.append(
                SelectedAsset(
                    slot=slot,
                    asset_id=reference.asset_id,
                    entity_id=entity_id,
                    role=role,
                    description=description,
                    display_name=display_name,
                )
            )
            decisions.append(
                {
                    "source": str(path),
                    "asset_id": reference.asset_id,
                    "entity_id": entity_id,
                    "role": role,
                    "reason": reason,
                }
            )
        return selected, decisions

    @staticmethod
    def _route_scene_references(
        panels: list[PanelPlanV1], copied: dict[str, Path]
    ) -> list[PanelPlanV1]:
        if not {"scene_opening", "scene_later"}.issubset(copied):
            return panels
        split_index = ceil(len(panels) / 2)
        return [
            panel.model_copy(
                update={
                    "background": (
                        _OPENING_SCENE_LABEL if index < split_index else _LATER_SCENE_LABEL
                    ),
                    "location_entity_id": (
                        _OPENING_SCENE_ID if index < split_index else _LATER_SCENE_ID
                    ),
                }
            )
            for index, panel in enumerate(panels)
        ]

    @staticmethod
    def _page_panel_counts(
        *,
        panel_count: int,
        pages_per_reference: int | None,
        has_two_scene_references: bool,
    ) -> list[int] | None:
        if pages_per_reference is None:
            return None
        if not has_two_scene_references:
            raise ValueError("pages per reference requires two scene references")
        opening_count = ceil(panel_count / 2)
        later_count = panel_count - opening_count
        if opening_count < pages_per_reference or later_count < pages_per_reference:
            raise ValueError("not enough panels to allocate every requested reference page")

        def distribute(count: int) -> list[int]:
            base, remainder = divmod(count, pages_per_reference)
            return [base + (1 if index < remainder else 0) for index in range(pages_per_reference)]

        return [*distribute(opening_count), *distribute(later_count)]

    @staticmethod
    def _apply_opening_scene_signage(
        *,
        run_root: Path,
        panel_ids: list[str],
        text: str,
        font_path: Path | None,
    ) -> list[dict[str, object]]:
        resolved_font_path = (
            font_path.resolve()
            if font_path is not None
            else next((path for path in DEFAULT_FONT_CANDIDATES if path.is_file()), None)
        )
        if resolved_font_path is None:
            raise FileNotFoundError(
                "opening scene signage requires a CJK font at "
                "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"
            )
        result_path = run_root / "result.json"
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        outputs = {
            item["shot_id"]: item["output"]
            for item in payload.get("shots", [])
            if item.get("status") == "succeeded" and isinstance(item.get("output"), str)
        }
        overlays: list[dict[str, object]] = []
        for panel_id in panel_ids:
            output = outputs.get(panel_id)
            if output is None:
                raise ValueError(f"opening signage panel has no generated output: {panel_id}")
            path = run_root / output
            with Image.open(path) as loaded:
                image = loaded.convert("RGB")
            try:
                width, height = image.size
                draw = ImageDraw.Draw(image)
                font_size = max(22, round(width * 0.055))
                font = ImageFont.truetype(str(resolved_font_path), size=font_size)
                bbox = draw.textbbox((0, 0), text, font=font, stroke_width=1)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                left = max(round(width * 0.14), (width - text_width) // 2)
                top = round(height * 0.25) - text_height // 2
                padding_x = max(14, round(width * 0.018))
                padding_y = max(6, round(height * 0.01))
                draw.rounded_rectangle(
                    (
                        left - padding_x,
                        top - padding_y,
                        min(width - padding_x, left + text_width + padding_x),
                        top + text_height + padding_y,
                    ),
                    radius=max(4, round(height * 0.008)),
                    fill=(232, 229, 216),
                    outline=(116, 101, 83),
                    width=max(1, round(width / 1024)),
                )
                draw.text(
                    (left, top - bbox[1]),
                    text,
                    font=font,
                    fill=(71, 50, 36),
                    stroke_width=max(1, round(width / 2048)),
                    stroke_fill=(244, 240, 228),
                )
                image.save(path, format="PNG", optimize=True)
                path.chmod(0o600)
                overlays.append(
                    {
                        "panel_id": panel_id,
                        "file": path.name,
                        "text": text,
                        "font": str(resolved_font_path),
                        "box": [
                            left - padding_x,
                            top - padding_y,
                            min(width - padding_x, left + text_width + padding_x),
                            top + text_height + padding_y,
                        ],
                    }
                )
            finally:
                image.close()
        (run_root / "opening-scene-signage.json").write_text(
            json.dumps(overlays, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (run_root / "opening-scene-signage.json").chmod(0o600)
        return overlays

    @classmethod
    def _copy_references(
        cls,
        reference_root: Path,
        *,
        character_reference: Path | None,
        scene_reference: Path | None,
        later_scene_reference: Path | None,
        sanitize_opening_scene_reference: bool,
    ) -> dict[str, Path]:
        copied: dict[str, Path] = {}
        staged_scenes = later_scene_reference is not None
        sources = [
            ("character", character_reference, "character-reference"),
            (
                "scene_opening" if staged_scenes else "scene",
                scene_reference,
                "opening-scene-reference" if staged_scenes else "scene-reference",
            ),
            ("scene_later", later_scene_reference, "later-scene-reference"),
        ]
        for kind, source, stem in sources:
            if source is None:
                continue
            resolved = source.resolve()
            if not resolved.is_file():
                raise FileNotFoundError(f"{kind} reference not found: {resolved}")
            suffix = resolved.suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                raise ValueError(f"unsupported {kind} reference type: {suffix}")
            destination = reference_root / f"{stem}{suffix}"
            if kind == "scene_opening" and sanitize_opening_scene_reference:
                cls._copy_with_clean_lintel(resolved, destination)
            else:
                shutil.copyfile(resolved, destination)
            os.chmod(destination, 0o600)
            copied[kind] = destination
        return copied

    @staticmethod
    def _copy_with_clean_lintel(source: Path, destination: Path) -> None:
        """Derive a clean architectural reference from a gate photo with a signed lintel."""

        with Image.open(source) as loaded:
            image = loaded.convert("RGB")
        overlay: Image.Image | None = None
        result: Image.Image | None = None
        try:
            width, height = image.size
            top, bottom = round(height * 0.25), round(height * 0.40)
            sample = image.crop(
                (round(width * 0.18), round(height * 0.22), round(width * 0.82), top)
            )
            fill = tuple(round(value) for value in ImageStat.Stat(sample).median)
            sample.close()
            overlay = image.copy()
            draw = ImageDraw.Draw(overlay)
            draw.rectangle((0, top, width, bottom), fill=fill)
            edge = tuple(max(0, value - 18) for value in fill)
            draw.line((0, top, width, top), fill=edge, width=max(1, height // 180))
            draw.line((0, bottom, width, bottom), fill=edge, width=max(1, height // 180))
            mask = Image.new("L", image.size, 0)
            ImageDraw.Draw(mask).rectangle((0, top, width, bottom), fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2, width // 100)))
            result = Image.composite(overlay, image, mask)
            mask.close()
            result.save(destination)
        finally:
            if result is not None:
                result.close()
            if overlay is not None:
                overlay.close()
            image.close()

    @staticmethod
    def _private_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)

    @staticmethod
    def _harden_tree(root: Path) -> None:
        for path in [root, *root.rglob("*")]:
            if path.is_symlink():
                raise ValueError(f"autonomous artifact tree contains a symlink: {path}")
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
