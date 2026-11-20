"""Code mode on real models (agents/scripts.py): the same question asked with run_script and without, on each chat
runtime, so what scripts save in model calls and tokens can be measured rather than assumed. Runs only when a
provider's key is given (DOTRIX_LIVE_ANTHROPIC_API_KEY, DOTRIX_LIVE_OPENAI_API_KEY, DOTRIX_LIVE_NVIDIA_API_KEY).

What a model does with the tool is its choice, so this asserts the answer and records the rest (`LIVE SCRIPTS …`
lines with `-s`): whether Nova scripted, its model calls, tokens and steps."""
import dataclasses
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime

import pytest

from apps.backend.tests.integration.test_live_chat import CASES, _live
from apps.backend.tests.integration.test_runtime_tools import (
    nova_pilot_world,  # noqa: F401  (a fixture)
)
from apps.backend.tests.script_benchmark import instrument
from dotrix_backend.modules.knowledge.models import KnowledgeFile

FACTS = {  # one fact a file, so the answer shows every file was read
    "research/costs.md": "Each turn costs about 4 cents.",
    "research/latency.md": "A reply takes about 900 milliseconds.",
    "decisions/0007-runtime.md": "We picked the queue-backed runtime.",
    "requirements/limits.md": "A workspace may run 3 turns at once.",
}
CHAINED = ("Search the project's knowledge for every document that mentions 'turn' or 'turns', read each one you find, "
           "and give me the one fact each states, a line per file.")
QUESTION = ("Read research/runtime.md, research/costs.md, research/latency.md, decisions/0007-runtime.md and "
            "requirements/limits.md in the project's knowledge, then give me the one fact each states, a line per file.")

# A reproducible corpus with 300 records and selective matches, split across pageable documents.
# Distractors exercise both predicates: refund alone and blocked alone must not match.
RECORDS = [
    {"id": f"CASE-{i:03d}", "topic": "refund" if i % 7 == 0 else "delivery",
     "status": "blocked" if i % 11 == 0 else "open",
     "notes": "Customer support evidence and routine investigation notes. " * 12}
    for i in range(1, 301)
]
MATCHES = tuple(row["id"] for row in RECORDS if row["topic"] == "refund" and row["status"] == "blocked")
LARGE_FILES = {
    f"research/support-{part}.md": "# Support records\n\n" + "\n".join(json.dumps(row) for row in RECORDS[start:start + 100])
    for part, start in enumerate(range(0, 300, 100), 1)
}
LARGE_FILES["research/support-index.md"] = "# Evidence index\n\n" + "\n".join(
    f"support-evidence: {path}" for path in LARGE_FILES
)
FILTER = ("Read all records in research/support-1.md, research/support-2.md and research/support-3.md. "
          "Return exactly the IDs whose topic equals refund AND status equals blocked, sorted, one ID per line. "
          "Do not include any other IDs. These are exact structured fields; inspect every record, paging as needed.")
DEPENDENT = ("Read research/support-index.md, then read every document it lists as support-evidence. "
             "Return exactly the IDs whose topic equals refund AND status equals blocked, sorted, one ID per line. "
             "Do not include any other IDs. Inspect every record, paging as needed.")


async def _add_files(sessions, run, contents=None) -> None:
    now = datetime.now(UTC)
    async with sessions() as session:
        for path, content in (contents or {path: f"# {path.rsplit('/', 1)[-1]}\n\n{fact}\n" for path, fact in FACTS.items()}).items():
            session.add(KnowledgeFile(workspace_id=run.workspace_id, project_id=run.project_id, path=path, version=1,
                                      revision=1, content=content, content_hash=hashlib.sha256(content.encode()).hexdigest(),
                                      size=len(content.encode()), created_at=now, updated_at=now))
        await session.commit()


