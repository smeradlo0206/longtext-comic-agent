"""Production StoryBible Curator execution, audit checkpoint, and safe recovery."""

from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError

from comic_agent.agents.storybible_curator import StoryBibleCurator
from comic_agent.config import Settings
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.storybible_production_run_repository import (
    StoryBibleProductionRunRepository,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    StoryBibleCuratorProposalV1,
    StoryBibleProductionFailureStage,
    StoryBibleProductionRunStatus,
    StoryBibleProductionRunV1,
)
from comic_agent.schemas.workflow import (
    AgentInputRefV1,
    AgentOutputRefV1,
    AgentRunStatus,
    AgentRunV1,
    ProviderResultV1,
    ProviderType,
)
from comic_agent.services.id_service import stable_id
from comic_agent.services.narrative_analyst_summary import sanitize_error_message
from comic_agent.services.storybible_curator_input_adapter import (
    StoryBibleContextBudgetExceededError,
    StoryBibleCuratorInputAdapter,
)
from comic_agent.services.storybible_production_context import PreparedStoryBibleProduction
from comic_agent.services.storybible_production_output_normalizer import (
    StoryBibleProductionOutputNormalizer,
)


class StoryBibleProductionBuilder(Protocol):
    """Trusted preparation boundary used by the coordinator."""

    def build_and_reserve(
        self,
        *,
        project_id: str,
        gate2_approved_bundle_id: str,
        approved_timeline_bundle_id: str,
        model_identity: str,
    ) -> PreparedStoryBibleProduction: ...


class StoryBibleProductionExecutionError(RuntimeError):
    """Explicit safe production failure or recovery outcome."""

    def __init__(self, stage: StoryBibleProductionFailureStage, message: str) -> None:
        super().__init__(message)
        self.stage = stage


class StoryBibleProductionRecoveryRequiredError(StoryBibleProductionExecutionError):
    """A RUNNING execution has no terminal checkpoint and cannot be rerun safely."""


