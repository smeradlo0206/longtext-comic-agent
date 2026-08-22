"""Idempotent Gate 2 APPROVED -> Timeline -> fresh Gate 3 orchestration."""

from datetime import UTC, datetime
from typing import Protocol, cast

from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.review import NarrativeAnalysisReviewRouteV1, ReviewGate2RoutingDecision
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.timeline import (
    ReviewGate3Decision,
    TimelineAnalysisInputV1,
    TimelineAnalysisMode,
    TimelineAnalysisProposalV1,
    TimelineGate3RunStatus,
    TimelineGate3RunV1,
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
        except (RuntimeError, TimeoutError, ValueError):
            failed = running.model_copy(
                update={
                    "status": TimelineGate3RunStatus.FAILED,
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
                    "provider_request_count": running.provider_request_count + 1,
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
        except (RuntimeError, TimeoutError, ValueError):
            failed = recovering.model_copy(
                update={
                    "status": TimelineGate3RunStatus.FAILED,
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
        return self._repository.save_transition(
            reviewing.model_copy(
                update={
                    "status": status,
                    "gate3_result": result,
                    "gate3_route": route,
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
