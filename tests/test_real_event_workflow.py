import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from comic_agent.config import Settings
from comic_agent.database.base import Base
from comic_agent.providers.openai_compatible import ProviderResponseError
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.workflow import AgentRunStatus, ProviderType
from comic_agent.services.document_parser import DocumentParser
from comic_agent.workflows.real_event_workflow import RealEventWorkflow

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class FakeProvider:
    def __init__(
        self,
        quote_text: str = "伞递给",
        exc: Exception | None = None,
    ) -> None:
        self.quote_text = quote_text
        self.exc = exc
        self.calls = 0
        self.requests: list[dict[str, object]] = []

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        self.calls += 1
        self.requests.append(request)
        if self.exc is not None:
            raise self.exc
        chunk_id = str(request["input_context"]["source_chunk_ids"][0])  # type: ignore[index]
        return output_model.model_validate(
            {
                "batch_id": "event-batch-1",
                "events": [
                    {
                        "proposal_id": "proposal-1",
                        "event_type": "handoff",
                        "summary": "陈野把伞递给林夏。",
                        "participant_ids": ["char-chen", "char-lin"],
                        "actor_resolution_status": "KNOWN",
                        "location_id": None,
                        "evidence_refs": [{"chunk_id": chunk_id, "quote_text": self.quote_text}],
                        "confidence": 0.9,
                        "reality_layer": "PRIMARY",
                    }
                ],
            }
        )


def _repositories(tmp_path: Path) -> tuple[SourceRepository, AgentRunRepository]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'real_workflow.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = session_factory()
    return SourceRepository(session), AgentRunRepository(session)


def _import_demo_source(repository: SourceRepository):
    parsed = DocumentParser().parse_txt(
        project_id="project-1",
        filename="source.txt",
        text="第一章 开端\n\n陈野把伞递给林夏。",
    )
    repository.import_parsed_document(parsed)
    return parsed


def _settings(enable_real_llm: bool) -> Settings:
    return Settings(
        _env_file=None,
        enable_real_llm=enable_real_llm,
        llm_api_key="secret-test-key",
        llm_model="deepseek-v4-pro",
    )


def test_real_event_workflow_disabled_saves_failed_run_without_calling_provider(
    tmp_path: Path,
) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    provider = FakeProvider()
    workflow = RealEventWorkflow(
        settings=_settings(enable_real_llm=False),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=provider,
    )

    result = workflow.run("project-1", [parsed.chunks[0].chunk_id])

    assert provider.calls == 0
    assert result.agent_run.status == AgentRunStatus.FAILED
    assert result.agent_run.provider_result is not None
    assert result.agent_run.provider_result.provider_type == ProviderType.LLM
    assert "disabled" in str(result.agent_run.error_message)
    assert agent_run_repository.get_agent_run(result.agent_run.agent_run_id) == result.agent_run


