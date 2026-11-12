"""Describe coding tool capabilities without granting any additional permission."""
from .models import CodingLocation
from .tools import tool_for


def describe(run, settings) -> list[dict]:
    tool = tool_for(run.agent, run.model, settings)
    planning = run.work_mode == "plan"
    browser = not planning and run.location is CodingLocation.CLOUD and settings.coding_sandbox in {"docker", "docker-cloud", "openshell"} and tool.browser
    return [
        {"id": "repository.read", "label": "Read repository", "available": True, "reason": None},
        {"id": "repository.write", "label": "Edit repository", "available": not planning,
         "reason": "Plan mode allows reads only" if planning else None},
        {"id": "terminal", "label": "Terminal", "available": True,
         "reason": "Read-only filesystem restrictions apply in Plan mode" if planning else None},
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
