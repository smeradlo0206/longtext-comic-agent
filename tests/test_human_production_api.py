"""Runtime wiring coverage for the human-approved StoryBible production path."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from comic_agent.config import Settings, get_settings
from comic_agent.main import create_app
from comic_agent.schemas.base import EvidenceRefV1
from comic_agent.schemas.storybible import (
    CommitPlanV1,
    ProfileUpdateProposalV1,
    StoryBibleCuratorProposalV1,
    StoryBibleProductionRunV1,
    StoryEntityProfileV1,
)
from comic_agent.services.comic_planning_input_adapter import ComicPlanningInputAdapter

_TEXT = """第一章
下午四点，小林先到学校礼堂，在公告栏张贴志愿者招募海报。
十分钟后，小周撑着一把蓝色雨伞赶到礼堂。
"""


class _FakeCurator:
    """Network-free Curator replacement used only by the API integration test."""

    class spec:
        max_context_chunks = 3

    def run(self, context: Any, chunk_texts: dict[str, str]) -> StoryBibleCuratorProposalV1:
        chunk_id = context.source_chunk_ids[0]
        quote = chunk_texts[chunk_id][:20]
        evidence = EvidenceRefV1(chunk_id=chunk_id, quote_text=quote)
        profile = StoryEntityProfileV1(
            profile_id="api-demo-profile",
            project_id=context.project_id,
            entity_kind="PERSON",
            canonical_name="小林",
            evidence_refs=[evidence],
        )
        update = ProfileUpdateProposalV1(
            update_id="api-demo-profile-update",
            project_id=context.project_id,
            profile=profile,
            evidence_refs=[evidence],
        )
        return StoryBibleCuratorProposalV1(
            proposal_id="api-demo-storybible-proposal",
            project_id=context.project_id,
            commit_plan=CommitPlanV1(
                commit_plan_id="api-demo-storybible-plan",
                project_id=context.project_id,
                source_proposal_id="api-demo-storybible-proposal",
                content_hash="untrusted-api-demo",
                updates=[update],
                evidence_refs=[evidence],
            ),
            evidence_refs=[evidence],
            confidence=0.9,
        )


def _client(tmp_path, monkeypatch) -> TestClient:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("COMIC_AGENT_ENV", "development")
    monkeypatch.setenv("COMIC_AGENT_FAKE_PIPELINE_DEMO", "true")
    monkeypatch.setenv("ENABLE_REAL_LLM", "false")
    monkeypatch.setenv("COMIC_AGENT_FAKE_PIPELINE_SCENARIO", "success")
    get_settings.cache_clear()
    return TestClient(create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'pipeline.db'}"))


def test_fake_pipeline_materializes_dossier_then_runs_human_approved_production(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """TXT through Gate 3 must be consumable by the new human-production APIs."""

    client = _client(tmp_path, monkeypatch)
    started = client.post(
        "/projects/human-api-demo/pipeline-runs/import-and-analyze",
        files={"file": ("official.txt", _TEXT.encode("utf-8"), "text/plain")},
    )
    assert started.status_code == 200
    analysis_run_id = started.json()["analysis_run_id"]

    dossier_response = client.get(
        f"/projects/human-api-demo/pipeline-runs/{analysis_run_id}/production-dossiers"
    )
    assert dossier_response.status_code == 200
    dossiers = dossier_response.json()["dossiers"]
    assert len(dossiers) == 1
    dossier = dossiers[0]
    assert dossier["dossier_id"]
    assert dossier["content_hash"]
    assert dossier["timeline_review_material_id"]

    reviewed = client.post(
        f"/projects/human-api-demo/production-dossiers/{dossier['dossier_id']}/human-review",
        json={
            "project_id": "human-api-demo",
            "dossier_id": dossier["dossier_id"],
            "decision": "APPROVE",
            "reviewer_id": "demo-reviewer",
        },
    )
    assert reviewed.status_code == 200
    review = reviewed.json()
    assert review["status"] == "READY_FOR_STORYBIBLE"
    review_id = review["review_run"]["review_id"]

    client.app.state.storybible_curator = _FakeCurator()
    monkeypatch.setenv("COMIC_AGENT_FAKE_PIPELINE_DEMO", "false")
    monkeypatch.setattr(
        "comic_agent.api.human_production.get_settings",
        lambda: Settings(enable_real_llm=True, comic_agent_env="development"),
    )
    executed = client.post(
        f"/projects/human-api-demo/storybible-production/human-reviews/{review_id}/execute",
        params={"real_llm_requested": "true"},
    )

    assert executed.status_code == 200
    run = executed.json()
    assert run["status"] == "SUCCEEDED"
    assert run["authorization_kind"] == "HUMAN_APPROVED"
    assert run["human_review_id"] == review_id
    assert run["curator_proposal"] is not None
    comic_planning_input = ComicPlanningInputAdapter().build(
        StoryBibleProductionRunV1.model_validate(run)
    )
    assert comic_planning_input.storybible_production_run_id == run["run_id"]
    assert comic_planning_input.human_review_id == review_id
