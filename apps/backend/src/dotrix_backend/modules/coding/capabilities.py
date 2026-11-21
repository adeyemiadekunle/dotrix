"""Describe coding tool capabilities without granting any additional permission."""
from .models import CodingAgent, CodingLocation
from .tools import tool_for

# A local turn runs commands only inside a sandbox on that computer, which the platform can't see
# before the runner starts the turn: Docker Sandboxes (`sbx`), or Linux namespaces for fx and
# Claude Code. Without one, the runner refuses fx and the other tools only edit files. Codex brings
# its own workspace sandbox on every system.
LOCAL_TERMINAL = ("On your computer, only inside a sandbox there: Docker Sandboxes, or Linux namespaces "
                  "for fx and Claude Code. Without one, file edits only")
LOCAL_CODEX_TERMINAL = "In Codex's own workspace sandbox on your computer, with network access off"


def _terminal(run, planning: bool) -> tuple[bool, str | None]:
    if run.location is CodingLocation.LOCAL:
        if run.agent is CodingAgent.CODEX:
            return True, LOCAL_CODEX_TERMINAL
        return False, LOCAL_TERMINAL
    return True, "Read-only filesystem restrictions apply in Plan mode" if planning else None


def describe(run, settings) -> list[dict]:
    tool = tool_for(run.agent, run.model, settings)
    planning = run.work_mode == "plan"
    browser = not planning and run.location is CodingLocation.CLOUD and settings.coding_sandbox in {"docker", "docker-cloud", "openshell"} and tool.browser
    terminal, terminal_reason = _terminal(run, planning)
    return [
        {"id": "repository.read", "label": "Read repository", "available": True, "reason": None},
        {"id": "repository.write", "label": "Edit repository", "available": not planning,
         "reason": "Plan mode allows reads only" if planning else None},
        {"id": "terminal", "label": "Terminal", "available": terminal, "reason": terminal_reason},
        {"id": "browser", "label": "Browser", "available": browser,
         "reason": None if browser else "Not offered for this turn's mode or runtime"},
        {"id": "publication", "label": "Publish changes", "available": False,
         "reason": "Dotrix publishes through the approval flow; agents cannot publish directly"},
    ]


def skills(snapshot, capabilities):
    from dotrix_engine.skills import describe_skill

    allowed = {item["id"] for item in capabilities if item["available"]}
    return [{"name": name, "description": describe_skill(item["content"]), "sha256": item["sha256"],
             "resources": list(item.get("resources", {})), "missing_resources": item.get("missing_resources", []),
             "unavailable_tools": [tool for tool in item.get("requires", []) if tool not in allowed]}
            for name, item in (snapshot or {}).items()]


def instructions(capabilities, snapshot) -> str:
    lines = ["\n\n## Tool capabilities", "These describe this turn's tools; skills cannot expand them."]
    for item in capabilities:
        lines.append(f"- {item['label']}: {'available' if item['available'] else 'unavailable'}"
                     + (f" ({item['reason']})" if item.get("reason") else ""))
    for skill in skills(snapshot, capabilities):
        if skill["unavailable_tools"]:
            lines.append(f"- Skill {skill['name']} requires unavailable tools: {', '.join(skill['unavailable_tools'])}. "
                         "Report the gap instead of bypassing the tool boundary.")
        if skill["missing_resources"]:
            lines.append(f"- Skill {skill['name']} has missing resources: {', '.join(skill['missing_resources'])}.")
    return "\n".join(lines)
