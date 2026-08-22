"""Cross-window proposal ID normalization at the Narrative aggregate boundary."""

from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EventProposalV1, StateChangeProposalV1
from comic_agent.schemas.workflow import NarrativeAnalysisProposalSourceV1
from comic_agent.services.narrative_analysis_aggregation import aggregate_narrative_analysis
from comic_agent.services.review_gate2_service import build_review_gate2_input


def _event(local_id: str, summary: str, chunk_id: str) -> EventProposalV1:
    return EventProposalV1(
        proposal_id=local_id,
        event_type="ACTION",
        summary=summary,
        actor_resolution_status="UNKNOWN",
        evidence_refs=[EvidenceRefV1(chunk_id=chunk_id, quote_text=summary)],
        confidence=0.9,
        reality_layer=RealityLayer.PRIMARY,
    )


def _source(agent_run_id: str, proposal) -> NarrativeAnalysisProposalSourceV1:  # type: ignore[no-untyped-def]
    return NarrativeAnalysisProposalSourceV1(
        mode="event_extraction",
        agent_run_id=agent_run_id,
        proposal=proposal,
    )


def test_cross_window_local_ids_are_unique_and_gate2_valid() -> None:
    sources = [
        _source("run-a", _event("evt-1", "Event A1", "chunk-a")),
        _source("run-a", _event("evt-2", "Event A2", "chunk-a")),
        _source("run-b", _event("evt-1", "Event B1", "chunk-b")),
        _source("run-b", _event("evt-2", "Event B2", "chunk-b")),
    ]
    scopes = {"run-a": "window-a", "run-b": "window-b"}

    result = aggregate_narrative_analysis(
        sources, analysis_run_id="analysis-1", source_scopes=scopes
    )
    proposal_ids = [item.proposal.proposal_id for item in result.events]
    review_input = build_review_gate2_input(
        result=result,
        project_id="project-1",
        document_id="document-1",
        allowed_chunk_ids=["chunk-a", "chunk-b"],
    )

    assert len(result.events) == 4
    assert len(proposal_ids) == len(set(proposal_ids))
    assert len(review_input.proposals) == 4
    assert [item.agent_run_ids for item in result.events] == [
        ["run-a"],
        ["run-a"],
        ["run-b"],
        ["run-b"],
    ]


def test_normalized_ids_are_repeatable_for_resume() -> None:
    sources = [_source("run-a", _event("evt-1", "Event A1", "chunk-a"))]
    kwargs = {"analysis_run_id": "analysis-1", "source_scopes": {"run-a": "window-a"}}

    first = aggregate_narrative_analysis(sources, **kwargs)
    second = aggregate_narrative_analysis(sources, **kwargs)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_state_change_reference_tracks_normalized_event_id() -> None:
    event = _event("evt-1", "Event A1", "chunk-a")
    change = StateChangeProposalV1(
        schema_version="1.1",
        proposal_id="change-1",
        event={
            "event_summary": "Event A1",
            "event_proposal_id": "evt-1",
            "proposal_schema": "EventProposalV1",
            "resolution_status": "RESOLVED",
        },
        target={
            "mention_text": "the door",
            "entity_proposal_id": None,
            "proposal_schema": None,
            "resolution_status": "UNRESOLVED",
        },
        attribute_path="door.state",
        old_value="open",
        new_value="closed",
        persistent=True,
        reality_layer=RealityLayer.PRIMARY,
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-a", quote_text="Event A1")],
        confidence=0.9,
    )
    sources = [
        _source("event-run", event),
        NarrativeAnalysisProposalSourceV1(
            mode="state_change_extraction",
            agent_run_id="change-run",
            proposal=change,
        ),
    ]

    result = aggregate_narrative_analysis(
        sources,
        analysis_run_id="analysis-1",
        source_scopes={"event-run": "window-a", "change-run": "window-a"},
    )

    normalized_event_id = result.events[0].proposal.proposal_id
    normalized_change = result.state_changes[0].proposal
    assert normalized_event_id != "evt-1"
    assert normalized_change.event is not None
    assert normalized_change.event.event_proposal_id == normalized_event_id


def test_semantic_dedup_still_merges_provenance_after_normalization() -> None:
    sources = [
        _source("run-a", _event("evt-1", "Same event", "chunk-a")),
        _source("run-b", _event("evt-9", "Same event", "chunk-a")),
    ]

    result = aggregate_narrative_analysis(
        sources,
        analysis_run_id="analysis-1",
        source_scopes={"run-a": "window-a", "run-b": "window-b"},
    )

    assert len(result.events) == 1
    assert result.events[0].agent_run_ids == ["run-a", "run-b"]
