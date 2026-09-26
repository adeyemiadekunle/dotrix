"""Tasks: one file per task, Jira-shaped, under .pmagent/tasks/.

    .pmagent/tasks/TASK-1a2b3c4d.md

    ---
    id: TASK-1a2b3c4d
    title: Add postcode lookup to checkout
    status: todo            # todo | in_progress | blocked | review | done
    priority: high          # low | medium | high | urgent
    assignee: claude-code   # or codex, a human's name, or empty
    due: '2026-10-09'
    scheduled: null
    depends_on: [TASK-9f8e7d6c]
    labels: [checkout]
    created_at: ...
    updated_at: ...
    ---
    Description in markdown.

    ## Log
    - 2026-09-26T10:00:00+00:00 **pm-agent**: created

The files ARE the board: there's no database to keep in sync, and `git log
.pmagent/tasks/` is the task history.

Locking: every write takes the same per-file lock path that
LockingFilesystemBackend uses for `/tasks/<file>` (CompositeBackend strips the
`/pmagent/` route prefix before the routed backend sees the path). So a CLI
command, a background job, and a Claude Code session touching the same task
serialize instead of racing. Claiming takes an extra board-wide lock so two
coding agents running `pmagent next --claim` at once can't grab the same task.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import yaml
from filelock import FileLock

from .config import ProjectConfig

TASKS_DIRNAME = "tasks"
STATUSES = ("todo", "in_progress", "blocked", "review", "done")
PRIORITIES = ("low", "medium", "high", "urgent")
_PRIORITY_RANK = {p: i for i, p in enumerate(reversed(PRIORITIES))}  # urgent=0
EDITABLE_FIELDS = {
    "title", "status", "priority", "assignee", "due", "scheduled",
    "depends_on", "labels", "description",
}
LOG_HEADER = "## Log"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_str_date(value) -> Optional[str]:
    """Hand-edited frontmatter often has unquoted dates, which YAML parses into
    date objects. Normalize everything to ISO strings (or None)."""
    if value in (None, ""):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    s = str(value).strip()
    # Validate: accept YYYY-MM-DD or a full ISO datetime.
    try:
        (datetime.fromisoformat(s) if "T" in s else date.fromisoformat(s))
    except ValueError as e:
        raise ValueError(f"Bad date {s!r}: use YYYY-MM-DD or ISO datetime") from e
    return s


def _as_list(value) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in value]


@dataclass
class Task:
    id: str
    title: str
    status: str = "todo"
    priority: str = "medium"
    assignee: Optional[str] = None
    due: Optional[str] = None
    scheduled: Optional[str] = None
    depends_on: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    body: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, got {self.status!r}")
        if self.priority not in PRIORITIES:
            raise ValueError(f"priority must be one of {PRIORITIES}, got {self.priority!r}")
        self.due = _as_str_date(self.due)
        self.scheduled = _as_str_date(self.scheduled)
        self.depends_on = _as_list(self.depends_on)
        self.labels = _as_list(self.labels)
        self.assignee = self.assignee or None

    # -- description / log split -------------------------------------------
    @property
    def description(self) -> str:
        return self.body.split(LOG_HEADER, 1)[0].strip()

    @property
    def log(self) -> str:
        parts = self.body.split(LOG_HEADER, 1)
        return parts[1].strip() if len(parts) > 1 else ""

    def set_description(self, text: str) -> None:
        log = self.log
        self.body = f"{text.strip()}\n\n{LOG_HEADER}\n{log}\n" if log else f"{text.strip()}\n\n{LOG_HEADER}\n"

    def append_log(self, author: str, text: str) -> None:
        line = f"- {_now()} **{author}**: {text.strip()}"
        if LOG_HEADER not in self.body:
            self.body = f"{self.body.rstrip()}\n\n{LOG_HEADER}\n"
        self.body = f"{self.body.rstrip()}\n{line}\n"

    # -- (de)serialization --------------------------------------------------
    def to_markdown(self) -> str:
        meta = asdict(self)
        meta.pop("body")
        front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
        return f"---\n{front}---\n{self.body.lstrip()}"

    @classmethod
    def from_markdown(cls, text: str) -> "Task":
        if not text.startswith("---"):
            raise ValueError("Task file is missing YAML frontmatter")
        _, front, body = text.split("---", 2)
        meta = yaml.safe_load(front) or {}
        known = {f for f in cls.__dataclass_fields__} - {"body"}
        return cls(body=body.lstrip("\n"), **{k: v for k, v in meta.items() if k in known})

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("body")
        d["description"] = self.description
        d["log"] = self.log
        return d


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def _tasks_dir(config: ProjectConfig) -> Path:
    d = Path(config.pmagent_dir) / TASKS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def norm_id(task_id: str) -> str:
    """Canonical form is 'TASK-' + lowercase hex. Accepts any casing
    (humans type 'task-1A2B...') so ids, file names, deps, and lock paths
    always agree, even on case-sensitive filesystems."""
    s = str(task_id).strip()
    prefix, _, rest = s.partition("-")
    if prefix.upper() != "TASK" or not rest or not rest.isalnum():
        raise ValueError(f"Not a task id: {task_id!r}")
    return f"TASK-{rest.lower()}"


def _task_path(config: ProjectConfig, task_id: str) -> Path:
    return _tasks_dir(config) / f"{norm_id(task_id)}.md"


def _lock(config: ProjectConfig, rel: str) -> FileLock:
    # Must match LockingFilesystemBackend._lock_for("/tasks/<file>").
    p = Path(config.pmagent_dir) / ".locks" / (rel + ".lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(p), timeout=30)


def _task_lock(config: ProjectConfig, task_id: str) -> FileLock:
    return _lock(config, f"{TASKS_DIRNAME}/{norm_id(task_id)}.md")


def _atomic_write(path: Path, text: str) -> None:
    """Readers never see a half-written file (reads aren't locked)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def get_task(config: ProjectConfig, task_id: str) -> Task:
    path = _task_path(config, task_id)
    if not path.exists():
        raise FileNotFoundError(f"No such task: {task_id}")
    return Task.from_markdown(path.read_text())


def _save(config: ProjectConfig, task: Task) -> None:
    _atomic_write(_task_path(config, task.id), task.to_markdown())


def create_task(
    config: ProjectConfig,
    title: str,
    *,
    description: str = "",
    priority: str = "medium",
    assignee: Optional[str] = None,
    due: Optional[str] = None,
    scheduled: Optional[str] = None,
    depends_on: Iterable[str] | str | None = None,
    labels: Iterable[str] | str | None = None,
    author: str = "human",
) -> Task:
    task_id = f"TASK-{uuid.uuid4().hex[:8]}"
    task = Task(
        id=task_id, title=title.strip(), priority=priority, assignee=assignee,
        due=due, scheduled=scheduled,
        depends_on=[norm_id(d) for d in _as_list(depends_on)],
        labels=_as_list(labels),
    )
    missing = [d for d in task.depends_on if not _task_path(config, d).exists()]
    if missing:
        raise ValueError(f"depends_on references unknown task(s): {', '.join(missing)}")
    task.set_description(description)
    task.append_log(author, "created")
    with _task_lock(config, task_id):
        _save(config, task)
    return task


def update_task(
    config: ProjectConfig, task_id: str, *, author: str = "human",
    note: Optional[str] = None, **changes,
) -> Task:
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"Can't edit field(s): {', '.join(sorted(unknown))}")
    changes = {k: v for k, v in changes.items() if v is not None}

    with _task_lock(config, task_id):
        task = get_task(config, task_id)
        summary = []
        if "description" in changes:
            task.set_description(changes.pop("description"))
            summary.append("description updated")
        for k, v in changes.items():
            old = getattr(task, k)
            if k == "depends_on":
                v = [norm_id(d) for d in _as_list(v)]
            setattr(task, k, v)
            summary.append(f"{k}: {old!r} -> {v!r}")
        missing = [d for d in task.depends_on if not _task_path(config, d).exists()]
        if missing:
            raise ValueError(f"depends_on references unknown task(s): {', '.join(missing)}")
        if task.id in task.depends_on:
            raise ValueError("A task can't depend on itself")
        task.__post_init__()  # re-validate + normalize
        task.updated_at = _now()
        if summary:
            task.append_log(author, "; ".join(summary))
        if note:
            task.append_log(author, note)
        _save(config, task)
    return task


