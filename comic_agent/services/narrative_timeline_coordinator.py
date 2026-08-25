"""Idempotent Gate 2 APPROVED -> Timeline -> fresh Gate 3 orchestration."""

import re
from datetime import UTC, datetime
from typing import Protocol, cast

from pydantic import ValidationError

from comic_agent.providers.openai_compatible import (
    ProviderHttpError,
    ProviderNetworkError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.base import EvidenceRefV1
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
    TimelineFailureOrigin,
    TimelineFailureSummaryV1,
    TimelineGate3RunStatus,
    TimelineGate3RunV1,
    TimelineProviderDiagnosticsV1,
    TimelineReviewMaterialProvenanceV1,
    TimelineReviewMaterialV1,
    TimelineValidationErrorV1,
)
from comic_agent.schemas.timeline_execution import (
    TimelineExecutionBundleV1,
    TimelineExecutionDiagnosticV1,
    TimelineExecutionFailedItemV1,
    TimelineExecutionInputReferenceV1,
    TimelineExecutionIssueV1,
    TimelineExecutionProvenanceV1,
    TimelineExecutionStatus,
    TimelineInputAvailability,
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
                schema_version="1.5",
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
            return self._persist_failure(
                running=running,
                timeline_input=timeline_input,
                exc=exc,
                provider_request_count=(
                    running.provider_request_count + _provider_request_count(self._timeline_runner)
                ),
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
                    "timeline_execution_bundle": self._succeeded_execution_bundle(
                        running=running,
                        timeline_input=timeline_input,
                        proposal=proposal,
                        timeline_agent_run_id=agent_run_id,
                    ),
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
        if execution is None:
            return None
        input_availability = self._adapter.classify_execution_input(execution)
        if input_availability != TimelineInputAvailability.AVAILABLE:
            return self._persist_input_unavailable(
                route=route,
                execution=execution,
                input_availability=input_availability,
            )
        try:
            timeline_input = self._adapter.build_from_execution_bundle(
                route=route,
                source_chunks=source_chunks,
                mode=self._timeline_mode,
            )
        except ValueError:
            # A candidate whose evidence cannot be located is never a Timeline fact.
            # Persist the audited exclusion outcome instead of silently breaking
            # the Narrative -> Timeline handoff.
            return self._persist_input_unavailable(
                route=route,
                execution=execution,
                input_availability=TimelineInputAvailability.INPUT_EXCLUDED,
            )
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
        reserved = self._reserve_execution_run(route=route, execution=execution)
        if reserved is None:
            return None
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
            return self._persist_failure(
                running=running,
                timeline_input=timeline_input,
                exc=exc,
                provider_request_count=(
                    running.provider_request_count + _provider_request_count(self._timeline_runner)
                ),
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
                    "timeline_execution_bundle": self._succeeded_execution_bundle(
                        running=running,
                        timeline_input=timeline_input,
                        proposal=proposal,
                        timeline_agent_run_id=agent_run_id,
                    ),
                    "provider_request_count": (
                        running.provider_request_count
                        + _provider_request_count(self._timeline_runner)
                    ),
                    "updated_at": datetime.now(UTC),
                }
            )
        )
        return self._review(succeeded)

    def _persist_input_unavailable(
        self,
        *,
        route: NarrativeAnalysisReviewRouteV1,
        execution: NarrativeExecutionBundleV1,
        input_availability: TimelineInputAvailability,
    ) -> TimelineGate3RunV1 | None:
        """Persist a zero-provider Timeline outcome when audited input is unavailable.

        This path records no temporal relation and never calls ``TimelineRunner``.
        It exists solely to carry the source-free input classification through the
        ordinary Gate 3 and Human Review artifacts.
        """

        reserved = self._reserve_execution_run(route=route, execution=execution)
        if reserved is None:
            return None
        if reserved.status in _TERMINAL or reserved.status == TimelineGate3RunStatus.RUNNING:
            return reserved

        timeline_agent_run_id = stable_id(
            "timeline-input-classification-run", reserved.timeline_run_id
        )
        reviewer_agent_run_id = stable_id(
            "gate3-agent-input-unavailable-run", reserved.timeline_run_id
        )
        evidence_refs: list[EvidenceRefV1] = []
        for evidence_ref in execution.evidence_refs:
            if evidence_ref not in evidence_refs:
                evidence_refs.append(evidence_ref)
        if not evidence_refs:
            raise ValueError("Timeline input-unavailable artifact requires Narrative evidence")
        execution_bundle = TimelineExecutionBundleV1(
            schema_version="1.1",
            bundle_id=stable_id("timeline-execution", reserved.timeline_run_id),
            project_id=reserved.project_id,
            timeline_run_id=reserved.timeline_run_id,
            status=TimelineExecutionStatus.NEEDS_HUMAN_ACTION,
            input_reference=self._input_reference_from_execution(
                running=reserved,
                execution=execution,
            ),
            input_availability=input_availability,
            input_availability_summary=self._adapter.execution_input_summary(execution),
            candidate_relations=[],
            issues=[
                TimelineExecutionIssueV1(
                    issue_id=stable_id(
                        "timeline-input-unavailable-issue",
                        reserved.timeline_run_id,
                        str(input_availability),
                    ),
                    issue_code=f"TIMELINE_{input_availability}",
                    severity="WARNING",
                    evidence_refs=evidence_refs,
                )
            ],
            evidence_refs=evidence_refs,
            provenance=TimelineExecutionProvenanceV1(
                source_chunk_ids=list(execution.provenance.source_chunk_ids),
                timeline_agent_run_id=timeline_agent_run_id,
                gate3_reviewer_agent_run_id=reviewer_agent_run_id,
            ),
            provider_request_count=0,
        )
        proposal = self._input_unavailable_timeline_proposal(
            running=reserved,
            evidence_refs=evidence_refs,
        )
        self._agent_runs.save_agent_run(
            AgentRunV1(
                agent_run_id=timeline_agent_run_id,
                project_id=reserved.project_id,
                agent_name="timeline-input-classifier",
                input_chunk_ids=list(execution.provenance.source_chunk_ids),
                output_proposal_ids=[proposal.proposal_id],
                output_schema="TimelineAnalysisProposalV1",
                status=AgentRunStatus.SUCCEEDED,
                payload={
                    "timeline_run_id": reserved.timeline_run_id,
                    "input_availability": str(input_availability),
                    "provider_request_count": 0,
                },
            )
        )
        result, gate3_route = self._review_service.execution_failed(
            timeline_execution_bundle=execution_bundle,
            reviewer_agent_run_id=reviewer_agent_run_id,
        )
        self._agent_runs.save_agent_run(
            AgentRunV1(
                agent_run_id=reviewer_agent_run_id,
                project_id=reserved.project_id,
                agent_name="review-gate-3",
                input_chunk_ids=list(execution.provenance.source_chunk_ids),
                output_proposal_ids=[result.review_id],
                output_schema="ReviewGate3ResultV1",
                status=AgentRunStatus.SUCCEEDED,
                payload={
                    "timeline_run_id": reserved.timeline_run_id,
                    "input_availability": str(input_availability),
                    "provider_request_count": 0,
                },
            )
        )
        material = TimelineReviewMaterialV1(
            schema_version="1.3",
            material_id=stable_id(
                "timeline-review-material", reserved.timeline_run_id, result.review_id
            ),
            project_id=reserved.project_id,
            narrative_execution_bundle_id=execution.bundle_id,
            timeline_run_id=reserved.timeline_run_id,
            timeline_execution_bundle_id=execution_bundle.bundle_id,
            timeline_candidate=proposal,
            temporal_relations=[],
            review_id=result.review_id,
            review_status=result.decision,
            issues=result.issues,
            evidence_refs=[*proposal.evidence_refs, *result.evidence_refs],
            provenance=TimelineReviewMaterialProvenanceV1(
                source_chunk_ids=list(execution.provenance.source_chunk_ids),
                timeline_agent_run_id=timeline_agent_run_id,
                gate3_reviewer_agent_run_id=reviewer_agent_run_id,
            ),
        )
        return self._repository.save_transition(
            reserved.model_copy(
                update={
                    "status": TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW,
                    "timeline_proposal": proposal,
                    "timeline_agent_run_id": timeline_agent_run_id,
                    "gate3_result": result,
                    "gate3_route": gate3_route,
                    "timeline_review_material": material,
                    "timeline_execution_bundle": execution_bundle,
                    "provider_request_count": 0,
                    "updated_at": datetime.now(UTC),
                }
            )
        )

    def _reserve_execution_run(
        self,
        *,
        route: NarrativeAnalysisReviewRouteV1,
        execution: NarrativeExecutionBundleV1,
    ) -> TimelineGate3RunV1 | None:
        """Reserve the existing Timeline/Gate 3 checkpoint for an execution bundle."""

        gate2_review_id = route.review_run_id
        if not isinstance(gate2_review_id, str) or not gate2_review_id:
            return None
        approved_bundle_id = (
            route.approved_proposal_bundle.bundle_id
            if route.approved_proposal_bundle is not None
            else None
        )
        timeline_source_id = approved_bundle_id or execution.bundle_id
        key = stable_id("timeline-gate3-key", execution.project_id, timeline_source_id)
        return self._repository.reserve_run(
            TimelineGate3RunV1(
                schema_version="1.6",
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
            return self._persist_failure(
                running=recovering,
                timeline_input=recovering.timeline_input,
                exc=exc,
                provider_request_count=(
                    recovering.provider_request_count
                    + _provider_request_count(self._timeline_runner)
                ),
            )
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
                    "timeline_execution_bundle": self._succeeded_execution_bundle(
                        running=recovering,
                        timeline_input=recovering.timeline_input,
                        proposal=proposal,
                        timeline_agent_run_id=agent_run_id,
                    ),
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
                timeline_execution_bundle=run.timeline_execution_bundle,
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
            schema_version=("1.3" if run.timeline_execution_bundle is not None else "1.1"),
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
            timeline_execution_bundle_id=(
                run.timeline_execution_bundle.bundle_id
                if run.timeline_execution_bundle is not None
                else None
            ),
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

    def _persist_failure(
        self,
        *,
        running: TimelineGate3RunV1,
        timeline_input: TimelineAnalysisInputV1,
        exc: Exception,
        provider_request_count: int,
    ) -> TimelineGate3RunV1:
        """Persist a readable, source-free terminal Timeline failure artifact.

        Timeline v1.3 requires terminal review material.  A Provider or local
        validation failure has no valid inferred relation, so this records an
        empty, evidence-backed candidate and a failed Gate 3 audit rather than
        manufacturing a Timeline fact or leaving an unreadable checkpoint.
        """

        failure_category, safe_issue_codes = _safe_failure_diagnostics(exc)
        diagnostics = _safe_provider_diagnostics(exc)
        timeline_agent_run_id = stable_id("timeline-agent-failure-run", running.timeline_run_id)
        reviewer_agent_run_id = stable_id("gate3-agent-failure-run", running.timeline_run_id)
        failure_origin = (
            str(diagnostics.failure_origin) if diagnostics and diagnostics.failure_origin else None
        )
        execution_bundle = self._failed_execution_bundle(
            running=running,
            timeline_input=timeline_input,
            timeline_agent_run_id=timeline_agent_run_id,
            reviewer_agent_run_id=reviewer_agent_run_id,
            failure_category=failure_category,
            safe_issue_codes=safe_issue_codes,
            diagnostics=diagnostics,
        )
        self._agent_runs.save_agent_run(
            AgentRunV1(
                agent_run_id=timeline_agent_run_id,
                project_id=running.project_id,
                agent_name="timeline-agent",
                input_chunk_ids=self._chunk_ids(timeline_input),
                output_schema="TimelineAnalysisProposalV1",
                status=AgentRunStatus.FAILED,
                error_message="Timeline execution failed",
                payload={
                    "timeline_run_id": running.timeline_run_id,
                    "failure_origin": failure_origin,
                },
            )
        )
        result, route = self._review_service.execution_failed(
            timeline_execution_bundle=execution_bundle,
            reviewer_agent_run_id=reviewer_agent_run_id,
        )
        self._agent_runs.save_agent_run(
            AgentRunV1(
                agent_run_id=reviewer_agent_run_id,
                project_id=running.project_id,
                agent_name="review-gate-3",
                input_chunk_ids=self._chunk_ids(timeline_input),
                output_proposal_ids=[result.review_id],
                output_schema="ReviewGate3ResultV1",
                status=AgentRunStatus.SUCCEEDED,
                payload={
                    "timeline_run_id": running.timeline_run_id,
                    "failure_origin": failure_origin,
                },
            )
        )
        proposal = self._failed_timeline_proposal(running, timeline_input)
        material = TimelineReviewMaterialV1(
            schema_version="1.3",
            material_id=stable_id(
                "timeline-review-material", running.timeline_run_id, result.review_id
            ),
            project_id=running.project_id,
            narrative_execution_bundle_id=(
                running.source_narrative_execution_bundle_id
                or stable_id(
                    "legacy-approved-bundle-execution",
                    running.source_approved_proposal_bundle_id,
                )
            ),
            timeline_run_id=running.timeline_run_id,
            timeline_execution_bundle_id=execution_bundle.bundle_id,
            timeline_candidate=proposal,
            temporal_relations=[],
            review_id=result.review_id,
            review_status=result.decision,
            issues=result.issues,
            evidence_refs=[*proposal.evidence_refs, *result.evidence_refs],
            provenance=TimelineReviewMaterialProvenanceV1(
                source_chunk_ids=self._chunk_ids(timeline_input),
                timeline_agent_run_id=timeline_agent_run_id,
                gate3_reviewer_agent_run_id=reviewer_agent_run_id,
            ),
            failure_summary=TimelineFailureSummaryV1(
                category=failure_category,
                error_origin=(diagnostics.failure_origin if diagnostics else None),
                field_path=(
                    diagnostics.validation_errors[0].field_path
                    if diagnostics and diagnostics.validation_errors
                    else None
                ),
            ),
        )
        return self._repository.save_transition(
            running.model_copy(
                update={
                    "status": TimelineGate3RunStatus.NEEDS_HUMAN_REVIEW,
                    "timeline_proposal": proposal,
                    "timeline_agent_run_id": timeline_agent_run_id,
                    "gate3_result": result,
                    "gate3_route": route,
                    "timeline_review_material": material,
                    "timeline_execution_bundle": execution_bundle,
                    "failure_category": failure_category,
                    "safe_issue_codes": safe_issue_codes,
                    "provider_request_count": provider_request_count,
                    "provider_diagnostics": diagnostics,
                    "updated_at": datetime.now(UTC),
                }
            )
        )

    @staticmethod
    def _input_reference(
        running: TimelineGate3RunV1,
        timeline_input: TimelineAnalysisInputV1,
    ) -> TimelineExecutionInputReferenceV1:
        """Describe Timeline input identity without retaining source text."""

        return TimelineExecutionInputReferenceV1(
            source_approved_proposal_bundle_id=(running.source_approved_proposal_bundle_id),
            source_narrative_execution_bundle_id=(running.source_narrative_execution_bundle_id),
            source_gate2_review_id=running.source_gate2_review_id,
            source_gate2_route_id=running.source_gate2_route_id,
            event_proposal_ids=[item.proposal_id for item in timeline_input.event_proposals],
            claim_proposal_ids=[item.proposal_id for item in timeline_input.claim_proposals],
            state_change_proposal_ids=[
                item.proposal_id for item in timeline_input.state_change_proposals
            ],
        )

    @staticmethod
    def _input_reference_from_execution(
        *,
        running: TimelineGate3RunV1,
        execution: NarrativeExecutionBundleV1,
    ) -> TimelineExecutionInputReferenceV1:
        """Retain only handoff identity when no candidate reaches Timeline."""

        return TimelineExecutionInputReferenceV1(
            source_approved_proposal_bundle_id=(running.source_approved_proposal_bundle_id),
            source_narrative_execution_bundle_id=(running.source_narrative_execution_bundle_id),
            source_gate2_review_id=running.source_gate2_review_id,
            source_gate2_route_id=running.source_gate2_route_id,
        )

    @staticmethod
    def _input_unavailable_timeline_proposal(
        *,
        running: TimelineGate3RunV1,
        evidence_refs: list[EvidenceRefV1],
    ) -> TimelineAnalysisProposalV1:
        """Create empty review material without asserting a temporal relation."""

        return TimelineAnalysisProposalV1(
            proposal_id=stable_id("timeline-input-unavailable-proposal", running.timeline_run_id),
            project_id=running.project_id,
            temporal_relations=[],
            conflicts=[],
            duplicate_candidates=[],
            evidence_refs=evidence_refs,
            confidence=0,
        )

    def _succeeded_execution_bundle(
        self,
        *,
        running: TimelineGate3RunV1,
        timeline_input: TimelineAnalysisInputV1,
        proposal: TimelineAnalysisProposalV1,
        timeline_agent_run_id: str,
    ) -> TimelineExecutionBundleV1:
        return TimelineExecutionBundleV1(
            bundle_id=stable_id("timeline-execution", running.timeline_run_id),
            project_id=running.project_id,
            timeline_run_id=running.timeline_run_id,
            status=TimelineExecutionStatus.SUCCEEDED,
            input_reference=self._input_reference(running, timeline_input),
            candidate_relations=proposal.temporal_relations,
            evidence_refs=proposal.evidence_refs,
            provenance=TimelineExecutionProvenanceV1(
                source_chunk_ids=self._chunk_ids(timeline_input),
                timeline_agent_run_id=timeline_agent_run_id,
            ),
        )

    def _failed_execution_bundle(
        self,
        *,
        running: TimelineGate3RunV1,
        timeline_input: TimelineAnalysisInputV1,
        timeline_agent_run_id: str,
        reviewer_agent_run_id: str,
        failure_category: ProviderFailureCategory,
        safe_issue_codes: list[str],
        diagnostics: TimelineProviderDiagnosticsV1 | None,
    ) -> TimelineExecutionBundleV1:
        """Persist a source-free failed unit without manufacturing a relation."""

        first_error = (
            diagnostics.validation_errors[0]
            if (diagnostics and diagnostics.validation_errors)
            else None
        )
        failure_origin = (
            str(diagnostics.failure_origin)
            if diagnostics and diagnostics.failure_origin is not None
            else None
        )
        pair_id = stable_id("timeline-failed-unit", running.timeline_run_id)
        issue_code = safe_issue_codes[0] if safe_issue_codes else "TIMELINE_EXECUTION_FAILED"
        issue_id = stable_id("timeline-execution-issue", running.timeline_run_id, issue_code)
        source_evidence = self._failed_timeline_proposal(running, timeline_input).evidence_refs
        execution_status = (
            TimelineExecutionStatus.NEEDS_HUMAN_ACTION
            if failure_category
            in {
                ProviderFailureCategory.TIMEOUT,
                ProviderFailureCategory.CONNECTION,
                ProviderFailureCategory.SERVER,
            }
            else TimelineExecutionStatus.FAILED
        )
        return TimelineExecutionBundleV1(
            bundle_id=stable_id("timeline-execution", running.timeline_run_id),
            project_id=running.project_id,
            timeline_run_id=running.timeline_run_id,
            status=execution_status,
            input_reference=self._input_reference(running, timeline_input),
            failed_items=[
                TimelineExecutionFailedItemV1(
                    pair_id=pair_id,
                    failure_category=failure_category,
                    field_path=(first_error.field_path if first_error else None),
                    failure_origin=failure_origin,
                    safe_issue_codes=safe_issue_codes,
                )
            ],
            issues=[
                TimelineExecutionIssueV1(
                    issue_id=issue_id,
                    issue_code=issue_code,
                    failed_pair_id=pair_id,
                    evidence_refs=source_evidence,
                )
            ],
            diagnostics=(
                [
                    TimelineExecutionDiagnosticV1(
                        failure_origin=failure_origin,
                        field_path=item.field_path,
                        error_type=item.error_type,
                        message_type=item.message_type,
                    )
                    for item in diagnostics.validation_errors
                ]
                if diagnostics
                else []
            ),
            evidence_refs=source_evidence,
            provenance=TimelineExecutionProvenanceV1(
                source_chunk_ids=self._chunk_ids(timeline_input),
                timeline_agent_run_id=timeline_agent_run_id,
                gate3_reviewer_agent_run_id=reviewer_agent_run_id,
            ),
        )

    @staticmethod
    def _failed_timeline_proposal(
        running: TimelineGate3RunV1,
        timeline_input: TimelineAnalysisInputV1,
    ) -> TimelineAnalysisProposalV1:
        """Build an empty, source-backed candidate solely for failure review material."""

        evidence_refs: list[EvidenceRefV1] = []

        def add_evidence(source_evidence: list[EvidenceRefV1]) -> None:
            for evidence_ref in source_evidence:
                if evidence_ref not in evidence_refs:
                    evidence_refs.append(evidence_ref)

        for event_proposal in timeline_input.event_proposals:
            add_evidence(event_proposal.evidence_refs)
        for claim_proposal in timeline_input.claim_proposals:
            add_evidence(claim_proposal.evidence_refs)
        for state_change_proposal in timeline_input.state_change_proposals:
            add_evidence(state_change_proposal.evidence_refs)
        return TimelineAnalysisProposalV1(
            proposal_id=stable_id("timeline-failure-proposal", running.timeline_run_id),
            project_id=running.project_id,
            temporal_relations=[],
            conflicts=[],
            duplicate_candidates=[],
            evidence_refs=evidence_refs,
            confidence=0,
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
                evidence.chunk_id for proposal in proposals for evidence in proposal.evidence_refs
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
    """Return typed, source-free validation diagnostics when available."""

    if isinstance(exc, ValidationError):
        validation_errors = _validation_errors_from_pydantic(exc)
        return TimelineProviderDiagnosticsV1(
            failure_origin=TimelineFailureOrigin.LOCAL_ARTIFACT_CONSTRUCTION_ERROR,
            validation_errors=validation_errors,
            schema_error_field_paths=[item.field_path for item in validation_errors],
            schema_error_rule_codes=[item.error_type.upper() for item in validation_errors],
        )
    if not isinstance(exc, ProviderResponseError):
        if isinstance(exc, ValueError):
            return TimelineProviderDiagnosticsV1(
                failure_origin=TimelineFailureOrigin.CONTRACT_VALIDATION_ERROR,
            )
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
    field_paths = safe_strings("schema_error_field_paths", 32, r"[A-Za-z0-9_.\[\]-]{1,256}")
    rule_codes = safe_strings("schema_error_rule_codes", 32, r"[A-Z][A-Z0-9_]{0,255}")
    error_kind = diagnostics.get("schema_error_kind")
    safe_error_type = (
        error_kind[:128]
        if isinstance(error_kind, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", error_kind)
        else "provider_response_error"
    )
    return TimelineProviderDiagnosticsV1(
        failure_origin=TimelineFailureOrigin.LLM_OUTPUT_SCHEMA_INVALID,
        expected_output_schema=safe_expected,
        schema_error_field_paths=field_paths,
        schema_error_rule_codes=rule_codes,
        finish_reason=safe_finish,
        validation_errors=[
            TimelineValidationErrorV1(
                field_path=field_path,
                error_type=safe_error_type,
                message_type=_message_type(safe_error_type),
            )
            for field_path in field_paths
        ],
    )


def _validation_errors_from_pydantic(exc: ValidationError) -> list[TimelineValidationErrorV1]:
    """Convert Pydantic locations into a bounded allowlist without input values."""

    validation_errors: list[TimelineValidationErrorV1] = []
    for error in exc.errors(include_input=False)[:32]:
        field_path = _safe_field_path(error.get("loc"))
        error_type = error.get("type")
        if field_path is None or not isinstance(error_type, str):
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", error_type):
            continue
        validation_errors.append(
            TimelineValidationErrorV1(
                field_path=field_path,
                error_type=error_type,
                message_type=_message_type(error_type),
            )
        )
    return validation_errors


def _safe_field_path(location: object) -> str | None:
    if not isinstance(location, tuple) or not location:
        return None
    parts: list[str] = []
    for item in location:
        if isinstance(item, int) and item >= 0:
            parts.append(f"[{item}]")
        elif isinstance(item, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item):
            parts.append(item)
        else:
            return None
    path = "".join(
        part if part.startswith("[") or index == 0 else f".{part}"
        for index, part in enumerate(parts)
    )
    return path if re.fullmatch(r"[A-Za-z0-9_.\[\]-]{1,256}", path) else None


def _message_type(error_type: str) -> str:
    if error_type == "literal_error":
        return "enum_error"
    if error_type == "missing":
        return "missing_field"
    if error_type == "extra_forbidden":
        return "extra_field"
    if error_type.endswith("_type"):
        return "type_error"
    if error_type == "value_error":
        return "value_error"
    return "validation_error"
