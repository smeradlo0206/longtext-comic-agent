"""Production StoryBible execution and recovery never call a real provider."""

from datetime import UTC, datetime
from threading import Lock, Thread
from typing import Any

import pytest
from pydantic import SecretStr

from comic_agent.config import Settings
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ConflictV1,
    HumanApprovedStoryBibleProductionLineageV1,
    ProfileUpdateProposalV1,
    StoryBibleCanonicalSnapshotV1,
    StoryBibleCuratorProposalV1,
    StoryBibleProductionAuthorizationKind,
    StoryBibleProductionAuthorizationPolicy,
    StoryBibleProductionContextV1,
    StoryBibleProductionFailureStage,
    StoryBibleProductionInputV1,
    StoryBibleProductionRunStatus,
    StoryBibleProductionRunV1,
    StoryEntityProfileV1,
)
from comic_agent.schemas.workflow import AgentRunStatus, AgentRunV1
from comic_agent.services.id_service import checksum_text, stable_id
from comic_agent.services.storybible_curator_input_adapter import (
    StoryBibleCuratorInputAdapter,
)
from comic_agent.services.storybible_production_context import (
    PreparedStoryBibleProduction,
    canonical_storybible_snapshot_hash,
)
from comic_agent.services.storybible_production_coordinator import (
    StoryBibleProductionCoordinator,
    StoryBibleProductionExecutionError,
    StoryBibleProductionRecoveryRequiredError,
)
from comic_agent.services.storybible_production_output_normalizer import (
    StoryBibleProductionOutputNormalizer,
)


def _chunk(index: int = 1) -> SourceChunkV1:
    text = f"Xia Ming arrived {index}."
    return SourceChunkV1(
        chunk_id=f"chunk-{index}",
        document_id="document-1",
        chapter_id="chapter-1",
        project_id="project-1",
        order=index - 1,
        text=text,
        checksum=checksum_text(text),
    )


def _prepared(chunk_count: int = 1) -> PreparedStoryBibleProduction:
    chunks = [_chunk(index) for index in range(1, chunk_count + 1)]
    evidence = [EvidenceRefV1(chunk_id=chunk.chunk_id, quote_text=chunk.text) for chunk in chunks]
    snapshot = StoryBibleCanonicalSnapshotV1(project_id="project-1")
    snapshot_hash = canonical_storybible_snapshot_hash(snapshot)
    context = StoryBibleProductionContextV1(
        project_id="project-1",
        gate2_approved_bundle_id="gate2-1",
        narrative_analysis_run_id="analysis-1",
        approved_timeline_bundle_id="timeline-1",
        timeline_run_id="timeline-run-1",
        trusted_event_ids=[],
        trusted_event_order=[],
        trusted_evidence_refs=evidence,
        source_chunk_ids=[chunk.chunk_id for chunk in chunks],
        source_chunks=chunks,
        canonical_snapshot=snapshot,
        canonical_storybible_snapshot_hash=snapshot_hash,
    )
    production_input = StoryBibleProductionInputV1(
        project_id="project-1",
        gate2_approved_bundle_id="gate2-1",
        approved_timeline_bundle_id="timeline-1",
        canonical_storybible_snapshot_hash=snapshot_hash,
    )
    now = datetime.now(UTC)
    run = StoryBibleProductionRunV1(
        run_id="storybible-run-1",
        project_id="project-1",
        gate2_approved_bundle_id="gate2-1",
        approved_timeline_bundle_id="timeline-1",
        canonical_storybible_snapshot_hash=snapshot_hash,
        input_hash="input-1",
        model_identity="model-1",
        status=StoryBibleProductionRunStatus.RESERVED,
        created_at=now,
        updated_at=now,
    )
    return PreparedStoryBibleProduction(production_input=production_input, context=context, run=run)


