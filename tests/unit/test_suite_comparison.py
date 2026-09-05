"""Correctness Reset CR5: suite-level paired comparison contracts."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from research_evolution.core import canonical_sha256, load_record
from research_evolution.evaluation.statistics import paired_permutation
from research_evolution.evaluation import (
    ComparePolicy,
    MetricPolicy,
    SuiteComparePolicy,
    compare,
    compare_suite,
    render_html,
    render_json,
    render_markdown,
)

GENERATED_AT = "2026-08-25T00:00:00Z"


def _case_ref(case_id: str) -> dict[str, str]:
    return {"evaluation_case_id": case_id, "sha256": canonical_sha256({"case": case_id})}


def _suite() -> dict:
    return {
        "schema": "suite/v1",
        "suite_id": "suite-cr5",
        "title": "CR5 paired-observation suite",
        "cases": [_case_ref("case-a"), _case_ref("case-b")],
        "frozen_at": GENERATED_AT,
    }


def _run(
    *,
    candidate_id: str,
    case_id: str,
    seed: int,
    accuracy: float,
    latency: float,
) -> dict:
    suite = _suite()
    candidate_sha = canonical_sha256({"candidate": candidate_id})
    envelope_sha = canonical_sha256({"seed": seed, "frozen": "same"})
    return {
        "schema": "evaluation-run/v1",
        "evaluation_run_id": f"{candidate_id}-{case_id}-{seed}",
        "case": _case_ref(case_id),
        "suite": {
            "suite_id": suite["suite_id"],
            "sha256": canonical_sha256(suite),
        },
        "candidate": {"candidate_id": candidate_id, "sha256": candidate_sha},
        "envelope": {"envelope_sha256": envelope_sha, "seed": seed},
        "runner": {"tool": "runner", "version": "1"},
        "environment": {"class": "frozen"},
        "output": {"output_sha256": canonical_sha256({"output": candidate_id})},
        "scorer": {"level": "oracle", "tool": "oracle", "version": "1"},
        "score_vector": [
            {"dimension": "accuracy", "value": accuracy, "unit": "ratio"},
            {"dimension": "latency", "value": latency, "unit": "ms"},
        ],
        "gate_results": [{"gate": "integrity", "result": "pass"}],
        "verdict": "pass",
        "levels_covered": ["L0", "L1"],
        "generated_at": GENERATED_AT,
    }


def _runs(candidate_id: str, offset: float) -> list[dict]:
    return [
        _run(
            candidate_id=candidate_id,
            case_id=case_id,
            seed=seed,
            accuracy=0.70 + offset + case_index * 0.05,
            latency=100.0 - offset * 10 + seed,
        )
        for case_index, case_id in enumerate(("case-a", "case-b"))
        for seed in (7, 11)
    ]


def _candidate(candidate_id: str) -> dict[str, str]:
    return {
        "candidate_id": candidate_id,
        "sha256": canonical_sha256({"candidate": candidate_id}),
    }


class SuiteComparisonObservationUnitTest(unittest.TestCase):
    def _report(self) -> dict:
        return compare_suite(
            suite=_suite(),
            champion_candidate=_candidate("champion"),
            challenger_candidate=_candidate("challenger"),
            champion_runs=_runs("champion", 0.0),
            challenger_runs=_runs("challenger", 0.1),
            policy=SuiteComparePolicy(
                seed=20260825,
                expected_seeds=(7, 11),
                minimum_pairs=30,
                metrics=(
                    MetricPolicy("accuracy", direction="higher", role="primary", rope=0.01),
                    MetricPolicy(
                        "latency",
                        direction="lower",
                        role="guardrail",
                        rope=1.0,
                        noninferiority_margin=5.0,
                    ),
                ),
            ),
            comparison_id="suite-comparison-cr5",
            title="Champion vs challenger",
            conclusion="Synthetic engineering comparison only.",
            generated_at=GENERATED_AT,
        )

    def test_each_metric_uses_case_seed_envelope_pairs_not_dimensions(self) -> None:
        report = self._report()

        self.assertEqual(load_record(json.dumps(report)).schema_id, "suite-comparison/v1")
        self.assertEqual(report["observation_unit"], "case_seed_frozen_envelope")
        self.assertEqual(len(report["pairs"]), 4)
        self.assertEqual(
            {item["dimension"]: item["n_pairs"] for item in report["metrics"]},
            {"accuracy": 4, "latency": 4},
        )
        self.assertTrue(
            all(item["inference_status"] == "insufficient_pairs" for item in report["metrics"])
        )

    def test_three_report_forms_surface_paired_statistical_provenance(self) -> None:
        report = self._report()
        self.assertEqual(load_record(render_json(report)).schema_id, "suite-comparison/v1")
        for rendered in (render_markdown(report), render_html(report)):
            self.assertIn("case_seed_frozen_envelope", rendered)
            self.assertIn("accuracy", rendered)
            self.assertIn("insufficient_pairs", rendered)
            self.assertIn("rank_biserial", rendered)

    def test_candidate_digest_drift_is_rejected_before_statistics(self) -> None:
        original = _runs
        for side in ("champion", "challenger"):
            for mutation in ("one_hash", "all_hashes", "one_id", "missing_hash"):
                with self.subTest(side=side, mutation=mutation):
                    def mutated_runs(candidate_id: str, offset: float) -> list[dict]:
                        runs = original(candidate_id, offset)
                        if candidate_id == side:
                            if mutation == "one_hash":
                                runs[0]["candidate"]["sha256"] = "a" * 64
                            elif mutation == "all_hashes":
                                for run in runs:
                                    run["candidate"]["sha256"] = "a" * 64
                            elif mutation == "one_id":
                                runs[0]["candidate"]["candidate_id"] = "different"
                            else:
                                del runs[0]["candidate"]["sha256"]
                        return runs

                    with (
                        patch(f"{__name__}._runs", side_effect=mutated_runs),
                        patch(
                            "research_evolution.evaluation.suite_comparison.paired_permutation",
                            wraps=paired_permutation,
                        ) as statistics,
                        self.assertRaises(ValueError),
                    ):
                        self._report()
                    statistics.assert_not_called()

    def test_report_reference_must_match_every_observation(self) -> None:
        original = _candidate
        for side in ("champion", "challenger"):
            with self.subTest(side=side):
                def changed_reference(candidate_id: str) -> dict[str, str]:
                    reference = original(candidate_id)
                    if candidate_id == side:
                        reference["sha256"] = "f" * 64
                    return reference

                with (
                    patch(f"{__name__}._candidate", side_effect=changed_reference),
                    self.assertRaisesRegex(ValueError, "candidate"),
                ):
                    self._report()

    def test_legacy_per_run_compare_fails_closed(self) -> None:
        champion = _runs("champion", 0.0)[0]
        challenger = _runs("challenger", 0.1)[0]
        with self.assertRaisesRegex(ValueError, "metric dimensions are not observations"):
            compare(
                champion=champion,
                challenger=challenger,
                policy=ComparePolicy(seed=1),
                report_id="legacy",
                title="legacy",
                conclusion="legacy",
                generated_at=GENERATED_AT,
            )

    def test_same_candidate_bytes_under_different_names_are_rejected(self) -> None:
        champion_runs = _runs("champion", 0.0)
        challenger_runs = _runs("challenger", 0.1)
        champion_candidate = _candidate("champion")
        challenger_candidate = _candidate("challenger")
        challenger_candidate["sha256"] = champion_candidate["sha256"]
        for run in challenger_runs:
            run["candidate"]["sha256"] = champion_candidate["sha256"]
        with self.assertRaisesRegex(ValueError, "same candidate artifact"):
            compare_suite(
                suite=_suite(),
                champion_candidate=champion_candidate,
                challenger_candidate=challenger_candidate,
                champion_runs=champion_runs,
                challenger_runs=challenger_runs,
                policy=SuiteComparePolicy(
                    seed=1,
                    expected_seeds=(7, 11),
                    metrics=(MetricPolicy("accuracy", "higher", "primary", 0.01),),
                ),
                comparison_id="same-bytes",
                title="same bytes",
                conclusion="must fail",
                generated_at=GENERATED_AT,
            )

    def test_metric_unit_drift_across_observations_is_rejected(self) -> None:
        champion_runs = _runs("champion", 0.0)
        challenger_runs = _runs("challenger", 0.1)
        for run in champion_runs + challenger_runs:
            run["score_vector"] = [run["score_vector"][0]]
        champion_runs[0]["score_vector"][0].pop("unit")
        challenger_runs[0]["score_vector"][0].pop("unit")
        with self.assertRaisesRegex(ValueError, "metric unit drift"):
            compare_suite(
                suite=_suite(),
                champion_candidate=_candidate("champion"),
                challenger_candidate=_candidate("challenger"),
                champion_runs=champion_runs,
                challenger_runs=challenger_runs,
                policy=SuiteComparePolicy(
                    seed=1,
                    expected_seeds=(7, 11),
                    metrics=(MetricPolicy("accuracy", "higher", "primary", 0.01),),
                ),
                comparison_id="unit-drift",
                title="unit drift",
                conclusion="must fail",
                generated_at=GENERATED_AT,
            )


if __name__ == "__main__":
    unittest.main()
