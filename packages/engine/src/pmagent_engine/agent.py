"""Builds the PM Agent System for a given connected project.

Same design regardless of which project you're in: a PM/orchestrator agent
plus Product / Architecture / Research / Reviewer / Documentation subagents,
none of which touch application code, gated by Chat Mode vs Action Mode.
What changes per project is just the ProjectConfig passed in.

Checked against deepagents 0.7.19:
  - A subagent's instructions go in `system_prompt`. The key `prompt` is
    silently ignored, which is what the previous version used, so every
    subagent was running with no role instructions at all.
  - A subagent's `tools` list replaces the *custom* tools it inherits from
    the main agent. Filesystem tools (read_file, write_file, ...) come from
    middleware and are always present, so `tools` can't make an agent
    read-only. `permissions` can, and the Reviewer uses it.
  - Subagents inherit the top-level `interrupt_on`, so the Action Mode gate
    covers writes made by any subagent.
"""
from __future__ import annotations

from typing import Any

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend

from . import tasks as T
from .backend import LockingFilesystemBackend
from .config import ProjectConfig

# Tools that change task state, gated exactly like write_file/edit_file.
TASK_WRITE_TOOLS = ("create_task", "update_task", "comment_task")
_APPROVAL = {"allowed_decisions": ["approve", "edit", "reject"]}


def _web_search_tool(model: str) -> dict:
    """Provider-native web search. Each provider's built-in tool has a
    different shape, and the wrong one fails at the first model call."""
    provider = model.split(":", 1)[0] if ":" in model else ""
    if provider == "anthropic":
        return {"type": "web_search_20250305", "name": "web_search", "max_uses": 8}
    if provider == "openai":
        return {"type": "web_search"}
    if provider in ("google_genai", "google_vertexai"):
        return {"google_search": {}}
    raise ValueError(
        f"No built-in web search known for provider {provider!r}. "
        f"Pass a search tool (e.g. Tavily) in _web_search_tool()."
    )


def _task_tools(config: ProjectConfig) -> tuple[list, list]:
    """(read_tools, write_tools) bound to this project. Plain functions:
    deepagents turns the signature + docstring into the tool schema."""

    def list_tasks(status: str | None = None, assignee: str | None = None,
                   label: str | None = None, ready_only: bool = False) -> list[dict]:
        """List tasks on the project board, sorted by priority then due date.

        Args:
            status: Filter to one status: todo, in_progress, blocked, review, done.
            assignee: Filter to one assignee (e.g. "claude-code", "codex", a person).
            label: Filter to tasks carrying this label.
            ready_only: Only tasks that could start now (todo, deps done).
        """
        items = (T.ready_tasks(config) if ready_only
                 else T.list_tasks(config, status=status, assignee=assignee, label=label))
        return [{k: v for k, v in t.to_dict().items() if k != "log"} for t in items]

    def get_task(task_id: str) -> dict:
        """Get one task in full, including its description and activity log.

        Args:
            task_id: e.g. "TASK-1a2b3c4d".
        """
        return T.get_task(config, task_id).to_dict()

    def create_task(title: str, description: str = "", priority: str = "medium",
                    assignee: str | None = None, due: str | None = None,
                    scheduled: str | None = None, depends_on: list[str] | None = None,
                    labels: list[str] | None = None) -> dict:
        """Create a task on the project board. ACTION MODE ONLY.

        Write the description so a coding agent with no other context can do
        the work: what to build, where, acceptance criteria, and links to the
        relevant /pmagent/requirements/ or /pmagent/architecture/ files.

        Args:
            title: Short imperative title.
            description: Markdown body (see above).
            priority: low | medium | high | urgent.
            assignee: "claude-code", "codex", a person's name, or None for anyone.
            due: YYYY-MM-DD deadline.
            scheduled: YYYY-MM-DD or ISO datetime when work should happen.
            depends_on: Task ids that must be done first.
            labels: Free-form tags.
        """
        return T.create_task(config, title, description=description, priority=priority,
                             assignee=assignee, due=due, scheduled=scheduled,
                             depends_on=depends_on, labels=labels, author="pm-agent").to_dict()

    def update_task(task_id: str, status: str | None = None, priority: str | None = None,
                    assignee: str | None = None, due: str | None = None,
                    scheduled: str | None = None, depends_on: list[str] | None = None,
                    labels: list[str] | None = None, title: str | None = None,
                    description: str | None = None, note: str | None = None) -> dict:
        """Change fields on an existing task. Only pass what changes. ACTION MODE ONLY.

        Args:
            task_id: e.g. "TASK-1a2b3c4d".
            status: todo | in_progress | blocked | review | done.
            note: Optional explanation, appended to the task's log.
        """
        return T.update_task(config, task_id, author="pm-agent", note=note, status=status,
                             priority=priority, assignee=assignee, due=due,
                             scheduled=scheduled, depends_on=depends_on, labels=labels,
                             title=title, description=description).to_dict()

    def comment_task(task_id: str, text: str) -> dict:
        """Append a comment to a task's log. ACTION MODE ONLY.

        Args:
            task_id: e.g. "TASK-1a2b3c4d".
            text: The comment.
        """
        return T.comment_task(config, task_id, text, author="pm-agent").to_dict()

    return [list_tasks, get_task], [create_task, update_task, comment_task]


