"""Deterministic Comic Planning and Panel Planning coverage."""

from datetime import UTC, datetime

import pytest

from comic_agent.schemas import (
    ApprovedStoryBibleBundleV1,
    ApprovedTimelineBundleV1,
    EvidenceRefV1,
    PanelPlanV1,
    ScenePlanV1,
    StoryBibleReviewMetadataV1,
    StoryEntityProfileV1,
    StoryEntityStateV1,
    TemporalRelationProposalV1,
)
from comic_agent.schemas.base import RealityLayer
from comic_agent.schemas.narrative import EventProposalV1
from comic_agent.schemas.source import SourceChunkV1
from comic_agent.services.comic_planning_service import ComicPlanningService
from comic_agent.services.panel_planning_service import PanelPlanningService
from scripts import export_json_schemas

EVIDENCE = EvidenceRefV1(
    chunk_id="chunk-1",
    quote_start=0,
    quote_end=18,
    quote_text="Lin opens the gate",
)


def timeline_bundle() -> ApprovedTimelineBundleV1:
    return ApprovedTimelineBundleV1(
        bundle_id="timeline-bundle-1",
        project_id="project-1",
        source_approved_proposal_bundle_id="gate2-bundle-1",
        source_gate2_review_id="gate2-review-1",
        source_gate2_route_id="gate2-route-1",
        timeline_run_id="timeline-run-1",
        gate3_review_id="gate3-review-1",
        gate3_route_id="gate3-route-1",
        temporal_relations=[
            TemporalRelationProposalV1(
                proposal_id="relation-1",
                source_event_id="event-1",
                target_event_id="event-2",
                relation="BEFORE",
                evidence_refs=[EVIDENCE],
                confidence=1.0,
            )
        ],
        event_ids=["event-1", "event-2"],
        evidence_refs=[EVIDENCE],
    )


def storybible_bundle() -> ApprovedStoryBibleBundleV1:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return ApprovedStoryBibleBundleV1(
        bundle_id="storybible-bundle-1",
        project_id="project-1",
        source_storybible_run_id="storybible-run-1",
        snapshot_hash="snapshot-hash-1",
        entities=[
            StoryEntityProfileV1(
                profile_id="character-lin",
                project_id="project-1",
                entity_kind="PERSON",
                canonical_name="Lin",
                evidence_refs=[EVIDENCE],
            ),
            StoryEntityProfileV1(
                profile_id="location-gate",
                project_id="project-1",
                entity_kind="LOCATION",
                canonical_name="North Gate",
                evidence_refs=[EVIDENCE],
            ),
        ],
        state_changes=[
            StoryEntityStateV1(
                state_id="state-1",
                project_id="project-1",
                profile_id="character-lin",
                state={"activity": "opens the gate"},
                triggering_event_id="event-1",
                evidence_refs=[EVIDENCE],
            ),
            StoryEntityStateV1(
                state_id="state-2",
                project_id="project-1",
                profile_id="character-lin",
                state={"activity": "rests"},
                triggering_event_id="event-2",
                evidence_refs=[EVIDENCE],
            ),
            StoryEntityStateV1(
                state_id="state-3",
                project_id="project-1",
                profile_id="location-gate",
                state={"condition": "open"},
                triggering_event_id="event-1",
                evidence_refs=[EVIDENCE],
            ),
        ],
        evidence_refs=[EVIDENCE],
        review_metadata=StoryBibleReviewMetadataV1(
            review_id="review-1",
            decision="APPROVE",
            proposal_hash="proposal-hash-1",
            source_approved_timeline_bundle_id="timeline-bundle-1",
            reviewed_at=now,
            frozen_at=now,
        ),
    )


def test_storybible_and_timeline_generate_scene_plans() -> None:
    scenes = ComicPlanningService().plan(
        storybible=storybible_bundle(), timeline=timeline_bundle()
    )

    assert len(scenes) == 2
    assert scenes[0].related_event_ids == ["event-1"]
    assert scenes[0].character_ids == ["character-lin"]
    assert scenes[0].evidence_refs == [EVIDENCE]
    assert scenes[1].related_event_ids == ["event-2"]
    assert scenes[0].storybible_bundle_id == "storybible-bundle-1"
    assert scenes[0].timeline_bundle_id == "timeline-bundle-1"


def test_comic_planning_uses_approved_event_summary_and_scoped_evidence() -> None:
    second_evidence = EvidenceRefV1(chunk_id="chunk-2", quote_text="Lin rests")
    timeline = timeline_bundle().model_copy(
        update={"evidence_refs": [EVIDENCE, second_evidence]}
    )
    events = [
        EventProposalV1(
            proposal_id="event-1",
            event_type="ACTION",
            summary="Lin opens the North Gate.",
            evidence_refs=[EVIDENCE],
            confidence=1.0,
            reality_layer=RealityLayer.PRIMARY,
        ),
        EventProposalV1(
            proposal_id="event-2",
            event_type="ACTION",
            summary="Lin rests inside.",
            evidence_refs=[second_evidence],
            confidence=1.0,
            reality_layer=RealityLayer.PRIMARY,
        ),
    ]

    scenes = ComicPlanningService().plan(
        storybible=storybible_bundle(), timeline=timeline, events=events
    )

    assert scenes[0].summary == "Lin opens the North Gate."
    assert scenes[0].evidence_refs == [EVIDENCE]
    assert scenes[1].summary == "Lin rests inside."
    assert scenes[1].evidence_refs == [second_evidence]


