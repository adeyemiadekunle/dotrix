"""Kai's helpers in each coding engine's terms: one definition, the same workers everywhere."""
import json

from dotrix_engine.coding_helpers import (
    AT_ONCE,
    HELPERS_RULE,
    READ,
    RUNNER_AT_ONCE,
    WORKERS,
    claude_agents,
    codex_settings,
    helper_share,
    opencode_agents,
    workers,
)


def test_a_turn_that_runs_no_commands_gets_only_the_workers_that_read() -> None:
    assert [w["name"] for w in workers()] == ["explorer", "tester", "reviewer"]
    assert [w["name"] for w in workers(commands=False)] == ["explorer", "reviewer"]
    assert all(set(w["tools"]) <= set(READ) for w in workers(commands=False))


def test_claude_code_gets_each_worker_with_its_own_tools_and_step_limit() -> None:
    agents = json.loads(claude_agents(list(WORKERS)))
    assert agents["explorer"] == {"description": WORKERS[0]["description"], "prompt": WORKERS[0]["prompt"],
                                  "tools": ["Read", "Glob", "Grep"], "maxTurns": 30}
    assert agents["tester"]["tools"] == ["Bash", "Read", "Glob", "Grep"] and agents["tester"]["maxTurns"] == 50


def test_an_opencode_worker_may_use_only_its_own_tools_and_never_what_the_turn_denies() -> None:
    agents = opencode_agents(workers(commands=False), denied=("bash", "webfetch"))
    assert set(agents) == {"explorer", "reviewer"} and agents["explorer"]["mode"] == "subagent"
    rules = agents["explorer"]["permissions"]
    assert rules[0] == {"action": "*", "resource": "*", "effect": "deny"}  # the last matching rule wins
    assert [r["action"] for r in rules if r["effect"] == "allow"] == ["read", "glob", "grep"]
    assert rules[-4:] == [{"action": tool, "resource": "*", "effect": "deny"} for tool in ("subagent", "skill", "bash", "webfetch")]
    # A turn that denies a tool a worker would have keeps it denied.
    tester = opencode_agents([WORKERS[1]], denied=("shell",))["tester"]["permissions"]
    assert "shell" not in [r["action"] for r in tester if r["effect"] == "allow"]


def test_codex_s_helpers_are_capped_and_start_none_of_their_own() -> None:
    assert codex_settings() == ["-c", "agents.max_threads=3", "-c", "agents.max_depth=1"]
    assert codex_settings(1) == ["-c", "agents.max_threads=1", "-c", "agents.max_depth=1"]


def test_a_turn_gets_what_is_left_of_its_runner_s_helpers_and_never_none() -> None:
    """Three helpers for a turn alone, at most six across a runner's turns (one kept for each that may still start),
    and one at least: only a runner coding more than six turns at once goes past six."""
    assert (AT_ONCE, RUNNER_AT_ONCE) == (3, 6)

    def shares(parallel: int) -> list[int]:
        taken, out = 0, []
        for started in range(parallel):
            out.append(helper_share(taken, parallel - started - 1))
            taken += out[-1]
        return out

    assert [shares(n) for n in (1, 2, 3, 4)] == [[3], [3, 3], [3, 2, 1], [3, 1, 1, 1]]
    assert all(sum(shares(n)) <= RUNNER_AT_ONCE for n in range(1, 7)) and shares(8) == [1] * 8
    assert "At most three at a time" in HELPERS_RULE and "at most one of them running" in HELPERS_RULE
