"""Unit and integration tests for the deterministic synthetic ML runner."""

import copy
import hashlib
import re
import unittest
from pathlib import Path
from unittest import mock

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
    split_sha = canonical_sha256(split_projection)
    case["dataset"] = {
        "identity": f"{case['case_id']}-dataset",
        "sha256": dataset_sha,
        "description": "Small deterministic synthetic numeric fixture.",
    }
    case["split"] = {
        "identity": f"{case['case_id']}-split",
        "sha256": split_sha,
        "input_sha256": dataset_sha,
        "kind": "iid",
        "parameters": {},
    }
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


class SyntheticMLRunnerTest(unittest.TestCase):
    def test_identity_and_hash_bound_evidence(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        result = run_synthetic_experiment(dataset, case, final_partition="test")
        self.assertEqual(
            runner_identity(), {"tool": "synthetic-ml-runner", "version": "0.1.0"}
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
        first = run_synthetic_experiment(dataset, case, final_partition="test")
        second = run_synthetic_experiment(dataset, case, final_partition="test")
        self.assertEqual(first, second)
        mutated = first.artifact
        mutated["seeds"].append(999)
        self.assertNotIn(999, first.artifact["seeds"])

    def test_runner_performs_no_hidden_schema_file_reads(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        with mock.patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("runner attempted filesystem I/O"),
        ):
            result = run_synthetic_experiment(dataset, case, final_partition="test")
        self.assertEqual(result.evidence["data_provenance"], "synthetic")

    def test_seed_aggregation_and_parity_are_explicit(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        artifact = run_synthetic_experiment(
            dataset, case, final_partition="test"
        ).artifact
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
        for side in ("candidate", "baseline"):
            for metric in ("accuracy", "f1"):
                summary = artifact["aggregates"][side][metric]
                self.assertEqual(set(summary), {"mean", "variance", "observed_range"})

    def test_regression_reference_path(self) -> None:
        dataset = _regression_dataset()
        case = _runner_case(dataset, regression=True)
        artifact = run_synthetic_experiment(
            dataset, case, final_partition="test"
        ).artifact
        self.assertEqual(
            set(artifact["aggregates"]["candidate"]),
            {"mean_squared_error", "mean_absolute_error"},
        )

    def test_runner_evidence_flows_through_validate_claim(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        result = run_synthetic_experiment(dataset, case, final_partition="test")
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
            run_synthetic_experiment(tampered, case, final_partition="test")
        self.assertIn("dataset payload hash", str(ctx.exception))
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(dataset, case, final_partition="validation")
        self.assertIn("final-evaluation-not-protected", str(ctx.exception))
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(dataset, case, final_partition=[])
        self.assertIn("partition-name string", str(ctx.exception))

    def test_duplicate_seeds_and_unsupported_metric_fail_closed(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        case["selection"]["seed_set"] = [3, 3]
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(dataset, case, final_partition="test")
        self.assertIn("unique seeds", str(ctx.exception))
        case = _runner_case(dataset)
        case["metrics"] = ["auc"]
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(dataset, case, final_partition="test")
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
