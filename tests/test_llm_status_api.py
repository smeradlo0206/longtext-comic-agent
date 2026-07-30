import json
from pathlib import Path

from fastapi.testclient import TestClient

from comic_agent.config import get_settings
from comic_agent.main import create_app


def create_test_client(tmp_path: Path) -> TestClient:
    app = create_app(database_url=f"sqlite+pysqlite:///{tmp_path / 'llm_status.db'}")
    return TestClient(app)


def test_llm_status_reports_key_presence_without_value(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "secret-test-key")
    monkeypatch.setenv("ENABLE_REAL_LLM", "false")
    get_settings.cache_clear()
    try:
        with create_test_client(tmp_path) as client:
            response = client.get("/settings/llm/status")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["enable_real_llm"] is False
    assert payload["provider_name"] == "ustc-openai-compatible"
    assert payload["base_url"] == "https://api.llm.ustc.edu.cn/v1"
    assert payload["model"] == "deepseek-v4-pro"
    assert payload["api_key_present"] is True
    assert payload["api_key_non_empty"] is True
    assert "secret-test-key" not in serialized


def test_llm_status_reports_missing_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    try:
        with create_test_client(tmp_path) as client:
            response = client.get("/settings/llm/status")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["api_key_present"] is False
    assert response.json()["api_key_non_empty"] is False