def _proposal(*, conflict: bool = False) -> StoryBibleCuratorProposalV1:
    evidence = [EvidenceRefV1(chunk_id="chunk-1", quote_text="Xia Ming arrived 1.")]
    profile = StoryEntityProfileV1(
        profile_id="local-profile",
        project_id="project-1",
        entity_kind="PERSON",
        canonical_name="Xia Ming",
        evidence_refs=evidence,
    )
    update = ProfileUpdateProposalV1(
        update_id="local-update",
        project_id="project-1",
        profile=profile,
        evidence_refs=evidence,
    )
    conflicts = (
        [
            ConflictV1(
                conflict_id="local-conflict",
                project_id="project-1",
                category="IDENTITY",
                summary="Needs review.",
                affected_update_ids=["local-update"],
                evidence_refs=evidence,
            )
        ]
        if conflict
        else []
    )
    return StoryBibleCuratorProposalV1(
        proposal_id="local-proposal",
        project_id="project-1",
        commit_plan=CommitPlanV1(
            commit_plan_id="local-plan",
            project_id="project-1",
            source_proposal_id="local-proposal",
            content_hash="untrusted",
            updates=[update],
            evidence_refs=evidence,
        ),
        conflicts=conflicts,
        evidence_refs=evidence,
        confidence=0.8,
    )


class _Builder:
    def __init__(self, prepared: PreparedStoryBibleProduction) -> None:
        self.prepared = prepared

    def build_and_reserve(self, **_: Any) -> PreparedStoryBibleProduction:
        self.prepared = self.prepared.__class__(
            production_input=self.prepared.production_input,
            context=self.prepared.context,
            run=self.prepared.run.model_copy(deep=True),
        )
        return self.prepared


class _Runs:
    def __init__(self, run: StoryBibleProductionRunV1) -> None:
        self.run = run
        self.lock = Lock()
        self.fail_success_once = False

    def get_run(self, _: str) -> StoryBibleProductionRunV1:
        return self.run.model_copy(deep=True)

    def claim_execution(self, _: str) -> bool:
        with self.lock:
            if self.run.status != StoryBibleProductionRunStatus.RESERVED:
                return False
            self.run = self.run.model_copy(
                update={
                    "status": StoryBibleProductionRunStatus.RUNNING,
                    "provider_request_count": 1,
                    "updated_at": datetime.now(UTC),
                }
            )
            return True

    def save_success(self, _: str, *, curator_proposal: Any, agent_run_id: str) -> Any:
        if self.fail_success_once:
            self.fail_success_once = False
            raise RuntimeError("checkpoint unavailable")
        self.run = self.run.model_copy(
            update={
                "status": StoryBibleProductionRunStatus.SUCCEEDED,
                "curator_proposal": curator_proposal,
                "agent_run_id": agent_run_id,
            }
        )
        return self.run

    def save_failure(
        self,
        _: str,
        *,
        error_message: str,
        failure_stage: StoryBibleProductionFailureStage | None = None,
        agent_run_id: str | None = None,
    ) -> StoryBibleProductionRunV1:
        self.run = self.run.model_copy(
            update={
                "status": StoryBibleProductionRunStatus.FAILED,
                "error_message": error_message,
                "failure_stage": failure_stage,
                "agent_run_id": agent_run_id,
            }
        )
        return self.run


class _AgentRuns:
    def __init__(self) -> None:
        self.values: dict[str, AgentRunV1] = {}
        self.fail_save = False

    def save_agent_run(self, value: AgentRunV1) -> AgentRunV1:
        if self.fail_save:
            raise RuntimeError("agent audit unavailable")
        previous = self.values.get(value.agent_run_id)
        if previous is not None and previous != value:
            raise ValueError("AgentRun conflict")
        self.values[value.agent_run_id] = value
        return value

    def get_agent_run(self, value: str) -> AgentRunV1 | None:
        return self.values.get(value)


class _Curator:
    class spec:
        max_context_chunks = 3

    def __init__(self, result: Any = None) -> None:
        self.result = result or _proposal()
        self.calls = 0
        self.lock = Lock()

    def run(self, context: Any, chunk_texts: Any) -> StoryBibleCuratorProposalV1:
        with self.lock:
            self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _LineageRecordingAdapter(StoryBibleCuratorInputAdapter):
    def __init__(self) -> None:
        self.lineage = None
        self.strict_calls = 0
        self.legacy_calls = 0
        self._inside_strict = False

    def adapt_with_lineage(self, production: Any, *, lineage: Any, **kwargs: Any) -> Any:
        self.strict_calls += 1
        self.lineage = lineage
        self._inside_strict = True
        try:
            return super().adapt_with_lineage(production, lineage=lineage, **kwargs)
        finally:
            self._inside_strict = False

    def adapt(self, production: Any, **kwargs: Any) -> Any:
        if not self._inside_strict:
            self.legacy_calls += 1
        return super().adapt(production, **kwargs)


