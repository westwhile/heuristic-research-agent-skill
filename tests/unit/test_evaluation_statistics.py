"""Unit tests for the E5 comparison statistics (ADR-0006 decision 7):
exact McNemar, paired bootstrap, rare-event upper bound, and the trace
discipline that makes every result reproducible from its parameters."""

import json
import unittest
from decimal import Decimal
from pathlib import Path

from research_evolution.evaluation.statistics import (
    SMALL_SAMPLE_THRESHOLD,
    STATISTICAL_METHODS,
    StatisticResult,
    mcnemar_exact,
    paired_bootstrap,
    paired_permutation,
    rare_event_upper_bound,
    small_sample_limitation,
)

SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "schemas"
    / "core"
    / "comparison-report-v1.schema.json"
)

# Golden values computed once from the implementation and pinned here:
# re-deriving them from the traced parameters must reproduce them exactly
# (decision 7: "conclusions must be reproducible from traced parameters").
CHAMPION = [1, 0, 1, 1, 0, 1, 0, 1, 1, 0]
CHALLENGER = [0, 0, 1, 1, 1, 1, 0, 1, 0, 1]
BOOTSTRAP_GOLDEN = {"mean_difference": 0.0, "ci_low": -0.4, "ci_high": 0.4}
RARE_ZERO_GOLDEN = 0.13910834066826516
RARE_TWO_GOLDEN = 0.12061415542204407


