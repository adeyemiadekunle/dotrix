"""Supported model providers and their fixed platform endpoints."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    env_var: str
    setting: str
    kwarg: str
    label: str = ""
    base_url: str | None = None


PROVIDERS = {
    "anthropic": Provider("ANTHROPIC_API_KEY", "anthropic_api_key", "api_key", "Anthropic"),
    "openai": Provider("OPENAI_API_KEY", "openai_api_key", "api_key", "OpenAI"),
    "google_genai": Provider("GOOGLE_API_KEY", "google_api_key", "google_api_key", "Google"),
    "xai": Provider("XAI_API_KEY", "xai_api_key", "api_key", "xAI (Grok)", "https://api.x.ai/v1"),
    "deepseek": Provider("DEEPSEEK_API_KEY", "deepseek_api_key", "api_key", "DeepSeek", "https://api.deepseek.com/v1"),
    "mistral": Provider("MISTRAL_API_KEY", "mistral_api_key", "api_key", "Mistral", "https://api.mistral.ai/v1"),
    "groq": Provider("GROQ_API_KEY", "groq_api_key", "api_key", "Groq", "https://api.groq.com/openai/v1"),
    "openrouter": Provider("OPENROUTER_API_KEY", "openrouter_api_key", "api_key", "OpenRouter", "https://openrouter.ai/api/v1"),
}