@pytest.mark.parametrize(("question", "expected"), [
    pytest.param(QUESTION, ("4 cents", "900 milliseconds", "queue-backed", "3 turns", "private project evidence"), id="five-files"),
    pytest.param(CHAINED, ("4 cents", "3 turns"), id="search-then-read"),
])
@pytest.mark.parametrize(("runtime", "provider", "model"), CASES)
async def test_live_nova_reads_with_and_without_scripts(
    nova_pilot_world, db_client, agent_script, outbox, storage, checkouts, runtime, provider, model, question, expected,  # noqa: F811
):
    await _add_files(nova_pilot_world[1], nova_pilot_world[0])
    chat, fx = await _live(nova_pilot_world, db_client, outbox, storage, checkouts, agent_script, provider)
    settings = fx.runner.settings
    measured = {}
    try:
        for scripts in (True, False):
            fx.runner.settings = settings.model_copy(update={"agent_scripts": scripts})
            asked = await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
                "message": question, "chat_runtime": runtime, "work_mode": "discuss", "model": model,
            })
            assert asked.status_code == 202, asked.text
            run = asked.json()
            assert run["status"] == "completed", (scripts, run["status"], run.get("error"), run.get("reply"))
            reply = run["reply"].lower()
            missing = [f for f in expected if f not in reply.replace("four", "4").replace("three", "3")]
            events = (await fx.client.get(f"{fx.base}/runs/{run['id']}/events", headers=fx.headers)).json()["events"]
            steps = [e["data"].get("label") for e in events if e["kind"] == "activity"]
            tools = {t["tool"]: t["calls"] for t in (run.get("breakdown") or {}).get("tools", [])}
            measured[scripts] = {
                "scripted": "Working through the project in one step" in steps,
                "model_calls": run.get("model_calls"), "tools": tools,
                "input": run.get("input_tokens"), "output": run.get("output_tokens"),
                "cached": run.get("cached_input_tokens"), "complete": run.get("usage_complete"),
                "steps": len(steps), "missing": missing,
            }
            print(f"LIVE SCRIPTS {runtime}/{model} scripts={scripts}: {measured[scripts]}\n  steps={steps}\n  reply={run['reply']!r}")
            assert not missing, (scripts, missing, run["reply"])
    finally:
        fx.runner.settings = settings
        await chat.__aexit__(None, None, None)
    on, off = measured[True], measured[False]
    if on["input"] and off["input"]:
        print(f"LIVE SCRIPTS {runtime}/{model} input tokens with scripts {on['input']} vs without {off['input']} "
              f"({(on['input'] - off['input']) / off['input']:+.0%}); scripted={on['scripted']}")


@pytest.mark.skipif(os.environ.get("DOTRIX_LIVE_SCRIPT_BENCHMARK") != "1",
                    reason="Explicitly opt in with DOTRIX_LIVE_SCRIPT_BENCHMARK=1 (many live calls)")
@pytest.mark.parametrize(("workload", "question", "expected"), [
    pytest.param("tiny-control", QUESTION, (), id="tiny-control"),
    pytest.param("filter", FILTER, MATCHES, id="filter"),
    pytest.param("dependent", DEPENDENT, MATCHES, id="dependent"),
])
@pytest.mark.parametrize("strategy", ["natural", "requested"])
@pytest.mark.parametrize(("runtime", "provider", "model"), CASES)
async def test_live_script_benchmark(
    nova_pilot_world, db_client, agent_script, outbox, storage, checkouts, runtime, provider, model,  # noqa: F811
    workload, question, expected, strategy, monkeypatch, tmp_path,
):
    """Repeated fresh conversations, balanced order, exact selective answers and content-free telemetry.

    A requested trial instructs the enabled model to script, but never forces the tool at the
    provider level. Non-adoption is reported separately from answer correctness.
    """
    repeats = int(os.environ.get("DOTRIX_LIVE_SCRIPT_REPEATS", "2"))
    assert 2 <= repeats <= 10 and repeats % 2 == 0, "Use an even repeat count from 2 to 10 to balance order"
    contents = {path: f"# {path}\n\n{fact}\n" for path, fact in FACTS.items()} if workload == "tiny-control" else LARGE_FILES
    await _add_files(nova_pilot_world[1], nova_pilot_world[0], contents)
    chat, fx = await _live(nova_pilot_world, db_client, outbox, storage, checkouts, agent_script, provider)
    settings = fx.runner.settings
    trials = []
    report = tmp_path / "code-mode-benchmark.json"
    try:
        for repeat in range(repeats):
            for position, enabled in enumerate((True, False) if repeat % 2 == 0 else (False, True)):
                message = question
                if strategy == "requested":
                    message += (" Use run_script to gather and filter the evidence before returning it."
                                if enabled else " Use the ordinary read tools to gather the evidence.")
                fx.runner.settings = settings.model_copy(update={"agent_scripts": enabled})
                # No thread_id: every trial starts a new conversation, never reusing prior answers.
                with monkeypatch.context() as patch:
                    metrics = instrument(patch)
                    started = time.perf_counter()
                    asked = await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
                        "message": message, "chat_runtime": runtime, "work_mode": "discuss", "model": model,
                    })
                    elapsed = time.perf_counter() - started
                assert asked.status_code == 202, asked.status_code
                run = asked.json()
                reply = run.get("reply") or ""
                returned = tuple(re.findall(r"\bCASE-\d+\b", reply))
                if workload == "tiny-control":
                    normalized = reply.lower().replace("four", "4").replace("three", "3")
                    correct = all(fact in normalized for fact in (
                        "4 cents", "900 milliseconds", "queue-backed", "3 turns", "private project evidence",
                    ))
                else:
                    correct = returned == expected
                input_tokens, cached = run.get("input_tokens"), run.get("cached_input_tokens")
                trials.append({
                    "repeat": repeat, "position": position, "scripts_enabled": enabled,
                    "status": run["status"], "correct": correct, "seconds": elapsed,
                    "script_adopted": metrics.script_invocations > 0, **dataclasses.asdict(metrics),
                    "model_calls": run.get("model_calls"), "input_tokens": input_tokens,
                    "output_tokens": run.get("output_tokens"), "cached_input_tokens": cached,
                    "uncached_input_tokens": input_tokens - cached if input_tokens is not None and cached is not None else None,
                    "usage_complete": run.get("usage_complete"),
                })
    finally:
        fx.runner.settings = settings
        await chat.__aexit__(None, None, None)
        payload = {"schema_version": 1, "runtime": runtime, "model": model,
                   "workload": workload, "strategy": strategy, "trials": trials,
                   "corpus_sha256": hashlib.sha256(json.dumps(contents, sort_keys=True).encode()).hexdigest()}
        report.write_text(json.dumps(payload, indent=2) + "\n")
        print("CODE_MODE_BENCHMARK " + json.dumps(payload))
        print(f"Benchmark artifact: {report}")
    # Finish all pairs and retain failed answers' metrics before failing the quality check.
    assert all(trial["status"] == "completed" and trial["correct"] for trial in trials), report


