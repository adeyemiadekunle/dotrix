"""The coding tools we wrap, run headless: the command line, and their JSON events read into
what the run page shows (steps) and what the run used (tokens).

- Claude Code: `claude -p --bare --output-format stream-json --verbose`, the brief on stdin.
  Headless has no prompts, so the tools it may use are pre-allowed (`--permission-mode dontAsk`
  refuses the rest); the sandbox's policy is the boundary for what Bash can reach.
- Codex: `codex exec --json … -`, the brief on stdin, with Codex's own sandbox off
  (`danger-full-access`) because the run is already in one.
- OpenCode 2: `opencode run --standalone --format json --auto`, the brief on stdin, on any provider's
  model (one OpenCode per provider: its key and the one host the sandbox lets it reach). Its config
  is ours, never the repo's (`OPENCODE_DISABLE_PROJECT_CONFIG`, `OPENCODE_CONFIG_CONTENT`).
- fx (opt-in, `DOTRIX_CODING_FX`): `fx acp` driven by infra/coding/fx-acp.mjs, the brief on stdin, on an
  OpenAI-compatible provider's model (one per provider, like OpenCode), in fx's full-access mode.
"""
from __future__ import annotations

import json
import os
import shlex
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.agents.llm import PROVIDERS, available_models

from .models import CODING_AGENT_NAME, CodingAgent

MAX_STEP = 300  # characters of one step shown on the run page
CLAUDE_TOOLS = "Read,Edit,Write,MultiEdit,Glob,Grep,Bash,TodoWrite"

# The agent's browser: Playwright MCP in the sandbox (infra/coding/Dockerfile), headless Chromium with
# its profile in memory. It opens what the agent serves on localhost; the sandbox's network rules apply
# to everything else. Only the platform's MCP servers load (--strict-mcp-config), never a repo's.
BROWSER_SERVER = "browser"
BROWSER_MCP = {
    "mcpServers": {
        BROWSER_SERVER: {
            "command": "playwright-mcp",
            "args": ["--headless", "--isolated", "--browser", "chromium", "--no-sandbox", "--output-dir", "/tmp/playwright"],
        }
    }
}
BROWSER_RULE = """\
- You have a headless browser (the `browser` tools). When the change shows in a web page, start
  the app's dev server in the background on localhost and note its process id (for example
  `python3 -m http.server 8080 >/tmp/server.log 2>&1 & echo $! >/tmp/server.pid` for static files,
  or the project's dev script), open it, check the change works, and take a screenshot of it: the
  browser saves screenshots in /tmp/playwright, never in the repository, and the person sees them.
  When you're done, stop the server with `kill $(cat /tmp/server.pid)`. Pages outside this machine
  can't be reached, and that's expected.
"""


@dataclass(frozen=True)
class Step:
    kind: str  # "text" (the agent's words), "tool" (what it did), "output" / "output-error", "step", "error"
    text: str
    ref: str | None = None  # a command and its output share it (the tool call's id)


MAX_OUTPUT = 8_000  # of a command's output: its start and, mostly, its end (where errors are)


def output_step(text: str, ref: str | None, *, failed: bool) -> Step:
    """A command's output as the session's Terminal shows it."""
    text = text.rstrip()
    if len(text) > MAX_OUTPUT:
        text = text[:1_500] + f"\n… ({len(text) - MAX_OUTPUT:,} characters left out) …\n" + text[-(MAX_OUTPUT - 1_500):]
    return Step("output-error" if failed else "output", text, ref)


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(c.get("text", "")) for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    # Claude Code repeats a model call's usage on each of its content blocks: counted once.
    _calls: dict[str, tuple[int, int]] = field(default_factory=dict)
    # The tool calls of this run that ran a command: their results are kept as the command's output.
    _commands: set[str] = field(default_factory=set)
    # fx: each tool call's description, for when it fails (its result comes on a later line).
    _tools: dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Parsed:
    steps: list[Step] = field(default_factory=list)
    summary: str | None = None  # the agent's final message, when this line carried it
    failed: str | None = None  # the tool reported it couldn't finish


class CodingTool(Protocol):
    """What the runner and sandboxes need from a coding tool; nothing outside this module names one."""

    agent: CodingAgent
    name: str  # the engine, for logs and the record only: people see Kai (`CODING_AGENT_NAME`), never this
    provider: str  # whose model it runs on, as dotrix names it ("anthropic"): the key it takes (`run_key`)
    key_env: str  # the model key's environment variable
    provider_type: str  # its OpenShell provider profile
    api_host: str  # where its model API is (the Docker sandbox lets it through, nothing else)
    base_url_env: str  # a proxy in front of the provider, when this is set
    resumes: bool  # its conversation carries over between turns (saved, and restored in a fresh sandbox)
    browser: bool  # it can use the sandbox's browser (Playwright MCP)

    def command(self, model: str | None, browser: bool = False) -> list[str]: ...
    def session_args(self, session: uuid.UUID, resumed: bool) -> list[str]: ...
    # Shell, run in the sandbox: the session's conversation as base64 on stdout, and back from stdin.
    def save_state(self, session: uuid.UUID) -> str: ...
    def restore_state(self, session: uuid.UUID) -> str: ...
    # Shell whose stdout `read_usage` reads after a turn, for totals its events leave out (or None).
    def usage_command(self, session: uuid.UUID) -> str | None: ...
    def read_usage(self, output: str, usage: Usage) -> None: ...
    def sandbox_env(self, model_key: str) -> dict[str, str]: ...
    def model(self, settings: Settings) -> str | None: ...
    def parse(self, line: str, usage: Usage) -> Parsed: ...


