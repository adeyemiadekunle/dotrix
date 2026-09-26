"""MCP server: lets Claude Code, Codex, or any MCP client read a project's
`.pmagent/` knowledge and work its tasks, without that folder ever being in git.

    pmagent mcp --project <name-or-path> --assignee claude-code

Registered per tool with a user-level or local config, never a file in the
repo (see `pmagent handoff install`):

    claude mcp add --transport stdio --scope local pmagent -- pmagent mcp --project /abs/path --assignee claude-code
    codex mcp add pmagent-<project> -- pmagent mcp --project /abs/path --assignee codex

What a coding agent can do through it:
  - READ   project overview, any knowledge doc (requirements, architecture,
           ADRs, research, reviews, progress), full-text search, the task board.
  - WRITE  only its own task state: claim a task it was told to work on,
           comment, mark blocked, submit for review. The same operations the
           CLI offers coding agents, with the same locks and logging.

It cannot write or edit knowledge docs. Those are owned by the thinking
agents and change only in Action Mode with approval.
"""
from __future__ import annotations

import functools
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from pmagent_engine import tasks as T
from pmagent_engine.config import ProjectConfig

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
TASK_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                             idempotentHint=False, openWorldHint=False)

# Runtime state and internals that are never exposed.
_HIDDEN_PARTS = {".locks", "jobs", ".gitignore"}
_HIDDEN_PREFIXES = ("checkpoints.sqlite",)
_TEXT_EXTS = {".md", ".markdown", ".txt", ".yaml", ".yml", ".json", ".csv", ".rst"}
_MAX_READ_CHARS = 60_000

INSTRUCTIONS = """pmagent project knowledge and task board for this repo. The knowledge is NOT in git; this server is the only way to read it.

Before designing or writing code, read what applies: project_overview, then the relevant requirements/, architecture/ and decisions/ (ADRs) via search_docs / read_doc. Follow recorded decisions; if code must contradict an ADR, stop and tell the user.

Only work on a pmagent task when the user tells you to (by id, or "take the next task"). Then: claim_task, read its description and linked docs, implement, comment_task on meaningful progress, set_task_blocked if stuck, and finish with submit_for_review (never mark tasks done). You cannot edit knowledge docs; propose changes to the user instead. Never copy .pmagent/ content into the repo or commit it."""


def _is_hidden(rel: Path) -> bool:
    return any(p in _HIDDEN_PARTS for p in rel.parts) or rel.name.startswith(_HIDDEN_PREFIXES) \
        or any(p.startswith(".") and p != "." for p in rel.parts[:-1]) or rel.name.endswith(".tmp")


