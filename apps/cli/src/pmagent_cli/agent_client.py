"""Talking to the platform's agents: start a run, wait, and settle its approvals.

UI-agnostic: the terminal (or a test) supplies `decide`, which is shown one pending
change at a time and returns ("approve" | "reject", reason). A run can pause
several times (each write pauses), so `converse` loops until the run completes,
fails, or is left waiting for someone else to approve.

With `on_text`, the Project Manager's reply is followed as it's written (the run's
server-sent event stream) instead of appearing at the end. Streaming is best effort:
if it's unavailable, waiting falls back to polling and the saved reply is shown.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .platform import PlatformClient, PlatformError
from .sync import LinkState

DONE_STATUSES = ("completed", "failed", "awaiting_approval")
Decision = tuple[str, str | None]  # ("approve" | "reject" | "steer" (a checkpoint), reason)


class ApprovalNotAllowed(Exception):
    """The signed-in person can't approve; the run waits for someone who can."""


OnText = Callable[[str, bool], None]  # (text, starts a new message)
OnActivity = Callable[[str], None]  # what the PM is doing now, e.g. "Reading roadmap.md"


@dataclass
class Outcome:
    run: dict[str, Any]
    left_waiting: bool = False  # awaiting approval that this person couldn't give
    streamed: str = ""  # the last message as it was shown while streaming

    @property
    def reply_shown(self) -> bool:
        """Whether streaming already showed the whole reply."""
        reply = (self.run.get("reply") or "").strip()
        return bool(reply) and self.streamed.strip() == reply

    @property
    def status(self) -> str:
        return self.run["status"]


class PlatformAgent:
    def __init__(self, client: PlatformClient, state: LinkState, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.client = client
        self.base = f"/workspaces/{state.workspace_id}/projects/{state.project_id}/agent"
        self.sleep = sleep

    def start(
        self, message: str, thread_id: str | None = None, *, agent: str | None = None, model: str | None = None
    ) -> dict:
        """Send a message: `agent` picks who answers (auto or a specialist); `model` is only for
        a new conversation (an existing one keeps the model it started with)."""
        body: dict[str, Any] = {"message": message}
        if thread_id:
            body["thread_id"] = thread_id
        if agent and agent != "auto":
            body["agent"] = agent
        if model and not thread_id:
            body["model"] = model
        return self.client.post(f"{self.base}/runs", body)

    def briefing(self) -> dict:
        return self.client.post(f"{self.base}/briefing")

    def triage(self, report: str) -> dict:
        """The Project Manager triages a report: duplicates, then a proposed issue or comment."""
        return self.client.post(f"{self.base}/triage", {"report": report})

    def review(self, key: str) -> dict:
        """The Reviewer reviews one issue against its acceptance criteria."""
        return self.client.post(f"{self.base}/issues/{key}/review")

    def get(self, run_id: str) -> dict:
        return self.client.get(f"{self.base}/runs/{run_id}")

    def list_runs(self, limit: int = 20) -> list[dict]:
        """The project's most recent runs, newest first."""
        return self.client.get(f"{self.base}/runs", params={"limit": limit})

    def stop(self, run_id: str) -> dict:
        return self.client.post(f"{self.base}/runs/{run_id}/stop")

    def wait(
        self,
        run: dict,
        *,
        timeout: float = 900,
        on_tick: Callable[[dict], None] | None = None,
        on_text: OnText | None = None,
        on_activity: OnActivity | None = None,
        shown: list[str] | None = None,
    ) -> dict:
        """Wait until the run stops (completed, failed, or waiting for approval): follow its
        stream with `on_text`, otherwise poll. `shown` holds the current message's text so
        far, across calls."""
        shown = shown if shown is not None else [""]
        delay, waited = 0.5, 0.0
        streaming = on_text is not None
        while run["status"] not in DONE_STATUSES:
            if waited >= timeout:
                raise TimeoutError(f"Run {run['id']} is still {run['status']} after {int(timeout)}s")
            started = time.monotonic()
            got_text = False
            if streaming:
                try:
                    got_text = self._follow(run, on_text, shown, on_activity)  # type: ignore[arg-type]
                except PlatformError:
                    streaming = False  # (an older server, or the connection dropped): poll
            waited += time.monotonic() - started
            run = self.client.get(f"{self.base}/runs/{run['id']}")
            if on_tick:
                on_tick(run)
            if run["status"] in DONE_STATUSES:
                break
            if not got_text:
                # Queued, or between steps: no stream yet. Wait a little before looking again.
                self.sleep(delay)
                waited += delay
                delay = min(delay * 1.5, 3.0)
        return run

    def _follow(self, run: dict, on_text: OnText, shown: list[str], on_activity: OnActivity | None = None) -> bool:
        """Show the stream until it ends; True if any text came."""
        got = False
        for event, data in self.client.events(f"{self.base}/runs/{run['id']}/stream"):
            text = data.get("text", "") if isinstance(data, dict) else ""
            if event == "text":
                # Everything so far. A reconnect repeats what was shown; a new step starts afresh.
                if text.startswith(shown[0]):
                    if text[len(shown[0]):]:
                        on_text(text[len(shown[0]):], not shown[0])
                else:
                    on_text(text, True)
                shown[0] = text
                got = got or bool(text)
            elif event == "delta" and text:
                on_text(text, not shown[0])
                shown[0] += text
                got = True
            elif event == "activity" and text and on_activity is not None:
                on_activity(text)
            elif event == "end":
                break
        return got

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
        on_text: OnText | None = None,
        on_activity: OnActivity | None = None,
    ) -> Outcome:
        """Wait for the run, settle each pause with `decide`, and repeat until it ends.

        `decide(approval, index, total)` returns a Decision, or "approve-all" to approve
        this and every remaining change in the same pause.
        """
        shown = [""]
        run = self.wait(run, on_tick=on_tick, on_text=on_text, on_activity=on_activity, shown=shown)
        while run["status"] == "awaiting_approval":
            pending = [a for a in run["approvals"] if a["status"] == "pending"]
            decisions: list[tuple[dict, Decision]] = []
            approve_rest = False
            for index, approval in enumerate(pending, 1):
                if approve_rest and approval["tool"] != "checkpoint":  # a plan is answered, not approved in bulk
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
                return Outcome(run, left_waiting=True, streamed=shown[0])
            shown[0] = ""  # the resumed run writes a new message
            run = self.wait(run, on_tick=on_tick, on_text=on_text, on_activity=on_activity, shown=shown)
        return Outcome(run, streamed=shown[0])
