"""Phase 6 L2 runner interface, budget, and failure-state tests."""

import ast
import copy
import dataclasses
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from research_evolution.adapters.deep_learning import DLRunManifest
from research_evolution.adapters.deep_learning.runner import (
    DLRunnerError,
    run_fixture,
    runner_identity,
)
from research_evolution.core import load_strict_json

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"
MANIFEST_FIXTURE = FIXTURES / "dl-run-manifest" / "v1" / "valid" / "minimal.json"
FULL_MANIFEST_FIXTURE = FIXTURES / "dl-run-manifest" / "v1" / "valid" / "full.json"
RUNNER_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "research_evolution"
    / "adapters"
    / "deep_learning"
    / "runner.py"
)


def _manifest_payload() -> dict:
    return load_strict_json(MANIFEST_FIXTURE.read_bytes())


def _manifest(*, mode: str = "cpu_fixture", budget: dict | None = None) -> DLRunManifest:
    payload = _manifest_payload()
    payload["execution_mode"] = mode
    if budget:
        payload["budget"].update(budget)
    return DLRunManifest.from_payload(payload)


def _fixture(*, failure: str = "none", at_step: int = 0) -> dict:
    return {
        "schema": "synthetic-dl-fixture/v1",
        "fixture_id": "tiny-regression-001",
        "features": [[-1.0], [0.0], [1.0], [2.0]],
        "targets": [-1.0, 1.0, 3.0, 5.0],
        "hidden_units": 3,
        "learning_rate": 0.05,
        "requested_steps": 8,
        "seed": 7,
        "failure_injection": {"kind": failure, "at_step": at_step},
    }


class DLRunnerInterfaceTest(unittest.TestCase):
    def test_identity_matches_manifest_contract(self) -> None:
        self.assertEqual(
            runner_identity(), {"name": "reference-dl-runner", "version": "0.2.0"}
        )

    def test_cpu_fixture_result_is_deterministic_and_golden_pinned(self) -> None:
        first = run_fixture(_manifest(), _fixture())
        second = run_fixture(_manifest(), _fixture())
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(
            first.sha256,
            "33304445f2dd9413858818639f72a0540f36aedb78b4e18ac3dd1173d10609b3",
        )
        self.assertEqual(first.status, "completed")
        self.assertEqual(first.failure_class, "none")
        self.assertEqual(first.evidence_scope, "synthetic_engineering")
        self.assertEqual(
            first.artifact["metrics"],
            {
                "initial_mean_squared_error": Decimal("9.023769409672"),
                "final_mean_squared_error": Decimal("5.716990630316"),
            },
        )

    def test_result_is_frozen_and_returns_defensive_copies(self) -> None:
        result = run_fixture(_manifest(), _fixture())
        before = result.sha256
        returned = result.artifact
        returned["status"] = "failed"
        returned["budget_ledger"]["consumed"]["steps"] = 99
        self.assertEqual(result.sha256, before)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.budget_ledger["consumed"]["steps"], 8)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result._artifact_bytes = b"{}"

    def test_input_mutation_after_run_does_not_change_result(self) -> None:
        manifest_payload = _manifest_payload()
        fixture = _fixture()
        result = run_fixture(DLRunManifest.from_payload(manifest_payload), fixture)
        before = result.sha256
        manifest_payload["budget"]["max_steps"] = 1
        fixture["features"][0][0] = 999.0
        self.assertEqual(result.sha256, before)

    def test_runner_has_no_filesystem_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                run_fixture(_manifest(), _fixture())
                leftovers = list(Path(temp).rglob("*"))
            finally:
                os.chdir(previous)
        self.assertEqual(leftovers, [])

    def test_dependency_surface_excludes_frameworks_and_system_io(self) -> None:
        tree = ast.parse(RUNNER_SOURCE.read_text(encoding="utf-8"))
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
        self.assertEqual(absolute_imports, {"hashlib", "math"})
        self.assertEqual(
            from_imports,
            {
                (0, "__future__"),
                (0, "dataclasses"),
                (0, "decimal"),
                (0, "typing"),
                (0, "research_evolution.core"),
                (1, "manifest"),
            },
        )


