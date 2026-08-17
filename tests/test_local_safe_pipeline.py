"""HTTP acceptance coverage for the development-only one-click safe pipeline."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from comic_agent.config import Settings, get_settings
from comic_agent.main import create_app

_OFFICIAL_TEXT = """下午四点，小林先到学校礼堂，在公告栏张贴志愿者招募海报。
十分钟后，天下起雨；小周撑着一把蓝色雨伞赶到礼堂。
小林把备用雨伞交给小周，两人随后一起进入礼堂。
活动开始时，小周仍拿着蓝色雨伞，小林已经不在公告栏旁。"""


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client(tmp_path, monkeypatch, *, scenario: str = "success") -> TestClient:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("COMIC_AGENT_ENV", "development")
    monkeypatch.setenv("COMIC_AGENT_FAKE_PIPELINE_DEMO", "true")
    monkeypatch.setenv("ENABLE_REAL_LLM", "false")
    monkeypatch.setenv("COMIC_AGENT_FAKE_PIPELINE_SCENARIO", scenario)
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "false")
    get_settings.cache_clear()
    return TestClient(create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'pipeline.db'}"))


def test_one_click_pipeline_imports_and_reaches_gate3_approved(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, monkeypatch)

    console = client.get("/console/")
    fixture = client.get("/console/official_safe_pipeline_demo.txt")
    started = client.post(
        "/projects/local-demo/pipeline-runs/import-and-analyze",
        data={"project_name": "Local safe demo"},
        files={"file": ("official.txt", _OFFICIAL_TEXT.encode("utf-8"), "text/plain")},
    )

    assert console.status_code == 200
    assert 'id="safePipeline"' in console.text
    assert "window.location.origin" in console.text
    assert fixture.status_code == 200
    assert fixture.text.strip() == _OFFICIAL_TEXT
    assert started.status_code == 200
    run_id = started.json()["analysis_run_id"]
    status = client.get(f"/pipeline-runs/{run_id}")
    gate2_bundle = client.get(f"/narrative-analysis-runs/{run_id}/approved-proposal-bundle")

    assert status.status_code == 200
    payload = status.json()
    assert payload["gate1"] == "APPROVED"
    assert payload["narrative"] == "SUCCEEDED"
    assert payload["gate2"] == "APPROVED"
    assert payload["timeline"] == "APPROVED"
    assert payload["gate3"] == "APPROVED"
    assert payload["approved_timeline_bundle_id"]
    assert "quote_text" not in status.text
    assert _OFFICIAL_TEXT not in status.text
    assert gate2_bundle.status_code == 200
    source_bundle_id = gate2_bundle.json()["bundle_id"]
    approved = client.get(
        f"/projects/local-demo/timeline-gate3/{source_bundle_id}/approved-bundle"
    )
    assert approved.status_code == 200
    assert approved.json()["source_approved_proposal_bundle_id"] == source_bundle_id
    assert "quote_text" not in approved.text


def test_gate1_rejection_stops_one_click_pipeline_before_narrative(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, monkeypatch)
    provider = client.app.state.narrative_analyst_provider
    unsafe_text = "第一章\n\n正常段落。\ufffd\n"

    response = client.post(
        "/projects/blocked-demo/pipeline-runs/import-and-analyze",
        files={"file": ("unsafe.txt", unsafe_text.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["gate1"]["decision"] == "NEEDS_HUMAN_REVIEW"
    assert unsafe_text not in response.text
    assert provider.calls == 0


def test_fake_pipeline_configuration_rejects_production_and_real_llm() -> None:
    for values in (
        {"comic_agent_env": "production", "fake_pipeline_demo": True},
        {
            "comic_agent_env": "development",
            "fake_pipeline_demo": True,
            "enable_real_llm": True,
        },
    ):
        try:
            Settings(_env_file=None, **values)
        except ValidationError:
            continue
        raise AssertionError("unsafe Fake pipeline configuration was accepted")


def test_one_click_pipeline_recovers_gate2_once_with_the_original_scope(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, monkeypatch, scenario="recover_gate2")
    provider = client.app.state.narrative_analyst_provider

    started = client.post(
        "/projects/gate2-recovery/pipeline-runs/import-and-analyze",
        files={"file": ("official.txt", _OFFICIAL_TEXT.encode("utf-8"), "text/plain")},
    )

    assert started.status_code == 200
    status = client.get(f"/pipeline-runs/{started.json()['analysis_run_id']}").json()
    assert status["gate2"] == "APPROVED"
    assert status["narrative_recovery"] == "SUCCEEDED"
    assert status["narrative_recovery_attempts"] == 1
    assert status["timeline"] == "APPROVED"
    assert provider.calls == 2


def test_one_click_pipeline_recovers_gate3_once_with_the_same_gate2_bundle(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, monkeypatch, scenario="recover_gate3")
    timeline_provider = client.app.state.timeline_agent._provider

    started = client.post(
        "/projects/gate3-recovery/pipeline-runs/import-and-analyze",
        files={"file": ("official.txt", _OFFICIAL_TEXT.encode("utf-8"), "text/plain")},
    )

    assert started.status_code == 200
    status = client.get(f"/pipeline-runs/{started.json()['analysis_run_id']}").json()
    assert status["gate3"] == "APPROVED"
    assert status["timeline_recovery"] == "SUCCEEDED"
    assert status["timeline_recovery_budget"]["attempts_used"] == 1
    assert timeline_provider.calls == 12


def test_double_click_reuses_the_durable_pipeline_run_without_a_second_provider_call(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, monkeypatch)
    provider = client.app.state.narrative_analyst_provider
    request = {
        "files": {"file": ("official.txt", _OFFICIAL_TEXT.encode("utf-8"), "text/plain")}
    }

    first = client.post("/projects/idempotent-demo/pipeline-runs/import-and-analyze", **request)
    second = client.post("/projects/idempotent-demo/pipeline-runs/import-and-analyze", **request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["analysis_run_id"] == second.json()["analysis_run_id"]
    assert provider.calls == 1
