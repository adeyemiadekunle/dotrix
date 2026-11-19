"""A common, fail-closed read-only process boundary for coding Plan turns.

Linux Landlock restrictions are inherited by every descendant, including shell tools.
Only a fresh scratch directory is writable; the repository and the original HOME are not.
Unsupported hosts refuse the turn before starting the runtime.
"""
from __future__ import annotations

import json

# Sent as Python source through argv, not a file the agent can replace before enforcement.
READ_ONLY_EXEC = r'''
import ctypes, os, platform, sys, tempfile
if platform.machine() not in ("x86_64", "aarch64"):
    sys.exit("Read-only planning is unavailable on this host architecture")
libc = ctypes.CDLL(None, use_errno=True)
abi = libc.syscall(444, 0, 0, 1)
if abi < 3:
    sys.exit("Read-only planning requires Linux Landlock ABI 3 or newer")
class Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]
class PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]
# All filesystem mutation rights through ABI 3, including truncate and cross-directory rename.
writes = (1 << 1) | sum(1 << bit for bit in range(4, 15))
rules = Ruleset(writes)
fd = libc.syscall(444, ctypes.byref(rules), ctypes.sizeof(rules), 0)
if fd < 0:
    sys.exit("Read-only planning could not create its filesystem boundary")
scratch = tempfile.mkdtemp(prefix="dotrix-plan-")
for path, rights in ((scratch, writes), ("/dev/null", 1 << 1)):
    parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
    rule = PathRule(rights, parent)
    result = libc.syscall(445, fd, 1, ctypes.byref(rule), 0)
    os.close(parent)
    if result != 0:
        sys.exit("Read-only planning could not configure its filesystem boundary")
if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.syscall(446, fd, 0) != 0:
    sys.exit("Read-only planning could not enforce its filesystem boundary")
os.close(fd)
os.environ.update(HOME=scratch, TMPDIR=scratch, TMP=scratch, TEMP=scratch,
                  XDG_CONFIG_HOME=scratch + "/config", XDG_DATA_HOME=scratch + "/data",
                  XDG_CACHE_HOME=scratch + "/cache")
os.execvpe(sys.argv[1], sys.argv[1:], os.environ)
'''


def readonly_command(argv: list[str]) -> list[str]:
    return ["python3", "-c", READ_ONLY_EXEC, *argv]


def planning_brief(brief: str, repository: str, base_sha: str) -> str:
    from dotrix_backend.modules.agents.work_modes import SavePlan

    return ("You are Kai in strict Plan mode. Read the repository and prepare a plan only. "
            "Do not edit project files, install packages, publish, or delegate project changes. "
            "Only temporary private scratch files are writable. Return ONLY a JSON object matching "
            "the schema below, with no markdown fences. Keep unresolved questions explicit; omit "
            "execution metadata until they are resolved. Include the verified revision in execution metadata. "
            "Commands in checks are proposed verification, not evidence that they passed.\n"
            f"Repository: {repository}\nVerified revision: {base_sha}\n"
            f"Plan schema: {json.dumps(SavePlan.model_json_schema())}\n\nTask context:\n{brief}")


def parse_plan(summary: str | None) -> dict:
    from dotrix_backend.modules.agents.work_modes import SavePlan

    plan = SavePlan.model_validate_json(summary or "")
    if plan.execution:
        plan.execution.validate_plan(plan.tasks, plan.open_questions)
    else:
        remaining = set(range(1, len(plan.tasks) + 1))
        if any(dep not in remaining for task in plan.tasks for dep in task.depends_on):
            raise ValueError("Unknown plan dependency")
        while remaining:
            ready = {i for i in remaining if not remaining.intersection(plan.tasks[i - 1].depends_on)}
            if not ready:
                raise ValueError("Task dependencies contain a cycle")
            remaining -= ready
    return plan.model_dump(mode="json")
