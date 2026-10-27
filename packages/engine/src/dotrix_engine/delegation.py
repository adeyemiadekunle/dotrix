"""UI-independent briefs and results for durable specialist work."""
from typing import Literal

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field, model_validator

Specialist = Literal["product", "architecture", "research", "reviewer", "documentation"]


class SpecialistTask(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    agent: Specialist
    brief: str = Field(min_length=1, max_length=12_000)
    expected_result: str = Field(min_length=1, max_length=2000)
    depends_on: list[str] = Field(default_factory=list, max_length=12)
    changes_project: bool = Field(default=False, description="Whether this task needs approved project changes")


class SpecialistBatch(BaseModel):
    tasks: list[SpecialistTask] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def dependency_graph(self):
        by_key = {task.key: task for task in self.tasks}
        if len(by_key) != len(self.tasks):
            raise ValueError("Task keys must be unique")
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(key: str):
            if key not in by_key:
                raise ValueError(f"Unknown dependency {key}")
            if key in visiting:
                raise ValueError("Task dependencies contain a cycle")
            if key in visited:
                return
            visiting.add(key)
            for dependency in by_key[key].depends_on:
                visit(dependency)
            visiting.remove(key)
            visited.add(key)

        for key in by_key:
            visit(key)
        return self


class SpecialistResult(BaseModel):
    summary: str = Field(min_length=1, max_length=12_000)
    status: Literal["completed", "partial", "blocked"] = "completed"
    findings: list[str] = Field(default_factory=list, max_length=60)
    evidence: list[str] = Field(default_factory=list, max_length=60)
    artifacts: list[str] = Field(default_factory=list, max_length=30)
    risks: list[str] = Field(default_factory=list, max_length=30)


class DelegationBoundary(AgentMiddleware):
    """Hide inline dispatch on the platform and refuse implicit/general-purpose agents."""

    def __init__(self, allowed: set[str] | None = None):
        self.allowed = allowed or set()

    def wrap_model_call(self, request, handler):
        if not self.allowed:
            request = request.override(tools=[t for t in request.tools if getattr(t, "name", None) != "task"])
        return handler(request)

    async def awrap_model_call(self, request, handler):
        if not self.allowed:
            request = request.override(tools=[t for t in request.tools if getattr(t, "name", None) != "task"])
        return await handler(request)

    def _denied(self, request):
        call = request.tool_call
        if call["name"] == "task" and call.get("args", {}).get("subagent_type") not in self.allowed:
            return ToolMessage(content="Inline delegation is unavailable. Use delegate_tasks for built-in specialists.",
                               tool_call_id=call["id"], status="error")
        return None

    def wrap_tool_call(self, request, handler):
        return self._denied(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._denied(request) or await handler(request)
