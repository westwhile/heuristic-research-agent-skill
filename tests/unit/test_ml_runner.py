"""Unit and integration tests for the deterministic synthetic ML runner."""

import copy
import hashlib
import re
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from research_evolution.adapters import EvaluationContract
from research_evolution.adapters.ml import MLAdapter
from research_evolution.adapters.ml.runner import (
    SyntheticRunnerError,
    run_synthetic_experiment,
    runner_identity,
)
from research_evolution.core import canonical_sha256, load_strict_json

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"
RUNNER_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "research_evolution"
    / "adapters"
    / "ml"
    / "runner.py"
)


def _fixture(family: str, name: str) -> dict:
    return load_strict_json(
        (FIXTURES / family / "v1" / "valid" / name).read_bytes()
    )


def _classification_dataset() -> dict:
    return {
        "task_type": "binary_classification",
        "features": [
            [-2.0, -1.0],
            [-1.5, -0.5],
            [-1.0, -1.5],
            [-0.5, -1.0],
            [0.5, 0.5],
            [1.0, 0.5],
            [1.5, 1.0],
            [-1.2, -0.8],
            [2.0, 1.5],
            [-2.0, -1.5],
            [1.2, 0.8],
            [-0.8, -1.2],
        ],
        "targets": [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0],
        "partitions": {
            "train": [0, 1, 2, 3, 4, 5],
            "validation": [6, 7],
            "test": [8, 9, 10, 11],
        },
    }


def _regression_dataset() -> dict:
    return {
        "task_type": "regression",
        "features": [[float(value)] for value in range(12)],
        "targets": [1.0 + 2.0 * value for value in range(12)],
        "partitions": {
            "train": [0, 1, 2, 3, 4, 5],
            "validation": [6, 7],
            "test": [8, 9, 10, 11],
        },
    }


def _runner_case(dataset: dict, *, regression: bool = False) -> dict:
    case = copy.deepcopy(_fixture("ml-case", "minimal.json"))
    case["case_id"] = "ml-runner-regression" if regression else "ml-runner-classification"
    case["study_id"] = "synthetic-runner-study"
    case["gates"] = ["engineering", "generalization"]
    data_projection = {
        "task_type": dataset["task_type"],
        "features": dataset["features"],
        "targets": dataset["targets"],
    }
    split_projection = {"partitions": dataset["partitions"]}
    dataset_sha = canonical_sha256(data_projection)
    assignment_sha = canonical_sha256(split_projection)
    case["dataset"] = {
        "identity": f"{case['case_id']}-dataset",
        "sha256": dataset_sha,
        "description": "Small deterministic synthetic numeric fixture.",
    }
    split_core = {
        "identity": f"{case['case_id']}-split",
        "input_sha256": dataset_sha,
        "kind": "iid",
        "parameters": {"assignment_sha256": assignment_sha},
    }
    split_sha = canonical_sha256(split_core)
    case["split"] = {"sha256": split_sha, **split_core}
    case["model"] = {
        "family": "ridge-regression" if regression else "logistic-regression",
        "hyperparameters": {"learning_rate": 0.01 if regression else 0.1, "l2": 0.01},
    }
    case["metrics"] = (
        ["mean_squared_error", "mean_absolute_error"]
        if regression
        else ["accuracy", "f1"]
    )
    case["tuning"] = {
        "search_space": {},
        "split_used": "validation",
        "seed_count": 3,
    }
    selection_core = {
        "input_sha256": split_sha,
        "split_used": "validation",
        "metric": case["metrics"][0],
        "search_budget": {"epochs": 20, "sample_limit": 6},
        "seed_set": [3, 5, 7],
    }
    case["selection"] = {
        "identity": f"{case['case_id']}-selection",
        "sha256": canonical_sha256(selection_core),
        **selection_core,
    }
    return case


def _run(dataset: dict, case: dict, *, final_partition: str = "test"):
    return run_synthetic_experiment(
        dataset,
        case,
        contract=MLAdapter().build_evaluation_contract(case),
        final_partition=final_partition,
    )


def _repin_selection(case: dict) -> None:
    selection = case["selection"]
    selection["sha256"] = canonical_sha256(
        {
            "input_sha256": selection["input_sha256"],
            "split_used": selection["split_used"],
            "metric": selection["metric"],
            "search_budget": selection["search_budget"],
            "seed_set": selection["seed_set"],
        }
    )


