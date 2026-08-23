"""Idempotent Gate 2 APPROVED -> Timeline -> fresh Gate 3 orchestration."""

import re
from datetime import UTC, datetime
from typing import Protocol, cast

from comic_agent.providers.openai_compatible import (
    ProviderHttpError,
    ProviderNetworkError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.reliability import ProviderFailureCategory
from comic_agent.schemas.review import (
    NarrativeAnalysisReviewRouteV1,
    NarrativeExecutionBundleV1,
    ReviewGate2RoutingDecision,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import (
    ReviewGate3Decision,
    TimelineAnalysisInputV1,
    TimelineAnalysisMode,
    TimelineAnalysisProposalV1,
    TimelineGate3RunStatus,
    TimelineGate3RunV1,
    TimelineProviderDiagnosticsV1,
    TimelineReviewMaterialProvenanceV1,
    TimelineReviewMaterialV1,
)
from comic_agent.schemas.workflow import AgentRunStatus, AgentRunV1
from comic_agent.services.id_service import stable_id
from comic_agent.services.narrative_timeline_input_adapter import NarrativeTimelineInputAdapter
from comic_agent.services.review_gate3_service import ReviewGate3Service


class TimelineRunner(Protocol):
    """The existing Timeline Agent interface, represented without a provider bypass."""

    def run(
        self,
        input_context: TimelineAnalysisInputV1,
        *,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineAnalysisProposalV1:
        """Return one candidate Timeline proposal."""


_TERMINAL = {
    TimelineGate3RunStatus.APPROVED,
    TimelineGate3RunStatus.REJECTED,
    TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW,
    TimelineGate3RunStatus.FAILED,
}


class NarrativeTimelineCoordinator:
    """Persist checkpoints before/after the sole permitted Timeline Provider call."""

    def __init__(
        self,
        *,
        repository: TimelineGate3Repository,
        timeline_runner: TimelineRunner,
        agent_run_repository: AgentRunRepository,
        input_adapter: NarrativeTimelineInputAdapter | None = None,
        review_service: ReviewGate3Service | None = None,
        timeline_mode: TimelineAnalysisMode = TimelineAnalysisMode.RULES_ONLY,
    ) -> None:
        self._repository = repository
        self._timeline_runner = timeline_runner
        self._agent_runs = agent_run_repository
        self._adapter = input_adapter or NarrativeTimelineInputAdapter()
        self._review_service = review_service or ReviewGate3Service()
        self._timeline_mode = timeline_mode

    def run_if_approved(
        self,
        *,
        route: NarrativeAnalysisReviewRouteV1,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineGate3RunV1 | None:
        """Start only from a fresh Gate 2 APPROVED bundle, never an aggregate."""

        if route.narrative_execution_bundle is not None:
            return self.run_if_execution_ready(route=route, source_chunks=source_chunks)
        if route.decision != ReviewGate2RoutingDecision.APPROVED:
            return None
        bundle = route.approved_proposal_bundle
        if bundle is None:
            return None
        key = stable_id("timeline-gate3-key", bundle.project_id, bundle.bundle_id)
        reserved = self._repository.reserve_run(
            TimelineGate3RunV1(
                timeline_run_id=stable_id("timeline-gate3-run", key),
                project_id=bundle.project_id,
                source_approved_proposal_bundle_id=bundle.bundle_id,
                source_gate2_review_id=bundle.review_run_id,
                source_gate2_route_id=route.analysis_run_id,
                idempotency_key=key,
                status=TimelineGate3RunStatus.RESERVED,
            )
        )
        if reserved.status in _TERMINAL or reserved.status == TimelineGate3RunStatus.RUNNING:
            return reserved
        if reserved.status in {
            TimelineGate3RunStatus.PROVIDER_SUCCEEDED,
            TimelineGate3RunStatus.REVIEWING,
        }:
            return self._review(reserved)

        timeline_input = self._adapter.build_from_approved_bundle(
            route=route,
            source_chunks=source_chunks,
            mode=self._timeline_mode,
        )
        claimed = self._repository.claim_provider(
            reserved,
            timeline_input,
        )
        if not claimed:
            return self._repository.get_run(reserved.timeline_run_id) or reserved
        running = self._repository.get_run(reserved.timeline_run_id)
        if running is None:
            raise RuntimeError("Timeline Gate 3 reservation disappeared")
        try:
            proposal = self._timeline_runner.run(timeline_input, source_chunks=source_chunks)
        except (RuntimeError, TimeoutError, ValueError) as exc:
            failure_category, safe_issue_codes = _safe_failure_diagnostics(exc)
            failed = running.model_copy(
                update={
                    "status": TimelineGate3RunStatus.FAILED,
                    "failure_category": failure_category,
                    "safe_issue_codes": safe_issue_codes,
                    "provider_request_count": (
                        running.provider_request_count
                        + _provider_request_count(self._timeline_runner)
                    ),
                    "provider_diagnostics": _safe_provider_diagnostics(exc),
                    "updated_at": datetime.now(UTC),
                }
            )
            return self._repository.save_transition(failed)

        agent_run_id = stable_id("timeline-agent-run", running.timeline_run_id)
        self._agent_runs.save_agent_run(
            AgentRunV1(
                agent_run_id=agent_run_id,
                project_id=running.project_id,
                agent_name="timeline-agent",
                input_chunk_ids=self._chunk_ids(timeline_input),
                output_proposal_ids=[proposal.proposal_id],
                output_schema="TimelineAnalysisProposalV1",
                status=AgentRunStatus.SUCCEEDED,
                payload={"timeline_run_id": running.timeline_run_id},
            )
        )
        succeeded = self._repository.save_transition(
            running.model_copy(
                update={
                    "status": TimelineGate3RunStatus.PROVIDER_SUCCEEDED,
                    "timeline_proposal": proposal,
                    "timeline_agent_run_id": agent_run_id,
                    "provider_request_count": (
                        running.provider_request_count
                        + _provider_request_count(self._timeline_runner)
                    ),
                    "updated_at": datetime.now(UTC),
                }
            )
        )
        return self._review(succeeded)

    def run_if_execution_ready(
        self,
        *,
        route: NarrativeAnalysisReviewRouteV1,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineGate3RunV1 | None:
        """Run Timeline from Gate 2 execution material regardless of audit decision."""

        execution = route.narrative_execution_bundle
        if execution is None or not self._adapter.has_timeline_candidates(execution):
            return None
        try:
            timeline_input = self._adapter.build_from_execution_bundle(
                route=route,
                source_chunks=source_chunks,
                mode=self._timeline_mode,
            )
        except ValueError:
            # A candidate whose evidence cannot be located is never a Timeline fact.
            return None
        return self._run_execution_bundle(
            route=route,
            execution=execution,
            timeline_input=timeline_input,
            source_chunks=source_chunks,
        )

    def _run_execution_bundle(
        self,
        *,
        route: NarrativeAnalysisReviewRouteV1,
        execution: NarrativeExecutionBundleV1,
        timeline_input: TimelineAnalysisInputV1,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineGate3RunV1 | None:
        gate2_review_id = route.review_run_id
        if not isinstance(gate2_review_id, str) or not gate2_review_id:
            return None
        approved_bundle_id = (
            route.approved_proposal_bundle.bundle_id
            if route.approved_proposal_bundle is not None
            else None
        )
        # A recovered all-green Gate 2 route is a distinct audited handoff from
        # an earlier execution-only route, even when Gate 2's deterministic
        # review ID is reused.  Keep the approved-bundle key for the former so
        # legacy status/recovery lookups remain stable; execution-only routes
        # use their execution-bundle identity.
        timeline_source_id = approved_bundle_id or execution.bundle_id
        key = stable_id("timeline-gate3-key", execution.project_id, timeline_source_id)
        reserved = self._repository.reserve_run(
            TimelineGate3RunV1(
                schema_version="1.3",
                timeline_run_id=stable_id("timeline-gate3-run", key),
                project_id=execution.project_id,
                source_approved_proposal_bundle_id=approved_bundle_id,
                source_narrative_execution_bundle_id=execution.bundle_id,
                source_gate2_review_id=gate2_review_id,
                source_gate2_route_id=route.analysis_run_id,
                idempotency_key=key,
                status=TimelineGate3RunStatus.RESERVED,
            )
        )
        if reserved.status in _TERMINAL or reserved.status == TimelineGate3RunStatus.RUNNING:
            return reserved
        if reserved.status in {
            TimelineGate3RunStatus.PROVIDER_SUCCEEDED,
            TimelineGate3RunStatus.REVIEWING,
        }:
            return self._review(reserved)
        claimed = self._repository.claim_provider(reserved, timeline_input)
        if not claimed:
            return self._repository.get_run(reserved.timeline_run_id) or reserved
        running = self._repository.get_run(reserved.timeline_run_id)
        if running is None:
            raise RuntimeError("Timeline execution reservation disappeared")
        try:
            proposal = self._timeline_runner.run(timeline_input, source_chunks=source_chunks)
        except (RuntimeError, TimeoutError, ValueError) as exc:
            failure_category, safe_issue_codes = _safe_failure_diagnostics(exc)
            return self._repository.save_transition(
                running.model_copy(
                    update={
                        "status": TimelineGate3RunStatus.FAILED,
                        "failure_category": failure_category,
                        "safe_issue_codes": safe_issue_codes,
                        "provider_request_count": (
                            running.provider_request_count
                            + _provider_request_count(self._timeline_runner)
                        ),
                        "provider_diagnostics": _safe_provider_diagnostics(exc),
                        "updated_at": datetime.now(UTC),
                    }
                )
            )
        agent_run_id = stable_id("timeline-agent-run", running.timeline_run_id)
        self._agent_runs.save_agent_run(
            AgentRunV1(
                agent_run_id=agent_run_id,
                project_id=running.project_id,
                agent_name="timeline-agent",
                input_chunk_ids=self._chunk_ids(timeline_input),
                output_proposal_ids=[proposal.proposal_id],
                output_schema="TimelineAnalysisProposalV1",
                status=AgentRunStatus.SUCCEEDED,
                payload={"timeline_run_id": running.timeline_run_id},
            )
        )
        succeeded = self._repository.save_transition(
            running.model_copy(
                update={
                    "status": TimelineGate3RunStatus.PROVIDER_SUCCEEDED,
                    "timeline_proposal": proposal,
                    "timeline_agent_run_id": agent_run_id,
                    "timeline_review_material": None,
                    "provider_request_count": (
                        running.provider_request_count
                        + _provider_request_count(self._timeline_runner)
                    ),
                    "updated_at": datetime.now(UTC),
                }
            )
        )
        return self._review(succeeded)

    def resume(self, timeline_run_id: str) -> TimelineGate3RunV1 | None:
        """Resume only post-Provider review checkpoints; never repeat the Provider."""

        run = self._repository.get_run(timeline_run_id)
        if run is None or run.status in _TERMINAL:
            return run
        if run.status in {
            TimelineGate3RunStatus.PROVIDER_SUCCEEDED,
            TimelineGate3RunStatus.REVIEWING,
        }:
            return self._review(run)
        return run

    def recover(
        self,
        *,
        timeline_run_id: str,
        source_chunks: list[SourceChunkV1],
    ) -> TimelineGate3RunV1 | None:
        """Make one bounded rerun for explicit, recoverable Gate 3 structural issues."""

        run = self._repository.get_run(timeline_run_id)
        if (
            run is None
            or run.status != TimelineGate3RunStatus.REJECTED
            or run.timeline_input is None
            or run.gate3_result is None
            or run.recovery_budget.attempts_used >= run.recovery_budget.max_attempts
            or not run.gate3_result.issues
            or not all(issue.recoverable for issue in run.gate3_result.issues)
        ):
            return run
        if not self._repository.claim_recovery(run):
            return self._repository.get_run(timeline_run_id) or run
        recovering = self._repository.get_run(timeline_run_id)
        if recovering is None or recovering.timeline_input is None:
            raise RuntimeError("Timeline recovery checkpoint disappeared")
        try:
            proposal = self._timeline_runner.run(
                recovering.timeline_input,
                source_chunks=source_chunks,
            )
        except (RuntimeError, TimeoutError, ValueError) as exc:
            failure_category, safe_issue_codes = _safe_failure_diagnostics(exc)
            failed = recovering.model_copy(
                update={
                    "status": TimelineGate3RunStatus.FAILED,
                    "failure_category": failure_category,
                    "safe_issue_codes": safe_issue_codes,
                    "updated_at": datetime.now(UTC),
                }
            )
            return self._repository.save_transition(failed)
        attempt_number = recovering.recovery_budget.attempts_used
        agent_run_id = stable_id(
            "timeline-agent-recovery-run",
            recovering.timeline_run_id,
            str(attempt_number),
        )
        self._agent_runs.save_agent_run(
            AgentRunV1(
                agent_run_id=agent_run_id,
                project_id=recovering.project_id,
                agent_name="timeline-agent",
                input_chunk_ids=self._chunk_ids(recovering.timeline_input),
                output_proposal_ids=[proposal.proposal_id],
                output_schema="TimelineAnalysisProposalV1",
                status=AgentRunStatus.SUCCEEDED,
                payload={
                    "timeline_run_id": recovering.timeline_run_id,
                    "recovery_attempt": attempt_number,
                },
            )
        )
        succeeded = self._repository.save_transition(
            recovering.model_copy(
                update={
                    "status": TimelineGate3RunStatus.PROVIDER_SUCCEEDED,
                    "timeline_proposal": proposal,
                    "timeline_agent_run_id": agent_run_id,
                    "timeline_review_material": None,
                    "provider_request_count": recovering.provider_request_count + 1,
                    "updated_at": datetime.now(UTC),
                }
            )
        )
        return self._review(succeeded)

    def _review(self, run: TimelineGate3RunV1) -> TimelineGate3RunV1:
        if (
            run.timeline_input is None
            or run.timeline_proposal is None
            or run.timeline_agent_run_id is None
        ):
            return run
        if not self._repository.claim_review(run):
            return self._repository.get_run(run.timeline_run_id) or run
        reviewer_agent_run_id = stable_id("gate3-agent-run", run.timeline_agent_run_id)
        self._agent_runs.save_agent_run(
            AgentRunV1(
                agent_run_id=reviewer_agent_run_id,
                project_id=run.project_id,
                agent_name="review-gate-3",
                input_chunk_ids=self._chunk_ids(run.timeline_input),
                output_proposal_ids=[run.timeline_proposal.proposal_id],
                output_schema="ReviewGate3ResultV1",
                status=AgentRunStatus.SUCCEEDED,
                payload={"timeline_run_id": run.timeline_run_id},
            )
        )
        try:
            result, route = self._review_service.review(
                project_id=run.project_id,
                source_approved_proposal_bundle_id=run.source_approved_proposal_bundle_id,
                source_narrative_execution_bundle_id=run.source_narrative_execution_bundle_id,
                timeline_run_id=run.timeline_run_id,
                reviewer_agent_run_id=reviewer_agent_run_id,
                event_ids=[item.proposal_id for item in run.timeline_input.event_proposals],
                temporal_relations=run.timeline_proposal.temporal_relations,
                evidence_refs=run.timeline_proposal.evidence_refs,
                source_gate2_review_id=run.source_gate2_review_id,
                source_gate2_route_id=run.source_gate2_route_id,
            )
        except (RuntimeError, TimeoutError, ValueError):
            result, route = self._review_service.failed(
                project_id=run.project_id,
                source_approved_proposal_bundle_id=run.source_approved_proposal_bundle_id,
                source_narrative_execution_bundle_id=run.source_narrative_execution_bundle_id,
                timeline_run_id=run.timeline_run_id,
                reviewer_agent_run_id=reviewer_agent_run_id,
            )
        status = {
            ReviewGate3Decision.APPROVED: TimelineGate3RunStatus.APPROVED,
            ReviewGate3Decision.REJECTED: TimelineGate3RunStatus.REJECTED,
            ReviewGate3Decision.NEEDS_HUMAN_REVIEW: TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW,
            ReviewGate3Decision.FAILED: TimelineGate3RunStatus.FAILED,
        }[route.route]
        reviewing = self._repository.get_run(run.timeline_run_id)
        if reviewing is None:
            raise RuntimeError("Timeline Gate 3 review checkpoint disappeared")
        material = TimelineReviewMaterialV1(
            material_id=stable_id(
                "timeline-review-material", run.timeline_run_id, result.review_id
            ),
            project_id=run.project_id,
            narrative_execution_bundle_id=(
                run.source_narrative_execution_bundle_id
                or stable_id(
                    "legacy-approved-bundle-execution",
                    run.source_approved_proposal_bundle_id,
                )
            ),
            timeline_run_id=run.timeline_run_id,
            timeline_candidate=run.timeline_proposal,
            temporal_relations=run.timeline_proposal.temporal_relations,
            review_id=result.review_id,
            review_status=result.decision,
            issues=result.issues,
            evidence_refs=[*run.timeline_proposal.evidence_refs, *result.evidence_refs],
            provenance=TimelineReviewMaterialProvenanceV1(
                source_chunk_ids=self._chunk_ids(run.timeline_input),
                timeline_agent_run_id=run.timeline_agent_run_id,
                gate3_reviewer_agent_run_id=reviewer_agent_run_id,
            ),
        )
        return self._repository.save_transition(
            reviewing.model_copy(
                update={
                    "status": status,
                    "gate3_result": result,
                    "gate3_route": route,
                    "timeline_review_material": material,
                    "approved_timeline_bundle": route.approved_timeline_bundle,
                    "updated_at": datetime.now(UTC),
                }
            )
        )

    @staticmethod
    def _chunk_ids(timeline_input: TimelineAnalysisInputV1) -> list[str]:
        proposals = [
            *cast(list[TimelineAnalysisProposalV1], timeline_input.event_proposals),
            *cast(list[TimelineAnalysisProposalV1], timeline_input.claim_proposals),
            *cast(list[TimelineAnalysisProposalV1], timeline_input.state_change_proposals),
        ]
        return list(
            dict.fromkeys(
                evidence.chunk_id
                for proposal in proposals
                for evidence in proposal.evidence_refs
            )
        )


def _safe_failure_diagnostics(exc: Exception) -> tuple[ProviderFailureCategory, list[str]]:
    """Classify Timeline execution failures without persisting provider response text."""

    if isinstance(exc, (ProviderTimeoutError, TimeoutError)):
        return ProviderFailureCategory.TIMEOUT, ["TIMELINE_PROVIDER_TIMEOUT"]
    if isinstance(exc, ProviderNetworkError):
        return ProviderFailureCategory.CONNECTION, ["TIMELINE_PROVIDER_CONNECTION_ERROR"]
    if isinstance(exc, ProviderHttpError):
        return ProviderFailureCategory.SERVER, ["TIMELINE_PROVIDER_HTTP_ERROR"]
    if isinstance(exc, (ProviderResponseError, ValueError)):
        return ProviderFailureCategory.SCHEMA, ["TIMELINE_SCHEMA_VALIDATION_FAILED"]
    return ProviderFailureCategory.UNKNOWN, ["TIMELINE_EXECUTION_FAILED"]


def _provider_request_count(runner: TimelineRunner) -> int:
    value = getattr(runner, "provider_request_count", 1)
    return value if isinstance(value, int) and value >= 0 else 1


def _safe_provider_diagnostics(exc: Exception) -> TimelineProviderDiagnosticsV1 | None:
    """Copy only typed, source-free Provider diagnostics into the Timeline run."""

    if not isinstance(exc, ProviderResponseError):
        return None
    diagnostics = exc.diagnostics

    def safe_strings(key: str, limit: int, pattern: str) -> list[str]:
        value = diagnostics.get(key)
        if not isinstance(value, list):
            return []
        return [
            item[:256]
            for item in value
            if isinstance(item, str) and re.fullmatch(pattern, item[:256])
        ][:limit]

    expected = diagnostics.get("expected_output_schema")
    finish_reason = diagnostics.get("finish_reason")
    safe_expected = (
        expected[:128]
        if isinstance(expected, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", expected)
        else None
    )
    safe_finish = (
        finish_reason[:64]
        if isinstance(finish_reason, str)
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", finish_reason)
        else None
    )
    return TimelineProviderDiagnosticsV1(
        expected_output_schema=safe_expected,
        schema_error_field_paths=safe_strings(
            "schema_error_field_paths", 32, r"[A-Za-z0-9_.\[\]-]{1,256}"
        ),
        schema_error_rule_codes=safe_strings(
            "schema_error_rule_codes", 32, r"[A-Z][A-Z0-9_]{0,255}"
        ),
        finish_reason=(
            safe_finish
        ),
    )
