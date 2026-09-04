"""Panel text QA stays proposal-only and source bounded."""

import pytest

from comic_agent.agents.panel_text_qa import PanelTextQAAgent
from comic_agent.providers.openai_compatible import ProviderResponseError
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.comic_planning import PanelPlanV1
from comic_agent.schemas.source import SourceChunkV1


class RecordingProvider:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    def structured_generate(self, request, output_model):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        response = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
        return output_model.model_validate(response)


def _chunk() -> SourceChunkV1:
    text = "New students arrive at the campus gate and receive welcome packs."
    return SourceChunkV1(
        chunk_id="chunk-1",
        document_id="document-1",
        chapter_id="chapter-1",
        project_id="project-1",
        order=0,
        text=text,
        checksum="checksum-1",
    )


def _panel() -> PanelPlanV1:
    chunk = _chunk()
    return PanelPlanV1(
        panel_id="panel-1",
        project_id="project-1",
        scene_id="scene-1",
        index=0,
        storybible_bundle_id="storybible-1",
        timeline_bundle_id="timeline-1",
        panel_purpose="Show the approved arrival",
        narrative_beat="New students arrive at the campus gate",
        aspect_ratio="1:1",
        shot_type="WIDE",
        camera_angle="EYE_LEVEL",
        composition="Students enter through the gate",
        background="campus gate",
        related_event_ids=["event-1"],
        evidence_refs=[EvidenceRefV1(chunk_id=chunk.chunk_id, quote_text=chunk.text)],
    )


def test_panel_text_qa_reuses_exact_source_and_returns_only_a_proposal() -> None:
    provider = RecordingProvider(
        [{"findings": [], "summary": "All planned facts are supported.", "confidence": 0.96}]
    )

    proposal = PanelTextQAAgent(provider).run(
        project_id="project-1", panels=[_panel()], source_chunks=[_chunk()]
    )

    assert proposal.status == "CANDIDATE"
    assert proposal.passed is True
    assert proposal.checked_panel_ids == ["panel-1"]
    assert proposal.evidence_refs == _panel().evidence_refs
    assert _chunk().text in str(provider.requests[0])


def test_panel_text_qa_maps_provider_indexes_to_trusted_ids_and_evidence() -> None:
    provider = RecordingProvider(
        [
            {
                "findings": [
                    {
                        "panel_index": 0,
                        "issue_code": "UNSUPPORTED_PANEL_FACT",
                        "severity": "BLOCKING",
                        "evidence_indexes": [0],
                        "summary": "The planned action is not supported.",
                    }
                ],
                "summary": "One blocking mismatch.",
                "confidence": 0.9,
            }
        ]
    )

    proposal = PanelTextQAAgent(provider).run(
        project_id="project-1", panels=[_panel()], source_chunks=[_chunk()]
    )

    assert proposal.passed is False
    assert proposal.findings[0].panel_id == "panel-1"
    assert proposal.findings[0].evidence_refs == _panel().evidence_refs


def test_panel_text_qa_repairs_once_then_rejects_unknown_indexes() -> None:
    invalid = {
        "findings": [
            {
                "panel_index": 99,
                "issue_code": "EVENT_MISMATCH",
                "severity": "BLOCKING",
                "evidence_indexes": [],
                "summary": "Unknown panel.",
            }
        ],
        "summary": "Invalid indexed result.",
        "confidence": 0.8,
    }
    provider = RecordingProvider([invalid])

    with pytest.raises(ProviderResponseError, match="unknown panel"):
        PanelTextQAAgent(provider).run(
            project_id="project-1", panels=[_panel()], source_chunks=[_chunk()]
        )

    assert len(provider.requests) == 2
    assert "PANEL_INDEX_OUT_OF_RANGE" in str(provider.requests[1])