class _NoUsageCommand:
    """Tools whose events already carry every token and the cost."""

    def usage_command(self, session: uuid.UUID) -> str | None:
        return None

    def read_usage(self, output: str, usage: Usage) -> None:
        return None


def _bare(model: str) -> str:
    """A model as its engine names it: "anthropic:claude-sonnet-5-5" → "claude-sonnet-5-5" (a bare name stays)."""
    return model.partition(":")[2] or model


def _clip(text: str, limit: int = MAX_STEP) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _relative(path: str) -> str:
    for prefix in ("/sandbox/repo/", "./"):
        if path.startswith(prefix):
            return path[len(prefix):]
    return path.rsplit("/repo/", 1)[-1] if "/repo/" in path else path


def _describe_browser(action: str, args: dict[str, Any]) -> str:
    target = _clip(str(args.get("element") or args.get("ref") or ""), 80)
    match action:
        case "browser_navigate":
            return f"Opened {_clip(str(args.get('url', '')), 120)} in the browser"
        case "browser_take_screenshot":
            return "Took a screenshot"
        case "browser_snapshot":
            return "Read the page"
        case "browser_click":
            return f"Clicked {target}" if target else "Clicked in the page"
        case "browser_type" | "browser_fill_form" | "browser_select_option":
            return f"Filled in {target}" if target else "Filled in the page"
        case "browser_console_messages":
            return "Read the browser console"
        case "browser_wait_for":
            return "Waited for the page"
        case "browser_run_code" | "browser_run_code_unsafe" | "browser_evaluate":
            return "Ran a script in the page"
        case "browser_find":
            looked = _clip(str(args.get("text") or args.get("query") or args.get("selector") or ""), 80)
            return f"Looked for {looked} in the page" if looked else "Looked through the page"
        case _:
            return f"Used the browser ({action.removeprefix('browser_').replace('_', ' ')})"


def _describe_claude_tool(name: str, args: dict[str, Any]) -> str | None:
    if name.startswith(f"mcp__{BROWSER_SERVER}__"):
        return _describe_browser(name.removeprefix(f"mcp__{BROWSER_SERVER}__"), args)
    path = _relative(str(args.get("file_path") or args.get("path") or ""))
    match name:
        case "Bash":
            return f"Ran {_clip(str(args.get('command', '')), 160)}"
        case "Edit" | "MultiEdit":
            return f"Edited {path}"
        case "Write":
            return f"Wrote {path}"
        case "Read":
            return f"Read {path}"
        case "Glob" | "Grep":
            return f"Searched for {_clip(str(args.get('pattern', '')), 80)}"
        case "TodoWrite":
            return None
        case _:
            return f"Used {name}"