class DLRunnerInputGateTest(unittest.TestCase):
    def assert_runner_error(self, manifest, fixture, text: str) -> None:
        with self.assertRaises(DLRunnerError) as ctx:
            run_fixture(manifest, fixture)
        self.assertIn(text, str(ctx.exception))

    def test_requires_manifest_type(self) -> None:
        self.assert_runner_error({}, _fixture(), "DLRunManifest")

    def test_runner_name_and_version_must_match(self) -> None:
        for field, value in (("name", "foreign-runner"), ("version", "9.9.9")):
            with self.subTest(field=field):
                payload = _manifest_payload()
                payload["runner"][field] = value
                self.assert_runner_error(
                    DLRunManifest.from_payload(payload), _fixture(), f"runner.{field}"
                )

    def test_checkpoint_resume_is_fail_closed_until_l3(self) -> None:
        manifest = DLRunManifest.from_payload(
            load_strict_json(FULL_MANIFEST_FIXTURE.read_bytes())
        )
        self.assert_runner_error(manifest, _fixture(), "requires runner 0.2.0")

    def test_gpu_modes_are_fail_closed(self) -> None:
        payload = load_strict_json(FULL_MANIFEST_FIXTURE.read_bytes())
        payload["checkpoint_policy"]["resume"] = {"mode": "fresh"}
        manifest = DLRunManifest.from_payload(payload)
        self.assert_runner_error(manifest, _fixture(), "dry_run and cpu_fixture")

    def test_fixture_requires_exact_fields_and_schema(self) -> None:
        extra = _fixture()
        extra["unexpected"] = True
        self.assert_runner_error(_manifest(), extra, "fields must be exactly")

        wrong_schema = _fixture()
        wrong_schema["schema"] = "synthetic-dl-fixture/v2"
        self.assert_runner_error(_manifest(), wrong_schema, "fixture.schema")

    def test_fixture_shape_and_numeric_bounds(self) -> None:
        probes = (
            (lambda value: value.update(features=[]), "features must contain"),
            (lambda value: value.update(targets=[1.0]), "one value per feature"),
            (
                lambda value: value.update(features=[[0.0], [0.0, 1.0], [1.0], [2.0]]),
                "same width",
            ),
            (lambda value: value.update(hidden_units=0), "hidden_units"),
            (lambda value: value.update(requested_steps=101), "requested_steps"),
            (lambda value: value.update(seed=-1), "seed"),
            (lambda value: value.update(learning_rate=0), "learning_rate"),
            (
                lambda value: value.update(features=[[2_000_000.0], [0.0], [1.0], [2.0]]),
                "oversized",
            ),
        )
        for mutate, expected in probes:
            with self.subTest(expected=expected):
                fixture = _fixture()
                mutate(fixture)
                self.assert_runner_error(_manifest(), fixture, expected)

    def test_failure_injection_declaration_is_fail_closed(self) -> None:
        bad_kind = _fixture()
        bad_kind["failure_injection"] = {"kind": "power_loss", "at_step": 2}
        self.assert_runner_error(_manifest(), bad_kind, "kind must be one of")

        none_at_step = _fixture()
        none_at_step["failure_injection"]["at_step"] = 1
        self.assert_runner_error(_manifest(), none_at_step, "must be zero")

        outside = _fixture(failure="oom", at_step=9)
        self.assert_runner_error(_manifest(), outside, "requested step range")

    def test_cost_only_budget_is_not_silently_treated_as_enforced(self) -> None:
        manifest = _manifest(
            budget={"max_steps": 0, "max_epochs": 0, "max_flops": 0}
        )
        self.assert_runner_error(manifest, _fixture(), "requires a positive step")


