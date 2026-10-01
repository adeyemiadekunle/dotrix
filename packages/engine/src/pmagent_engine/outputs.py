"""What an agent returns besides its reply (docs/agents-v2.md §4.6, §4.7).

An agent whose contract names an `output` ends its work by calling `submit_result` with items
of that schema, so the app can show each item with actions (create an issue from a finding,
dismiss it, ...). One that follows a pipeline (`pmagent_engine.pipelines`) reports its stages
with `stage`, so people see where it is. Both are plain tools; the platform decides where
results go (`sink`).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, ValidationError, create_model

from .pipelines import PIPELINES as _PIPELINES

Severity = Literal["low", "medium", "high", "critical"]


class Finding(BaseModel):
    severity: Severity
    title: str = Field(max_length=200)
    detail: str = Field(max_length=4000, description="What's wrong and why it matters")
    refs: list[str] = Field(default_factory=list, description="Paths, modules, or issue keys it concerns")
    suggested_fix: str = Field(default="", max_length=2000)


class PlanStep(BaseModel):
    step: str = Field(max_length=300)
    agent: str = Field(default="", max_length=31, description="Who does it (a handle), if not you")
    expected_output: str = Field(default="", max_length=500)


class SpecStory(BaseModel):
    title: str = Field(max_length=200)
    acceptance_criteria: list[str] = Field(default_factory=list)


class SpecItem(BaseModel):
    path: str = Field(max_length=300, description="The document, e.g. requirements/checkout.md")
    summary: str = Field(max_length=2000)
    stories: list[SpecStory] = Field(default_factory=list)


class Impact(BaseModel):
    ref: str = Field(max_length=300, description="What's affected: a requirement, ADR, module, or issue")
    why: str = Field(max_length=1000)
    severity: Severity = "medium"


class ReportFinding(BaseModel):
    claim: str = Field(max_length=1000)
    sources: list[str] = Field(default_factory=list, description="URLs or source ids")
    confidence: Literal["low", "medium", "high"] = "medium"
    affects: list[str] = Field(default_factory=list)


class DocUpdate(BaseModel):
    path: str = Field(max_length=300)
    reason: str = Field(max_length=1000)


class Brief(BaseModel):
    issue: str = Field(max_length=24, description="The issue key")
    acceptance_criteria: list[str] = Field(default_factory=list)
    excerpts: list[str] = Field(default_factory=list, description="Linked requirement and ADR excerpts")
    tests: list[str] = Field(default_factory=list, description="Tests to run")


SCHEMAS: dict[str, type[BaseModel]] = {
    "finding": Finding,
    "plan": PlanStep,
    "spec": SpecItem,
    "impact": Impact,
    "report": ReportFinding,
    "doc_update": DocUpdate,
    "brief": Brief,
}

# What each schema's items can become in the app (the platform implements the actions).
ACTIONS: dict[str, tuple[str, ...]] = {
    "finding": ("create_issue", "dismiss"),
    "plan": ("dismiss",),
    "spec": ("dismiss",),
    "impact": ("create_issue", "dismiss"),
    "report": ("create_issue", "dismiss"),
    "doc_update": ("dismiss",),
    "brief": ("dismiss",),
}

# Pipeline stage names by pipeline (`pmagent_engine.pipelines` holds the pipelines themselves).
PIPELINES: dict[str, tuple[str, ...]] = {name: p.stage_names for name, p in _PIPELINES.items()}

ResultSink = Callable[[str, list[dict[str, Any]]], None]
StageSink = Callable[[str, str], None]


def result_instructions(schema: str) -> str:
    fields = ", ".join(SCHEMAS[schema].model_fields)
    return (
        f"\n## Your result\nWhen your work is done, call `submit_result` once with every {schema} item "
        f"({fields}), in the same turn as your final answer if you can; skip it when the work produced "
        "none (a plain question). The app shows each item with actions, so keep items specific; your "
        "reply still explains them to the person."
    )


def result_tool(schema: str, sink: ResultSink) -> StructuredTool:
    """`submit_result(items)`: validated against the schema, then handed to `sink`."""
    item_model = SCHEMAS[schema]
    args = create_model(f"{schema.title().replace('_', '')}Result", items=(list[item_model], ...))

    def submit_result(items: list[Any]) -> str:
        try:
            parsed = [item_model.model_validate(i if isinstance(i, dict) else i.model_dump()) for i in items]
        except ValidationError as exc:
            return f"Error: {exc.errors()[0]['msg']}; fix the items and call again"
        sink(schema, [p.model_dump() for p in parsed])
        return f"Recorded {len(parsed)} {schema} item(s)."

    return StructuredTool.from_function(
        submit_result,
        name="submit_result",
        description=f"Record your result: a list of {schema} items the app shows with actions.",
        args_schema=args,
    )


def stage_tool(pipeline: str, sink: StageSink) -> StructuredTool:
    """`stage(name)`: report the pipeline stage you're starting."""
    stages = PIPELINES[pipeline]
    args = create_model("Stage", current=(Literal[stages], Field(description="One of: " + ", ".join(stages))))  # type: ignore[valid-type]

    def stage(current: str) -> str:
        if current not in stages:
            return f"Error: unknown stage; use one of {', '.join(stages)}"
        sink(pipeline, current)
        return "ok"

    return StructuredTool.from_function(stage, name="stage", description="Say which stage you're starting.", args_schema=args)