class ClaudeCode(_NoUsageCommand):
    agent = CodingAgent.CLAUDE_CODE
    name = "Claude Code"
    provider = "anthropic"
    key_env = "ANTHROPIC_API_KEY"
    provider_type = "dotrix-claude-code"
    api_host = "api.anthropic.com"
    base_url_env = "ANTHROPIC_BASE_URL"
    resumes = True
    browser = True

    def session_args(self, session: uuid.UUID, resumed: bool) -> list[str]:
        return ["--resume", str(session)] if resumed else ["--session-id", str(session)]

    def save_state(self, session: uuid.UUID) -> str:  # its transcript: ~/.claude
        return 'cd "$HOME" && [ -d .claude ] && tar -cz .claude | base64 -w0'

    def restore_state(self, session: uuid.UUID) -> str:
        return 'cd "$HOME" && base64 -d | tar -xz'

    def sandbox_env(self, model_key: str) -> dict[str, str]:
        return {self.key_env: model_key}

    def model(self, settings: Settings) -> str | None:
        return settings.coding_claude_model

    def command(self, model: str | None, browser: bool = False) -> list[str]:
        """`browser`: give it the browser (a sandbox with the coding image; not the local one)."""
        allowed = CLAUDE_TOOLS + (f",mcp__{BROWSER_SERVER}" if browser else "")
        argv = [
            "claude", "-p", "--bare", "--output-format", "stream-json", "--verbose",
            "--permission-mode", "dontAsk", "--allowedTools", allowed,
            "--disallowedTools", "WebFetch,WebSearch", "--strict-mcp-config",
        ]
        if browser:
            argv += ["--mcp-config", json.dumps(BROWSER_MCP)]
        return argv + (["--model", _bare(model)] if model else [])

    def parse(self, line: str, usage: Usage) -> Parsed:
        out = Parsed()
        event = _json(line)
        if event is None:
            return out
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            out.steps.append(Step("step", f"Started ({event.get('model') or 'default model'})"))
            for server in event.get("mcp_servers") or []:  # a server that didn't start is said, not skipped
                if server.get("name") == BROWSER_SERVER and server.get("status") != "connected":
                    out.steps.append(Step("error", f"The browser didn't start ({server.get('status') or 'unknown'})"))
        elif kind == "system" and event.get("subtype") == "api_retry":
            error = str(event.get("error") or event.get("error_status") or "error")
            if event.get("error_status") in (401, 403):  # retrying won't help: stop now
                out.failed = f"The model provider refused the key ({error})"
            else:
                out.steps.append(Step("error", f"A model call failed ({error}); retry {event.get('attempt')}"))
        elif kind == "assistant":
            message = event.get("message") or {}
            for block in message.get("content") or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    out.steps.append(Step("text", _clip(block["text"])))
                elif block.get("type") == "tool_use":
                    said = _describe_claude_tool(str(block.get("name")), block.get("input") or {})
                    ref = str(block.get("id") or "") or None
                    if block.get("name") == "Bash" and ref:
                        usage._commands.add(ref)
                    if said:
                        out.steps.append(Step("tool", said, ref if block.get("name") == "Bash" else None))
            calls = message.get("usage") or {}
            if message.get("id") and calls:
                usage._calls[message["id"]] = (
                    int(calls.get("input_tokens") or 0) + int(calls.get("cache_creation_input_tokens") or 0)
                    + int(calls.get("cache_read_input_tokens") or 0),
                    int(calls.get("output_tokens") or 0),
                )
                usage.input_tokens = sum(i for i, _ in usage._calls.values())
                usage.output_tokens = sum(o for _, o in usage._calls.values())
        elif kind == "user":  # the results of its tool calls: a command's output is kept
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result" \
                        and block.get("tool_use_id") in usage._commands:
                    out.steps.append(output_step(_tool_result_text(block.get("content")), block["tool_use_id"],
                                                 failed=bool(block.get("is_error"))))
        elif kind == "result":
            totals = event.get("usage") or {}
            if totals:
                usage.input_tokens = max(usage.input_tokens, int(totals.get("input_tokens") or 0)
                                         + int(totals.get("cache_creation_input_tokens") or 0)
                                         + int(totals.get("cache_read_input_tokens") or 0))
                usage.output_tokens = max(usage.output_tokens, int(totals.get("output_tokens") or 0))
            if event.get("total_cost_usd") is not None:
                usage.cost_usd = float(event["total_cost_usd"])
            if event.get("is_error") or str(event.get("subtype", "")).startswith("error"):
                out.failed = _clip(str(event.get("result") or event.get("subtype") or f"{CODING_AGENT_NAME} stopped"), 500)
            elif event.get("result"):
                out.summary = str(event["result"])[:20_000]
        return out


class Codex(_NoUsageCommand):
    agent = CodingAgent.CODEX
    name = "Codex"
    provider = "openai"
    key_env = "OPENAI_API_KEY"
    provider_type = "dotrix-codex"
    api_host = "api.openai.com"
    base_url_env = "OPENAI_BASE_URL"
    resumes = False  # `--ephemeral`: each turn starts afresh
    browser = False  # not yet

    def session_args(self, session: uuid.UUID, resumed: bool) -> list[str]:
        return []

    def save_state(self, session: uuid.UUID) -> str:
        raise NotImplementedError("Codex doesn't resume")

    def restore_state(self, session: uuid.UUID) -> str:
        raise NotImplementedError("Codex doesn't resume")

    def sandbox_env(self, model_key: str) -> dict[str, str]:
        return {self.key_env: model_key, "CODEX_API_KEY": model_key}  # CODEX_API_KEY: what `codex exec` reads

    def model(self, settings: Settings) -> str | None:
        return settings.coding_codex_model

    def command(self, model: str | None, browser: bool = False) -> list[str]:
        argv = ["codex", "exec", "--json", "--skip-git-repo-check", "--sandbox", "danger-full-access", "--ephemeral"]
        return argv + (["-c", f'model="{_bare(model)}"'] if model else []) + ["-"]

    def parse(self, line: str, usage: Usage) -> Parsed:
        out = Parsed()
        event = _json(line)
        if event is None:
            return out
        kind = event.get("type")
        item = event.get("item") or {}
        if kind == "thread.started":
            out.steps.append(Step("step", "Started"))
        elif kind == "item.started" and item.get("type") == "command_execution":
            out.steps.append(Step("tool", f"Ran {_clip(str(item.get('command', '')), 160)}", item.get("id")))
        elif kind == "item.completed":
            match item.get("type"):
                case "command_execution":
                    out.steps.append(output_step(str(item.get("aggregated_output") or ""), item.get("id"),
                                                 failed=item.get("exit_code") not in (0, None)))
                case "agent_message" if str(item.get("text", "")).strip():
                    out.steps.append(Step("text", _clip(item["text"])))
                    out.summary = str(item["text"])[:20_000]
                case "file_change":
                    for change in item.get("changes") or []:
                        out.steps.append(Step("tool", f"Edited {_relative(str(change.get('path', '')))}"))
        elif kind == "turn.completed":
            turn = event.get("usage") or {}
            usage.input_tokens += int(turn.get("input_tokens") or 0)
            usage.output_tokens += int(turn.get("output_tokens") or 0)
        elif kind in ("turn.failed", "error"):
            message = (event.get("error") or {}).get("message") if kind == "turn.failed" else event.get("message")
            out.failed = _clip(str(message or f"{CODING_AGENT_NAME} stopped"), 500)
        return out