def test_scene_plan_generates_image_agent_ready_panel_plan() -> None:
    scene = ComicPlanningService().plan(
        storybible=storybible_bundle(), timeline=timeline_bundle()
    )[0]

    panel = PanelPlanningService().plan(scene=scene, storybible=storybible_bundle())

    assert panel.scene_id == scene.scene_id
    assert panel.index == 0
    assert panel.character_ids == scene.character_ids
    assert panel.related_event_ids == scene.related_event_ids
    assert panel.evidence_refs == scene.evidence_refs
    assert panel.panel_purpose == scene.purpose
    assert panel.narrative_beat == scene.summary
    assert panel.aspect_ratio == "1:1"
    assert panel.character_state_ids == ["state-1"]
    assert panel.character_actions == {"character-lin": "opens the gate"}
    assert panel.location_entity_id == "location-gate"
    assert panel.background == "North Gate"
    assert panel.shot_type == "MEDIUM"
    assert panel.camera_angle == "EYE_LEVEL"
    assert panel.caption == scene.summary


def test_panel_planning_extracts_only_source_grounded_spoken_chinese_dialogue() -> None:
    text = "志愿者指向服务台，说：“同学，欢迎来到中国科大！”路牌写着“报到处”。"
    evidence = EvidenceRefV1(
        chunk_id="chunk-dialogue",
        quote_start=0,
        quote_end=len(text),
        quote_text=text,
    )
    chunk = SourceChunkV1(
        chunk_id="chunk-dialogue",
        document_id="document-1",
        chapter_id="chapter-1",
        project_id="project-1",
        order=0,
        text=text,
        checksum="checksum-dialogue",
    )
    scene = ComicPlanningService().plan(
        storybible=storybible_bundle(), timeline=timeline_bundle()
    )[0].model_copy(update={"summary": text, "evidence_refs": [evidence]})

    panel = PanelPlanningService().plan(
        scene=scene,
        storybible=storybible_bundle(),
        source_chunks=[chunk],
    )

    assert panel.dialogue == ["同学，欢迎来到中国科大！"]
    assert panel.caption is None


def test_unknown_character_state_is_not_generated() -> None:
    scene = ComicPlanningService().plan(
        storybible=storybible_bundle(), timeline=timeline_bundle()
    )[0]

    panel = PanelPlanningService().plan(scene=scene, storybible=storybible_bundle())

    assert "state-2" not in panel.character_state_ids
    assert "rests" not in panel.character_actions.values()


def test_location_reference_must_be_canonical() -> None:
    scene = ComicPlanningService().plan(
        storybible=storybible_bundle(), timeline=timeline_bundle()
    )[0].model_copy(update={"location": "invented-location"})

    with pytest.raises(ValueError, match="canonical StoryBible location"):
        PanelPlanningService().plan(scene=scene, storybible=storybible_bundle())


def test_panel_rejects_character_outside_storybible() -> None:
    valid = ComicPlanningService().plan(
        storybible=storybible_bundle(), timeline=timeline_bundle()
    )[0]
    invalid = valid.model_copy(update={"character_ids": ["invented-character"]})

    with pytest.raises(ValueError, match="characters must come from"):
        PanelPlanningService().plan(scene=invalid, storybible=storybible_bundle())


def test_scene_rejects_unapproved_timeline_lineage() -> None:
    timeline = timeline_bundle().model_copy(update={"bundle_id": "other-timeline"})

    with pytest.raises(ValueError, match="freeze lineage"):
        ComicPlanningService().plan(storybible=storybible_bundle(), timeline=timeline)


def test_comic_planning_json_schema_export(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)

    export_json_schemas.main()

    output = tmp_path / "schema_exports"
    for schema_name in ("ComicPlanningInputV1", "ScenePlanV1", "PanelPlanV1"):
        assert (output / f"{schema_name}.json").exists()


def test_scene_schema_requires_event_and_evidence_lineage() -> None:
    required = set(ScenePlanV1.model_json_schema()["required"])

    assert {"related_event_ids", "evidence_refs", "timeline_bundle_id"} <= required


def test_panel_schema_requires_image_agent_contract_fields() -> None:
    required = set(PanelPlanV1.model_json_schema()["required"])

    assert {
        "panel_purpose",
        "narrative_beat",
        "aspect_ratio",
        "related_event_ids",
        "evidence_refs",
    } <= required
