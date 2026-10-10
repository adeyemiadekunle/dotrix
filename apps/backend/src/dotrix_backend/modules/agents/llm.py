"""Which chat model a project's agents use, with whose key, and whether it can run right now.

A workspace's own key for the provider comes first (model_keys); without one, the server's,
when `DOTRIX_SERVER_MODEL_KEYS` lends them (self-hosting, development)."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_google_genai import ChatGoogleGenerativeAI

from dotrix_backend.core.errors import DomainError
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.projects.models import Project
from dotrix_engine.agent import _web_search_tool


class ModelUnavailable(DomainError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "model_unavailable"


@dataclass(frozen=True)
class Provider:
    env_var: str
    setting: str  # Settings attribute holding the key
    kwarg: str  # init_chat_model keyword for the key
    label: str = ""


PROVIDERS = {
    "anthropic": Provider("ANTHROPIC_API_KEY", "anthropic_api_key", "api_key", "Anthropic"),
    "openai": Provider("OPENAI_API_KEY", "openai_api_key", "api_key", "OpenAI"),
    "google_genai": Provider("GOOGLE_API_KEY", "google_api_key", "google_api_key", "Google"),
}

# provider -> a workspace's own key (model_keys.ModelKeys.keys)
Keys = dict[str, str]


@dataclass(frozen=True)
class ModelChoice:
    model: Any  # a chat model instance
    web_search: dict | None
    # A cheaper model for the specialists and conversation summaries (None: `model`).
    specialist_model: Any = None


# (project, the conversation's model or None for the project's) -> the model to run it with.
# Tests swap in a scripted model.
ModelFactory = Callable[..., ModelChoice]


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


def server_key(settings: Settings, provider: str) -> str | None:
    """The server's own key for a provider, or None (unset, or `KEY=` left empty in .env)."""
    spec = PROVIDERS.get(provider)
    key = getattr(settings, spec.setting) if spec else None
    value = key.get_secret_value().strip() if key is not None else ""
    return value or None


def key_for(settings: Settings, model: str, keys: Keys | None = None) -> str | None:
    """The key a model runs with here: the workspace's own, else the server's if it lends them."""
    provider = model.partition(":")[0]
    if keys and keys.get(provider):
        return keys[provider]
    return server_key(settings, provider) if settings.server_model_keys else None


def has_key(settings: Settings, model: str, connected: set[str] | None = None) -> bool:
    provider = model.partition(":")[0]
    return provider in (connected or set()) or (settings.server_model_keys and server_key(settings, provider) is not None)


def available_models(settings: Settings, *also: str, connected: set[str] | None = None) -> list[str]:
    """The models a conversation or an agent can run on here: the catalogue (and `also`, e.g. the
    project's model) whose provider has a key (the workspace's own, `connected`, or the server's),
    in order, without repeats."""
    found: list[str] = []
    for model in [*also, *settings.models, settings.default_model]:
        runnable = has_key(settings, model, connected) or (settings.e2e_models and model.startswith("e2e:"))
        if model and runnable and model not in found:
            found.append(model)
    return found


def settings_model_factory(settings: Settings) -> ModelFactory:
    def factory(project: Project, model: str | None = None, keys: Keys | None = None) -> ModelChoice:
        chosen = model or project.model
        if chosen.startswith("e2e:"):
            if not settings.e2e_models:
                raise ModelUnavailable("Test models need DOTRIX_E2E_MODELS=true (end-to-end tests only)")
            from dotrix_engine.testing import RuleBasedChatModel

            return ModelChoice(model=RuleBasedChatModel(), web_search=None)
        specialist = project.specialist_model
        return ModelChoice(
            model=_build(chosen, keys),
            web_search=_web_search_tool(chosen),
            specialist_model=_build(specialist, keys) if specialist and specialist != chosen else None,
        )

    def _build(model: str, keys: Keys | None) -> Any:
        provider = provider_of(model)
        key = key_for(settings, model, keys)
        if key is None:
            hint = f"set {provider.env_var} in .env and restart" if settings.server_model_keys else "an owner or admin connects it"
            raise ModelUnavailable(
                f"No {provider.label} key for {model}: connect one in Settings → Models ({hint})"
            )
        return build_chat_model(model, key)

    return factory


# -- a provider refusing for its limits ------------------------------------------------------

_LIMIT_MARKERS = (
    "rate limit", "rate_limit", "ratelimit", "resource_exhausted", "resource exhausted", "quota",
    "insufficient_quota", "credit balance", "too many requests",
)


def limit_error(exc: BaseException) -> str | None:
    """When `exc` is a provider refusing for a rate limit, quota, or spent credit (HTTP 429, or
    Anthropic's "credit balance is too low"), what it said in a line; None for anything else."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status_code", None) or getattr(getattr(current, "response", None), "status_code", None)
        text = str(current)
        name = type(current).__name__.lower()
        if status == 429 or "ratelimit" in name or "resourceexhausted" in name or any(m in text.lower() for m in _LIMIT_MARKERS):
            return " ".join(text.split())[:300] or type(current).__name__
        current = current.__cause__ or current.__context__
    return None


_RESET_IN = re.compile(r"(?:retry|try again)[^0-9]{0,30}?(\d+(?:\.\d+)?)\s*(ms|s|sec|seconds?|m|min|minutes?)\b", re.I)
_RETRY_DELAY = re.compile(r"retry_?delay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", re.I)


def limit_resets_in(exc: BaseException) -> float | None:
    """Seconds until a provider's limit resets, when it says (a Retry-After header, Google's
    retryDelay, or "try again in 20s"); None when it doesn't."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        headers = getattr(getattr(current, "response", None), "headers", None) or {}
        try:
            after = headers.get("retry-after")
            if after is not None:
                return max(0.0, float(after))
        except (TypeError, ValueError):
            pass
        text = str(current)
        if m := _RETRY_DELAY.search(text):
            return float(m.group(1))
        if m := _RESET_IN.search(text):
            value, unit = float(m.group(1)), m.group(2).lower()
            return value / 1000 if unit == "ms" else value * 60 if unit.startswith("m") and unit != "ms" else value
        current = current.__cause__ or current.__context__
    return None
