from pathlib import Path

import pytest

from comic_agent.demo.narrative_adapter import DemoNarrativeAdapter
from comic_agent.demo.pipeline import ComicDemoPipeline, DemoRecoverableCuratorError
from comic_agent.demo.storybible_builder import DemoStoryBibleBuilder
from comic_agent.demo.timeline_adapter import DemoRecoverableTimelineError, DemoTimelineAdapter
from comic_agent.services.document_parser import DocumentParser
from comic_agent.services.id_service import stable_id


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "novel.txt"
    path.write_text("Lin opens the North Gate.\nMira follows Lin inside.", encoding="utf-8")
    return path


def test_curator_length_failure_falls_back_and_writes_artifacts(tmp_path: Path) -> None:
    def curator(**_: object):
        raise DemoRecoverableCuratorError("finish_reason=length")

    result = ComicDemoPipeline(curator=curator).run(
        input_path=_source(tmp_path),
        output_root=tmp_path / "out",
        provider_mode="deterministic",
    )
    assert result.summary["storybible_source"] == "DEMO_FALLBACK"
    assert result.summary["comic_plan_status"] == "SUCCESS"
    assert result.summary["panel_count"] > 0
    for name in ("summary.json", "demo_report.md", "comic_plan.json", "panels.json"):
        assert (result.artifact_dir / name).is_file()


def test_curator_success_is_marked_real(tmp_path: Path) -> None:
    builder = DemoStoryBibleBuilder()

    def curator(**kwargs: object):
        return builder.build(**kwargs)

    result = ComicDemoPipeline(curator=curator).run(
        input_path=_source(tmp_path),
        output_root=tmp_path / "out",
        provider_mode="deterministic",
    )
    assert result.summary["storybible_source"] == "REAL_CURATOR"


def test_gate_review_does_not_block_comic_planning(tmp_path: Path) -> None:
    def finding(_: object) -> dict[str, object]:
        return {"status": "NEEDS_HUMAN_REVIEW", "issues": ["ambiguous"]}

    result = ComicDemoPipeline(gate2=finding, gate3=finding).run(
        input_path=_source(tmp_path),
        output_root=tmp_path / "out",
        provider_mode="deterministic",
    )
    assert result.summary["demo_review_decision"] == "CONTINUE_FOR_DEMO"
    assert result.summary["panel_count"] > 0


def test_fallback_is_deterministic(tmp_path: Path) -> None:
    pipeline = ComicDemoPipeline()
    first = pipeline.run(
        input_path=_source(tmp_path),
        output_root=tmp_path / "one",
        provider_mode="deterministic",
    )
    second = pipeline.run(
        input_path=_source(tmp_path),
        output_root=tmp_path / "two",
        provider_mode="deterministic",
    )
    assert (first.artifact_dir / "storybible.json").read_text(encoding="utf-8") == (
        second.artifact_dir / "storybible.json"
    ).read_text(encoding="utf-8")


class _ProductionRunner:
    def __init__(
        self,
        tmp_path: Path,
        *,
        fail_narrative: bool = False,
        fail_timeline: bool = False,
    ) -> None:
        self.fail_narrative = fail_narrative
        self.fail_timeline = fail_timeline
        source = _source(tmp_path)
        project_id = stable_id("comic-demo-project", source.name, source.read_text("utf-8"))
        pipeline = ComicDemoPipeline()
        chunks = (
            DocumentParser().parse_txt(project_id, source.name, source.read_text("utf-8")).chunks
        )
        parsed = pipeline._narrative(chunks)  # noqa: SLF001 - bounded test fixture
        self.entities, self.events = parsed
        self.timeline = pipeline._timeline(project_id, self.events)  # noqa: SLF001
        self.narrative_called = 0
        self.timeline_called = 0
        self.timeline_input = None

    def run_narrative(self):
        self.narrative_called += 1
        if self.fail_narrative:
            raise RuntimeError("provider unavailable")
        return self.entities, self.events, 2

    def run_timeline(self, events):
        self.timeline_called += 1
        self.timeline_input = events
        assert events == self.events
        if self.fail_timeline:
            raise DemoRecoverableTimelineError("provider response failed schema validation")
        return self.timeline, "APPROVED", [], 1


def test_real_adapters_call_production_runner(tmp_path: Path) -> None:
    runner = _ProductionRunner(tmp_path)
    narrative = DemoNarrativeAdapter(runner).run()
    timeline = DemoTimelineAdapter(runner).run(narrative.events)
    assert narrative.source == "REAL_PROVIDER"
    assert timeline.source == "REAL_PROVIDER"
    assert runner.narrative_called == runner.timeline_called == 1


