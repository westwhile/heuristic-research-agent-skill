"""Pure executable split-family checks for the synthetic ML runner (L5)."""

from __future__ import annotations

import re
from typing import Any

_SESSIONS = re.compile(r"^(0|[1-9][0-9]*) sessions$")


class SplitExecutionError(Exception):
    """The in-memory split assignment does not satisfy its declaration."""


def validate_split_execution(
    data: dict[str, Any], split: dict[str, Any]
) -> dict[str, Any]:
    """Validate one declared split against its in-memory execution context."""

    kind = split["kind"]
    if kind == "iid":
        if data["split_context"] is not None:
            raise SplitExecutionError("iid execution must not carry split_context")
        if set(split["parameters"]) != {"assignment_sha256"}:
            raise SplitExecutionError(
                "iid parameters must contain exactly assignment_sha256"
            )
        _require_complete_assignment(data)
        return {"kind": "iid"}
    if kind == "group":
        return _validate_group(data, split)
    if kind == "time_series":
        return _validate_time_series(data, split)
    if kind == "nested":
        return _validate_nested(data, split)
    raise SplitExecutionError(f"unsupported split kind: {kind!r}")


def _validate_group(
    data: dict[str, Any], split: dict[str, Any]
) -> dict[str, Any]:
    context = data["split_context"]
    if not isinstance(context, dict) or set(context) != {"group_labels"}:
        raise SplitExecutionError(
            "group split_context must contain exactly group_labels"
        )
    labels = context["group_labels"]
    if not isinstance(labels, list) or len(labels) != len(data["features"]):
        raise SplitExecutionError(
            "group_labels must contain exactly one label per dataset row"
        )
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise SplitExecutionError("group_labels must be non-empty strings")
    _require_complete_assignment(data)
    parameters = split["parameters"]
    if set(parameters) != {"group_key", "assignment_sha256", "context_sha256"}:
        raise SplitExecutionError(
            "group parameters must contain exactly group_key, "
            "assignment_sha256, and context_sha256"
        )
    group_key = parameters["group_key"]
    if not isinstance(group_key, str) or not group_key.strip():
        raise SplitExecutionError("group_key must be a non-empty string")
    owner: dict[str, str] = {}
    for partition, indices in data["partitions"].items():
        for index in indices:
            label = labels[index]
            previous = owner.setdefault(label, partition)
            if previous != partition:
                raise SplitExecutionError(
                    f"group label appears in both {previous!r} and {partition!r}"
                )
    return {
        "kind": "group",
        "group_count": len(owner),
        "group_key": group_key,
    }


def _validate_time_series(
    data: dict[str, Any], split: dict[str, Any]
) -> dict[str, Any]:
    context = data["split_context"]
    if not isinstance(context, dict) or set(context) != {
        "timestamps",
        "excluded_indices",
    }:
        raise SplitExecutionError(
            "time_series split_context must contain exactly timestamps and "
            "excluded_indices"
        )
    timestamps = context["timestamps"]
    if not isinstance(timestamps, list) or len(timestamps) != len(data["features"]):
        raise SplitExecutionError(
            "timestamps must contain exactly one session ordinal per dataset row"
        )
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in timestamps
    ):
        raise SplitExecutionError("timestamps must be integer session ordinals")
    if any(left >= right for left, right in zip(timestamps, timestamps[1:])):
        raise SplitExecutionError("timestamps must be strictly increasing")
    if any(right != left + 1 for left, right in zip(timestamps, timestamps[1:])):
        raise SplitExecutionError("timestamps must be consecutive session ordinals")
    excluded = context["excluded_indices"]
    if not isinstance(excluded, list) or any(
        isinstance(index, bool) or not isinstance(index, int) for index in excluded
    ):
        raise SplitExecutionError("excluded_indices must be an integer array")
    if len(excluded) != len(set(excluded)):
        raise SplitExecutionError("excluded_indices must not contain duplicates")
    row_count = len(data["features"])
    if any(index < 0 or index >= row_count for index in excluded):
        raise SplitExecutionError("excluded_indices contains an out-of-range index")
    assigned = {
        index
        for indices in data["partitions"].values()
        for index in indices
    }
    excluded_set = set(excluded)
    if assigned & excluded_set:
        raise SplitExecutionError(
            "excluded_indices must be disjoint from every partition"
        )
    if assigned | excluded_set != set(range(row_count)):
        raise SplitExecutionError(
            "partitions plus excluded_indices must account for every row"
        )
    parameters = split["parameters"]
    if set(parameters) != {
        "gap",
        "embargo",
        "assignment_sha256",
        "context_sha256",
    }:
        raise SplitExecutionError(
            "time_series parameters must contain exactly gap, embargo, "
            "assignment_sha256, and context_sha256"
        )
    gap = _session_count(parameters["gap"], "gap")
    embargo = _session_count(parameters["embargo"], "embargo")
    partitions = data["partitions"]
    for name in ("train", "validation", "test"):
        if name not in partitions:
            raise SplitExecutionError(
                "time_series execution requires train, validation, and test"
            )
    train_max = max(timestamps[index] for index in partitions["train"])
    validation_min = min(timestamps[index] for index in partitions["validation"])
    validation_max = max(timestamps[index] for index in partitions["validation"])
    test_min = min(timestamps[index] for index in partitions["test"])
    if not train_max < validation_min <= validation_max < test_min:
        raise SplitExecutionError(
            "time_series partitions must be ordered train < validation < test"
        )
    if "future_holdout" in partitions:
        test_max = max(timestamps[index] for index in partitions["test"])
        future_min = min(
            timestamps[index] for index in partitions["future_holdout"]
        )
        if test_max >= future_min:
            raise SplitExecutionError(
                "time_series future_holdout must be ordered after test"
            )
    required_excluded = {
        index
        for index, timestamp in enumerate(timestamps)
        if train_max < timestamp < validation_min
        or validation_max < timestamp < test_min
    }
    if excluded_set != required_excluded:
        raise SplitExecutionError(
            "excluded_indices must contain exactly the gap and embargo rows"
        )
    observed_gap = validation_min - train_max - 1
    observed_embargo = test_min - validation_max - 1
    if observed_gap < gap:
        raise SplitExecutionError(
            f"observed train-validation gap {observed_gap} is below declared {gap}"
        )
    if observed_embargo < embargo:
        raise SplitExecutionError(
            f"observed validation-test embargo {observed_embargo} is below "
            f"declared {embargo}"
        )
    return {
        "kind": "time_series",
        "gap_sessions": gap,
        "embargo_sessions": embargo,
        "excluded_rows": len(excluded),
    }


