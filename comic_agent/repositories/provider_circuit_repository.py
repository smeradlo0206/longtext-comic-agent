"""Durable, source-free Provider circuit-breaker persistence."""

from sqlalchemy.orm import Session

from comic_agent.database.models import ProviderCircuitStateModel
from comic_agent.schemas.reliability import ProviderCapabilityProfileV1, ProviderCircuitStateV1


class ProviderCircuitRepository:
    """Store one circuit state per configured Provider identity."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, provider_key: str) -> ProviderCircuitStateV1 | None:
        row = self._session.get(ProviderCircuitStateModel, provider_key)
        return ProviderCircuitStateV1.model_validate(row.payload) if row is not None else None

    def save(self, state: ProviderCircuitStateV1) -> ProviderCircuitStateV1:
        row = self._session.get(ProviderCircuitStateModel, state.provider_key)
        if row is None:
            self._session.add(
                ProviderCircuitStateModel(
                    provider_key=state.provider_key,
                    status=str(state.status),
                    payload=state.model_dump(mode="json"),
                    updated_at=state.updated_at,
                )
            )
        else:
            row.status = str(state.status)
            row.payload = state.model_dump(mode="json")
            row.updated_at = state.updated_at
        self._session.commit()
        return state

    def get_capability_profile(self, provider_key: str) -> ProviderCapabilityProfileV1 | None:
        """Read the cached source-free capability profile, if one was probed."""

        state = self.get(provider_key)
        return state.capability_profile if state is not None else None

    def save_capability_profile(
        self, profile: ProviderCapabilityProfileV1
    ) -> ProviderCapabilityProfileV1:
        """Persist capability in the existing circuit payload without a new table."""

        provider_key = f"{profile.provider_name}:{profile.model_name}"
        state = self.get(provider_key) or ProviderCircuitStateV1(provider_key=provider_key)
        self.save(
            state.model_copy(
                update={
                    "schema_version": "1.1",
                    "capability_profile": profile,
                    "updated_at": profile.checked_at,
                }
            )
        )
        return profile
