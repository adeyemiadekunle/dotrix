"""An in-memory stand-in for the platform API, for CLI tests (httpx.MockTransport)."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from dotrix_cli.platform import PlatformClient

WS, PID = "ws-1", "proj-1"
KB = f"/v1/workspaces/{WS}/projects/{PID}/knowledge"
ISSUES = f"/v1/workspaces/{WS}/projects/{PID}/issues"
AGENT = f"/v1/workspaces/{WS}/projects/{PID}/agent"
CODING = f"/v1/workspaces/{WS}/projects/{PID}/coding"


def canonical(url: str) -> str:
    """The server's repo-URL canonical form, enough for tests."""
    url = url.strip().removesuffix("/").removesuffix(".git")
    if url.startswith("git@"):
        host, path = url[4:].split(":", 1)
        return f"https://{host}/{path}"
    return url


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
        # Each GET of a run's stream serves the next list of (event, text) as server-sent
        # events; with none left, the stream just ends (the run isn't working right now).
        self.streams: list[list[tuple[str, str]]] = []
        self.stream_status = 200  # e.g. 404 for a server without streaming
        self.runs_list: list[dict[str, Any]] = []  # GET .../agent/runs (newest first)
        # Uploads: without states, converted at once; otherwise each GET of the document applies
        # the next state (e.g. {"status": "converting"}, then {"status": "ready", ...}).
        self.documents: list[dict[str, Any]] = []
        self.document_states: list[dict[str, Any]] = []
        self.stopped: list[str] = []  # runs stopped through .../stop
        self.runs_started: list[dict[str, Any]] = []
        # Workspaces the signed-in person belongs to, and the projects in them.
        self.workspaces: list[dict[str, Any]] = [
            {"id": WS, "slug": "kunemi-ab12cd", "name": "Kunemi", "role": "owner", "kind": "organization"}
        ]
        self.projects: list[dict[str, Any]] = []
        # Set to a workspace (with a "projects" list) when the linked project moved there: the
        # project is then gone from WS and found in that workspace instead.
        self.moved_to: dict[str, Any] | None = None
        self.me = {"id": "user-1", "email": "ada@example.com", "display_name": "Ada"}
        # Kai's coding sessions (GET .../coding/sessions) and each one's turns, by session id; each
        # GET of a run answers with the next of `coding_script` when there is one (for waiting).
        self.coding_sessions: list[dict[str, Any]] = []
        self.coding_turns: dict[str, list[dict[str, Any]]] = {}
        self.coding_script: list[dict[str, Any]] = []
        # GET .../coding/sessions answers with the next of these lists when there are any (a
        # session appearing after a Build turn), then with `coding_sessions`.
        self.coding_session_lists: list[list[dict[str, Any]]] = []

    # -- state changes, as if someone edited on the platform ----------------------------
    def put(self, path: str, content: str) -> None:
        self.revision += 1
        self.files[path] = {"content": content, "revision": self.revision, "deleted": False}

    def remove(self, path: str) -> None:
        self.revision += 1
        self.files[path] = {"content": "", "revision": self.revision, "deleted": True}

    # -- HTTP ---------------------------------------------------------------------
    def client(self, token: str | None = "dtx_test") -> PlatformClient:
        http = httpx.Client(base_url="http://fake", transport=httpx.MockTransport(self.handle))
        return PlatformClient("http://fake", token, http=http)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        is_json = request.headers.get("content-type", "").startswith("application/json")
        body = json.loads(request.content) if request.content and is_json else {}
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
                return httpx.Response(200, json={"id": "tok-1", "token": "dtx_new"})
            return self.problem(400, answer)
        if path == "/v1/me":
            return httpx.Response(200, json=self.me)
        if path == f"/v1/workspaces/{WS}/projects/{PID}/graph/neighbors":
            ref = request.url.params["ref"]
            node = {"ref": ref, "kind": "issue", "subtype": "task", "title": "Postcode lookup", "status": "todo"}
            linked = {"ref": "requirements/lookup.md", "kind": "document", "subtype": "requirements",
                      "title": "Lookup", "status": None}
            return httpx.Response(200, json={"node": node, "links": [
                {"id": "l-1", "direction": "out", "kind": "implements", "origin": "derived", "agent": None,
                 "reason": None, "node": linked},
            ]})
        if path == f"/v1/workspaces/{WS}/projects/{PID}/agents" and method == "GET":
            return httpx.Response(200, json=[
                {"handle": "project-manager", "name": "Nova", "source": "built_in", "scope": "default",
                 "description": "Coordinates the specialists."},
                {"handle": "research", "name": "Research Agent", "source": "built_in", "scope": "default",
                 "description": "Runs external research."},
                {"handle": "security", "name": "Security reviewer", "source": "custom", "scope": "project",
                 "description": "Reviews changes for security risks."},
            ])
        if path == f"/v1/workspaces/{WS}/projects/{PID}" and method == "GET":
            if self.moved_to is not None:
                return self.problem(404, "not_found")
            return httpx.Response(200, json={"id": PID, "key": "KUN", "name": "Kunemi", "workspace_id": WS})
        if self.moved_to is not None:
            if path == "/v1/workspaces" and method == "GET":
                return httpx.Response(200, json=[*self.workspaces, self.moved_to])
            if path == f"/v1/workspaces/{self.moved_to['id']}/projects" and method == "GET":
                return httpx.Response(200, json=self.moved_to["projects"])
        if path == "/v1/workspaces" and method == "GET":
            return httpx.Response(200, json=self.workspaces)
        if path == f"/v1/workspaces/{WS}/projects" and method == "GET":
            wanted = request.url.params.get("repo_url")
            found = [p for p in self.projects if wanted is None or p.get("repo_url") == canonical(wanted)]
            return httpx.Response(200, json=found)
        if path == f"/v1/workspaces/{WS}/projects" and method == "POST":
            project = {"id": PID, "key": body["key"], "name": body["name"], "description": body.get("description", ""),
                       "model": "google_genai:gemini-3.8-flash", "repo_url": canonical(body["repo_url"]) if body.get("repo_url") else None,
                       "source": body.get("source"), "readme": body.get("readme")}
            self.projects.append(project)
            return httpx.Response(201, json=project)
        if path == f"/v1/workspaces/{WS}/projects/{PID}/documents" and method == "POST":
            name = request.content.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
            path = f"docs/normalized/{name.rsplit('.', 1)[0]}.md"
            doc = {"id": f"doc-{len(self.documents) + 1}", "filename": name, "knowledge_path": path,
                   "knowledge_version": 0, "status": "converting", "error": None}
            self.documents.append(doc)
            if not self.document_states:  # converted straight away
                self.put(path, f"imported {name}")
                doc |= {"status": "ready", "knowledge_version": 1}
            return httpx.Response(201, json=doc)
        if path.startswith(f"/v1/workspaces/{WS}/projects/{PID}/documents/") and method == "GET":
            doc = next(d for d in self.documents if d["id"] == path.rsplit("/", 1)[1])
            if self.document_states:
                doc |= self.document_states.pop(0)
                if doc["status"] == "ready":
                    self.put(doc["knowledge_path"], f"imported {doc['filename']}")
            return httpx.Response(200, json=doc)
        if path == AGENT + "/architecture-draft" and method == "POST":
            self.runs_started.append(body)
            return httpx.Response(202, json={"id": "run-1", "thread_id": "thread-1", "status": "queued",
                                             "approvals": [], "reply": None, "error": None})
        if path.startswith("/v1/me/tokens/") and method == "DELETE":
            return httpx.Response(204)
        if (path in (AGENT + "/runs", AGENT + "/briefing", AGENT + "/triage")
                or (path.startswith(AGENT + "/issues/") and path.endswith("/review"))) and method == "POST":
            self.runs_started.append(body)
            run = {"id": "run-1", "thread_id": body.get("thread_id") or "thread-1", "status": "queued",
                   "approvals": [], "reply": None, "error": None}
            return httpx.Response(202, json=run)
        if path.startswith(AGENT + "/runs/") and path.endswith("/always-allow") and method == "POST":
            if self.deny_decisions:
                return self.problem(403, "forbidden")
            return httpx.Response(200, json={"handle": "product", "autonomy": {"knowledge.write": "allow"}})
        if path.startswith(AGENT + "/runs/") and path.endswith("/decisions"):
            if self.deny_decisions:
                return self.problem(403, "forbidden")
            return httpx.Response(200, json=self._next_run())
        if path == AGENT + "/runs" and method == "GET":
            return httpx.Response(200, json=self.runs_list[: int(request.url.params.get("limit", 20))])
        if path.startswith(AGENT + "/runs/") and path.endswith("/stop") and method == "POST":
            run_id = path.split("/")[-2]
            self.stopped.append(run_id)
            return httpx.Response(200, json={"id": run_id, "status": "failed"})
        if path.startswith(AGENT + "/runs/") and path.endswith("/stream"):
            if self.stream_status != 200:
                return self.problem(self.stream_status, "not_found")
            events = self.streams.pop(0) if self.streams else []
            sse = ": ping\n\n" + "".join(
                f"event: {event}\ndata: {json.dumps({'text': text})}\n\n" for event, text in [*events, ("end", "")]
            )
            return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})
        if path.startswith(AGENT + "/runs/") and method == "GET":
            return httpx.Response(200, json=self._next_run())
        if path == f"/v1/workspaces/{WS}/coding/sessions" and method == "GET":
            if self.coding_session_lists:
                return httpx.Response(200, json=self.coding_session_lists.pop(0))
            return httpx.Response(200, json=self.coding_sessions)
        if path.startswith(CODING + "/"):
            return self._coding(path.removeprefix(CODING), method, body)
        if path.startswith(AGENT + "/runs/") and path.endswith("/continue") and method == "POST":
            self.runs_started.append({"continue": path.split("/")[-2], **body})
            return httpx.Response(202, json=self._next_run())
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

    def _coding(self, path: str, method: str, body: dict[str, Any]) -> httpx.Response:
        turns = [t for ts in self.coding_turns.values() for t in ts]
        if path.startswith("/sessions/") and path.endswith("/turns") and method == "POST":
            session_id = path.split("/")[2]
            prior = self.coding_turns[session_id][-1]
            turn = prior | {"id": f"run-{len(turns) + 1}", "turn": prior["turn"] + 1, "status": "queued",
                            "note": body["message"], "events": [], "files_changed": [], "summary": None}
            self.coding_turns[session_id].append(turn)
            return httpx.Response(201, json=turn)
        if path.startswith("/sessions/") and method == "GET":
            return httpx.Response(200, json=self.coding_turns.get(path.split("/")[2], []))
        if path.startswith("/issues/") and path.endswith("/runs") and method == "POST":
            key = path.split("/")[2]
            run = coding_run("run-new", key, status="awaiting_approval" if body.get("approval_mode") in (None, "manual") else "queued")
            return httpx.Response(201, json=run)
        if path.startswith("/runs/"):
            parts = path.split("/")
            run_id, action = parts[2], parts[3] if len(parts) > 3 else ""
            turn = next((t for t in turns if t["id"] == run_id), None)
            if turn is None:
                return self.problem(404, "not_found")
            if action == "diff":
                return httpx.Response(200, json={"base_sha": None, "diff": turn.get("diff", ""), "files": []})
            if method == "GET":
                if self.coding_script:
                    turn |= self.coding_script.pop(0)
                return httpx.Response(200, json=turn)
            if action == "decision":
                approved = body["decision"] == "approve"
                after = {"awaiting_approval": "queued" if approved else "rejected",
                         "changes_ready": "pr_opened" if approved else "no_changes"}
                turn["status"] = after.get(turn["status"], turn["status"])
                return httpx.Response(200, json=turn)
            if action == "stop":
                turn["status"] = "stopped"
                return httpx.Response(200, json=turn)
            if action == "recover":
                turn["status"] = "pr_opened" if body["action"] == "check" else "failed"
                return httpx.Response(200, json=turn)
            if action == "revert":
                session = self.coding_turns[turn["session_id"]]
                new = turn | {"id": f"run-{len(turns) + 1}", "turn": session[-1]["turn"] + 1, "status": "queued",
                              "revert_of": run_id, "can_revert": False}
                session.append(new)
                return httpx.Response(201, json=new)
        return self.problem(404, "not_found")

    def _next_run(self) -> dict[str, Any]:
        state = self.agent_script.pop(0) if len(self.agent_script) > 1 else self.agent_script[0]
        return {"id": "run-1", "thread_id": "thread-1", "approvals": [], "reply": None, "error": None, **state}

    @staticmethod
    def problem(status: int, code: str) -> httpx.Response:
        return httpx.Response(status, json={"type": f"https://dotrix.app/problems/{code}", "detail": code})

    def bodies(self, suffix: str) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith(suffix) and r.content]


