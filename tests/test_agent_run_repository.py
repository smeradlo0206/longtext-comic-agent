from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from comic_agent.database.base import Base
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.schemas.workflow import AgentRunStatus, AgentRunV1, ProviderResultV1, ProviderType


def _repository(tmp_path: Path) -> AgentRunRepository:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'agent_runs.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = session_factory()
    return AgentRunRepository(session)


def _agent_run() -> AgentRunV1:
    provider_result = ProviderResultV1(
        provider_result_id="provider-result-1",
        provider_name="mock-llm",
        provider_type=ProviderType.MOCK,
        output_schema="EventProposalV1",
        structured_output={"proposal_id": "proposal-1"},
        success=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return AgentRunV1(
        agent_run_id="agent-run-1",
        project_id="project-1",
        agent_name="mock_event_agent",
        input_chunk_ids=["chunk-1"],
        output_proposal_ids=["proposal-1"],
        output_schema="EventProposalV1",
        provider_result_id=provider_result.provider_result_id,
        provider_result=provider_result,
        status=AgentRunStatus.SUCCEEDED,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        payload={"input_context": {"source_chunk_ids": ["chunk-1"]}},
    )


def test_agent_run_repository_saves_and_reads_agent_run(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    agent_run = _agent_run()

    saved = repository.save_agent_run(agent_run)
    loaded = repository.get_agent_run(agent_run.agent_run_id)

    assert saved == agent_run
    assert loaded == agent_run
    assert loaded is not None
    assert loaded.provider_result is not None
    assert loaded.provider_result.structured_output == {"proposal_id": "proposal-1"}


def test_agent_run_repository_repeated_save_is_idempotent(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    agent_run = _agent_run()

    first = repository.save_agent_run(agent_run)
    second = repository.save_agent_run(agent_run)

    assert first == second
    assert repository.count_agent_runs() == 1


def test_agent_run_repository_rejects_same_id_different_payload(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.save_agent_run(_agent_run())

    with pytest.raises(ValueError, match="AgentRun conflict"):
        repository.save_agent_run(_agent_run().model_copy(update={"payload": {"changed": True}}))


def test_agent_run_repository_missing_run_returns_none(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    assert repository.get_agent_run("missing-agent-run") is None
