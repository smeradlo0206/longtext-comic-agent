"""Deterministic Stage B directives for strictly original-window reruns."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, cast

from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.recovery import (
    RecoveryAttemptStatus,
    RecoveryAttemptV1,
    RecoveryBudgetUsageV1,
    RecoveryDirectiveV1,
    RecoveryOutcomeStatus,
    RecoveryOutcomeV1,
    RecoveryPolicyV1,
)
from comic_agent.schemas.review import (
    NarrativeAnalysisReviewRouteV1,
    ReviewGate2ResultV1,
    ReviewGate2RoutingDecision,
    ReviewIssueCode,
)
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.workflow import (
    AgentRunStatus,
    AgentRunV1,
    NarrativeAnalysisResultV1,
    NarrativeAnalysisRunV1,
    NarrativeAnalysisWindowStatus,
    NarrativeAnalysisWindowV1,
)
from comic_agent.services.id_service import checksum_text, stable_id
from comic_agent.services.narrative_analysis_aggregation import aggregate_narrative_analysis
from comic_agent.services.narrative_analysis_proposal_sources import proposal_sources_for_window
from comic_agent.services.narrative_analysis_review_coordinator import (
    NarrativeAnalysisReviewCoordinator,
)
from comic_agent.services.review_gate2_service import (
    ReviewGate2Service,
    ReviewGate2ServiceContext,
    build_review_gate2_input,
)


def default_recovery_policy() -> RecoveryPolicyV1:
    """Return the fixed, conservative Stage B policy for evidence-only reruns."""

    return RecoveryPolicyV1(
        policy_id="stage-b-evidence-rerun-v1",
        allowed_issue_codes=[
            ReviewIssueCode.EVIDENCE_QUOTE_NOT_FOUND,
            ReviewIssueCode.EVIDENCE_RANGE_INCOMPLETE,
            ReviewIssueCode.EVIDENCE_OFFSET_MISMATCH,
        ],
        terminal_issue_codes=[
            ReviewIssueCode.EXACT_DUPLICATE,
            ReviewIssueCode.PROVENANCE_MISSING,
            ReviewIssueCode.ANALYSIS_RUN_MISMATCH,
            ReviewIssueCode.AGENT_RUN_NOT_FOUND,
            ReviewIssueCode.HUMAN_DECISION_REQUIRED,
        ],
        max_attempts_per_proposal=1,
        max_attempts_per_window=1,
        max_attempts_per_root_run=3,
        max_total_tokens=100_000,
        max_elapsed_seconds=300,
        max_provider_requests=3,
    )


class _SourceRepository(Protocol):
    def get_review_gate1(self, document_id: str) -> object: ...

    def get_chunk(self, chunk_id: str) -> SourceChunkV1 | None: ...


class _AnalysisRepository(Protocol):
    def get_run(self, analysis_run_id: str) -> NarrativeAnalysisRunV1 | None: ...

    def get_result(self, analysis_run_id: str) -> NarrativeAnalysisResultV1 | None: ...

    def list_windows(self, analysis_run_id: str) -> list[NarrativeAnalysisWindowV1]: ...


class _RecoveryRepository(Protocol):
    def list_attempts(self, root_analysis_run_id: str) -> list[RecoveryAttemptV1]: ...

    def reserve_attempt(self, attempt: RecoveryAttemptV1) -> tuple[RecoveryAttemptV1, bool]: ...

    def save_attempt_transition(self, attempt: RecoveryAttemptV1) -> RecoveryAttemptV1: ...


class NarrativeAnalysisRecoveryCoordinator:
    """Derive source-locked directives; execution is intentionally separate."""

    def __init__(
        self,
        *,
        source_repository: _SourceRepository,
        analysis_repository: _AnalysisRepository,
        recovery_repository: _RecoveryRepository,
        policy: RecoveryPolicyV1,
        rerun_window: Callable[[RecoveryDirectiveV1, str], AgentRunV1 | None] | None = None,
        get_agent_run: Callable[[str], AgentRunV1 | None] | None = None,
        review_service: ReviewGate2Service | None = None,
    ) -> None:
        self._source_repository = source_repository
        self._analysis_repository = analysis_repository
        self._recovery_repository = recovery_repository
        self._policy = policy
        self._rerun_window = rerun_window
        self._get_agent_run = get_agent_run
        self._review_service = review_service or ReviewGate2Service()

    def derive_directive(
        self,
        root_analysis_run_id: str,
        proposal_id: str,
        issue_codes: list[ReviewIssueCode],
    ) -> RecoveryDirectiveV1 | RecoveryOutcomeV1:
        """Return one exact-scope directive or a terminal safe outcome."""

        run = self._analysis_repository.get_run(root_analysis_run_id)
        result = self._analysis_repository.get_result(root_analysis_run_id)
        if run is None or result is None:
            return self._outcome(root_analysis_run_id, proposal_id, RecoveryOutcomeStatus.SKIPPED)
        codes = {str(code) for code in issue_codes}
        allowed = {str(code) for code in self._policy.allowed_issue_codes}
        if not codes or not codes.issubset(allowed):
            return self._outcome(
                root_analysis_run_id,
                proposal_id,
                RecoveryOutcomeStatus.NON_RECOVERABLE,
                issue_codes,
            )
        proposal_sources = [
            item
            for collection in (
                result.events,
                result.entities,
                result.claims,
                result.knowledge_states,
                result.state_changes,
                result.relationship_signals,
            )
            for item in collection
            if item.proposal.proposal_id == proposal_id
        ]
        if len(proposal_sources) != 1 or len(proposal_sources[0].agent_run_ids) != 1:
            return self._outcome(
                root_analysis_run_id, proposal_id, RecoveryOutcomeStatus.NON_RECOVERABLE
            )
        source = proposal_sources[0]
        windows = self._analysis_repository.list_windows(root_analysis_run_id)
        matching = [
            window
            for window in windows
            if window.status == NarrativeAnalysisWindowStatus.SUCCEEDED
            and window.agent_run_id == source.agent_run_ids[0]
            and not any(
                candidate.parent_window_id == window.analysis_window_id for candidate in windows
            )
        ]
        if len(matching) != 1:
            return self._outcome(
                root_analysis_run_id, proposal_id, RecoveryOutcomeStatus.NON_RECOVERABLE
            )
        window = matching[0]
        gate1 = self._source_repository.get_review_gate1(run.document_id)
        bundle = getattr(gate1, "approved_chunk_bundle", None)
        approved = list(getattr(bundle, "chunk_ids", []))
        if not approved or any(chunk_id not in approved for chunk_id in window.chunk_ids):
            return self._outcome(
                root_analysis_run_id, proposal_id, RecoveryOutcomeStatus.NON_RECOVERABLE
            )
        stored_attempts = self._recovery_repository.list_attempts(root_analysis_run_id)
        attempts = [
            attempt
            for attempt in stored_attempts
            if isinstance(attempt, RecoveryAttemptV1)
        ]
        proposal_attempts = [
            attempt for attempt in attempts if attempt.directive.proposal_id == proposal_id
        ]
        window_attempts = [
            attempt
            for attempt in attempts
            if attempt.directive.original_window_id == window.analysis_window_id
        ]
        usage = RecoveryBudgetUsageV1(
            proposal_attempts=len(proposal_attempts),
            window_attempts=len(window_attempts),
            root_run_attempts=len(stored_attempts),
            total_tokens=sum(attempt.budget_usage.total_tokens for attempt in attempts),
            elapsed_seconds=sum(attempt.budget_usage.elapsed_seconds for attempt in attempts),
            provider_requests=sum(attempt.budget_usage.provider_requests for attempt in attempts),
        )
        exhausted = (
            usage.proposal_attempts >= self._policy.max_attempts_per_proposal
            or usage.window_attempts >= self._policy.max_attempts_per_window
            or usage.root_run_attempts >= self._policy.max_attempts_per_root_run
            or usage.total_tokens >= self._policy.max_total_tokens
            or usage.elapsed_seconds >= self._policy.max_elapsed_seconds
            or (
                self._policy.max_provider_requests is not None
                and usage.provider_requests >= self._policy.max_provider_requests
            )
        )
        if exhausted:
            return self._outcome(
                root_analysis_run_id,
                proposal_id,
                RecoveryOutcomeStatus.BUDGET_EXHAUSTED,
                issue_codes,
                usage,
            )
        parts = (
            root_analysis_run_id,
            proposal_id,
            source.agent_run_ids[0],
            window.analysis_window_id,
            self._policy.policy_id,
            ",".join(str(code) for code in issue_codes),
            str(usage.proposal_attempts + 1),
        )
        key = stable_id("recovery-attempt", checksum_text("|".join(parts)))
        return RecoveryDirectiveV1(
            directive_id=stable_id("recovery-directive", key),
            idempotency_key=key,
            root_analysis_run_id=root_analysis_run_id,
            project_id=run.project_id,
            document_id=run.document_id,
            proposal_id=proposal_id,
            proposal_schema=type(source.proposal).__name__,
            mode=window.mode,
            original_window_id=window.analysis_window_id,
            original_agent_run_id=source.agent_run_ids[0],
            ordered_source_chunk_ids=list(window.chunk_ids),
            approved_source_chunk_ids=list(window.chunk_ids),
            issue_ids=[f"gate2:{proposal_id}:{code}" for code in issue_codes],
            issue_codes=issue_codes,
            policy=self._policy,
            budget_usage=usage,
            max_chars_per_chunk=window.effective_max_chars_per_chunk,
        )

    def recover_if_eligible(
        self,
        root_analysis_run_id: str,
        *,
        real_llm_requested: bool,
    ) -> list[RecoveryOutcomeV1]:
        """Return safe no-op outcomes until an eligible rejected route is wired for execution."""

        run = self._analysis_repository.get_run(root_analysis_run_id)
        if run is None:
            return [self._outcome(root_analysis_run_id, "unknown", RecoveryOutcomeStatus.SKIPPED)]
        route = run.review_gate2_route
        if (
            run.status != "SUCCEEDED"
            or route is None
            or route.decision != ReviewGate2RoutingDecision.REJECTED
        ):
            return []
        outcomes: list[RecoveryOutcomeV1] = []
        for diagnostic in route.recovery_diagnostics:
            if not diagnostic.eligible_for_original_mode_rerun:
                outcome = self._outcome(
                    root_analysis_run_id,
                    diagnostic.proposal_id,
                    RecoveryOutcomeStatus.NON_RECOVERABLE,
                    diagnostic.issue_codes,
                )
            else:
                resumable = [
                    attempt
                    for attempt in self._recovery_repository.list_attempts(root_analysis_run_id)
                    if attempt.directive.proposal_id == diagnostic.proposal_id
                    and attempt.status != RecoveryAttemptStatus.COMPLETED
                ]
                directive_or_outcome = (
                    resumable[0].directive
                    if len(resumable) == 1
                    else self.derive_directive(
                        root_analysis_run_id,
                        diagnostic.proposal_id,
                        diagnostic.issue_codes,
                    )
                )
                outcome = (
                    directive_or_outcome
                    if isinstance(directive_or_outcome, RecoveryOutcomeV1)
                    else self._execute_directive(directive_or_outcome, real_llm_requested)
                )
            outcomes.append(outcome)
        return outcomes

    def _execute_directive(
        self,
        directive: RecoveryDirectiveV1,
        real_llm_requested: bool,
    ) -> RecoveryOutcomeV1:
        attempt = RecoveryAttemptV1(
            attempt_id=stable_id("recovery-attempt-record", directive.idempotency_key),
            idempotency_key=directive.idempotency_key,
            directive=directive,
            status=RecoveryAttemptStatus.RESERVED,
            original_gate2_issue_codes=directive.issue_codes,
        )
        stored, created = self._recovery_repository.reserve_attempt(attempt)
        if stored.status == RecoveryAttemptStatus.COMPLETED:
            assert stored.outcome is not None
            return stored.outcome
        if stored.status == RecoveryAttemptStatus.RUNNING:
            return self._outcome(
                directive.root_analysis_run_id,
                directive.proposal_id,
                RecoveryOutcomeStatus.IN_PROGRESS,
                directive.issue_codes,
                attempt_id=stored.attempt_id,
            )
        if stored.status == RecoveryAttemptStatus.RESERVED:
            if not created or self._rerun_window is None:
                return self._outcome(
                    directive.root_analysis_run_id,
                    directive.proposal_id,
                    RecoveryOutcomeStatus.IN_PROGRESS,
                    directive.issue_codes,
                    attempt_id=stored.attempt_id,
                )
            running = stored.model_copy(
                update={
                    "status": RecoveryAttemptStatus.RUNNING,
                    "started_at": datetime.now(UTC),
                    "budget_usage": stored.budget_usage.model_copy(
                        update={
                            "proposal_attempts": 1,
                            "window_attempts": 1,
                            "root_run_attempts": 1,
                            "provider_requests": stored.budget_usage.provider_requests + 1,
                        }
                    ),
                }
            )
            stored = self._recovery_repository.save_attempt_transition(running)
            agent_run = self._rerun_window(directive, stored.attempt_id)
            if agent_run is None or agent_run.status != AgentRunStatus.SUCCEEDED:
                reviewing = stored.model_copy(
                    update={
                        "status": RecoveryAttemptStatus.REVIEWING,
                        "budget_usage": self._usage_after_provider(stored, agent_run),
                    }
                )
                stored = self._recovery_repository.save_attempt_transition(reviewing)
                return self._complete(stored, RecoveryOutcomeStatus.FAILED)
            provider_succeeded = stored.model_copy(
                update={
                    "status": RecoveryAttemptStatus.PROVIDER_SUCCEEDED,
                    "new_agent_run_id": agent_run.agent_run_id,
                    "new_proposal_ids": list(agent_run.output_proposal_ids),
                    "budget_usage": self._usage_after_provider(stored, agent_run),
                }
            )
            stored = self._recovery_repository.save_attempt_transition(provider_succeeded)
        if stored.status == RecoveryAttemptStatus.PROVIDER_SUCCEEDED:
            stored = self._recovery_repository.save_attempt_transition(
                stored.model_copy(update={"status": RecoveryAttemptStatus.REVIEWING})
            )
        return self._review_existing(stored)

    @staticmethod
    def _usage_after_provider(
        attempt: RecoveryAttemptV1, agent_run: AgentRunV1 | None
    ) -> RecoveryBudgetUsageV1:
        """Persist provider-visible usage without storing provider output or prompts."""

        elapsed = 1
        if attempt.started_at is not None:
            elapsed = max(1, int((datetime.now(UTC) - attempt.started_at).total_seconds()))
        latency_ms = (
            agent_run.provider_result.latency_ms
            if agent_run is not None and agent_run.provider_result is not None
            else None
        )
        if latency_ms is not None:
            elapsed = max(elapsed, (latency_ms + 999) // 1000)
        total_tokens = 0
        if agent_run is not None:
            usage = agent_run.payload.get("provider_usage")
            if isinstance(usage, dict) and isinstance(usage.get("total_tokens"), int):
                total_tokens = max(0, usage["total_tokens"])
            elif agent_run.provider_result is not None:
                # Mock and legacy providers do not expose token telemetry.  Retain a
                # deterministic, conservative accounting unit instead of resetting
                # the budget during resume; real adapters may supply provider_usage.
                output = agent_run.provider_result.structured_output
                if output is not None:
                    total_tokens = max(1, (len(json.dumps(output, sort_keys=True)) + 3) // 4)
        return attempt.budget_usage.model_copy(
            update={
                "total_tokens": total_tokens,
                "elapsed_seconds": elapsed,
            }
        )

    def _review_existing(self, attempt: RecoveryAttemptV1) -> RecoveryOutcomeV1:
        if attempt.new_agent_run_id is None:
            return self._outcome(
                attempt.directive.root_analysis_run_id,
                attempt.directive.proposal_id,
                RecoveryOutcomeStatus.IN_PROGRESS,
                attempt.directive.issue_codes,
                attempt_id=attempt.attempt_id,
            )
        if self._get_agent_run is None:
            return self._complete(attempt, RecoveryOutcomeStatus.FAILED)
        agent_run = self._get_agent_run(attempt.new_agent_run_id)
        if not isinstance(agent_run, AgentRunV1):
            return self._complete(attempt, RecoveryOutcomeStatus.FAILED)
        window = self._locked_recovery_window(attempt.directive, agent_run.agent_run_id)
        sources = proposal_sources_for_window(agent_run, window)
        aggregate = aggregate_narrative_analysis(
            sources, analysis_run_id=attempt.directive.root_analysis_run_id
        )
        chunks = [
            self._source_repository.get_chunk(chunk_id)
            for chunk_id in attempt.directive.ordered_source_chunk_ids
        ]
        if any(chunk is None for chunk in chunks):
            return self._complete(attempt, RecoveryOutcomeStatus.FAILED)
        selected_chunks = tuple(chunk for chunk in chunks if chunk is not None)
        review_input = build_review_gate2_input(
            result=aggregate,
            project_id=attempt.directive.project_id,
            document_id=attempt.directive.document_id,
            allowed_chunk_ids=attempt.directive.approved_source_chunk_ids,
        )
        review_result = self._review_service.review(
            review_input,
            ReviewGate2ServiceContext(
                source_chunks=selected_chunks,
                known_agent_run_ids=frozenset({agent_run.agent_run_id}),
                agent_run_analysis_run_ids={
                    agent_run.agent_run_id: attempt.directive.root_analysis_run_id
                },
            ),
        )
        root = self._analysis_repository.get_run(attempt.directive.root_analysis_run_id)
        if root is None:
            return self._complete(attempt, RecoveryOutcomeStatus.FAILED)
        route = NarrativeAnalysisReviewCoordinator(
            source_repository=cast("SourceRepository", self._source_repository),
            analysis_repository=cast("NarrativeAnalysisRepository", self._analysis_repository),
        )._route_for(
            run=root,
            review_result=review_result,
            windows=[window],
            review_input=review_input,
        )
        status = {
            ReviewGate2RoutingDecision.APPROVED: RecoveryOutcomeStatus.APPROVED,
            ReviewGate2RoutingDecision.REJECTED: RecoveryOutcomeStatus.REJECTED,
            ReviewGate2RoutingDecision.NEEDS_HUMAN_REVIEW: RecoveryOutcomeStatus.NEEDS_HUMAN_REVIEW,
            ReviewGate2RoutingDecision.FAILED: RecoveryOutcomeStatus.FAILED,
        }[route.decision]
        return self._complete(attempt, status, review_result=review_result, route=route)

    @staticmethod
    def _locked_recovery_window(
        directive: RecoveryDirectiveV1, agent_run_id: str
    ) -> NarrativeAnalysisWindowV1:
        return NarrativeAnalysisWindowV1(
            analysis_window_id=directive.original_window_id,
            analysis_run_id=directive.root_analysis_run_id,
            mode=directive.mode,
            window_index=0,
            chunk_ids=directive.ordered_source_chunk_ids,
            owned_chunk_ids=directive.ordered_source_chunk_ids,
            status="SUCCEEDED",
            agent_run_id=agent_run_id,
            effective_max_chars_per_chunk=directive.max_chars_per_chunk,
        )

    def _complete(
        self,
        attempt: RecoveryAttemptV1,
        status: RecoveryOutcomeStatus,
        *,
        review_result: ReviewGate2ResultV1 | None = None,
        route: NarrativeAnalysisReviewRouteV1 | None = None,
    ) -> RecoveryOutcomeV1:
        outcome = self._outcome(
            attempt.directive.root_analysis_run_id,
            attempt.directive.proposal_id,
            status,
            attempt.directive.issue_codes,
            attempt_id=attempt.attempt_id,
            route_decision=str(route.decision) if route is not None else None,
            budget_usage=attempt.budget_usage,
        )
        completed = attempt.model_copy(
            update={
                "status": RecoveryAttemptStatus.COMPLETED,
                "fresh_review_result": review_result,
                "fresh_route": route,
                "outcome": outcome,
                "completed_at": datetime.now(UTC),
            }
        )
        self._recovery_repository.save_attempt_transition(completed)
        return outcome

    @staticmethod
    def _outcome(
        root_analysis_run_id: str,
        proposal_id: str,
        status: RecoveryOutcomeStatus,
        issue_codes: list[ReviewIssueCode] | None = None,
        budget_usage: RecoveryBudgetUsageV1 | None = None,
        attempt_id: str | None = None,
        route_decision: str | None = None,
    ) -> RecoveryOutcomeV1:
        return RecoveryOutcomeV1(
            outcome_id=stable_id(
                "recovery-outcome", f"{root_analysis_run_id}:{proposal_id}:{status}"
            ),
            root_analysis_run_id=root_analysis_run_id,
            proposal_id=proposal_id,
            attempt_id=attempt_id,
            status=status,
            safe_issue_codes=issue_codes or [],
            route_decision=route_decision,
            budget_usage=budget_usage or RecoveryBudgetUsageV1(),
            created_at=datetime.now(UTC),
        )