def _session_count(value: Any, name: str) -> int:
    if not isinstance(value, str):
        raise SplitExecutionError(f"{name} must use '<integer> sessions' syntax")
    match = _SESSIONS.fullmatch(value)
    if match is None:
        raise SplitExecutionError(f"{name} must use '<integer> sessions' syntax")
    return int(match.group(1))


def _validate_nested(
    data: dict[str, Any], split: dict[str, Any]
) -> dict[str, Any]:
    context = data["split_context"]
    if not isinstance(context, dict) or set(context) != {"outer_folds"}:
        raise SplitExecutionError(
            "nested split_context must contain exactly outer_folds"
        )
    parameters = split["parameters"]
    if set(parameters) != {
        "outer_folds",
        "inner_folds",
        "assignment_sha256",
        "context_sha256",
    }:
        raise SplitExecutionError(
            "nested parameters must contain exactly outer_folds, inner_folds, "
            "assignment_sha256, and context_sha256"
        )
    outer_count = parameters["outer_folds"]
    inner_count = parameters["inner_folds"]
    if (
        isinstance(outer_count, bool)
        or not isinstance(outer_count, int)
        or outer_count < 2
        or isinstance(inner_count, bool)
        or not isinstance(inner_count, int)
        or inner_count < 2
    ):
        raise SplitExecutionError(
            "nested outer_folds and inner_folds must be integers >= 2"
        )
    folds = context["outer_folds"]
    if not isinstance(folds, list) or len(folds) != outer_count:
        raise SplitExecutionError(
            "split_context outer_folds count must match the declaration"
        )
    partitions = data["partitions"]
    for name in ("train", "validation", "test"):
        if name not in partitions:
            raise SplitExecutionError(
                "nested execution requires train, validation, and test"
            )
    _require_complete_assignment(data)
    development = set(partitions["train"]) | set(partitions["validation"])
    outer_validation_counts = {index: 0 for index in development}
    for outer_index, outer in enumerate(folds):
        path = f"outer_folds[{outer_index}]"
        if not isinstance(outer, dict) or set(outer) != {
            "train",
            "validation",
            "inner_folds",
        }:
            raise SplitExecutionError(
                f"{path} must contain exactly train, validation, and inner_folds"
            )
        outer_train = _fold_indices(outer["train"], f"{path}.train")
        outer_validation = _fold_indices(
            outer["validation"], f"{path}.validation"
        )
        if (
            outer_train & outer_validation
            or outer_train | outer_validation != development
        ):
            raise SplitExecutionError(
                f"{path} train and validation must partition the development rows"
            )
        for index in outer_validation:
            outer_validation_counts[index] += 1
        inner_folds = outer["inner_folds"]
        if not isinstance(inner_folds, list) or len(inner_folds) != inner_count:
            raise SplitExecutionError(
                f"{path}.inner_folds count must match the declaration"
            )
        inner_validation_counts = {index: 0 for index in outer_train}
        for inner_index, inner in enumerate(inner_folds):
            inner_path = f"{path}.inner_folds[{inner_index}]"
            if not isinstance(inner, dict) or set(inner) != {
                "train",
                "validation",
            }:
                raise SplitExecutionError(
                    f"{inner_path} must contain exactly train and validation"
                )
            inner_train = _fold_indices(inner["train"], f"{inner_path}.train")
            inner_validation = _fold_indices(
                inner["validation"], f"{inner_path}.validation"
            )
            if (
                inner_train & inner_validation
                or inner_train | inner_validation != outer_train
            ):
                raise SplitExecutionError(
                    f"{inner_path} train and validation must partition the outer "
                    "training rows"
                )
            for index in inner_validation:
                inner_validation_counts[index] += 1
        if any(count != 1 for count in inner_validation_counts.values()):
            raise SplitExecutionError(
                f"{path} inner validation folds must cover each outer training "
                "row exactly once"
            )
    if any(count != 1 for count in outer_validation_counts.values()):
        raise SplitExecutionError(
            "outer validation folds must cover each development row exactly once"
        )
    return {
        "kind": "nested",
        "outer_folds": outer_count,
        "inner_folds": inner_count,
        "development_rows": len(development),
    }


def _fold_indices(value: Any, path: str) -> set[int]:
    if not isinstance(value, list) or not value:
        raise SplitExecutionError(f"{path} must be a non-empty integer array")
    if any(
        isinstance(index, bool) or not isinstance(index, int) for index in value
    ):
        raise SplitExecutionError(f"{path} must be a non-empty integer array")
    if len(value) != len(set(value)):
        raise SplitExecutionError(f"{path} must not contain duplicates")
    return set(value)


def _require_complete_assignment(data: dict[str, Any]) -> None:
    assigned = {
        index
        for indices in data["partitions"].values()
        for index in indices
    }
    if assigned != set(range(len(data["features"]))):
        raise SplitExecutionError("partitions must assign every row exactly once")


__all__: list[str] = []