@dataclass(frozen=True)
class OpenCodeProvider:
    """A provider OpenCode can run on: dotrix's name for it (as in "anthropic:claude-sonnet-5-5",
    and in `run_keys`), OpenCode's, and what the sandbox needs to let it through."""

    name: str
    opencode: str  # OpenCode's provider id ("anthropic/claude-sonnet-5-5")
    label: str
    key_env: str  # the key's variable, which OpenCode reads
    api_host: str
    base_url_env: str  # a proxy in front of the provider, when this is set
    setting: str  # Settings attribute with the server's key
    # What OpenCode's SDK wants after the base URL that Claude Code and Codex take (Anthropic's SDK
    # in OpenCode posts to `{baseURL}/messages`; Claude Code to `{ANTHROPIC_BASE_URL}/v1/messages`).
    base_url_suffix: str = ""


OPENCODE_PROVIDERS = {
    p.name: p for p in (
        OpenCodeProvider("anthropic", "anthropic", "Anthropic", "ANTHROPIC_API_KEY", "api.anthropic.com",
                         "ANTHROPIC_BASE_URL", "anthropic_api_key", "/v1"),
        OpenCodeProvider("openai", "openai", "OpenAI", "OPENAI_API_KEY", "api.openai.com",
                         "OPENAI_BASE_URL", "openai_api_key"),
        OpenCodeProvider("google_genai", "google", "Google", "GOOGLE_API_KEY", "generativelanguage.googleapis.com",
                         "GOOGLE_GEMINI_BASE_URL", "google_api_key"),
        OpenCodeProvider("xai", "xai", "xAI (Grok)", "XAI_API_KEY", "api.x.ai", "XAI_BASE_URL", "xai_api_key"),
        OpenCodeProvider("deepseek", "deepseek", "DeepSeek", "DEEPSEEK_API_KEY", "api.deepseek.com", "DEEPSEEK_BASE_URL", "deepseek_api_key"),
        OpenCodeProvider("mistral", "mistral", "Mistral", "MISTRAL_API_KEY", "api.mistral.ai", "MISTRAL_BASE_URL", "mistral_api_key"),
        OpenCodeProvider("groq", "groq", "Groq", "GROQ_API_KEY", "api.groq.com", "GROQ_BASE_URL", "groq_api_key"),
        OpenCodeProvider("openrouter", "openrouter", "OpenRouter", "OPENROUTER_API_KEY", "openrouter.ai", "OPENROUTER_BASE_URL", "openrouter_api_key"),
    )
}
# Never offered to the model: the sandbox can't reach the web, and a run has nobody to answer.
OPENCODE_DENIED = ("webfetch", "websearch", "question")
OPENCODE_DATA = ".local/share/opencode"  # under $HOME; also holds a git copy of the worktree, so never saved whole


def opencode_session(session: uuid.UUID) -> str:
    """OpenCode's id for a dotrix session: `-s` makes the session with it, then continues it."""
    return f"ses_{session.hex}"


def _describe_opencode_tool(name: str, args: dict[str, Any]) -> str | None:
    path = _relative(str(args.get("path") or ""))
    match name:
        case "shell":
            return f"Ran {_clip(str(args.get('command', '')), 160)}"
        case "edit":
            return f"Edited {path}"
        case "write":
            return f"Wrote {path}"
        case "read":
            return f"Read {path}"
        case "glob" | "grep":
            return f"Searched for {_clip(str(args.get('pattern', '')), 80)}"
        case "execute":
            return "Ran a script"
        case "subagent":
            return f"Asked a subagent to {_clip(str(args.get('description', '')), 120)}"
        case "skill":
            return None
        case _:
            return f"Used {name}"


