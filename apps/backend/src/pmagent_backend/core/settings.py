from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root .env, so settings load the same from any working directory
# (uvicorn at the root, alembic in apps/backend). Real env vars take precedence.
REPO_ROOT_ENV = Path(__file__).resolve().parents[5] / ".env"

_CONFIG = SettingsConfigDict(
    env_prefix="PMAGENT_", env_file=(REPO_ROOT_ENV, ".env"), extra="ignore"
)


class DatabaseSettings(BaseSettings):
    """Just what migrations and test setup need, so they don't require app secrets."""

    model_config = _CONFIG

    # Required, no default: credentials only ever come from the environment / .env.
    database_url: str
    database_echo: bool = False


class Settings(DatabaseSettings):
    model_config = _CONFIG

    env: str = "development"
    log_level: str = "INFO"
    log_json: bool = True
    # 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first and stalls.
    redis_url: str = "redis://127.0.0.1:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]
    # Swagger UI (/docs), ReDoc (/redoc), and /openapi.json. Turn off to hide the API surface.
    docs_enabled: bool = True

    # Auth. The secret is required and never has a default.
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_issuer: str = "pmagent"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    email_verification_ttl_hours: int = 48
    password_reset_ttl_minutes: int = 60
    magic_link_ttl_minutes: int = 15

    # Base URL of the web app, used to build links in emails.
    app_url: str = "http://localhost:3000"
    # Outgoing email: "console" logs it (development only; links carry tokens), "sendly" sends
    # it through Sendly (https://developer.sendlyai.com). Unset: Sendly when its key is set.
    email_backend: Literal["console", "sendly"] | None = None
    # The From address, e.g. "pmagent <no-reply@yourdomain.com>", on a domain verified with the
    # provider. Unset: the provider account's default (Sendly's shared address with a test key).
    email_from: str | None = None
    # Sendly API key: sk_test_… (validates and logs, never delivers) or sk_live_…
    sendly_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("PMAGENT_SENDLY_API_KEY", "SENDLY_API_KEY", "SENDLY_EMAIL"),
    )
    sendly_api_url: str = "https://api.sendlyai.com"

    # Sign in with GitHub (a GitHub App or OAuth App). Both unset: the option isn't offered.
    github_client_id: str | None = Field(
        default=None, validation_alias=AliasChoices(
            "PMAGENT_GITHUB_CLIENT_ID", "GITHUB_CLIENT_ID", "GITHUB_APP_CLIENT_ID", "GITHUB_OAUTH_CLIENT_ID"
        ),
    )
    github_client_secret: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices(
            "PMAGENT_GITHUB_CLIENT_SECRET", "GITHUB_CLIENT_SECRET", "GITHUB_APP_CLIENT_SECRET", "GITHUB_OAUTH_CLIENT_SECRET"
        ),
    )
    # Where GitHub sends people back. Unset: the callback URL registered on the app, which
    # should be the web app's {app_url}/api/auth/github/callback or this API's
    # /v1/auth/oauth/github/callback (which forwards there).
    github_redirect_uri: str | None = None

    # The GitHub App's repository access (connecting projects' repos; agents v2 step 5). The same
    # app as sign-in. Unset: connecting repos isn't offered (pasting a repo address still works).
    github_app_id: str | None = Field(default=None, validation_alias=AliasChoices("PMAGENT_GITHUB_APP_ID", "GITHUB_APP_ID"))
    # The app's public name in its URL (github.com/apps/<slug>), for the install page.
    github_app_slug: str | None = Field(
        default=None, validation_alias=AliasChoices("PMAGENT_GITHUB_APP_SLUG", "GITHUB_APP_SLUG")
    )
    # The app's private key (PEM), inline or from a file; it signs the app's tokens to GitHub.
    github_app_private_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("PMAGENT_GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_PRIVATE_KEY")
    )
    github_app_private_key_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PMAGENT_GITHUB_APP_PRIVATE_KEY_PATH", "GITHUB_APP_PRIVATE_KEY_PATH"),
    )
    # Checks that webhook deliveries come from GitHub (X-Hub-Signature-256).
    github_webhook_secret: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("PMAGENT_GITHUB_WEBHOOK_SECRET", "GITHUB_WEBHOOK_SECRET")
    )

    # Checkouts of connected repos for agents to read (agents v2 step 5b): a folder on the machine
    # that runs agents (the worker, or the API in local mode), and the largest repo it keeps.
    code_dir: str = "~/.cache/pmagent/code"
    code_max_mb: int = Field(default=500, ge=1)
    # Coding runs (step 5c): Claude Code or Codex editing a checkout in a sandbox.
    # - "openshell": an OpenShell sandbox per run (its gateway set up and selected with the
    #   OpenShell CLI; see infra/coding/README.md), with a policy and the model key injected
    # - "local": a temporary folder on this machine, no isolation (development only)
    # - "off": "Start coding" is refused
    coding_sandbox: Literal["off", "openshell", "local"] = "off"
    openshell_bin: str = "openshell"
    coding_image: str = "pmagent-coding:latest"  # the sandbox image (infra/coding/Dockerfile)
    # Which tool codes: "auto" follows the key the server has (Anthropic: Claude Code, else
    # OpenAI: Codex); naming one needs its key.
    coding_agent: Literal["auto", "claude-code", "codex"] = "auto"
    coding_claude_model: str | None = None  # Claude Code's default when unset
    coding_codex_model: str | None = None  # Codex's default when unset
    coding_timeout_minutes: int = Field(default=30, ge=1, le=240)
    # Tokens (input + output) one coding run may use before it's stopped; 0: no limit.
    coding_token_budget: int = Field(default=3_000_000, ge=0)

    # Object storage for document originals: any S3-compatible store (MinIO locally).
    # Leave the endpoint and keys unset to run without uploads (they answer 503).
    s3_endpoint_url: str | None = None
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_bucket: str = "pmagent-documents"
    s3_region: str = "us-east-1"
    max_upload_mb: int = Field(default=25, ge=1, le=200)

    # Model provider keys. Read under their usual names (no PMAGENT_ prefix), so the
    # same .env works for the CLI. A project's model ("anthropic:...") needs its key.
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "PMAGENT_ANTHROPIC_API_KEY")
    )
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "PMAGENT_OPENAI_API_KEY")
    )
    google_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GOOGLE_API_KEY", "PMAGENT_GOOGLE_API_KEY")
    )
    # Organisations connect their own provider keys (Settings → Models), stored encrypted with
    # these Fernet keys: comma-separated, the first encrypts, every one decrypts (to rotate, put
    # a new key first and re-save). None: workspaces can't connect keys.
    encryption_key: SecretStr | None = None
    # Whether workspaces without their own key for a provider may use the server's keys above
    # (self-hosting and development). Off for a hosted service where everyone brings their own.
    server_model_keys: bool = True
    # Model for new projects ("provider:model"); each project can change its own.
    default_model: str = "anthropic:claude-sonnet-5"
    # Models a conversation can be started on; only those whose provider has a key are offered.
    models: list[str] = [
        "google_genai:gemini-3.8-flash",
        "anthropic:claude-opus-5-5",
        "anthropic:claude-sonnet-5",
        "anthropic:claude-haiku-5-5",
        "anthropic:claude-haiku-4-5-20251001",
        "openai:gpt-5.5",
        "openai:gpt-5.5-mini",
    ]
    # The most tokens (input + output, over all its steps) one agent run may use before it
    # stops; a project can set its own. 0 turns the limit off.
    run_token_budget: int = Field(default=500_000, ge=0)
    # Automation runs a workspace may start per day (UTC), across all its projects; 0: no limit
    # (the default: organisations run on their own keys, and their provider's limits apply).
    automation_daily_runs: int = Field(default=0, ge=0)
    # Tokens (input + output) a workspace's automation runs may use per UTC day; 0: no limit.
    automation_daily_tokens: int = Field(default=0, ge=0)
    # Changes agents may make without a person approving them (owners' standing rules): per run
    # step, and per workspace per UTC day. Past either, the change waits for approval as usual.
    unattended_changes_per_run: int = Field(default=20, ge=0)
    unattended_changes_per_day: int = Field(default=200, ge=0)
    # A conversation's older turns are summarised once its prompt passes this many tokens
    # (the most recent turns are kept word for word).
    summarize_after_tokens: int = Field(default=40_000, ge=5_000)
    # The model that turns documents and issues into vectors for search ("provider:model",
    # google_genai or openai, with that provider's key). Empty: search by keywords only.
    embedding_model: str = "google_genai:gemini-embedding-001"
    # Meaning matches below this cosine similarity are left out (the nearest chunks of an
    # unrelated query are still "nearest"). Depends on the model: measured on
    # gemini-embedding-001, the right passage scored 0.68-0.72 and unrelated queries at most 0.56.
    embedding_min_similarity: float = Field(default=0.6, ge=0, le=1)
    # Research on the web (docs/agents-v2.md §6). Search: "tavily" (needs the key), "native"
    # (the model's built-in search), or "auto" (Tavily when the key is set). Agents read pages
    # themselves either way. "fake": a canned search and site, for end-to-end tests only.
    tavily_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("PMAGENT_TAVILY_API_KEY", "TAVILY_API_KEY")
    )
    search_provider: Literal["auto", "tavily", "native", "fake"] = "auto"
    # Pages our reader can't read (JavaScript-only, blocking readers) are read by Tavily instead.
    tavily_extract: bool = True
    # Per run: web searches and pages read. Per workspace per day: Tavily credits (0: no limit).
    research_max_searches: int = Field(default=10, ge=0, le=100)
    research_max_fetches: int = Field(default=20, ge=0, le=200)
    tavily_daily_credits: int = Field(default=500, ge=0)
    # Where background work executes (agent runs, emails, password-reset requests):
    # - "local": tasks in the API process (simplest; an API restart cuts runs off)
    # - "worker": queued in Redis and executed by `python -m pmagent_backend.worker`; work
    #   survives API restarts and is retried if the worker dies
    # - "inline": inside the request (tests, debugging)
    jobs: Literal["local", "worker", "inline"] = "local"
    # Rate limits on sign-up, login, password reset, and verification emails:
    # "redis" (shared by every API process; required in production), "memory" (this process
    # only), or "off".
    rate_limits: Literal["redis", "memory", "off"] = "memory"
    # Peers whose X-Forwarded-For is believed when finding a caller's IP (the web app's
    # server, a load balancer). Addresses or CIDR ranges.
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]
    # End-to-end tests only: allow the deterministic "e2e:rules" model (no API key, no cost).
    e2e_models: bool = False

    @model_validator(mode="after")
    def _safe_for_production(self) -> Settings:
        if self.email_backend is None:
            self.email_backend = "sendly" if self.sendly_api_key else "console"
        if self.email_backend == "sendly" and not self.sendly_api_key:
            raise ValueError("email_backend=sendly needs PMAGENT_SENDLY_API_KEY")
        if self.env == "production" and self.email_backend == "console":
            raise ValueError("email_backend=console logs tokens; not allowed in production")
        if self.env == "production" and self.rate_limits != "redis":
            raise ValueError("rate_limits must be redis in production (limits shared by every process)")
        if self.search_provider == "tavily" and not self.tavily_api_key:
            raise ValueError("search_provider=tavily needs PMAGENT_TAVILY_API_KEY")
        if self.search_provider == "fake" and not self.e2e_models:
            raise ValueError("search_provider=fake is for end-to-end tests (needs PMAGENT_E2E_MODELS=true)")
        if self.env == "production" and self.coding_sandbox == "local":
            raise ValueError("coding_sandbox=local runs coding agents unisolated; not allowed in production")
        if self.env == "production" and self.e2e_models:
            raise ValueError("e2e_models is for end-to-end tests; not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()  # type: ignore[call-arg]
