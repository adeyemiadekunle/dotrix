"""Price two saved, matching evaluation runs using a supplied per-million token rate card.

These are usage-based price estimates, not provider invoices or a quality score.
Missing usage or prices makes the comparison incomplete rather than free.
"""
import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path


def cost(row, prices):
    usage, rate = row.get("usage"), prices.get(row.get("model"))
    if not usage or not rate:
        return None
    required = ("input_tokens", "output_tokens")
    if any(type(usage.get(key)) is not int or usage[key] < 0 for key in required):
        return None
    cached = usage.get("cached_input_tokens", 0)
    if type(cached) is not int or not 0 <= cached <= usage["input_tokens"]:
        return None
    try:
        rates = {key: Decimal(str(rate[key])) for key in ("input", "output")}
        rates["cached_input"] = Decimal(str(rate["cached_input"])) if cached else rates["input"]
        if any(not value.is_finite() or value < 0 for value in rates.values()):
            return None
    except (KeyError, InvalidOperation):
        return None
    return ((usage["input_tokens"] - cached) * rates["input"] + cached * rates["cached_input"]
            + usage["output_tokens"] * rates["output"]) / 1_000_000


def summarize(run, prices):
    rows = list(run["turns"].values()) if "turns" in run else [run, *run.get("specialists", [])]
    costs = [cost(row, prices) for row in rows]
    complete = bool(rows) and all(value is not None for value in costs)
    completed = all(row.get("stopReason", "end_turn") == "end_turn" and row.get("status", "completed") == "completed"
                    for row in rows)
    return {"calls_or_turns": len(rows), "usage_and_prices_complete": complete, "completed": completed,
            "estimated_cost": str(sum(costs)) if complete else None,
            "models": sorted({row["model"] for row in rows if row.get("model")})}


def compare(baseline, routed, prices):
    if len(baseline) != len(routed) or not baseline:
        raise ValueError("Provide matching nonempty baseline and routed evaluation lists")
    results = []
    for before, after in zip(baseline, routed, strict=True):
        if (not before.get("case_digest") or any(before.get(key) != after.get(key)
                for key in ("runtime", "case_digest", "mode"))):
            raise ValueError("Comparisons need the same runtime, mode, and scenario content")
        left, right = summarize(before, prices), summarize(after, prices)
        valid = all(item["usage_and_prices_complete"] and item["completed"] for item in (left, right))
        difference = Decimal(left["estimated_cost"]) - Decimal(right["estimated_cost"]) if valid else None
        results.append({"runtime": before["runtime"], "baseline": left, "routed": right,
                        "estimated_savings": str(difference) if difference is not None else None,
                        "quality_review_required": True})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("routed", type=Path)
    parser.add_argument("prices", type=Path, help="JSON model → input/output/cached_input rates per million tokens, in one currency")
    args = parser.parse_args()
    print(json.dumps(compare(json.loads(args.baseline.read_text()), json.loads(args.routed.read_text()),
                             json.loads(args.prices.read_text())), indent=2))


if __name__ == "__main__":
    main()