def _tokens(part: dict[str, Any]) -> tuple[int, int]:
    tokens = part.get("tokens") or {}
    cache = tokens.get("cache") or {}
    return (int(tokens.get("input") or 0) + int(cache.get("read") or 0) + int(cache.get("write") or 0),
            int(tokens.get("output") or 0) + int(tokens.get("reasoning") or 0))


# After a turn: the session's running cost and this turn's steps (each step is an assistant message;
# the last one never reaches the event stream), read in the sandbox so a long session's export never
# has to come back whole.
_OPENCODE_TOTALS = (
    "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{const d=JSON.parse(s);let turn=[];"
    "for(const m of d.messages||[]){if(m.type==='user')turn=[];"
    "else if(m.type==='assistant')turn.push({id:m.id,tokens:m.tokens})}"
    "console.log(JSON.stringify({cost:(d.info||{}).cost,turn}))})"
)


class OpenCode:
    """OpenCode 2 on one provider. Checked against a fake model (2.1.4): the brief on stdin, `-s` our
    session id, events `step_start` / `text` / `tool_use` / `step_finish` / `error`, SIGINT stops it."""

    agent = CodingAgent.OPENCODE
    name = "OpenCode"
    resumes = True
    browser = False  # not yet: Playwright MCP through `OPENCODE_CONFIG_CONTENT` is unchecked

    def __init__(self, provider: OpenCodeProvider) -> None:
        self.opencode_provider = provider
        self.provider = provider.name
        self.key_env, self.api_host, self.base_url_env = provider.key_env, provider.api_host, provider.base_url_env
        self.provider_type = f"dotrix-opencode-{provider.opencode}"  # infra/coding/dotrix-opencode-*.yaml

    def _env(self, model: str | None = None) -> list[str]:
        """Its settings, before every command (`env …`): the same in each sandbox, OpenShell's too,
        which passes the sandbox nothing but the key. None of them is a secret."""
        config: dict[str, Any] = {
            "enabled_providers": [self.opencode_provider.opencode],  # not every provider it finds credentials for
            "permission": {tool: "deny" for tool in OPENCODE_DENIED},
            "autoupdate": False,
        }
        if base_url := os.environ.get(self.base_url_env, "").rstrip("/"):
            # The URL itself, not `{env:…}`: OpenShell passes the sandbox nothing but the key.
            config["provider"] = {self.opencode_provider.opencode: {"options": {"baseURL": base_url + self.opencode_provider.base_url_suffix}}}
        elif endpoint := PROVIDERS[self.provider].base_url:
            config["provider"] = {self.opencode_provider.opencode: {"options": {"baseURL": endpoint}}}
        if model:
            # The pinned CLI's built-in catalogue may predate a platform-configured model.
            config.setdefault("provider", {}).setdefault(self.opencode_provider.opencode, {})["models"] = {
                model.partition(":")[2]: {}
            }
        return [
            f"OPENCODE_CONFIG_CONTENT={json.dumps(config, separators=(',', ':'))}",
            "OPENCODE_DISABLE_PROJECT_CONFIG=1",  # the repo's opencode.json is data, not config
            "OPENCODE_DISABLE_MODELS_FETCH=1",  # its built-in model list: the sandbox reaches one host only
            "OPENCODE_DISABLE_AUTOUPDATE=1",
        ]

    def _shell(self, args: str) -> str:
        return "env " + " ".join(shlex.quote(pair) for pair in self._env()) + f" opencode {args}"

    def command(self, model: str | None, browser: bool = False) -> list[str]:
        argv = ["env", *self._env(model), "opencode", "run", "--standalone", "--format", "json", "--auto"]
        if model:
            argv += ["-m", f"{self.opencode_provider.opencode}/{model.partition(':')[2] or model}"]
        return argv

    def session_args(self, session: uuid.UUID, resumed: bool) -> list[str]:
        return ["-s", opencode_session(session)]  # made the first time, continued after

    def save_state(self, session: uuid.UUID) -> str:
        sid = shlex.quote(opencode_session(session))
        return self._shell(f"session export --standalone {sid} </dev/null") + " | gzip | base64 -w0"

    def restore_state(self, session: uuid.UUID) -> str:
        return ("base64 -d | gunzip > /tmp/opencode-session.json && "
                + self._shell("session import --standalone /tmp/opencode-session.json </dev/null >/dev/null"))

    def usage_command(self, session: uuid.UUID) -> str | None:
        sid = shlex.quote(opencode_session(session))
        return self._shell(f"session export --standalone {sid} </dev/null") + f" | node -e {shlex.quote(_OPENCODE_TOTALS)}"

    def read_usage(self, output: str, usage: Usage) -> None:
        totals = _json(output.strip().splitlines()[-1] if output.strip() else "")
        if totals is None:
            return
        for step in totals.get("turn") or []:  # the steps the stream didn't report
            if step.get("id") and step["id"] not in usage._calls:
                usage._calls[step["id"]] = _tokens(step)
        usage.input_tokens = sum(i for i, _ in usage._calls.values())
        usage.output_tokens = sum(o for _, o in usage._calls.values())
        if totals.get("cost") is not None:
            usage.cost_usd = float(totals["cost"])  # the session's running total, like Claude Code's

    def sandbox_env(self, model_key: str) -> dict[str, str]:
        return {self.key_env: model_key}

    def model(self, settings: Settings) -> str | None:
        return settings.coding_opencode_model

    def parse(self, line: str, usage: Usage) -> Parsed:
        out = Parsed()
        event = _json(line)
        if event is None:
            return out
        part = event.get("part") or {}
        match event.get("type"):
            case "text" if str(part.get("text", "")).strip():
                out.steps.append(Step("text", _clip(part["text"])))
                out.summary = str(part["text"])[:20_000]  # the last one is its final message
            case "tool_use":
                state = part.get("state") or {}
                said = _describe_opencode_tool(str(part.get("tool")), state.get("input") or {})
                command = part.get("tool") in ("shell", "bash")
                ref = str(part.get("callID") or part.get("id") or "") or None if command else None
                if state.get("status") == "error" and not command:  # a failed command shows in the Terminal instead
                    out.steps.append(Step("error", _clip(f"{said or part.get('tool')}: {state.get('error') or 'failed'}")))
                elif said:
                    out.steps.append(Step("tool", said, ref))
                if command and state.get("status") in ("completed", "error") and (state.get("output") or state.get("error")):
                    metadata = state.get("metadata") or {}
                    out.steps.append(output_step(str(state.get("output") or state.get("error") or ""), ref,
                                                 failed=state.get("status") == "error" or metadata.get("exit") not in (0, None)))
            case "step_finish":
                if part.get("messageID"):
                    usage._calls[part["messageID"]] = _tokens(part)
                    usage.input_tokens = sum(i for i, _ in usage._calls.values())
                    usage.output_tokens = sum(o for _, o in usage._calls.values())
            case "error":
                error = event.get("error") or {}
                out.failed = _clip(str(error.get("message") or error.get("type") or f"{CODING_AGENT_NAME} stopped"), 500)
        return out


