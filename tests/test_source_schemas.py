import pytest
from pydantic import ValidationError

from comic_agent.schemas.base import EvidenceRefV1, RealityLayer
from comic_agent.schemas.narrative import (
    EntityProposalV1,
    EventProposalV1,
    TemporalRelationProposalV1,
)
from comic_agent.schemas.source import FidelityMode, ProjectSpecV1, ProjectType
from comic_agent.schemas.visual import PanelSpecV1


def test_project_spec_rejects_invalid_enum() -> None:
    with pytest.raises(ValidationError):
        ProjectSpecV1(
            id="project-1",
            name="Demo",
            project_type="NOVEL",
            fidelity_mode=FidelityMode.CANON_STRICT,
            output_format="PAGES",
            reading_direction="LTR",
            allow_new_events=False,
            allow_new_dialogue=False,
            allow_event_reordering=False,
            allow_visual_compression=True,
            allow_dialogue_splitting=True,
            require_source_traceability=True,
            max_auto_repairs=3,
            budget_limit=100,
        )


def test_confidence_out_of_bounds_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EntityProposalV1(
            proposal_id="proposal-1",
            entity_type="CHARACTER",
            canonical_name="Lin Xia",
            aliases=[],
            evidence_refs=[EvidenceRefV1(chunk_id="chunk-1")],
            confidence=1.5,
        )


def test_evidence_ref_requires_valid_range() -> None:
    with pytest.raises(ValidationError):
        EvidenceRefV1(chunk_id="chunk-1", quote_start=10, quote_end=5)


def test_temporal_relation_rejects_self_loop() -> None:
    with pytest.raises(ValidationError):
        TemporalRelationProposalV1(
            proposal_id="proposal-1",
            source_event_id="event-1",
            target_event_id="event-1",
            relation="BEFORE",
            offset_value=None,
            offset_unit=None,
            evidence_refs=[EvidenceRefV1(chunk_id="chunk-1")],
            confidence=0.9,
        )


def test_unknown_temporal_relation_rejects_offset() -> None:
    with pytest.raises(ValidationError):
        TemporalRelationProposalV1(
            proposal_id="proposal-1",
            source_event_id="event-1",
            target_event_id="event-2",
            relation="UNKNOWN",
            offset_value=3,
            offset_unit="days",
            evidence_refs=[],
            confidence=0.5,
        )


def test_panel_spec_forbids_provider_fields() -> None:
    with pytest.raises(ValidationError):
        PanelSpecV1(
            panel_id="panel-1",
            page_id="page-1",
            scene_id="scene-1",
            source_chunk_ids=["chunk-1"],
            story_time_ref="event-1",
            character_bindings={},
            shot_type="medium",
            camera_angle="eye-level",
            must_show=["umbrella"],
            must_not_show=[],
            reserved_text_regions=[],
            provider="forbidden",
        )


def test_event_proposal_contains_evidence_ref() -> None:
    event = EventProposalV1(
        proposal_id="proposal-1",
        event_type="handoff",
        summary="Chen Ye gives Lin Xia an umbrella.",
        participant_ids=["char-chen", "char-lin"],
        location_id="loc-playground",
        evidence_refs=[EvidenceRefV1(chunk_id="chunk-1", quote_text="递给她")],
        confidence=0.91,
        reality_layer=RealityLayer.PRIMARY,
    )

    assert event.evidence_refs[0].chunk_id == "chunk-1"


def test_event_proposal_rejects_empty_evidence_refs() -> None:
    with pytest.raises(ValidationError):
        EventProposalV1(
            proposal_id="proposal-1",
            event_type="MOCK_EVENT",
            summary="A mock event.",
            evidence_refs=[],
            confidence=1.0,
            reality_layer=RealityLayer.PRIMARY,
        )


def test_event_proposal_rejects_blank_summary() -> None:
    with pytest.raises(ValidationError):
        EventProposalV1(
            proposal_id="proposal-1",
            event_type="MOCK_EVENT",
            summary="",
            evidence_refs=[EvidenceRefV1(chunk_id="chunk-1")],
            confidence=1.0,
            reality_layer=RealityLayer.PRIMARY,
        )


def test_project_spec_valid_example() -> None:
    project = ProjectSpecV1(
        id="project-1",
        name="Golden Novel",
        project_type=ProjectType.LONG_NOVEL,
        fidelity_mode=FidelityMode.CANON_STRICT,
        output_format="PAGES",
        reading_direction="LTR",
        allow_new_events=False,
        allow_new_dialogue=False,
        allow_event_reordering=False,
        allow_visual_compression=True,
        allow_dialogue_splitting=True,
        require_source_traceability=True,
        max_auto_repairs=3,
        budget_limit=100,
    )

    assert project.model_dump()["schema_version"] == "1.0"