def issue(key: str, **fields: Any) -> dict[str, Any]:
    return {"key": key, "type": "task", "title": f"Issue {key}", "status": "todo", "priority": "medium",
            "assignee_user_id": None, "assignee_agent": None, "parent_key": None, **fields}


def approval(approval_id: str, tool: str = "write_file", target: str = "/dotrix/roadmap.md", **extra: Any) -> dict:
    return {"id": approval_id, "tool": tool, "target": target, "args": {}, "diff": None, "status": "pending", **extra}


def coding_run(run_id: str, key: str = "KUN-7", *, session_id: str = "0192abcd-0000-7000-8000-000000000001", turn: int = 1,
               **fields: Any) -> dict[str, Any]:
    return {"id": run_id, "project_id": PID, "issue_key": key, "session_id": session_id, "turn": turn,
            "status": "pr_opened", "note": None, "events": [], "files_changed": [], "summary": None, "error": None,
            "repo_full_name": "kunemi/app", "branch": "kai/kun-7", "commit_sha": None, "pr_number": None,
            "pr_url": None, "ci_state": None, "review_posted_url": None, "model": "anthropic:claude-sonnet-5-5",
            "location": "cloud", "can_decide": False, "can_stop": False, "can_revert": False, "can_recover": False,
            "ci_sensitive": [], "revert_of": None, **fields}


def coding_session(key: str = "KUN-7", *, session_id: str = "0192abcd-0000-7000-8000-000000000001",
                   **fields: Any) -> dict[str, Any]:
    return {"session_id": session_id, "project_id": PID, "project_key": "KUN", "issue_key": key,
            "issue_title": "Fix the postcode lookup", "title": "Fix the postcode lookup", "status": "pr_opened",
            "branch": "kai/kun-7", "pr_number": None, "pr_url": None, "pr_state": None, "thread_id": None,
            "archived": False, "updated_at": "2026-11-01T10:00:00Z", **fields}
