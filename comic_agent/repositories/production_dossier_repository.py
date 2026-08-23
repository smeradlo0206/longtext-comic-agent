"""Durable insert-only storage for immutable ProductionDossier artifacts."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from comic_agent.database.models import ProductionDossierModel
from comic_agent.schemas.storybible import ProductionDossierV1
from comic_agent.services.production_dossier_identity import production_dossier_content_hash


class ProductionDossierConflictError(ValueError):
    """A dossier id was reused with different immutable material."""


class ProductionDossierRepository:
    """Persist a full dossier once and verify it whenever it is retrieved."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_dossier_id(self, dossier_id: str) -> ProductionDossierV1 | None:
        row = self._session.get(ProductionDossierModel, dossier_id)
        if row is None:
            return None
        dossier = ProductionDossierV1.model_validate(row.payload)
        if row.project_id != dossier.project_id or row.document_id != dossier.document_id:
            raise ProductionDossierConflictError("persisted dossier index does not match payload")
        if row.content_hash != production_dossier_content_hash(dossier):
            raise ProductionDossierConflictError("persisted dossier payload hash does not match")
        return dossier

    def get_content_hash(self, dossier_id: str) -> str | None:
        row = self._session.get(ProductionDossierModel, dossier_id)
        return None if row is None else row.content_hash

    def insert(self, dossier: ProductionDossierV1) -> ProductionDossierV1:
        """Insert exactly once; identical content is idempotent across restarts."""

        content_hash = production_dossier_content_hash(dossier)
        existing = self.get_by_dossier_id(dossier.dossier_id)
        if existing is not None:
            return self._matching_or_raise(existing, dossier, content_hash)
        try:
            self._session.add(
                ProductionDossierModel(
                    dossier_id=dossier.dossier_id,
                    project_id=dossier.project_id,
                    document_id=dossier.document_id,
                    content_hash=content_hash,
                    payload=dossier.model_dump(mode="json"),
                    created_at=dossier.created_at,
                )
            )
            self._session.commit()
            return dossier
        except IntegrityError:
            self._session.rollback()
            winner = self.get_by_dossier_id(dossier.dossier_id)
            if winner is None:
                raise
            return self._matching_or_raise(winner, dossier, content_hash)

    @staticmethod
    def _matching_or_raise(
        existing: ProductionDossierV1, incoming: ProductionDossierV1, incoming_hash: str
    ) -> ProductionDossierV1:
        if production_dossier_content_hash(existing) != incoming_hash:
            raise ProductionDossierConflictError("ProductionDossier is insert-only and immutable")
        return existing
