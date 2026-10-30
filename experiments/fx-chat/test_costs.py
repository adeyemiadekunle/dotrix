import unittest

from costs import compare, cost


class CostsTest(unittest.TestCase):
    prices = {"strong": {"input": 10, "output": 30, "cached_input": 1},
              "routine": {"input": 1, "output": 3, "cached_input": .1}}

    @staticmethod
    def sample(model):
        return {"runtime": "fx", "mode": "live-delegation", "specialist_observations_complete": True, "case_digest": "same-case", "model": "strong", "stopReason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 50}, "specialists": [
                    {"model": model, "status": "completed", "usage": {"input_tokens": 100, "output_tokens": 50}}]}

    def test_includes_parent_and_children(self):
        report = compare([self.sample("strong")], [self.sample("routine")], self.prices)[0]
        self.assertEqual(report["baseline"]["estimated_cost"], "0.0050")
        self.assertEqual(report["routed"]["estimated_cost"], "0.00275")
        self.assertEqual(report["estimated_savings"], "0.00225")
        self.assertTrue(report["quality_review_required"])

    def test_missing_usage_is_unknown(self):
        routed = self.sample("routine")
        routed["specialists"][0]["usage"] = None
        self.assertIsNone(compare([self.sample("strong")], [routed], self.prices)[0]["estimated_savings"])

    def test_missing_specialist_status_cannot_claim_savings(self):
        routed = self.sample("routine")
        del routed["specialists"][0]["status"]
        self.assertIsNone(compare([self.sample("strong")], [routed], self.prices)[0]["estimated_savings"])

    def test_legacy_delegation_logs_have_unproven_coverage(self):
        routed = self.sample("routine")
        del routed["specialist_observations_complete"]
        self.assertIsNone(compare([self.sample("strong")], [routed], self.prices)[0]["estimated_savings"])

    def test_cache_prices_and_invalid_counts(self):
        row = {"model": "strong", "usage": {"input_tokens": 100, "output_tokens": 0, "cached_input_tokens": 100}}
        self.assertEqual(str(cost(row, self.prices)), "0.0001")
        row["usage"]["cached_input_tokens"] = 101
        self.assertIsNone(cost(row, self.prices))
        self.assertIsNone(cost({"model": "missing", "usage": {"input_tokens": 1, "output_tokens": 1}}, self.prices))

    def test_mismatched_task_or_failed_work_cannot_claim_savings(self):
        routed = self.sample("routine")
        routed["case_digest"] = "different"
        with self.assertRaises(ValueError):
            compare([self.sample("strong")], [routed], self.prices)
        routed = self.sample("routine")
        routed["specialists"][0]["status"] = "partial"
        self.assertIsNone(compare([self.sample("strong")], [routed], self.prices)[0]["estimated_savings"])


class DelegationFailuresTest(unittest.IsolatedAsyncioTestCase):
    async def test_failed_attempt_and_blocked_dependency_cannot_disappear_from_costs(self):
        from team import ReadOnlyTeam

        from dotrix_engine.runtimes import ModelPolicy, ModelSelection

        for fail_during_creation in (False, True):
            with self.subTest(fail_during_creation=fail_during_creation):
                prompts = []

                class FailingRuntime:
                    async def prompt(self, agent, prompt, _prompts=prompts):
                        _prompts.append(agent)
                        raise RuntimeError("Provider refused the specialist")

                    async def close(self):
                        pass

                async def factory(config, selection, _fail=fail_during_creation):
                    if _fail:
                        raise RuntimeError("Could not create the specialist runtime")
                    return FailingRuntime()

                policy = ModelPolicy({"routine": ModelSelection("routine")}, {}, "routine")
                team = ReadOnlyTeam(factory, policy, {"project.md": "Evidence"})
                try:
                    result = await team._delegate({"tasks": [
                        {"key": "design", "agent": "architecture", "brief": "Design auth", "expected_result": "Design"},
                        {"key": "review", "agent": "reviewer", "brief": "Review auth", "expected_result": "Review",
                         "depends_on": ["design"]},
                    ]})
                    self.assertEqual([row["status"] for row in team.observations], ["failed", "blocked"])
                    self.assertEqual([row["key"] for row in team.observations], ["design", "review"])
                    self.assertEqual([row["attempted"] for row in team.observations], [not fail_during_creation, False])
                    self.assertTrue(all(row["usage"] is None for row in team.observations))
                    self.assertEqual(prompts, [] if fail_during_creation else ["architecture"])
                    self.assertTrue(all(task["result"]["status"] == "blocked" for task in result["tasks"]))
                    baseline, routed = CostsTest.sample("strong"), CostsTest.sample("routine")
                    routed["specialists"] = team.observations
                    report = compare([baseline], [routed], CostsTest.prices)[0]
                    self.assertFalse(report["routed"]["completed"])
                    self.assertFalse(report["routed"]["usage_and_prices_complete"])
                    self.assertIsNone(report["estimated_savings"])
                finally:
                    await team.close()
