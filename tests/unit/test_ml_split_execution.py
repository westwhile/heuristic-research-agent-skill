"""L5 executable split contracts tested through the public runner seam."""

import copy
import unittest

from research_evolution.adapters import EvaluationContract
from research_evolution.adapters.ml import MLAdapter
from research_evolution.adapters.ml.runner import (
    SyntheticRunnerError,
    run_synthetic_experiment,
)
from research_evolution.core import canonical_sha256
from tests.unit.test_ml_runner import (
    _classification_dataset,
    _repin_selection,
    _runner_case,
)


def _repin_split(case: dict) -> None:
    split = case["split"]
    split["sha256"] = canonical_sha256(
        {
            "identity": split["identity"],
            "input_sha256": split["input_sha256"],
            "kind": split["kind"],
            "parameters": split["parameters"],
        }
    )
    case["selection"]["input_sha256"] = split["sha256"]
    _repin_selection(case)


def _run(dataset: dict, case: dict):
    return run_synthetic_experiment(
        dataset,
        case,
        contract=MLAdapter().build_evaluation_contract(case),
        final_partition="test",
    )


def _group_payload() -> tuple[dict, dict]:
    dataset = _classification_dataset()
    dataset["split_context"] = {
        "group_labels": [
            "a",
            "a",
            "b",
            "b",
            "c",
            "c",
            "d",
            "d",
            "e",
            "e",
            "f",
            "f",
        ]
    }
    case = _runner_case(dataset)
    case["split"]["kind"] = "group"
    case["split"]["parameters"] = {
        "group_key": "site",
        "assignment_sha256": canonical_sha256(
            {"partitions": dataset["partitions"]}
        ),
        "context_sha256": canonical_sha256(dataset["split_context"]),
    }
    _repin_split(case)
    return dataset, case


def _time_series_payload() -> tuple[dict, dict]:
    dataset = {
        "task_type": "binary_classification",
        "features": [[float((index % 4) - 2)] for index in range(16)],
        "targets": [float((index % 4) >= 2) for index in range(16)],
        "partitions": {
            "train": [0, 1, 2, 3, 4, 5],
            "validation": [8, 9],
            "test": [12, 13, 14, 15],
        },
        "split_context": {
            "timestamps": list(range(16)),
            "excluded_indices": [6, 7, 10, 11],
        },
    }
    case = _runner_case(dataset)
    case["split"]["kind"] = "time_series"
    case["split"]["parameters"] = {
        "gap": "2 sessions",
        "embargo": "2 sessions",
        "assignment_sha256": canonical_sha256(
            {"partitions": dataset["partitions"]}
        ),
        "context_sha256": canonical_sha256(dataset["split_context"]),
    }
    _repin_split(case)
    return dataset, case


def _time_series_payload_with_early_future() -> tuple[dict, dict]:
    dataset = {
        "task_type": "binary_classification",
        "features": [[float((index % 4) - 2)] for index in range(16)],
        "targets": [float((index % 4) >= 2) for index in range(16)],
        "partitions": {
            "future_holdout": [0, 1],
            "train": [2, 3, 4, 5, 6, 7],
            "validation": [10, 11],
            "test": [14, 15],
        },
        "split_context": {
            "timestamps": list(range(16)),
            "excluded_indices": [8, 9, 12, 13],
        },
    }
    case = _runner_case(dataset)
    case["split"]["kind"] = "time_series"
    case["split"]["parameters"] = {
        "gap": "2 sessions",
        "embargo": "2 sessions",
        "assignment_sha256": canonical_sha256(
            {"partitions": dataset["partitions"]}
        ),
        "context_sha256": canonical_sha256(dataset["split_context"]),
    }
    _repin_split(case)
    return dataset, case