def _subagents(
    project_name: str,
    read_task_tools: list,
    web_search: dict | None,
    rules: dict[str, str] | None = None,
    context: str | None = None,
) -> list[dict]:
    def role(title: str, body: str) -> str:
        prompt = f"You are the {title} for {project_name}.\n{body}"
        return _with_context(_with_rules(rules, _ROLE_FOR_TITLE[title], prompt), context)

    # Custom tools per subagent are set explicitly so it's obvious who can do
    # what. Filesystem tools are always present (middleware) and gated by
    # interrupt_on / permissions, not by this list.
    return [
        {
            "name": "product-agent",
            "description": "Owns product thinking: features, user stories, business rules, acceptance criteria.",
            "system_prompt": role("Product Agent", (
                "Given a feature request, work through: why it's needed, who "
                "uses it, user stories, business rules, edge cases, acceptance "
                "criteria, and dependencies on other parts of the system. "
                "Write/update files under /pmagent/requirements/ via write_file. "
                "When asked to break a feature into tasks, use list_tasks to avoid "
                "duplicates, then propose them (title, description with acceptance "
                "criteria, priority, dependencies) in your reply. The PM creates them. "
                "Never write application code."
            )),
            "tools": list(read_task_tools),
        },
        {
            "name": "architecture-agent",
            "description": "Tracks system architecture and the ripple effects of proposed changes.",
            "system_prompt": role("Architecture Agent", (
                "Maintain files under /pmagent/architecture/. When asked about a "
                "proposed change, name every existing module/entity it touches. "
                "Never write application code."
            )),
            "tools": list(read_task_tools),
        },
        {
            "name": "research-agent",
            "description": "Runs external research (regulations, APIs, competitors, market changes).",
            "system_prompt": role("Research Agent", (
                "Investigate using web search. Clearly separate verified facts "
                "(with sources) from assumptions. Write findings under /pmagent/research/."
            )),
            "tools": [web_search] if web_search else [],
        },
        {
            "name": "reviewer-agent",
            "description": ("Reviews what has been built against stated requirements, including "
                            "tasks in 'review' status handed back by coding agents. Read-only."),
            "system_prompt": role("Reviewer Agent", (
                "Read /pmagent/requirements/ and /pmagent/architecture/ (and the "
                "actual repo, if you're given a way to see it) and produce a "
                "requirement-by-requirement status table (done / partial / "
                "missing) with what's missing and why. For a task in 'review', "
                "check the coding agent's final log note against the task's "
                "acceptance criteria and recommend: close, or send back with "
                "specific changes. You cannot write anything; report findings "
                "in your reply."
            )),
            "tools": list(read_task_tools),
            # Structurally read-only: every filesystem write is denied.
            "permissions": [FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
        },
        {
            "name": "documentation-agent",
            "description": "Keeps /pmagent/ organized; writes the decision log.",
            "system_prompt": role("Documentation Agent", (
                "Keep /pmagent/ tidy across project.md, requirements/, "
                "architecture/, decisions/, research/, progress/. When a "
                "decision is made, write a new /pmagent/decisions/ADR-NNN.md "
                "with: Decision, Reason, Date, Affected modules, Status. Never "
                "edit /pmagent/tasks/ files directly."
            )),
            "tools": list(read_task_tools),
        },
    ]


def _with_rules(rules: dict[str, str] | None, role: str, prompt: str) -> str:
    """Prepend the project's agent rules (base.md + the role's file) when given."""
    if not rules:
        return prompt
    parts = [rules.get("base", ""), rules.get(role, ""), prompt]
    return "\n\n".join(part.strip() for part in parts if part.strip())


_CONTEXT_GUIDE = """## Using the project context
The project context below is built fresh for this run: every document with a one-line
summary, the board, recent decisions, and what changed since this conversation's last
message. Start from it. Open only the files (or the sections of them) you need, and don't
re-read a file you already read in this conversation unless it has changed since. When you
delegate, give the specialist the paths and excerpts that matter, not just the question."""


def _with_context(prompt: str, context: str | None) -> str:
    """Append the run's project context pack after the fixed instructions (so the unchanging
    part of the prompt comes first, which is what prompt caching reuses)."""
    if not context:
        return prompt
    return f"{prompt}\n\n{_CONTEXT_GUIDE}\n\n{context.strip()}"


# Subagent name -> role name used by agent-rules/ and the folder permissions.
SUBAGENT_ROLES = {
    "product-agent": "product",
    "architecture-agent": "architecture",
    "research-agent": "research",
    "reviewer-agent": "reviewer",
    "documentation-agent": "documentation",
}
PM_ROLE = "project-manager"
_ROLE_FOR_TITLE = {
    "Product Agent": "product",
    "Architecture Agent": "architecture",
    "Research Agent": "research",
    "Reviewer Agent": "reviewer",
    "Documentation Agent": "documentation",
}


def role_for_agent_name(name: str | None) -> str:
    """The role behind a LangGraph agent name: a subagent's, else the Project Manager."""
    return SUBAGENT_ROLES.get(name or "", PM_ROLE)


_BOARD_SECTION = """
## The task board
Work is tracked as tasks. Use list_tasks / get_task to read the board, and
create_task / update_task / comment_task to change it. Never write or edit
files under /pmagent/tasks/ directly with write_file/edit_file; the task tools
keep the format valid and the log intact.

Coding is done by separate coding agents (assignees "claude-code" and
"codex") that pick up tasks from this board at the start of their sessions
and hand them back in status "review". So a task you create must stand on
its own: a coding agent reads only its description plus whatever files it
links to. Include what to build, where in the codebase, acceptance criteria,
and links to the relevant /pmagent/requirements/ and /pmagent/architecture/
files. Set depends_on so nothing is picked up before its prerequisites are
done, and set due dates when the user gives deadlines. Those dates drive the
project calendar.

When tasks are in "review", have reviewer-agent check them against their
acceptance criteria, then summarize its recommendation for the user. Closing
a task (status done) or sending it back (status todo, with a note) is an
Action Mode change like any other.
"""


def build_team(
    project_name: str,
    description: str,
    model: Any,
    backend: Any,
    *,
    checkpointer: object | None = None,
    task_tools: tuple[list, list] | None = None,
    web_search: dict | None = None,
    rules: dict[str, str] | None = None,
    board_instructions: str | None = None,
    subagent_task_tools: list | None = None,
    context: str | None = None,
):
    """The Project Manager plus five thinking subagents, over any storage backend.

    `backend` must serve the project's `.pmagent/` under `/pmagent/`. `model` is a
    "provider:model" string or a chat model instance. `rules` maps role names
    ("base", "project-manager", "product", ...) to agent-rules/ text. Without
    `task_tools`, the board section is left out of the PM's instructions;
    `board_instructions` replaces it (the platform's issue board differs from the
    CLI's task files). `subagent_task_tools` are extra board tools the specialists
    get (e.g. opening their own issue types); they're gated like every write. `context` is the
    run's project context pack (the platform builds it): the PM and every specialist get it.
    """
    read_task_tools, write_task_tools = task_tools or ([], [])
    if board_instructions is not None:
        board = board_instructions
    else:
        board = _BOARD_SECTION if task_tools else ""
    board_source = ", and the task board" if task_tools else ""
    briefing_sources = (
        "start from the project context below (the board, what changed, recent decisions, the "
        "documents and what each is about); read /pmagent/current-state.md, /pmagent/progress/, "
        "or a decision only where you need more detail than the context gives"
        if context
        else f"read /pmagent/progress/*.md, /pmagent/decisions/*.md,\n/pmagent/current-state.md{board_source}"
    )

    pm_instructions = f"""You are the Project Manager for {project_name}.

{description}

You coordinate five specialist subagents via the `task` tool (product-agent,
architecture-agent, research-agent, reviewer-agent, documentation-agent) and
keep /pmagent/ (project.md, requirements/, architecture/, decisions/,
research/, progress/, docs/) as the single source of truth. Ingested
reference docs live under /pmagent/docs/normalized/ as markdown regardless
of their original format. Check there before asking the user something that
may already be documented. You do not write application code, and neither
do your subagents.
{board}
## Chat Mode vs Action Mode
Default to CHAT MODE: read files, read the board, delegate to subagents for
analysis, research, and review, and discuss/plan freely. Never call
write_file or edit_file (or any board-changing tool) in this mode. Only enter
ACTION MODE when the user explicitly instructs a change (e.g. "create those
tasks", "update the PRD", "log that decision", "close it"). Make the change,
report exactly what changed, then return to Chat Mode. Every write pauses for
the user's approval regardless. That gate exists as a backstop, not as a
substitute for staying in Chat Mode.

## Concurrency
Other sessions, background jobs, or coding agents may be working on this
project right now. Before starting substantial work, check /pmagent/progress/
and what's in progress so you don't duplicate something in flight. When a
request splits into independent pieces, call the relevant subagents together
in the same turn rather than one at a time.

## Briefings
On "briefing" or "status": {briefing_sources}, then report phase, rough % progress,
today's priorities, what's in progress, recent decisions, open questions,
blockers, and documentation status. A briefing never writes.
"""

    interrupt_on = {
        "write_file": _APPROVAL,
        "edit_file": _APPROVAL,
        **{tool.__name__: _APPROVAL for tool in write_task_tools},
    }

    return create_deep_agent(
        model=model,
        tools=[*read_task_tools, *write_task_tools, *([web_search] if web_search else [])],
        system_prompt=_with_context(_with_rules(rules, PM_ROLE, pm_instructions), context),
        subagents=_subagents(
            project_name, [*read_task_tools, *(subagent_task_tools or [])], web_search, rules, context
        ),
        backend=backend,
        checkpointer=checkpointer,
        interrupt_on=interrupt_on,
    )


def build_agent(config: ProjectConfig, checkpointer: object | None = None):
    """The team for a local project: `.pmagent/` on disk, local task board (CLI)."""
    # LockingFilesystemBackend: several processes (chat, background jobs,
    # coding agents via the CLI) may touch /pmagent/ at once.
    backend = CompositeBackend(
        default=StateBackend(),
        routes={"/pmagent/": LockingFilesystemBackend(root_dir=config.pmagent_dir)},
    )
    return build_team(
        config.name,
        config.description,
        config.model,
        backend,
        checkpointer=checkpointer,
        task_tools=_task_tools(config),
        web_search=_web_search_tool(config.model),
    )