def _coordinator(
    prepared: PreparedStoryBibleProduction | None = None,
    *,
    curator: _Curator | None = None,
    authorization_policy: StoryBibleProductionAuthorizationPolicy = (
        StoryBibleProductionAuthorizationPolicy.LEGACY_COMPAT
    ),
    allow_legacy_compat: bool | None = None,
    input_adapter: StoryBibleCuratorInputAdapter | None = None,
) -> tuple[StoryBibleProductionCoordinator, _Builder, _Runs, _AgentRuns, _Curator]:
    prepared = prepared or _prepared()
    builder = _Builder(prepared)
    runs = _Runs(prepared.run)
    agents = _AgentRuns()
    curator = curator or _Curator()
    coordinator = StoryBibleProductionCoordinator(
        input_builder=builder,
        run_repository=runs,  # type: ignore[arg-type]
        curator=curator,  # type: ignore[arg-type]
        output_normalizer=StoryBibleProductionOutputNormalizer(),
        agent_run_repository=agents,  # type: ignore[arg-type]
        settings=Settings(_env_file=None, enable_real_llm=True),
        authorization_policy=authorization_policy,
        input_adapter=input_adapter,
        allow_legacy_compat=(
            authorization_policy == StoryBibleProductionAuthorizationPolicy.LEGACY_COMPAT
            if allow_legacy_compat is None
            else allow_legacy_compat
        ),
    )
    return coordinator, builder, runs, agents, curator


def _human_prepared(
    *, lineage: HumanApprovedStoryBibleProductionLineageV1 | None
) -> PreparedStoryBibleProduction:
    legacy = _prepared()
    context = legacy.context.model_copy(
        update={
            "gate2_approved_bundle_id": None,
            "approved_timeline_bundle_id": None,
            "human_review_id": "review-1",
            "production_dossier_id": "dossier-1",
            "narrative_execution_bundle_id": "narrative-1",
            "timeline_review_material_id": "timeline-material-1",
            "authorization_kind": StoryBibleProductionAuthorizationKind.HUMAN_APPROVED,
            "human_approved_lineage": lineage,
        }
    )
    production_input = legacy.production_input.model_copy(
        update={
            "gate2_approved_bundle_id": None,
            "approved_timeline_bundle_id": None,
            "human_review_id": "review-1",
            "production_dossier_id": "dossier-1",
            "narrative_execution_bundle_id": "narrative-1",
            "timeline_review_material_id": "timeline-material-1",
            "authorization_kind": StoryBibleProductionAuthorizationKind.HUMAN_APPROVED,
            "human_approved_lineage": lineage,
        }
    )
    run = legacy.run.model_copy(
        update={
            "gate2_approved_bundle_id": None,
            "approved_timeline_bundle_id": None,
            "human_review_id": "review-1",
            "production_dossier_id": "dossier-1",
            "narrative_execution_bundle_id": "narrative-1",
            "timeline_review_material_id": "timeline-material-1",
            "authorization_kind": StoryBibleProductionAuthorizationKind.HUMAN_APPROVED,
            "human_approved_lineage": lineage,
        }
    )
    return PreparedStoryBibleProduction(production_input, context, run)


def _human_lineage() -> HumanApprovedStoryBibleProductionLineageV1:
    return HumanApprovedStoryBibleProductionLineageV1(
        human_review_id="review-1",
        dossier_id="dossier-1",
        narrative_execution_bundle_id="narrative-1",
        timeline_review_material_id="timeline-material-1",
    )


def _run(coordinator: StoryBibleProductionCoordinator) -> StoryBibleProductionRunV1:
    return coordinator.run(
        project_id="project-1",
        gate2_approved_bundle_id="gate2-1",
        approved_timeline_bundle_id="timeline-1",
        model_identity="model-1",
        real_llm_requested=True,
    )


def test_default_policy_refuses_legacy_v1_before_curator_execution() -> None:
    coordinator, _, runs, _, curator = _coordinator(
        authorization_policy=StoryBibleProductionAuthorizationPolicy.HUMAN_APPROVED_ONLY
    )

    result = _run(coordinator)

    assert result.code == "PRODUCTION_AUTHORIZATION_REQUIRED"
    assert curator.calls == 0
    assert runs.run.status == StoryBibleProductionRunStatus.RESERVED


