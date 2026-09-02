"""Thin adaptation from the demo pipeline to an existing Narrative service."""

from dataclasses import dataclass
from typing import Protocol

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import EntityProposalV1, EventProposalV1


class ProductionNarrativeRunner(Protocol):
    def run_narrative(self) -> tuple[list[EntityProposalV1], list[EventProposalV1], int]: ...


@dataclass(frozen=True)
class DemoNarrativeResult:
    source: str
    entities: list[EntityProposalV1]
    events: list[EventProposalV1]
    evidence_refs: list[EvidenceRefV1]
    gate2_status: str
    gate2_issues: list[str]
    provider_request_count: int


class DemoNarrativeAdapter:
    """Call the configured production Narrative runner without implementing an agent."""

    def __init__(self, runner: ProductionNarrativeRunner) -> None:
        self._runner = runner

    def run(self) -> DemoNarrativeResult:
        entities, events, count = self._runner.run_narrative()
        evidence: list[EvidenceRefV1] = []
        proposals: list[EntityProposalV1 | EventProposalV1] = [*entities, *events]
        for proposal in proposals:
            for ref in proposal.evidence_refs:
                if ref not in evidence:
                    evidence.append(ref)
        if not events:
            raise RuntimeError("production Narrative returned no event proposals")
        return DemoNarrativeResult(
            source="REAL_PROVIDER",
            entities=entities,
            events=events,
            evidence_refs=evidence,
            gate2_status="RECORDED_FOR_DEMO",
            gate2_issues=[],
            provider_request_count=count,
        )
