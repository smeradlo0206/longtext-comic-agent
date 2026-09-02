"""Stable end-to-end comic demo orchestration, isolated from production approval."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from comic_agent.demo.html_renderer import DemoHtmlRenderer
from comic_agent.demo.narrative_adapter import DemoNarrativeAdapter
from comic_agent.demo.storybible_builder import DemoStoryBibleBuilder
from comic_agent.demo.timeline_adapter import DemoRecoverableTimelineError, DemoTimelineAdapter
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EntityProposalV1, EventProposalV1
from comic_agent.schemas.storybible import ApprovedStoryBibleBundleV1
from comic_agent.schemas.timeline import ApprovedTimelineBundleV1
from comic_agent.services.comic_planning_service import ComicPlanningService
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.id_service import stable_id
from comic_agent.services.panel_planning_service import PanelPlanningService


class DemoRecoverableCuratorError(RuntimeError):
    """Provider/normalization errors for which the demo must fall back."""


@dataclass(frozen=True)
class DemoRunResult:
    artifact_dir: Path
    summary: dict[str, Any]


class ComicDemoPipeline:
    def __init__(
        self,
        *,
        curator: Callable[..., ApprovedStoryBibleBundleV1] | None = None,
        narrative_adapter: DemoNarrativeAdapter | None = None,
        timeline_adapter: DemoTimelineAdapter | None = None,
        gate2: Callable[[list[EventProposalV1]], dict[str, Any]] | None = None,
        gate3: Callable[[ApprovedTimelineBundleV1], dict[str, Any]] | None = None,
    ) -> None:
        self.curator = curator
        self.narrative_adapter = narrative_adapter
        self.timeline_adapter = timeline_adapter
        self.gate2 = gate2 or (lambda _: {"status": "APPROVED", "issues": []})
        self.gate3 = gate3 or (lambda _: {"status": "APPROVED", "issues": []})

    def run(
        self,
        *,
        input_path: Path,
        output_root: Path,
        provider_mode: str = "auto",
        skip_storybible_provider: bool = False,
    ) -> DemoRunResult:
        text = input_path.read_text(encoding="utf-8")
        project_id = stable_id("comic-demo-project", input_path.name, text)
        parsed = DocumentParser().parse_txt(project_id, input_path.name, text)
        narrative_calls = 0
        timeline_calls = 0
        narrative_error: str | None = None
        timeline_error: str | None = None
        timeline_real_attempted = False
        if provider_mode == "deterministic":
            entities, events = self._narrative(parsed.chunks)
            narrative_source = "DEMO_DETERMINISTIC"
            gate2 = self.gate2(events)
        else:
            try:
                if self.narrative_adapter is None:
                    raise RuntimeError("production Narrative adapter is not configured")
                narrative_result = self.narrative_adapter.run()
                entities, events = narrative_result.entities, narrative_result.events
                narrative_source = narrative_result.source
                narrative_calls = narrative_result.provider_request_count
                gate2 = {
                    "status": narrative_result.gate2_status,
                    "issues": narrative_result.gate2_issues,
                }
            except Exception as exc:
                if provider_mode == "real":
                    raise
                narrative_error = f"{type(exc).__name__}: {exc}"
                entities, events = self._narrative(parsed.chunks)
                narrative_source = "DEMO_FALLBACK"
                gate2 = self.gate2(events)
        if provider_mode == "deterministic" or narrative_source == "DEMO_FALLBACK":
            timeline = self._timeline(project_id, events)
            timeline_source = (
                "DEMO_DETERMINISTIC" if provider_mode == "deterministic" else "DEMO_FALLBACK"
            )
            gate3 = self.gate3(timeline)
        else:
            try:
                if self.timeline_adapter is None:
                    raise RuntimeError("production Timeline adapter is not configured")
                timeline_real_attempted = True
                timeline_calls = 1
                timeline_result = self.timeline_adapter.run(events)
                timeline = timeline_result.timeline
                timeline_source = timeline_result.source
                timeline_calls = timeline_result.provider_request_count
                gate3 = {
                    "status": timeline_result.gate3_status,
                    "issues": timeline_result.gate3_issues,
                }
            except DemoRecoverableTimelineError as exc:
                if provider_mode == "real":
                    raise
                timeline_error = f"{type(exc).__name__}: {exc}"
                timeline = self._timeline(project_id, events)
                timeline_source = "DEMO_FALLBACK"
                gate3 = {
                    "status": "NOT_APPLICABLE_TO_DEMO_FALLBACK",
                    "issues": [],
                }
        storybible_source = "REAL_CURATOR"
        fallback_reason: str | None = None
        storybible_calls = 0
        try:
            if timeline_source == "DEMO_FALLBACK":
                raise DemoRecoverableCuratorError(
                    "demo timeline is not a production-approved timeline input"
                )
            if skip_storybible_provider:
                raise DemoRecoverableCuratorError("StoryBible provider skipped by demo option")
            if self.curator is None:
                raise DemoRecoverableCuratorError("real StoryBible curator is not configured")
            storybible_calls = 1
            storybible = self.curator(
                project_id=project_id,
                source_chunks=parsed.chunks,
                narrative_entities=entities,
                narrative_events=events,
                timeline=timeline,
            )
        except (TimeoutError, DemoRecoverableCuratorError, ValidationError, ValueError) as exc:
            storybible_source = "DEMO_FALLBACK"
            fallback_reason = f"{type(exc).__name__}: {exc}"
            storybible = DemoStoryBibleBuilder().build(
                project_id=project_id,
                source_chunks=parsed.chunks,
                narrative_entities=entities,
                narrative_events=events,
                timeline=timeline,
            )
        scenes = ComicPlanningService().plan(storybible=storybible, timeline=timeline)
        panels = [
            PanelPlanningService().plan(scene=scene, storybible=storybible) for scene in scenes
        ]
        run_id = stable_id("comic-demo-run", project_id, provider_mode)[:24]
        artifact_dir = output_root / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        review_findings = {"gate2": gate2, "gate3": gate3}
        summary = {
            "status": "SUCCESS",
            "input": str(input_path.resolve()),
            "provider_mode": provider_mode,
            "narrative_status": "SUCCESS",
            "narrative_source": narrative_source,
            "narrative_error": narrative_error,
            "timeline_status": "SUCCESS",
            "timeline_source": timeline_source,
            "timeline_error": timeline_error,
            "timeline_real_attempted": timeline_real_attempted,
            "timeline_fallback_reason": timeline_error,
            "gate2_status": gate2["status"],
            "gate3_status": gate3["status"],
            "storybible_source": storybible_source,
            "storybible_fallback_reason": fallback_reason,
            "comic_plan_status": "SUCCESS",
            "scene_count": len(scenes),
            "panel_count": len(panels),
            "provider_calls": {
                "narrative": narrative_calls,
                "timeline": timeline_calls,
                "storybible": storybible_calls,
            },
            "artifact_dir": str(artifact_dir.resolve()),
            "review_findings": review_findings,
            "demo_review_decision": "CONTINUE_FOR_DEMO",
            "review_disclaimer": "This does not represent production approval.",
        }
        self._write_json(artifact_dir / "summary.json", summary)
        self._write_json(
            artifact_dir / "narrative.json",
            {
                "entities": [x.model_dump(mode="json") for x in entities],
                "events": [x.model_dump(mode="json") for x in events],
                "review_findings": {"gate2": gate2},
            },
        )
        self._write_json(
            artifact_dir / "timeline.json",
            {**timeline.model_dump(mode="json"), "review_findings": {"gate3": gate3}},
        )
        self._write_json(
            artifact_dir / "storybible.json",
            {
                "storybible_source": storybible_source,
                "fallback_reason": fallback_reason,
                "bundle": storybible.model_dump(mode="json"),
            },
        )
        self._write_json(
            artifact_dir / "comic_plan.json", [x.model_dump(mode="json") for x in scenes]
        )
        self._write_json(artifact_dir / "panels.json", [x.model_dump(mode="json") for x in panels])
        (artifact_dir / "demo_report.md").write_text(
            self._report(
                input_path, text, entities, events, timeline, storybible, scenes, panels, summary
            ),
            encoding="utf-8",
        )
        try:
            DemoHtmlRenderer().render(artifact_dir)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            summary["html_status"] = "FAILED"
            summary["html_error"] = f"{type(exc).__name__}: {exc}"
            self._write_json(artifact_dir / "summary.json", summary)
        else:
            summary["html_status"] = "SUCCESS"
            self._write_json(artifact_dir / "summary.json", summary)
        return DemoRunResult(artifact_dir=artifact_dir, summary=summary)

    @staticmethod
    def _narrative(chunks: list[Any]) -> tuple[list[EntityProposalV1], list[EventProposalV1]]:
        entities: list[EntityProposalV1] = []
        events: list[EventProposalV1] = []
        known: dict[str, str] = {}
        for chunk in chunks:
            quote = chunk.text.strip()
            evidence = EvidenceRefV1(
                chunk_id=chunk.chunk_id, quote_start=0, quote_end=len(quote), quote_text=quote
            )
            names = re.findall(r"\b[A-Z][a-z]{1,30}\b", quote)
            for name in names:
                if name not in known:
                    proposal_id = stable_id("demo-entity", chunk.project_id, name)
                    known[name] = proposal_id
                    entities.append(
                        EntityProposalV1(
                            proposal_id=proposal_id,
                            entity_type="CHARACTER",
                            canonical_name=name,
                            evidence_refs=[evidence],
                            confidence=0.5,
                        )
                    )
            event_id = stable_id("demo-event", chunk.project_id, chunk.chunk_id)
            events.append(
                EventProposalV1(
                    proposal_id=event_id,
                    event_type="SOURCE_CHUNK_EVENT",
                    summary=quote[:240],
                    participant_ids=[known[name] for name in names if name in known],
                    evidence_refs=[evidence],
                    confidence=0.5,
                    reality_layer=RealityLayer.PRIMARY,
                )
            )
        return sorted(entities, key=lambda x: x.proposal_id), events

    @staticmethod
    def _timeline(project_id: str, events: list[EventProposalV1]) -> ApprovedTimelineBundleV1:
        evidence = []
        for event in events:
            for ref in event.evidence_refs:
                if ref not in evidence:
                    evidence.append(ref)
        event_ids = [event.proposal_id for event in events]
        return ApprovedTimelineBundleV1(
            bundle_id=stable_id("demo-timeline", project_id, *event_ids),
            project_id=project_id,
            source_approved_proposal_bundle_id=stable_id("demo-gate2-bundle", project_id),
            source_gate2_review_id=stable_id("demo-gate2-review", project_id),
            source_gate2_route_id=stable_id("demo-gate2-route", project_id),
            timeline_run_id=stable_id("demo-timeline-run", project_id),
            gate3_review_id=stable_id("demo-gate3-review", project_id),
            gate3_route_id=stable_id("demo-gate3-route", project_id),
            event_ids=event_ids,
            evidence_refs=evidence,
            created_at=datetime(2000, 1, 1, tzinfo=UTC),
        )

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _report(
        input_path: Path,
        text: str,
        entities: list[Any],
        events: list[Any],
        timeline: Any,
        storybible: Any,
        scenes: list[Any],
        panels: list[Any],
        summary: dict[str, Any],
    ) -> str:
        lines = [
            "# Comic Generation Demo",
            "",
            "## Execution provenance",
            "",
            f"- Narrative: **{summary['narrative_source']}**",
            f"- Timeline: **{summary['timeline_source']}**",
            f"- StoryBible: **{summary['storybible_source']}**",
            f"- Comic Planning: **{summary['comic_plan_status']}**",
            "",
            f"- Input: `{input_path}` ({len(text)} characters)",
            "- Demo review decision: `CONTINUE_FOR_DEMO`",
            "- This does not represent production approval.",
        ]
        if summary["timeline_source"] == "DEMO_FALLBACK":
            lines += [
                "",
                "Timeline real provider was attempted but its response failed the production",
                "schema contract. The demo therefore continued with a deterministic timeline",
                "derived from the real Narrative analysis.",
            ]
        lines += ["", "## Characters"]
        lines += [
            f"- {x.canonical_name}" for x in storybible.entities if str(x.entity_kind) == "PERSON"
        ] or ["- None extracted"]
        lines += ["", "## Story Events"] + [f"- {x.summary}" for x in events]
        lines += [
            "",
            "## Timeline",
            f"- Event order: {' → '.join(timeline.event_ids)}",
            "",
            "## Gate warnings",
            f"- Gate 2: {summary['gate2_status']}",
            f"- Gate 3: {summary['gate3_status']}",
            "",
            "## StoryBible entities",
        ] + [f"- {x.entity_kind}: {x.canonical_name}" for x in storybible.entities]
        lines += ["", "## Character / Scene State"] + [
            f"- {x.profile_id}: {x.state}" for x in storybible.state_changes
        ]
        if not storybible.state_changes:
            lines += ["- No explicit state changes extracted"]
        lines += ["", "## Comic Scenes"] + [f"- {x.title}: {x.summary}" for x in scenes]
        lines += ["", "## Panels"] + [
            (
                f"- `{x.panel_id}` — {x.narrative_beat}; visual: "
                f"{x.shot_type}, {x.camera_angle}, {x.composition}, "
                f"background={x.background or 'UNKNOWN'}"
            )
            for x in panels
        ]
        return "\n".join(lines) + "\n"
