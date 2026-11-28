"""Versioned project cloud setup, pinned before approval; never applied to native runners.

A project's environment: its name, image, setup and verification scripts and variables, saved with its network policy
(network.py) from one form. A new cloud session pins the environment's revision; follow-ups keep it.

Variables are plain, non-secret configuration (`NODE_ENV`, a test service's address): they're shown in the brief and
set for the setup script, Kai's commands and verification (`with_variables`). Names that would change how the sandbox,
the coding tool or the network work are refused, and so are names that look like secrets, which have to wait for
secrets that the sandbox never holds (docs/product.md, Roadmap).
"""
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .schemas import SandboxNetworkUpdate

MAX_VARIABLES = 50
MAX_VALUE = 4096
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
# What the sandbox, the coding tools, the shell or the network read: a variable must not change them.
RESERVED = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "PWD", "OLDPWD", "IFS", "ENV", "BASH_ENV", "CDPATH", "PS4", "TERM",
    "LANG", "LANGUAGE", "TMPDIR", "TZ", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE",
    "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "NODE_OPTIONS", "NODE_USE_ENV_PROXY",
    "PYTHONSTARTUP", "PYTHONHOME", "PYTHONINSPECT", "PERL5OPT", "RUBYOPT", "JAVA_TOOL_OPTIONS", "XDG_CONFIG_HOME",
    "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "PLAYWRIGHT_BROWSERS_PATH",
})
RESERVED_PREFIXES = ("DOTRIX_", "LC_", "LD_", "DYLD_", "GIT_", "SSH_", "ANTHROPIC_", "OPENAI_", "CODEX_", "CLAUDE_",
                     "OPENCODE_", "FX_", "GOOGLE_", "GEMINI_", "XAI_", "DEEPSEEK_", "MISTRAL_", "GROQ_", "OPENROUTER_",
                     "NVIDIA_", "AI_GATEWAY_", "VERCEL_", "AWS_", "AZURE_", "GH_", "GITHUB_", "KAI_")
# Parts of a name (split at `_`) that say it holds a secret: `NPM_TOKEN`, `STRIPE_KEY`, `DB_PASSWORD`.
SECRET_PARTS = frozenset({"TOKEN", "TOKENS", "SECRET", "SECRETS", "PASSWORD", "PASSWD", "PASS", "PWD", "KEY", "KEYS",
                          "APIKEY", "CREDENTIAL", "CREDENTIALS", "AUTH", "COOKIE", "PRIVATE"})


def check_variable(name: str, value: str) -> None:
    upper = name.upper()
    if not _NAME.fullmatch(name):
        raise ValueError(f"{name!r} isn't a variable name (letters, digits and _, not starting with a digit)")
    if upper in RESERVED or upper.startswith(RESERVED_PREFIXES):
        raise ValueError(f"{name} is set by the sandbox or the coding tool; choose another name")
    if SECRET_PARTS & set(upper.split("_")):
        raise ValueError(f"{name} looks like a secret. Variables are visible to Kai and in the brief, so secrets can't "
                         "go here yet")
    if len(value) > MAX_VALUE or "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"{name}'s value must be one line of at most {MAX_VALUE} characters")


class EnvironmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    enabled: bool = False
    name: str = Field(default="Project environment", min_length=1, max_length=100)
    image: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$")] | None = None
    setup_script: str = Field(default="", max_length=16000)
    verify_script: str = Field(default="", max_length=16000)
    timeout_seconds: int = Field(default=300, ge=10, le=900)
    variables: dict[str, str] = Field(default_factory=dict, description=(
        "Non-secret variables for the setup script, Kai's commands and verification on cloud turns. Visible to Kai "
        "and in the brief; names the sandbox or tools use, and names that look like secrets, are refused"))

    @field_validator("variables")
    @classmethod
    def _variables(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > MAX_VARIABLES:
            raise ValueError(f"At most {MAX_VARIABLES} variables")
        for name, text in value.items():
            check_variable(name, text)
        return value


class EnvironmentSave(EnvironmentUpdate):
    """The environment and, when given, the project's network policy, saved together from one form."""

    network: SandboxNetworkUpdate | None = Field(default=None, description=(
        "The project's network policy, saved with the environment; None leaves it as it is"))


class EnvironmentRead(EnvironmentUpdate):
    image_policy: Literal["platform", "approved"] = "platform"
    available_images: list[str] = Field(default_factory=list)


def profile(value: dict | None) -> EnvironmentRead:
    result = EnvironmentRead.model_validate(value or {"revision": 0})
    return result.model_copy(update={"image_policy": "approved" if result.image else "platform"})


def with_variables(argv: list[str], environment: dict | None) -> list[str]:
    """`argv` with the environment's variables set (`env NAME=value … argv`), the same on every sandbox kind."""
    if not environment:
        return argv
    configured = profile(environment)
    if not configured.enabled or not configured.variables:
        return argv
    return ["env", *[f"{name}={value}" for name, value in configured.variables.items()], *argv]


def require_approved_image(image: str | None, approved: list[str]) -> None:
    from dotrix_backend.core.errors import Conflict

    if image is not None and image not in approved:
        raise Conflict("This coding image is not approved by the server operator; choose an approved image")
