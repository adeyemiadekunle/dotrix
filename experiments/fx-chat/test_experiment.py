"""Exercise both real runtimes against a deterministic OpenAI-compatible local server."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from langchain_openai import ChatOpenAI
from run import evaluate, roles, validate
from team import ReadOnlyTeam

from dotrix_engine.runtimes import (
    AgentRuntimeConfig,
    DeepAgentsRuntime,
    FxRuntime,
    ModelPolicy,
    ModelSelection,
    RuntimeTool,
)


class ModelHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    evidence_name = "architecture.md"
    no_retry = False
    skip_result = False
    dependent_task = False
    same_specialist = False

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append(request)
        messages = request["messages"]
        offered = {tool["function"]["name"] for tool in request.get("tools", [])}
        needs_tool = messages[-1]["role"] != "tool"
        submit = False
        if "submit_specialist_result" in offered and messages[-1]["role"] == "tool" and not self.skip_result:
            previous_call = next((m["tool_calls"][0]["function"]["name"] for m in reversed(messages)
                                  if m.get("role") == "assistant" and m.get("tool_calls")), "")
            submit = previous_call == "read_evidence"
            needs_tool = submit
        if self.no_retry and any(m.get("role") == "assistant" and m.get("tool_calls") for m in messages):
            needs_tool = False
        base = {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1, "model": request["model"]}
        if needs_tool:
            if "delegate_tasks" in offered:
                tool_name = "delegate_tasks"
                tasks = [{"key": "architecture", "agent": "architecture", "brief": "Review the design",
                          "expected_result": "Findings", "depends_on": [], "changes_project": False}]
                if self.dependent_task:
                    tasks.append({"key": "review", "agent": "reviewer", "brief": "Review the findings",
                                  "expected_result": "Review", "depends_on": ["architecture"], "changes_project": False})
                if self.same_specialist:
                    tasks.append({"key": "second", "agent": "architecture", "brief": "Inspect the second design",
                                  "expected_result": "Second finding", "depends_on": [], "changes_project": False})
                arguments = {"tasks": tasks}
            elif submit:
                tool_name = "submit_specialist_result"
                last_user = next((str(m.get("content", "")) for m in reversed(messages) if m["role"] == "user"), "")
                arguments = {"summary": f"Architecture findings: {last_user[:100]}", "status": "completed",
                             "evidence": ["architecture.md"]}
            else:
                tool_name = "read_evidence"
                arguments = {"name": self.evidence_name}
            delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{len(self.requests)}", "type": "function",
                     "function": {"name": tool_name, "arguments": json.dumps(arguments)}}]}
            finish = "tool_calls"
        else:
            users = sum(message["role"] == "user" for message in messages)
            delta = {"role": "assistant", "content": f"Read evidence. User turns in context: {users}."}
            finish = "stop"
        chunks = [
            {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
            {**base, "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}},
        ]
        if request.get("stream"):
            payload = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            content_type = "text/event-stream"
        else:
            payload = json.dumps({"id": "chatcmpl-test", "object": "chat.completion", "created": 1,
                                  "model": request["model"], "choices": [{"index": 0, "message": delta,
                                  "finish_reason": finish}], "usage": {"prompt_tokens": 10,
                                  "completion_tokens": 4, "total_tokens": 14}})
            content_type = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(payload.encode())


class RuntimeTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        ModelHandler.requests = []
        ModelHandler.evidence_name = "architecture.md"
        ModelHandler.no_retry = False
        ModelHandler.skip_result = False
        ModelHandler.dependent_task = False
        ModelHandler.same_specialist = False
        self.scenario = {
            "name": "test",
            "evidence": {"architecture.md": "Synthetic architecture evidence."},
            "model_policy": {"tiers": {"strong": {"model": "main-model"},
                                        "economy": {"model": "specialist-model"}},
                             "agents": {"architecture": "economy"}, "default": "strong"},
            "turns": [
                {"id": "a", "agent": "architecture", "prompt": "First question"},
                {"id": "b", "agent": "architecture", "prompt": "Follow-up"},
                {"id": "c", "agent": "project-manager", "prompt": "Synthesize", "include": ["a"]},
            ],
        }
        self.roles = roles(self.scenario, "main-model")

    async def test_both_runtimes_use_tools_and_keep_role_sessions_separate(self):
        for kind in ("deepagents", "fx"):
            with self.subTest(runtime=kind):
                ModelHandler.requests = []
                result = await asyncio.wait_for(evaluate(kind, self.scenario, self.roles, self.base_url), timeout=60)
                turns = result["turns"]
                self.assertIn("User turns in context: 2", turns["b"]["text"])
                self.assertIn("User turns in context: 1", turns["c"]["text"])
                self.assertEqual(turns["a"]["tools"], ["read_evidence"])
                self.assertEqual(turns["a"]["model"], "specialist-model")
                self.assertEqual(turns["c"]["model"], "main-model")
                self.assertTrue(any("Synthetic architecture evidence." in json.dumps(r["messages"]) for r in ModelHandler.requests))
                for request in ModelHandler.requests:
                    self.assertEqual({t["function"]["name"] for t in request.get("tools", [])}, {"read_evidence"})

    async def test_unknown_evidence_is_not_readable(self):
        ModelHandler.evidence_name = "/etc/passwd"
        for kind in ("deepagents", "fx"):
            ModelHandler.requests = []
            scenario = {**self.scenario, "turns": self.scenario["turns"][:1]}
            await asyncio.wait_for(evaluate(kind, scenario, self.roles, self.base_url), timeout=60)
            self.assertTrue(any("Evidence document not found." in json.dumps(r["messages"]) for r in ModelHandler.requests))

    def test_forward_reference_is_rejected(self):
        self.scenario["turns"][0]["include"] = ["b"]
        with self.assertRaises(ValueError):
            validate(self.scenario, self.roles)

    async def test_command_outputs_comparable_json(self):
        with tempfile.TemporaryDirectory() as directory:
            scenario = Path(directory) / "scenario.json"
            scenario.write_text(json.dumps(self.scenario))
            process = await asyncio.create_subprocess_exec(
                sys.executable, str(Path(__file__).with_name("run.py")), "--runtime", "both",
                "--scenario", str(scenario), "--model", "main-model", "--base-url", self.base_url,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
            self.assertEqual(process.returncode, 0, stderr.decode())
            reports = json.loads(stdout)
            self.assertEqual([report["runtime"] for report in reports], ["deepagents", "fx"])
            self.assertEqual(set(reports[0]["turns"]), set(reports[1]["turns"]))
            process = await asyncio.create_subprocess_exec(
                sys.executable, str(Path(__file__).with_name("run.py")), "--runtime", "both", "--delegate",
                "--scenario", str(scenario), "--model", "main-model", "--base-url", self.base_url,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
            self.assertEqual(process.returncode, 0, stderr.decode())
            reports = json.loads(stdout)
            self.assertTrue(all(report["specialists"][0]["model"] == "specialist-model" for report in reports))

    async def test_host_delegates_to_cheaper_specialist_with_both_runtimes(self):
        policy = ModelPolicy(
            tiers={"strong": ModelSelection("main-model"), "economy": ModelSelection("specialist-model")},
            agents={"project-manager": "strong", "architecture": "economy"}, default="economy",
        )
        for kind in ("deepagents", "fx"):
            ModelHandler.requests = []

            async def factory(config, selection, selected_kind=kind):
                if selected_kind == "fx":
                    return await FxRuntime.create(config, model=selection.model, base_url=self.base_url)
                model = ChatOpenAI(model=selection.model, base_url=self.base_url, api_key="test", use_responses_api=False)
                return DeepAgentsRuntime(config, model)

            team = ReadOnlyTeam(factory, policy, self.scenario["evidence"])
            try:
                result = await asyncio.wait_for(team.ask("Please ask Orion about the design"), timeout=60)
            finally:
                await team.close()
            self.assertEqual(result.stop_reason, "end_turn")
            self.assertIn("delegate_tasks", result.tools)
            main_requests = [r for r in ModelHandler.requests if r["model"] == "main-model"]
            child_requests = [r for r in ModelHandler.requests if r["model"] == "specialist-model"]
            self.assertTrue(child_requests)
            self.assertTrue(any("Architecture findings" in json.dumps(r["messages"]) and
                                "architecture.md" in json.dumps(r["messages"]) for r in main_requests))
            self.assertTrue(all({t["function"]["name"] for t in r.get("tools", [])} == {"read_evidence", "submit_specialist_result"}
                                for r in child_requests))

    async def test_missing_structured_result_blocks_dependent_specialist(self):
        ModelHandler.skip_result = True
        ModelHandler.dependent_task = True
        policy = ModelPolicy(
            {"main": ModelSelection("main-model"), "child": ModelSelection("specialist-model"),
             "review": ModelSelection("review-model")},
            {"project-manager": "main", "architecture": "child", "reviewer": "review"}, default="child",
        )
        for kind in ("deepagents", "fx"):
            ModelHandler.requests = []

            async def factory(config, selection, selected_kind=kind):
                if selected_kind == "fx":
                    return await FxRuntime.create(config, model=selection.model, base_url=self.base_url)
                model = ChatOpenAI(model=selection.model, base_url=self.base_url, api_key="test", use_responses_api=False)
                return DeepAgentsRuntime(config, model)

            team = ReadOnlyTeam(factory, policy, self.scenario["evidence"])
            try:
                result = await asyncio.wait_for(team.ask("Ask for architecture and review"), timeout=60)
                self.assertEqual(result.stop_reason, "end_turn")
                self.assertEqual([item["status"] for item in team.observations], ["partial"])
                self.assertFalse(any(r["model"] == "review-model" for r in ModelHandler.requests))
                parent_messages = json.dumps([r["messages"] for r in ModelHandler.requests if r["model"] == "main-model"])
                self.assertIn("No structured specialist result", parent_messages)
                self.assertIn("blocked", parent_messages)
            finally:
                await team.close()

    async def test_parallel_tasks_for_one_specialist_keep_their_results_separate(self):
        ModelHandler.same_specialist = True
        policy = ModelPolicy({"main": ModelSelection("main-model"), "child": ModelSelection("specialist-model")},
                             {"project-manager": "main", "architecture": "child"}, default="child")
        for kind in ("deepagents", "fx"):
            ModelHandler.requests = []

            async def factory(config, selection, selected_kind=kind):
                if selected_kind == "fx":
                    return await FxRuntime.create(config, model=selection.model, base_url=self.base_url)
                model = ChatOpenAI(model=selection.model, base_url=self.base_url, api_key="test", use_responses_api=False)
                return DeepAgentsRuntime(config, model)

            team = ReadOnlyTeam(factory, policy, self.scenario["evidence"])
            try:
                await asyncio.wait_for(team.ask("Ask Orion for both analyses"), timeout=60)
                self.assertEqual({item["key"] for item in team.observations}, {"architecture", "second"})
                self.assertTrue(all(item["status"] == "completed" for item in team.observations))
                parent = json.dumps([r["messages"] for r in ModelHandler.requests if r["model"] == "main-model"])
                self.assertIn("Review the design", parent)
                self.assertIn("Inspect the second design", parent)
            finally:
                await team.close()

    def test_model_policy_validates_and_uses_host_task_tier(self):
        policy = ModelPolicy({"critical": ModelSelection("strong"), "routine": ModelSelection("cheap")},
                             {"project-manager": "critical"}, default="routine")
        self.assertEqual(policy.resolve("project-manager").model, "strong")
        self.assertEqual(policy.resolve("architecture").model, "cheap")
        self.assertEqual(policy.resolve("architecture", task_tier="critical").model, "strong")
        with self.assertRaises(ValueError):
            policy.resolve("architecture", task_tier="missing")

    async def test_fx_streams_and_accepts_steering_during_a_tool(self):
        started, release = asyncio.Event(), asyncio.Event()
        events = []

        async def read_evidence(arguments):
            started.set()
            await release.wait()
            return "Evidence read."

        async def observe(event):
            events.append(event)

        tool = RuntimeTool("read_evidence", "Read a document", {
            "type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"],
        }, read_evidence, idempotent=True, writes=False)
        runtime = await FxRuntime.create(AgentRuntimeConfig("architecture", "Review the evidence.", (tool,)),
                                         model="specialist-model", base_url=self.base_url)
        try:
            turn = asyncio.create_task(runtime.prompt("session1", "Read the design", on_event=observe))
            await asyncio.wait_for(started.wait(), timeout=30)
            steer = asyncio.create_task(runtime.steer("session1", "Consider self-hosted options only."))
            await asyncio.sleep(0.05)
            release.set()
            await asyncio.wait_for(steer, timeout=30)
            result = await asyncio.wait_for(turn, timeout=30)
            self.assertEqual(result.stop_reason, "end_turn")
            self.assertTrue(any(event.type == "text_delta" for event in events))
            self.assertTrue(any("self-hosted options only" in json.dumps(r["messages"]) for r in ModelHandler.requests))
        finally:
            release.set()
            await runtime.close()

    async def test_fx_local_sessions_survive_host_restart(self):
        async def read_evidence(arguments):
            return "Evidence read."

        tool = RuntimeTool("read_evidence", "Read a document", {
            "type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"],
        }, read_evidence, idempotent=True, writes=False)
        config = AgentRuntimeConfig("architecture", "Review the evidence.", (tool,))
        events = []

        async def observe(event):
            events.append(event)

        with tempfile.TemporaryDirectory() as directory:
            local_dir = Path(directory) / "sessions"
            runtime = await FxRuntime.create(config, model="specialist-model", base_url=self.base_url, local_dir=local_dir)
            try:
                session_id = await runtime.new_session()
                with self.assertRaisesRegex(ValueError, "new_session"):
                    await runtime.prompt("architecture", "First")
                result = await asyncio.wait_for(runtime.prompt(session_id, "First", message_id="first-turn", on_event=observe), 30)
                self.assertEqual(result.stop_reason, "end_turn")
                self.assertTrue(any(event.type == "turn_accepted" and event.message_id for event in events))
                requests_before = len(ModelHandler.requests)
                repeated = await asyncio.wait_for(runtime.prompt(session_id, "First", message_id="first-turn"), 30)
                self.assertTrue(repeated.repeated)
                self.assertEqual(repeated.text, result.text)
                self.assertEqual(len(ModelHandler.requests), requests_before)
            finally:
                await runtime.close()
            with self.assertRaisesRegex(ValueError, "different runtime configuration"):
                await FxRuntime.create(AgentRuntimeConfig("research", "Different agent.", (tool,)),
                                       model="specialist-model", base_url=self.base_url, local_dir=local_dir)
            runtime = await FxRuntime.create(config, model="specialist-model", base_url=self.base_url, local_dir=local_dir)
            try:
                requests_before = len(ModelHandler.requests)
                repeated = await asyncio.wait_for(runtime.prompt(session_id, "First", message_id="first-turn"), 30)
                self.assertTrue(repeated.repeated)
                self.assertEqual(repeated.text, result.text)
                self.assertEqual(len(ModelHandler.requests), requests_before)
                result = await asyncio.wait_for(runtime.prompt(session_id, "Follow-up"), 30)
                self.assertIn("User turns in context: 2", result.text)
            finally:
                await runtime.close()

    async def test_fx_resumes_a_stored_idempotent_tool_after_process_death(self):
        started, never_finish = asyncio.Event(), asyncio.Event()
        execution_ids = []

        async def scoped(arguments, context):
            execution_ids.append(context.execution_id)
            if len(execution_ids) == 1:
                started.set()
                await never_finish.wait()
            return "Evidence read."

        tool = RuntimeTool("read_evidence", "Read a document", {
            "type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"],
        }, idempotent=True, writes=True, execute_scoped=scoped)
        config = AgentRuntimeConfig("architecture", "Review the evidence.", (tool,))
        with tempfile.TemporaryDirectory() as directory:
            local_dir = Path(directory) / "sessions"
            runtime = await FxRuntime.create(config, model="specialist-model", base_url=self.base_url, local_dir=local_dir)
            session_id = await runtime.new_session()
            turn = asyncio.create_task(runtime.prompt(session_id, "Read the design"))
            try:
                await asyncio.wait_for(started.wait(), 30)
                runtime.process.kill()
                await runtime.process.wait()
                with self.assertRaises(RuntimeError):
                    await asyncio.wait_for(turn, 30)
            finally:
                await runtime.close()
            runtime = await FxRuntime.create(config, model="specialist-model", base_url=self.base_url, local_dir=local_dir)
            try:
                result = await asyncio.wait_for(runtime.resume(session_id), 30)
                self.assertEqual(result.stop_reason, "end_turn")
                self.assertGreaterEqual(len(execution_ids), 2, execution_ids)
                self.assertTrue(execution_ids[0])
                self.assertEqual(execution_ids[0], execution_ids[1])
            finally:
                await runtime.close()

    async def test_fx_does_not_auto_replay_ambiguous_non_idempotent_tool(self):
        ModelHandler.no_retry = True
        started, never_finish = asyncio.Event(), asyncio.Event()
        executions = []

        async def scoped(arguments, context):
            executions.append(context.execution_id)
            started.set()
            await never_finish.wait()

        tool = RuntimeTool("read_evidence", "A potentially non-idempotent operation", {
            "type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"],
        }, idempotent=False, writes=True, execute_scoped=scoped)
        config = AgentRuntimeConfig("architecture", "Review the evidence.", (tool,))
        with tempfile.TemporaryDirectory() as directory:
            local_dir = Path(directory) / "sessions"
            runtime = await FxRuntime.create(config, model="specialist-model", base_url=self.base_url, local_dir=local_dir)
            session_id = await runtime.new_session()
            turn = asyncio.create_task(runtime.prompt(session_id, "Read the design"))
            try:
                await asyncio.wait_for(started.wait(), 30)
                runtime.process.kill()
                await runtime.process.wait()
                with self.assertRaises(RuntimeError):
                    await asyncio.wait_for(turn, 30)
            finally:
                await runtime.close()
            runtime = await FxRuntime.create(config, model="specialist-model", base_url=self.base_url, local_dir=local_dir)
            try:
                result = await asyncio.wait_for(runtime.resume(session_id), 30)
                self.assertEqual(result.stop_reason, "end_turn")
                self.assertEqual(len(executions), 1)
                requests = json.dumps(ModelHandler.requests)
                self.assertTrue("interrupted" in requests.lower() or "may have" in requests.lower(), requests)
            finally:
                await runtime.close()

    async def test_tools_receive_their_session_identity_from_both_runtimes(self):
        for kind in ("deepagents", "fx"):
            seen = []

            async def scoped(arguments, context, collector=seen):
                collector.append(context)
                return "Scoped evidence"

            tool = RuntimeTool("read_evidence", "Read evidence", {
                "type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"],
            }, idempotent=True, writes=False, execute_scoped=scoped)
            config = AgentRuntimeConfig("architecture", "Read evidence.", (tool,))
            if kind == "fx":
                runtime = await FxRuntime.create(config, model="specialist-model", base_url=self.base_url)
            else:
                model = ChatOpenAI(model="specialist-model", base_url=self.base_url, api_key="test", use_responses_api=False)
                runtime = DeepAgentsRuntime(config, model)
            try:
                await asyncio.wait_for(runtime.prompt("session-a", "First"), 30)
                await asyncio.wait_for(runtime.prompt("session-b", "Second"), 30)
            finally:
                await runtime.close()
            self.assertEqual([context.session_id for context in seen], ["session-a", "session-b"])
            if kind == "fx":
                self.assertTrue(all(context.execution_id for context in seen))


if __name__ == "__main__":
    unittest.main()