def _nested_payload() -> tuple[dict, dict]:
    dataset = _classification_dataset()
    dataset["split_context"] = {
        "outer_folds": [
            {
                "train": [0, 1, 2, 3],
                "validation": [4, 5, 6, 7],
                "inner_folds": [
                    {"train": [0, 1], "validation": [2, 3]},
                    {"train": [2, 3], "validation": [0, 1]},
                ],
            },
            {
                "train": [4, 5, 6, 7],
                "validation": [0, 1, 2, 3],
                "inner_folds": [
                    {"train": [4, 5], "validation": [6, 7]},
                    {"train": [6, 7], "validation": [4, 5]},
                ],
            },
        ]
    }
    case = _runner_case(dataset)
    case["split"]["kind"] = "nested"
    case["split"]["parameters"] = {
        "outer_folds": 2,
        "inner_folds": 2,
        "assignment_sha256": canonical_sha256(
            {"partitions": dataset["partitions"]}
        ),
        "context_sha256": canonical_sha256(dataset["split_context"]),
    }
    _repin_split(case)
    return dataset, case


class IIDSplitExecutionTest(unittest.TestCase):
    def test_iid_parameters_must_only_carry_the_assignment_pin(self) -> None:
        dataset = _classification_dataset()
        case = _runner_case(dataset)
        case["split"]["parameters"]["unused"] = True
        _repin_split(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn("iid parameters must contain exactly", str(ctx.exception))

    def test_iid_partitions_must_assign_every_row(self) -> None:
        dataset = _classification_dataset()
        dataset["partitions"]["test"].remove(11)
        case = _runner_case(dataset)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn("partitions must assign every row exactly once", str(ctx.exception))


class GroupSplitExecutionTest(unittest.TestCase):
    def test_group_labels_are_executably_isolated_by_partition(self) -> None:
        dataset, case = _group_payload()
        result = _run(dataset, case)
        self.assertEqual(
            result.artifact["split_validation"],
            {"kind": "group", "group_count": 6, "group_key": "site"},
        )

    def test_group_reused_across_partitions_is_rejected(self) -> None:
        dataset, case = _group_payload()
        dataset["split_context"]["group_labels"][8] = "a"
        case["split"]["parameters"]["context_sha256"] = canonical_sha256(
            dataset["split_context"]
        )
        _repin_split(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn("group label appears in both", str(ctx.exception))

    def test_hand_built_contract_cannot_bypass_group_key_type(self) -> None:
        dataset, case = _group_payload()
        contract_payload = MLAdapter().build_evaluation_contract(case).payload
        case["split"]["parameters"]["group_key"] = False
        _repin_split(case)
        contract_payload["case_sha256"] = canonical_sha256(case)
        contract_payload["split_sha256"] = case["split"]["sha256"]
        contract_payload["selection_sha256"] = case["selection"]["sha256"]
        contract = EvaluationContract.from_payload(contract_payload)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="test",
            )
        self.assertIn("group_key must be a non-empty string", str(ctx.exception))


class TimeSeriesSplitExecutionTest(unittest.TestCase):
    def test_gap_and_embargo_are_executed_against_ordered_sessions(self) -> None:
        dataset, case = _time_series_payload()
        result = _run(dataset, case)
        self.assertEqual(
            result.artifact["split_validation"],
            {
                "kind": "time_series",
                "gap_sessions": 2,
                "embargo_sessions": 2,
                "excluded_rows": 4,
            },
        )

    def test_declared_gap_must_be_observed_in_the_assignment(self) -> None:
        dataset, case = _time_series_payload()
        case["split"]["parameters"]["gap"] = "3 sessions"
        _repin_split(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn("observed train-validation gap 2 is below declared 3", str(ctx.exception))

    def test_session_ordinals_must_be_strictly_increasing(self) -> None:
        dataset, case = _time_series_payload()
        dataset["split_context"]["timestamps"][7] = 8
        case["split"]["parameters"]["context_sha256"] = canonical_sha256(
            dataset["split_context"]
        )
        _repin_split(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn("timestamps must be strictly increasing", str(ctx.exception))

    def test_session_ordinals_must_not_hide_unrepresented_sessions(self) -> None:
        dataset, case = _time_series_payload()
        dataset["split_context"]["timestamps"] = [
            value if value < 7 else value + 1 for value in range(16)
        ]
        case["split"]["parameters"]["context_sha256"] = canonical_sha256(
            dataset["split_context"]
        )
        _repin_split(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn("timestamps must be consecutive", str(ctx.exception))

    def test_excluded_rows_must_not_overlap_a_partition(self) -> None:
        dataset, case = _time_series_payload()
        dataset["split_context"]["excluded_indices"] = [5, 6, 7, 10, 11]
        case["split"]["parameters"]["context_sha256"] = canonical_sha256(
            dataset["split_context"]
        )
        _repin_split(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn("excluded_indices must be disjoint", str(ctx.exception))

    def test_excluded_rows_must_be_exactly_the_gap_and_embargo(self) -> None:
        dataset, case = _time_series_payload()
        dataset["partitions"]["train"] = [1, 2, 3, 4, 5, 6]
        dataset["split_context"]["excluded_indices"] = [0, 7, 10, 11]
        case["split"]["parameters"]["gap"] = "1 sessions"
        case["split"]["parameters"]["assignment_sha256"] = canonical_sha256(
            {"partitions": dataset["partitions"]}
        )
        case["split"]["parameters"]["context_sha256"] = canonical_sha256(
            dataset["split_context"]
        )
        _repin_split(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn("exactly the gap and embargo rows", str(ctx.exception))

    def test_future_holdout_must_follow_test_chronologically(self) -> None:
        dataset, case = _time_series_payload_with_early_future()
        contract = MLAdapter().build_evaluation_contract(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            run_synthetic_experiment(
                dataset,
                case,
                contract=contract,
                final_partition="future_holdout",
            )
        self.assertIn("future_holdout must be ordered after test", str(ctx.exception))

    def test_future_holdout_after_test_is_a_valid_final_partition(self) -> None:
        dataset, case = _time_series_payload()
        dataset["partitions"]["test"] = [12, 13]
        dataset["partitions"]["future_holdout"] = [14, 15]
        case["split"]["parameters"]["assignment_sha256"] = canonical_sha256(
            {"partitions": dataset["partitions"]}
        )
        _repin_split(case)
        contract = MLAdapter().build_evaluation_contract(case)
        result = run_synthetic_experiment(
            dataset,
            case,
            contract=contract,
            final_partition="future_holdout",
        )
        self.assertEqual(
            result.evidence["final_evaluation"]["partition"],
            "future_holdout",
        )


class NestedSplitExecutionTest(unittest.TestCase):
    def test_outer_and_inner_fold_assignments_are_executed(self) -> None:
        dataset, case = _nested_payload()
        result = _run(dataset, case)
        self.assertEqual(
            result.artifact["split_validation"],
            {
                "kind": "nested",
                "outer_folds": 2,
                "inner_folds": 2,
                "development_rows": 8,
            },
        )

    def test_inner_fold_may_not_use_outer_validation_rows(self) -> None:
        dataset, case = _nested_payload()
        inner = dataset["split_context"]["outer_folds"][0]["inner_folds"][0]
        inner["validation"] = [2, 4]
        case["split"]["parameters"]["context_sha256"] = canonical_sha256(
            dataset["split_context"]
        )
        _repin_split(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn("must partition the outer training rows", str(ctx.exception))

    def test_outer_validation_folds_must_rotate_over_development_rows(self) -> None:
        dataset, case = _nested_payload()
        outer_folds = dataset["split_context"]["outer_folds"]
        outer_folds[1] = copy.deepcopy(outer_folds[0])
        case["split"]["parameters"]["context_sha256"] = canonical_sha256(
            dataset["split_context"]
        )
        _repin_split(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn(
            "outer validation folds must cover each development row exactly once",
            str(ctx.exception),
        )

    def test_inner_validation_folds_must_rotate_over_outer_train(self) -> None:
        dataset, case = _nested_payload()
        inner_folds = dataset["split_context"]["outer_folds"][0]["inner_folds"]
        inner_folds[1] = copy.deepcopy(inner_folds[0])
        case["split"]["parameters"]["context_sha256"] = canonical_sha256(
            dataset["split_context"]
        )
        _repin_split(case)
        with self.assertRaises(SyntheticRunnerError) as ctx:
            _run(dataset, case)
        self.assertIn(
            "inner validation folds must cover each outer training row exactly once",
            str(ctx.exception),
        )


if __name__ == "__main__":
    unittest.main()
