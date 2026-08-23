"""Phase 6 L3 multi-seed selection and failure-preservation tests."""

import ast
import dataclasses
import os
import tempfile
import unittest
from pathlib import Path

from research_evolution.adapters.deep_learning import DLRunManifest
from research_evolution.adapters.deep_learning.runner import run_fixture
from research_evolution.adapters.deep_learning.selection import (
    DLSelectionError,
    select_fixture_runs,
    selector_identity,
)
from research_evolution.core import load_strict_json

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"
MANIFEST_FIXTURE = FIXTURES / "dl-run-manifest" / "v1" / "valid" / "minimal.json"
SELECTION_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "research_evolution"
    / "adapters"
    / "deep_learning"
    / "selection.py"
)


def _manifest(run_id: str) -> DLRunManifest:
    payload = load_strict_json(MANIFEST_FIXTURE.read_bytes())
    payload["manifest_id"] = f"manifest-{run_id}"
    payload["run_id"] = run_id
    payload["runner"]["version"] = "0.2.0"
    payload["budget"].update(
        {"max_steps": 10, "max_epochs": 10, "max_flops": 0}
    )
    payload["checkpoint_policy"].update(
        {"retention": "best_and_last", "max_retained": 2}
    )
    return DLRunManifest.from_payload(payload)


def _fixture(seed: int, *, failure: str = "none") -> dict:
    return {
        "schema": "synthetic-dl-fixture/v2",
        "fixture_id": "tiny-regression-selection",
        "features": [[-1.0], [0.0], [1.0], [2.0]],
        "targets": [-1.0, 1.0, 3.0, 5.0],
        "validation_features": [[-0.5], [0.5], [1.5]],
        "validation_targets": [0.0, 2.0, 4.0],
        "hidden_units": 3,
        "learning_rate": 0.05,
        "requested_steps": 6,
        "seed": seed,
        "failure_injection": {
            "kind": failure,
            "at_step": 1 if failure != "none" else 0,
        },
        "early_stopping": {
            "enabled": False,
            "patience": 0,
            "min_delta": 0,
            "warmup_steps": 0,
        },
    }


def _plan(*, minimum: int = 2) -> dict:
    return {
        "schema": "synthetic-dl-selection-plan/v1",
        "selection_id": "dl-selection-study-001",
        "study_id": "synthetic-dl-study-001",
        "case_sha256": "1" * 64,
        "metric": "validation_loss",
        "direction": "minimize",
        "expected_runs": [
            {"run_id": "dl-seed-1", "seed": 1},
            {"run_id": "dl-seed-2", "seed": 2},
            {"run_id": "dl-seed-3", "seed": 3},
            {"run_id": "dl-seed-4", "seed": 4},
        ],
        "minimum_successful_runs": minimum,
    }


def _results():
    return [
        run_fixture(_manifest("dl-seed-1"), _fixture(1)),
        run_fixture(_manifest("dl-seed-2"), _fixture(2)),
        run_fixture(_manifest("dl-seed-3"), _fixture(3, failure="nan")),
    ]


