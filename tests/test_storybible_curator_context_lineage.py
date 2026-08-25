"""Tests for server-owned Curator context lineage metadata."""

import pytest
from pydantic import ValidationError

from comic_agent.schemas.storybible import (
    StoryBibleCanonicalSnapshotV1,
    StoryBibleCuratorContextLineageV1,
    StoryBibleProductionContextV1,
)
from comic_agent.services.storybible_curator_input_adapter import (
    StoryBibleContextLineageError,
    StoryBibleCuratorInputAdapter,
)
from comic_agent.services.storybible_production_context import (
    canonical_storybible_snapshot_hash,
)


def _production_context() -> StoryBibleProductionContextV1:
    snapshot = StoryBibleCanonicalSnapshotV1(project_id="project-1")
    return StoryBibleProductionContextV1(
        project_id="project-1",
        gate2_approved_bundle_id="gate2-1",
        narrative_analysis_run_id="analysis-1",
        approved_timeline_bundle_id="timeline-1",
        timeline_run_id="timeline-run-1",
        human_review_id="review-1",
        production_dossier_id="dossier-1",
        trusted_event_ids=[],
        trusted_event_order=[],
        trusted_evidence_refs=[],
        source_chunk_ids=[],
        source_chunks=[],
        canonical_snapshot=snapshot,
        canonical_storybible_snapshot_hash=canonical_storybible_snapshot_hash(snapshot),
    )


def _lineage(context: StoryBibleProductionContextV1) -> StoryBibleCuratorContextLineageV1:
    return StoryBibleCuratorContextLineageV1(
        production_run_id="storybible-run-1",
        dossier_id="dossier-1",
        human_review_id="review-1",
        approved_timeline_bundle_id="timeline-1",
        canonical_snapshot_identity="snapshot-identity-1",
        canonical_snapshot_hash=context.canonical_storybible_snapshot_hash,
    )


def test_curator_context_contains_complete_server_lineage() -> None:
    production = _production_context()

    adapted = StoryBibleCuratorInputAdapter().adapt_with_lineage(
        production,
        lineage=_lineage(production),
    )

    assert adapted.context.lineage is not None
    assert adapted.context.lineage.production_run_id == "storybible-run-1"
    assert adapted.context.lineage.dossier_id == "dossier-1"
    assert adapted.context.lineage.human_review_id == "review-1"
    assert adapted.context.lineage.approved_timeline_bundle_id == "timeline-1"
    assert (
        adapted.context.lineage.canonical_snapshot_hash
        == production.canonical_storybible_snapshot_hash
    )


def test_missing_curator_lineage_fails_safely() -> None:
    with pytest.raises(StoryBibleContextLineageError, match="requires"):
        StoryBibleCuratorInputAdapter().adapt_with_lineage(
            _production_context(),
            lineage=None,
        )


def test_inconsistent_curator_lineage_fails_before_provider_context_is_built() -> None:
    production = _production_context()
    lineage = _lineage(production).model_copy(update={"dossier_id": "other-dossier"})

    with pytest.raises(StoryBibleContextLineageError, match="dossier_id"):
        StoryBibleCuratorInputAdapter().adapt_with_lineage(production, lineage=lineage)


def test_lineage_contract_requires_all_metadata_fields() -> None:
    with pytest.raises(ValidationError):
        StoryBibleCuratorContextLineageV1.model_validate(
            {
                "production_run_id": "run-1",
                "dossier_id": "dossier-1",
                "human_review_id": "review-1",
                "canonical_snapshot_identity": "snapshot-1",
                "canonical_snapshot_hash": "hash-1",
            }
        )
