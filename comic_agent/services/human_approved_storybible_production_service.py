"""Small runtime bridge from a durable human approval to existing production execution."""

from comic_agent.schemas.storybible import (
    HumanApprovedStoryBibleProductionExecutionFailureCode,
    StoryBibleProductionAuthorizationFailureV1,
    StoryBibleProductionRunV1,
)
from comic_agent.services.human_approved_storybible_production_execution_adapter import (
    HumanApprovedStoryBibleProductionExecutionAdapter,
)
from comic_agent.services.storybible_production_coordinator import StoryBibleProductionCoordinator


class HumanApprovedStoryBibleProductionService:
    """Execute only material prepared by the durable human-approved adapter."""

    def __init__(
        self,
        adapter: HumanApprovedStoryBibleProductionExecutionAdapter,
        coordinator: StoryBibleProductionCoordinator,
    ) -> None:
        self._adapter = adapter
        self._coordinator = coordinator

    def execute(
        self,
        *,
        project_id: str,
        human_review_id: str,
        model_identity: str,
        real_llm_requested: bool,
    ) -> (
        StoryBibleProductionRunV1
        | StoryBibleProductionAuthorizationFailureV1
        | HumanApprovedStoryBibleProductionExecutionFailureCode
    ):
        prepared = self._adapter.build_and_reserve(
            project_id=project_id,
            human_review_id=human_review_id,
            model_identity=model_identity,
        )
        if prepared.failure_code is not None:
            return prepared.failure_code
        if prepared.prepared is None:
            return (
                HumanApprovedStoryBibleProductionExecutionFailureCode.INVALID_HUMAN_APPROVED_CONTEXT
            )
        return self._coordinator.run_prepared(
            prepared=prepared.prepared,
            model_identity=model_identity,
            real_llm_requested=real_llm_requested,
        )
