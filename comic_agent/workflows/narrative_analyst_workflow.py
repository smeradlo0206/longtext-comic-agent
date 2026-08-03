"""Unified NarrativeAnalyst workflow for internal console evaluation."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel

from comic_agent.agents.narrative_analyst import NarrativeAnalyst
from comic_agent.config import Settings
from comic_agent.providers.llm import LLMProvider
from comic_agent.providers.openai_compatible import OpenAICompatibleLLMProvider
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.workflow import AgentRunStatus, AgentRunV1, ProviderResultV1, ProviderType
from comic_agent.services.context_builder import AgentContext, ContextBuilder
from comic_agent.services.id_service import checksum_text, stable_id
from comic_agent.services.narrative_analyst_summary import (
    DEFAULT_MAX_CHARS_PER_CHUNK,
    add_proposal_details,
    add_provider_diagnostics,
    base_eval_summary,
    classify_evidence_result,
    classify_exception,
    manual_review_checklist,
    sanitize_error_message,
    selected_chunk_metadata,
    set_failure,
    slim_input_context,
    visible_context_chunks,
)

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)

DETERMINISTIC_NARRATIVE_ANALYST_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class NarrativeAnalystWorkflowResult:
    """Result returned by the internal NarrativeAnalyst console workflow."""

    summary: dict[str, Any]
    proposal: BaseModel | None
    agent_run: AgentRunV1 | None

    def response_payload(self) -> dict[str, Any]:
        """Return an API payload without raw provider response fields."""

        return {
            **self.summary,
            "proposal": self.proposal.model_dump(mode="json") if self.proposal else None,
            "manual_review_checklist": manual_review_checklist(str(self.summary["mode"])),
        }


class NarrativeAnalystWorkflow:
    """Run implemented NarrativeAnalyst modes for the internal console."""

    def __init__(
        self,
        *,
        settings: Settings,
        source_repository: SourceRepository,
        agent_run_repository: AgentRunRepository,
        provider: LLMProvider | None = None,
    ) -> None:
        self._settings = settings
        self._source_repository = source_repository
        self._agent_run_repository = agent_run_repository
        self._provider = provider

    def run(
        self,
        *,
        project_id: str,
        mode: str,
        chunk_ids: list[str] | None = None,
        chunk_limit: int = 3,
        chunk_offset: int = 0,
        max_chars_per_chunk: int = DEFAULT_MAX_CHARS_PER_CHUNK,
        real_llm_requested: bool = False,
    ) -> NarrativeAnalystWorkflowResult:
        """Run or dry-run a NarrativeAnalyst mode over selected chunks."""

        self._validate_budget(
            chunk_limit=chunk_limit,
            chunk_offset=chunk_offset,
            max_chars_per_chunk=max_chars_per_chunk,
        )
        mode_spec = NarrativeAnalyst(_NoopProvider()).get_mode_spec(mode)
        if mode_spec.status != "implemented":
            raise NotImplementedError(
                f"NarrativeAnalyst mode is not implemented: {mode} "
                f"(status={mode_spec.status})"
            )
        if mode_spec.output_schema is None:
            raise NotImplementedError(
                f"NarrativeAnalyst mode is not implemented: {mode} "
                f"(status={mode_spec.status})"
            )

        selected_chunks = self._select_chunks(
            project_id=project_id,
            chunk_ids=chunk_ids,
            chunk_limit=chunk_limit,
            chunk_offset=chunk_offset,
        )
        context = self._build_context(
            project_id=project_id,
            chunk_ids=chunk_ids,
            selected_chunks=selected_chunks,
            chunk_limit=chunk_limit,
        )
        visible_chunks = visible_context_chunks(context.chunks, max_chars_per_chunk)

        summary = base_eval_summary(
            project_id=project_id,
            mode=mode,
            real_llm_requested=real_llm_requested,
            real_llm_enabled=self._settings.enable_real_llm,
            provider_name=self._settings.llm_provider_name,
            model=self._settings.llm_model,
            chunk_limit=chunk_limit,
            chunk_offset=chunk_offset,
            max_chars_per_chunk=max_chars_per_chunk,
            selected_chunks=selected_chunks,
            output_schema=mode_spec.output_schema,
            import_idempotent=None,
        )
        summary["context_chunk_ids"] = context.source_chunk_ids
        chapter_titles = {
            chapter.chapter_id: chapter.title
            for chapter in self._source_repository.list_chapters(project_id)
        }
        summary["selected_chunk_metadata"] = selected_chunk_metadata(
            selected_chunks,
            chapter_titles=chapter_titles,
        )

        if not real_llm_requested:
            return NarrativeAnalystWorkflowResult(
                summary=summary,
                proposal=None,
                agent_run=None,
            )

        input_context = slim_input_context(context, visible_chunks)
        if not self._settings.enable_real_llm:
            disabled_error_message = "ENABLE_REAL_LLM is false; provider was not called"
            disabled_provider_result = self._provider_result(
                success=False,
                output_schema=mode_spec.output_schema,
                error_message=disabled_error_message,
            )
            agent_run = self._agent_run(
                project_id=project_id,
                mode=mode,
                output_schema=mode_spec.output_schema,
                chunk_ids=context.source_chunk_ids,
                input_context=input_context,
                provider_result=disabled_provider_result,
                proposal=None,
                status=AgentRunStatus.FAILED,
                evidence_validation_passed=False,
                error_message=disabled_error_message,
                provider_error_diagnostics=None,
                max_chars_per_chunk=max_chars_per_chunk,
            )
            saved = self._agent_run_repository.save_agent_run(agent_run)
            self._mark_saved_failure(
                summary,
                saved,
                disabled_provider_result,
                disabled_error_message,
            )
            return NarrativeAnalystWorkflowResult(summary=summary, proposal=None, agent_run=saved)

        proposal: BaseModel | None = None
        provider_result: ProviderResultV1
        error_message: str | None = None
        provider_error_diagnostics: dict[str, object] | None = None
        status = AgentRunStatus.SUCCEEDED

        try:
            provider = self._provider or self._build_provider()
            summary["real_llm_called"] = True
            proposal = NarrativeAnalyst(provider).run(mode, input_context)
            provider_result = self._provider_result(
                success=True,
                output_schema=mode_spec.output_schema,
                proposal=proposal,
            )
            summary["provider_success"] = True
            summary["schema_validation_passed"] = True
            add_proposal_details(
                summary=summary,
                proposal=proposal,
                selected_chunks=visible_chunks,
            )
            classify_evidence_result(summary)
        except (TimeoutError, ValueError, NotImplementedError) as exc:
            error_message = sanitize_error_message(
                str(exc),
                settings=self._settings,
                selected_chunks=selected_chunks,
            )
            add_provider_diagnostics(summary, exc)
            set_failure(summary, classify_exception(exc))
            provider_error_diagnostics = summary["provider_error_diagnostics"]
            status = AgentRunStatus.FAILED
            provider_result = self._provider_result(
                success=False,
                output_schema=mode_spec.output_schema,
                error_message=error_message,
            )
            summary["provider_success"] = False
            summary["schema_validation_passed"] = False
            summary["evidence_validation_passed"] = False
            summary["error_message"] = error_message
        except Exception as exc:
            error_message = sanitize_error_message(
                str(exc),
                settings=self._settings,
                selected_chunks=selected_chunks,
            )
            set_failure(summary, "UNKNOWN_ERROR")
            status = AgentRunStatus.FAILED
            provider_result = self._provider_result(
                success=False,
                output_schema=mode_spec.output_schema,
                error_message=error_message,
            )
            summary["provider_success"] = False
            summary["schema_validation_passed"] = False
            summary["evidence_validation_passed"] = False
            summary["error_message"] = error_message

        agent_run = self._agent_run(
            project_id=project_id,
            mode=mode,
            output_schema=mode_spec.output_schema,
            chunk_ids=context.source_chunk_ids,
            input_context=input_context,
            provider_result=provider_result,
            proposal=proposal,
            status=status,
            evidence_validation_passed=summary["evidence_validation_passed"] is True,
            error_message=error_message,
            provider_error_diagnostics=provider_error_diagnostics,
            max_chars_per_chunk=max_chars_per_chunk,
        )
        saved = self._agent_run_repository.save_agent_run(agent_run)
        self._mark_saved(summary, saved, provider_result, status)
        return NarrativeAnalystWorkflowResult(summary=summary, proposal=proposal, agent_run=saved)

    def _validate_budget(
        self,
        *,
        chunk_limit: int,
        chunk_offset: int,
        max_chars_per_chunk: int,
    ) -> None:
        if chunk_limit < 1:
            raise ValueError("chunk_limit must be at least 1")
        if chunk_limit > 3:
            raise ValueError("chunk_limit cannot exceed 3")
        if chunk_offset < 0:
            raise ValueError("chunk_offset must be non-negative")
        if max_chars_per_chunk < 1:
            raise ValueError("max_chars_per_chunk must be at least 1")

    def _select_chunks(
        self,
        *,
        project_id: str,
        chunk_ids: list[str] | None,
        chunk_limit: int,
        chunk_offset: int,
    ) -> list[SourceChunkV1]:
        if chunk_ids:
            if len(chunk_ids) > 3:
                raise ValueError("chunk_ids cannot exceed 3")
            return self._project_chunks(project_id, chunk_ids)

        chunks = self._source_repository.list_project_chunks(project_id)
        selected_chunks = chunks[chunk_offset : chunk_offset + chunk_limit]
        if not selected_chunks:
            raise ValueError("No SourceChunk records selected for project")
        return selected_chunks

    def _build_context(
        self,
        *,
        project_id: str,
        chunk_ids: list[str] | None,
        selected_chunks: list[SourceChunkV1],
        chunk_limit: int,
    ) -> AgentContext:
        builder = ContextBuilder(self._source_repository, max_chunks=chunk_limit)
        if chunk_ids:
            return builder.build_from_chunk_ids(project_id, chunk_ids)
        return builder.from_chunks(project_id, selected_chunks)

    def _project_chunks(
        self,
        project_id: str,
        chunk_ids: list[str],
    ) -> list[SourceChunkV1]:
        chunks = []
        for chunk_id in chunk_ids:
            chunk = self._source_repository.get_chunk(chunk_id)
            if chunk is None or chunk.project_id != project_id:
                raise ValueError("SourceChunk not found for project")
            chunks.append(chunk)
        return chunks

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

    def _provider_result(
        self,
        *,
        success: bool,
        output_schema: str,
        proposal: BaseModel | None = None,
        error_message: str | None = None,
    ) -> ProviderResultV1:
        structured_output = proposal.model_dump(mode="json") if proposal is not None else None
        seed = self._stable_json(
            {
                "provider_name": self._settings.llm_provider_name,
                "model": self._settings.llm_model,
                "output_schema": output_schema,
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
            output_schema=output_schema,
            structured_output=structured_output,
            success=success,
            error_message=error_message,
            created_at=DETERMINISTIC_NARRATIVE_ANALYST_TIME,
        )

    def _agent_run(
        self,
        *,
        project_id: str,
        mode: str,
        output_schema: str,
        chunk_ids: list[str],
        input_context: dict[str, object],
        provider_result: ProviderResultV1,
        proposal: BaseModel | None,
        status: AgentRunStatus,
        evidence_validation_passed: bool,
        error_message: str | None,
        provider_error_diagnostics: dict[str, object] | None,
        max_chars_per_chunk: int,
    ) -> AgentRunV1:
        proposal_id = getattr(proposal, "proposal_id", None) if proposal is not None else None
        output_proposal_ids = [str(proposal_id)] if proposal_id is not None else []
        payload = {
            "input_context": {
                "project_id": project_id,
                "mode": mode,
                "source_chunk_ids": chunk_ids,
                "chunks_count": len(chunk_ids),
                "max_chars_per_chunk": max_chars_per_chunk,
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
            mode,
            ",".join(chunk_ids),
            self._settings.llm_model,
            checksum_text(self._stable_json(payload)),
        )
        return AgentRunV1(
            agent_run_id=agent_run_id,
            project_id=project_id,
            agent_name=f"narrative-analyst:{mode}",
            input_chunk_ids=chunk_ids,
            output_proposal_ids=output_proposal_ids,
            output_schema=output_schema,
            provider_result_id=provider_result.provider_result_id,
            provider_result=provider_result,
            status=status,
            started_at=DETERMINISTIC_NARRATIVE_ANALYST_TIME,
            completed_at=DETERMINISTIC_NARRATIVE_ANALYST_TIME,
            error_message=error_message,
            payload=payload,
        )

    def _mark_saved_failure(
        self,
        summary: dict[str, Any],
        agent_run: AgentRunV1,
        provider_result: ProviderResultV1,
        error_message: str,
    ) -> None:
        summary["agent_run_saved"] = True
        summary["agent_run_id"] = agent_run.agent_run_id
        summary["agent_run_status"] = str(agent_run.status)
        summary["provider_result_id"] = provider_result.provider_result_id
        summary["provider_success"] = False
        summary["schema_validation_passed"] = False
        summary["evidence_validation_passed"] = False
        summary["error_message"] = error_message

    def _mark_saved(
        self,
        summary: dict[str, Any],
        agent_run: AgentRunV1,
        provider_result: ProviderResultV1,
        status: AgentRunStatus,
    ) -> None:
        summary["agent_run_saved"] = True
        summary["agent_run_id"] = agent_run.agent_run_id
        summary["agent_run_status"] = str(status)
        summary["provider_result_id"] = provider_result.provider_result_id

    def _stable_json(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class _NoopProvider:
    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        raise RuntimeError("No provider call is available during mode validation")
