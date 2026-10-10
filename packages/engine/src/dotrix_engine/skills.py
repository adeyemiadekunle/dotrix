"""Skills (agents v2 step 2): reusable procedures an agent loads when the work calls for one,
`SKILL.md`-style: a name (the file's), a one-line description, and the steps.

Every new project gets these in `agent-rules/skills/`; owners and admins edit them or add their
own there like any rule. A run's prompt lists each skill with its description only, so a skill
costs a line until an agent reads it.
"""
from __future__ import annotations

import re

SKILLS_FOLDER = "agent-rules/skills/"
_DESCRIPTION = re.compile(r"^description\s*:\s*(.+)$", re.IGNORECASE)

SKILLS: dict[str, str] = {
    "write-an-adr": """# Skill: write an ADR
Description: Record an architecture decision so it can be followed and later superseded.

## Steps
1. Search decisions/ for an ADR on the same question; if one exists, the new ADR supersedes it.
2. Read the requirements and the architecture it touches, and check `graph_impact` on them.
3. Follow /dotrix/agent-rules/templates/decisions.md: context, the decision, the options with
   their trade-offs, the consequences, "Affected modules", and "Supersedes" when it replaces one.
4. Name it decisions/ADR-NNN.md with the next number.
5. Propose tasks for the work it implies, linked to the ADR.
""",
    "triage-a-bug": """# Skill: triage a bug report
Description: Turn a report into a well-formed bug, or a comment on the issue it duplicates.

## Steps
1. Restate the report: what happened, what was expected, where, and since when.
2. Look for duplicates with search_knowledge and list_issues (open bugs first).
3. If one matches, propose a comment on it with what's new in this report; stop there.
4. Otherwise propose a bug: a title that names the symptom, steps to reproduce, expected and
   actual behaviour, priority by impact (who is blocked, how many), and links to the
   requirement or module it concerns.
""",
    "scope-a-failing-build": """# Skill: scope a failing build
Description: Work out what broke a build or a test run, and who should look at it.

## Steps
1. Read the failure: the first error, not the last; note the file, test, and message.
2. Find what changed: the commit or PR, and the files it touched (code_search, code_read).
3. Check `graph_impact` on the modules and requirements those files belong to.
4. Decide: a real regression, a flaky test (only with evidence it passed on the same commit),
   or the environment.
5. Report one finding with the cause, the evidence, the files, and a suggested fix.
""",
    "break-down-a-feature": """# Skill: break a feature into stories
Description: Turn a requirement into an epic and stories a coding agent can work from.

## Steps
1. Read the requirement in full and the decisions it links to.
2. Split by user-visible outcome, not by layer: each story delivers something someone can try.
3. Give each story acceptance criteria (testable, one behaviour each) and link the requirement.
4. Order them with depends_on; put open questions in the epic, not the stories.
5. Propose the epic and stories as one batch for approval.
""",
}


def default_skills() -> dict[str, str]:
    return {f"{SKILLS_FOLDER}{name}.md": text for name, text in SKILLS.items()}


def describe_skill(content: str) -> str:
    """A skill's one-line description: its "Description:" line, else its first sentence."""
    for line in content.splitlines():
        if (match := _DESCRIPTION.match(line.strip())) is not None:
            return match.group(1).strip()[:200]
    for line in content.splitlines():
        if line.strip() and not line.startswith("#"):
            return line.strip()[:200]
    return ""


def skill_name(path: str) -> str:
    return path.removeprefix(SKILLS_FOLDER).removesuffix(".md")


def skills_guide(skills: dict[str, str]) -> str:
    """The prompt's list of skills (name -> content): names and descriptions only. The
    project's and the workspace's together; a project's skill wins over the workspace's of the
    same name, so the caller merges them first."""
    if not skills:
        return ""
    lines = ["## Skills", "Before doing one of these, read it with read_skill(skill) and follow its steps:"]
    for name, content in sorted(skills.items()):
        lines.append(f"- {name}: {describe_skill(content)}")
    return "\n".join(lines)
