"""HTTP acceptance coverage for the development-only one-click safe pipeline."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from comic_agent.agents.timeline_agent import TimelineAgent
from comic_agent.api.pipeline import (
    _batch_summary,
    _gate2_safe_issue_codes,
    _parse_narrative_modes,
    _pipeline_retry_wait_seconds,
    _require_real_pipeline_opt_in,
    _save_pipeline_failure,
)
from comic_agent.config import Settings, get_settings
from comic_agent.main import create_app
from comic_agent.providers.mocks import LocalSafeDemoProvider, MockLLMProvider
from comic_agent.repositories.narrative_analysis_repository import NarrativeAnalysisRepository
from comic_agent.repositories.provider_circuit_repository import ProviderCircuitRepository

_OFFICIAL_TEXT = """下午四点，小林先到学校礼堂，在公告栏张贴志愿者招募海报。
十分钟后，天下起雨；小周撑着一把蓝色雨伞赶到礼堂。
小林把备用雨伞交给小周，两人随后一起进入礼堂。
活动开始时，小周仍拿着蓝色雨伞，小林已经不在公告栏旁。"""

_ALL_NARRATIVE_MODES = [
    "entity_extraction",
    "event_extraction",
    "claim_extraction",
    "knowledge_state_extraction",
    "state_change_extraction",
    "relationship_signal_extraction",
]


def test_gate2_safe_issue_codes_include_rejected_proposal_diagnostics() -> None:
    """Pipeline progress must expose Gate 2 codes without source text or raw output."""

    result = type(
        "Result",
        (),
        {
            "execution_issues": [type("Issue", (), {"code": "GATE2_EXECUTION_ERROR"})()],
            "decisions": [
                type(
                    "Decision",
                    (),
                    {"issues": [type("Issue", (), {"code": "REFERENCE_TARGET_NOT_FOUND"})()]},
                )()
            ],
        },
    )()

    assert _gate2_safe_issue_codes(result) == {
        "GATE2_EXECUTION_ERROR",
        "REFERENCE_TARGET_NOT_FOUND",
    }


def test_pipeline_accepts_only_distinct_known_requested_narrative_modes() -> None:
    assert _parse_narrative_modes(
        '["entity_extraction", "event_extraction"]'
    ) == ["entity_extraction", "event_extraction"]
    with pytest.raises(ValueError, match="distinct"):
        _parse_narrative_modes('["event_extraction", "event_extraction"]')
    with pytest.raises(ValueError, match="unsupported"):
        _parse_narrative_modes('["unknown_mode"]')


def test_pipeline_defaults_to_all_six_narrative_modes() -> None:
    assert _parse_narrative_modes(None) == _ALL_NARRATIVE_MODES


def test_batch_summary_marks_a_split_parent_with_successful_children_as_succeeded() -> None:
    """A completed split tree must not look like a planned batch in the Console."""

    run = SimpleNamespace(batches=[SimpleNamespace(batch_id="batch-1")])
    windows = [
        SimpleNamespace(batch_id="batch-1", status="SPLIT"),
        SimpleNamespace(batch_id="batch-1", status="SUCCEEDED"),
        SimpleNamespace(batch_id="batch-1", status="SUCCEEDED"),
    ]

    assert _batch_summary(run, windows) == {"total": 1, "status_counts": {"SUCCEEDED": 1}}


def test_overdue_pipeline_retry_checkpoint_is_immediately_eligible() -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    assert _pipeline_retry_wait_seconds(now - timedelta(seconds=1), now=now) == 0
    assert _pipeline_retry_wait_seconds(now + timedelta(seconds=30), now=now) == 5


def test_real_preflight_reuses_the_provider_instance_for_narrative_execution(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("COMIC_AGENT_ENV", "development")
    monkeypatch.setenv("COMIC_AGENT_FAKE_PIPELINE_DEMO", "false")
    monkeypatch.setenv("ENABLE_REAL_LLM", "true")
    monkeypatch.setenv("LLM_API_KEY", "test-local-key")
    get_settings.cache_clear()
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'preflight.db'}")
    if hasattr(app.state, "narrative_analyst_provider"):
        delattr(app.state, "narrative_analyst_provider")
    provider = LocalSafeDemoProvider()
    monkeypatch.setattr(
        "comic_agent.api.pipeline.build_openai_compatible_provider", lambda _: provider
    )
    session = app.state.session_factory()
    try:
        _require_real_pipeline_opt_in(
            True,
            app_state=app.state,
            circuit_repository=ProviderCircuitRepository(session),
        )
        assert app.state.narrative_analyst_provider is provider
    finally:
        session.close()


def test_pipeline_persists_an_explicit_six_mode_request(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, monkeypatch)
    modes = _ALL_NARRATIVE_MODES

    started = client.post(
        "/projects/six-mode-request/pipeline-runs/import-and-analyze",
        data={"narrative_modes": json.dumps(modes)},
        files={"file": ("official.txt", _OFFICIAL_TEXT.encode("utf-8"), "text/plain")},
    )

    assert started.status_code == 200
    run_id = started.json()["analysis_run_id"]
    run = client.get(f"/narrative-analysis-runs/{run_id}")
    assert run.status_code == 200
    assert run.json()["modes"] == modes


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


def _real_llm_client(tmp_path, monkeypatch) -> TestClient:  # type: ignore[no-untyped-def]
    """Exercise the real-request route with injected, network-free providers."""

    monkeypatch.setenv("COMIC_AGENT_ENV", "development")
    monkeypatch.setenv("COMIC_AGENT_FAKE_PIPELINE_DEMO", "false")
    monkeypatch.setenv("ENABLE_REAL_LLM", "true")
    monkeypatch.setenv("LLM_API_KEY", "test-local-key")
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "false")
    get_settings.cache_clear()
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'real-pipeline.db'}")
    app.state.narrative_analyst_provider = LocalSafeDemoProvider()
    app.state.timeline_agent = TimelineAgent(
        LocalSafeDemoProvider(), provider_model="test-real-llm-provider"
    )
    return TestClient(app)


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
    assert fixture.headers["content-type"].startswith("text/plain")
    assert fixture.content == Path("web_console/official_safe_pipeline_demo.txt").read_bytes()
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
    assert payload["batch_summary"] == {"total": 1, "status_counts": {"SUCCEEDED": 1}}
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


def test_one_click_pipeline_only_uses_real_provider_after_explicit_opt_in(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    client = _real_llm_client(tmp_path, monkeypatch)
    narrative_provider = client.app.state.narrative_analyst_provider

    status = client.get("/settings/llm/status")
    started = client.post(
        "/projects/real-opt-in/pipeline-runs/import-and-analyze",
        data={"real_llm_requested": "true"},
        files={"file": ("official.txt", _OFFICIAL_TEXT.encode("utf-8"), "text/plain")},
    )

    assert status.status_code == 200
    assert status.json()["real_pipeline_opt_in_available"] is True
    assert "test-local-key" not in status.text
    assert started.status_code == 200
    assert started.json()["real_llm_requested"] is True
    assert narrative_provider.calls == 6
    run_id = started.json()["analysis_run_id"]
    assert client.get(f"/pipeline-runs/{run_id}").json()["gate3"] == "APPROVED"


def test_one_click_real_pipeline_retries_a_waiting_provider_preflight(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """A transient preflight timeout must not terminally fail untouched windows."""

    class _FailsFirstPreflightProvider(LocalSafeDemoProvider):
        def __init__(self) -> None:
            super().__init__()
            self.preflight_calls = 0

        def preflight(self) -> None:
            self.preflight_calls += 1
            if self.preflight_calls == 1:
                raise TimeoutError("transient provider timeout")

    monkeypatch.setenv("PROVIDER_CIRCUIT_BACKOFF_SECONDS", "1")
    monkeypatch.setenv("PROVIDER_CIRCUIT_MAX_BACKOFF_SECONDS", "1")
    client = _real_llm_client(tmp_path, monkeypatch)
    provider = _FailsFirstPreflightProvider()
    client.app.state.narrative_analyst_provider = provider

    started = client.post(
        "/projects/preflight-retry/pipeline-runs/import-and-analyze",
        data={"real_llm_requested": "true"},
        files={"file": ("official.txt", _OFFICIAL_TEXT.encode("utf-8"), "text/plain")},
    )

    assert started.status_code == 200
    run = client.get(f"/pipeline-runs/{started.json()['analysis_run_id']}").json()
    assert provider.preflight_calls == 2
    assert run["narrative"] == "SUCCEEDED"
    assert run["pipeline_phase"] == "COMPLETED"
    assert run["pipeline_safe_issue_codes"] == []


def test_one_click_real_pipeline_stops_after_preflight_circuit_pauses(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """A permanently unavailable Provider consumes only the bounded preflight allowance."""

    class _FailingPreflightProvider(LocalSafeDemoProvider):
        def __init__(self) -> None:
            super().__init__()
            self.preflight_calls = 0

        def preflight(self) -> None:
            self.preflight_calls += 1
            raise TimeoutError("persistent provider timeout")

    monkeypatch.setenv("PROVIDER_CIRCUIT_FAILURE_THRESHOLD", "2")
    monkeypatch.setenv("PROVIDER_CIRCUIT_BACKOFF_SECONDS", "1")
    monkeypatch.setenv("PROVIDER_CIRCUIT_MAX_BACKOFF_SECONDS", "1")
    client = _real_llm_client(tmp_path, monkeypatch)
    provider = _FailingPreflightProvider()
    client.app.state.narrative_analyst_provider = provider

    started = client.post(
        "/projects/preflight-paused/pipeline-runs/import-and-analyze",
        data={"real_llm_requested": "true"},
        files={"file": ("official.txt", _OFFICIAL_TEXT.encode("utf-8"), "text/plain")},
    )

    assert started.status_code == 200
    run = client.get(f"/pipeline-runs/{started.json()['analysis_run_id']}").json()
    assert provider.preflight_calls == 2
    assert provider.calls == 0
    assert run["narrative"] == "NEEDS_HUMAN_ACTION"
    assert run["pipeline_phase"] == "NEEDS_HUMAN_ACTION"
    assert run["pipeline_safe_issue_codes"] == ["PROVIDER_CIRCUIT_OPEN", "PROVIDER_TIMEOUT"]


def test_one_click_real_llm_opt_in_missing_key_is_reported_by_durable_run(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("COMIC_AGENT_ENV", "development")
    monkeypatch.setenv("COMIC_AGENT_FAKE_PIPELINE_DEMO", "false")
    monkeypatch.setenv("ENABLE_REAL_LLM", "true")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    client = TestClient(create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'no-key.db'}"))

    response = client.post(
        "/projects/no-key/pipeline-runs/import-and-analyze",
        data={"real_llm_requested": "true"},
        files={"file": ("official.txt", _OFFICIAL_TEXT.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 200
    run_id = response.json()["analysis_run_id"]
    status = client.get(f"/pipeline-runs/{run_id}")
    assert status.status_code == 200
    assert status.json()["narrative"] == "FAILED"
    assert status.json()["pipeline_phase"] == "FAILED"
    assert status.json()["pipeline_safe_issue_codes"] == ["PROVIDER_API_KEY_MISSING"]
    assert "PROVIDER_API_KEY_MISSING" in status.json()["safe_issue_codes"]
    assert client.get("/projects/no-key/documents").status_code == 200


def test_one_click_pipeline_exposes_sanitized_narrative_failure_summary(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, monkeypatch)
    client.app.state.narrative_analyst_provider = MockLLMProvider(response={})

    started = client.post(
        "/projects/failure-summary/pipeline-runs/import-and-analyze",
        files={"file": ("official.txt", _OFFICIAL_TEXT.encode("utf-8"), "text/plain")},
    )

    assert started.status_code == 200
    status = client.get(f"/pipeline-runs/{started.json()['analysis_run_id']}")

    assert status.status_code == 200
    payload = status.json()
    assert payload["narrative"] == "NEEDS_HUMAN_ACTION"
    assert payload["narrative_failure_summary"] == {
        "failed_window_count": 6,
        "failure_categories": ["SCHEMA_REPAIR_EXHAUSTED"],
        "recommended_actions": [
            "automatic schema recovery stopped; inspect safe rule codes"
        ],
    }
    assert "error_message" not in status.text
    assert "raw_output" not in status.text


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
    assert provider.calls == 7


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
    assert provider.calls == 6


def test_pipeline_status_reports_gate2_pending_for_saved_aggregate_without_route(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, monkeypatch)
    started = client.post(
        "/projects/gate2-pending/pipeline-runs/import-and-analyze",
        files={"file": ("official.txt", _OFFICIAL_TEXT.encode("utf-8"), "text/plain")},
    )
    run_id = started.json()["analysis_run_id"]
    session = client.app.state.session_factory()
    try:
        repository = NarrativeAnalysisRepository(session)
        run = repository.get_run(run_id)
        assert run is not None
        repository.save_run(
            run.model_copy(
                update={
                    "schema_version": "1.5",
                    "review_gate2_result": None,
                    "review_gate2_route": None,
                    "gate2_handoff": None,
                }
            )
        )
    finally:
        session.close()

    response = client.get(f"/pipeline-runs/{run_id}")

    assert response.status_code == 200
    assert response.json()["gate2"] == "GATE2_PENDING"
    assert "quote_text" not in response.text
    assert _OFFICIAL_TEXT not in response.text


def test_background_failure_does_not_rewrite_a_completed_narrative_run(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """A downstream worker error must retain a completed Narrative checkpoint for resume."""

    client = _client(tmp_path, monkeypatch)
    started = client.post(
        "/projects/preserve-narrative/pipeline-runs/import-and-analyze",
        files={"file": ("official.txt", _OFFICIAL_TEXT.encode("utf-8"), "text/plain")},
    )
    run_id = started.json()["analysis_run_id"]

    _save_pipeline_failure(
        client.app.state.session_factory,
        run_id,
        ["PIPELINE_WORKER_FAILED"],
    )

    status = client.get(f"/pipeline-runs/{run_id}").json()
    assert status["narrative"] == "SUCCEEDED"
    assert status["pipeline_phase"] == "FAILED"
    assert status["pipeline_safe_issue_codes"] == ["PIPELINE_WORKER_FAILED"]
