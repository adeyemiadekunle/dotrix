"""Talking to the platform's agents: start a run, wait, and settle its approvals.

UI-agnostic: the terminal (or a test) supplies `decide`, which is shown one pending
change at a time and returns ("approve" | "reject", reason). A run can pause
several times (each write pauses), so `converse` loops until the run completes,
fails, or is left waiting for someone else to approve.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .platform import PlatformClient, PlatformError
from .sync import LinkState

DONE_STATUSES = ("completed", "failed", "awaiting_approval")
Decision = tuple[str, str | None]  # ("approve" | "reject", reason)


class ApprovalNotAllowed(Exception):
    """The signed-in person can't approve; the run waits for someone who can."""


@dataclass
class Outcome:
    run: dict[str, Any]
    left_waiting: bool = False  # awaiting approval that this person couldn't give

    @property
    def status(self) -> str:
        return self.run["status"]


class PlatformAgent:
    def __init__(self, client: PlatformClient, state: LinkState, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.client = client
        self.base = f"/workspaces/{state.workspace_id}/projects/{state.project_id}/agent"
        self.sleep = sleep

    def start(self, message: str, thread_id: str | None = None) -> dict:
        body: dict[str, Any] = {"message": message}
        if thread_id:
            body["thread_id"] = thread_id
        return self.client.post(f"{self.base}/runs", body)

    def briefing(self) -> dict:
        return self.client.post(f"{self.base}/briefing")

    def wait(self, run: dict, *, timeout: float = 900, on_tick: Callable[[dict], None] | None = None) -> dict:
        """Poll until the run stops (completed, failed, or waiting for approval)."""
        delay, waited = 0.5, 0.0
        while run["status"] not in DONE_STATUSES:
            if waited >= timeout:
                raise TimeoutError(f"Run {run['id']} is still {run['status']} after {int(timeout)}s")
            self.sleep(delay)
            waited += delay
            delay = min(delay * 1.5, 3.0)
            run = self.client.get(f"{self.base}/runs/{run['id']}")
            if on_tick:
                on_tick(run)
        return run

    def decide(self, run: dict, decisions: list[tuple[dict, Decision]]) -> dict:
        body = {
            "decisions": [
                {"approval_id": approval["id"], "decision": kind, "reason": reason}
                for approval, (kind, reason) in decisions
            ]
        }
        try:
            return self.client.post(f"{self.base}/runs/{run['id']}/decisions", body)
        except PlatformError as exc:
            if exc.status == 403:
                raise ApprovalNotAllowed(exc.detail) from exc
            raise

    def converse(
        self,
        run: dict,
        decide: Callable[[dict, int, int], Decision | str],
        *,
        on_tick: Callable[[dict], None] | None = None,
    ) -> Outcome:
        """Wait for the run, settle each pause with `decide`, and repeat until it ends.

        `decide(approval, index, total)` returns a Decision, or "approve-all" to approve
        this and every remaining change in the same pause.
        """
        run = self.wait(run, on_tick=on_tick)
        while run["status"] == "awaiting_approval":
            pending = [a for a in run["approvals"] if a["status"] == "pending"]
            decisions: list[tuple[dict, Decision]] = []
            approve_rest = False
            for index, approval in enumerate(pending, 1):
                if approve_rest:
                    decisions.append((approval, ("approve", None)))
                    continue
                answer = decide(approval, index, len(pending))
                if answer == "approve-all":
                    approve_rest = True
                    answer = ("approve", None)
                decisions.append((approval, answer))  # type: ignore[arg-type]
            try:
                run = self.decide(run, decisions)
            except ApprovalNotAllowed:
                return Outcome(run, left_waiting=True)
            run = self.wait(run, on_tick=on_tick)
        return Outcome(run)
