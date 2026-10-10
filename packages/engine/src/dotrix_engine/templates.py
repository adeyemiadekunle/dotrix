"""Document templates per folder (agents v2 step 2): the shape a new document in that folder
takes. They live in the project's `agent-rules/templates/`, so owners and admins edit them like
any rule; agents read the template before writing a new document there and never change it.
"""
from __future__ import annotations

TEMPLATES: dict[str, str] = {
    "requirements": """# Template: a requirements document

Use this shape for a new document in requirements/ (a module, a feature, a workstream).

# <Name>

## Why
The problem, who has it, and what changes for them when it's solved.

## Users
Who uses it, and what each of them needs from it.

## Stories
- As a <user>, I want <what>, so that <why>.

## Rules
Business rules and constraints, each one testable.

## Acceptance criteria
- Given <context>, when <action>, then <result>.

## Edge cases
What happens when things go wrong or are unusual.

## Dependencies
Other requirements, decisions (ADR-…), and issues (KEY-…) this relies on.

## Open questions
What's still undecided, and who decides it.
""",
    "decisions": """# Template: an architecture decision record (ADR)

Use this shape for a new decision in decisions/, named ADR-NNN.md with the next number.
A decision is never edited away: a changed decision is a new ADR that supersedes it.

# ADR-NNN: <Decision, in a few words>

- Date: YYYY-MM-DD
- Status: Proposed | Accepted | Superseded by ADR-…
- Affected modules: …
- Supersedes: ADR-… (if it replaces one)

## Context
What forces the decision: requirements, constraints, what's true today.

## Decision
What we decided, stated plainly.

## Options considered
Each option, with its trade-offs.

## Consequences
What becomes easier, what becomes harder, and what to watch.
""",
    "research": """# Template: a research note

Use this shape for a new document in research/, named YYYY-MM-DD-topic.md.

# <Question>

## Answer
The short answer, in two or three sentences.

## Findings
Each finding with the sources that support it ([S1], [S2], …).

## Assumptions
What isn't verified by a source, kept apart from the findings.

## Sources
- [S1] Title, publisher, date: address

## What it means for the project
Requirements, decisions, or issues it affects.
""",
    "design": """# Template: a design brief

Use this shape for a new document in design/.

# <Screen or flow>

## Goal
What the person using it is trying to do.

## Requirements
The requirements and acceptance criteria it covers (link them).

## Flow
The steps, screen by screen.

## Frames
Links to the design files and frames.

## Open questions
What's undecided, and who decides it.
""",
}

TEMPLATES_GUIDE = """
## Document templates
Before you write a new document in requirements/, decisions/, research/, or design/, read its
template at /dotrix/agent-rules/templates/<folder>.md and follow its shape. Templates are rules:
never change them.
"""


def default_templates() -> dict[str, str]:
    """`agent-rules/templates/<folder>.md` for each folder with a template."""
    return {f"agent-rules/templates/{folder}.md": text for folder, text in TEMPLATES.items()}