def test_human_only_run_prepared_requires_human_review_and_dossier_ids() -> None:
    legacy = _prepared()
    malformed_input = legacy.production_input.model_copy(
        update={
            "authorization_kind": StoryBibleProductionAuthorizationKind.HUMAN_APPROVED,
            "gate2_approved_bundle_id": None,
            "approved_timeline_bundle_id": None,
            "human_review_id": None,
            "production_dossier_id": None,
        }
    )
    malformed = legacy.__class__(malformed_input, legacy.context, legacy.run)
    coordinator, _, _, _, curator = _coordinator(
        malformed,
        authorization_policy=StoryBibleProductionAuthorizationPolicy.HUMAN_APPROVED_ONLY,
    )

    result = coordinator.run_prepared(
        prepared=malformed,
        model_identity="model-1",
        real_llm_requested=True,
    )

    assert result.code == "PRODUCTION_AUTHORIZATION_REQUIRED"
    assert curator.calls == 0


def test_human_approved_runtime_wiring_uses_strict_curator_lineage_adapter() -> None:
    adapter = _LineageRecordingAdapter()
    prepared = _human_prepared(lineage=_human_lineage())
    coordinator, _, _, _, curator = _coordinator(
        prepared,
        authorization_policy=StoryBibleProductionAuthorizationPolicy.HUMAN_APPROVED_ONLY,
        input_adapter=adapter,
    )

    result = coordinator.run_prepared(
        prepared=prepared,
        model_identity="model-1",
        real_llm_requested=True,
    )

    assert result.status == StoryBibleProductionRunStatus.SUCCEEDED
    assert adapter.strict_calls == 1
    assert adapter.legacy_calls == 0
    assert adapter.lineage is not None
    assert adapter.lineage.production_run_id == prepared.run.run_id
    assert adapter.lineage.dossier_id == "dossier-1"
    assert adapter.lineage.human_review_id == "review-1"
    assert adapter.lineage.approved_timeline_bundle_id is None
    assert (
        adapter.lineage.canonical_snapshot_hash
        == prepared.context.canonical_storybible_snapshot_hash
    )
    assert curator.calls == 1


def test_human_approved_runtime_wiring_rejects_missing_lineage_without_fallback() -> None:
    adapter = _LineageRecordingAdapter()
    prepared = _human_prepared(lineage=None)
    coordinator, _, runs, _, curator = _coordinator(
        prepared,
        authorization_policy=StoryBibleProductionAuthorizationPolicy.HUMAN_APPROVED_ONLY,
        input_adapter=adapter,
    )

    with pytest.raises(StoryBibleProductionExecutionError) as caught:
        coordinator.run_prepared(
            prepared=prepared,
            model_identity="model-1",
            real_llm_requested=True,
        )

    assert caught.value.stage == StoryBibleProductionFailureStage.INPUT_ADAPTATION
    assert runs.run.status == StoryBibleProductionRunStatus.FAILED
    assert adapter.strict_calls == adapter.legacy_calls == 0
    assert curator.calls == 0


def test_human_approved_runtime_wiring_rejects_inconsistent_persisted_lineage() -> None:
    adapter = _LineageRecordingAdapter()
    inconsistent = _human_lineage().model_copy(update={"dossier_id": "other-dossier"})
    prepared = _human_prepared(lineage=inconsistent)
    coordinator, _, runs, _, curator = _coordinator(
        prepared,
        authorization_policy=StoryBibleProductionAuthorizationPolicy.HUMAN_APPROVED_ONLY,
        input_adapter=adapter,
    )

    with pytest.raises(StoryBibleProductionExecutionError) as caught:
        coordinator.run_prepared(
            prepared=prepared,
            model_identity="model-1",
            real_llm_requested=True,
        )

    assert caught.value.stage == StoryBibleProductionFailureStage.INPUT_ADAPTATION
    assert runs.run.status == StoryBibleProductionRunStatus.FAILED
    assert adapter.strict_calls == adapter.legacy_calls == 0
    assert curator.calls == 0


def test_legacy_compat_requires_explicit_test_or_maintenance_tool_opt_in() -> None:
    with pytest.raises(ValueError, match="explicit test or maintenance-tool opt-in"):
        _coordinator(allow_legacy_compat=False)