class DLSelectionInterfaceTest(unittest.TestCase):
    def test_identity_and_deterministic_canonical_result(self) -> None:
        self.assertEqual(
            selector_identity(),
            {"name": "reference-dl-selector", "version": "0.1.0"},
        )
        results = _results()
        first = select_fixture_runs(results, _plan())
        second = select_fixture_runs(results, _plan())
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(
            first.sha256,
            "14aaaab9382783017fca520e03bcfd4d6de113fd75a9a7850230067ab51f7f04",
        )
        self.assertEqual(first.status, "completed")
        self.assertIsNotNone(first.selected_checkpoint)

    def test_failed_and_missing_seeds_remain_explicit(self) -> None:
        artifact = select_fixture_runs(_results(), _plan()).artifact
        self.assertEqual(
            artifact["counts"],
            {
                "expected": 4,
                "observed": 3,
                "successful": 2,
                "failed": 1,
                "missing": 1,
                "minimum_successful_runs": 2,
            },
        )
        by_run = {record["run_id"]: record for record in artifact["runs"]}
        self.assertEqual(by_run["dl-seed-3"]["status"], "failed")
        self.assertFalse(by_run["dl-seed-3"]["eligible"])
        self.assertEqual(by_run["dl-seed-4"]["status"], "missing")
        self.assertEqual(
            by_run["dl-seed-4"]["ineligibility_reason"],
            "expected-run-missing",
        )

    def test_aggregate_reports_mean_variance_and_observed_range(self) -> None:
        aggregate = select_fixture_runs(_results(), _plan()).artifact["aggregate"]
        self.assertEqual(aggregate["count"], 2)
        self.assertIn("mean", aggregate)
        self.assertIn("variance", aggregate)
        self.assertEqual(len(aggregate["observed_range"]), 2)
        self.assertLessEqual(
            aggregate["observed_range"][0], aggregate["observed_range"][1]
        )

    def test_minimum_successful_gate_blocks_best_only_selection(self) -> None:
        result = select_fixture_runs(_results(), _plan(minimum=3))
        self.assertEqual(result.status, "insufficient_successful_runs")
        self.assertIsNone(result.selected_checkpoint)
        self.assertIsNone(result.artifact["selected_run"])

    def test_budget_exhausted_seed_is_not_eligible(self) -> None:
        manifest_payload = _manifest("dl-seed-1").payload
        manifest_payload["budget"]["max_steps"] = 1
        manifest_payload["budget"]["max_epochs"] = 0
        exhausted = run_fixture(
            DLRunManifest.from_payload(manifest_payload), _fixture(1)
        )
        successful = run_fixture(_manifest("dl-seed-2"), _fixture(2))
        result = select_fixture_runs([exhausted, successful], _plan())
        by_run = {
            record["run_id"]: record for record in result.artifact["runs"]
        }
        self.assertEqual(result.status, "insufficient_successful_runs")
        self.assertEqual(by_run["dl-seed-1"]["status"], "budget_exhausted")
        self.assertEqual(
            by_run["dl-seed-1"]["ineligibility_reason"],
            "terminal-status-budget_exhausted",
        )

    def test_result_is_frozen_and_defensive(self) -> None:
        result = select_fixture_runs(_results(), _plan())
        before = result.sha256
        artifact = result.artifact
        artifact["runs"][0]["eligible"] = False
        self.assertEqual(result.sha256, before)
        self.assertTrue(result.artifact["runs"][0]["eligible"])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result._artifact_bytes = b"{}"

    def test_no_filesystem_side_effects(self) -> None:
        results = _results()
        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                select_fixture_runs(results, _plan())
                leftovers = list(Path(temp).rglob("*"))
            finally:
                os.chdir(previous)
        self.assertEqual(leftovers, [])

    def test_dependency_surface_is_standard_library_and_runner_result_only(
        self,
    ) -> None:
        tree = ast.parse(SELECTION_SOURCE.read_text(encoding="utf-8"))
        absolute_imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        from_imports = {
            (node.level, node.module)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertEqual(absolute_imports, {"hashlib", "math", "statistics"})
        self.assertEqual(
            from_imports,
            {
                (0, "__future__"),
                (0, "dataclasses"),
                (0, "decimal"),
                (0, "typing"),
                (0, "research_evolution.core"),
                (1, "runner"),
            },
        )


class DLSelectionInputGateTest(unittest.TestCase):
    def test_plan_requires_unique_preregistered_multi_seed_set(self) -> None:
        plan = _plan()
        plan["expected_runs"][1]["seed"] = 1
        with self.assertRaisesRegex(DLSelectionError, "must be unique"):
            select_fixture_runs([], plan)

        plan = _plan()
        plan["expected_runs"] = plan["expected_runs"][:1]
        plan["minimum_successful_runs"] = 1
        with self.assertRaisesRegex(DLSelectionError, "2..64"):
            select_fixture_runs([], plan)

    def test_unexpected_duplicate_and_wrong_seed_results_fail_closed(self) -> None:
        result = run_fixture(_manifest("dl-seed-1"), _fixture(1))
        with self.assertRaisesRegex(DLSelectionError, "duplicate"):
            select_fixture_runs([result, result], _plan())

        unexpected = run_fixture(_manifest("dl-unexpected"), _fixture(9))
        with self.assertRaisesRegex(DLSelectionError, "not preregistered"):
            select_fixture_runs([unexpected], _plan())

        wrong_seed = run_fixture(_manifest("dl-seed-1"), _fixture(9))
        with self.assertRaisesRegex(DLSelectionError, "seed does not match"):
            select_fixture_runs([wrong_seed], _plan())

    def test_legacy_result_and_wrong_binding_fail_closed(self) -> None:
        legacy_payload = load_strict_json(MANIFEST_FIXTURE.read_bytes())
        legacy = run_fixture(
            DLRunManifest.from_payload(legacy_payload),
            {
                "schema": "synthetic-dl-fixture/v1",
                "fixture_id": "legacy",
                "features": [[0.0]],
                "targets": [0.0],
                "hidden_units": 1,
                "learning_rate": 0.1,
                "requested_steps": 1,
                "seed": 0,
                "failure_injection": {"kind": "none", "at_step": 0},
            },
        )
        with self.assertRaisesRegex(DLSelectionError, "0.2 result"):
            select_fixture_runs([legacy], _plan())

        wrong_plan = _plan()
        wrong_plan["study_id"] = "different-study"
        with self.assertRaisesRegex(DLSelectionError, "study_id"):
            select_fixture_runs(_results(), wrong_plan)


if __name__ == "__main__":
    unittest.main()
