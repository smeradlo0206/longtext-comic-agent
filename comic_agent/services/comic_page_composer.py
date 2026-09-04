"""Idempotent page composition for individually generated comic panels."""

from __future__ import annotations

import json
import time
from pathlib import Path

from comic_agent.schemas.comic_production import (
    ComicPageArtifactV1,
    ComicProductionManifestV1,
)
from comic_agent.services.comic_letterer import ComicLetterer
from flux2_agent.workflow import create_contact_sheet, write_json


class ComicPageComposer:
    """Compose generated single panels into page files without another model call."""

    def __init__(self, letterer: ComicLetterer | None = None) -> None:
        self._letterer = letterer or ComicLetterer()

    def compose(
        self,
        *,
        run_root: Path,
        manifest: ComicProductionManifestV1,
    ) -> list[ComicPageArtifactV1]:
        result_path = run_root / "result.json"
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if payload.get("status") != "succeeded":
            raise ValueError("comic pages can only be composed from a succeeded image run")
        output_by_panel = {
            item["shot_id"]: item["output"]
            for item in payload.get("shots", [])
            if item.get("status") == "succeeded" and isinstance(item.get("output"), str)
        }

        performance = payload.setdefault("performance", {})
        stages = performance.setdefault("stages", {})
        lettering_started = time.perf_counter()
        lettered_panels: list[dict[str, object]] = []
        if manifest.request.dialogue_layout.enabled:
            proposal_by_panel = {
                item.panel.panel_id: item for item in manifest.proposal.panels
            }
            for panel_id, source_name in output_by_panel.items():
                destination = run_root / f"lettered-{panel_id}.png"
                artifact = self._letterer.render(
                    source=run_root / source_name,
                    destination=destination,
                    overlays=proposal_by_panel[panel_id].panel.text_overlays,
                    settings=manifest.request.dialogue_layout,
                )
                output_by_panel[panel_id] = destination.name
                lettered_panels.append({"panel_id": panel_id} | artifact)
        lettering_seconds = time.perf_counter() - lettering_started
        stages["lettering"] = round(lettering_seconds, 3)
        payload["lettered_panels"] = lettered_panels

        artifacts: list[ComicPageArtifactV1] = []
        composition_started = time.perf_counter()
        for page in manifest.proposal.pages:
            missing = [panel_id for panel_id in page.panel_ids if panel_id not in output_by_panel]
            if missing:
                raise ValueError(f"page {page.page_id} is missing generated panels: {missing}")
            filename = f"page-{page.order + 1:03d}.png"
            sheet = create_contact_sheet(
                run_root,
                [output_by_panel[panel_id] for panel_id in page.panel_ids],
                columns=min(3, len(page.panel_ids)),
                filename=filename,
            )
            artifacts.append(
                ComicPageArtifactV1(
                    page_id=page.page_id,
                    order=page.order,
                    panel_ids=page.panel_ids,
                    file=filename,
                    width=int(sheet["width"]),
                    height=int(sheet["height"]),
                )
            )

        composition_seconds = time.perf_counter() - composition_started
        stages["page_composition"] = round(composition_seconds, 3)
        previous_total = performance.get("end_to_end_seconds")
        if isinstance(previous_total, int | float):
            total = float(previous_total) + lettering_seconds + composition_seconds
            performance["end_to_end_seconds"] = round(total, 3)
            budget = performance.get("latency_budget_seconds")
            if isinstance(budget, int | float):
                performance["workflow_within_budget"] = total <= float(budget)
        single_image = performance.get("single_image_seconds")
        if isinstance(single_image, int | float):
            panel_count = max(1, len(output_by_panel))
            page_count = max(1, len(artifacts))
            single_image_total = (
                float(single_image)
                + lettering_seconds / panel_count
                + composition_seconds / page_count
            )
            performance["single_image_seconds"] = round(single_image_total, 3)
            budget = performance.get("latency_budget_seconds")
            if isinstance(budget, int | float):
                performance["within_budget"] = single_image_total <= float(budget)
        payload["comic_pages"] = [item.model_dump(mode="json") for item in artifacts]
        write_json(result_path, payload)
        write_json(
            run_root / "production-manifest.json",
            manifest.model_dump(mode="json"),
        )
        return artifacts
