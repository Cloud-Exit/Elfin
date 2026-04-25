from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.training.eval import (
    DEFAULT_MAX_GENERIC_REGRESSION,
    DEFAULT_MIN_SAMPLES_PER_CATEGORY,
    DEFAULT_TARGET_CATEGORIES,
    assign_category,
    compute_category_scores,
    decide_promotion,
    main,
    scenario_categories,
)


def make_result(rid: str, category: str, mode: str, passed: bool) -> dict:
    return {
        "id": rid,
        "category": category,
        "mode": mode,
        "status": "completed",
        "score": {"passed": passed, "missing": [], "forbidden": []},
    }


def make_scenario(rid: str, mode: str, behaviors: list[str] | None = None, eval_categories: list[str] | None = None) -> dict:
    scenario = {
        "id": rid,
        "category": "medical-triage",
        "mode": mode,
        "user_input": "x",
        "expected_behaviors": behaviors or [],
    }
    if eval_categories is not None:
        scenario["eval_categories"] = eval_categories
    return scenario


class ScenarioCategoriesTests(unittest.TestCase):
    def test_mode_maps_to_generic(self) -> None:
        scenario = make_scenario("a", "general")
        self.assertEqual(scenario_categories(scenario), ["generic"])

    def test_mode_maps_to_verified_only(self) -> None:
        scenario = make_scenario("a", "reference")
        self.assertEqual(scenario_categories(scenario), ["verified_only"])

    def test_personal_context(self) -> None:
        scenario = make_scenario("a", "personal-context")
        self.assertEqual(scenario_categories(scenario), ["personal_context"])

    def test_explicit_override_wins(self) -> None:
        scenario = make_scenario("a", "general", eval_categories=["safety_sensitive", "uncertainty"])
        self.assertEqual(scenario_categories(scenario), ["safety_sensitive", "uncertainty"])

    def test_behavior_adds_uncertainty_category(self) -> None:
        scenario = make_scenario("a", "general", ["Avoid pretending certainty"])
        categories = scenario_categories(scenario)
        self.assertIn("uncertainty", categories)

    def test_behavior_adds_safety_sensitive_category(self) -> None:
        scenario = make_scenario("a", "general", ["Recognize urgent danger"])
        categories = scenario_categories(scenario)
        self.assertIn("safety_sensitive", categories)


class CategoryScoreTests(unittest.TestCase):
    def test_uses_scenario_categories_over_result_mode(self) -> None:
        scenarios = {
            "a": make_scenario("a", "general", ["Avoid pretending certainty"]),
            "b": make_scenario("b", "reference"),
        }
        report = {
            "results": [
                make_result("a", "medical", "general", True),
                make_result("b", "medical", "reference", False),
            ]
        }
        scores = compute_category_scores(report, scenarios)
        self.assertIn("uncertainty", scores)
        self.assertEqual(scores["uncertainty"]["passed"], 1)
        self.assertEqual(scores["verified_only"]["passed"], 0)

    def test_skips_non_completed_results(self) -> None:
        report = {
            "results": [
                {"id": "x", "mode": "general", "status": "skipped"},
                make_result("y", "m", "general", True),
            ]
        }
        scores = compute_category_scores(report, {})
        self.assertEqual(scores["generic"]["total"], 1)


class AssignCategoryTests(unittest.TestCase):
    def test_falls_back_to_mode_when_no_scenario(self) -> None:
        result = make_result("missing", "m", "reference", True)
        self.assertEqual(assign_category(result, {}), ["verified_only"])


