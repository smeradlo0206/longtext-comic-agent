"""Real LLM event extraction workflow, disabled by default."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from comic_agent.agents.event_extraction import EventExtractionAgent
from comic_agent.config import Settings
from comic_agent.providers.llm import LLMProvider
from comic_agent.providers.openai_compatible import OpenAICompatibleLLMProvider
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.workflow import AgentRunStatus, AgentRunV1, ProviderResultV1, ProviderType
from comic_agent.services.commit_service import CommitService
from comic_agent.services.context_builder import AgentContext, ContextBuilder
from comic_agent.services.id_service import checksum_text, stable_id

DETERMINISTIC_REAL_AUDIT_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class RealEventWorkflowResult:
    """Result of one real event workflow attempt."""

    agent_run: AgentRunV1
    proposal: EventProposalV1 | None


class RealEventWorkflow:
    """Run a real-LLM EventProposal workflow only when explicitly enabled."""

    def __init__(
        self,
        settings: Settings,
        source_repository: SourceRepository,
        agent_run_repository: AgentRunRepository,
        provider: LLMProvider | None = None,
        agent_id: str = "event-extraction-agent",
    ) -> None:
        self._settings = settings
        self._source_repository = source_repository
        self._agent_run_repository = agent_run_repository
        self._provider = provider
        self._agent_id = agent_id

    def run(self, project_id: str, chunk_ids: list[str]) -> RealEventWorkflowResult:
        """Execute the workflow and always persist an AgentRunV1 audit record."""

        context = ContextBuilder(
            self._source_repository,
            max_chunks=EventExtractionAgent.spec.max_context_chunks,
        ).build_from_chunk_ids(project_id, chunk_ids)
        input_context = self._input_context_payload(context)

        if not self._settings.enable_real_llm:
            agent_run = self._failed_agent_run(
                project_id=project_id,
                chunk_ids=chunk_ids,
                input_context=input_context,
                error_message="Real LLM is disabled; set ENABLE_REAL_LLM=true to run",
            )
            saved = self._agent_run_repository.save_agent_run(agent_run)
            return RealEventWorkflowResult(agent_run=saved, proposal=None)

        proposal: EventProposalV1 | None = None
        provider_result: ProviderResultV1
        evidence_validation_passed = False
        error_message: str | None = None
        provider_error_diagnostics: dict[str, object] | None = None
        status = AgentRunStatus.SUCCEEDED

        try:
            provider = self._provider or self._build_provider()
            proposal = EventExtractionAgent(provider).run(input_context)
            provider_result = self._provider_result(success=True, proposal=proposal)
            CommitService(self._source_repository).validate_story_proposal_evidence(proposal)
            evidence_validation_passed = True
        except (TimeoutError, ValueError) as exc:
            error_message = str(exc)
            provider_error_diagnostics = self._provider_error_diagnostics(exc)
            status = AgentRunStatus.FAILED
            provider_result = (
                self._provider_result(success=True, proposal=proposal)
                if proposal is not None
                else self._provider_result(success=False, error_message=error_message)
            )

        agent_run = self._agent_run(
            project_id=project_id,
            chunk_ids=chunk_ids,
            input_context=input_context,
            provider_result=provider_result,
            proposal=proposal,
            status=status,
            evidence_validation_passed=evidence_validation_passed,
            error_message=error_message,
            provider_error_diagnostics=provider_error_diagnostics,
        )
        saved = self._agent_run_repository.save_agent_run(agent_run)
        return RealEventWorkflowResult(agent_run=saved, proposal=proposal)

    def _build_provider(self) -> OpenAICompatibleLLMProvider:
        api_key = (
            self._settings.llm_api_key.get_secret_value()
            if self._settings.llm_api_key is not None
            else None
        )
        return OpenAICompatibleLLMProvider(
            api_key=api_key,
            base_url=self._settings.llm_base_url,
            model=self._settings.llm_model,
            response_format=self._settings.llm_response_format,
            timeout_seconds=self._settings.llm_timeout_seconds,
            max_output_tokens=self._settings.llm_max_output_tokens,
        )

    def _input_context_payload(self, context: AgentContext) -> dict[str, object]:
        return {
            "project_id": context.project_id,
            "source_chunk_ids": context.source_chunk_ids,
            "source_chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "chapter_id": chunk.chapter_id,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "text": chunk.text,
                }
                for chunk in context.chunks
            ],
        }

    def _provider_result(
        self,
        success: bool,
        proposal: EventProposalV1 | None = None,
        error_message: str | None = None,
    ) -> ProviderResultV1:
        structured_output = proposal.model_dump(mode="json") if proposal is not None else None
        seed = self._stable_json(
            {
                "provider_name": self._settings.llm_provider_name,
                "model": self._settings.llm_model,
                "success": success,
                "structured_output": structured_output,
                "error_message": error_message,
            }
        )
        return ProviderResultV1(
            provider_result_id=stable_id("provider-result", seed),
            provider_name=self._settings.llm_provider_name,
            provider_type=ProviderType.LLM,
            model_name=self._settings.llm_model,
            output_schema="EventProposalV1",
            structured_output=structured_output,
            success=success,
            error_message=error_message,
            created_at=DETERMINISTIC_REAL_AUDIT_TIME,
        )

    def _failed_agent_run(
        self,
        project_id: str,
        chunk_ids: list[str],
        input_context: dict[str, object],
        error_message: str,
    ) -> AgentRunV1:
        return self._agent_run(
            project_id=project_id,
            chunk_ids=chunk_ids,
            input_context=input_context,
            provider_result=self._provider_result(success=False, error_message=error_message),
            proposal=None,
            status=AgentRunStatus.FAILED,
            evidence_validation_passed=False,
            error_message=error_message,
            provider_error_diagnostics=None,
        )

    def _agent_run(
        self,
        project_id: str,
        chunk_ids: list[str],
        input_context: dict[str, object],
        provider_result: ProviderResultV1,
        proposal: EventProposalV1 | None,
        status: AgentRunStatus,
        evidence_validation_passed: bool,
        error_message: str | None,
        provider_error_diagnostics: dict[str, object] | None,
    ) -> AgentRunV1:
        output_proposal_ids = [proposal.proposal_id] if proposal is not None else []
        payload = {
            "input_context": {
                "project_id": project_id,
                "source_chunk_ids": chunk_ids,
                "chunks_count": len(chunk_ids),
            },
            "provider": {
                "provider_name": self._settings.llm_provider_name,
                "model": self._settings.llm_model,
                "real_llm_enabled": self._settings.enable_real_llm,
            },
            "provider_result": provider_result.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json") if proposal is not None else None,
            "evidence_validation_passed": evidence_validation_passed,
            "error_message": error_message,
        }
        if provider_error_diagnostics is not None:
            payload["provider_error_diagnostics"] = provider_error_diagnostics
        agent_run_id = stable_id(
            "agent-run",
            project_id,
            ",".join(chunk_ids),
            self._agent_id,
            self._settings.llm_model,
            checksum_text(self._stable_json(payload)),
        )
        return AgentRunV1(
            agent_run_id=agent_run_id,
            project_id=project_id,
            agent_name=self._agent_id,
            input_chunk_ids=chunk_ids,
            output_proposal_ids=output_proposal_ids,
            output_schema="EventProposalV1",
            provider_result_id=provider_result.provider_result_id,
            provider_result=provider_result,
            status=status,
            started_at=DETERMINISTIC_REAL_AUDIT_TIME,
            completed_at=DETERMINISTIC_REAL_AUDIT_TIME,
            error_message=error_message,
            payload=payload,
        )

    def _stable_json(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _provider_error_diagnostics(self, exc: BaseException) -> dict[str, object] | None:
        diagnostics = getattr(exc, "diagnostics", None)
        return diagnostics if isinstance(diagnostics, dict) else None