# fx: OpenAI-compatible endpoints only (fx's custom providers speak Chat Completions): those of its chat preview
# (agents/fx_pilot.py), and Anthropic's OpenAI-compatible endpoint (checked with fx 0.0.16 on Claude Haiku 5.5,
# 2026-10-30); the key's variable and host as OpenCode has them.
FX_ENDPOINTS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    **{name: provider.base_url for name, provider in PROVIDERS.items() if provider.base_url},
}
FX_PROVIDERS = {name: p for name, p in OPENCODE_PROVIDERS.items() if name in FX_ENDPOINTS}
FX_DATA = ".fx"  # under $HOME: fx's sessions, and ours (`.fx/dotrix`: the fx session of each dotrix session)
FX_STOPS = {  # a turn that ended any other way than end_turn: what the person reads
    "cancelled": "Stopped",
    "max_tokens": "The model's output limit was reached",
    "max_turn_requests": f"{CODING_AGENT_NAME} reached its step limit for one turn",
    "refusal": "The model refused",
    "refused": "The model refused",
}


def _describe_fx_tool(name: str, title: str, args: dict[str, Any]) -> str | None:
    path = _relative(str(args.get("path") or args.get("file_path") or ""))
    request = args.get("request") if isinstance(args.get("request"), dict) else {}
    match name:
        case "shell":
            command = request.get("command") or args.get("command")
            return f"Ran {_clip(str(command), 160)}" if command else None  # its other actions read a running one
        case "edit_file":
            return f"Edited {path}"
        case "write_file":
            return f"Wrote {path}"
        case "read_file":
            return f"Read {path}"
        case "glob_files" | "grep_files":
            return f"Searched for {_clip(str(args.get('pattern') or args.get('query') or ''), 80)}"
        case "subagent":
            return f"Asked a subagent to {_clip(str(args.get('description') or args.get('prompt') or ''), 120)}"
        case "read_tool_result" | "skill" | "skill_search" | "capability_search":
            return None
        case _:
            return _clip(title, 160) if title else f"Used {name}"