class StoryBibleProductionCoordinator:
    """Allow exactly one Curator call and durably checkpoint its trusted result."""

    def __init__(
        self,
        *,
        input_builder: StoryBibleProductionBuilder,
        run_repository: StoryBibleProductionRunRepository,
        curator: StoryBibleCurator,
        output_normalizer: StoryBibleProductionOutputNormalizer,
        agent_run_repository: AgentRunRepository,
        settings: Settings,
        provider_name: str | None = None,
        input_adapter: StoryBibleCuratorInputAdapter | None = None,
    ) -> None:
        self._builder = input_builder
        self._runs = run_repository
        self._curator = curator
        self._normalizer = output_normalizer
        self._agent_runs = agent_run_repository
        self._settings = settings
        self._provider_name = provider_name or settings.llm_provider_name
        self._adapter = input_adapter or StoryBibleCuratorInputAdapter()

    def run(
        self,
        *,
        project_id: str,
        gate2_approved_bundle_id: str,
        approved_timeline_bundle_id: str,
        model_identity: str,
        real_llm_requested: bool,
    ) -> StoryBibleProductionRunV1:
        """Execute or safely resume one canonical production input."""

        if not real_llm_requested:
            raise StoryBibleProductionExecutionError(
                StoryBibleProductionFailureStage.INPUT_ADAPTATION,
                "real StoryBible LLM execution was not explicitly requested",
            )
        if not self._settings.enable_real_llm:
            raise StoryBibleProductionExecutionError(
                StoryBibleProductionFailureStage.INPUT_ADAPTATION,
                "real StoryBible LLM execution is disabled by server configuration",
            )
        try:
            prepared = self._builder.build_and_reserve(
                project_id=project_id,
                gate2_approved_bundle_id=gate2_approved_bundle_id,
                approved_timeline_bundle_id=approved_timeline_bundle_id,
                model_identity=model_identity,
            )
            self._validate_prepared(prepared, model_identity=model_identity)
        except (ValueError, ValidationError) as exc:
            raise StoryBibleProductionExecutionError(
                StoryBibleProductionFailureStage.INPUT_ADAPTATION,
                self._sanitize(exc, []),
            ) from exc

        run = prepared.run
        if run.status == StoryBibleProductionRunStatus.SUCCEEDED:
            return run
        if run.status == StoryBibleProductionRunStatus.FAILED:
            return run
        if run.status == StoryBibleProductionRunStatus.RUNNING:
            return self._resume_running(run)
        try:
            curator_input = self._adapter.adapt(
                prepared.context,
                max_context_chunks=self._curator.spec.max_context_chunks,
            )
        except StoryBibleContextBudgetExceededError as exc:
            raise StoryBibleProductionExecutionError(
                StoryBibleProductionFailureStage.CONTEXT_BUDGET, str(exc)
            ) from exc
        except (ValueError, ValidationError) as exc:
            raise StoryBibleProductionExecutionError(
                StoryBibleProductionFailureStage.INPUT_ADAPTATION,
                self._sanitize(exc, prepared.context.source_chunks),
            ) from exc
        if not self._runs.claim_execution(run.run_id):
            persisted = self._require_run(run.run_id)
            if persisted.status == StoryBibleProductionRunStatus.RUNNING:
                return self._resume_running(persisted)
            return persisted

        running = self._require_run(run.run_id)
        started_at = running.updated_at
        try:
            raw = self._curator.run(curator_input.context, curator_input.chunk_texts)
        except Exception as exc:
            stage = (
                StoryBibleProductionFailureStage.SCHEMA
                if isinstance(exc, ValidationError)
                else StoryBibleProductionFailureStage.PROVIDER
            )
            return self._record_failure(
                running, stage, exc, started_at, prepared.context.source_chunks
            )
        try:
            normalized = self._normalizer.normalize(
                raw, context=prepared.context, run=running
            )
        except Exception as exc:
            return self._record_failure(
                running,
                StoryBibleProductionFailureStage.NORMALIZATION,
                exc,
                started_at,
                prepared.context.source_chunks,
            )

        agent_run = self._success_agent_run(
            running, normalized, started_at, prepared.context.source_chunks
        )
        try:
            self._agent_runs.save_agent_run(agent_run)
        except Exception as exc:
            message = self._sanitize(exc, prepared.context.source_chunks)
            try:
                self._runs.save_failure(
                    running.run_id,
                    error_message=message,
                    failure_stage=StoryBibleProductionFailureStage.AGENT_RUN_PERSISTENCE,
                )
            except Exception:
                pass
            raise StoryBibleProductionExecutionError(
                StoryBibleProductionFailureStage.AGENT_RUN_PERSISTENCE, message
            ) from exc
        try:
            return self._runs.save_success(
                running.run_id,
                curator_proposal=normalized,
                agent_run_id=agent_run.agent_run_id,
            )
        except Exception as exc:
            raise StoryBibleProductionExecutionError(
                StoryBibleProductionFailureStage.RUN_CHECKPOINT_PERSISTENCE,
                self._sanitize(exc, prepared.context.source_chunks),
            ) from exc

    def _resume_running(self, run: StoryBibleProductionRunV1) -> StoryBibleProductionRunV1:
        agent_run_id = self._agent_run_id(run.run_id)
        checkpoint = self._agent_runs.get_agent_run(agent_run_id)
        if checkpoint is None:
            raise StoryBibleProductionRecoveryRequiredError(
                StoryBibleProductionFailureStage.RUN_CHECKPOINT_PERSISTENCE,
                "RECOVERY_REQUIRED: RUNNING StoryBible run has no terminal AgentRun",
            )
        self._validate_checkpoint(run, checkpoint)
        if checkpoint.status == AgentRunStatus.SUCCEEDED:
            proposal = StoryBibleCuratorProposalV1.model_validate(
                checkpoint.payload.get("normalized_curator_proposal")
            )
            return self._runs.save_success(
                run.run_id, curator_proposal=proposal, agent_run_id=agent_run_id
            )
        if checkpoint.status == AgentRunStatus.FAILED:
            stage = StoryBibleProductionFailureStage(
                checkpoint.payload.get("failure_stage", "PROVIDER")
            )
            return self._runs.save_failure(
                run.run_id,
                error_message=checkpoint.error_message or "StoryBible execution failed",
                failure_stage=stage,
                agent_run_id=agent_run_id,
            )
        raise StoryBibleProductionRecoveryRequiredError(
            StoryBibleProductionFailureStage.RUN_CHECKPOINT_PERSISTENCE,
            "RECOVERY_REQUIRED: StoryBible AgentRun is not terminal",
        )

    def _record_failure(
        self,
        run: StoryBibleProductionRunV1,
        stage: StoryBibleProductionFailureStage,
        exc: Exception,
        started_at: datetime,
        source_chunks: list[SourceChunkV1],
    ) -> StoryBibleProductionRunV1:
        message = self._sanitize(exc, source_chunks)
        agent_run = self._failed_agent_run(
            run, stage, message, started_at, source_chunks
        )
        agent_run_id: str | None = None
        try:
            self._agent_runs.save_agent_run(agent_run)
            agent_run_id = agent_run.agent_run_id
        except Exception as persistence_exc:
            message = self._sanitize(persistence_exc, source_chunks)
            stage = StoryBibleProductionFailureStage.AGENT_RUN_PERSISTENCE
        return self._runs.save_failure(
            run.run_id,
            error_message=message,
            failure_stage=stage,
            agent_run_id=agent_run_id,
        )

    def _success_agent_run(
        self,
        run: StoryBibleProductionRunV1,
        proposal: StoryBibleCuratorProposalV1,
        started_at: datetime,
        source_chunks: list[SourceChunkV1],
    ) -> AgentRunV1:
        now = datetime.now(UTC)
        metadata_getter = getattr(self._curator, "last_execution_metadata", None)
        execution_metadata = metadata_getter() if callable(metadata_getter) else None
        provider_result = ProviderResultV1(
            provider_result_id=stable_id("storybible-provider-result", run.run_id),
            provider_name=self._provider_name,
            provider_type=ProviderType.LLM,
            model_name=run.model_identity,
            output_schema="StoryBibleCuratorProposalV1",
            structured_output=proposal.model_dump(mode="json"),
            success=True,
            execution_metadata=execution_metadata,
            created_at=now,
        )
        return AgentRunV1(
            agent_run_id=self._agent_run_id(run.run_id),
            project_id=run.project_id,
            agent_name="storybible-curator",
            input_chunk_ids=[chunk.chunk_id for chunk in source_chunks],
            output_proposal_ids=[proposal.proposal_id],
            output_schema="StoryBibleCuratorProposalV1",
            provider_result_id=provider_result.provider_result_id,
            provider_result=provider_result,
            input_refs=self._input_refs(run),
            output_refs=[
                AgentOutputRefV1(
                    object_id=proposal.proposal_id,
                    object_schema="StoryBibleCuratorProposalV1",
                    role="normalized_proposal_checkpoint",
                )
            ],
            status=AgentRunStatus.SUCCEEDED,
            started_at=started_at,
            completed_at=now,
            payload=self._checkpoint_payload(run)
            | {"normalized_curator_proposal": proposal.model_dump(mode="json")},
        )

    def _failed_agent_run(
        self,
        run: StoryBibleProductionRunV1,
        stage: StoryBibleProductionFailureStage,
        message: str,
        started_at: datetime,
        source_chunks: list[SourceChunkV1],
    ) -> AgentRunV1:
        return AgentRunV1(
            agent_run_id=self._agent_run_id(run.run_id),
            project_id=run.project_id,
            agent_name="storybible-curator",
            input_chunk_ids=[chunk.chunk_id for chunk in source_chunks],
            output_schema="StoryBibleCuratorProposalV1",
            input_refs=self._input_refs(run),
            status=AgentRunStatus.FAILED,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            error_message=message,
            payload=self._checkpoint_payload(run) | {"failure_stage": str(stage)},
        )

    @staticmethod
    def _agent_run_id(run_id: str) -> str:
        return stable_id("storybible-agent-run", run_id)

    @staticmethod
    def _input_refs(run: StoryBibleProductionRunV1) -> list[AgentInputRefV1]:
        return [
            AgentInputRefV1(
                object_id=run.run_id,
                object_schema="StoryBibleProductionRunV1",
                role="production_run",
            ),
            AgentInputRefV1(
                object_id=run.gate2_approved_bundle_id,
                object_schema="ApprovedProposalBundleV1",
                role="approved_narrative",
            ),
            AgentInputRefV1(
                object_id=run.approved_timeline_bundle_id,
                object_schema="ApprovedTimelineBundleV1",
                role="approved_timeline",
            ),
        ]

    def _checkpoint_payload(self, run: StoryBibleProductionRunV1) -> dict[str, object]:
        return {
            "storybible_run_id": run.run_id,
            "input_hash": run.input_hash,
            "model_identity": run.model_identity,
            "provider_name": self._provider_name,
            "output_schema": "StoryBibleCuratorProposalV1",
        }

    @staticmethod
    def _validate_prepared(
        prepared: PreparedStoryBibleProduction, *, model_identity: str
    ) -> None:
        run = prepared.run
        context = prepared.context
        value = prepared.production_input
        if (
            run.project_id != context.project_id
            or run.project_id != value.project_id
            or run.gate2_approved_bundle_id != context.gate2_approved_bundle_id
            or run.approved_timeline_bundle_id != context.approved_timeline_bundle_id
            or run.canonical_storybible_snapshot_hash
            != context.canonical_storybible_snapshot_hash
            or run.canonical_storybible_snapshot_hash
            != value.canonical_storybible_snapshot_hash
            or run.model_identity != model_identity
        ):
            raise ValueError("stale or mismatched StoryBible production context")

    @staticmethod
    def _validate_checkpoint(run: StoryBibleProductionRunV1, checkpoint: AgentRunV1) -> None:
        payload = checkpoint.payload
        if (
            checkpoint.project_id != run.project_id
            or payload.get("storybible_run_id") != run.run_id
            or payload.get("input_hash") != run.input_hash
            or checkpoint.output_schema != "StoryBibleCuratorProposalV1"
        ):
            raise StoryBibleProductionRecoveryRequiredError(
                StoryBibleProductionFailureStage.RUN_CHECKPOINT_PERSISTENCE,
                "RECOVERY_REQUIRED: StoryBible AgentRun linkage is invalid",
            )

    def _require_run(self, run_id: str) -> StoryBibleProductionRunV1:
        run = self._runs.get_run(run_id)
        if run is None:
            raise RuntimeError("StoryBible production reservation disappeared")
        return run

    def _sanitize(self, exc: Exception, chunks: list[SourceChunkV1]) -> str:
        message = sanitize_error_message(
            str(exc) or type(exc).__name__,
            settings=self._settings,
            selected_chunks=chunks,
        )
        return " ".join(message.splitlines())[:1000] or type(exc).__name__
