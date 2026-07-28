"""Mock agent implementations for tests and examples."""

from comic_agent.agents.specs import AgentSpec
from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.source import SourceChunkV1


class MockEventAgent:
    """Deterministic event agent used to verify the source-evidence workflow."""

    spec = AgentSpec(
        agent_id="mock-event-agent",
        version="1.0",
        reads=["SourceChunkV1"],
        output_schema="EventProposalV1",
        tools=[],
        can_write_canonical_data=False,
        requires_evidence=True,
        max_context_chunks=3,
        confidence_threshold=0.7,
    )

    def run(self, chunk: SourceChunkV1) -> EventProposalV1:
        """Return one fixed-format proposal with an exact reference to ``chunk``.

        This deliberately performs no language understanding and makes no model call.
        It exists solely to exercise schema validation and evidence traceability.
        """

        return EventProposalV1(
            proposal_id=f"mock-event-{chunk.chunk_id}",
            event_type="MOCK_EVENT",
            summary="Mock event extracted from source chunk.",
            participant_ids=[],
            location_id=None,
            evidence_refs=[
                EvidenceRefV1(
                    chunk_id=chunk.chunk_id,
                    quote_start=0,
                    quote_end=len(chunk.text),
                    quote_text=chunk.text,
                )
            ],
            confidence=1.0,
            reality_layer=RealityLayer.PRIMARY,
        )
