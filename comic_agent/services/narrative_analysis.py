"""Deterministic planning helpers for whole-document narrative analysis."""

from datetime import UTC, datetime
from typing import Protocol, TypeVar

from pydantic import BaseModel

from comic_agent.agents.narrative_analyst import NarrativeAnalyst
from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.workflow import (
    NarrativeAnalysisRunStatus,
    NarrativeAnalysisRunV1,
    NarrativeAnalysisWindowPlanV1,
    NarrativeAnalysisWindowStatus,
    NarrativeAnalysisWindowV1,
)
from comic_agent.services.id_service import stable_id

DEFAULT_ANALYSIS_WINDOW_SIZE = 3
DEFAULT_ANALYSIS_STRIDE = 2
OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class DocumentChunkLookup(Protocol):
    """Source repository capability required to create an analysis task."""

    def list_document_chunks(self, document_id: str) -> list[SourceChunkV1]:
        """Return source chunks in document order."""


def plan_analysis_windows(
    chunks: list[SourceChunkV1],
    *,
    window_size: int = DEFAULT_ANALYSIS_WINDOW_SIZE,
    stride: int = DEFAULT_ANALYSIS_STRIDE,
) -> list[NarrativeAnalysisWindowPlanV1]:
    """Plan ordered, overlapping windows and guarantee final-chunk coverage."""

    if window_size < 1:
        raise ValueError("window_size must be at least 1")
    if stride < 1:
        raise ValueError("stride must be at least 1")
    if not chunks:
        return []

    ordered_chunks = sorted(chunks, key=lambda chunk: (chunk.order, chunk.chunk_id))
    starts = list(range(0, max(len(ordered_chunks) - window_size + 1, 1), stride))
    tail_start = max(len(ordered_chunks) - window_size, 0)
    if tail_start not in starts:
        starts.append(tail_start)
    covered_positions = {
        position
        for start in starts
        for position in range(start, min(start + window_size, len(ordered_chunks)))
    }
    for position in range(len(ordered_chunks)):
        if position not in covered_positions:
            starts.append(min(position, len(ordered_chunks) - window_size))
    starts = sorted(set(starts))
    planned_windows: list[NarrativeAnalysisWindowPlanV1] = []
    owned_chunk_ids: set[str] = set()
    for index, start in enumerate(starts):
        chunk_ids = [
            chunk.chunk_id for chunk in ordered_chunks[start : start + window_size]
        ]
        owned = [chunk_id for chunk_id in chunk_ids if chunk_id not in owned_chunk_ids]
        owned_chunk_ids.update(owned)
        planned_windows.append(
            NarrativeAnalysisWindowPlanV1(
                window_index=index,
                chunk_ids=chunk_ids,
                owned_chunk_ids=owned,
            )
        )
    return planned_windows


def create_narrative_analysis_run(
    *,
    source_repository: DocumentChunkLookup,
    analysis_repository: NarrativeAnalysisRepository,
    project_id: str,
    document_id: str,
    modes: list[str],
    window_size: int = DEFAULT_ANALYSIS_WINDOW_SIZE,
    stride: int = DEFAULT_ANALYSIS_STRIDE,
    real_llm_requested: bool = False,
) -> NarrativeAnalysisRunV1:
    """Create an idempotent task with independent mode-window audit records."""

    if not modes:
        raise ValueError("at least one NarrativeAnalyst mode is required")
    if len(set(modes)) != len(modes):
        raise ValueError("NarrativeAnalyst modes must be distinct")
    for mode in modes:
        mode_spec = NarrativeAnalyst(_ModeLookupProvider()).get_mode_spec(mode)
        if mode_spec.status != "implemented":
            raise ValueError(f"NarrativeAnalyst mode is not implemented: {mode}")

    chunks = source_repository.list_document_chunks(document_id)
    if not chunks or any(chunk.project_id != project_id for chunk in chunks):
        raise ValueError("SourceDocument has no SourceChunk records for project")
    plans = plan_analysis_windows(chunks, window_size=window_size, stride=stride)
    analysis_run_id = stable_id(
        "narrative-analysis-run",
        project_id,
        document_id,
        ",".join(modes),
        window_size,
        stride,
        real_llm_requested,
    )
    existing = analysis_repository.get_run(analysis_run_id)
    if existing is not None:
        return existing

    windows = [
        NarrativeAnalysisWindowV1(
            analysis_window_id=stable_id(
                "narrative-analysis-window", analysis_run_id, mode, plan.window_index
            ),
            analysis_run_id=analysis_run_id,
            mode=mode,
            window_index=plan.window_index,
            chunk_ids=plan.chunk_ids,
            owned_chunk_ids=plan.owned_chunk_ids,
            status=NarrativeAnalysisWindowStatus.PENDING,
        )
        for mode in modes
        for plan in plans
    ]
    now = datetime.now(UTC)
    run = NarrativeAnalysisRunV1(
        analysis_run_id=analysis_run_id,
        project_id=project_id,
        document_id=document_id,
        modes=modes,
        status=NarrativeAnalysisRunStatus.PENDING,
        window_size=window_size,
        stride=stride,
        real_llm_requested=real_llm_requested,
        window_ids=[window.analysis_window_id for window in windows],
        created_at=now,
        updated_at=now,
    )
    return analysis_repository.create_run(run, windows)


class _ModeLookupProvider:
    """Never-called provider used solely to access the mode registry."""

    def structured_generate(
        self,
        request: dict[str, object],
        output_model: type[OutputModelT],
    ) -> OutputModelT:
        raise RuntimeError("NarrativeAnalyst mode lookup must not call a provider")
