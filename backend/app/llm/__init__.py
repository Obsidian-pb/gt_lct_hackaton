from functools import lru_cache

from app.core.config import get_settings
from app.llm.base import CommentReview, GeneratedScenario, LLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.llm.stub import StubProvider


@lru_cache
def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider == "stub":
        return StubProvider()
    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        name=settings.llm_provider,
    )


__all__ = [
    "CommentReview",
    "GeneratedScenario",
    "LLMProvider",
    "get_llm_provider",
]
