import unittest

from costs import compare, cost


class CostsTest(unittest.TestCase):
    prices = {"strong": {"input": 10, "output": 30, "cached_input": 1},
              "routine": {"input": 1, "output": 3, "cached_input": .1}}

    def sample(self, model):
        return {"runtime": "fx", "case_digest": "same-case", "model": "strong", "stopReason": "end_turn",
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
