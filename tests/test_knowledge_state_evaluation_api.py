from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.config import get_settings
from comic_agent.main import create_app
from comic_agent.providers.openai_compatible import (
    ProviderHttpError,
    ProviderNetworkError,
    ProviderResponseError,
    ProviderTimeoutError,
)


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'evaluation_api.db'}")
    )


def _heard_batch() -> dict[str, object]:
    return {
        "batch_id": "offline-evaluation-batch",
        "states": [
            {
                "proposal_id": "offline-proposal",
                "subject": {
                    "mention_text": "林舟",
                    "entity_proposal_id": None,
                    "resolution_status": "UNRESOLVED",
                },
                "target": {
                    "target_kind": "WORLD_FACT",
                    "target_text": "城门已经封锁",
                    "proposal_id": None,
                    "proposal_schema": None,
                    "resolution_status": "UNRESOLVED",
                },
                "epistemic_status": "HEARD",
                "epistemic_basis": "HEARD",
                "reality_layer": "PRIMARY",
                "evidence_refs": [
                    {"chunk_id": "fixture-heard-1", "quote_text": "林舟听掌柜说城门已经封锁。"}
                ],
                "confidence": 0.9,
            }
        ],
    }


class FakeProvider:
    def __init__(self) -> None:
        self.calls = 0

    def structured_generate(self, request, response_model):  # type: ignore[no-untyped-def]
        self.calls += 1
        return response_model.model_validate(_heard_batch())


class SchemaRecoveryProvider:
    def __init__(self, failures: int = 1) -> None:
        self.calls = 0
        self.failures = failures
        self.contexts: list[dict[str, object]] = []

    def structured_generate(self, request, response_model):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.contexts.append(request)
        if self.calls <= self.failures:
            raise ProviderResponseError(
                "provider raw content must not escape",
                diagnostics={
                    "schema_error_kind": "validation_error",
                "schema_error_field_paths": ["states", "0", "target"],
                "schema_error_rule_codes": ["TARGET_REFERENCE_MUST_STAY_UNRESOLVED"],
                "expected_output_schema": "KnowledgeStateProposalBatchV1",
                },
            )
        return response_model.model_validate(_heard_batch())


