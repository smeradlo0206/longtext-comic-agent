"""Thin adaptation from real Narrative proposals to the existing Timeline service."""

from dataclasses import dataclass
from typing import Protocol

from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.timeline import ApprovedTimelineBundleV1


class DemoRecoverableTimelineError(RuntimeError):
    """A provider/output failure that auto mode may replace for Demo purposes."""


class ProductionTimelineRunner(Protocol):
    def run_timeline(
        self, events: list[EventProposalV1]
    ) -> tuple[ApprovedTimelineBundleV1, str, list[str], int]: ...


@dataclass(frozen=True)
class DemoTimelineResult:
    source: str
    timeline: ApprovedTimelineBundleV1
    gate3_status: str
    gate3_issues: list[str]
    provider_request_count: int


class DemoTimelineAdapter:
    """Pass Narrative proposals to the configured production Timeline runner."""

    def __init__(self, runner: ProductionTimelineRunner) -> None:
        self._runner = runner

    def run(self, events: list[EventProposalV1]) -> DemoTimelineResult:
        timeline, status, issues, count = self._runner.run_timeline(events)
        return DemoTimelineResult(
            source="REAL_PROVIDER",
            timeline=timeline,
            gate3_status=status,
            gate3_issues=issues,
            provider_request_count=count,
        )