def comment_task(config: ProjectConfig, task_id: str, text: str, author: str = "human") -> Task:
    return update_task(config, task_id, author=author, note=text)


def list_tasks(
    config: ProjectConfig,
    *,
    status: Optional[str | Iterable[str]] = None,
    assignee: Optional[str] = None,
    label: Optional[str] = None,
    include_done: bool = True,
) -> list[Task]:
    statuses = {status} if isinstance(status, str) else set(status or [])
    out = []
    for p in sorted(_tasks_dir(config).glob("TASK-*.md")):
        try:
            t = Task.from_markdown(p.read_text())
        except Exception as e:  # a hand-mangled file shouldn't break the board
            print(f"warning: skipping {p.name}: {e}")
            continue
        if statuses and t.status not in statuses:
            continue
        if not include_done and t.status == "done":
            continue
        if assignee is not None and (t.assignee or "") != assignee:
            continue
        if label and label not in t.labels:
            continue
        out.append(t)
    return sort_tasks(out)


def sort_tasks(tasks: list[Task]) -> list[Task]:
    return sorted(
        tasks,
        key=lambda t: (_PRIORITY_RANK[t.priority], t.due or "9999-12-31", t.created_at),
    )


def _deps_satisfied(task: Task, by_id: dict[str, Task]) -> bool:
    # A dependency that no longer exists counts as unsatisfied — safer to
    # surface it as blocked than to start work on an assumption.
    return all(d in by_id and by_id[d].status == "done" for d in task.depends_on)


