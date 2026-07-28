from comic_agent.agents.mocks import MockEventAgent
from comic_agent.services.commit_service import CommitService
from comic_agent.services.document_parser import DocumentParser


def test_mock_event_agent_returns_traceable_proposal(temp_repository) -> None:  # type: ignore[no-untyped-def]
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="demo.txt",
        text="Chapter 1\n\nExact source text.",
    )
    temp_repository.import_parsed_document(parsed)
    chunk = parsed.chunks[0]

    proposal = MockEventAgent().run(chunk)

    assert proposal.event_type == "MOCK_EVENT"
    assert proposal.evidence_refs[0].chunk_id == chunk.chunk_id
    assert proposal.evidence_refs[0].quote_text == chunk.text
    CommitService(temp_repository).validate_story_proposal_evidence(proposal)
