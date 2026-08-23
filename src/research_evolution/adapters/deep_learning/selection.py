"""Deterministic multi-seed selection for synthetic DL fixture results.

The module consumes canonical runner artifacts through one interface.  It
never executes training, opens checkpoints, reads a clock, probes hardware, or
touches the filesystem.  Expected seeds are declared before aggregation so a
failed or missing run cannot disappear from a best-only narrative.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence

from research_evolution.core import (
    CoreError,
    canonical_bytes,
    canonical_sha256,
    load_strict_json,
)

from .runner import DLRunResult

SELECTOR_NAME = "reference-dl-selector"
SELECTOR_VERSION = "0.1.0"

_PLAN_SCHEMA = "synthetic-dl-selection-plan/v1"
_RESULT_SCHEMA = "synthetic-dl-selection-result/v1"
_RUN_RESULT_SCHEMA = "synthetic-dl-run-result/v2"
_PLAN_FIELDS = frozenset(
    {
        "schema",
        "selection_id",
        "study_id",
        "case_sha256",
        "metric",
        "direction",
        "expected_runs",
        "minimum_successful_runs",
    }
)
_EXPECTED_RUN_FIELDS = frozenset({"run_id", "seed"})
_MAX_EXPECTED_RUNS = 64


class DLSelectionError(Exception):
    """Invalid selection plan or run-result set."""


@dataclass(frozen=True)
class DLSelectionResult:
    """Immutable canonical selection artifact."""

    _artifact_bytes: bytes

    @property
    def artifact(self) -> dict[str, Any]:
        return load_strict_json(self._artifact_bytes)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self._artifact_bytes).hexdigest()

    @property
    def status(self) -> str:
        return self.artifact["status"]

    @property
    def selected_checkpoint(self) -> dict[str, Any] | None:
        return self.artifact["selected_checkpoint"]


def selector_identity() -> dict[str, str]:
    return {"name": SELECTOR_NAME, "version": SELECTOR_VERSION}


def select_fixture_runs(
    results: Sequence[DLRunResult], selection_payload: dict[str, Any]
) -> DLSelectionResult:
    """Aggregate an expected multi-seed set and select one checkpoint.

    Every expected ``run_id``/``seed`` pair appears in the result.  Missing,
    failed, interrupted, numerically invalid, resource-exhausted, and
    budget-exhausted runs remain ineligible records rather than disappearing.
    Selection is permitted only when ``minimum_successful_runs`` is met.
    """
    plan = _validate_plan(selection_payload)
    observed = _validate_results(results, plan)
    run_records: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []

    for expected in plan["expected_runs"]:
        artifact = observed.get(expected["run_id"])
        if artifact is None:
            run_records.append(
                {
                    "run_id": expected["run_id"],
                    "seed": expected["seed"],
                    "result_sha256": None,
                    "status": "missing",
                    "failure_class": "missing",
                    "eligible": False,
                    "ineligibility_reason": "expected-run-missing",
                    "metric_value": None,
                    "checkpoint": None,
                }
            )
            continue
        record = _classify_run(artifact, expected, plan["metric"])
        run_records.append(record)
        if record["eligible"]:
            eligible.append(record)

    successful = len(eligible)
    status = (
        "completed"
        if successful >= plan["minimum_successful_runs"]
        else "insufficient_successful_runs"
    )
    aggregate = _aggregate(eligible)
    selected = _select(eligible, plan["direction"]) if status == "completed" else None
    selected_checkpoint = selected["checkpoint"] if selected else None
    selected_run = (
        {"run_id": selected["run_id"], "seed": selected["seed"]}
        if selected
        else None
    )
    missing = sum(record["status"] == "missing" for record in run_records)
    failed = len(run_records) - successful - missing
    core = {
        "schema": _RESULT_SCHEMA,
        "selection_id": plan["selection_id"],
        "selection_plan_sha256": canonical_sha256(plan["payload"]),
        "study_id": plan["study_id"],
        "case_sha256": plan["case_sha256"],
        "selector": selector_identity(),
        "metric": plan["metric"],
        "direction": plan["direction"],
        "status": status,
        "evidence_scope": "synthetic_engineering",
        "counts": {
            "expected": len(run_records),
            "observed": len(run_records) - missing,
            "successful": successful,
            "failed": failed,
            "missing": missing,
            "minimum_successful_runs": plan["minimum_successful_runs"],
        },
        "runs": run_records,
        "aggregate": aggregate,
        "selected_run": selected_run,
        "selected_checkpoint": selected_checkpoint,
        "limitations": [
            "All runs and checkpoints are synthetic CPU engineering artifacts.",
            "Observed range is descriptive and is not a confidence interval.",
            "The selected checkpoint does not establish multi-seed stability.",
            "Failed and missing expected seeds remain explicit in this artifact.",
            "No framework, GPU, real dataset, or external checkpoint store "
            "was observed.",
        ],
    }
    identity_sha256 = canonical_sha256(core)
    artifact = {
        "selection_result_id": f"dl-selection-{identity_sha256[:16]}",
        **core,
    }
    return DLSelectionResult(canonical_bytes(artifact))


def _validate_plan(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DLSelectionError("selection_payload must be an object")
    try:
        snapshot = load_strict_json(canonical_bytes(payload))
    except CoreError as exc:
        raise DLSelectionError(
            f"selection_payload is not strict JSON: {exc}"
        ) from exc
    if set(snapshot) != _PLAN_FIELDS:
        raise DLSelectionError(
            f"selection fields must be exactly {sorted(_PLAN_FIELDS)}"
        )
    if snapshot["schema"] != _PLAN_SCHEMA:
        raise DLSelectionError(f"selection.schema must be {_PLAN_SCHEMA}")
    for field in ("selection_id", "study_id"):
        _token(snapshot[field], f"selection.{field}")
    _sha256(snapshot["case_sha256"], "selection.case_sha256")
    if snapshot["metric"] != "validation_loss":
        raise DLSelectionError("selector 0.1.0 supports only validation_loss")
    if snapshot["direction"] != "minimize":
        raise DLSelectionError("selector 0.1.0 supports only minimize")
    expected = snapshot["expected_runs"]
    if (
        not isinstance(expected, list)
        or not 2 <= len(expected) <= _MAX_EXPECTED_RUNS
    ):
        raise DLSelectionError(
            f"expected_runs must contain 2..{_MAX_EXPECTED_RUNS} entries"
        )
    seen_runs: set[str] = set()
    seen_seeds: set[int] = set()
    normalized_expected = []
    for index, entry in enumerate(expected):
        if not isinstance(entry, dict) or set(entry) != _EXPECTED_RUN_FIELDS:
            raise DLSelectionError(
                f"expected_runs[{index}] fields must be exactly "
                f"{sorted(_EXPECTED_RUN_FIELDS)}"
            )
        run_id = _token(entry["run_id"], f"expected_runs[{index}].run_id")
        seed = entry["seed"]
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            raise DLSelectionError(
                f"expected_runs[{index}].seed must be a non-negative integer"
            )
        if run_id in seen_runs or seed in seen_seeds:
            raise DLSelectionError("expected run ids and seeds must be unique")
        seen_runs.add(run_id)
        seen_seeds.add(seed)
        normalized_expected.append({"run_id": run_id, "seed": seed})
    minimum = snapshot["minimum_successful_runs"]
    if (
        not isinstance(minimum, int)
        or isinstance(minimum, bool)
        or not 2 <= minimum <= len(expected)
    ):
        raise DLSelectionError(
            "minimum_successful_runs must be between 2 and expected count"
        )
    return {
        **snapshot,
        "payload": snapshot,
        "expected_runs": normalized_expected,
    }


def _validate_results(
    results: Sequence[DLRunResult], plan: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    if isinstance(results, (str, bytes, bytearray)) or not isinstance(
        results, Sequence
    ):
        raise DLSelectionError("results must be a sequence of DLRunResult")
    expected_ids = {entry["run_id"] for entry in plan["expected_runs"]}
    observed: dict[str, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, DLRunResult):
            raise DLSelectionError("results must contain only DLRunResult")
        artifact = result.artifact
        if artifact.get("schema") != _RUN_RESULT_SCHEMA:
            raise DLSelectionError("selector requires runner 0.2 result artifacts")
        run_id = artifact["run_id"]
        if run_id not in expected_ids:
            raise DLSelectionError("result run_id was not preregistered")
        if run_id in observed:
            raise DLSelectionError("duplicate result run_id")
        if artifact["study_id"] != plan["study_id"]:
            raise DLSelectionError("result study_id does not match selection plan")
        if artifact["case_sha256"] != plan["case_sha256"]:
            raise DLSelectionError("result case_sha256 does not match selection plan")
        artifact["_result_sha256"] = result.sha256
        observed[run_id] = artifact
    return observed


def _classify_run(
    artifact: dict[str, Any], expected: dict[str, Any], metric: str
) -> dict[str, Any]:
    if artifact["fixture"]["seed"] != expected["seed"]:
        raise DLSelectionError("result seed does not match preregistered run")
    status = artifact["status"]
    checkpoint = artifact["checkpointing"]["selected_checkpoint"]
    eligible_status = status in {"completed", "early_stopped"}
    eligible = (
        eligible_status
        and artifact["failure"]["class"] == "none"
        and checkpoint is not None
        and artifact["evidence_scope"] == "synthetic_engineering"
    )
    if eligible:
        value = _finite(checkpoint[metric], f"{expected['run_id']}.{metric}")
        reason = None
    else:
        value = None
        if not eligible_status:
            reason = f"terminal-status-{status}"
        elif artifact["failure"]["class"] != "none":
            reason = f"failure-{artifact['failure']['class']}"
        elif checkpoint is None:
            reason = "selected-checkpoint-missing"
        else:
            reason = "evidence-scope-ineligible"
    return {
        "run_id": expected["run_id"],
        "seed": expected["seed"],
        "result_sha256": artifact["_result_sha256"],
        "status": status,
        "failure_class": artifact["failure"]["class"],
        "eligible": eligible,
        "ineligibility_reason": reason,
        "metric_value": _rounded(value) if value is not None else None,
        "checkpoint": checkpoint if eligible else None,
    }


def _aggregate(eligible: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not eligible:
        return None
    values = [float(record["metric_value"]) for record in eligible]
    return {
        "method": "population_descriptive_statistics",
        "count": len(values),
        "mean": _rounded(statistics.fmean(values)),
        "variance": _rounded(statistics.pvariance(values)),
        "observed_range": [_rounded(min(values)), _rounded(max(values))],
    }


def _select(
    eligible: list[dict[str, Any]], direction: str
) -> dict[str, Any]:
    if direction == "minimize":
        return min(eligible, key=lambda record: record["metric_value"])
    return max(eligible, key=lambda record: record["metric_value"])


def _token(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise DLSelectionError(f"{path} must be a non-whitespace token")
    return value


def _sha256(value: Any, path: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise DLSelectionError(f"{path} must be lowercase SHA-256")
    return value


def _finite(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise DLSelectionError(f"{path} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise DLSelectionError(f"{path} must be finite")
    return result


def _rounded(value: float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise DLSelectionError("selection statistics must be finite")
    rounded = round(result, 12)
    return 0.0 if rounded == 0.0 else rounded


__all__ = [
    "DLSelectionError",
    "DLSelectionResult",
    "select_fixture_runs",
    "selector_identity",
]
