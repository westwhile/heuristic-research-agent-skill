"""Deterministic Phase 6 runner for dry-runs and tiny CPU fixtures.

This is an in-process protocol machine, not a framework or GPU executor.  One
public function consumes a validated :class:`DLRunManifest` plus a bounded
synthetic regression fixture and returns one immutable canonical artifact.
The same implementation owns validation, deterministic tiny-MLP training,
budget accounting, and terminal failure classification so those rules do not
spread across callers.

There is no filesystem, clock, environment, network, subprocess, global random
state, training-framework import, checkpoint I/O, or hardware probe.  Failure
injection is explicitly synthetic and can only support engineering tests.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from research_evolution.core import (
    CoreError,
    canonical_bytes,
    canonical_sha256,
    load_strict_json,
)

from .manifest import DLRunManifest

RUNNER_NAME = "reference-dl-runner"
RUNNER_VERSION = "0.1.0"

_FIXTURE_SCHEMA = "synthetic-dl-fixture/v1"
_RESULT_SCHEMA = "synthetic-dl-run-result/v1"
_MAX_ROWS = 32
_MAX_FEATURES = 8
_MAX_HIDDEN_UNITS = 8
_MAX_STEPS = 100
_MAX_ABS_VALUE = 1_000_000.0

_FIXTURE_FIELDS = frozenset(
    {
        "schema",
        "fixture_id",
        "features",
        "targets",
        "hidden_units",
        "learning_rate",
        "requested_steps",
        "seed",
        "failure_injection",
    }
)
_FAILURE_FIELDS = frozenset({"kind", "at_step"})
_FAILURE_KINDS = frozenset({"none", "nan", "interrupt", "oom"})


class DLRunnerError(Exception):
    """Invalid input or an execution mode outside the Phase 6 L2 envelope."""


@dataclass(frozen=True)
class DLRunResult:
    """Immutable canonical runner artifact; accessors return fresh trees."""

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
    def failure_class(self) -> str:
        return self.artifact["failure"]["class"]

    @property
    def evidence_scope(self) -> str:
        return self.artifact["evidence_scope"]

    @property
    def budget_ledger(self) -> dict[str, Any]:
        return self.artifact["budget_ledger"]


def runner_identity() -> dict[str, str]:
    """Identity a caller must pin into ``DLRunManifest.runner``."""
    return {"name": RUNNER_NAME, "version": RUNNER_VERSION}


def run_fixture(
    manifest: DLRunManifest, fixture_payload: dict[str, Any]
) -> DLRunResult:
    """Validate or execute one bounded synthetic fixture.

    ``dry_run`` validates the full declaration and predicts the first budget
    cap without training or consuming budget. ``cpu_fixture`` executes a tiny
    standard-library MLP and records deterministic resource proxies. GPU modes
    and checkpoint resume fail closed until their later governed slices.

    Legal budget exhaustion and injected failures are returned as terminal
    artifacts. Structurally invalid input and unsupported capabilities raise
    :class:`DLRunnerError`.
    """
    manifest_data = _validate_manifest(manifest)
    fixture = _validate_fixture(fixture_payload)
    fixture_sha256 = canonical_sha256(fixture["payload"])
    plan = _plan_budget(manifest_data["budget"], fixture)
    mode = manifest_data["execution_mode"]

    if mode == "dry_run":
        status = "completed" if plan["exhausted_dimension"] == "none" else "budget_exhausted"
        failure = _budget_failure(plan["exhausted_dimension"], 0)
        return _build_result(
            manifest,
            manifest_data,
            fixture,
            fixture_sha256,
            status=status,
            failure=failure,
            consumed=_consumption(0, 0, plan["flops_per_step"]),
            metrics={},
        )

    model = _initialize_model(
        fixture["feature_count"], fixture["hidden_units"], fixture["seed"]
    )
    initial_loss = _loss(model, fixture["features"], fixture["targets"])
    final_loss = initial_loss
    executed_steps = 0
    failure = _no_failure()
    status = "completed"

    for step in range(1, plan["allowed_steps"] + 1):
        injected = fixture["failure_injection"]
        if injected["kind"] != "none" and injected["at_step"] == step:
            failure = _injected_failure(injected["kind"], step)
            status = "failed"
            break
        try:
            _train_step(
                model,
                fixture["features"],
                fixture["targets"],
                fixture["learning_rate"],
            )
            final_loss = _loss(model, fixture["features"], fixture["targets"])
        except ArithmeticError:
            failure = {
                "class": "numerical_failure",
                "code": "non-finite-training-state",
                "at_step": step,
                "synthetic_injection": False,
            }
            status = "failed"
            break
        executed_steps = step

    if status == "completed" and executed_steps < fixture["requested_steps"]:
        status = "budget_exhausted"
        failure = _budget_failure(plan["exhausted_dimension"], executed_steps)

    consumed = _consumption(
        len(fixture["features"]) if executed_steps else 0,
        executed_steps,
        plan["flops_per_step"],
    )
    metrics = {
        "initial_mean_squared_error": _rounded(initial_loss),
        "final_mean_squared_error": _rounded(final_loss),
    }
    return _build_result(
        manifest,
        manifest_data,
        fixture,
        fixture_sha256,
        status=status,
        failure=failure,
        consumed=consumed,
        metrics=metrics,
    )


def _validate_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, DLRunManifest):
        raise DLRunnerError("manifest must be a DLRunManifest")
    payload = manifest.payload
    identity = runner_identity()
    if payload["runner"]["name"] != identity["name"]:
        raise DLRunnerError("manifest runner.name does not match this runner")
    if payload["runner"]["version"] != identity["version"]:
        raise DLRunnerError("manifest runner.version does not match this runner")
    if payload["checkpoint_policy"]["resume"]["mode"] != "fresh":
        raise DLRunnerError("checkpoint resume is not implemented in Phase 6 L2")
    if payload["execution_mode"] not in {"dry_run", "cpu_fixture"}:
        raise DLRunnerError("Phase 6 L2 supports only dry_run and cpu_fixture")
    return payload


def _validate_fixture(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DLRunnerError("fixture_payload must be an object")
    try:
        snapshot = load_strict_json(canonical_bytes(payload))
    except CoreError as exc:
        raise DLRunnerError(f"fixture_payload is not strict JSON: {exc}") from exc
    if set(snapshot) != _FIXTURE_FIELDS:
        raise DLRunnerError(
            f"fixture fields must be exactly {sorted(_FIXTURE_FIELDS)}"
        )
    if snapshot["schema"] != _FIXTURE_SCHEMA:
        raise DLRunnerError(f"fixture.schema must be {_FIXTURE_SCHEMA}")
    fixture_id = snapshot["fixture_id"]
    if not isinstance(fixture_id, str) or not fixture_id or any(ch.isspace() for ch in fixture_id):
        raise DLRunnerError("fixture.fixture_id must be a non-whitespace token")

    features = snapshot["features"]
    targets = snapshot["targets"]
    if not isinstance(features, list) or not 1 <= len(features) <= _MAX_ROWS:
        raise DLRunnerError(f"features must contain 1..{_MAX_ROWS} rows")
    if not isinstance(targets, list) or len(targets) != len(features):
        raise DLRunnerError("targets must contain one value per feature row")

    numeric_features: list[list[float]] = []
    feature_count: int | None = None
    for row_index, row in enumerate(features):
        if not isinstance(row, list) or not 1 <= len(row) <= _MAX_FEATURES:
            raise DLRunnerError(
                f"features[{row_index}] must contain 1..{_MAX_FEATURES} values"
            )
        numeric_row = [
            _finite_number(value, f"features[{row_index}]") for value in row
        ]
        if feature_count is None:
            feature_count = len(numeric_row)
        elif len(numeric_row) != feature_count:
            raise DLRunnerError("all feature rows must have the same width")
        numeric_features.append(numeric_row)
    numeric_targets = [
        _finite_number(value, f"targets[{index}]")
        for index, value in enumerate(targets)
    ]

    hidden_units = _bounded_integer(
        snapshot["hidden_units"], "hidden_units", 1, _MAX_HIDDEN_UNITS
    )
    requested_steps = _bounded_integer(
        snapshot["requested_steps"], "requested_steps", 1, _MAX_STEPS
    )
    seed = _bounded_integer(snapshot["seed"], "seed", 0, 2**31 - 1)
    learning_rate = _finite_number(snapshot["learning_rate"], "learning_rate")
    if not 0.0 < learning_rate <= 1.0:
        raise DLRunnerError("learning_rate must be in (0, 1]")

    injection = snapshot["failure_injection"]
    if not isinstance(injection, dict) or set(injection) != _FAILURE_FIELDS:
        raise DLRunnerError(
            f"failure_injection fields must be exactly {sorted(_FAILURE_FIELDS)}"
        )
    kind = injection["kind"]
    if kind not in _FAILURE_KINDS:
        raise DLRunnerError(f"failure_injection.kind must be one of {sorted(_FAILURE_KINDS)}")
    at_step = injection["at_step"]
    if not isinstance(at_step, int) or isinstance(at_step, bool):
        raise DLRunnerError("failure_injection.at_step must be an integer")
    if kind == "none" and at_step != 0:
        raise DLRunnerError("failure_injection.at_step must be zero when kind is none")
    if kind != "none" and not 1 <= at_step <= requested_steps:
        raise DLRunnerError(
            "failure_injection.at_step must be inside the requested step range"
        )

    return {
        "payload": snapshot,
        "fixture_id": fixture_id,
        "features": numeric_features,
        "targets": numeric_targets,
        "feature_count": feature_count,
        "hidden_units": hidden_units,
        "learning_rate": learning_rate,
        "requested_steps": requested_steps,
        "seed": seed,
        "failure_injection": {"kind": kind, "at_step": at_step},
    }


def _finite_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise DLRunnerError(f"{path} contains a non-numeric value")
    try:
        numeric = float(value)
    except (OverflowError, ValueError) as exc:
        raise DLRunnerError(f"{path} contains an out-of-range number") from exc
    if not math.isfinite(numeric) or abs(numeric) > _MAX_ABS_VALUE:
        raise DLRunnerError(f"{path} contains a non-finite or oversized value")
    return numeric


def _bounded_integer(value: Any, path: str, lower: int, upper: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not lower <= value <= upper:
        raise DLRunnerError(f"{path} must be an integer in {lower}..{upper}")
    return value


def _plan_budget(budget: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    rows = len(fixture["features"])
    requested = fixture["requested_steps"]
    flops_per_step = rows * fixture["hidden_units"] * (
        fixture["feature_count"] * 6 + 8
    )
    enforceable_caps: list[tuple[int, str]] = []
    if budget["max_steps"] > 0:
        enforceable_caps.append((budget["max_steps"], "max_steps"))
    if budget["max_epochs"] > 0:
        enforceable_caps.append((budget["max_epochs"], "max_epochs"))
    if budget["max_flops"] > 0:
        enforceable_caps.append((int(budget["max_flops"] // flops_per_step), "max_flops"))
    if not enforceable_caps:
        raise DLRunnerError(
            "small-fixture execution requires a positive step, epoch, or FLOP cap"
        )
    if rows > budget["max_samples"]:
        return {
            "allowed_steps": 0,
            "exhausted_dimension": "max_samples",
            "flops_per_step": flops_per_step,
        }
    # ``min`` keeps the first item on a tie, giving the declared stable
    # priority max_steps -> max_epochs -> max_flops.
    allowed, dimension = min(enforceable_caps, key=lambda item: item[0])
    allowed = min(requested, allowed)
    return {
        "allowed_steps": allowed,
        "exhausted_dimension": "none" if allowed == requested else dimension,
        "flops_per_step": flops_per_step,
    }


def _initialize_model(width: int, hidden: int, seed: int) -> dict[str, Any]:
    return {
        "input_weights": [
            [_initial_value(seed, f"w1:{unit}:{index}") for index in range(width)]
            for unit in range(hidden)
        ],
        "hidden_bias": [0.05 for _ in range(hidden)],
        "output_weights": [
            _initial_value(seed, f"w2:{unit}") for unit in range(hidden)
        ],
        "output_bias": 0.0,
    }


def _initial_value(seed: int, label: str) -> float:
    digest = hashlib.sha256(f"{seed}:{label}".encode("ascii")).digest()
    unit = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
    return (unit - 0.5) * 0.2


def _predict(model: dict[str, Any], row: list[float]) -> tuple[float, list[float], list[float]]:
    pre_activation = [
        sum(weight * value for weight, value in zip(weights, row, strict=True)) + bias
        for weights, bias in zip(
            model["input_weights"], model["hidden_bias"], strict=True
        )
    ]
    hidden = [max(0.0, value) for value in pre_activation]
    prediction = (
        sum(
            weight * value
            for weight, value in zip(model["output_weights"], hidden, strict=True)
        )
        + model["output_bias"]
    )
    return prediction, pre_activation, hidden


def _loss(
    model: dict[str, Any], features: list[list[float]], targets: list[float]
) -> float:
    value = sum(
        (_predict(model, row)[0] - target) ** 2
        for row, target in zip(features, targets, strict=True)
    ) / len(features)
    if not math.isfinite(value):
        raise ArithmeticError("non-finite loss")
    return value


def _train_step(
    model: dict[str, Any],
    features: list[list[float]],
    targets: list[float],
    learning_rate: float,
) -> None:
    hidden_count = len(model["hidden_bias"])
    width = len(model["input_weights"][0])
    grad_input = [[0.0] * width for _ in range(hidden_count)]
    grad_hidden_bias = [0.0] * hidden_count
    grad_output = [0.0] * hidden_count
    grad_output_bias = 0.0
    scale = 2.0 / len(features)

    for row, target in zip(features, targets, strict=True):
        prediction, pre_activation, hidden = _predict(model, row)
        output_gradient = scale * (prediction - target)
        grad_output_bias += output_gradient
        for unit in range(hidden_count):
            grad_output[unit] += output_gradient * hidden[unit]
            if pre_activation[unit] <= 0.0:
                continue
            hidden_gradient = output_gradient * model["output_weights"][unit]
            grad_hidden_bias[unit] += hidden_gradient
            for index, value in enumerate(row):
                grad_input[unit][index] += hidden_gradient * value

    for unit in range(hidden_count):
        for index in range(width):
            model["input_weights"][unit][index] -= learning_rate * grad_input[unit][index]
        model["hidden_bias"][unit] -= learning_rate * grad_hidden_bias[unit]
        model["output_weights"][unit] -= learning_rate * grad_output[unit]
    model["output_bias"] -= learning_rate * grad_output_bias

    values = [model["output_bias"], *model["hidden_bias"], *model["output_weights"]]
    values.extend(value for row in model["input_weights"] for value in row)
    if not all(math.isfinite(value) and abs(value) <= _MAX_ABS_VALUE for value in values):
        raise ArithmeticError("non-finite model state")


def _consumption(samples: int, steps: int, flops_per_step: int) -> dict[str, int]:
    return {
        "samples": samples,
        "steps": steps,
        "epochs": steps,
        "tokens": 0,
        "flops_proxy": steps * flops_per_step,
    }


def _no_failure() -> dict[str, Any]:
    return {
        "class": "none",
        "code": "none",
        "at_step": 0,
        "synthetic_injection": False,
    }


def _budget_failure(dimension: str, at_step: int) -> dict[str, Any]:
    if dimension == "none":
        return _no_failure()
    return {
        "class": "budget_exhausted",
        "code": f"{dimension}-exhausted",
        "at_step": at_step,
        "synthetic_injection": False,
    }


def _injected_failure(kind: str, at_step: int) -> dict[str, Any]:
    mapping = {
        "nan": ("numerical_failure", "synthetic-nan-injection"),
        "interrupt": ("interrupted", "synthetic-interrupt-injection"),
        "oom": ("resource_exhausted", "synthetic-oom-injection"),
    }
    failure_class, code = mapping[kind]
    return {
        "class": failure_class,
        "code": code,
        "at_step": at_step,
        "synthetic_injection": True,
    }


def _build_result(
    manifest: DLRunManifest,
    manifest_data: dict[str, Any],
    fixture: dict[str, Any],
    fixture_sha256: str,
    *,
    status: str,
    failure: dict[str, Any],
    consumed: dict[str, int],
    metrics: dict[str, Any],
) -> DLRunResult:
    mode = manifest_data["execution_mode"]
    limitations = [
        "Hardware, framework, wall-clock time, and monetary cost were not observed."
    ]
    if mode == "dry_run":
        limitations.insert(0, "Dry-run validation executed no training.")
    else:
        limitations.insert(
            0,
            "Synthetic CPU fixture evidence supports runner engineering behavior only.",
        )
    if failure["synthetic_injection"]:
        limitations.append("The terminal failure was injected and was not an observed outage.")
    if status == "budget_exhausted":
        limitations.append("The requested fixture exceeded a declared deterministic cap.")

    core = {
        "schema": _RESULT_SCHEMA,
        "manifest_sha256": manifest.sha256,
        "run_id": manifest_data["run_id"],
        "study_id": manifest_data["study_id"],
        "case_sha256": manifest_data["case_sha256"],
        "runner": manifest_data["runner"],
        "execution": {
            "mode": mode,
            "observation": (
                "configuration_validated"
                if mode == "dry_run"
                else "synthetic_cpu_fixture"
            ),
            "hardware": "declared_not_observed",
            "framework": "not_loaded",
        },
        "fixture": {
            "fixture_id": fixture["fixture_id"],
            "content_sha256": fixture_sha256,
            "data_provenance": "synthetic",
            "rows": len(fixture["features"]),
            "feature_count": fixture["feature_count"],
            "hidden_units": fixture["hidden_units"],
            "requested_steps": fixture["requested_steps"],
            "seed": fixture["seed"],
            "failure_injection": fixture["failure_injection"],
        },
        "status": status,
        "failure": failure,
        "evidence_scope": (
            "configuration_only" if mode == "dry_run" else "synthetic_engineering"
        ),
        "budget_ledger": {
            "accounting": "cumulative_no_double_charge",
            "prior_consumption_sha256": None,
            "limits": manifest_data["budget"],
            "consumed": consumed,
            "cost_observation": "not_observed",
            "exhausted_dimension": (
                failure["code"].removesuffix("-exhausted")
                if failure["class"] == "budget_exhausted"
                else "none"
            ),
        },
        "metrics": metrics,
        "limitations": limitations,
    }
    identity_sha256 = canonical_sha256(core)
    artifact = {
        "result_id": f"dl-run-result-{identity_sha256[:16]}",
        **core,
    }
    return DLRunResult(_artifact_bytes=canonical_bytes(artifact))


def _rounded(value: float) -> float:
    if not math.isfinite(value):
        raise ArithmeticError("cannot serialize a non-finite metric")
    rounded = round(value, 12)
    return 0.0 if rounded == 0.0 else rounded


__all__ = ["DLRunResult", "DLRunnerError", "run_fixture", "runner_identity"]
