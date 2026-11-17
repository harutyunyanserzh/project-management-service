"""Chat model factory. One setting (LLM_PROVIDER) switches between local and hosted models."""

from langchain_core.language_models import BaseChatModel

from app.core.config import settings


class LLMConfigError(Exception):
    """The configured provider cannot be used (for example, a missing API key)."""


def model_label() -> tuple[str, str]:
    """(provider, model name) for logs and API responses."""
    provider = settings.LLM_PROVIDER.lower()
    model = {
        "ollama": settings.OLLAMA_MODEL,
        "anthropic": settings.ANTHROPIC_MODEL,
        "openai": settings.OPENAI_MODEL,
    }.get(provider, "none")
    return provider, model


def build_chat_model() -> BaseChatModel | None:
    """Return a LangChain chat model, or None when LLM_PROVIDER is 'none'.

    All providers share LangChain's chat-model interface (`invoke`, `bind_tools`),
    so the rest of the code does not care which one is used.
    """
    provider = settings.LLM_PROVIDER.lower()

    if provider == "none":
        return None

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.OLLAMA_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            temperature=settings.LLM_TEMPERATURE,
            num_predict=settings.LLM_MAX_TOKENS,
        )

    if provider == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise LLMConfigError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.ANTHROPIC_MODEL,
            api_key=settings.ANTHROPIC_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )

    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise LLMConfigError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )

    raise LLMConfigError(f"Unknown LLM_PROVIDER: {settings.LLM_PROVIDER}")


def get_chat_model() -> BaseChatModel | None:
    """FastAPI dependency. Tests replace it with a fake model via dependency_overrides."""
    return build_chat_model()
