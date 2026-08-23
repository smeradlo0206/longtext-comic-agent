"""Deterministic identity for immutable non-canonical production dossiers."""

import json

from comic_agent.schemas.storybible import ProductionDossierV1
from comic_agent.services.id_service import checksum_text


def production_dossier_content_hash(dossier: ProductionDossierV1) -> str:
    """Hash business content while excluding runtime-only artifact metadata."""

    payload = dossier.model_dump(mode="json")
    # A dossier can be rebuilt during recovery. Its creation timestamp records
    # persistence timing, not reviewed business content, so it must not change
    # the immutable approval binding.
    payload.pop("created_at", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return checksum_text(canonical)
