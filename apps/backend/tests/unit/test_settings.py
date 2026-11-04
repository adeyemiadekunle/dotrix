"""Settings: which environments exist, and what a deployed one (staging, production) refuses."""
import pytest
from fastapi import Response
from pydantic import ValidationError

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.auth.schemas import TokenPair
from dotrix_backend.modules.web.session import set_session

BASE = {
    "database_url": "postgresql+asyncpg://localhost/unused",
    "jwt_secret": "test-only-jwt-secret-not-used-anywhere-else",
}
DEPLOYED = {"email_backend": "sendly", "DOTRIX_SENDLY_API_KEY": "sk_test_not_a_real_key", "rate_limits": "redis"}


def settings(**values: object) -> Settings:
    return Settings(**{**BASE, **values})  # type: ignore[arg-type]


def test_an_unknown_environment_is_refused() -> None:
    with pytest.raises(ValidationError, match="env"):
        settings(env="prod", **DEPLOYED)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_deployed_environments_get_the_production_checks(env: str) -> None:
    assert settings(env=env, **DEPLOYED).is_deployed
    with pytest.raises(ValueError, match="rate_limits must be redis"):
        settings(env=env, **{**DEPLOYED, "rate_limits": "memory"})
    with pytest.raises(ValueError, match="email_backend=console"):
        settings(env=env, **{**DEPLOYED, "email_backend": "console"})
    with pytest.raises(ValueError, match="coding_sandbox=local"):
        settings(env=env, **DEPLOYED, coding_sandbox="local")


@pytest.mark.parametrize("env", ["development", "test"])
def test_local_environments_are_not_deployed(env: str) -> None:
    assert not settings(env=env, rate_limits="memory").is_deployed


@pytest.mark.parametrize(("env", "secure"), [("development", False), ("staging", True), ("production", True)])
def test_session_cookies_are_secure_when_deployed(env: str, secure: bool) -> None:
    extra = DEPLOYED if env != "development" else {}
    response = Response()
    tokens = TokenPair(access_token="a", refresh_token="r", expires_in=900)
    set_session(response, tokens, settings(env=env, **extra))
    cookies = [v for k, v in response.raw_headers if k == b"set-cookie" and b"Max-Age=0" not in v]
    session_cookies = [c.decode() for c in cookies if c.split(b"=")[0] in (b"dx_access", b"dx_refresh", b"dx_session")]
    assert session_cookies and all(("; Secure" in c or "; secure" in c) == secure for c in session_cookies)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_deployed_coding_runs_push_to_a_fork(env: str) -> None:
    with pytest.raises(ValueError, match="DOTRIX_CODING_FORK_OWNER"):
        settings(env=env, **DEPLOYED, coding_sandbox="docker")
    assert settings(env=env, **DEPLOYED, coding_sandbox="docker", coding_fork_owner="dotrix-fork",
                    coding_docker_runtime="runsc").coding_fork_owner
    assert settings(env=env, **DEPLOYED).coding_fork_owner is None  # coding off: no fork needed
    with pytest.raises(ValueError):
        settings(coding_fork_owner="not/an-org")


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize("runtime", [None, "", "runc", "io.containerd.runc.v2", "custom"])
def test_deployed_docker_coding_requires_gvisor(env: str, runtime: str | None) -> None:
    with pytest.raises(ValueError, match="DOTRIX_CODING_DOCKER_RUNTIME=runsc"):
        settings(env=env, **DEPLOYED, coding_sandbox="docker", coding_fork_owner="dotrix-fork",
                 coding_docker_runtime=runtime)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_deployed_coding_cannot_disable_the_worker_capacity_limit(env: str) -> None:
    with pytest.raises(ValueError, match="DOTRIX_CODING_MAX_RUNS must be positive"):
        settings(env=env, **DEPLOYED, coding_sandbox="docker", coding_fork_owner="dotrix-fork",
                 coding_docker_runtime="runsc", coding_max_runs=0)
    assert settings(env=env, **DEPLOYED, coding_max_runs=0).coding_sandbox == "off"


def test_development_keeps_plain_docker_and_unlimited_runs_available() -> None:
    local = settings(coding_sandbox="docker", coding_max_runs=0)
    assert local.coding_docker_runtime is None
    assert local.coding_max_runs == 0