AREAS = ["login", "search", "invoices", "the sidebar", "notifications", "exports", "the API docs", "onboarding",
         "billing emails", "the board", "file uploads", "dark mode", "the audit log", "webhooks", "settings"]
REFUNDS = ["Refund lands in the wrong zone", "Partial refund drops the tax line", "Refund email says 'charged'",
           "Refunds over 30 days are refused silently", "Refund button shows for free plans"]
BOARD_QUESTION = ("Which issues on the board are about refunds (in their title or description)? Give me only their keys "
                  "and titles, one per line.")


async def _fill_board(fx) -> list[str]:
    """150 issues with long descriptions, five of them about refunds: most of what a read returns is noise."""
    base = f"/v1/workspaces/{fx.existing.workspace_id}/projects/{fx.existing.project_id}/issues"
    filler = ("The behaviour differs between browsers and the steps below reproduce it most of the time. " * 6).strip()
    refund_keys = []
    for i in range(150):
        refund = i % 30 == 7
        title = REFUNDS[i // 30] if refund else f"Tidy up {AREAS[i % len(AREAS)]} ({i})"
        made = await fx.client.post(base, headers=fx.headers, json={
            "title": title, "type": "bug" if refund else "task",
            "description": f"{'Customers asking for their money back hit this.' if refund else 'Small cleanup.'} {filler}",
        })
        assert made.status_code == 201, made.text
        if refund:
            refund_keys.append(made.json()["key"])
    return refund_keys


COUNT_QUESTION = ("Count the issues on the board exactly: how many are bugs and how many are tasks? Answer as "
                  "'bugs: N, tasks: M'.")


@pytest.mark.parametrize("question", [pytest.param(BOARD_QUESTION, id="find"), pytest.param(COUNT_QUESTION, id="count"),
                                      pytest.param(COUNT_QUESTION + " Use run_script.", id="count-told")])
@pytest.mark.parametrize(("runtime", "provider", "model"), CASES)
async def test_live_nova_filters_a_large_board_with_and_without_scripts(
    nova_pilot_world, db_client, agent_script, outbox, storage, checkouts, runtime, provider, model, question,  # noqa: F811
):
    """The case code mode is for: a read whose result is mostly thrown away (150 issues, 5 wanted)."""
    chat, fx = await _live(nova_pilot_world, db_client, outbox, storage, checkouts, agent_script, provider)
    settings = fx.runner.settings
    try:
        wanted = await _fill_board(fx)
        measured = {}
        for scripts in (True, False):
            fx.runner.settings = settings.model_copy(update={"agent_scripts": scripts})
            run = (await fx.client.post(f"{fx.base}/runs", headers=fx.headers, json={
                "message": question, "chat_runtime": runtime, "work_mode": "discuss", "model": model,
            })).json()
            assert run["status"] == "completed", (scripts, run["status"], run.get("error"))
            events = (await fx.client.get(f"{fx.base}/runs/{run['id']}/events", headers=fx.headers)).json()["events"]
            steps = [e["data"].get("label") for e in events if e["kind"] == "activity"]
            tools = {t["tool"]: (t["calls"], t["result_tokens"]) for t in (run.get("breakdown") or {}).get("tools", [])}
            counted = "bugs: 5" in run["reply"].lower() and "tasks: 145" in run["reply"].lower()
            found = wanted if counted else [k for k in wanted if k in run["reply"]]
            measured[scripts] = {"scripted": "Working through the project in one step" in steps,
                                 "model_calls": run.get("model_calls"), "input": run.get("input_tokens"),
                                 "output": run.get("output_tokens"), "cached": run.get("cached_input_tokens"),
                                 "tools": tools, "found": f"{len(found)}/{len(wanted)}"}
            print(f"LIVE BOARD {runtime}/{model} scripts={scripts}: {measured[scripts]}\n  steps={steps}\n  reply={run['reply']!r}")
        assert all(m["found"] == f"{len(wanted)}/{len(wanted)}" for m in measured.values()), measured
    finally:
        fx.runner.settings = settings
        await chat.__aexit__(None, None, None)
