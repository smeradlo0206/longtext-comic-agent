"""Deterministic server-owned identity for production StoryBible execution."""

import json

from comic_agent.schemas.storybible import StoryBibleProductionInputV1
from comic_agent.services.id_service import checksum_text, stable_id


def storybible_production_input_hash(
    production_input: StoryBibleProductionInputV1,
    *,
    model_identity: str,
) -> str:
    """Hash canonical approved-artifact and execution identities before provider use."""

    if not model_identity.strip():
        raise ValueError("model_identity must not be blank")
    payload = {
        "approved_timeline_bundle_id": production_input.approved_timeline_bundle_id,
        "canonical_storybible_snapshot_hash": (
            production_input.canonical_storybible_snapshot_hash
        ),
        "gate2_approved_bundle_id": production_input.gate2_approved_bundle_id,
        "model_identity": model_identity,
        "project_id": production_input.project_id,
        "schema_version": production_input.schema_version,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return checksum_text(canonical)


def storybible_production_run_id(input_hash: str) -> str:
    """Return the stable application-owned run id for one canonical input hash."""

    if not input_hash.strip():
        raise ValueError("input_hash must not be blank")
    return stable_id("storybible-run", input_hash)
