"""Regression tests for StoryBible contract validation."""

import pytest
from pydantic import ValidationError

from comic_agent.schemas import EvidenceRefV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    StoryRelationshipV1,
    WorldRuleV1,
)

EVIDENCE = [EvidenceRefV1(chunk_id="chunk-1")]


def test_profile_rejects_unsupported_entity_kind() -> None:
    """Only story entities supported by the curator may be canonical profiles."""

    with pytest.raises(ValidationError):
        StoryEntityProfileV1(
            profile_id="p-1",
            project_id="project-1",
            entity_kind="PROP",
            canonical_name="Umbrella",
            evidence_refs=EVIDENCE,
        )


def test_commit_plan_requires_at_least_one_update() -> None:
    """An empty plan must never be eligible for canonical processing."""

    with pytest.raises(ValidationError):
        CommitPlanV1(
            commit_plan_id="plan-1",
            project_id="project-1",
            source_proposal_id="curator-1",
            content_hash="hash-1",
            updates=[],
            evidence_refs=EVIDENCE,
        )


@pytest.mark.parametrize(
    ("model", "name_field"),
    [
        (StoryEntityProfileV1, "canonical_name"),
        (WorldRuleV1, "name"),
    ],
)
def test_canonical_resources_reject_blank_names(model: type, name_field: str) -> None:
    """Whitespace-only canonical names must not become StoryBible facts."""

    values = {
        "project_id": "project-1",
        "revision": 1,
        "status": "CANONICAL",
        "evidence_refs": EVIDENCE,
    }
    if model is StoryEntityProfileV1:
        values.update(profile_id="p-1", entity_kind="PERSON")
    else:
        values.update(rule_id="rule-1", statement="Magic requires a spoken name.")
    values[name_field] = "   "

    with pytest.raises(ValidationError, match="must not be blank"):
        model(**values)


@pytest.mark.parametrize(
    "resource",
    [
        StoryEntityStateV1(
            state_id="state-1",
            project_id="project-1",
            profile_id="p-1",
            valid_from_order=1,
            valid_until_order=2,
            evidence_refs=EVIDENCE,
        ),
        StoryRelationshipV1(
            relationship_id="relationship-1",
            project_id="project-1",
            source_profile_id="p-1",
            target_profile_id="p-2",
            relationship_type="ALLY",
            valid_from_order=1,
            valid_until_order=2,
            evidence_refs=EVIDENCE,
        ),
    ],
)
def test_temporal_resources_reject_reversed_intervals(
    resource: StoryEntityStateV1 | StoryRelationshipV1,
) -> None:
    """An interval end must never precede its start."""

    values = resource.model_dump()
    values["valid_from_order"] = 2
    values["valid_until_order"] = 1

    with pytest.raises(ValidationError, match="must not precede"):
        type(resource)(**values)


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (
            StoryEntityStateV1,
            {"state_id": "state-1", "profile_id": "p-1"},
        ),
        (
            StoryRelationshipV1,
            {
                "relationship_id": "relationship-1",
                "source_profile_id": "p-1",
                "target_profile_id": "p-2",
                "relationship_type": "ALLY",
            },
        ),
    ],
)
def test_temporal_resources_accept_open_ended_intervals(model: type, values: dict) -> None:
    """An ongoing fact may have a known start without a known end."""

    resource = model(
        project_id="project-1",
        valid_from_order=1,
        evidence_refs=EVIDENCE,
        **values,
    )

    assert resource.valid_from_order == 1
    assert resource.valid_until_order is None
