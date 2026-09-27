"""The platform issue board, for the CLI and the MCP server.

A person uses it as themselves. Claude Code and Codex use it `as_agent`, which the
platform restricts to their own issues: claim, comment, block, and hand back for
review (only a person closes an issue).
"""
from __future__ import annotations

from typing import Any

from .platform import PlatformClient
from .sync import LinkState

CODING_AGENTS = ("claude-code", "codex", "coding-agent")


class PlatformBoard:
    def __init__(self, client: PlatformClient, state: LinkState, agent: str | None = None) -> None:
        if agent is not None and agent not in CODING_AGENTS:
            raise ValueError(f"Unknown agent {agent!r}; use one of {', '.join(CODING_AGENTS)}")
        self.client, self.state, self.agent = client, state, agent
        self.base = state.issues_path

    def _as(self, body: dict[str, Any]) -> dict[str, Any]:
        return {**body, "as_agent": self.agent} if self.agent else body

    def list(self, *, status: str | None = None, mine: bool = False, ready: bool = False) -> list[dict]:
        params: dict[str, Any] = {"order": "priority"}
        if status:
            params["status"] = status
        if ready:
            params["ready"] = True
        if mine:
            if self.agent is None:
                raise ValueError("--mine needs --as <agent>; people can filter with `--assignee <user id>`")
            params["assignee"] = self.agent
        return self.client.get(self.base, params=params)

    def get(self, key: str) -> dict:
        return self.client.get(f"{self.base}/{key}")

    def next(self) -> dict:
        params = {"as_agent": self.agent} if self.agent else {}
        return self.client.get(f"{self.base}/next", params=params)

    def claim(self, key: str | None = None) -> dict:
        body: dict[str, Any] = {"key": key} if key else {}
        return self.client.post(f"{self.base}/claim", self._as(body))

    def comment(self, key: str, text: str) -> dict:
        return self.client.post(f"{self.base}/{key}/comments", self._as({"body": text}))

    def block(self, key: str, reason: str) -> dict:
        return self.client.patch(f"{self.base}/{key}", self._as({"status": "blocked", "note": reason}))

    def review(self, key: str, summary: str, pr_url: str | None = None) -> dict:
        body: dict[str, Any] = {"status": "review", "note": summary}
        if pr_url:
            current = self.get(key).get("links", [])
            body["links"] = [*current, {"kind": "pr", "url": pr_url}]
        return self.client.patch(f"{self.base}/{key}", self._as(body))

    def done(self, key: str, note: str | None = None) -> dict:
        if self.agent is not None:
            raise ValueError("Only a person closes an issue; coding agents hand it back for review")
        body: dict[str, Any] = {"status": "done"}
        if note:
            body["note"] = note
        return self.client.patch(f"{self.base}/{key}", body)
