"""Base agent protocol."""

from typing import Protocol, TypeVar

from pydantic import BaseModel

from comic_agent.agents.specs import AgentSpec

ProposalT = TypeVar("ProposalT", bound=BaseModel, covariant=True)


class BaseAgent(Protocol[ProposalT]):
    """Agent interface that returns proposals only."""

    spec: AgentSpec

    def run(self, input_context: dict[str, object]) -> ProposalT:
        """Run agent over bounded context and return a proposal model."""
