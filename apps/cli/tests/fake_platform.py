"""An in-memory stand-in for the platform API, for CLI tests (httpx.MockTransport)."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from pmagent_cli.platform import PlatformClient

WS, PID = "ws-1", "proj-1"
KB = f"/v1/workspaces/{WS}/projects/{PID}/knowledge"
ISSUES = f"/v1/workspaces/{WS}/projects/{PID}/issues"
AGENT = f"/v1/workspaces/{WS}/projects/{PID}/agent"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class FakePlatform:
    def __init__(self) -> None:
        self.revision = 1
        self.files: dict[str, dict[str, Any]] = {}  # path -> {content, revision, deleted}
        self.requests: list[httpx.Request] = []
        self.issues: dict[str, dict[str, Any]] = {}
        self.device_polls: list[str] = []  # scripted answers for /auth/device/token
        # Agent runs: each GET of a run, and each decision, returns the next scripted state.
        self.agent_script: list[dict[str, Any]] = []
        self.deny_decisions = False  # answer decisions with 403 (role can't approve)
        self.runs_started: list[dict[str, Any]] = []

    # -- state changes, as if someone edited on the platform ----------------------------
    def put(self, path: str, content: str) -> None:
        self.revision += 1
        self.files[path] = {"content": content, "revision": self.revision, "deleted": False}

    def remove(self, path: str) -> None:
        self.revision += 1
        self.files[path] = {"content": "", "revision": self.revision, "deleted": True}

    # -- HTTP ---------------------------------------------------------------------
    def client(self, token: str | None = "pmat_test") -> PlatformClient:
        http = httpx.Client(base_url="http://fake", transport=httpx.MockTransport(self.handle))
        return PlatformClient("http://fake", token, http=http)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        if path == KB:
            since = request.url.params.get("since_revision")
            entries = [
                {"path": p, "version": 1, "revision": f["revision"], "content_hash": sha(f["content"]),
                 "size": len(f["content"]), "deleted": f["deleted"], "updated_at": "2026-09-27T00:00:00Z"}
                for p, f in sorted(self.files.items())
                if (since is None and not f["deleted"]) or (since is not None and f["revision"] > int(since))
            ]
            return httpx.Response(200, json={"revision": self.revision, "files": entries})
        if path.startswith(KB + "/files/"):
            f = self.files[path.removeprefix(KB + "/files/")]
            return httpx.Response(200, json={"content": f["content"]})
        if path == "/v1/auth/device/code":
            return httpx.Response(200, json={
                "device_code": "dev-123", "user_code": "BCDF-GHJK", "verification_uri": "http://fake/device",
                "verification_uri_complete": "http://fake/device?code=BCDF-GHJK", "expires_in": 600, "interval": 5,
            })
        if path == "/v1/auth/device/token":
            answer = self.device_polls.pop(0)
            if answer == "ok":
                return httpx.Response(200, json={"id": "tok-1", "token": "pmat_new"})
            return self.problem(400, answer)
        if path.startswith("/v1/me/tokens/") and method == "DELETE":
            return httpx.Response(204)
        if path in (AGENT + "/runs", AGENT + "/briefing") and method == "POST":
            self.runs_started.append(body)
            run = {"id": "run-1", "thread_id": body.get("thread_id") or "thread-1", "status": "queued",
                   "approvals": [], "reply": None, "error": None}
            return httpx.Response(202, json=run)
        if path.startswith(AGENT + "/runs/") and path.endswith("/decisions"):
            if self.deny_decisions:
                return self.problem(403, "forbidden")
            return httpx.Response(200, json=self._next_run())
        if path.startswith(AGENT + "/runs/") and method == "GET":
            return httpx.Response(200, json=self._next_run())
        if path == ISSUES + "/claim":
            if not self.issues:
                return self.problem(404, "nothing_ready")
            key = body.get("key") or next(iter(self.issues))
            issue = self.issues[key] | {"status": "in_progress", "assignee_agent": body.get("as_agent")}
            self.issues[key] = issue
            return httpx.Response(200, json=issue)
        if path.startswith(ISSUES + "/") and method == "PATCH":
            key = path.rsplit("/", 1)[1]
            self.issues[key] |= {k: v for k, v in body.items() if k in ("status",)}
            return httpx.Response(200, json=self.issues[key] | {"log": []})
        if path.startswith(ISSUES + "/") and path.endswith("/comments"):
            return httpx.Response(201, json=self.issues[path.split("/")[-2]] | {"log": []})
        if path.startswith(ISSUES + "/") and method == "GET":
            return httpx.Response(200, json=self.issues[path.rsplit("/", 1)[1]] | {"log": [], "links": []})
        if path == ISSUES:
            return httpx.Response(200, json=list(self.issues.values()))
        return self.problem(404, "not_found")

    def _next_run(self) -> dict[str, Any]:
        state = self.agent_script.pop(0) if len(self.agent_script) > 1 else self.agent_script[0]
        return {"id": "run-1", "thread_id": "thread-1", "approvals": [], "reply": None, "error": None, **state}

    @staticmethod
    def problem(status: int, code: str) -> httpx.Response:
        return httpx.Response(status, json={"type": f"https://pmagent.dev/problems/{code}", "detail": code})

    def bodies(self, suffix: str) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith(suffix) and r.content]


def issue(key: str, **fields: Any) -> dict[str, Any]:
    return {"key": key, "type": "task", "title": f"Issue {key}", "status": "todo", "priority": "medium",
            "assignee_user_id": None, "assignee_agent": None, "parent_key": None, **fields}


def approval(approval_id: str, tool: str = "write_file", target: str = "/pmagent/roadmap.md", **extra: Any) -> dict:
    return {"id": approval_id, "tool": tool, "target": target, "args": {}, "diff": None, "status": "pending", **extra}
