"""Deterministic server-owned identity for production StoryBible execution."""

import json

from comic_agent.schemas.storybible import (
    HumanApprovedStoryBibleProductionLineageV1,
    StoryBibleProductionInputV1,
)
from comic_agent.services.id_service import checksum_text, stable_id


def storybible_production_input_hash(
    production_input: StoryBibleProductionInputV1,
    *,
    model_identity: str,
    human_approved_lineage: HumanApprovedStoryBibleProductionLineageV1 | None = None,
) -> str:
    """Hash the authorized production lineage before any provider use."""

    if not model_identity.strip():
        raise ValueError("model_identity must not be blank")
    payload: dict[str, object] = {
        "approved_timeline_bundle_id": production_input.approved_timeline_bundle_id,
        "canonical_storybible_snapshot_hash": (
            production_input.canonical_storybible_snapshot_hash
        ),
        "gate2_approved_bundle_id": production_input.gate2_approved_bundle_id,
        "human_review_id": production_input.human_review_id,
        "model_identity": model_identity,
        "narrative_execution_bundle_id": production_input.narrative_execution_bundle_id,
        "production_dossier_id": production_input.production_dossier_id,
        "project_id": production_input.project_id,
        "schema_version": production_input.schema_version,
        "timeline_review_material_id": production_input.timeline_review_material_id,
    }
    if human_approved_lineage is not None:
        payload["human_approved_lineage"] = human_approved_lineage.model_dump(mode="json")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return checksum_text(canonical)


def storybible_production_run_id(input_hash: str) -> str:
    """Return the stable application-owned run id for one canonical input hash."""

    if not input_hash.strip():
        raise ValueError("input_hash must not be blank")
    return stable_id("storybible-run", input_hash)
