import pytest

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.agents.llm import (
    GeminiWithBuiltinTools,
    ModelUnavailable,
    build_chat_model,
    settings_model_factory,
)
from dotrix_backend.modules.projects.models import Project


def search_files(query: str) -> str:
    """Stand-in function tool."""
    return query


def test_gemini_enables_builtin_tools_alongside_function_calling() -> None:
    model = build_chat_model("google_genai:gemini-3.8-flash", "test-key")
    assert isinstance(model, GeminiWithBuiltinTools)
    bound = model.bind_tools([search_files, {"google_search": {}}])
    config = bound.kwargs["tool_config"]
    enabled = config["include_server_side_tool_invocations"] if isinstance(config, dict) else (
        config.include_server_side_tool_invocations
    )
    assert enabled is True


def settings(**keys: str) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://localhost/unused",
        jwt_secret="test-only-jwt-secret-not-used-anywhere-else",  # type: ignore[arg-type]
        anthropic_api_key=keys.get("anthropic"),  # type: ignore[arg-type]
        google_api_key=keys.get("google"),  # type: ignore[arg-type]
        openai_api_key=None,
    )


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_or_empty_key_is_model_unavailable(key: str | None) -> None:
    factory = settings_model_factory(settings(google=key) if key is not None else settings())
    with pytest.raises(ModelUnavailable):
        factory(Project(model="google_genai:gemini-3.8-flash"))


def test_factory_builds_the_projects_model() -> None:
    choice = settings_model_factory(settings(google="test-key"))(Project(model="google_genai:gemini-3.8-flash"))
    assert isinstance(choice.model, GeminiWithBuiltinTools)
    assert choice.web_search == {"google_search": {}}


def test_e2e_models_need_the_flag_and_never_run_in_production() -> None:
    project = Project(model="e2e:rules")
    with pytest.raises(ModelUnavailable):
        settings_model_factory(settings())(project)
    enabled = settings().model_copy(update={"e2e_models": True})
    assert settings_model_factory(enabled)(project).web_search is None
    with pytest.raises(ValueError, match="e2e_models"):
        Settings(
            database_url="postgresql+asyncpg://localhost/unused",
            jwt_secret="test-only-jwt-secret-not-used-anywhere-else",  # type: ignore[arg-type]
            env="production",
            email_backend="sendly",
            DOTRIX_SENDLY_API_KEY="sk_test_not_a_real_key",
            e2e_models=True,
        )
