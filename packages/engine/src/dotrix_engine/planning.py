"""Validated, runtime-independent execution specifications for saved plans.

These specifications describe authorized scope; they do not authorize execution or publication.
Paths are literal repository-relative files or directories, never shell patterns.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PlannedCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1, max_length=2000)
    expected: str = Field(min_length=1, max_length=2000)


class ExecutionTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    task_number: int = Field(ge=1, le=40, description="The corresponding saved plan task, from 1")
    owned_paths: list[str] = Field(min_length=1, max_length=100)
    instructions: str = Field(min_length=1, max_length=12000)
    checks: list[PlannedCheck] = Field(min_length=1, max_length=20)
    stop_conditions: list[str] = Field(min_length=1, max_length=20)

    @field_validator("owned_paths")
    @classmethod
    def safe_paths(cls, paths: list[str]) -> list[str]:
        for path in paths:
            parts = path.rstrip("/").split("/")
            if (not path or path.startswith("/") or any(part in {"", ".", "..", ".git", ".dotrix"} for part in parts)
                    or any(char in path for char in "\\:*?[]\x00\r\n") or path != path.strip()):
                raise ValueError("Owned paths must be literal relative repository files or directories")
        if len(set(paths)) != len(paths):
            raise ValueError("Owned paths must be unique")
        return paths


def paths_overlap(left: str, right: str) -> bool:
    """Exact files and directory prefixes overlap; names sharing only a prefix do not."""
    a, b = PurePosixPath(left), PurePosixPath(right)
    return a == b or a in b.parents or b in a.parents


class ExecutionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    constraints: list[str] = Field(default_factory=list, max_length=30)
    exclusions: list[str] = Field(default_factory=list, max_length=30)
    tasks: list[ExecutionTask] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def unique_tasks(self):
        if len({task.key for task in self.tasks}) != len(self.tasks):
            raise ValueError("Execution task keys must be unique")
        if len({task.task_number for task in self.tasks}) != len(self.tasks):
            raise ValueError("Each saved plan task must have exactly one execution specification")
        return self

    def validate_plan(self, tasks: list, open_questions: list[str]) -> None:
        if open_questions:
            raise ValueError("Resolve open questions before saving an executable plan")
        if {task.task_number for task in self.tasks} != set(range(1, len(tasks) + 1)):
            raise ValueError("Execution specifications must cover every saved plan task")
        remaining = set(range(1, len(tasks) + 1))
        for task in tasks:
            if any(dep not in remaining for dep in task.depends_on):
                raise ValueError("Unknown plan dependency")
        while remaining:
            ready = {number for number in remaining if not remaining.intersection(tasks[number - 1].depends_on)}
            if not ready:
                raise ValueError("Task dependencies contain a cycle")
            remaining -= ready

    def ready_tasks(self, dependencies: dict[int, list[int]], completed: set[int], active: set[int],
                    *, limit: int = 2) -> list[int]:
        """Select dependency-ready, non-overlapping work; the host still admits each worker."""
        by_number = {task.task_number: task for task in self.tasks}
        known = set(by_number)
        if (set(dependencies) != known or not (completed | active) <= known or completed & active
                or any(not set(deps) <= known for deps in dependencies.values())):
            raise ValueError("Invalid execution scheduler state")
        selected: list[int] = []
        for number, task in sorted(by_number.items()):
            if len(active) + len(selected) >= max(0, min(limit, 2)):
                break
            if number in completed | active or not set(dependencies[number]) <= completed:
                continue
            occupied = [path for other in active | set(selected) for path in by_number[other].owned_paths]
            if any(paths_overlap(path, other) for path in task.owned_paths for other in occupied):
                continue
            selected.append(number)
        return selected
