"""Deterministic planning helpers for whole-document narrative analysis."""

from datetime import UTC, datetime
from typing import Protocol, TypeVar

from pydantic import BaseModel

from comic_agent.agents.narrative_analyst import NarrativeAnalyst
from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.schemas.workflow import (
    NarrativeAnalysisBatchV1,
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
    batch_max_chunks: int = 20,
    output_token_budget: int = 2000,
    time_budget_seconds: int = 300,
    max_call_attempts: int = 2,
    max_split_depth: int = 1,
    real_llm_requested: bool = False,
    selected_chunks: list[SourceChunkV1] | None = None,
) -> NarrativeAnalysisRunV1:
    """Create an idempotent task with independent mode-window audit records."""

    if not modes:
        raise ValueError("at least one NarrativeAnalyst mode is required")
    if len(set(modes)) != len(modes):
        raise ValueError("NarrativeAnalyst modes must be distinct")
    if batch_max_chunks < 1:
        raise ValueError("batch_max_chunks must be at least 1")
    if max_split_depth < 0:
        raise ValueError("max_split_depth must not be negative")
    for mode in modes:
        mode_spec = NarrativeAnalyst(_ModeLookupProvider()).get_mode_spec(mode)
        if mode_spec.status != "implemented":
            raise ValueError(f"NarrativeAnalyst mode is not implemented: {mode}")

    all_chunks = source_repository.list_document_chunks(document_id)
    if not all_chunks or any(chunk.project_id != project_id for chunk in all_chunks):
        raise ValueError("SourceDocument has no SourceChunk records for project")
    if selected_chunks is None:
        chunks = all_chunks
    else:
        selected_ids = [chunk.chunk_id for chunk in selected_chunks]
        available = {chunk.chunk_id: chunk for chunk in all_chunks}
        if not selected_ids or len(set(selected_ids)) != len(selected_ids):
            raise ValueError("selected chunks must be non-empty and distinct")
        if any(chunk.project_id != project_id for chunk in selected_chunks):
            raise ValueError("selected chunks must belong to project")
        if any(chunk_id not in available for chunk_id in selected_ids):
            raise ValueError("selected chunk is not part of document")
        chunks = [chunk for chunk in all_chunks if chunk.chunk_id in set(selected_ids)]
    batch_chunks = [
        chunks[index : index + batch_max_chunks]
        for index in range(0, len(chunks), batch_max_chunks)
    ]
    analysis_run_id = stable_id(
        "narrative-analysis-run",
        project_id,
        document_id,
        ",".join(modes),
        window_size,
        stride,
        batch_max_chunks,
        output_token_budget,
        time_budget_seconds,
        max_call_attempts,
        max_split_depth,
        real_llm_requested,
        ",".join(chunk.chunk_id for chunk in chunks),
    )
    existing = analysis_repository.get_run(analysis_run_id)
    if existing is not None:
        return existing

    batches: list[NarrativeAnalysisBatchV1] = []
    planned_windows: list[tuple[int, str, NarrativeAnalysisWindowPlanV1]] = []
    for batch_index, current_batch_chunks in enumerate(batch_chunks):
        batch_id = stable_id(
            "narrative-analysis-batch",
            analysis_run_id,
            batch_index,
            ",".join(chunk.chunk_id for chunk in current_batch_chunks),
        )
        estimated_chars = sum(len(chunk.text) for chunk in current_batch_chunks)
        batches.append(
            NarrativeAnalysisBatchV1(
                batch_id=batch_id,
                analysis_run_id=analysis_run_id,
                document_id=document_id,
                chunk_ids=[chunk.chunk_id for chunk in current_batch_chunks],
                idempotency_key=stable_id(
                    "narrative-analysis-batch-execution", analysis_run_id, batch_id
                ),
                estimated_input_chars=estimated_chars,
                estimated_input_tokens=(estimated_chars + 3) // 4,
                output_token_budget=output_token_budget,
                time_budget_seconds=time_budget_seconds,
                max_call_attempts=max_call_attempts,
            )
        )
        for plan in plan_analysis_windows(
            current_batch_chunks, window_size=window_size, stride=stride
        ):
            planned_windows.append((batch_index, batch_id, plan))
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    windows = [
        NarrativeAnalysisWindowV1(
            analysis_window_id=stable_id(
                "narrative-analysis-window", analysis_run_id, mode, batch_index, plan.window_index
            ),
            analysis_run_id=analysis_run_id,
            mode=mode,
            window_index=(batch_index * 100_000) + plan.window_index,
            chunk_ids=plan.chunk_ids,
            owned_chunk_ids=plan.owned_chunk_ids,
            status=NarrativeAnalysisWindowStatus.PENDING,
            idempotency_key=stable_id(
                "narrative-window-execution",
                analysis_run_id,
                mode,
                ",".join(plan.chunk_ids),
            ),
            batch_id=batch_id,
            estimated_input_chars=sum(
                len(chunks_by_id[chunk_id].text) for chunk_id in plan.chunk_ids
            ),
            estimated_input_tokens=(
                sum(len(chunks_by_id[chunk_id].text) for chunk_id in plan.chunk_ids) + 3
            )
            // 4,
            output_token_budget=output_token_budget,
            time_budget_seconds=time_budget_seconds,
            max_call_attempts=max_call_attempts,
            max_split_depth=max_split_depth,
        )
        for batch_index, batch_id, plan in planned_windows
        for mode in modes
    ]
    now = datetime.now(UTC)
    run = NarrativeAnalysisRunV1(
        schema_version="1.3",
        analysis_run_id=analysis_run_id,
        project_id=project_id,
        document_id=document_id,
        modes=modes,
        status=NarrativeAnalysisRunStatus.PENDING,
        window_size=window_size,
        stride=stride,
        real_llm_requested=real_llm_requested,
        window_ids=[window.analysis_window_id for window in windows],
        batches=batches,
        # Every original window is bounded, and at most one owned child scope per
        # selected chunk can be created by deterministic split recovery.  Reserve
        # that finite worst-case tree up front rather than letting children extend
        # the root budget at runtime.
        max_provider_requests=(len(windows) + (len(chunks) * len(modes))) * max_call_attempts,
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
