from ..config import Settings
from .base import LLMProvider, ProviderError
from .manager import ProviderManager


def get_provider(s: Settings) -> LLMProvider:
    """Build configured adapters and route requests according to AI_PROVIDER."""
    if s.provider not in {"auto", "gemini", "groq", "openrouter"}:
        raise ProviderError("Unknown AI_PROVIDER. Choose auto, gemini, groq, or openrouter.")

    providers = {}
    if s.gemini_api_key:
        from .gemini import GeminiProvider
        providers["gemini"] = GeminiProvider(s.gemini_api_key, s.gemini_model)
    if s.groq_api_key:
        from .openai_compatible import OpenAICompatibleProvider
        providers["groq"] = OpenAICompatibleProvider(
            "groq", s.groq_api_key, s.groq_model, "https://api.groq.com/openai/v1")
    if s.openrouter_api_key:
        from .openai_compatible import OpenAICompatibleProvider
        providers["openrouter"] = OpenAICompatibleProvider(
            "openrouter", s.openrouter_api_key, s.openrouter_model, "https://openrouter.ai/api/v1")

    if s.provider != "auto" and s.provider not in providers:
        env_key = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY",
                   "openrouter": "OPENROUTER_API_KEY"}[s.provider]
        raise ProviderError(f"AI_PROVIDER={s.provider} requires {env_key} in backend/.env.")
    if not providers:
        raise ProviderError("No AI providers are configured. Add an API key to backend/.env.")
    return ProviderManager(providers, s.provider)