class SyntheticMLRunnerTest(unittest.TestCase):
    def test_split_declaration_and_assignment_pins_are_distinct(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        assignment_sha = case["split"]["parameters"]["assignment_sha256"]
        self.assertNotEqual(case["split"]["sha256"], assignment_sha)
        result = run_synthetic_experiment(
            dataset,
            case,
            contract=MLAdapter().build_evaluation_contract(case),
            final_partition="test",
        )
        self.assertEqual(result.artifact["partition_assignment_sha256"], assignment_sha)

    def test_runner_rejects_a_stale_split_declaration_pin(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        case["split"]["parameters"]["unexpected"] = True
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("split declaration hash", str(ctx.exception))

    def test_runner_rejects_a_stale_selection_declaration_pin(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        case["selection"]["search_budget"]["epochs"] = 21
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("selection declaration hash", str(ctx.exception))

    def test_runner_rejects_contract_from_another_case(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        foreign_case = copy.deepcopy(case)
        foreign_case["case_id"] = "ml-runner-foreign-case"
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                foreign_case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("contract case_sha256", str(ctx.exception))

    def test_hand_built_contract_cannot_bypass_the_complete_case_shape(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        contract_payload = MLAdapter().build_evaluation_contract(case).payload
        del case["assessment"]
        contract_payload["case_sha256"] = canonical_sha256(case)
        contract = EvaluationContract.from_payload(contract_payload)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("case fields must be exactly", str(ctx.exception))

    def test_hand_built_contract_cannot_leak_a_nested_case_key_error(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        contract_payload = MLAdapter().build_evaluation_contract(case).payload
        del case["split"]["identity"]
        contract_payload["case_sha256"] = canonical_sha256(case)
        contract = EvaluationContract.from_payload(contract_payload)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("case.split fields must be exactly", str(ctx.exception))

    def test_hand_built_contract_cannot_bypass_protected_tuning_split(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        contract_payload = MLAdapter().build_evaluation_contract(case).payload
        case["tuning"]["split_used"] = "test"
        contract_payload["case_sha256"] = canonical_sha256(case)
        contract = EvaluationContract.from_payload(contract_payload)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("protected tuning partition", str(ctx.exception))

    def test_runner_fails_closed_on_unimplemented_split_families(self) -> None:
        dataset = _classification_dataset()
        for kind, parameters in (
            ("group", {"group_key": "site"}),
            ("time_series", {"gap": "999 sessions", "embargo": "999 sessions"}),
            ("nested", {"outer_folds": 5, "inner_folds": 3}),
        ):
            with self.subTest(kind=kind):
                case = _runner_case(dataset)
                case["split"]["kind"] = kind
                case["split"]["parameters"] = parameters
                contract = MLAdapter().build_evaluation_contract(case)
                with self.assertRaises(SyntheticRunnerError) as ctx:
                    run_synthetic_experiment(
                        dataset,
                        case,
                        contract=contract,
                        final_partition="test",
                    )
                self.assertIn("only executes iid splits", str(ctx.exception))

    def test_runner_rejects_declared_preprocessing_it_does_not_execute(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        case["preprocessing"] = [
            {
                "identity": "runner-standardizer",
                "sha256": "e" * 64,
                "input_sha256": case["split"]["sha256"],
                "operation": "standard-scaler",
                "fit_scope": "train_only",
            }
        ]
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("does not execute preprocessing", str(ctx.exception))

    def test_runner_rejects_declared_sampling_it_does_not_execute(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        case["sampling"] = [
            {
                "identity": "runner-sampler",
                "sha256": "d" * 64,
                "input_sha256": case["split"]["sha256"],
                "method": "random-oversampling",
                "scope": "train_only",
            }
        ]
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("does not execute sampling", str(ctx.exception))

    def test_runner_rejects_declared_feature_transforms_it_does_not_execute(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        case["feature"]["selection_scope"] = "per_fold"
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("does not execute feature selection", str(ctx.exception))

    def test_runner_rejects_declared_target_encoding_it_does_not_execute(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        case["feature"]["target_encoding_scope"] = "per_fold"
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("does not execute target encoding", str(ctx.exception))

    def test_runner_rejects_hyperparameter_search_it_does_not_execute(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        case["tuning"]["search_space"] = {"l2": [0.0, 0.01]}
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("does not execute hyperparameter search", str(ctx.exception))

    def test_runner_requires_tuning_seed_count_to_match_the_executed_seed_set(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        case["tuning"]["seed_count"] = 2
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("tuning.seed_count", str(ctx.exception))

    def test_runner_requires_selection_metric_in_the_executed_metric_set(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        case["selection"]["metric"] = "roc_auc"
        _repin_selection(case)
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("selection.metric", str(ctx.exception))

    def test_numeric_instability_uses_the_runner_error_surface(self) -> None:
        dataset = _regression_dataset()
        case = _runner_case(dataset, regression=True)
        case["model"]["hyperparameters"]["learning_rate"] = 1e308
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("numeric instability", str(ctx.exception))

    def test_oversized_numeric_input_uses_the_runner_error_surface(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        dataset["features"][0][0] = 10**5000
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("cannot be represented as a finite float", str(ctx.exception))

    def test_identity_and_hash_bound_evidence(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        result = _run(dataset, case)
        self.assertEqual(
            runner_identity(), {"tool": "synthetic-ml-runner", "version": "0.2.0"}
        )
        self.assertEqual(result.artifact["runner"], runner_identity())
        self.assertEqual(result.evidence["schema"], "ml-evidence/v2")
        self.assertEqual(result.evidence["content_sha256"], result.artifact_sha256)
        self.assertEqual(
            hashlib.sha256(result._artifact_bytes).hexdigest(), result.artifact_sha256
        )

    def test_run_is_deterministic_and_result_accessors_are_isolated(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        first = _run(dataset, case)
        second = _run(dataset, case)
        self.assertEqual(first, second)
        mutated = first.artifact
        mutated["seeds"].append(999)
        self.assertNotIn(999, first.artifact["seeds"])

    def test_runner_performs_no_hidden_schema_file_reads(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        contract = MLAdapter().build_evaluation_contract(case)
        with mock.patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("runner attempted filesystem I/O"),
        ):
            result = run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertEqual(result.evidence["data_provenance"], "synthetic")

    def test_seed_aggregation_and_parity_are_explicit(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        artifact = _run(dataset, case).artifact
        self.assertEqual(artifact["seeds"], [3, 5, 7])
        self.assertEqual(len(artifact["per_seed"]), 3)
        self.assertEqual(artifact["parity"]["changed_axes"], ["model"])
        self.assertTrue(artifact["parity"]["resource_parity"])
        self.assertEqual(artifact["parity"]["frozen_axes"]["heuristics"], [])
        for entry in artifact["per_seed"]:
            self.assertEqual(
                entry["resource_usage"]["candidate"],
                entry["resource_usage"]["baseline"],
            )
            self.assertEqual(entry["resource_usage"]["candidate"]["sample_visits"], 120)
        for side in ("candidate", "baseline"):
            for metric in ("accuracy", "f1"):
                summary = artifact["aggregates"][side][metric]
                self.assertEqual(set(summary), {"mean", "variance", "observed_range"})
        self.assertEqual(
            artifact["aggregates"]["candidate"]["accuracy"]["mean"], 1
        )
        self.assertEqual(
            artifact["aggregates"]["baseline"]["accuracy"]["mean"],
            Decimal("0.5"),
        )
        self.assertEqual(artifact["parity"]["candidate_minus_baseline"]["f1"], 1)

    def test_regression_reference_path(self) -> None:
        dataset = _regression_dataset()
        case = _runner_case(dataset, regression=True)
        artifact = _run(dataset, case).artifact
        self.assertEqual(
            set(artifact["aggregates"]["candidate"]),
            {"mean_squared_error", "mean_absolute_error"},
        )
        self.assertEqual(
            artifact["aggregates"]["candidate"]["mean_absolute_error"]["mean"],
            Decimal("0.460061361464"),
        )
        self.assertEqual(
            artifact["aggregates"]["baseline"]["mean_squared_error"]["mean"],
            Decimal("254.612953587242"),
        )

    def test_runner_evidence_flows_through_validate_claim(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        result = _run(dataset, case)
        claim = copy.deepcopy(_fixture("ml-claim", "full.json"))
        claim["study_id"] = case["study_id"]
        claim["case_sha256"] = canonical_sha256(case)
        contract = MLAdapter().build_evaluation_contract(case)
        assessment = MLAdapter().validate_claim(claim, [result.evidence], contract)
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertIn("synthetic-evidence-cap", assessment.triggered_rules)

    def test_hash_mismatch_and_unsafe_final_partition_fail_closed(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        tampered = copy.deepcopy(dataset)
        tampered["features"][0][0] = 999.0
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(tampered, case)
        self.assertIn("dataset payload hash", str(ctx.exception))
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case, final_partition="validation")
        self.assertIn("final-evaluation-not-protected", str(ctx.exception))
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case, final_partition=[])
        self.assertIn("partition-name string", str(ctx.exception))

    def test_duplicate_seeds_and_unsupported_metric_fail_closed(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        case["selection"]["seed_set"] = [3, 3]
        _repin_selection(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn("unique seeds", str(ctx.exception))
        case = _runner_case(dataset)
        case["metrics"] = ["auc"]
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn("unsupported metrics", str(ctx.exception))


class SyntheticMLRunnerStaticDisciplineTest(unittest.TestCase):
    def test_runner_has_no_io_clock_process_or_third_party_imports(self) -> None:
        source = RUNNER_SOURCE.read_text(encoding="utf-8")
        banned_imports = re.compile(
            r"^\s*(?:import|from)\s+"
            r"(?:os|pathlib|time|datetime|socket|urllib|requests|httpx|http|ssl|"
            r"subprocess|ctypes|asyncio|numpy|pandas|sklearn|scipy)\b",
            re.MULTILINE,
        )
        self.assertIsNone(banned_imports.search(source))
        for call in ("open(", "Path(", "getenv(", "environ["):
            with self.subTest(call=call):
                self.assertNotIn(call, source)


if __name__ == "__main__":
    unittest.main()