class Fx:
    """fx on one OpenAI-compatible provider, through ACP (infra/coding/fx-acp.mjs prints its JSON lines). Checked
    with the real fx 0.0.16 against a fake model and on Claude Haiku 5.5 (a turn, resume, a restored session, Stop),
    and against a fake ACP server in tests/unit/test_fx_coding.py."""

    agent = CodingAgent.FX
    name = "fx"
    resumes = True  # fx saves its sessions under ~/.fx; the driver continues ours with --resume
    browser = False  # its own browser tools aren't passed in yet

    def __init__(self, provider: OpenCodeProvider, driver: str = "/opt/dotrix/fx-acp.mjs") -> None:
        self.fx_provider = provider
        self.driver = driver
        self.provider = provider.name
        self.key_env, self.api_host, self.base_url_env = provider.key_env, provider.api_host, provider.base_url_env
        self.provider_type = f"dotrix-fx-{provider.opencode}"  # infra/coding/dotrix-fx-*.yaml

    def _base_url(self) -> str:
        # A proxy in front of the provider takes the same path after it as OpenCode's (Anthropic's: /v1).
        if proxy := os.environ.get(self.base_url_env, "").rstrip("/"):
            return proxy + self.fx_provider.base_url_suffix
        return FX_ENDPOINTS[self.provider]

    def command(self, model: str | None, browser: bool = False) -> list[str]:
        name = (model or "").partition(":")[2] or (model or "")
        return ["node", self.driver, "--base-url", self._base_url(), "--key-env", self.key_env, "--model", name]

    def session_args(self, session: uuid.UUID, resumed: bool) -> list[str]:
        return ["--session", session.hex, *(["--resume"] if resumed else [])]

    def save_state(self, session: uuid.UUID) -> str:  # its sessions and ours; the settings are written each turn
        return f'cd "$HOME" && [ -d {FX_DATA} ] && tar -cz --exclude={FX_DATA}/settings.json {FX_DATA} | base64 -w0'

    def restore_state(self, session: uuid.UUID) -> str:
        return 'cd "$HOME" && base64 -d | tar -xz'

    def usage_command(self, session: uuid.UUID) -> str | None:
        return None  # the turn's end carries its usage

    def read_usage(self, output: str, usage: Usage) -> None:
        return None

    def sandbox_env(self, model_key: str) -> dict[str, str]:
        return {self.key_env: model_key}

    def model(self, settings: Settings) -> str | None:
        return settings.coding_fx_model

    def parse(self, line: str, usage: Usage) -> Parsed:
        out = Parsed()
        event = _json(line)
        if event is None:
            return out
        match event.get("type"):
            case "started":
                said = "Continued the conversation" if event.get("resumed") else "Started"
                if event.get("fresh"):
                    said = "Started a new conversation (the earlier one couldn't be restored)"
                out.steps.append(Step("step", f"{said} ({event.get('model') or 'default model'})"))
            case "text" if str(event.get("text", "")).strip():
                out.steps.append(Step("text", _clip(str(event["text"]))))
            case "tool":
                ref = str(event.get("id") or "") or None
                name, args = str(event.get("name") or ""), event.get("input") if isinstance(event.get("input"), dict) else {}
                said = _describe_fx_tool(name, str(event.get("title") or ""), args)
                command = name == "shell" and said is not None
                if ref:
                    usage._tools[ref] = said or name
                    if command:
                        usage._commands.add(ref)
                if said:
                    out.steps.append(Step("tool", said, ref if command else None))
            case "tool_result":
                ref = str(event.get("id") or "")
                failed = event.get("status") == "failed"
                if ref in usage._commands:
                    out.steps.append(output_step(str(event.get("output") or ""), ref, failed=failed))
                elif failed:
                    detail = str(event.get("output") or "failed")
                    out.steps.append(Step("error", _clip(f"{usage._tools.get(ref) or 'A tool'}: {detail}")))
            case "done":
                totals = event.get("usage") or {}
                usage.input_tokens = int(totals.get("inputTokens") or 0) + int(totals.get("cacheReadTokens") or 0) \
                    + int(totals.get("cacheWriteTokens") or 0)
                usage.output_tokens = int(totals.get("outputTokens") or 0) + int(totals.get("reasoningTokens") or 0)
                reason = str(event.get("stopReason") or "end_turn")
                if reason != "end_turn":
                    out.failed = FX_STOPS.get(reason, f"{CODING_AGENT_NAME} stopped ({reason})")
                elif event.get("final"):
                    out.summary = str(event["final"])[:20_000]
            case "error":
                out.failed = _clip(str(event.get("message") or f"{CODING_AGENT_NAME} stopped"), 500)
        return out


