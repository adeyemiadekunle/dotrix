"""What a coding tool started by `dotrix runner` gets in its environment: what it needs to run, and
its own provider's settings, never the rest of this machine's credentials."""
from __future__ import annotations

from collections.abc import Mapping

# Host credentials are not part of the tool's environment. Keep the execution settings it needs
# and explicit provider/tool settings, on every platform.
EXECUTION_ENV = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "PROGRAMDATA", "APPDATA", "LOCALAPPDATA",
    "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "USER", "LOGNAME", "SHELL", "TMP", "TEMP", "TMPDIR",
    "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TERM", "COLORTERM", "TZ",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
})
ANTHROPIC_ENV = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
})
OPENAI_ENV = frozenset({"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"})
TOOL_ENV = {
    "claude-code": ANTHROPIC_ENV | {
        "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
    },
    # Codex can be supplied through --tool codex --command even though it isn't auto-detected.
    "codex": OPENAI_ENV | {"CODEX_API_KEY", "CODEX_HOME"},
    "opencode": ANTHROPIC_ENV | OPENAI_ENV | {
        "GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "GOOGLE_GEMINI_BASE_URL",
        "OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT", "OPENCODE_DISABLE_AUTOUPDATE",
    },
}


def tool_environment(tool: str, environ: Mapping[str, str]) -> dict[str, str]:
    """An allowlist, rather than host inheritance or broad credential-name prefixes."""
    allowed = EXECUTION_ENV | TOOL_ENV[tool]
    return {key: value for key, value in environ.items() if key.upper() in allowed}
