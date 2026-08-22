"""Persistence and legal state claims for production StoryBible execution."""

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from comic_agent.database.models import (
    NarrativeAnalysisRunModel,
    StoryBibleProductionRunModel,
    TimelineGate3RunModel,
)
from comic_agent.schemas.review import ApprovedProposalBundleV1
from comic_agent.schemas.storybible import (
    StoryBibleCuratorProposalV1,
    StoryBibleProductionFailureStage,
    StoryBibleProductionInputV1,
    StoryBibleProductionRunStatus,
    StoryBibleProductionRunV1,
)
from comic_agent.schemas.timeline import ApprovedTimelineBundleV1, TimelineGate3RunStatus
from comic_agent.services.storybible_production_identity import (
    storybible_production_input_hash,
    storybible_production_run_id,
)


class StoryBibleProductionRunRepository:
    """Reserve and checkpoint exactly one execution per canonical production input."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def reserve_run(
        self,
        production_input: StoryBibleProductionInputV1,
        *,
        model_identity: str,
    ) -> StoryBibleProductionRunV1:
        """Validate approved lineage and create-or-return its deterministic run."""

        self.validate_approved_lineage(production_input)
        input_hash = storybible_production_input_hash(
            production_input, model_identity=model_identity
        )
        existing = self.get_by_input_hash(production_input.project_id, input_hash)
        if existing is not None:
            return existing
        now = datetime.now(UTC)
        run = StoryBibleProductionRunV1(
            run_id=storybible_production_run_id(input_hash),
            project_id=production_input.project_id,
            gate2_approved_bundle_id=production_input.gate2_approved_bundle_id,
            approved_timeline_bundle_id=production_input.approved_timeline_bundle_id,
            canonical_storybible_snapshot_hash=(
                production_input.canonical_storybible_snapshot_hash
            ),
            input_hash=input_hash,
            model_identity=model_identity,
            status=StoryBibleProductionRunStatus.RESERVED,
            created_at=now,
            updated_at=now,
        )
        try:
            self._session.add(
                StoryBibleProductionRunModel(
                    run_id=run.run_id,
                    project_id=run.project_id,
                    gate2_approved_bundle_id=run.gate2_approved_bundle_id,
                    approved_timeline_bundle_id=run.approved_timeline_bundle_id,
                    input_hash=run.input_hash,
                    status=str(run.status),
                    payload=run.model_dump(mode="json"),
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
            )
            self._session.commit()
            return run
        except IntegrityError:
            self._session.rollback()
            winner = self.get_by_input_hash(production_input.project_id, input_hash)
            if winner is None:
                raise
            return winner

    def get_run(self, run_id: str) -> StoryBibleProductionRunV1 | None:
        row = self._session.get(StoryBibleProductionRunModel, run_id)
        return StoryBibleProductionRunV1.model_validate(row.payload) if row else None

    def get_by_input_hash(
        self, project_id: str, input_hash: str
    ) -> StoryBibleProductionRunV1 | None:
        row = self._session.scalar(
            select(StoryBibleProductionRunModel).where(
                StoryBibleProductionRunModel.project_id == project_id,
                StoryBibleProductionRunModel.input_hash == input_hash,
            )
        )
        return StoryBibleProductionRunV1.model_validate(row.payload) if row else None

    def mark_running(self, run_id: str) -> StoryBibleProductionRunV1:
        """Atomically claim the single provider attempt for a reserved run."""

        if not self.claim_execution(run_id):
            run = self._require_run(run_id)
            raise ValueError(f"illegal StoryBible run transition: {run.status} -> RUNNING")
        return self._require_run(run_id)

    def claim_execution(self, run_id: str) -> bool:
        """Atomically claim RESERVED -> RUNNING; only the winner may call the Curator."""

        run = self._require_run(run_id)
        if run.status != StoryBibleProductionRunStatus.RESERVED:
            return False
        updated = run.model_copy(
            update={
                "status": StoryBibleProductionRunStatus.RUNNING,
                "provider_request_count": 1,
                "updated_at": datetime.now(UTC),
            }
        )
        result = self._session.execute(
            update(StoryBibleProductionRunModel)
            .where(
                StoryBibleProductionRunModel.run_id == run.run_id,
                StoryBibleProductionRunModel.status
                == str(StoryBibleProductionRunStatus.RESERVED),
            )
            .values(
                status=str(updated.status),
                payload=updated.model_dump(mode="json"),
                updated_at=updated.updated_at,
            )
        )
        self._session.commit()
        return cast(CursorResult[object], result).rowcount == 1

    def save_success(
        self,
        run_id: str,
        *,
        curator_proposal: StoryBibleCuratorProposalV1,
        agent_run_id: str,
    ) -> StoryBibleProductionRunV1:
        """Checkpoint the complete typed proposal exactly once after execution."""

        run = self._require_run(run_id)
        if run.status != StoryBibleProductionRunStatus.RUNNING:
            raise ValueError(f"illegal StoryBible run transition: {run.status} -> SUCCEEDED")
        updated = run.model_copy(
            update={
                "status": StoryBibleProductionRunStatus.SUCCEEDED,
                "curator_proposal": curator_proposal,
                "agent_run_id": agent_run_id,
                "updated_at": datetime.now(UTC),
            }
        )
        return self._compare_and_swap(run, updated)

    def save_failure(
        self,
        run_id: str,
        *,
        error_message: str,
        failure_stage: StoryBibleProductionFailureStage | None = None,
        agent_run_id: str | None = None,
    ) -> StoryBibleProductionRunV1:
        """Persist a sanitized failure only from an actively running execution."""

        run = self._require_run(run_id)
        if run.status != StoryBibleProductionRunStatus.RUNNING:
            raise ValueError(f"illegal StoryBible run transition: {run.status} -> FAILED")
        updated = run.model_copy(
            update={
                "status": StoryBibleProductionRunStatus.FAILED,
                "error_message": error_message,
                "failure_stage": failure_stage,
                "agent_run_id": agent_run_id,
                "updated_at": datetime.now(UTC),
            }
        )
        return self._compare_and_swap(run, updated)

    def validate_approved_lineage(self, production_input: StoryBibleProductionInputV1) -> None:
        """Reject cross-project or unrelated persisted Gate 2/Timeline artifacts."""

        gate2_found = False
        narrative_rows = self._session.scalars(select(NarrativeAnalysisRunModel)).all()
        for narrative_row in narrative_rows:
            route_payload = narrative_row.payload.get("review_gate2_route")
            bundle_payload = (
                route_payload.get("approved_proposal_bundle")
                if isinstance(route_payload, dict)
                else None
            )
            gate2_bundle = (
                ApprovedProposalBundleV1.model_validate(bundle_payload)
                if bundle_payload is not None
                else None
            )
            if (
                gate2_bundle is not None
                and gate2_bundle.bundle_id == production_input.gate2_approved_bundle_id
            ):
                if (
                    gate2_bundle.project_id != production_input.project_id
                    or narrative_row.project_id != production_input.project_id
                ):
                    raise ValueError("Gate 2 approved bundle belongs to another project")
                if gate2_bundle.analysis_run_id != narrative_row.analysis_run_id:
                    raise ValueError("Gate 2 approved bundle has invalid analysis lineage")
                gate2_found = True
                break
        if not gate2_found:
            raise ValueError("Gate 2 approved bundle not found")

        timeline_found = False
        timeline_rows = self._session.scalars(select(TimelineGate3RunModel)).all()
        for timeline_row in timeline_rows:
            bundle_payload = timeline_row.payload.get("approved_timeline_bundle")
            timeline_bundle = (
                ApprovedTimelineBundleV1.model_validate(bundle_payload)
                if bundle_payload is not None
                else None
            )
            if (
                timeline_bundle is None
                or timeline_bundle.bundle_id != production_input.approved_timeline_bundle_id
            ):
                continue
            if timeline_row.status != str(TimelineGate3RunStatus.APPROVED):
                raise ValueError("Timeline bundle is not approved")
            if (
                timeline_bundle.project_id != production_input.project_id
                or timeline_row.project_id != production_input.project_id
            ):
                raise ValueError("Approved Timeline bundle belongs to another project")
            if (
                timeline_bundle.source_approved_proposal_bundle_id
                != production_input.gate2_approved_bundle_id
                or timeline_row.source_bundle_id != production_input.gate2_approved_bundle_id
            ):
                raise ValueError("Approved Timeline bundle has unrelated Gate 2 lineage")
            if timeline_bundle.timeline_run_id != timeline_row.timeline_run_id:
                raise ValueError("Approved Timeline bundle has invalid run lineage")
            timeline_found = True
            break
        if not timeline_found:
            raise ValueError("Approved Timeline bundle not found")

    def _require_run(self, run_id: str) -> StoryBibleProductionRunV1:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError(f"StoryBible production run not found: {run_id}")
        return run

    def _compare_and_swap(
        self,
        previous: StoryBibleProductionRunV1,
        updated: StoryBibleProductionRunV1,
    ) -> StoryBibleProductionRunV1:
        result = self._session.execute(
            update(StoryBibleProductionRunModel)
            .where(
                StoryBibleProductionRunModel.run_id == previous.run_id,
                StoryBibleProductionRunModel.status == str(previous.status),
            )
            .values(
                status=str(updated.status),
                payload=updated.model_dump(mode="json"),
                updated_at=updated.updated_at,
            )
        )
        self._session.commit()
        if cast(CursorResult[object], result).rowcount != 1:
            raise ValueError("StoryBible production run changed concurrently")
        return updated