def test_success_replay_and_business_conflict_are_successful() -> None:
    coordinator, builder, runs, agents, curator = _coordinator(
        curator=_Curator(_proposal(conflict=True))
    )
    first = _run(coordinator)
    builder.prepared = builder.prepared.__class__(
        builder.prepared.production_input, builder.prepared.context, first
    )
    second = _run(coordinator)

    assert first.status == second.status == StoryBibleProductionRunStatus.SUCCEEDED
    assert first.curator_proposal is not None and first.curator_proposal.conflicts
    assert curator.calls == 1
    assert runs.run.provider_request_count == 1
    assert len(agents.values) == 1
    checkpoint = next(iter(agents.values.values()))
    assert checkpoint.agent_run_id == stable_id("storybible-agent-run", first.run_id)
    assert checkpoint.provider_result is not None
    assert checkpoint.payload["normalized_curator_proposal"] == first.curator_proposal.model_dump(
        mode="json"
    )


@pytest.mark.parametrize(
    ("error", "stage"),
    [
        (TimeoutError("provider timeout"), StoryBibleProductionFailureStage.PROVIDER),
        (
            pytest.raises,
            StoryBibleProductionFailureStage.SCHEMA,
        ),
    ],
)
def test_provider_and_schema_failures_are_terminal(error: Any, stage: Any) -> None:
    if error is pytest.raises:
        try:
            StoryBibleCuratorProposalV1.model_validate({})
        except Exception as exc:
            error = exc
    coordinator, _, runs, agents, curator = _coordinator(curator=_Curator(error))
    result = _run(coordinator)

    assert result.status == StoryBibleProductionRunStatus.FAILED
    assert result.failure_stage == stage
    assert result.curator_proposal is None
    assert curator.calls == 1
    assert next(iter(agents.values.values())).status == AgentRunStatus.FAILED
    assert runs.run.provider_request_count == 1


def test_server_owned_curator_project_id_is_rewritten_before_normalization() -> None:
    bad = _proposal().model_copy(update={"project_id": "wrong-project"})
    coordinator, _, _, agents, _ = _coordinator(curator=_Curator(bad))
    result = _run(coordinator)

    assert result.status == StoryBibleProductionRunStatus.SUCCEEDED
    assert result.curator_proposal is not None
    assert result.curator_proposal.project_id == "project-1"
    assert next(iter(agents.values.values())).status == AgentRunStatus.SUCCEEDED


def test_chunk_budget_fails_before_claim_without_truncation() -> None:
    coordinator, _, runs, agents, curator = _coordinator(_prepared(4))
    with pytest.raises(StoryBibleProductionExecutionError) as caught:
        _run(coordinator)

    assert caught.value.stage == StoryBibleProductionFailureStage.CONTEXT_BUDGET
    assert runs.run.status == StoryBibleProductionRunStatus.RESERVED
    assert runs.run.provider_request_count == 0
    assert curator.calls == 0
    assert not agents.values


def test_running_success_and_failure_checkpoints_repair_without_provider() -> None:
    coordinator, builder, runs, agents, curator = _coordinator()
    runs.claim_execution(runs.run.run_id)
    run = runs.run
    normalized = StoryBibleProductionOutputNormalizer().normalize(
        _proposal(), context=builder.prepared.context, run=run
    )
    checkpoint = coordinator._success_agent_run(  # noqa: SLF001
        run, normalized, run.updated_at, builder.prepared.context.source_chunks
    )
    agents.save_agent_run(checkpoint)
    result = _run(coordinator)
    assert result.status == StoryBibleProductionRunStatus.SUCCEEDED
    assert curator.calls == 0

    coordinator2, builder2, runs2, agents2, curator2 = _coordinator()
    runs2.claim_execution(runs2.run.run_id)
    failed = coordinator2._failed_agent_run(  # noqa: SLF001
        runs2.run,
        StoryBibleProductionFailureStage.PROVIDER,
        "safe failure",
        runs2.run.updated_at,
        builder2.prepared.context.source_chunks,
    )
    agents2.save_agent_run(failed)
    result2 = _run(coordinator2)
    assert result2.status == StoryBibleProductionRunStatus.FAILED
    assert result2.agent_run_id == failed.agent_run_id
    assert curator2.calls == 0


def test_running_without_checkpoint_requires_recovery_and_failed_does_not_retry() -> None:
    coordinator, builder, runs, _, curator = _coordinator()
    runs.claim_execution(runs.run.run_id)
    with pytest.raises(StoryBibleProductionRecoveryRequiredError):
        _run(coordinator)
    assert curator.calls == 0

    runs.save_failure(
        runs.run.run_id,
        error_message="safe failure",
        failure_stage=StoryBibleProductionFailureStage.PROVIDER,
    )
    builder.prepared = builder.prepared.__class__(
        builder.prepared.production_input, builder.prepared.context, runs.run
    )
    assert _run(coordinator).status == StoryBibleProductionRunStatus.FAILED
    assert curator.calls == 0


