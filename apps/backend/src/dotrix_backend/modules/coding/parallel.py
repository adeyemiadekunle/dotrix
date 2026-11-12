"""Isolated task execution with persisted results and serial integration.

The parent coding lease fences every task update. Workers have no publication capability;
only the parent hands the final combined patch to the existing acceptance/publication flow.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path, PurePosixPath

from sqlalchemy import select

from dotrix_backend.modules.code.checkouts import run_git
from dotrix_engine.planning import ExecutionSpec

from .models import CodingRun, CodingRunStatus
from .tools import Usage


async def record(runner, run_id, key, **fields):
    from .runner import _ReconciliationRequired, add_events

    async with runner.session_factory() as session:
        run = await session.scalar(select(CodingRun).where(CodingRun.id == run_id).with_for_update())
        if run is None or run.status is not CodingRunStatus.RUNNING or not runner._holds(run):
            raise _ReconciliationRequired()
        records = dict(run.task_records or {})
        records[key] = {**records.get(key, {}), **fields}
        run.task_records = records
        if "status" in fields:
            add_events(run, session, step=f"Task {key}: {fields['status']}")
        usage = [item.get("usage", {}) for item in records.values()]
        run.input_tokens = sum(item.get("input_tokens", 0) for item in usage)
        run.output_tokens = sum(item.get("output_tokens", 0) for item in usage)
        costs = [item.get("cost_usd") for item in usage]
        run.cost_usd = sum(costs) if costs and all(cost is not None for cost in costs) else None
        await session.commit()


async def report_usage(runner, run_id, key, usage: Usage):
    from dotrix_backend.core.model_prices import cost_of

    async with runner.session_factory() as session:
        run = await session.get(CodingRun, run_id)
        model = run.model if run else None
        prior = ((run.task_records or {}).get(key, {}).get("prior_usage", {})) if run else {}
    cost = usage.cost_usd if usage.cost_usd is not None else cost_of(
        model, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
        cached_input_tokens=usage.cached_input_tokens, cache_write_tokens=usage.cache_write_tokens,
        overrides=runner.settings.model_prices)
    await record(runner, run_id, key, usage={"input_tokens": usage.input_tokens + prior.get("input_tokens", 0),
                                          "output_tokens": usage.output_tokens + prior.get("output_tokens", 0),
                                          "cost_usd": cost + prior.get("cost_usd", 0) if cost is not None and prior.get("cost_usd", 0) is not None else None})


def check_scope(paths, owned):
    from .runner import RunFailed

    for path in paths:
        target = PurePosixPath(path)
        if not any(target == PurePosixPath(root) or PurePosixPath(root) in target.parents for root in owned):
            raise RunFailed(f"Task changed an unassigned path: {path}; refine the plan")


async def execute(runner, run_id, work: Path, host: Path, tool, key, model, brief, allow, execution: dict,
                  dependencies: dict[int, list[int]]) -> tuple[str, str]:
    from .runner import BOT_EMAIL, RunFailed, _baseline, _export, _stage, _Stopped
    from .warm import close_quietly

    spec = ExecutionSpec.model_validate(execution)
    initial = (await run_git(host, "rev-parse", "HEAD")).strip()
    if initial != spec.base_sha:
        raise RunFailed("The repository changed since this plan was written; refresh the plan before building")
    async with runner.session_factory() as session:
        run = await session.get(CodingRun, run_id)
        saved = dict(run.task_records or {}) if run else {}
        if run is None or spec.repository != run.repo_full_name:
            raise RunFailed("The plan names a different repository")
    for task in spec.tasks:
        if task.key not in saved:
            await record(runner, run_id, task.key, status="queued", owned_paths=task.owned_paths)
    completed: set[int] = set()
    summaries: list[str] = []
    by_number = {task.task_number: task for task in spec.tasks}
    boxes = []

    async def run_check(box, command):
        cancel = asyncio.Event()

        async def watch():
            while not cancel.is_set():
                if await runner.stop_requested(run_id) or await runner.reconciliation_required(run_id):
                    cancel.set()
                    return
                await asyncio.sleep(1)

        watcher = asyncio.create_task(watch())
        try:
            result = await box.exec(["sh", "-c", command], timeout=runner.settings.coding_timeout_minutes * 60, cancel=cancel)
            if result.cancelled or cancel.is_set():
                raise _Stopped("Stopped during verification")
            return result
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


    async def worker(number):
        task = by_number[number]
        existing = saved.get(task.key, {})
        if existing.get("status") in {"verified", "completed"} and existing.get("base_sha") == initial:
            return number, existing.get("patch", ""), existing.get("summary", "")
        task_dir = work / "tasks" / task.key
        task_dir.mkdir(parents=True, exist_ok=True)
        checkout = task_dir / "host"
        await run_git(task_dir, "clone", "--no-hardlinks", "--quiet", str(host), str(checkout))
        source = task_dir / "upload" / "repo"
        await _export(checkout, source)
        baseline = await _baseline(source)
        box = await runner.sandbox.open(uuid.uuid4(), source, tool, key, **({"allow": allow} if allow else {}))
        boxes.append(box)
        await record(runner, run_id, task.key, status="running", base_sha=initial,
                     attempt=existing.get("attempt", 0) + 1, owned_paths=task.owned_paths,
                     prior_usage=existing.get("usage", {}))
        try:
            session_id = uuid.uuid4()
            task_brief = (brief + "\n\n## Assigned task\n" + json.dumps(task.model_dump())
                          + "\nImplement only this task. Do not launch other agents, commit, push or publish. "
                          "Read other files as needed, but change only the owned paths. Stop if assumptions differ.")
            summary, _ = await runner._code(run_id, box, tool, model, session_id, task_brief,
                                            tool.session_args(session_id, False), None, task_key=task.key)
            await record(runner, run_id, task.key, status="verifying")
            evidence = []
            for check in task.checks:
                if await runner.stop_requested(run_id):
                    raise _Stopped("Stopped by a person")
                result = await run_check(box, check.command)
                evidence.append({"command": check.command, "expected": check.expected, "exit_code": result.code,
                                 "output": (result.stdout + result.stderr)[-8000:]})
                if result.code != 0 or result.timed_out or result.cancelled:
                    await record(runner, run_id, task.key, checks=evidence)
                    raise RunFailed(f"Task {task.key} failed verification: {check.command}")
            result = await box.exec(["sh", "-c", "git add -A && git diff --cached --binary --no-ext-diff --no-textconv "
                                     f"--no-renames {baseline}"], timeout=300)
            if result.code != 0 or result.truncated or len(result.stdout.encode()) > 8_000_000:
                raise RunFailed(f"Task {task.key} returned an unreadable or oversized patch")
            patch = result.stdout
            if patch.strip():
                paths, _ = await _stage(task_dir, checkout, patch)
                check_scope(paths, task.owned_paths)
                raw = await run_git(checkout, "diff", "--cached", "--raw", "--no-renames")
                if "120000" in raw:
                    raise RunFailed(f"Task {task.key} changed a symlink; refine the plan for explicit review")
            await record(runner, run_id, task.key, status="verified", patch=patch, summary=summary or "",
                         checks=evidence, base_sha=initial)
            return number, patch, summary or ""
        except BaseException:
            await record(runner, run_id, task.key, status="blocked")
            raise
        finally:
            await close_quietly(box)

    async def integrate(number, patch, summary):
        task = by_number[number]
        if patch.strip():
            paths, _ = await _stage(work, host, patch)
            check_scope(paths, task.owned_paths)
            await run_git(host, "-c", "user.name=dotrix", "-c", f"user.email={BOT_EMAIL}", "commit", "-q",
                          "--no-verify", "-m", f"Integrate {task.key}")
        completed.add(number)
        summaries.append(f"{task.key}: {summary}")
        await record(runner, run_id, task.key, status="completed")

    try:
        while len(completed) < len(spec.tasks):
            if await runner.stop_requested(run_id):
                raise _Stopped("Stopped by a person")
            # The parent owns one slot. Never wait for another while holding it: two parents
            # doing that could deadlock. Use a second slot only when it is immediately available.
            async with runner.slots.extra() as extra:
                ready = spec.ready_tasks(dependencies, completed, set(), limit=2 if extra else 1)
                if not ready:
                    raise RunFailed("No task is ready; the execution dependencies require replanning")
                jobs = [asyncio.create_task(worker(number)) for number in ready]
                try:
                    results = await asyncio.gather(*jobs)
                except BaseException:
                    for job in jobs:
                        job.cancel()
                    await asyncio.gather(*jobs, return_exceptions=True)
                    raise
                for result in results:
                    await integrate(*result)
        # Verify the combined result independently, in a new sandbox without a model.
        source = work / "verification" / "repo"
        await _export(host, source)
        verify_base = await _baseline(source)
        box = await runner.sandbox.open(uuid.uuid4(), source, tool, key, **({"allow": allow} if allow else {}))
        try:
            for command in dict.fromkeys(check.command for task in spec.tasks for check in task.checks):
                if await runner.stop_requested(run_id):
                    raise _Stopped("Stopped by a person")
                result = await run_check(box, command)
                if result.code != 0 or result.timed_out:
                    raise RunFailed(f"Combined verification failed: {command}")
            changed = await box.exec(["sh", "-c", f"git add -A && git diff --cached --quiet {verify_base}"], timeout=60)
            if changed.code != 0:
                raise RunFailed("Combined verification changed tracked files; refine the plan before publishing")
        finally:
            await close_quietly(box)
        patch = await run_git(host, "diff", "--binary", "--no-ext-diff", "--no-textconv", "--no-renames", initial, "HEAD")
        if len(patch.encode()) > 8_000_000:
            raise RunFailed("The combined patch exceeds the coding size limit")
        await run_git(host, "reset", "--hard", initial)
        return "\n\n".join(summaries) + "\n\nCombined verification passed.", patch
    finally:
        for box in boxes:
            await close_quietly(box)