class DLRunnerBudgetAndFailureTest(unittest.TestCase):
    def test_dry_run_executes_no_training_and_consumes_nothing(self) -> None:
        result = run_fixture(_manifest(mode="dry_run"), _fixture())
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.evidence_scope, "configuration_only")
        self.assertEqual(result.artifact["metrics"], {})
        self.assertEqual(
            result.budget_ledger["consumed"],
            {"samples": 0, "steps": 0, "epochs": 0, "tokens": 0, "flops_proxy": 0},
        )
        self.assertEqual(result.artifact["execution"]["hardware"], "declared_not_observed")
        self.assertEqual(result.artifact["execution"]["framework"], "not_loaded")

    def test_dry_run_predicts_budget_failure_without_consumption(self) -> None:
        result = run_fixture(_manifest(mode="dry_run", budget={"max_steps": 2}), _fixture())
        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual(result.failure_class, "budget_exhausted")
        self.assertEqual(result.budget_ledger["consumed"]["steps"], 0)
        self.assertEqual(result.budget_ledger["exhausted_dimension"], "max_steps")

    def test_cpu_fixture_records_manifest_bound_budget_ledger(self) -> None:
        manifest = _manifest()
        result = run_fixture(manifest, _fixture())
        ledger = result.budget_ledger
        self.assertEqual(result.artifact["manifest_sha256"], manifest.sha256)
        self.assertEqual(
            ledger["consumed"],
            {"samples": 4, "steps": 8, "epochs": 8, "tokens": 0, "flops_proxy": 1344},
        )
        self.assertEqual(ledger["accounting"], "cumulative_no_double_charge")
        self.assertIsNone(ledger["prior_consumption_sha256"])
        self.assertEqual(ledger["cost_observation"], "not_observed")
        self.assertLess(
            result.artifact["metrics"]["final_mean_squared_error"],
            result.artifact["metrics"]["initial_mean_squared_error"],
        )

    def test_each_enforceable_budget_cap_can_stop_execution(self) -> None:
        probes = (
            ({"max_samples": 3}, "max_samples", 0),
            ({"max_steps": 2}, "max_steps", 2),
            ({"max_epochs": 2}, "max_epochs", 2),
            ({"max_flops": 200}, "max_flops", 1),
        )
        for budget, dimension, steps in probes:
            with self.subTest(dimension=dimension):
                result = run_fixture(_manifest(budget=budget), _fixture())
                self.assertEqual(result.status, "budget_exhausted")
                self.assertEqual(result.failure_class, "budget_exhausted")
                self.assertEqual(result.budget_ledger["exhausted_dimension"], dimension)
                self.assertEqual(result.budget_ledger["consumed"]["steps"], steps)

    def test_equal_budget_caps_have_stable_priority(self) -> None:
        result = run_fixture(
            _manifest(budget={"max_steps": 2, "max_epochs": 2}), _fixture()
        )
        self.assertEqual(result.budget_ledger["exhausted_dimension"], "max_steps")

    def test_synthetic_failures_are_terminal_and_preserve_prior_consumption(self) -> None:
        probes = (
            ("nan", "numerical_failure"),
            ("interrupt", "interrupted"),
            ("oom", "resource_exhausted"),
        )
        for kind, expected_class in probes:
            with self.subTest(kind=kind):
                result = run_fixture(_manifest(), _fixture(failure=kind, at_step=3))
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.failure_class, expected_class)
                self.assertTrue(result.artifact["failure"]["synthetic_injection"])
                self.assertEqual(result.artifact["failure"]["at_step"], 3)
                self.assertEqual(result.budget_ledger["consumed"]["steps"], 2)
                self.assertTrue(
                    any("injected" in item for item in result.artifact["limitations"])
                )

    def test_natural_non_finite_state_is_a_non_injected_failure(self) -> None:
        fixture = _fixture()
        fixture.update(
            {
                "features": [[1_000_000.0], [-1_000_000.0]],
                "targets": [1_000_000.0, -1_000_000.0],
                "hidden_units": 8,
                "learning_rate": 1.0,
            }
        )
        result = run_fixture(_manifest(), fixture)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_class, "numerical_failure")
        self.assertEqual(result.artifact["failure"]["code"], "non-finite-training-state")
        self.assertFalse(result.artifact["failure"]["synthetic_injection"])
        self.assertEqual(result.budget_ledger["consumed"]["steps"], 0)

    def test_failure_beyond_budget_is_not_misreported_as_observed(self) -> None:
        result = run_fixture(
            _manifest(budget={"max_steps": 2}),
            _fixture(failure="oom", at_step=5),
        )
        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual(result.failure_class, "budget_exhausted")
        self.assertFalse(result.artifact["failure"]["synthetic_injection"])

    def test_dry_run_does_not_trigger_declared_failure_injection(self) -> None:
        result = run_fixture(
            _manifest(mode="dry_run"), _fixture(failure="nan", at_step=1)
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.failure_class, "none")


if __name__ == "__main__":
    unittest.main()
