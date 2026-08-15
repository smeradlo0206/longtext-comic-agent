from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from comic_agent.database.base import Base
from comic_agent.providers.mocks import MockLLMProvider, MockMode
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.base import RealityLayer
from comic_agent.schemas.workflow import AgentRunStatus
from comic_agent.services.document_parser import DocumentParser
from comic_agent.workflows.mock_event_workflow import MockEventWorkflow


def _repositories(tmp_path: Path) -> tuple[SourceRepository, AgentRunRepository]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = session_factory()
    return SourceRepository(session), AgentRunRepository(session)


def _import_demo_source(repository: SourceRepository):
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="source.txt",
        text="第一章 开端\n\n陈野把伞递给林夏。\n\n林夏站在操场边。",
    )
    repository.import_parsed_document(parsed)
    return parsed


def _provider_response(chunk_id: str, quote_text: str = "伞递给") -> dict[str, object]:
    return {
        "proposal_id": "proposal-1",
        "event_type": "handoff",
        "summary": "陈野把伞递给林夏。",
        "participant_ids": ["char-chen", "char-lin"],
        "actor_resolution_status": "KNOWN",
        "location_id": None,
        "evidence_refs": [{"chunk_id": chunk_id, "quote_text": quote_text}],
        "confidence": 0.9,
        "reality_layer": RealityLayer.PRIMARY,
    }


def test_mock_event_workflow_saves_successful_agent_run(tmp_path: Path) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    workflow = MockEventWorkflow(
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=MockLLMProvider(response=_provider_response(parsed.chunks[0].chunk_id)),
    )

    result = workflow.run(project_id="project-1", chunk_ids=[parsed.chunks[0].chunk_id])

    assert result.proposal is not None
    assert result.agent_run.status == AgentRunStatus.SUCCEEDED
    assert result.agent_run.input_chunk_ids == [parsed.chunks[0].chunk_id]
    assert result.agent_run.output_proposal_ids == [result.proposal.proposal_id]
    assert result.agent_run.payload["evidence_validation_passed"] is True
    assert agent_run_repository.get_agent_run(result.agent_run.agent_run_id) == result.agent_run


def test_mock_event_workflow_records_failed_run_for_bad_evidence(tmp_path: Path) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    workflow = MockEventWorkflow(
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=MockLLMProvider(
            response=_provider_response(parsed.chunks[0].chunk_id, quote_text="不存在")
        ),
    )

    result = workflow.run(project_id="project-1", chunk_ids=[parsed.chunks[0].chunk_id])

    assert result.proposal is not None
    assert result.agent_run.status == AgentRunStatus.FAILED
    assert result.agent_run.error_message is not None
    assert result.agent_run.payload["evidence_validation_passed"] is False
    assert "Evidence quote_text not found" in result.agent_run.error_message
    assert agent_run_repository.count_agent_runs() == 1


def test_mock_event_workflow_records_failed_run_for_provider_schema_error(
    tmp_path: Path,
) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    workflow = MockEventWorkflow(
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=MockLLMProvider(mode=MockMode.SCHEMA_ERROR, response={"proposal_id": "bad"}),
    )

    result = workflow.run(project_id="project-1", chunk_ids=[parsed.chunks[0].chunk_id])

    assert result.proposal is None
    assert result.agent_run.status == AgentRunStatus.FAILED
    assert result.agent_run.error_message == "mock schema error"
    assert result.agent_run.payload["provider_result"]["success"] is False


def test_mock_event_workflow_records_failed_run_for_provider_timeout(tmp_path: Path) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    workflow = MockEventWorkflow(
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=MockLLMProvider(mode=MockMode.TIMEOUT),
    )

    result = workflow.run(project_id="project-1", chunk_ids=[parsed.chunks[0].chunk_id])

    assert result.proposal is None
    assert result.agent_run.status == AgentRunStatus.FAILED
    assert result.agent_run.error_message == "mock provider timeout"
    assert result.agent_run.payload["provider_result"]["success"] is False


def test_mock_event_workflow_repeated_run_is_idempotent(tmp_path: Path) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    workflow = MockEventWorkflow(
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=MockLLMProvider(response=_provider_response(parsed.chunks[0].chunk_id)),
    )

    first = workflow.run(project_id="project-1", chunk_ids=[parsed.chunks[0].chunk_id])
    second = workflow.run(project_id="project-1", chunk_ids=[parsed.chunks[0].chunk_id])

    assert first.agent_run.agent_run_id == second.agent_run.agent_run_id
    assert second.agent_run.status == AgentRunStatus.SUCCEEDED
    assert agent_run_repository.count_agent_runs() == 1
    assert second.agent_run.payload["input_context"]["source_chunk_ids"] == [
        parsed.chunks[0].chunk_id
    ]