def test_success_checkpoint_repairs_after_final_run_save_failure() -> None:
    coordinator, builder, runs, agents, curator = _coordinator()
    runs.fail_success_once = True
    with pytest.raises(StoryBibleProductionExecutionError) as caught:
        _run(coordinator)
    assert caught.value.stage == StoryBibleProductionFailureStage.RUN_CHECKPOINT_PERSISTENCE
    assert runs.run.status == StoryBibleProductionRunStatus.RUNNING
    assert len(agents.values) == 1

    builder.prepared = builder.prepared.__class__(
        builder.prepared.production_input, builder.prepared.context, runs.run
    )
    assert _run(coordinator).status == StoryBibleProductionRunStatus.SUCCEEDED
    assert curator.calls == 1


def test_agent_run_persistence_failure_never_reports_success() -> None:
    coordinator, _, runs, agents, curator = _coordinator()
    agents.fail_save = True
    with pytest.raises(StoryBibleProductionExecutionError) as caught:
        _run(coordinator)
    assert caught.value.stage == StoryBibleProductionFailureStage.AGENT_RUN_PERSISTENCE
    assert runs.run.status == StoryBibleProductionRunStatus.FAILED
    assert curator.calls == 1


def test_snapshot_mismatch_and_llm_guards_prevent_claim() -> None:
    prepared = _prepared()
    prepared.context.canonical_storybible_snapshot_hash = "changed"
    coordinator, _, runs, _, curator = _coordinator(prepared)
    with pytest.raises(StoryBibleProductionExecutionError) as caught:
        _run(coordinator)
    assert caught.value.stage == StoryBibleProductionFailureStage.INPUT_ADAPTATION
    assert runs.run.provider_request_count == curator.calls == 0

    coordinator._settings.enable_real_llm = False  # noqa: SLF001
    with pytest.raises(StoryBibleProductionExecutionError):
        _run(coordinator)
    assert curator.calls == 0


def test_concurrent_duplicate_has_one_claim_and_one_curator_call() -> None:
    coordinator, builder, runs, agents, curator = _coordinator()
    results: list[StoryBibleProductionRunV1] = []
    errors: list[Exception] = []

    def execute() -> None:
        try:
            results.append(_run(coordinator))
        except StoryBibleProductionRecoveryRequiredError as exc:
            errors.append(exc)

    threads = [Thread(target=execute), Thread(target=execute)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    builder.prepared = builder.prepared.__class__(
        builder.prepared.production_input, builder.prepared.context, runs.run
    )

    assert curator.calls == 1
    assert runs.run.provider_request_count == 1
    assert len(agents.values) == 1
    assert results or errors
    assert _run(coordinator).status == StoryBibleProductionRunStatus.SUCCEEDED


def test_failure_messages_redact_configured_secret_and_source_text() -> None:
    secret = "sk-secret-value"
    error = RuntimeError(f"Authorization: Bearer {secret}; API key {secret}; Xia Ming arrived 1.")
    coordinator, _, _, agents, _ = _coordinator(curator=_Curator(error))
    coordinator._settings.llm_api_key = SecretStr(secret)  # noqa: SLF001
    result = _run(coordinator)
    serialized = result.model_dump_json() + next(iter(agents.values.values())).model_dump_json()
    assert secret not in serialized
    assert "Xia Ming arrived 1." not in serialized


def test_curator_adapter_maps_snapshot_and_trusted_chunks() -> None:
    prepared = _prepared()
    adapted = StoryBibleCuratorInputAdapter().adapt(prepared.context)
    assert adapted.context.entity_proposals == prepared.context.approved_entities
    assert adapted.context.event_proposals == prepared.context.approved_events
    assert adapted.context.state_change_proposals == prepared.context.approved_state_changes
    assert adapted.context.temporal_relation_proposals == (
        prepared.context.approved_temporal_relations
    )
    assert adapted.context.profiles == prepared.context.canonical_snapshot.profiles
    assert adapted.context.source_chunk_ids == prepared.context.source_chunk_ids
    assert adapted.chunk_texts == {"chunk-1": "Xia Ming arrived 1."}
