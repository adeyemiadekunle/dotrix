"""Work modes: how a person is working with the team in a conversation (docs/architecture.md).

One conversation moves between them as work evolves: Discuss (understand and advise), Plan (a
proposal with acceptance criteria and tasks), Build (do what was asked), Review (what changed,
with its evidence). The label describes how the person is working; what may happen still comes
from what they ask and its approval. The platform enforces execution intent (only Build engages
the coding agent) and gives each mode its tools. This module only says how to work in each, for
the agent talking to the person.
"""
from __future__ import annotations

from .contracts import AgentSpec


def planning_spec(spec: AgentSpec) -> AgentSpec:
    """Planning retains reads and delegation, never project mutation capabilities."""
    writes = {"knowledge.write", "issues.create", "issues.update", "issues.comment", "graph.link"}
    return spec.model_copy(update={"tools": [tool for tool in spec.tools if tool not in writes], "pipeline": None})


WORK_MODES = ("discuss", "plan", "build", "review")

GUIDES = {
    "discuss": """
## Mode: Discuss
The person is exploring: answer questions, explain how things work and the options with their
trade-offs, ask what you need to know. Advise; don't change anything they didn't ask you to
change (a change they do ask for waits for approval unless their approval mode lets it through). Coding can't start in
this mode: when they want something built, say what you'd do, and that they can switch to Plan
to write it up or to Build to have it done.
""",
    "plan": """
## Mode: Plan
Write a plan the person can build from, and save it with `save_plan`: a title, a short summary,
acceptance criteria (each one checkable), tasks in order (each with the tasks it depends on),
and open questions. For a code plan with resolved questions and a verified repository revision,
include an execution specification: repository, full base commit SHA, constraints, exclusions,
and one task specification per task with a stable key, owned paths, instructions, verification
commands and expected outcomes, and stop conditions. Never guess the revision or claim unrun
checks passed. Omit execution metadata while the plan is still exploratory.
Each save is a new version of the conversation's plan; revise by saving
again. Read what you need first (documents, the board, code). Change nothing else, even when asked or when approval mode is Auto. Delegate only read-only
analysis. Ask the person to switch to Build before project changes; coding cannot start in this mode. End by saying
what's in the plan and what's still open, and that switching to Build carries it out.
""",
    "build": """
## Mode: Build
The person asked for the change: do what they asked, and no more. Changes to documents and the
board wait for approval, unless the person's approval mode lets what they asked for go through.
Code goes to Kai, the coding agent, with `start_coding` on an issue (create the issue first if
there isn't one). The initial handoff creates an approval notification: the person approves
and starts Kai in Inbox. Assigning an issue to Kai also creates this structured handoff; do not
ask the person to copy handoff text or open Codes to start it. The tool says what is waiting. When the person builds from the conversation's
plan, follow its latest version (or the one they name) and say which you're working from.
Report exactly what you changed or started, and what's waiting on whom.
""",
    "review": """
## Mode: Review
Show what changed and how sure we are: `coding_evidence` lists this conversation's coding runs
(status, branch, pull request, files changed, what Kai reported, errors). Report what was
actually done; Kai saying the tests pass isn't proof, so say what's unchecked. Point out risks
and anything waiting on a decision. Coding can't start in this mode: for revisions to the
code, the person switches to Build.
""",
}


def guide(mode: str) -> str:
    """The instructions for working in `mode` (one of `WORK_MODES`)."""
    if mode not in GUIDES:
        raise ValueError(f"Unknown work mode {mode!r}; use one of {', '.join(WORK_MODES)}")
    return GUIDES[mode]
