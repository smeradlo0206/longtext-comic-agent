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
from comic_agent.services.narrative_analysis_aggregation import aggregate_narrative_analysis
from comic_agent.services.narrative_analysis_proposal_sources import proposal_sources_for_window
from comic_agent.services.review_gate2_service import build_review_gate2_input


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


def test_cross_window_local_proposal_ids_become_unique_before_gate2_input() -> None:
    """A Provider-local `evt_001` must not make the whole-document Gate 2 input invalid."""

    def source_for(*, run_id: str, window_id: str, chunk_id: str, summary: str):
        proposal = EventProposalV1(
            proposal_id="evt_001",
            event_type="ACTION",
            summary=summary,
            evidence_refs=[EvidenceRefV1(chunk_id=chunk_id, quote_text=summary)],
            confidence=0.8,
            reality_layer="PRIMARY",
        )
        batch = EventProposalBatchV1(batch_id=f"batch-{window_id}", events=[proposal])
        agent_run = AgentRunV1(
            agent_run_id=run_id,
            project_id="project-1",
            agent_name="narrative-analyst:event_extraction",
            input_chunk_ids=[chunk_id],
            output_proposal_ids=[proposal.proposal_id],
            output_schema="EventProposalBatchV1",
            provider_result=ProviderResultV1(
                provider_result_id=f"provider-{window_id}",
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
            analysis_window_id=window_id,
            analysis_run_id="root-run",
            mode="event_extraction",
            window_index=0,
            chunk_ids=[chunk_id],
            owned_chunk_ids=[chunk_id],
            status=NarrativeAnalysisWindowStatus.SUCCEEDED,
            agent_run_id=run_id,
        )
        return proposal_sources_for_window(agent_run, window)

    sources = [
        *source_for(
            run_id="agent-run-1",
            window_id="window-1",
            chunk_id="chunk-1",
            summary="First source-supported action.",
        ),
        *source_for(
            run_id="agent-run-2",
            window_id="window-2",
            chunk_id="chunk-2",
            summary="Second source-supported action.",
        ),
    ]

    aggregate = aggregate_narrative_analysis(sources, analysis_run_id="root-run")
    review_input = build_review_gate2_input(
        result=aggregate,
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=["chunk-1", "chunk-2"],
    )

    assert len(review_input.proposals) == 2
    assert len({item.proposal.proposal_id for item in review_input.proposals}) == 2
