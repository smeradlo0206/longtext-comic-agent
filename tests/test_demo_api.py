import json
from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.config import get_settings
from comic_agent.main import create_app


def create_test_client(tmp_path: Path) -> TestClient:
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'demo_api.db'}")
    return TestClient(app)


def test_demo_status_reports_sanitized_runtime_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "true")
    monkeypatch.setenv("INTERNAL_DEMO_ACCESS_CODE", "secret-demo-code")
    monkeypatch.setenv("ENABLE_REAL_LLM", "true")
    monkeypatch.setenv("LLM_API_KEY", "secret-test-key")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-pro")
    get_settings.cache_clear()
    try:
        with create_test_client(tmp_path) as client:
            response = client.get("/demo/status")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload == {
        "require_access_code": True,
        "real_llm_enabled": True,
        "provider_name": "ustc-openai-compatible",
        "model": "deepseek-v4-pro",
        "api_key_configured": True,
        "api_key_non_empty": True,
        "supported_modes": [
            "mock",
            "real_event",
            "event_extraction",
            "entity_extraction",
            "claim_extraction",
        ],
    }
    assert "secret-demo-code" not in serialized
    assert "secret-test-key" not in serialized


def test_demo_verify_access_accepts_correct_code(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "true")
    monkeypatch.setenv("INTERNAL_DEMO_ACCESS_CODE", "secret-demo-code")
    get_settings.cache_clear()
    try:
        with create_test_client(tmp_path) as client:
            response = client.post(
                "/demo/verify-access",
                json={"access_code": "secret-demo-code"},
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json() == {"access_granted": True}


def test_demo_verify_access_rejects_wrong_code_without_leaking_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "true")
    monkeypatch.setenv("INTERNAL_DEMO_ACCESS_CODE", "secret-demo-code")
    get_settings.cache_clear()
    try:
        with create_test_client(tmp_path) as client:
            response = client.post(
                "/demo/verify-access",
                json={"access_code": "wrong-code"},
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid demo access code"
    assert "secret-demo-code" not in response.text


def test_demo_verify_access_skips_code_when_requirement_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("INTERNAL_DEMO_REQUIRE_ACCESS_CODE", "false")
    monkeypatch.setenv("INTERNAL_DEMO_ACCESS_CODE", "")
    get_settings.cache_clear()
    try:
        with create_test_client(tmp_path) as client:
            response = client.post("/demo/verify-access", json={})
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json() == {"access_granted": True}
