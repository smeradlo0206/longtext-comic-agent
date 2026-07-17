import pytest

from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.services.commit_service import CommitService
from comic_agent.services.document_parser import DocumentParser


def test_evidence_ref_can_locate_source_chunk(temp_repository) -> None:  # type: ignore[no-untyped-def]
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text="第一章 开端\n\n陈野把伞递给林夏。",
    )
    temp_repository.import_parsed_document(parsed)
    chunk = parsed.chunks[0]

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