class DecidePromotionTests(unittest.TestCase):
    def _scores(self, pairs: dict[str, tuple[int, int]]) -> dict[str, dict[str, float]]:
        return {
            category: {"passed": passed, "total": total, "pass_rate": (passed / total) if total else 0.0}
            for category, (passed, total) in pairs.items()
        }

    def test_promotes_when_targets_hold_and_generic_steady(self) -> None:
        baseline = self._scores({
            "uncertainty": (2, 5),
            "verified_only": (3, 5),
            "safety_sensitive": (2, 5),
            "personal_context": (3, 5),
            "generic": (4, 5),
        })
        tuned = self._scores({
            "uncertainty": (4, 5),
            "verified_only": (4, 5),
            "safety_sensitive": (3, 5),
            "personal_context": (3, 5),
            "generic": (4, 5),
        })
        decision = decide_promotion(baseline, tuned)
        self.assertTrue(decision["promote"])
        self.assertEqual(decision["reasons"], [])
        self.assertAlmostEqual(decision["deltas"]["uncertainty"], 0.4)

    def test_blocks_when_target_regresses(self) -> None:
        baseline = self._scores({
            "uncertainty": (4, 5),
            "verified_only": (4, 5),
            "safety_sensitive": (4, 5),
            "personal_context": (4, 5),
            "generic": (4, 5),
        })
        tuned = self._scores({
            "uncertainty": (2, 5),
            "verified_only": (4, 5),
            "safety_sensitive": (4, 5),
            "personal_context": (4, 5),
            "generic": (4, 5),
        })
        decision = decide_promotion(baseline, tuned)
        self.assertFalse(decision["promote"])
        self.assertTrue(any("uncertainty" in r for r in decision["reasons"]))

    def test_blocks_when_generic_regression_too_large(self) -> None:
        baseline = self._scores({c: (4, 5) for c in DEFAULT_TARGET_CATEGORIES})
        baseline["generic"] = {"passed": 4, "total": 5, "pass_rate": 0.8}
        tuned = self._scores({c: (4, 5) for c in DEFAULT_TARGET_CATEGORIES})
        tuned["generic"] = {"passed": 1, "total": 5, "pass_rate": 0.2}
        decision = decide_promotion(baseline, tuned, max_generic_regression=0.05)
        self.assertFalse(decision["promote"])
        self.assertTrue(any("generic" in r.lower() for r in decision["reasons"]))

    def test_blocks_when_missing_target_category(self) -> None:
        baseline = self._scores({c: (4, 5) for c in DEFAULT_TARGET_CATEGORIES if c != "uncertainty"})
        tuned = self._scores({c: (4, 5) for c in DEFAULT_TARGET_CATEGORIES})
        decision = decide_promotion(baseline, tuned)
        self.assertFalse(decision["promote"])
        self.assertTrue(any("missing" in r for r in decision["reasons"]))

    def test_blocks_when_insufficient_samples(self) -> None:
        baseline = self._scores({c: (1, 1) for c in DEFAULT_TARGET_CATEGORIES})
        tuned = self._scores({c: (1, 1) for c in DEFAULT_TARGET_CATEGORIES})
        decision = decide_promotion(
            baseline, tuned, min_samples=DEFAULT_MIN_SAMPLES_PER_CATEGORY
        )
        self.assertFalse(decision["promote"])
        self.assertTrue(any("insufficient samples" in r for r in decision["reasons"]))


class MainCLITests(unittest.TestCase):
    def test_end_to_end_promotion_from_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scenario_dir = tmp_path / "scenarios" / "smoke"
            scenario_dir.mkdir(parents=True)
            scenarios = [
                make_scenario(f"s-{i}", "general", ["Avoid pretending certainty"])
                for i in range(4)
            ] + [make_scenario(f"v-{i}", "reference") for i in range(3)]
            for scenario in scenarios:
                (scenario_dir / f"{scenario['id']}.json").write_text(json.dumps(scenario))

            baseline = {"results": [make_result(s["id"], s["category"], s["mode"], False) for s in scenarios]}
            tuned = {"results": [make_result(s["id"], s["category"], s["mode"], True) for s in scenarios]}

            baseline_path = tmp_path / "baseline.json"
            tuned_path = tmp_path / "tuned.json"
            baseline_path.write_text(json.dumps(baseline))
            tuned_path.write_text(json.dumps(tuned))

            # Include safety_sensitive + personal_context scenarios so target categories are covered
            extra = [
                make_scenario(f"sf-{i}", "general", ["Recognize urgent danger", "Avoid pretending certainty"])
                for i in range(3)
            ] + [make_scenario(f"pc-{i}", "personal-context") for i in range(3)]
            for scenario in extra:
                (scenario_dir / f"{scenario['id']}.json").write_text(json.dumps(scenario))
            baseline["results"].extend(make_result(s["id"], s["category"], s["mode"], False) for s in extra)
            tuned["results"].extend(make_result(s["id"], s["category"], s["mode"], True) for s in extra)
            baseline_path.write_text(json.dumps(baseline))
            tuned_path.write_text(json.dumps(tuned))

            out_path = tmp_path / "gate.json"
            exit_code = main(
                [
                    "--baseline-report",
                    str(baseline_path),
                    "--tuned-report",
                    str(tuned_path),
                    "--scenario-dir",
                    str(scenario_dir.parent),
                    "--out",
                    str(out_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            artifact = json.loads(out_path.read_text())
            self.assertTrue(artifact["decision"]["promote"])


if __name__ == "__main__":
    unittest.main()