def ready_tasks(config: ProjectConfig, assignee: Optional[str] = None) -> list[Task]:
    """Tasks someone could start right now: status=todo, dependencies done,
    and either unassigned or assigned to `assignee`."""
    all_tasks = list_tasks(config)
    by_id = {t.id: t for t in all_tasks}
    return [
        t for t in all_tasks
        if t.status == "todo"
        and _deps_satisfied(t, by_id)
        and (t.assignee is None or t.assignee == assignee)
    ]


def next_task(
    config: ProjectConfig, assignee: str, *, claim: bool = False,
) -> Optional[Task]:
    """What should `assignee` work on next?

    Anything already in_progress for this assignee comes first — a coding
    agent that crashed mid-task picks it back up rather than starting
    something new. Otherwise the highest-priority ready task. With
    claim=True, the task is atomically assigned and moved to in_progress.
    """
    with _lock(config, f"{TASKS_DIRNAME}/.claim"):
        mine = list_tasks(config, status="in_progress", assignee=assignee)
        if mine:
            return mine[0]
        ready = ready_tasks(config, assignee)
        if not ready:
            return None
        task = ready[0]
        if claim:
            task = update_task(
                config, task.id, author=assignee,
                assignee=assignee, status="in_progress", note="claimed",
            )
        return task


def claim_task(config: ProjectConfig, task_id: str, assignee: str) -> Task:
    """Claim one specific task, the one the user told the agent to work on.

    Allowed if it's `todo` with every dependency done and it's unassigned or
    already assigned to `assignee`, or if `assignee` already has it
    in_progress (resuming). Uses the same board-wide lock as next_task so a
    specific claim and a next-claim can't grab the same task.
    """
    with _lock(config, f"{TASKS_DIRNAME}/.claim"):
        task = get_task(config, task_id)
        if task.status == "in_progress" and task.assignee == assignee:
            return task
        if task.status != "todo":
            raise ValueError(f"{task.id} is '{task.status}', not todo")
        if task.assignee not in (None, assignee):
            raise ValueError(f"{task.id} is assigned to {task.assignee}")
        by_id = {t.id: t for t in list_tasks(config)}
        pending = [d for d in task.depends_on if d not in by_id or by_id[d].status != "done"]
        if pending:
            raise ValueError(f"{task.id} is waiting on: {', '.join(pending)}")
        return update_task(config, task.id, author=assignee, assignee=assignee,
                           status="in_progress", note="claimed")


def complete_task(
    config: ProjectConfig, task_id: str, *, author: str = "human",
    note: Optional[str] = None, to_review: bool = False,
) -> Task:
    status = "review" if to_review else "done"
    return update_task(config, task_id, author=author, status=status, note=note)
