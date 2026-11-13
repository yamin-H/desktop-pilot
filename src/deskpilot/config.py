from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All app settings, read from environment variables or the .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: str = "dev"
    log_level: str = "INFO"
    database_url: str = "postgresql://postgres:deskpilot@localhost:5432/postgres"
    redis_url: str = "redis://localhost:6379/0"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    slack_webhook_url: str = ""
    api_token: str = ""
    api_enable_chat: bool = False
    use_redis: bool = False
    tick_stream: str = "ticks"
    tick_stream_maxlen: int = 200_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
