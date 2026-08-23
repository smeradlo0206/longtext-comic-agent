"""Durable unified Human Review decisions never require a real provider."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from comic_agent.database.base import Base
from comic_agent.repositories.human_review_repository import (
    HumanReviewRepository,
    RepositoryConflictError,
)
from comic_agent.repositories.production_dossier_repository import (
    ProductionDossierConflictError,
    ProductionDossierRepository,
)
from comic_agent.schemas.human_review import (
    HumanReviewDecision,
    HumanReviewLineageV1,
    HumanReviewRunV1,
)
from comic_agent.schemas.storybible import ProductionDossierProvenanceV1, ProductionDossierV1
from comic_agent.services.production_dossier_identity import production_dossier_content_hash


def _run(*, decision: HumanReviewDecision = HumanReviewDecision.APPROVE) -> HumanReviewRunV1:
    return HumanReviewRunV1(
        review_id="human-review-1",
        project_id="project-1",
        dossier_id="dossier-1",
        dossier_hash="dossier-hash-1",
        decision=decision,
        reviewer_id="reviewer-1",
        reviewer_note="Reviewed for production.",
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
        lineage=HumanReviewLineageV1(
            source_dossier_id="dossier-1",
            narrative_execution_bundle_id="narrative-execution-1",
            timeline_review_material_id="timeline-material-1",
        ),
    )


def _database_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'human-review.db'}"


def _dossier() -> ProductionDossierV1:
    return ProductionDossierV1(
        schema_version="1.0",
        dossier_id="dossier-1",
        project_id="project-1",
        document_id="document-1",
        narrative_execution_bundle_id="narrative-execution-1",
        timeline_review_material_id="timeline-material-1",
        provenance=ProductionDossierProvenanceV1(
            narrative_analysis_run_id="analysis-run-1",
            gate1_review_id="gate1-review-1",
        ),
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
    )


def test_human_review_is_durable_idempotent_and_insert_only_after_restart(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    first_session = Session(engine)
    first = HumanReviewRepository(first_session).insert(_run())
    first_session.close()

    restarted_session = Session(engine)
    repository = HumanReviewRepository(restarted_session)
    restored = repository.get_by_review_id(first.review_id)
    duplicate = repository.insert(_run())

    assert restored == first
    assert duplicate == first
    assert restored is not None
    assert restored.reviewer_note == "Reviewed for production."
    with pytest.raises(RepositoryConflictError):
        repository.insert(_run(decision=HumanReviewDecision.REJECT))


def test_concurrent_matching_approvals_converge_on_one_durable_review(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    def submit() -> str:
        session = Session(engine)
        try:
            return HumanReviewRepository(session).insert(_run()).review_id
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        review_ids = list(executor.map(lambda _: submit(), range(2)))

    assert review_ids == ["human-review-1", "human-review-1"]
    session = Session(engine)
    assert HumanReviewRepository(session).get_by_dossier_id("dossier-1") == _run()


def test_production_dossier_is_durable_insert_only_and_detects_payload_tampering(
    tmp_path: Path,
) -> None:
    engine = create_engine(_database_url(tmp_path), connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    first_session = Session(engine)
    first = ProductionDossierRepository(first_session).insert(_dossier())
    first_session.close()

    restarted = Session(engine)
    repository = ProductionDossierRepository(restarted)
    assert repository.get_by_dossier_id(first.dossier_id) == first
    with pytest.raises(ProductionDossierConflictError, match="insert-only"):
        repository.insert(first.model_copy(update={"document_id": "different-document"}))

    from comic_agent.database.models import ProductionDossierModel

    row = restarted.get(ProductionDossierModel, first.dossier_id)
    assert row is not None
    row.payload = row.payload | {
        "provenance": row.payload["provenance"] | {"gate1_review_id": "tampered-review"}
    }
    restarted.commit()
    with pytest.raises(ProductionDossierConflictError, match="hash"):
        repository.get_by_dossier_id(first.dossier_id)


def test_production_dossier_hash_ignores_creation_time() -> None:
    first = _dossier()
    rebuilt = first.model_copy(update={"created_at": datetime(2026, 8, 24, tzinfo=UTC)})

    assert first.dossier_id == rebuilt.dossier_id
    assert production_dossier_content_hash(first) == production_dossier_content_hash(rebuilt)
