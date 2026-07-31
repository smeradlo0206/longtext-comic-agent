from pydantic import SecretStr

from comic_agent.config import Settings


def test_llm_settings_defaults_do_not_require_key() -> None:
    settings = Settings(_env_file=None)

    assert settings.enable_real_llm is False
    assert settings.llm_provider_name == "ustc-openai-compatible"
    assert settings.llm_base_url == "https://api.llm.ustc.edu.cn/v1"
    assert settings.llm_model == "deepseek-v4-pro"
    assert settings.llm_api_key is None
    assert settings.llm_response_format is None
    assert settings.llm_timeout_seconds == 60
    assert settings.llm_max_output_tokens == 2000


def test_llm_settings_reads_response_format() -> None:
    settings = Settings(_env_file=None, LLM_RESPONSE_FORMAT="json_object")

    assert settings.llm_response_format == "json_object"


def test_llm_settings_reads_secret_key_from_llm_api_key() -> None:
    settings = Settings(_env_file=None, LLM_API_KEY="secret-test-key")

    assert isinstance(settings.llm_api_key, SecretStr)
    assert settings.llm_api_key.get_secret_value() == "secret-test-key"


def test_llm_settings_repr_and_dump_do_not_expose_secret() -> None:
    settings = Settings(_env_file=None, LLM_API_KEY="secret-test-key")

    assert "secret-test-key" not in repr(settings)
    assert settings.model_dump()["llm_api_key"] != "secret-test-key"


def test_llm_settings_openai_api_key_fallback() -> None:
    settings = Settings(_env_file=None, OPENAI_API_KEY="fallback-test-key")

    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "fallback-test-key"
