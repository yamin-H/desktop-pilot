from openai import AsyncOpenAI

from deskpilot.config import Settings


class AgentConfigError(Exception):
    """The assistant is not configured yet (missing key or model)."""


def make_client(settings: Settings) -> AsyncOpenAI:
    """The OpenAI SDK pointed at whatever LLM_BASE_URL says (Groq, by default)."""
    if not settings.llm_api_key:
        raise AgentConfigError(
            "LLM_API_KEY is empty. Put your Groq API key in .env (see .env.example)."
        )
    return AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        max_retries=2,
        timeout=60.0,
    )


def require_model(settings: Settings) -> str:
    if not settings.llm_model:
        raise AgentConfigError(
            "LLM_MODEL is empty. Set it in .env to a Groq model that supports tool calling, "
            "for example openai/gpt-oss-120b (check Groq's model list)."
        )
    return settings.llm_model