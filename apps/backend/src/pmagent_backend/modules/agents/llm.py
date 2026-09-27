"""Which chat model a project's agents use, and whether it can run right now."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_google_genai import ChatGoogleGenerativeAI

from pmagent_backend.core.errors import DomainError
from pmagent_backend.core.settings import Settings
from pmagent_backend.modules.projects.models import Project
from pmagent_engine.agent import _web_search_tool


class ModelUnavailable(DomainError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "model_unavailable"


@dataclass(frozen=True)
class Provider:
    env_var: str
    setting: str  # Settings attribute holding the key
    kwarg: str  # init_chat_model keyword for the key


PROVIDERS = {
    "anthropic": Provider("ANTHROPIC_API_KEY", "anthropic_api_key", "api_key"),
    "openai": Provider("OPENAI_API_KEY", "openai_api_key", "api_key"),
    "google_genai": Provider("GOOGLE_API_KEY", "google_api_key", "google_api_key"),
}


@dataclass(frozen=True)
class ModelChoice:
    model: Any  # a chat model instance
    web_search: dict | None


# (project) -> the model to run it with. Tests swap in a scripted model.
ModelFactory = Callable[[Project], ModelChoice]


def provider_of(model: str) -> Provider:
    name = model.split(":", 1)[0] if ":" in model else ""
    provider = PROVIDERS.get(name)
    if provider is None:
        raise ModelUnavailable(
            f"Unsupported model {model!r}; use one of: "
            + ", ".join(f"{p}:<model>" for p in PROVIDERS)
        )
    return provider


class GeminiWithBuiltinTools(ChatGoogleGenerativeAI):
    """Gemini refuses requests that mix its built-in tools (Google Search, which the Research
    agent uses) with function calling (every agent's file tools) unless
    `tool_config.include_server_side_tool_invocations` is on. deepagents binds tools without
    a tool_config, so turn it on here."""

    def bind_tools(self, tools: Any, *, tool_config: Any = None, **kwargs: Any) -> Any:  # type: ignore[override]
        config = dict(tool_config or {})
        config.setdefault("include_server_side_tool_invocations", True)
        return super().bind_tools(tools, tool_config=config, **kwargs)


def build_chat_model(model: str, api_key: str) -> Any:
    provider, _, name = model.partition(":")
    if provider == "google_genai":
        return GeminiWithBuiltinTools(model=name, google_api_key=api_key)
    return init_chat_model(model, **{PROVIDERS[provider].kwarg: api_key})


def settings_model_factory(settings: Settings) -> ModelFactory:
    def factory(project: Project) -> ModelChoice:
        provider = provider_of(project.model)
        key = getattr(settings, provider.setting)
        if key is None or not key.get_secret_value().strip():  # `KEY=` in .env is empty
            raise ModelUnavailable(
                f"No API key for {project.model}: set {provider.env_var} in .env and restart"
            )
        model = build_chat_model(project.model, key.get_secret_value())
        return ModelChoice(model=model, web_search=_web_search_tool(project.model))

    return factory