def test_real_mode_narrative_failure_is_not_hidden(tmp_path: Path) -> None:
    runner = _ProductionRunner(tmp_path, fail_narrative=True)
    pipeline = ComicDemoPipeline(
        narrative_adapter=DemoNarrativeAdapter(runner),
        timeline_adapter=DemoTimelineAdapter(runner),
    )
    with pytest.raises(RuntimeError, match="provider unavailable"):
        pipeline.run(
            input_path=_source(tmp_path), output_root=tmp_path / "out", provider_mode="real"
        )
    assert runner.timeline_called == 0


def test_auto_mode_falls_back_without_calling_real_timeline(tmp_path: Path) -> None:
    runner = _ProductionRunner(tmp_path, fail_narrative=True)
    result = ComicDemoPipeline(
        narrative_adapter=DemoNarrativeAdapter(runner),
        timeline_adapter=DemoTimelineAdapter(runner),
    ).run(input_path=_source(tmp_path), output_root=tmp_path / "out", provider_mode="auto")
    assert result.summary["narrative_source"] == "DEMO_FALLBACK"
    assert result.summary["timeline_source"] == "DEMO_FALLBACK"
    assert runner.timeline_called == 0


def test_real_mode_refuses_unconfigured_storybible_fallback(tmp_path: Path) -> None:
    runner = _ProductionRunner(tmp_path)
    pipeline = ComicDemoPipeline(
        narrative_adapter=DemoNarrativeAdapter(runner),
        timeline_adapter=DemoTimelineAdapter(runner),
    )

    with pytest.raises(DemoRecoverableCuratorError, match="not configured"):
        pipeline.run(
            input_path=_source(tmp_path),
            output_root=tmp_path / "out",
            provider_mode="real",
        )


def test_auto_mode_may_fallback_when_storybible_is_unconfigured(tmp_path: Path) -> None:
    runner = _ProductionRunner(tmp_path)
    result = ComicDemoPipeline(
        narrative_adapter=DemoNarrativeAdapter(runner),
        timeline_adapter=DemoTimelineAdapter(runner),
    ).run(input_path=_source(tmp_path), output_root=tmp_path / "out", provider_mode="auto")
    assert result.summary["narrative_source"] == "REAL_PROVIDER"
    assert result.summary["timeline_source"] == "REAL_PROVIDER"
    assert result.summary["storybible_source"] == "DEMO_FALLBACK"
    assert result.summary["comic_plan_status"] == "SUCCESS"
    assert result.summary["panel_count"] > 0


def test_auto_timeline_schema_failure_falls_back_from_real_narrative(
    tmp_path: Path,
) -> None:
    runner = _ProductionRunner(tmp_path, fail_timeline=True)
    result = ComicDemoPipeline(
        narrative_adapter=DemoNarrativeAdapter(runner),
        timeline_adapter=DemoTimelineAdapter(runner),
    ).run(input_path=_source(tmp_path), output_root=tmp_path / "out", provider_mode="auto")
    assert result.summary["status"] == "SUCCESS"
    assert result.summary["narrative_source"] == "REAL_PROVIDER"
    assert result.summary["timeline_source"] == "DEMO_FALLBACK"
    assert result.summary["timeline_real_attempted"] is True
    assert "schema validation" in result.summary["timeline_fallback_reason"]
    assert runner.timeline_input is runner.events


def test_real_timeline_schema_failure_remains_fail_closed(tmp_path: Path) -> None:
    runner = _ProductionRunner(tmp_path, fail_timeline=True)
    pipeline = ComicDemoPipeline(
        narrative_adapter=DemoNarrativeAdapter(runner),
        timeline_adapter=DemoTimelineAdapter(runner),
    )
    with pytest.raises(DemoRecoverableTimelineError, match="schema validation"):
        pipeline.run(
            input_path=_source(tmp_path), output_root=tmp_path / "out", provider_mode="real"
        )


def test_auto_full_timeline_and_storybible_fallback_reaches_panels(tmp_path: Path) -> None:
    runner = _ProductionRunner(tmp_path, fail_timeline=True)
    result = ComicDemoPipeline(
        narrative_adapter=DemoNarrativeAdapter(runner),
        timeline_adapter=DemoTimelineAdapter(runner),
    ).run(input_path=_source(tmp_path), output_root=tmp_path / "out", provider_mode="auto")
    assert result.summary["storybible_source"] == "DEMO_FALLBACK"
    assert "not a production-approved" in result.summary["storybible_fallback_reason"]
    assert result.summary["comic_plan_status"] == "SUCCESS"
    assert result.summary["scene_count"] > 0
    assert result.summary["panel_count"] > 0
