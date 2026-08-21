"""Deterministic standard-library runner for small synthetic ML fixtures.

This module is a protocol test machine, not a general training executor.  It
accepts one in-memory numeric dataset payload plus one ``ml-case/v1`` payload
and returns an immutable result containing a hash-bound ``ml-evidence/v2``
record.  There is no I/O, clock, environment, network, subprocess, or global
random state.  Seeded ordering and initialization are derived from SHA-256 so
the same payloads produce the same artifact across supported Python runtimes.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from research_evolution.core import (
    CoreError,
    canonical_bytes,
    canonical_sha256,
    load_strict_json,
)

from . import _evidence
from ..types import AdapterError

RUNNER_TOOL = "synthetic-ml-runner"
RUNNER_VERSION = "0.1.0"

_MAX_ROWS = 10_000
_MAX_FEATURES = 64
_MAX_SEEDS = 64
_MAX_EPOCHS = 1_000
_MAX_SAMPLE_VISITS = 2_000_000

_TASK_MODELS = {
    "binary_classification": "logistic-regression",
    "regression": "ridge-regression",
}
_TASK_METRICS = {
    "binary_classification": frozenset({"accuracy", "f1"}),
    "regression": frozenset({"mean_absolute_error", "mean_squared_error"}),
}


class SyntheticRunnerError(Exception):
    """Invalid runner input or unsupported synthetic experiment contract."""


@dataclass(frozen=True)
class SyntheticExperimentResult:
    """Immutable canonical result; accessors return fresh JSON trees."""

    _artifact_bytes: bytes
    _evidence_bytes: bytes

    @property
    def artifact(self) -> dict[str, Any]:
        return load_strict_json(self._artifact_bytes)

    @property
    def evidence(self) -> dict[str, Any]:
        return load_strict_json(self._evidence_bytes)

    @property
    def artifact_sha256(self) -> str:
        return hashlib.sha256(self._artifact_bytes).hexdigest()


def runner_identity() -> dict[str, str]:
    return {"tool": RUNNER_TOOL, "version": RUNNER_VERSION}


def run_synthetic_experiment(
    dataset_payload: dict[str, Any],
    case: dict[str, Any],
    *,
    final_partition: str,
) -> SyntheticExperimentResult:
    """Run one deterministic baseline/candidate comparison in memory.

    ``dataset_payload`` has exactly four keys: ``task_type``, ``features``,
    ``targets``, and ``partitions``.  The canonical hash of the first three
    keys must equal ``case.dataset.sha256``; the canonical hash of
    ``{"partitions": partitions}`` must equal ``case.split.sha256``.

    The case supplies the candidate model, seed set, selection partition,
    metrics, and a search budget containing exactly ``epochs`` and
    ``sample_limit``.  The baseline is an intercept-only model trained with
    the same seeds, row ordering, epochs, and sample limit.  Thus model is the
    only changed comparison axis; resource, seed, data, and heuristic axes are
    frozen and recorded in the artifact.
    """

    case_data, case_sha256 = _validate_case(case)
    data = _validate_dataset(dataset_payload)
    _validate_hash_bindings(dataset_payload, case_data)
    contract = {
        "case_sha256": case_sha256,
        "selection_partition": case_data["selection"]["split_used"],
        "selection_sha256": case_data["selection"]["sha256"],
        "split_sha256": case_data["split"]["sha256"],
    }
    _validate_partitions(data, contract, final_partition)
    model = _validate_model(case_data, data["task_type"])
    metrics = _validate_metrics(case_data, data["task_type"])
    seeds, budget = _validate_repetition_and_budget(case_data, data)

    per_seed: list[dict[str, Any]] = []
    for seed in seeds:
        orders = _epoch_orders(
            data["partitions"]["train"], seed, budget["epochs"], budget["sample_limit"]
        )
        candidate = _fit_model(data, orders, model, seed, use_features=True)
        baseline = _fit_model(data, orders, model, seed, use_features=False)
        final_indices = data["partitions"][final_partition]
        candidate_values = _predict(data, final_indices, candidate, use_features=True)
        baseline_values = _predict(data, final_indices, baseline, use_features=False)
        candidate_metrics = _score(
            data["task_type"], data["targets"], final_indices, candidate_values, metrics
        )
        baseline_metrics = _score(
            data["task_type"], data["targets"], final_indices, baseline_values, metrics
        )
        usage = {
            "epochs": budget["epochs"],
            "sample_visits": budget["epochs"] * budget["sample_limit"],
        }
        per_seed.append(
            {
                "seed": seed,
                "candidate_metrics": candidate_metrics,
                "baseline_metrics": baseline_metrics,
                "resource_usage": {
                    "candidate": usage,
                    "baseline": dict(usage),
                },
            }
        )

    aggregates = {
        "candidate": _aggregate(per_seed, "candidate_metrics", metrics),
        "baseline": _aggregate(per_seed, "baseline_metrics", metrics),
    }
    comparison = {
        metric: _rounded(
            aggregates["candidate"][metric]["mean"]
            - aggregates["baseline"][metric]["mean"]
        )
        for metric in metrics
    }
    artifact = {
        "runner": runner_identity(),
        "study_id": case_data["study_id"],
        "case_sha256": contract["case_sha256"],
        "dataset_sha256": case_data["dataset"]["sha256"],
        "split_sha256": case_data["split"]["sha256"],
        "selection": {
            "partition": contract["selection_partition"],
            "selection_sha256": contract["selection_sha256"],
        },
        "final_evaluation": {
            "partition": final_partition,
            "split_sha256": contract["split_sha256"],
        },
        "models": {
            "candidate": {
                "family": case_data["model"]["family"],
                "hyperparameters": model,
            },
            "baseline": {"family": "intercept-only"},
        },
        "metrics": metrics,
        "seeds": seeds,
        "per_seed": per_seed,
        "aggregates": aggregates,
        "parity": {
            "changed_axes": ["model"],
            "frozen_axes": {
                "dataset_sha256": case_data["dataset"]["sha256"],
                "split_sha256": case_data["split"]["sha256"],
                "resource_budget": budget,
                "seeds": seeds,
                "heuristics": [],
            },
            "resource_parity": True,
            "candidate_minus_baseline": comparison,
        },
    }
    artifact_bytes = canonical_bytes(artifact)
    artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    evidence = {
        "schema": "ml-evidence/v2",
        "evidence_id": f"ml-evidence-{artifact_sha256[:16]}",
        "study_id": case_data["study_id"],
        "kind": "experiment_run",
        "data_provenance": "synthetic",
        "content_sha256": artifact_sha256,
        "seeds": seeds,
        "frozen_holdout": True,
        "final_evaluation": artifact["final_evaluation"],
        "summary": (
            "Deterministic standard-library synthetic baseline/candidate "
            "comparison with repeated-seed aggregation."
        ),
        "limitations": [
            "Synthetic data proves protocol and runner behavior only.",
            "The reference algorithms are intentionally small and are not a real ML executor.",
        ],
    }
    evidence_bytes = canonical_bytes(evidence)
    validated_evidence = load_strict_json(evidence_bytes)
    _evidence.validate_final_evaluation(contract, validated_evidence)
    return SyntheticExperimentResult(
        _artifact_bytes=artifact_bytes,
        _evidence_bytes=evidence_bytes,
    )


def _validate_case(payload: Any) -> tuple[dict[str, Any], str]:
    """Take a strict in-memory snapshot and validate runner-owned fields.

    Full ``ml-case/v1`` schema and topology validation remain the adapter's
    responsibility.  Repeating that file-backed schema engine here would
    make this runner perform hidden I/O.  This boundary instead validates
    every field the runner consumes and lets the public adapter integration
    test prove that the emitted evidence traverses the full contract.
    """

    if not isinstance(payload, dict):
        raise SyntheticRunnerError("case must be an object")
    try:
        snapshot_bytes = canonical_bytes(payload)
        case = load_strict_json(snapshot_bytes)
    except CoreError as exc:
        raise SyntheticRunnerError(f"case is not strict JSON: {exc}") from exc
    required = {"schema", "study_id", "dataset", "split", "model", "metrics", "selection"}
    missing = sorted(required - set(case))
    if missing:
        raise SyntheticRunnerError(f"case is missing runner fields: {missing}")
    if case["schema"] != "ml-case/v1":
        raise SyntheticRunnerError("case.schema must be ml-case/v1")
    study_id = case["study_id"]
    if not isinstance(study_id, str) or not study_id or any(
        character.isspace() for character in study_id
    ):
        raise SyntheticRunnerError("case.study_id must be a non-whitespace token")
    for field in ("dataset", "split", "model", "selection"):
        if not isinstance(case[field], dict):
            raise SyntheticRunnerError(f"case.{field} must be an object")
    _require_sha256(case["dataset"], "sha256", "case.dataset.sha256")
    _require_sha256(case["split"], "sha256", "case.split.sha256")
    _require_sha256(case["selection"], "sha256", "case.selection.sha256")
    if "family" not in case["model"] or "hyperparameters" not in case["model"]:
        raise SyntheticRunnerError("case.model must declare family and hyperparameters")
    if not isinstance(case["model"]["family"], str):
        raise SyntheticRunnerError("case.model.family must be a string")
    if not isinstance(case["model"]["hyperparameters"], dict):
        raise SyntheticRunnerError("case.model.hyperparameters must be an object")
    metrics = case["metrics"]
    if not isinstance(metrics, list) or not metrics or any(
        not isinstance(metric, str) or not metric.strip() for metric in metrics
    ):
        raise SyntheticRunnerError("case.metrics must be a non-empty string array")
    selection = case["selection"]
    for field in ("split_used", "search_budget", "seed_set"):
        if field not in selection:
            raise SyntheticRunnerError(f"case.selection.{field} is required")
    if selection["split_used"] not in {"train", "validation", "test"}:
        raise SyntheticRunnerError("case.selection.split_used is unsupported")
    if not isinstance(selection["search_budget"], dict):
        raise SyntheticRunnerError("case.selection.search_budget must be an object")
    if not isinstance(selection["seed_set"], list) or not selection["seed_set"]:
        raise SyntheticRunnerError("case.selection.seed_set must be a non-empty array")
    if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in selection["seed_set"]):
        raise SyntheticRunnerError("case.selection.seed_set must contain integers")
    return case, hashlib.sha256(snapshot_bytes).hexdigest()


def _require_sha256(parent: dict[str, Any], field: str, path: str) -> None:
    value = parent.get(field)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SyntheticRunnerError(f"{path} must be a lowercase SHA-256 hex digest")


def _validate_dataset(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SyntheticRunnerError("dataset_payload must be an object")
    expected = {"task_type", "features", "targets", "partitions"}
    if set(payload) != expected:
        raise SyntheticRunnerError(
            f"dataset_payload keys must be exactly {sorted(expected)}"
        )
    task_type = payload["task_type"]
    if task_type not in _TASK_MODELS:
        raise SyntheticRunnerError(
            f"unsupported task_type; expected one of {sorted(_TASK_MODELS)}"
        )
    features = payload["features"]
    targets = payload["targets"]
    if not isinstance(features, list) or not features or len(features) > _MAX_ROWS:
        raise SyntheticRunnerError(f"features must contain 1..{_MAX_ROWS} rows")
    if not isinstance(targets, list) or len(targets) != len(features):
        raise SyntheticRunnerError("targets must have exactly one value per feature row")
    width: int | None = None
    clean_features: list[list[float]] = []
    for row_index, row in enumerate(features):
        if not isinstance(row, list) or not row:
            raise SyntheticRunnerError(f"features[{row_index}] must be a non-empty array")
        if width is None:
            width = len(row)
            if width > _MAX_FEATURES:
                raise SyntheticRunnerError(
                    f"feature width must not exceed {_MAX_FEATURES}"
                )
        if len(row) != width:
            raise SyntheticRunnerError("all feature rows must have the same width")
        clean_features.append(
            [_finite_number(value, f"features[{row_index}]") for value in row]
        )
    clean_targets = [
        _finite_number(value, f"targets[{index}]")
        for index, value in enumerate(targets)
    ]
    if task_type == "binary_classification" and any(
        value not in (0.0, 1.0) for value in clean_targets
    ):
        raise SyntheticRunnerError("binary_classification targets must be 0 or 1")
    partitions = payload["partitions"]
    if not isinstance(partitions, dict):
        raise SyntheticRunnerError("partitions must be an object")
    allowed = {"train", "validation", "test", "future_holdout"}
    if set(partitions) - allowed:
        raise SyntheticRunnerError("partitions contains an unknown partition name")
    clean_partitions: dict[str, list[int]] = {}
    seen: set[int] = set()
    for name, indices in partitions.items():
        if not isinstance(indices, list) or not indices:
            raise SyntheticRunnerError(f"partition {name!r} must be a non-empty array")
        clean: list[int] = []
        for index in indices:
            if isinstance(index, bool) or not isinstance(index, int):
                raise SyntheticRunnerError(f"partition {name!r} contains a non-integer index")
            if index < 0 or index >= len(features):
                raise SyntheticRunnerError(f"partition {name!r} contains an out-of-range index")
            if index in seen:
                raise SyntheticRunnerError("partition indices must be globally disjoint")
            seen.add(index)
            clean.append(index)
        clean_partitions[name] = clean
    if seen != set(range(len(features))):
        raise SyntheticRunnerError("partitions must assign every row exactly once")
    return {
        "task_type": task_type,
        "features": clean_features,
        "targets": clean_targets,
        "partitions": clean_partitions,
    }


def _finite_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise SyntheticRunnerError(f"{path} contains a non-numeric value")
    result = float(value)
    if not math.isfinite(result):
        raise SyntheticRunnerError(f"{path} contains a non-finite value")
    return result


def _validate_hash_bindings(data: dict[str, Any], case: dict[str, Any]) -> None:
    data_projection = {
        "task_type": data["task_type"],
        "features": data["features"],
        "targets": data["targets"],
    }
    split_projection = {"partitions": data["partitions"]}
    if canonical_sha256(data_projection) != case["dataset"]["sha256"]:
        raise SyntheticRunnerError("dataset payload hash does not match case.dataset.sha256")
    if canonical_sha256(split_projection) != case["split"]["sha256"]:
        raise SyntheticRunnerError("partition payload hash does not match case.split.sha256")


def _validate_partitions(
    data: dict[str, Any], contract: dict[str, Any], final_partition: Any
) -> None:
    if "train" not in data["partitions"]:
        raise SyntheticRunnerError("partitions must include train")
    selection = contract["selection_partition"]
    if selection not in data["partitions"]:
        raise SyntheticRunnerError("the case selection partition is absent from the dataset")
    if not isinstance(final_partition, str):
        raise SyntheticRunnerError("final_partition must be a partition-name string")
    if final_partition not in data["partitions"]:
        raise SyntheticRunnerError("the requested final partition is absent from the dataset")
    probe = {
        "final_evaluation": {
            "partition": final_partition,
            "split_sha256": contract["split_sha256"],
        }
    }
    try:
        _evidence.validate_selection_contract(contract)
        _evidence.validate_final_evaluation(contract, probe)
    except AdapterError as exc:
        raise SyntheticRunnerError(str(exc)) from exc


def _validate_model(case: dict[str, Any], task_type: str) -> dict[str, float]:
    expected_family = _TASK_MODELS[task_type]
    if case["model"]["family"] != expected_family:
        raise SyntheticRunnerError(
            f"task_type {task_type!r} requires model family {expected_family!r}"
        )
    raw = case["model"]["hyperparameters"]
    if set(raw) != {"learning_rate", "l2"}:
        raise SyntheticRunnerError(
            "model.hyperparameters must contain exactly learning_rate and l2"
        )
    learning_rate = _finite_number(raw["learning_rate"], "learning_rate")
    l2 = _finite_number(raw["l2"], "l2")
    if learning_rate <= 0.0 or l2 < 0.0:
        raise SyntheticRunnerError("learning_rate must be > 0 and l2 must be >= 0")
    return {"learning_rate": learning_rate, "l2": l2}


def _validate_metrics(case: dict[str, Any], task_type: str) -> list[str]:
    metrics = case["metrics"]
    if len(set(metrics)) != len(metrics):
        raise SyntheticRunnerError("metrics must not contain duplicates")
    unsupported = set(metrics) - _TASK_METRICS[task_type]
    if unsupported:
        raise SyntheticRunnerError(
            f"unsupported metrics for {task_type}: {sorted(unsupported)}"
        )
    return list(metrics)


def _validate_repetition_and_budget(
    case: dict[str, Any], data: dict[str, Any]
) -> tuple[list[int], dict[str, int]]:
    seeds = case["selection"]["seed_set"]
    if len(seeds) > _MAX_SEEDS or len(set(seeds)) != len(seeds):
        raise SyntheticRunnerError(
            f"selection.seed_set must contain 1..{_MAX_SEEDS} unique seeds"
        )
    raw = case["selection"]["search_budget"]
    if set(raw) != {"epochs", "sample_limit"}:
        raise SyntheticRunnerError(
            "selection.search_budget must contain exactly epochs and sample_limit"
        )
    epochs = raw["epochs"]
    sample_limit = raw["sample_limit"]
    if (
        isinstance(epochs, bool)
        or not isinstance(epochs, int)
        or epochs < 1
        or epochs > _MAX_EPOCHS
    ):
        raise SyntheticRunnerError(f"epochs must be an integer in 1..{_MAX_EPOCHS}")
    train_size = len(data["partitions"]["train"])
    if (
        isinstance(sample_limit, bool)
        or not isinstance(sample_limit, int)
        or sample_limit < 1
        or sample_limit > train_size
    ):
        raise SyntheticRunnerError("sample_limit must be an integer in 1..train size")
    if epochs * sample_limit * len(seeds) > _MAX_SAMPLE_VISITS:
        raise SyntheticRunnerError(
            f"experiment exceeds the {_MAX_SAMPLE_VISITS} sample-visit budget"
        )
    return list(seeds), {"epochs": epochs, "sample_limit": sample_limit}


def _epoch_orders(
    train_indices: list[int], seed: int, epochs: int, sample_limit: int
) -> list[list[int]]:
    orders = []
    for epoch in range(epochs):
        ordered = sorted(
            train_indices,
            key=lambda index: hashlib.sha256(
                f"{seed}:{epoch}:{index}".encode("ascii")
            ).digest(),
        )
        orders.append(ordered[:sample_limit])
    return orders


def _initial_weight(seed: int, index: int) -> float:
    digest = hashlib.sha256(f"weight:{seed}:{index}".encode("ascii")).digest()
    unit = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return (unit - 0.5) * 0.02


def _fit_model(
    data: dict[str, Any],
    orders: list[list[int]],
    model: dict[str, float],
    seed: int,
    *,
    use_features: bool,
) -> tuple[list[float], float, str]:
    width = len(data["features"][0])
    weights = [_initial_weight(seed, index) for index in range(width)]
    intercept = _initial_weight(seed, width)
    learning_rate = model["learning_rate"]
    l2 = model["l2"]
    task_type = data["task_type"]
    for order in orders:
        for row_index in order:
            row = data["features"][row_index]
            linear = intercept
            if use_features:
                linear += math.fsum(weight * value for weight, value in zip(weights, row))
            prediction = _sigmoid(linear) if task_type == "binary_classification" else linear
            error = prediction - data["targets"][row_index]
            intercept -= learning_rate * error
            if use_features:
                for index, value in enumerate(row):
                    weights[index] -= learning_rate * (
                        error * value + l2 * weights[index]
                    )
    return weights, intercept, task_type


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        exponent = math.exp(-min(value, 60.0))
        return 1.0 / (1.0 + exponent)
    exponent = math.exp(max(value, -60.0))
    return exponent / (1.0 + exponent)


def _predict(
    data: dict[str, Any],
    indices: list[int],
    fitted: tuple[list[float], float, str],
    *,
    use_features: bool,
) -> list[float]:
    weights, intercept, task_type = fitted
    predictions = []
    for row_index in indices:
        linear = intercept
        if use_features:
            linear += math.fsum(
                weight * value
                for weight, value in zip(weights, data["features"][row_index])
            )
        predictions.append(_sigmoid(linear) if task_type == "binary_classification" else linear)
    return predictions


def _score(
    task_type: str,
    targets: list[float],
    indices: list[int],
    predictions: list[float],
    metrics: list[str],
) -> dict[str, float]:
    actual = [targets[index] for index in indices]
    result: dict[str, float] = {}
    if task_type == "binary_classification":
        labels = [1.0 if value >= 0.5 else 0.0 for value in predictions]
        for metric in metrics:
            if metric == "accuracy":
                value = sum(a == p for a, p in zip(actual, labels)) / len(actual)
            else:
                true_positive = sum(a == 1.0 and p == 1.0 for a, p in zip(actual, labels))
                false_positive = sum(a == 0.0 and p == 1.0 for a, p in zip(actual, labels))
                false_negative = sum(a == 1.0 and p == 0.0 for a, p in zip(actual, labels))
                denominator = 2 * true_positive + false_positive + false_negative
                value = 0.0 if denominator == 0 else 2 * true_positive / denominator
            result[metric] = _rounded(value)
    else:
        errors = [prediction - target for prediction, target in zip(predictions, actual)]
        for metric in metrics:
            if metric == "mean_squared_error":
                value = math.fsum(error * error for error in errors) / len(errors)
            else:
                value = math.fsum(abs(error) for error in errors) / len(errors)
            result[metric] = _rounded(value)
    return result


def _aggregate(
    per_seed: list[dict[str, Any]], field: str, metrics: list[str]
) -> dict[str, dict[str, Any]]:
    result = {}
    for metric in metrics:
        values = [entry[field][metric] for entry in per_seed]
        result[metric] = {
            "mean": _rounded(statistics.fmean(values)),
            "variance": _rounded(statistics.pvariance(values)),
            "observed_range": [_rounded(min(values)), _rounded(max(values))],
        }
    return result


def _rounded(value: float) -> float:
    return round(float(value), 12)


__all__ = [
    "SyntheticExperimentResult",
    "SyntheticRunnerError",
    "run_synthetic_experiment",
    "runner_identity",
]
