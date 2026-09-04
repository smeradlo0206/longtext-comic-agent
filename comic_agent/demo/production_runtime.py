"""Local harness around the persisted production pipeline used by the demo CLI."""

import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.api.pipeline import _run_pipeline_until_terminal
from comic_agent.config import get_settings
from comic_agent.demo.timeline_adapter import DemoRecoverableTimelineError
from comic_agent.domain.identity import storybible_proposal_hash
from comic_agent.main import create_app
from comic_agent.repositories.agent_run_repository import AgentRunRepository
from comic_agent.repositories.narrative_analysis_recovery_repository import (
    NarrativeAnalysisRecoveryRepository,
)
from comic_agent.repositories.narrative_analysis_repository import (
    NarrativeAnalysisRepository,
)
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.repositories.storybible_production_run_repository import (
    StoryBibleProductionRunRepository,
)
from comic_agent.repositories.storybible_repository import StoryBibleRepository
from comic_agent.repositories.storybible_review_repository import StoryBibleReviewRepository
from comic_agent.repositories.timeline_gate3_repository import TimelineGate3Repository
from comic_agent.schemas.narrative import (
    EntityProposalV1,
    EventProposalV1,
)
from comic_agent.schemas.storybible import (
    ApprovedStoryBibleBundleV1,
    StoryBibleProductionRunStatus,
    StoryBibleReviewContextV1,
    StoryBibleReviewDecision,
)
from comic_agent.schemas.timeline import (
    ApprovedTimelineBundleV1,
    TimelineGate3RunStatus,
)
from comic_agent.schemas.workflow import NarrativeAnalysisRunStatus
from comic_agent.services.commit_service import CommitService
from comic_agent.services.id_service import stable_id
from comic_agent.services.narrative_analysis_coordinator import (
    DEFAULT_NARRATIVE_ANALYST_MODES,
    NarrativeAnalysisCoordinator,
)
from comic_agent.services.storybible_freeze_service import StoryBibleFreezeService
from comic_agent.services.storybible_production_context import (
    StoryBibleProductionContextAdapter,
    StoryBibleProductionInputBuilder,
)
from comic_agent.services.storybible_production_coordinator import (
    StoryBibleProductionCoordinator,
)
from comic_agent.services.storybible_production_output_normalizer import (
    StoryBibleProductionOutputNormalizer,
)
from comic_agent.services.storybible_review_service import StoryBibleReviewService


