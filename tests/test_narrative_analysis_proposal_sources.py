"""Regression coverage for bounded AgentRun proposal-source conversion."""

from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.narrative import EventProposalBatchV1, EventProposalV1
from comic_agent.schemas.workflow import (
    AgentRunStatus,
    AgentRunV1,
    NarrativeAnalysisWindowStatus,
    NarrativeAnalysisWindowV1,
    ProviderResultV1,
    ProviderType,
)
from comic_agent.services.narrative_analysis_proposal_sources import proposal_sources_for_window


def test_proposal_sources_preserve_window_mode_and_new_agent_run_provenance() -> None:
    proposal = EventProposalV1(
        proposal_id="new-event",
        event_type="ACTION",
        summary="A bounded synthetic action.",
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-1", quote_text="synthetic")],
        confidence=0.8,
        reality_layer="PRIMARY",
    )
    batch = EventProposalBatchV1(batch_id="batch-1", events=[proposal])
    agent_run = AgentRunV1(
        agent_run_id="new-agent-run",
        project_id="project-1",
        agent_name="narrative-analyst:event_extraction",
        input_chunk_ids=["chunk-1"],
        output_proposal_ids=[proposal.proposal_id],
        output_schema="EventProposalBatchV1",
        provider_result=ProviderResultV1(
            provider_result_id="provider-result-1",
            provider_name="fake",
            provider_type=ProviderType.MOCK,
            output_schema="EventProposalBatchV1",
            structured_output=batch.model_dump(mode="json"),
            success=True,
        ),
        status=AgentRunStatus.SUCCEEDED,
        payload={"proposal": batch.model_dump(mode="json")},
    )
    window = NarrativeAnalysisWindowV1(
        analysis_window_id="window-1",
        analysis_run_id="root-run",
        mode="event_extraction",
        window_index=0,
        chunk_ids=["chunk-1"],
        owned_chunk_ids=["chunk-1"],
        status=NarrativeAnalysisWindowStatus.SUCCEEDED,
        agent_run_id="new-agent-run",
    )

    sources = proposal_sources_for_window(agent_run, window)

    observed = [
        (source.mode, source.agent_run_id, source.proposal.proposal_id)
        for source in sources
    ]
    assert observed == [("event_extraction", "new-agent-run", "new-event")]