class MethodEnumPinTest(unittest.TestCase):
    def test_methods_match_report_schema_enum(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        enum = set(
            schema["properties"]["methods"]["properties"]["statistics"]["items"][
                "enum"
            ]
        )
        self.assertEqual(enum, set(STATISTICAL_METHODS))

    def test_result_rejects_unknown_method(self) -> None:
        with self.assertRaises(ValueError):
            StatisticResult(method="t_test", parameters={}, estimates={})


class McNemarTest(unittest.TestCase):
    def test_known_exact_value(self) -> None:
        # 2 * (C(10,0) + C(10,1)) / 2**10 = 22 / 1024 exactly.
        result = mcnemar_exact(1, 9)
        self.assertEqual(result.estimates["p_value"], 0.021484375)
        self.assertEqual(result.estimates["discordant_pairs"], 10.0)
        self.assertEqual(
            result.parameters, {"champion_only": 1, "challenger_only": 9}
        )

    def test_symmetry_and_no_discordance(self) -> None:
        self.assertEqual(
            mcnemar_exact(1, 9).estimates, mcnemar_exact(9, 1).estimates
        )
        self.assertEqual(mcnemar_exact(0, 0).estimates["p_value"], 1.0)

    def test_validation(self) -> None:
        with self.assertRaises(ValueError):
            mcnemar_exact(-1, 2)
        with self.assertRaises(ValueError):
            mcnemar_exact(True, 2)
        with self.assertRaises(ValueError):
            mcnemar_exact(1.5, 2)


class PairedBootstrapTest(unittest.TestCase):
    def test_golden_pin_and_determinism(self) -> None:
        first = paired_bootstrap(CHAMPION, CHALLENGER, seed=42, resamples=2000)
        second = paired_bootstrap(CHAMPION, CHALLENGER, seed=42, resamples=2000)
        self.assertEqual(first, second)
        self.assertEqual(first.estimates, BOOTSTRAP_GOLDEN)
        self.assertEqual(
            first.parameters,
            {"n_cases": 10, "resamples": 2000, "confidence": 0.95, "seed": 42},
        )

    def test_interval_is_ordered(self) -> None:
        result = paired_bootstrap(CHAMPION, CHALLENGER, seed=7)
        self.assertLessEqual(
            result.estimates["ci_low"], result.estimates["ci_high"]
        )

    def test_seed_is_required_and_traced(self) -> None:
        with self.assertRaises(TypeError):
            paired_bootstrap(CHAMPION, CHALLENGER)  # type: ignore[call-arg]
        with self.assertRaises(ValueError):
            paired_bootstrap(CHAMPION, CHALLENGER, seed=True)

    def test_validation(self) -> None:
        with self.assertRaises(ValueError):
            paired_bootstrap([1.0], [1.0, 0.0], seed=1)
        with self.assertRaises(ValueError):
            paired_bootstrap([], [], seed=1)
        with self.assertRaises(ValueError):
            paired_bootstrap([float("nan")], [0.0], seed=1)
        with self.assertRaises(ValueError):
            paired_bootstrap([1], [0], seed=1, resamples=0)
        with self.assertRaises(ValueError):
            paired_bootstrap([1], [0], seed=1, confidence=1.0)


class PairedPermutationTest(unittest.TestCase):
    def test_exact_known_value_and_effect_size(self) -> None:
        result = paired_permutation([0.0, 0.0], [1.0, 1.0], seed=42)
        self.assertEqual(result.estimates["mean_difference"], 1.0)
        self.assertEqual(result.estimates["p_value"], 0.5)
        self.assertEqual(result.estimates["rank_biserial"], 1.0)
        self.assertEqual(result.parameters["mode"], "exact")
        self.assertEqual(result.parameters["n_pairs"], 2)

    def test_metrics_are_separate_calls(self) -> None:
        accuracy = paired_permutation([0.0, 0.0], [1.0, 1.0], seed=7)
        latency = paired_permutation([100.0, 110.0], [99.0, 109.0], seed=7)
        self.assertEqual(accuracy.parameters["n_pairs"], 2)
        self.assertEqual(latency.parameters["n_pairs"], 2)
        self.assertNotEqual(
            accuracy.estimates["mean_difference"],
            latency.estimates["mean_difference"],
        )

    def test_validation_and_seeded_monte_carlo(self) -> None:
        with self.assertRaises(ValueError):
            paired_permutation([], [], seed=1)
        with self.assertRaises(ValueError):
            paired_permutation([0.0], [1.0, 2.0], seed=1)
        first = paired_permutation(
            [0.0, 0.0],
            [1.0, -0.5],
            seed=9,
            resamples=100,
            exact_limit=0,
        )
        second = paired_permutation(
            [0.0, 0.0],
            [1.0, -0.5],
            seed=9,
            resamples=100,
            exact_limit=0,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.parameters["mode"], "monte_carlo")


class RareEventUpperBoundTest(unittest.TestCase):
    def test_zero_events_closed_form(self) -> None:
        result = rare_event_upper_bound(0, 20)
        self.assertEqual(result.estimates["upper_bound"], RARE_ZERO_GOLDEN)
        self.assertEqual(
            result.parameters, {"events": 0, "trials": 20, "confidence": 0.95}
        )

    def test_nonzero_events_bisection(self) -> None:
        result = rare_event_upper_bound(2, 50)
        self.assertEqual(result.estimates["upper_bound"], RARE_TWO_GOLDEN)

    def test_bound_decreases_with_more_trials(self) -> None:
        self.assertLess(
            rare_event_upper_bound(0, 100).estimates["upper_bound"],
            rare_event_upper_bound(0, 20).estimates["upper_bound"],
        )

    def test_validation(self) -> None:
        with self.assertRaises(ValueError):
            rare_event_upper_bound(3, 2)
        with self.assertRaises(ValueError):
            rare_event_upper_bound(0, 0)
        with self.assertRaises(ValueError):
            rare_event_upper_bound(0, 20, confidence=0.0)


class TraceDisciplineTest(unittest.TestCase):
    def test_parameters_sha256_is_stable_and_sensitive(self) -> None:
        first = paired_bootstrap(CHAMPION, CHALLENGER, seed=42, resamples=2000)
        same = paired_bootstrap(CHAMPION, CHALLENGER, seed=42, resamples=2000)
        other_seed = paired_bootstrap(CHAMPION, CHALLENGER, seed=43, resamples=2000)
        self.assertEqual(first.parameters_sha256, same.parameters_sha256)
        self.assertNotEqual(first.parameters_sha256, other_seed.parameters_sha256)
        self.assertEqual(len(first.parameters_sha256), 64)

    def test_trace_payload_shape(self) -> None:
        result = mcnemar_exact(1, 9)
        self.assertEqual(
            result.trace_payload(),
            {
                "method": "paired_exact_mcnemar",
                "parameters": {"champion_only": 1, "challenger_only": 9},
            },
        )


class SmallSampleDisciplineTest(unittest.TestCase):
    def test_limitation_sentence_below_threshold(self) -> None:
        sentence = small_sample_limitation(20)
        self.assertEqual(
            sentence,
            "Small paired sample (20 cases): no statistical significance "
            "is claimed for overall accuracy at this scale.",
        )

    def test_no_limitation_at_threshold(self) -> None:
        self.assertIsNone(small_sample_limitation(SMALL_SAMPLE_THRESHOLD))
        self.assertEqual(SMALL_SAMPLE_THRESHOLD, 30)


class DecimalInputTest(unittest.TestCase):
    """R34 regression: a run reloaded from a store carries Decimal score
    values (the strict parser's frozen numeric model) — the statistics
    layer must accept them."""

    def test_paired_bootstrap_accepts_decimal(self) -> None:
        decimal_result = paired_bootstrap(
            [Decimal("1"), Decimal("0"), Decimal("0.5")],
            [Decimal("0.25"), Decimal("0"), Decimal("1")],
            seed=99,
            resamples=200,
        )
        float_result = paired_bootstrap(
            [1, 0, 0.5], [0.25, 0, 1], seed=99, resamples=200
        )
        self.assertEqual(decimal_result.estimates, float_result.estimates)
        self.assertEqual(decimal_result.parameters, float_result.parameters)

    def test_paired_bootstrap_rejects_decimal_nan(self) -> None:
        with self.assertRaises(ValueError):
            paired_bootstrap([Decimal("NaN")], [0], seed=99, resamples=10)


if __name__ == "__main__":
    unittest.main()
