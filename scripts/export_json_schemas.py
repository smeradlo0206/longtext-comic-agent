"""Export core Pydantic schemas to JSON Schema files."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, TypeAdapter

from comic_agent.schemas import (
    AgentRunV1,
    CharacterStateV1,
    ClaimProposalV1,
    CommitPlanV1,
    ConflictV1,
    EntityProposalV1,
    EventProposalV1,
    EvidenceRefV1,
    PanelSpecV1,
    ProfileUpdateProposalV1,
    ProjectSpecV1,
    QAResultV1,
    RelationshipUpdateProposalV1,
    RepairPlanV1,
    ResolvedProfileStateV1,
    SceneSpecV1,
    SourceChapterV1,
    SourceChunkV1,
    SourceDocumentV1,
    StateChangeProposalV1,
    StateUpdateProposalV1,
    StoryBeatV1,
    StoryBibleContextV1,
    StoryBibleCuratorProposalV1,
    StoryBibleSnapshotV1,
    StoryBibleUpdateV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    TemporalRelationProposalV1,
    WorldRuleUpdateProposalV1,
    WorldRuleV1,
)

SCHEMAS: list[type[BaseModel]] = [
    AgentRunV1,
    EvidenceRefV1,
    ProjectSpecV1,
    SourceDocumentV1,
    SourceChapterV1,
    SourceChunkV1,
    EntityProposalV1,
    EventProposalV1,
    ClaimProposalV1,
    TemporalRelationProposalV1,
    StateChangeProposalV1,
    CharacterStateV1,
    SceneSpecV1,
    StoryBeatV1,
    PanelSpecV1,
    QAResultV1,
    RepairPlanV1,
    StoryBibleContextV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleV1,
    ProfileUpdateProposalV1,
    StateUpdateProposalV1,
    RelationshipUpdateProposalV1,
    WorldRuleUpdateProposalV1,
    ConflictV1,
    CommitPlanV1,
    StoryBibleCuratorProposalV1,
    ResolvedProfileStateV1,
    StoryBibleSnapshotV1,
]


def main() -> None:
    """Write JSON Schema files."""

    output_dir = Path("schema_exports")
    output_dir.mkdir(exist_ok=True)
    for model in SCHEMAS:
        path = output_dir / f"{model.__name__}.json"
        path.write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    update_path = output_dir / "StoryBibleUpdateV1.json"
    update_path.write_text(
        json.dumps(
            TypeAdapter(StoryBibleUpdateV1).json_schema(),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
