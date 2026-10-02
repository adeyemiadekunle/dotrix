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
from .builtins import BUILTIN_HANDLES, SPECIALISTS, builtin_specs
from .catalog import group as catalog_group
from .catalog import tool_id, tool_name
from .code import CODE_GUIDE
from .config import ProjectConfig
from .context_middleware import CompactTools, UnchangedReads, summarization
from .contracts import PM_HANDLE, AgentSpec
from .outputs import ResultSink, StageSink, result_instructions, result_tool, stage_tool
from .pipelines import MODES, PIPELINES, checkpoint_tool
from .pipelines import instructions as pipeline_instructions
from .web import WEB_GUIDE

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
        f"Pass our own search (`pmagent_engine.web`, Tavily) as `web_tools` instead."
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


def _with_rules(rules: dict[str, str] | None, role: str, prompt: str) -> str:
    """Prepend the project's agent rules (base.md + the role's file) when given."""
    if not rules:
        return prompt
    parts = [rules.get("base", ""), rules.get(role, ""), prompt]
    return "\n\n".join(part.strip() for part in parts if part.strip())


# Delegation that doesn't start from zero: a specialist starts with the project context but
# not this conversation, so the brief carries what it needs, and it answers with findings.
_DELEGATION_GUIDE = """## Delegating
A specialist sees the project context, but not this conversation. When the person asks for
a specialist, or the work needs one, delegate straight away: don't research first, since the
specialist reads and searches for itself. Write each `task` as a short brief: the question,
what the person asked for, anything from this conversation it needs (quote what you've
already read rather than making it read it again), the paths, sections, or issue keys to start
from, and what to return. Ask several at once when their parts are independent.
"""

_FINDINGS_GUIDE = """
Work in few steps: every step re-sends everything so far. Decide what you need from the
brief and the project context, then ask for all of it in one turn (several read_file,
read_section, get_issue, or search calls at once), and answer as soon as you can; an empty
document needs no second look.

Your reply goes back to the Project Manager, not to a person. Answer with findings: a short
answer first, then the key points, each with the path and section it comes from, and any
changes you propose. Don't paste whole documents back; quote only the lines that matter."""

# A specialist picked in the chat leads the run: it talks to the person, and may ask the
# other specialists (one level: the ones it calls can't call anyone).
_LEAD_GUIDE = """
## You're in the project's chat
You're talking with a person in the project's chat; they picked you for this. Answer them
directly, in your role.

Default to CHAT MODE: read, search, analyse, and discuss; don't call write_file, edit_file,
or any board-changing tool. Only when the person explicitly asks for a change (e.g. "write
that up", "create those stories") make it, say exactly what changed, and return to Chat Mode.
Every change waits for a person's approval anyway.

When part of the work needs another specialist's expertise, ask them with the `task` tool:
a short brief (the question, what the person asked for, what you already know, where to
start, what to return). They can't ask anyone else. For work that needs the whole team
(planning across roles, editing or closing issues), suggest the person picks Auto.

Work in few steps: every step re-sends everything so far. Ask for all the files, sections,
and issues you need in one turn, and answer as soon as you can.
"""

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


# Subagent name -> role name used by agent-rules/ and the folder permissions (the built-ins).
SUBAGENT_ROLES = {f"{role}-agent": role for role in SPECIALISTS}
PM_ROLE = PM_HANDLE
# Who can lead a chat among the built-ins: Auto (the Project Manager) or one specialist.
LEADS = BUILTIN_HANDLES


def role_for_agent_name(name: str | None) -> str:
    """The handle behind a LangGraph agent name ("<handle>-agent"), else the Project Manager
    (the main agent, and deepagents' own general-purpose helper)."""
    if name and name.endswith("-agent") and name != "-agent":
        return name[: -len("-agent")]
    return PM_ROLE


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


_BRIEFING_INSTRUCTIONS = """You are the Project Manager for {project_name}.

{description}

Write the daily briefing for the person who asked, from the project context below. It was
built for this briefing from the board, the documents, recent decisions, and what changed
since the last briefing. You have no tools in this step, and nothing you write changes the
project. Cover phase and health (with rough % progress), what changed, today's priorities,
recent decisions, open questions, blockers, and documentation status (flag documents that
look out of date). Be concise and specific: name issue keys and documents. If something the
briefing should cover isn't in the context, say what's missing rather than guessing."""


