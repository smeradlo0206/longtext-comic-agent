"""Repository for auditable agent run records."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from comic_agent.database.models import AgentRunModel
from comic_agent.schemas.workflow import AgentRunV1


class AgentRunRepository:
    """Data access layer for AgentRunV1 audit records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_agent_run(self, agent_run: AgentRunV1) -> AgentRunV1:
        """Persist an AgentRunV1 idempotently."""

        payload = agent_run.model_dump(mode="json")
        existing = self._session.get(AgentRunModel, agent_run.agent_run_id)
        if existing is not None:
            if existing.payload != payload:
                raise ValueError(f"AgentRun conflict for id: {agent_run.agent_run_id}")
            return AgentRunV1.model_validate(existing.payload)

        self._session.add(
            AgentRunModel(
                agent_run_id=agent_run.agent_run_id,
                workflow_run_id=None,
                agent_id=agent_run.agent_name,
                status=str(agent_run.status),
                payload=payload,
                created_at=agent_run.started_at,
            )
        )
        self._session.commit()
        return agent_run

    def get_agent_run(self, agent_run_id: str) -> AgentRunV1 | None:
        """Return one AgentRunV1 by id."""

        row = self._session.get(AgentRunModel, agent_run_id)
        if row is None:
            return None
        return AgentRunV1.model_validate(row.payload)

    def count_agent_runs(self) -> int:
        """Return total agent run count."""

        return len(self._session.scalars(select(AgentRunModel)).all())