def _expected_errors(fn):
    """Refusals (bad path, wrong assignee, task not ready) are normal answers,
    not crashes. Raising ToolError sends the reason to the model so it can
    correct itself, instead of a generic "error executing tool" plus a stack
    trace on stderr."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, FileNotFoundError, TimeoutError) as e:
            raise ToolError(str(e)) from None
    return wrapper


def build_server(config: ProjectConfig, assignee: str) -> _Server:
    root = Path(config.pmagent_dir).resolve()
    _mcp = _Server(name=f"pmagent-{config.name}", instructions=INSTRUCTIONS)

    class _Registrar:  # server.tool(...) that also applies _expected_errors
        def tool(self, **kw):
            def deco(fn):
                return _mcp.tool(**kw)(_expected_errors(fn))
            return deco
    server = _Registrar()

    def _resolve(path: str) -> Path:
        rel = Path(path.strip().lstrip("/"))
        if rel.parts and rel.parts[0] == ".pmagent":
            rel = Path(*rel.parts[1:])
        full = (root / rel).resolve()
        if full != root and root not in full.parents:
            raise ValueError("Path is outside .pmagent/")
        if _is_hidden(full.relative_to(root)):
            raise ValueError("That path is internal and not readable")
        return full

    def _doc_files(folder: str | None) -> list[Path]:
        base = _resolve(folder) if folder else root
        if not base.is_dir():
            raise ValueError(f"No such folder: {folder}")
        out = []
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(root)
            if p.is_file() and p.suffix.lower() in _TEXT_EXTS and not _is_hidden(rel) \
                    and "originals" not in rel.parts:
                out.append(p)
        return out

    # -- knowledge (read-only) ---------------------------------------------
    @server.tool(annotations=READ_ONLY)
    def project_overview() -> dict:
        """Start here: project name, description, current state, and counts of
        docs and tasks by status. Cheap to call at the start of a session."""
        def read(name: str) -> str:
            p = root / name
            return p.read_text(errors="ignore")[:8000] if p.exists() else ""
        counts: dict[str, int] = {}
        for t in T.list_tasks(config):
            counts[t.status] = counts.get(t.status, 0) + 1
        folders = {}
        for d in ("requirements", "architecture", "decisions", "research", "reviews", "progress"):
            p = root / d
            folders[d] = len([f for f in p.rglob("*.md")]) if p.is_dir() else 0
        return {
            "name": config.name, "description": config.description,
            "project_md": read("project.md"), "current_state_md": read("current-state.md"),
            "doc_counts": folders, "task_counts": counts, "you_are": assignee,
        }

    @server.tool(annotations=READ_ONLY)
    def list_docs(folder: str | None = None) -> list[dict]:
        """List readable knowledge docs, optionally inside one folder such as
        "requirements", "architecture", "decisions", "research", "reviews",
        "progress", or "docs/normalized" (ingested reference docs)."""
        return [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size}
                for p in _doc_files(folder)]

    @server.tool(annotations=READ_ONLY)
    def read_doc(path: str) -> dict:
        """Read one knowledge doc by its path relative to .pmagent/, e.g.
        "requirements/checkout.md" or "decisions/ADR-014.md"."""
        p = _resolve(path)
        if not p.is_file():
            raise ValueError(f"No such doc: {path}. Use list_docs or search_docs.")
        if p.suffix.lower() not in _TEXT_EXTS:
            raise ValueError("Only text docs are readable; ingested originals have a "
                             "markdown copy under docs/normalized/")
        text = p.read_text(errors="ignore")
        truncated = len(text) > _MAX_READ_CHARS
        return {"path": str(p.relative_to(root)), "content": text[:_MAX_READ_CHARS],
                "truncated": truncated}

    @server.tool(annotations=READ_ONLY)
    def search_docs(query: str, folder: str | None = None, max_results: int = 20) -> list[dict]:
        """Case-insensitive text search across knowledge docs. Returns matching
        lines with their doc path and line number. Use it to find the
        requirement, ADR, or architecture note relevant to your task."""
        q = query.strip().lower()
        if not q:
            raise ValueError("query is empty")
        hits: list[dict] = []
        for p in _doc_files(folder):
            for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
                if q in line.lower():
                    hits.append({"path": str(p.relative_to(root)), "line": n, "text": line.strip()[:300]})
                    if len(hits) >= max(1, min(max_results, 100)):
                        return hits
        return hits

    # -- task board ----------------------------------------------------------
    @server.tool(annotations=READ_ONLY)
    def list_tasks(status: str | None = None, mine: bool = False,
                   ready_only: bool = False) -> list[dict]:
        """List tasks by priority then due date. `mine` = assigned to you;
        `ready_only` = could start now (todo, dependencies done, unassigned or yours)."""
        items = (T.ready_tasks(config, assignee) if ready_only
                 else T.list_tasks(config, status=status, assignee=assignee if mine else None,
                                   include_done=status == "done"))
        return [{k: v for k, v in t.to_dict().items() if k not in ("log", "description")}
                for t in items]

    @server.tool(annotations=READ_ONLY)
    def get_task(task_id: str) -> dict:
        """One task in full: description, acceptance criteria, dependencies, and log."""
        return T.get_task(config, task_id).to_dict()

    @server.tool(annotations=TASK_WRITE)
    def claim_task(task_id: str | None = None) -> dict:
        """Claim a task ONLY when the user told you to work on it. Pass the
        task_id they named; omit it only if they said "take the next task",
        which picks the highest-priority ready task (or resumes yours)."""
        if task_id:
            task = T.claim_task(config, task_id, assignee)
        else:
            task = T.next_task(config, assignee, claim=True)
            if task is None:
                return {"task": None, "message": "Nothing is ready for you."}
        return {"task": task.to_dict()}

    @server.tool(annotations=TASK_WRITE)
    def comment_task(task_id: str, text: str) -> dict:
        """Log meaningful progress, a decision you made, or a surprise on a task."""
        return T.comment_task(config, task_id, text, author=assignee).to_dict()

    @server.tool(annotations=TASK_WRITE)
    def set_task_blocked(task_id: str, reason: str) -> dict:
        """Mark a task you're working on as blocked, with why. Then stop and tell the user."""
        _require_mine(task_id)
        return T.update_task(config, task_id, author=assignee, status="blocked",
                             note=reason).to_dict()

    @server.tool(annotations=TASK_WRITE)
    def submit_for_review(task_id: str, summary: str) -> dict:
        """Hand a finished task back for review. The summary should cover what
        changed, which files, and how to test. Reviewers close it; you can't."""
        _require_mine(task_id)
        return T.complete_task(config, task_id, author=assignee, note=summary,
                               to_review=True).to_dict()

    def _require_mine(task_id: str) -> None:
        t = T.get_task(config, task_id)
        if t.assignee != assignee:
            raise ValueError(f"{t.id} is assigned to {t.assignee or 'nobody'}, not {assignee}")

    return _mcp


def run(config: ProjectConfig, assignee: str) -> None:
    build_server(config, assignee).run("stdio")