def test_evaluation_api_lists_details_and_evaluates_without_provider(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        case_list = client.get("/knowledge-state-evaluation/cases")
        detail = client.get("/knowledge-state-evaluation/cases/heard-world-fact-positive")
        evaluated = client.post(
            "/knowledge-state-evaluation/cases/heard-world-fact-positive/evaluate",
            json={"batch": _heard_batch()},
        )

    assert case_list.status_code == 200
    assert len(case_list.json()) == 12
    assert "source_chunks" not in case_list.json()[0]
    assert detail.status_code == 200
    assert detail.json()["fixture_origin"] == "SYNTHETIC"
    assert evaluated.status_code == 200
    assert evaluated.json()["passed"] is True


def test_evaluation_api_builds_a_batch_report_without_provider(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/knowledge-state-evaluation/report",
            json={
                "evaluations": [
                    {
                        "case_id": "heard-world-fact-positive",
                        "batch": _heard_batch(),
                    },
                    {
                        "case_id": "empty-batch-baseline",
                        "batch": {"batch_id": "empty-report", "states": []},
                    },
                ]
            },
        )

    assert response.status_code == 200
    assert response.json()["evaluated_case_count"] == 2
    assert response.json()["passed_case_count"] == 2
    assert response.json()["evidence_pass_rate"] == 1.0


def test_real_run_requires_explicit_server_opt_in(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ENABLE_REAL_LLM", "false")
    get_settings.cache_clear()
    try:
        with _client(tmp_path) as client:
            omitted_opt_in = client.post(
                "/knowledge-state-evaluation/cases/heard-world-fact-positive/run",
                json={"real_llm_requested": False},
            )
            disabled = client.post(
                "/knowledge-state-evaluation/cases/heard-world-fact-positive/run",
                json={"real_llm_requested": True},
            )
    finally:
        get_settings.cache_clear()

    assert omitted_opt_in.status_code == 400
    assert disabled.status_code == 409


def test_explicit_real_run_uses_only_the_injected_fake_provider(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ENABLE_REAL_LLM", "true")
    get_settings.cache_clear()
    fake_provider = FakeProvider()
    try:
        app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'fake_provider.db'}")
        app.state.narrative_analyst_provider = fake_provider
        with TestClient(app) as client:
            response = client.post(
                "/knowledge-state-evaluation/cases/heard-world-fact-positive/run",
                json={"real_llm_requested": True},
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["evaluation"]["passed"] is True
    assert fake_provider.calls == 1


def test_schema_failure_gets_one_recovery_retry_and_returns_success(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ENABLE_REAL_LLM", "true")
    get_settings.cache_clear()
    provider = SchemaRecoveryProvider()
    try:
        app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'recovery.db'}")
        app.state.narrative_analyst_provider = provider
        with TestClient(app) as client:
            response = client.post(
                "/knowledge-state-evaluation/cases/heard-world-fact-positive/run",
                json={"real_llm_requested": True},
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["status"] == "SUCCEEDED"
    assert provider.calls == 2
    assert provider.contexts[0]["input_context"].get("output_recovery") is None
    assert provider.contexts[1]["input_context"]["output_recovery"] == "schema_validation"
    assert provider.contexts[1]["input_context"]["schema_error_rule_codes"] == [
        "TARGET_REFERENCE_MUST_STAY_UNRESOLVED"
    ]


def test_second_schema_failure_is_typed_and_not_a_500(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ENABLE_REAL_LLM", "true")
    get_settings.cache_clear()
    provider = SchemaRecoveryProvider(failures=2)
    try:
        app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'failed-recovery.db'}")
        app.state.narrative_analyst_provider = provider
        with TestClient(app) as client:
            response = client.post(
                "/knowledge-state-evaluation/cases/heard-world-fact-positive/run",
                json={"real_llm_requested": True},
            )
    finally:
        get_settings.cache_clear()

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "FAILED"
    assert payload["failure_category"] == "PROVIDER_SCHEMA_VALIDATION"
    assert payload["diagnostics"]["schema_error_field_paths"] == ["states", "0", "target"]
    assert "provider raw content" not in response.text
    assert provider.calls == 2


def test_provider_failures_are_typed_without_schema_recovery(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cases = [
        (
            ProviderTimeoutError("timeout", {"timeout_kind": "read", "timeout_seconds": 60}),
            "PROVIDER_TIMEOUT",
        ),
        (ProviderNetworkError("network", {}), "PROVIDER_NETWORK"),
        (ProviderHttpError("http", {"http_status_code": 429}), "PROVIDER_HTTP"),
    ]
    for index, (failure, category) in enumerate(cases):
        monkeypatch.setenv("ENABLE_REAL_LLM", "true")
        get_settings.cache_clear()
        provider = _ExceptionProvider(failure)
        try:
            app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / f'provider-{index}.db'}")
            app.state.narrative_analyst_provider = provider
            with TestClient(app) as client:
                response = client.post(
                    "/knowledge-state-evaluation/cases/heard-world-fact-positive/run",
                    json={"real_llm_requested": True},
                )
        finally:
            get_settings.cache_clear()
        assert response.status_code == 200
        assert response.json()["failure_category"] == category
        assert provider.calls == 1


class _ExceptionProvider:
    def __init__(self, failure: Exception) -> None:
        self.failure = failure
        self.calls = 0

    def structured_generate(self, request, response_model):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise self.failure


def test_real_run_builds_configured_provider_when_app_state_has_none(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ENABLE_REAL_LLM", "true")
    get_settings.cache_clear()
    fake_provider = FakeProvider()
    monkeypatch.setattr(
        "comic_agent.api.knowledge_state_evaluation._build_configured_provider",
        lambda settings: fake_provider,
        raising=False,
    )
    try:
        app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'fallback_provider.db'}")
        with TestClient(app) as client:
            response = client.post(
                "/knowledge-state-evaluation/cases/heard-world-fact-positive/run",
                json={"real_llm_requested": True},
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["evaluation"]["passed"] is True
    assert fake_provider.calls == 1