def test_real_event_workflow_success_saves_succeeded_agent_run(tmp_path: Path) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    workflow = RealEventWorkflow(
        settings=_settings(enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=FakeProvider(),
    )

    result = workflow.run("project-1", [parsed.chunks[0].chunk_id])

    assert result.agent_run.status == AgentRunStatus.SUCCEEDED
    assert result.agent_run.provider_result is not None
    assert result.agent_run.provider_result.provider_name == "ustc-openai-compatible"
    assert result.agent_run.provider_result.provider_type == ProviderType.LLM
    assert result.agent_run.provider_result.structured_output is not None
    assert result.agent_run.payload["evidence_validation_passed"] is True


def test_real_event_workflow_sends_slim_source_chunks_to_provider(tmp_path: Path) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    provider = FakeProvider()
    workflow = RealEventWorkflow(
        settings=_settings(enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=provider,
    )

    workflow.run("project-1", [parsed.chunks[0].chunk_id])

    input_context = provider.requests[0]["input_context"]
    assert isinstance(input_context, dict)
    source_chunks = input_context["source_chunks"]
    assert isinstance(source_chunks, list)
    assert len(source_chunks) == 1
    slim_chunk = source_chunks[0]
    assert isinstance(slim_chunk, dict)
    assert set(slim_chunk) == {"chunk_id", "chapter_id", "char_start", "char_end", "text"}
    assert slim_chunk["chunk_id"] == parsed.chunks[0].chunk_id
    assert "document_id" not in slim_chunk
    assert "checksum" not in slim_chunk
    assert "storage_uri" not in slim_chunk
    assert "created_at" not in slim_chunk
    assert "updated_at" not in slim_chunk


def test_real_event_workflow_provider_error_saves_failed_agent_run(tmp_path: Path) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    workflow = RealEventWorkflow(
        settings=_settings(enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=FakeProvider(exc=ValueError("mock schema error")),
    )

    result = workflow.run("project-1", [parsed.chunks[0].chunk_id])

    assert result.agent_run.status == AgentRunStatus.FAILED
    assert result.agent_run.error_message == "mock schema error"
    assert result.agent_run.provider_result is not None
    assert result.agent_run.provider_result.success is False


def test_real_event_workflow_provider_error_saves_sanitized_diagnostics(tmp_path: Path) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    diagnostics = {
        "finish_reason": "stop",
        "response_has_choices": True,
        "choices_count": 1,
        "message_keys": ["content"],
        "content_type": "NoneType",
        "has_reasoning_content": False,
        "has_tool_calls": False,
    }
    workflow = RealEventWorkflow(
        settings=_settings(enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=FakeProvider(
            exc=ProviderResponseError(
                "LLM provider response content is missing",
                diagnostics=diagnostics,
            )
        ),
    )

    result = workflow.run("project-1", [parsed.chunks[0].chunk_id])

    assert result.agent_run.status == AgentRunStatus.FAILED
    assert result.agent_run.error_message == "LLM provider response content is missing"
    assert result.agent_run.payload["provider_error_diagnostics"] == diagnostics
    serialized = json.dumps(result.agent_run.model_dump(mode="json"), ensure_ascii=False)
    assert "secret-test-key" not in serialized


def test_real_event_workflow_timeout_saves_failed_agent_run(tmp_path: Path) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    workflow = RealEventWorkflow(
        settings=_settings(enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=FakeProvider(exc=TimeoutError("provider timeout")),
    )

    result = workflow.run("project-1", [parsed.chunks[0].chunk_id])

    assert result.agent_run.status == AgentRunStatus.FAILED
    assert result.agent_run.error_message == "provider timeout"


def test_real_event_workflow_bad_evidence_saves_failed_agent_run(tmp_path: Path) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    workflow = RealEventWorkflow(
        settings=_settings(enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=FakeProvider(quote_text="不存在"),
    )

    result = workflow.run("project-1", [parsed.chunks[0].chunk_id])

    assert result.agent_run.status == AgentRunStatus.FAILED
    assert result.agent_run.payload["evidence_validation_passed"] is False
    assert "Evidence quote_text not found" in str(result.agent_run.error_message)


def test_real_event_workflow_payload_does_not_contain_api_key(tmp_path: Path) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    workflow = RealEventWorkflow(
        settings=_settings(enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=FakeProvider(),
    )

    result = workflow.run("project-1", [parsed.chunks[0].chunk_id])
    serialized = json.dumps(result.agent_run.model_dump(mode="json"), ensure_ascii=False)

    assert "secret-test-key" not in serialized


def test_real_event_workflow_repeated_run_is_idempotent(tmp_path: Path) -> None:
    source_repository, agent_run_repository = _repositories(tmp_path)
    parsed = _import_demo_source(source_repository)
    workflow = RealEventWorkflow(
        settings=_settings(enable_real_llm=True),
        source_repository=source_repository,
        agent_run_repository=agent_run_repository,
        provider=FakeProvider(),
    )

    first = workflow.run("project-1", [parsed.chunks[0].chunk_id])
    second = workflow.run("project-1", [parsed.chunks[0].chunk_id])

    assert first.agent_run.agent_run_id == second.agent_run.agent_run_id
    assert agent_run_repository.count_agent_runs() == 1
