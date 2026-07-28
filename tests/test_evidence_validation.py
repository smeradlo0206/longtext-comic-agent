import pytest

from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.services.commit_service import CommitService
from comic_agent.services.document_parser import DocumentParser


def _import_demo_document(temp_repository):  # type: ignore[no-untyped-def]
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text="第一章 开端\n\n陈野把伞递给林夏。",
    )
    temp_repository.import_parsed_document(parsed)
    return parsed.chunks[0]


def _event_with_evidence(evidence_ref: EvidenceRefV1) -> EventProposalV1:
    return EventProposalV1(
        proposal_id="proposal-1",
        event_type="handoff",
        summary="Chen Ye gives Lin Xia an umbrella.",
        participant_ids=["char-chen", "char-lin"],
        location_id=None,
        evidence_refs=[evidence_ref],
        confidence=0.9,
        reality_layer=RealityLayer.PRIMARY,
    )


def test_evidence_ref_can_locate_source_chunk(temp_repository) -> None:  # type: ignore[no-untyped-def]
    chunk = _import_demo_document(temp_repository)
    event = EventProposalV1(
        proposal_id="proposal-1",
        event_type="handoff",
        summary="Chen Ye gives Lin Xia an umbrella.",
        participant_ids=["char-chen", "char-lin"],
        location_id=None,
        evidence_refs=[EvidenceRefV1(chunk_id=chunk.chunk_id, quote_text="伞")],
        confidence=0.9,
        reality_layer=RealityLayer.PRIMARY,
    )

    located = temp_repository.get_chunk(chunk.chunk_id)
    assert located is not None
    assert located.chunk_id == event.evidence_refs[0].chunk_id


def test_commit_service_accepts_chunk_only_evidence(temp_repository) -> None:  # type: ignore[no-untyped-def]
    chunk = _import_demo_document(temp_repository)
    event = _event_with_evidence(EvidenceRefV1(chunk_id=chunk.chunk_id))

    CommitService(temp_repository).validate_story_proposal_evidence(event)


def test_commit_service_accepts_quote_text_found_in_chunk(temp_repository) -> None:  # type: ignore[no-untyped-def]
    chunk = _import_demo_document(temp_repository)
    event = _event_with_evidence(EvidenceRefV1(chunk_id=chunk.chunk_id, quote_text="伞递给"))

    CommitService(temp_repository).validate_story_proposal_evidence(event)


def test_commit_service_rejects_quote_text_missing_from_chunk(temp_repository) -> None:  # type: ignore[no-untyped-def]
    chunk = _import_demo_document(temp_repository)
    event = _event_with_evidence(EvidenceRefV1(chunk_id=chunk.chunk_id, quote_text="不存在"))

    with pytest.raises(ValueError, match="Evidence quote_text not found in source chunk"):
        CommitService(temp_repository).validate_story_proposal_evidence(event)


def test_commit_service_accepts_quote_range_inside_chunk(temp_repository) -> None:  # type: ignore[no-untyped-def]
    chunk = _import_demo_document(temp_repository)
    event = _event_with_evidence(EvidenceRefV1(chunk_id=chunk.chunk_id, quote_start=0, quote_end=2))

    CommitService(temp_repository).validate_story_proposal_evidence(event)


def test_commit_service_rejects_quote_range_out_of_bounds(temp_repository) -> None:  # type: ignore[no-untyped-def]
    chunk = _import_demo_document(temp_repository)
    event = _event_with_evidence(
        EvidenceRefV1(chunk_id=chunk.chunk_id, quote_start=0, quote_end=len(chunk.text) + 1)
    )

    with pytest.raises(ValueError, match="Evidence quote range out of bounds"):
        CommitService(temp_repository).validate_story_proposal_evidence(event)


def test_commit_service_accepts_matching_quote_range_and_text(temp_repository) -> None:  # type: ignore[no-untyped-def]
    chunk = _import_demo_document(temp_repository)
    start = chunk.text.index("伞")
    end = start + len("伞递给")
    event = _event_with_evidence(
        EvidenceRefV1(
            chunk_id=chunk.chunk_id,
            quote_start=start,
            quote_end=end,
            quote_text="伞递给",
        )
    )

    CommitService(temp_repository).validate_story_proposal_evidence(event)


def test_commit_service_rejects_quote_range_that_does_not_match_text(temp_repository) -> None:  # type: ignore[no-untyped-def]
    chunk = _import_demo_document(temp_repository)
    event = _event_with_evidence(
        EvidenceRefV1(chunk_id=chunk.chunk_id, quote_start=0, quote_end=2, quote_text="伞递给")
    )

    with pytest.raises(ValueError, match="Evidence quote range does not match quote_text"):
        CommitService(temp_repository).validate_story_proposal_evidence(event)


def test_commit_service_rejects_missing_evidence(temp_repository) -> None:  # type: ignore[no-untyped-def]
    event = EventProposalV1(
        proposal_id="proposal-1",
        event_type="handoff",
        summary="Chen Ye gives Lin Xia an umbrella.",
        participant_ids=["char-chen", "char-lin"],
        location_id=None,
        evidence_refs=[EvidenceRefV1(chunk_id="missing")],
        confidence=0.9,
        reality_layer=RealityLayer.PRIMARY,
    )

    with pytest.raises(ValueError, match="EvidenceRef"):
        CommitService(temp_repository).validate_story_proposal_evidence(event)