def briefing_system_prompt(
    project_name: str, description: str, *, rules: dict[str, str] | None = None, context: str | None = None
) -> str:
    """The Project Manager's prompt for a briefing written in one model call, with no tools:
    the platform has already worked out what happened (the context pack), so the model only
    narrates it. Much cheaper than letting the PM explore the project to find out."""
    prompt = _with_rules(
        rules, PM_ROLE, _BRIEFING_INSTRUCTIONS.format(project_name=project_name, description=description)
    )
    return f"{prompt}\n\n{context.strip()}" if context else prompt


_WRITE_TOOL_GROUPS = ("issues.create", "issues.update", "issues.comment")
_DENY_FILE_WRITES = [FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")]


def _toolbox(tools: list[Any]) -> dict[str, list[Any]]:
    """Supplied tools by catalogue id (first of each name wins)."""
    box: dict[str, list[Any]] = {}
    seen: set[str] = set()
    for tool in tools:
        name, group_id = tool_name(tool), tool_id(tool)
        if group_id is None or name in seen:
            continue
        seen.add(name)
        box.setdefault(group_id, []).append(tool)
    return box


def _tools_for(spec: AgentSpec, box: dict[str, list[Any]]) -> list[Any]:
    """The supplied tools its contract lists, minus the ones whose actions are blocked."""
    return [tool for group_id in spec.tools if spec.can(group_id) for tool in box.get(group_id, [])]


def _gate(spec: AgentSpec, box: dict[str, list[Any]]) -> dict[str, Any]:
    """What pauses for approval when this agent acts: its file writes and board changes, except
    the low-risk actions an owner allowed it to take without asking."""
    gated: dict[str, Any] = {}
    if spec.can("knowledge.write"):
        gated |= {"write_file": _APPROVAL, "edit_file": _APPROVAL}
    for group_id in _WRITE_TOOL_GROUPS:
        if spec.can(group_id) and not all(spec.allowed(a) for a in catalog_group(group_id).actions):
            gated |= {tool_name(tool): _APPROVAL for tool in box.get(group_id, [])}
    return gated


def _permissions(spec: AgentSpec) -> list[FilesystemPermission]:
    """Structurally read-only unless it may write documents (the Reviewer's way)."""
    return [] if spec.can("knowledge.write") else list(_DENY_FILE_WRITES)


def _callable(caller: AgentSpec, specs: list[AgentSpec]) -> list[AgentSpec]:
    """The agents `caller` may hand work to: its `can_call` (["*"]: everyone), never the
    Project Manager and never itself; nobody without the delegate tool."""
    if not caller.has("delegate"):
        return []
    wanted = set(caller.can_call)
    return [
        spec for spec in specs
        if spec.handle not in (caller.handle, PM_HANDLE) and ("*" in wanted or spec.handle in wanted)
    ]


def build_team(
    project_name: str,
    description: str,
    model: Any,
    backend: Any,
    *,
    checkpointer: object | None = None,
    task_tools: tuple[list, list] | None = None,
    web_search: dict | None = None,
    web_tools: list | None = None,
    rules: dict[str, str] | None = None,
    board_instructions: str | None = None,
    subagent_task_tools: list | None = None,
    context: str | None = None,
    knowledge_tools: list | None = None,
    code_tools: list | None = None,
    specialist_model: Any = None,
    summarize_after_tokens: int | None = None,
    lead: str | None = None,
    agents: list[AgentSpec] | None = None,
    models: Any = None,
    result_sink: ResultSink | None = None,
    stage_sink: StageSink | None = None,
    mode: str | None = None,
):
    """The Project Manager plus the specialists, over any storage backend.

    The team comes from `agents` (contracts, `pmagent_engine.contracts`); without them, the
    six built-ins. Each agent gets the supplied tools its contract lists, pauses for approval
    on its own writes, and is structurally read-only without `knowledge.write`.

    `backend` must serve the project's `.pmagent/` under `/pmagent/`. `model` is a
    "provider:model" string or a chat model instance. `rules` maps handles ("base",
    "project-manager", "product", ...) to agent-rules/ text. Without `task_tools`, the board
    section is left out of the PM's instructions; `board_instructions` replaces it (the
    platform's issue board differs from the CLI's task files). The PM's tools come from
    `task_tools` (read, write); the specialists' board changes come from `subagent_task_tools`
    (the platform passes them all and checks each agent's contract on every change; the CLI
    passes none, so its specialists only read the board). `context` is the run's project
    context pack: the PM and every specialist get it. `knowledge_tools` are extra read-only
    tools (outline, sections, search). `code_tools` read the project's checked-out repository
    (`pmagent_engine.code`), given to agents granted `code.read`. `web_tools` are our web tools (`pmagent_engine.web`:
    `web_search`, `fetch_page`), given to agents granted `web.search` with how to cite what they
    find; our `web_search` replaces `web_search` (the model's built-in search) when both are
    given. `specialist_model` runs the specialists and summaries
    (a cheaper model); a contract's own `model` is turned into a chat model by `models(name)`
    when given. `summarize_after_tokens` sets when a long conversation's older turns are
    summarised. `lead` picks who talks to the person: None or "project-manager" for the PM
    (Auto), or another agent's handle, who then leads with its own prompt, tools, and folder
    permissions and may call the agents its contract lists (one level deep).

    An agent whose contract names a `pipeline` reports its stages to `stage_sink`; the agent
    talking to the person, when its contract names an `output`, records its result items with
    `result_sink` (`pmagent_engine.outputs`). Without the sinks, neither tool is given. `mode`
    is a pipeline from `pipelines.MODES` the leading agent follows for this run instead of its
    own (with that pipeline's output). The agent talking to the person gets `checkpoint` when
    its pipeline has a checkpoint stage: it pauses like a write, for the person to continue,
    change the plan, or stop.
    """
    if mode is not None and mode not in MODES:
        raise ValueError(f"Unknown mode {mode!r}; use one of {', '.join(MODES)}")
    specs = list(agents) if agents else builtin_specs()
    if not any(spec.handle == PM_HANDLE for spec in specs):
        specs = [builtin_specs()[0], *specs]
    by_handle = {spec.handle: spec for spec in specs}
    if lead not in (None, *by_handle):
        raise ValueError(f"Unknown lead agent {lead!r}; use one of {', '.join(by_handle)}")
    lead = None if lead == PM_HANDLE else lead
    pm = by_handle[PM_HANDLE]

    read_task_tools, write_task_tools = task_tools or ([], [])
    # Our web tools come first, so our `web_search` wins over the model's built-in one (a
    # provider-native dict) when both are given; without our search, the built-in one stays.
    web = [*(web_tools or []), *([web_search] if web_search else [])]
    reading = [*(knowledge_tools or []), *(code_tools or [])]
    pm_box = _toolbox([*read_task_tools, *write_task_tools, *reading, *web])
    specialist_box = _toolbox([*read_task_tools, *(subagent_task_tools or []), *reading, *web])

    def guides(spec: AgentSpec) -> str:
        """How to use the code and web tools it was given."""
        text = CODE_GUIDE if code_tools and spec.can("code.read") else ""
        return text + (WEB_GUIDE if web_tools and spec.can("web.search") else "")

    if board_instructions is not None:
        board = board_instructions
    else:
        board = _BOARD_SECTION if task_tools else ""
    board_source = ", and the task board" if task_tools else ""
    briefing_sources = (
        "write it from the project context below (the board, what changed since the last "
        "briefing, recent decisions, the documents and what each is about), without asking the "
        "specialists; open a file only where something needs more explanation than the context gives"
        if context
        else f"read /pmagent/progress/*.md, /pmagent/decisions/*.md,\n/pmagent/current-state.md{board_source}"
    )

    team = _callable(pm, specs)
    names = ", ".join(spec.agent_name for spec in team) or "none yet"
    pm_instructions = f"""You are the {pm.name} for {project_name}.

{description}

You coordinate the specialist subagents via the `task` tool ({names}).
{pm.instructions}
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

{_DELEGATION_GUIDE}
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

    summary_model = specialist_model or model

    def middleware() -> list[Any]:
        """Fresh instances for each agent: files already read, and when to summarise."""
        extra: list[Any] = [CompactTools(), UnchangedReads()]
        if summarize_after_tokens:
            extra.append(summarization(summary_model, backend, summarize_after_tokens))
        return extra

    speaker = lead or PM_HANDLE

    def plan_of(spec: AgentSpec) -> tuple[str | None, str | None]:
        """(pipeline, output) for this run: the run's mode for the speaker, else its contract's."""
        if mode is not None and spec.handle == speaker:
            return mode, PIPELINES[mode].output
        return spec.pipeline, spec.output

    def steers(spec: AgentSpec) -> bool:
        pipeline = plan_of(spec)[0]
        return spec.handle == speaker and pipeline is not None and PIPELINES[pipeline].steers

    def extras(spec: AgentSpec) -> tuple[list[Any], str]:
        """The stage, checkpoint, and result tools it gets, and how to use them."""
        tools: list[Any] = []
        text = ""
        pipeline, output = plan_of(spec)
        if pipeline and stage_sink is not None:
            tools.append(stage_tool(pipeline, lambda pipeline, name, h=spec.handle: stage_sink(h, name)))
            if steers(spec):
                tools.append(checkpoint_tool())
            text += pipeline_instructions(pipeline, can_steer=steers(spec))
        if output and result_sink is not None and spec.handle == speaker:
            tools.append(result_tool(output, result_sink))
            text += result_instructions(output)
        return tools, text

    def gate(spec: AgentSpec, box: dict[str, list[Any]]) -> dict[str, Any]:
        gated = _gate(spec, box)
        if steers(spec) and stage_sink is not None:
            gated["checkpoint"] = _APPROVAL
        return gated

    def prompt(spec: AgentSpec) -> str:
        if spec.handle == lead:
            text = f"You are the {spec.name} for {project_name}.\n{spec.instructions}\n{board}\n{_LEAD_GUIDE}"
        else:
            text = f"You are the {spec.name} for {project_name}.\n{spec.instructions}\n{_FINDINGS_GUIDE}"
        text += extras(spec)[1] + guides(spec)
        return _with_context(_with_rules(rules, spec.handle, text), context)

    def subagent(spec: AgentSpec) -> dict:
        entry: dict[str, Any] = {
            "name": spec.agent_name,
            "description": spec.description or spec.name,
            "system_prompt": prompt(spec),
            "tools": [*_tools_for(spec, specialist_box), *extras(spec)[0]],
            "interrupt_on": _gate(spec, specialist_box),
            "permissions": _permissions(spec),
            "middleware": middleware(),
        }
        if spec.model and models is not None:
            entry["model"] = models(spec.model)
        elif specialist_model is not None:
            entry["model"] = specialist_model
        return entry

    if lead is not None:
        # The picked agent is the main agent; the ones it may call are its subagents.
        leader = by_handle[lead]
        return create_deep_agent(
            model=model,
            tools=[*_tools_for(leader, specialist_box), *extras(leader)[0]],
            system_prompt=prompt(leader),
            subagents=[subagent(spec) for spec in _callable(leader, specs)],
            middleware=middleware(),
            permissions=_permissions(leader),
            backend=backend,
            checkpointer=checkpointer,
            interrupt_on=gate(leader, specialist_box),
            name=leader.agent_name,
        )

    return create_deep_agent(
        model=model,
        tools=[*_tools_for(pm, pm_box), *extras(pm)[0]],
        system_prompt=_with_context(_with_rules(rules, PM_HANDLE, pm_instructions + extras(pm)[1] + guides(pm)), context),
        subagents=[subagent(spec) for spec in team],
        middleware=middleware(),
        permissions=_permissions(pm),
        backend=backend,
        checkpointer=checkpointer,
        interrupt_on=gate(pm, pm_box),
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
