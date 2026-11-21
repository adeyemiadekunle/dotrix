"""Kai's workers: the named helpers (fx agent profiles) Kai may start during a coding turn, alongside fx's own
`agent`, a copy of Kai. Dotrix defines them; the driver writes them for a new session and keeps them with it, so
a resumed session has the same workers, under the same profile digest as Kai's contract (`runner._profile`).

Each has a narrower tool list than Kai and none can start workers of its own or reach the web. A tool list is
what fx enforces; what a worker is asked to leave alone is only asked. `tester` keeps the shell, which can write
files, so it is told not to; its changes would still be part of the turn's diff, through the same guard and
approvals as Kai's own.
"""
from __future__ import annotations

READ = ["read_file", "glob_files", "grep_files", "read_tool_result"]

# Each worker's own limits on a turn (the Kai runtime's `max_steps` and `max_tokens`, every request's input and
# output together): a worker past one stops and reports, so a looping helper can't spend a person's key without
# end. Starting values, to tune from real usage.
READ_LIMITS = {"max_steps": 30, "max_tokens": 300_000}

WORKERS: tuple[dict, ...] = (
    {
        "name": "explorer",
        "description": "Reads and searches the repository and reports where things are and how they work; changes nothing.",
        "tools": READ,
        "mcp_servers": [],
        **READ_LIMITS,
        "prompt": "You are one of Kai's workers. Kai asked you a question about this repository. Find the answer by "
                  "reading and searching the code, then report it with the paths and lines it rests on. Say what "
                  "you couldn't find. Change nothing.",
    },
    {
        "name": "tester",
        "description": "Runs the project's tests, linters and builds and reports what passed and what failed, with the "
                       "output that matters; doesn't edit files.",
        "tools": ["shell", *READ],
        "max_steps": 50,
        "max_tokens": 500_000,
        "prompt": "You are one of Kai's workers. Run the checks Kai asked for (tests, linters, builds) the way this "
                  "project runs them, and report each command, whether it passed, and the output that explains any "
                  "failure. Don't edit, create or delete project files, don't install anything beyond what the "
                  "project's own setup does, and don't try to fix what fails: report it.",
    },
    {
        "name": "reviewer",
        "description": "Reviews a change Kai describes against the issue and the code around it and reports findings; "
                       "changes nothing.",
        "tools": READ,
        "mcp_servers": [],
        **READ_LIMITS,
        "prompt": "You are one of Kai's workers. Review the change Kai describes: read the files it touches and the "
                  "code that calls them, and check it against what the issue asks. Report each finding with its "
                  "path and line, how sure you are, and why it matters, most serious first. Say when you found "
                  "nothing. Change nothing.",
    },
)
