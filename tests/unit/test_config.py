from deskpilot.config import Settings


def test_defaults_load_without_env_file():
    settings = Settings(_env_file=None)
    assert settings.log_level == "INFO"
    assert settings.llm_base_url == "https://api.groq.com/openai/v1"


def test_environment_variable_overrides_default(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = Settings(_env_file=None)
    assert settings.log_level == "DEBUG"
