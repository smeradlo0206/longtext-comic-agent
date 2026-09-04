"""Compilation, queue handoff, recovery, and finalization for long-text comics."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from comic_agent.agents.long_text_storyboard import LongTextStoryboardAgent
from comic_agent.repositories.comic_production_repository import ComicProductionRepository
from comic_agent.repositories.source_repository import SourceRepository
from comic_agent.schemas.comic_planning import PanelPlanV1
from comic_agent.schemas.comic_production import (
    ComicPerformanceV1,
    ComicProductionRequestV1,
    ComicProductionRunV1,
    ComicRunStatus,
    ComicStoryboardProposalV1,
)
from comic_agent.schemas.source import ProjectSpecV1
from comic_agent.services.comic_page_composer import ComicPageComposer
from comic_agent.services.comic_plan_storyboard_adapter import ComicPlanStoryboardAdapter
from comic_agent.services.context_builder import AgentContext, ContextBuilder
from comic_agent.services.long_text_comic_compiler import LongTextComicCompiler
from flux2_agent.catalog import load_catalog
from flux2_agent.planning import build_plan
from flux2_agent.queueing import QueueStore


class ComicProductionCoordinator:
    """Own deterministic orchestration while model work remains in the image Provider layer."""

    def __init__(
        self,
        *,
        workspace: Path,
        source_repository: SourceRepository,
        production_repository: ComicProductionRepository,
        queue_store: QueueStore,
    ) -> None:
        self._workspace = workspace.resolve()
        self._source_repository = source_repository
        self._production_repository = production_repository
        self._queue_store = queue_store
        self._storyboard_agent = LongTextStoryboardAgent()
        self._planned_storyboard_adapter = ComicPlanStoryboardAdapter()
        self._compiler = LongTextComicCompiler()
        self._composer = ComicPageComposer()

    def compile_and_enqueue(
        self,
        *,
        project_id: str,
        request: ComicProductionRequestV1,
        priority: int = 100,
    ) -> ComicProductionRunV1:
        project, context = self._project_context(project_id=project_id, request=request)
        proposal = self._storyboard_agent.propose(
            context=context,
            document_id=request.document_id,
            request=request,
            reading_direction=project.reading_direction,
        )
        return self._compile_proposal_and_enqueue(
            project=project,
            request=request,
            context=context,
            proposal=proposal,
            priority=priority,
        )

    def compile_planned_and_enqueue(
        self,
        *,
        project_id: str,
        request: ComicProductionRequestV1,
        panel_plans: list[PanelPlanV1],
        page_panel_counts: list[int] | None = None,
        priority: int = 100,
    ) -> ComicProductionRunV1:
        """Compile approved PanelPlan records through the local image workflow."""

        project, context = self._project_context(project_id=project_id, request=request)
        proposal = self._planned_storyboard_adapter.adapt(
            context=context,
            document_id=request.document_id,
            request=request,
            reading_direction=project.reading_direction,
            panel_plans=panel_plans,
            page_panel_counts=page_panel_counts,
        )
        return self._compile_proposal_and_enqueue(
            project=project,
            request=request,
            context=context,
            proposal=proposal,
            priority=priority,
        )

    def _project_context(
        self, *, project_id: str, request: ComicProductionRequestV1
    ) -> tuple[ProjectSpecV1, AgentContext]:
        project = self._source_repository.get_project(project_id)
        if project is None:
            raise ValueError(f"project not found: {project_id}")
        document = self._source_repository.get_document(request.document_id)
        if document is None or document.project_id != project_id:
            raise ValueError("source document does not belong to the requested project")

        chapters = self._source_repository.list_document_chapters(request.document_id)
        known_chapter_ids = {chapter.chapter_id for chapter in chapters}
        selected_chapter_ids = request.chapter_ids or [chapter.chapter_id for chapter in chapters]
        unknown_chapters = [item for item in selected_chapter_ids if item not in known_chapter_ids]
        if unknown_chapters:
            raise ValueError(f"unknown source chapter ids: {unknown_chapters}")
        selected = set(selected_chapter_ids)
        chunks = [
            chunk
            for chunk in self._source_repository.list_document_chunks(request.document_id)
            if chunk.chapter_id in selected
        ]
        if not chunks:
            raise ValueError("selected source chapters contain no approved chunks")
        context = ContextBuilder(max_chunks=max(1, len(chunks))).from_chunks(project_id, chunks)
        return project, context

    def _compile_proposal_and_enqueue(
        self,
        *,
        project: ProjectSpecV1,
        request: ComicProductionRequestV1,
        context: AgentContext,
        proposal: ComicStoryboardProposalV1,
        priority: int,
    ) -> ComicProductionRunV1:
        manifest = self._compiler.compile(
            project=project,
            request=request,
            context=context,
            proposal=proposal,
        )
        existing = self._production_repository.get(manifest.run_id)
        if existing is not None:
            return self.refresh(existing.run_id)

        catalog = load_catalog(self._workspace)
        build_plan(self._workspace, manifest.workflow_job, catalog)
        now = datetime.now(UTC)
        run = self._production_repository.create_or_get(
            ComicProductionRunV1(
                run_id=manifest.run_id,
                project_id=project.id,
                document_id=request.document_id,
                request_hash=manifest.request_hash,
                status=ComicRunStatus.COMPILED,
                manifest=manifest,
                created_at=now,
                updated_at=now,
            )
        )
        try:
            self._queue_store.enqueue(
                manifest.workflow_job,
                priority=priority,
                handoff_validated=True,
            )
        except ValueError as exc:
            if "already exists" not in str(exc):
                raise
        return self._production_repository.save(
            run.model_copy(
                update={
                    "status": ComicRunStatus.QUEUED,
                    "queue_id": manifest.workflow_job.job_id,
                }
            )
        )

    def refresh(self, run_id: str) -> ComicProductionRunV1:
        run = self._production_repository.get(run_id)
        if run is None:
            raise KeyError(f"comic production run not found: {run_id}")
        if run.queue_id is None:
            return run
        queue_item = self._queue_store.get(run.queue_id)
        status_map = {
            "pending": ComicRunStatus.QUEUED,
            "running": ComicRunStatus.RUNNING,
            "succeeded": ComicRunStatus.SUCCEEDED,
            "failed": ComicRunStatus.FAILED,
            "cancelled": ComicRunStatus.CANCELLED,
        }
        next_status = status_map[queue_item.status]
        run_root = queue_item.run_root or run.run_root
        artifacts = run.page_artifacts
        performance = run.performance
        if next_status == ComicRunStatus.SUCCEEDED and run_root and not artifacts:
            artifacts = self._composer.compose(
                run_root=Path(run_root),
                manifest=run.manifest,
            )
        if next_status == ComicRunStatus.SUCCEEDED and run_root:
            result_payload = json.loads(
                (Path(run_root) / "result.json").read_text(encoding="utf-8")
            )
            if isinstance(result_payload.get("performance"), dict):
                performance = ComicPerformanceV1.model_validate(result_payload["performance"])
        updated = run.model_copy(
            update={
                "status": next_status,
                "run_root": run_root,
                "page_artifacts": artifacts,
                "performance": performance,
                "error": queue_item.error,
            }
        )
        return self._production_repository.save(updated) if updated != run else run
