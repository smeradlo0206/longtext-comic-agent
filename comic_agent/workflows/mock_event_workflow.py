"""Phase-one mock event extraction workflow."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from comic_agent.agents.mocks import MockEventAgent
from comic_agent.providers.mocks import MockLLMProvider
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.workflow import AgentRunStatus, AgentRunV1, ProviderResultV1, ProviderType
from comic_agent.services.commit_service import CommitService
from comic_agent.services.context_builder import AgentContext, ContextBuilder
from comic_agent.services.id_service import checksum_text, stable_id

DETERMINISTIC_AUDIT_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class MockEventWorkflowResult:
    """Result of one mock event workflow execution."""

    agent_run: AgentRunV1
    proposal: EventProposalV1 | None


class MockEventWorkflow:
    """Run SourceChunk -> MockEventAgent -> EvidenceRef validation -> AgentRun."""

    def __init__(
        self,
        source_repository: SourceRepository,
        agent_run_repository: AgentRunRepository,
        provider: MockLLMProvider,
        agent_id: str = "mock_event_agent",
    ) -> None:
        self._source_repository = source_repository
        self._agent_run_repository = agent_run_repository
        self._provider = provider
        self._agent_id = agent_id

    def run(
        self,
        project_id: str,
        chunk_ids: list[str],
        agent_id: str | None = None,
    ) -> MockEventWorkflowResult:
        """Execute one deterministic mock event extraction run."""

        effective_agent_id = agent_id or self._agent_id
        context = ContextBuilder(self._source_repository).build_from_chunk_ids(
            project_id=project_id,
            chunk_ids=chunk_ids,
        )
        input_context = self._input_context_payload(context)
        agent = MockEventAgent()

        proposal: EventProposalV1 | None = None
        provider_result: ProviderResultV1
        evidence_validation_passed = False
        error_message: str | None = None

        try:
            if not context.chunks:
                raise ValueError("Mock event workflow requires at least one source chunk")
            proposal = agent.run(context.chunks[0])
            provider_result = self._provider_result(
                project_id=project_id,
                chunk_ids=chunk_ids,
                agent_id=effective_agent_id,
                success=True,
                structured_output=proposal.model_dump(mode="json"),
            )
            CommitService(self._source_repository).validate_story_proposal_evidence(proposal)
            evidence_validation_passed = True
            status = AgentRunStatus.SUCCEEDED
        except (TimeoutError, ValueError) as exc:
            error_message = str(exc)
            provider_result = self._provider_result(
                project_id=project_id,
                chunk_ids=chunk_ids,
                agent_id=effective_agent_id,
                success=False,
                error_message=error_message,
            )
            status = AgentRunStatus.FAILED

        agent_run = self._agent_run(
            project_id=project_id,
            chunk_ids=chunk_ids,
            agent_id=effective_agent_id,
            provider_result=provider_result,
            proposal=proposal,
            status=status,
            input_context=input_context,
            evidence_validation_passed=evidence_validation_passed,
            error_message=error_message,
        )
        saved = self._agent_run_repository.save_agent_run(agent_run)
        return MockEventWorkflowResult(agent_run=saved, proposal=proposal)

    def _input_context_payload(self, context: AgentContext) -> dict[str, object]:
        return {
            "project_id": context.project_id,
            "source_chunk_ids": context.source_chunk_ids,
            "source_chunks": [chunk.model_dump(mode="json") for chunk in context.chunks],
        }

    def _provider_result(
        self,
        project_id: str,
        chunk_ids: list[str],
        agent_id: str,
        success: bool,
        structured_output: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> ProviderResultV1:
        result_seed = self._stable_json(
            {
                "project_id": project_id,
                "chunk_ids": chunk_ids,
                "agent_id": agent_id,
                "success": success,
                "structured_output": structured_output,
                "error_message": error_message,
            }
        )
        return ProviderResultV1(
            provider_result_id=stable_id("provider-result", result_seed),
            provider_name="mock-llm",
            provider_type=ProviderType.MOCK,
            output_schema="EventProposalV1",
            structured_output=structured_output,
            success=success,
            error_message=error_message,
            created_at=DETERMINISTIC_AUDIT_TIME,
        )

    def _agent_run(
        self,
        project_id: str,
        chunk_ids: list[str],
        agent_id: str,
        provider_result: ProviderResultV1,
        proposal: EventProposalV1 | None,
        status: AgentRunStatus,
        input_context: dict[str, object],
        evidence_validation_passed: bool,
        error_message: str | None,
    ) -> AgentRunV1:
        output_proposal_ids = [proposal.proposal_id] if proposal is not None else []
        payload = {
            "input_context": {
                "project_id": project_id,
                "source_chunk_ids": chunk_ids,
                "chunks_count": len(chunk_ids),
            },
            "provider_result": provider_result.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json") if proposal is not None else None,
            "evidence_validation_passed": evidence_validation_passed,
            "error_message": error_message,
        }
        agent_run_id = stable_id(
            "agent-run",
            project_id,
            ",".join(chunk_ids),
            agent_id,
            checksum_text(self._stable_json(payload)),
        )
        return AgentRunV1(
            agent_run_id=agent_run_id,
            project_id=project_id,
            agent_name=agent_id,
            input_chunk_ids=chunk_ids,
            output_proposal_ids=output_proposal_ids,
            output_schema="EventProposalV1",
            provider_result_id=provider_result.provider_result_id,
            provider_result=provider_result,
            status=status,
            started_at=DETERMINISTIC_AUDIT_TIME,
            completed_at=DETERMINISTIC_AUDIT_TIME,
            error_message=error_message,
            payload=payload,
        )

    def _stable_json(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