class ProductionDemoRuntime:
    """Invoke production-wired workflows in an isolated database."""

    def __init__(self, *, input_path: Path, work_dir: Path, max_chunks: int) -> None:
        self.input_path = input_path
        self.max_chunks = max_chunks
        self.project_id = stable_id(
            "real-comic-demo", input_path.name, input_path.read_text("utf-8")
        )
        work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(work_dir, 0o700)
        database = work_dir / f"{self.project_id}.db"
        self.database_path = database
        self.app = create_app(database_url=f"sqlite+pysqlite:///{database.as_posix()}")
        if database.exists():
            os.chmod(database, 0o600)
        self._context = TestClient(self.app)
        self.client = self._context.__enter__()
        self.analysis_run_id: str | None = None
        self.gate2_bundle_id: str | None = None
        self.timeline_run_id: str | None = None
        self.timeline_bundle: ApprovedTimelineBundleV1 | None = None
        self._prepare()

    def close(self) -> None:
        self._context.__exit__(None, None, None)
        for path in [self.database_path.parent, *self.database_path.parent.rglob("*")]:
            if not path.is_symlink():
                os.chmod(path, 0o700 if path.is_dir() else 0o600)

    def _prepare(self) -> None:
        created = self.client.post(
            "/projects", json={"project_id": self.project_id, "name": "Comic Demo"}
        )
        if created.status_code not in {200, 201, 409}:
            raise RuntimeError(f"production project setup failed: HTTP {created.status_code}")
        with self.input_path.open("rb") as stream:
            imported = self.client.post(
                f"/projects/{self.project_id}/documents/import",
                files={"file": (self.input_path.name, stream, "text/plain")},
            )
        if imported.status_code not in {200, 201}:
            raise RuntimeError(f"production TXT import failed: HTTP {imported.status_code}")
        document = imported.json().get("document")
        if not isinstance(document, dict) or not isinstance(document.get("document_id"), str):
            raise RuntimeError("production TXT import did not return a document id")
        self.document_id = document["document_id"]
        with self.app.state.session_factory() as session:
            self.chunk_ids = [
                chunk.chunk_id
                for chunk in SourceRepository(session).list_document_chunks(self.document_id)
            ]
        if not self.chunk_ids:
            raise RuntimeError("production import produced no SourceChunks")

    def run_narrative(self) -> tuple[list[EntityProposalV1], list[EventProposalV1], int]:
        """Run every approved source chunk through the resumable six-mode worker."""

        with self.app.state.session_factory() as session:
            settings = get_settings().model_copy(
                update={"narrative_batch_max_chunks": self.max_chunks}
            )
            run = NarrativeAnalysisCoordinator(
                source_repository=SourceRepository(session),
                analysis_repository=NarrativeAnalysisRepository(session),
                settings=settings,
            ).create_run(
                project_id=self.project_id,
                document_id=self.document_id,
                chapter_ids=None,
                modes=list(DEFAULT_NARRATIVE_ANALYST_MODES),
                real_llm_requested=True,
            )
            self.analysis_run_id = run.analysis_run_id

        _run_pipeline_until_terminal(
            self.app.state.session_factory,
            self.app.state,
            self.analysis_run_id,
            True,
        )
        with self.app.state.session_factory() as session:
            analyses = NarrativeAnalysisRepository(session)
            persisted_run = analyses.get_run(self.analysis_run_id)
            result = analyses.get_result(self.analysis_run_id)
            windows = analyses.list_windows(self.analysis_run_id)
            if (
                persisted_run is None
                or result is None
                or persisted_run.status != NarrativeAnalysisRunStatus.SUCCEEDED
            ):
                diagnostics = sorted(
                    {
                        str(window.failure_category)
                        for window in windows
                        if window.failure_category
                    }
                )
                fallback_status = persisted_run.status if persisted_run else "MISSING"
                raise RuntimeError(
                    "production whole-document Narrative failed: "
                    + (", ".join(diagnostics) if diagnostics else str(fallback_status))
                )
            route = persisted_run.review_gate2_route
            bundle = route.approved_proposal_bundle if route is not None else None
            if bundle is None:
                for attempt in reversed(
                    NarrativeAnalysisRecoveryRepository(session).list_attempts(
                        self.analysis_run_id
                    )
                ):
                    candidate = attempt.fresh_route
                    if (
                        candidate is not None
                        and str(candidate.decision) == "APPROVED"
                        and candidate.approved_proposal_bundle is not None
                    ):
                        bundle = candidate.approved_proposal_bundle
                        break
            if bundle is None:
                raise RuntimeError("production Gate 2 did not produce an approved bundle")
            timeline_run = TimelineGate3Repository(session).get_by_bundle(
                self.project_id, bundle.bundle_id
            )
            if (
                timeline_run is None
                or timeline_run.status != TimelineGate3RunStatus.APPROVED
                or timeline_run.approved_timeline_bundle is None
            ):
                status = timeline_run.status if timeline_run is not None else "MISSING"
                raise RuntimeError(f"production Timeline/Gate 3 did not approve: {status}")
            self.gate2_bundle_id = bundle.bundle_id
            self.timeline_run_id = timeline_run.timeline_run_id
            self.timeline_bundle = timeline_run.approved_timeline_bundle
            provider_calls = sum(window.provider_request_count for window in windows)
            return (
                [item.proposal for item in result.entities],
                [item.proposal for item in result.events],
                provider_calls,
            )

    def run_timeline(
        self, events: list[EventProposalV1]
    ) -> tuple[ApprovedTimelineBundleV1, str, list[str], int]:
        if self.timeline_bundle is None or self.timeline_run_id is None:
            raise DemoRecoverableTimelineError("production Timeline has not been executed")
        if set(self.timeline_bundle.event_ids) != {event.proposal_id for event in events}:
            raise RuntimeError("production Timeline event universe differs from Narrative")
        with self.app.state.session_factory() as session:
            run = TimelineGate3Repository(session).get_run(self.timeline_run_id)
            if run is None or run.gate3_result is None:
                raise RuntimeError("production Timeline/Gate 3 checkpoint is missing")
            return (
                self.timeline_bundle,
                str(run.gate3_result.effective_decision or run.gate3_result.decision),
                [str(item.issue_code) for item in run.gate3_result.issues],
                run.provider_request_count,
            )

    def run_storybible(self, **_: object) -> ApprovedStoryBibleBundleV1:
        """Produce, review, commit, and freeze the production StoryBible."""

        if self.gate2_bundle_id is None or self.timeline_bundle is None:
            raise RuntimeError("approved Narrative and Timeline artifacts are required")
        settings = get_settings()
        with self.app.state.session_factory() as session:
            context = StoryBibleProductionContextAdapter(session).build(
                project_id=self.project_id,
                gate2_approved_bundle_id=self.gate2_bundle_id,
                approved_timeline_bundle_id=self.timeline_bundle.bundle_id,
            )
            production = StoryBibleProductionCoordinator(
                input_builder=StoryBibleProductionInputBuilder(session),
                run_repository=StoryBibleProductionRunRepository(session),
                curator=self.app.state.storybible_curator,
                output_normalizer=StoryBibleProductionOutputNormalizer(),
                agent_run_repository=AgentRunRepository(session),
                settings=settings,
            ).run(
                project_id=self.project_id,
                gate2_approved_bundle_id=self.gate2_bundle_id,
                approved_timeline_bundle_id=self.timeline_bundle.bundle_id,
                model_identity=settings.storybible_model,
                real_llm_requested=True,
            )
            if (
                production.status != StoryBibleProductionRunStatus.SUCCEEDED
                or production.curator_proposal is None
            ):
                raise RuntimeError(
                    "production StoryBible failed: "
                    + (production.error_message or str(production.failure_stage or "UNKNOWN"))
                )
            proposal = production.curator_proposal
            review_context = StoryBibleReviewContextV1(
                review_id=stable_id("storybible-review", production.run_id),
                project_id=self.project_id,
                source_storybible_run_id=production.run_id,
                source_approved_timeline_bundle_id=self.timeline_bundle.bundle_id,
                canonical_snapshot=context.canonical_snapshot,
                canonical_snapshot_hash=context.canonical_storybible_snapshot_hash,
                proposal_hash=storybible_proposal_hash(proposal),
                reviewed_at=datetime.now(UTC),
            )
            review_result = StoryBibleReviewService(SourceRepository(session)).review(
                review_context,
                production_run=production,
                proposal=proposal,
                commit_plan=proposal.commit_plan,
                approved_timeline=self.timeline_bundle,
            )
            review = StoryBibleReviewRepository(session).save_review(
                review_context, review_result
            )
            if review_result.decision != StoryBibleReviewDecision.APPROVE:
                raise RuntimeError(
                    f"production StoryBible review requires intervention: {review_result.decision}"
                )
            return StoryBibleFreezeService(
                review_repository=StoryBibleReviewRepository(session),
                storybible_repository=StoryBibleRepository(session),
                commit_service=CommitService(SourceRepository(session)),
            ).freeze(
                review.review_id,
                production_run=production,
                approved_timeline=self.timeline_bundle,
            )