def _json(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


TOOLS: dict[CodingAgent, CodingTool] = {CodingAgent.CLAUDE_CODE: ClaudeCode(), CodingAgent.CODEX: Codex()}


def tool_for(agent: CodingAgent, model: str | None = None, settings: Settings | None = None) -> CodingTool | None:
    """The tool for a run: OpenCode and fx are one per provider, from its model ("anthropic:…"); None
    when that provider isn't one they run on here."""
    if agent in TOOLS:
        return TOOLS[agent]
    name, _, rest = (model or "").partition(":")
    if agent is CodingAgent.FX:
        provider = FX_PROVIDERS.get(name)
        driver = settings.coding_fx_driver if settings is not None else "/opt/dotrix/fx-acp.mjs"
        return Fx(provider, driver) if provider is not None and rest else None
    provider = OPENCODE_PROVIDERS.get(name)
    return OpenCode(provider) if provider is not None and rest else None


def run_key(tool: CodingTool, settings: Settings, keys: dict[str, str]) -> str | None:
    """Only the requesting person's key for the selected provider."""
    if keys.get(tool.provider):
        return keys[tool.provider]
    return None


def coding_models(settings: Settings, providers: frozenset[str] | set[str]) -> list[str]:
    return [m for m in available_models(settings, *([settings.coding_opencode_model] if settings.coding_opencode_model else []),
                                       connected=set(providers))
            if m.partition(":")[0] in OPENCODE_PROVIDERS]


def fx_models(settings: Settings, providers: frozenset[str] | set[str]) -> list[str]:
    """The models fx can run on for these providers; none while fx is off (`DOTRIX_CODING_FX`)."""
    if not settings.coding_fx:
        return []
    return [m for m in available_models(settings, *([settings.coding_fx_model] if settings.coding_fx_model else []),
                                       connected=set(providers))
            if m.partition(":")[0] in FX_PROVIDERS]


def models_for(settings: Settings, agent: CodingAgent, providers: frozenset[str] | set[str]) -> list[str]:
    """The models this engine can code on with these providers."""
    if agent is CodingAgent.OPENCODE:
        return coding_models(settings, providers)
    if agent is CodingAgent.FX:
        return fx_models(settings, providers)
    native = TOOLS[agent].provider  # Claude Code: Anthropic's; Codex: OpenAI's
    also = [m for m in (TOOLS[agent].model(settings),) if m and ":" in m]
    return [m for m in available_models(settings, *also, connected=set(providers)) if m.partition(":")[0] == native]


# Which engine runs a model when the person hasn't set one that can: its provider's own, else OpenCode.
AUTO_ENGINE = {"anthropic": CodingAgent.CLAUDE_CODE, "openai": CodingAgent.CODEX}


def kai_models(settings: Settings, providers: frozenset[str] | set[str]) -> list[str]:
    """Every model Kai can code on with these providers, whatever engine runs it: what a new session offers."""
    found: list[str] = []
    for agent in (CodingAgent.CLAUDE_CODE, CodingAgent.CODEX, CodingAgent.OPENCODE, CodingAgent.FX):
        found += [m for m in models_for(settings, agent, providers) if m not in found]
    return found


def engine_for(
    settings: Settings, model: str, providers: frozenset[str] | set[str], preferred: str | None = None,
) -> CodingAgent | None:
    """The engine Kai codes on for a model: the person's preferred engine (Account → Your models) when it can
    run that model, else the model's provider's own (Claude Code for Anthropic, Codex for OpenAI), else OpenCode."""
    auto = AUTO_ENGINE.get(model.partition(":")[0], CodingAgent.OPENCODE)
    for name in dict.fromkeys([preferred, settings.coding_agent, auto, CodingAgent.OPENCODE]):
        if name in (None, "auto") or name not in set(CodingAgent):
            continue
        agent = CodingAgent(name)
        if model in models_for(settings, agent, providers):
            return agent
    return None


def choose_agent(
    settings: Settings, providers: frozenset[str] | set[str] = frozenset(), *,
    preferred: str | None = None, preferred_model: str | None = None,
) -> CodingAgent | None:
    """A compatible personal/server default, otherwise Codex, Claude Code, then OpenCode. fx only when it's
    asked for (a person's or the server's default) and on (`DOTRIX_CODING_FX`)."""
    order = [preferred, settings.coding_agent, CodingAgent.CODEX, CodingAgent.CLAUDE_CODE, CodingAgent.OPENCODE]
    for name in dict.fromkeys(order):
        if name in (None, "auto") or name not in set(CodingAgent):
            continue
        agent = CodingAgent(name)
        if agent is CodingAgent.FX and not settings.coding_fx:
            continue
        model = model_for(settings, agent, providers, preferred_model=preferred_model)
        tool = tool_for(agent, model, settings)
        if tool and tool.provider in providers:
            return agent
    return None


def model_for(
    settings: Settings, agent: CodingAgent, providers: frozenset[str] | set[str] = frozenset(), *,
    preferred_model: str | None = None,
) -> str | None:
    if agent is CodingAgent.OPENCODE:
        models = coding_models(settings, providers)
        for model in (settings.coding_opencode_model, preferred_model):
            if model in models:
                return model
        # Other providers have no native tool; use OpenCode with their first allowed model.
        return next((m for m in models if m.partition(":")[0] not in ("openai", "anthropic")),
                    next(iter(models), None))
    if agent is CodingAgent.FX:
        models = fx_models(settings, providers)
        for model in (settings.coding_fx_model, preferred_model):
            if model in models:
                return model
        return next(iter(models), None)
    return TOOLS[agent].model(settings)
