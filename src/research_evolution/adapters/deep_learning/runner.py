"""Deterministic Phase 6 runner for governed tiny CPU fixtures.

This is an in-process protocol machine, not a framework or GPU executor.  One
public function consumes a validated :class:`DLRunManifest` plus a bounded
synthetic regression fixture and returns one immutable canonical artifact.
The same implementation owns validation, deterministic tiny-MLP training,
budget accounting, terminal failures, checkpoint/recovery, and early stopping
so those rules do not spread across callers.

There is no filesystem, clock, environment, network, subprocess, global random
state, training-framework import, external checkpoint-store I/O, or hardware
probe.  Bounded checkpoint payloads are returned in memory.  Failure injection
is explicitly synthetic and can only support engineering tests.
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
RUNNER_VERSION = "0.2.0"

_LEGACY_RUNNER_VERSION = "0.1.0"
_SUPPORTED_RUNNER_VERSIONS = frozenset({_LEGACY_RUNNER_VERSION, RUNNER_VERSION})

_FIXTURE_SCHEMA = "synthetic-dl-fixture/v1"
_RESULT_SCHEMA = "synthetic-dl-run-result/v1"
_FIXTURE_SCHEMA_V2 = "synthetic-dl-fixture/v2"
_RESULT_SCHEMA_V2 = "synthetic-dl-run-result/v2"
_CHECKPOINT_SCHEMA = "synthetic-dl-checkpoint/v1"
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
_EARLY_STOPPING_FIELDS = frozenset(
    {"enabled", "patience", "min_delta", "warmup_steps"}
)
_FIXTURE_V2_FIELDS = _FIXTURE_FIELDS.union(
    {"validation_features", "validation_targets", "early_stopping"}
)
_CONSUMPTION_FIELDS = frozenset(
    {"samples", "steps", "epochs", "tokens", "flops_proxy"}
)
_CHECKPOINT_FIELDS = frozenset(
    {
        "schema",
        "checkpoint_id",
        "locator",
        "source_run_id",
        "source_manifest_sha256",
        "study_id",
        "case_sha256",
        "runner",
        "training_identity_sha256",
        "completed_steps",
        "completed_epochs",
        "consumed_budget",
        "model_state",
        "optimizer_state",
        "scheduler_state",
        "early_stopping_state",
        "validation_metric",
    }
)


class DLRunnerError(Exception):
    """Invalid input or an execution mode outside the synthetic envelope."""


@dataclass(frozen=True)
class DLRunResult:
    """Immutable canonical runner artifact; accessors return fresh trees."""

    _artifact_bytes: bytes
    _checkpoint_bytes: tuple[bytes, ...] = ()

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

    @property
    def checkpoint_payloads(self) -> tuple[dict[str, Any], ...]:
        """Return defensive copies of tiny in-memory checkpoint exports.

        The canonical result artifact contains locator/hash metadata only.
        A caller may persist these bounded synthetic payloads in an external
        artifact store; this runner itself performs no checkpoint I/O.
        """
        return tuple(load_strict_json(value) for value in self._checkpoint_bytes)


def runner_identity() -> dict[str, str]:
    """Identity a caller must pin into ``DLRunManifest.runner``."""
    return {"name": RUNNER_NAME, "version": RUNNER_VERSION}


def run_fixture(
    manifest: DLRunManifest,
    fixture_payload: dict[str, Any],
    *,
    checkpoint_payload: dict[str, Any] | None = None,
) -> DLRunResult:
    """Validate or execute one bounded synthetic fixture.

    ``dry_run`` validates the full declaration and predicts the first budget
    cap without training or consuming budget. ``cpu_fixture`` executes a tiny
    standard-library MLP and records deterministic resource proxies. Runner
    0.2.0 additionally accepts fixture v2 and an exact in-memory checkpoint;
    GPU modes and external checkpoint-store I/O remain fail-closed.

    Legal budget exhaustion and injected failures are returned as terminal
    artifacts. Structurally invalid input and unsupported capabilities raise
    :class:`DLRunnerError`.
    """
    manifest_data = _validate_manifest(manifest)
    if manifest_data["runner"]["version"] == RUNNER_VERSION:
        return _run_fixture_v2(
            manifest,
            manifest_data,
            fixture_payload,
            checkpoint_payload=checkpoint_payload,
        )
    if checkpoint_payload is not None:
        raise DLRunnerError("runner 0.1.0 does not accept checkpoint_payload")
    return _run_fixture_v1(manifest, manifest_data, fixture_payload)


def _run_fixture_v1(
    manifest: DLRunManifest,
    manifest_data: dict[str, Any],
    fixture_payload: dict[str, Any],
) -> DLRunResult:
    """Preserve the Phase 6 L2 artifact byte-for-byte for runner 0.1.0."""
    fixture = _validate_fixture(fixture_payload)
    fixture_sha256 = canonical_sha256(fixture["payload"])
    plan = _plan_budget(manifest_data["budget"], fixture)
    mode = manifest_data["execution_mode"]

    if mode == "dry_run":
        status = (
            "completed"
            if plan["exhausted_dimension"] == "none"
            else "budget_exhausted"
        )
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
    if payload["runner"]["version"] not in _SUPPORTED_RUNNER_VERSIONS:
        raise DLRunnerError("manifest runner.version is not supported by this runner")
    if (
        payload["runner"]["version"] == _LEGACY_RUNNER_VERSION
        and payload["checkpoint_policy"]["resume"]["mode"] != "fresh"
    ):
        raise DLRunnerError("checkpoint resume requires runner 0.2.0")
    if payload["execution_mode"] not in {"dry_run", "cpu_fixture"}:
        raise DLRunnerError("the fixture runner supports only dry_run and cpu_fixture")
    return payload


def _run_fixture_v2(
    manifest: DLRunManifest,
    manifest_data: dict[str, Any],
    fixture_payload: dict[str, Any],
    *,
    checkpoint_payload: dict[str, Any] | None,
) -> DLRunResult:
    fixture = _validate_fixture_v2(fixture_payload)
    _validate_v2_policy(manifest_data, fixture)
    fixture_sha256 = canonical_sha256(fixture["payload"])
    training_identity_sha256 = canonical_sha256(
        {
            key: value
            for key, value in fixture["payload"].items()
            if key not in {"requested_steps", "failure_injection"}
        }
    )
    flops_per_step = _flops_per_step(fixture)
    resume = manifest_data["checkpoint_policy"]["resume"]
    if resume["mode"] == "exact_checkpoint":
        if checkpoint_payload is None:
            raise DLRunnerError(
                "exact_checkpoint resume requires checkpoint_payload"
            )
        restored = _validate_checkpoint_payload(
            checkpoint_payload,
            manifest_data,
            fixture,
            training_identity_sha256,
            flops_per_step,
        )
    else:
        if checkpoint_payload is not None:
            raise DLRunnerError(
                "fresh execution must not receive checkpoint_payload"
            )
        restored = (
            _dry_state(fixture)
            if manifest_data["execution_mode"] == "dry_run"
            else _fresh_state(fixture)
        )

    plan = _plan_budget_v2(
        manifest_data["budget"],
        fixture,
        restored["consumed"],
        flops_per_step,
    )
    if manifest_data["execution_mode"] == "dry_run":
        status = (
            "completed"
            if plan["exhausted_dimension"] == "none"
            else "budget_exhausted"
        )
        return _build_result_v2(
            manifest,
            manifest_data,
            fixture,
            fixture_sha256,
            training_identity_sha256,
            status=status,
            failure=_budget_failure(plan["exhausted_dimension"], 0),
            consumed=restored["consumed"],
            segment_consumed=_consumption(0, 0, flops_per_step),
            initial_training_loss=None,
            final_training_loss=None,
            initial_validation_loss=None,
            final_validation_loss=None,
            early_state=restored["early_state"],
            checkpoint_refs=[],
            checkpoint_bytes=(),
        )

    model = restored["model"]
    initial_training_loss = _loss(
        model, fixture["features"], fixture["targets"]
    )
    initial_validation_loss = _loss(
        model,
        fixture["validation_features"],
        fixture["validation_targets"],
    )
    final_training_loss = initial_training_loss
    final_validation_loss = initial_validation_loss
    early_state = restored["early_state"]
    consumed_before = restored["consumed"]
    executed_segment_steps = 0
    failure = _no_failure()
    status = "completed"
    candidates: list[tuple[dict[str, Any], bytes]] = []

    if restored["checkpoint_ref"] is not None:
        early_state["best_checkpoint"] = restored["best_checkpoint"]
        candidates.append(
            (restored["checkpoint_ref"], restored["checkpoint_bytes"])
        )
    else:
        initial_reference, initial_payload = _make_checkpoint(
            manifest,
            manifest_data,
            fixture,
            training_identity_sha256,
            model,
            consumed_before,
            early_state,
            initial_validation_loss,
            best_checkpoint=None,
        )
        candidates.append((initial_reference, initial_payload))
        early_state["best_checkpoint"] = initial_reference

    for absolute_step in range(
        consumed_before["steps"] + 1,
        consumed_before["steps"] + plan["allowed_steps"] + 1,
    ):
        injected = fixture["failure_injection"]
        if injected["kind"] != "none" and injected["at_step"] == absolute_step:
            failure = _injected_failure(injected["kind"], absolute_step)
            status = "failed"
            break
        try:
            _train_step(
                model,
                fixture["features"],
                fixture["targets"],
                fixture["learning_rate"],
            )
            final_training_loss = _loss(
                model, fixture["features"], fixture["targets"]
            )
            final_validation_loss = _loss(
                model,
                fixture["validation_features"],
                fixture["validation_targets"],
            )
        except ArithmeticError:
            failure = {
                "class": "numerical_failure",
                "code": "non-finite-training-state",
                "at_step": absolute_step,
                "synthetic_injection": False,
            }
            status = "failed"
            break

        executed_segment_steps += 1
        cumulative = _cumulative_consumption(
            consumed_before,
            len(fixture["features"]),
            executed_segment_steps,
            flops_per_step,
        )
        improved = _update_early_stopping(
            early_state,
            final_validation_loss,
            absolute_step,
            fixture["early_stopping"],
        )
        reference, payload_bytes = _make_checkpoint(
            manifest,
            manifest_data,
            fixture,
            training_identity_sha256,
            model,
            cumulative,
            early_state,
            final_validation_loss,
            best_checkpoint=None if improved else early_state["best_checkpoint"],
        )
        candidates.append((reference, payload_bytes))
        if improved:
            early_state["best_checkpoint"] = reference

        if _should_early_stop(early_state, fixture["early_stopping"]):
            status = "early_stopped"
            break

    consumed = _cumulative_consumption(
        consumed_before,
        len(fixture["features"]),
        executed_segment_steps,
        flops_per_step,
    )
    if (
        status == "completed"
        and consumed["steps"] < fixture["requested_steps"]
    ):
        status = "budget_exhausted"
        failure = _budget_failure(
            plan["exhausted_dimension"], consumed["steps"]
        )

    checkpoint_refs, checkpoint_bytes = _retain_checkpoints(
        candidates,
        manifest_data["checkpoint_policy"],
        early_state["best_checkpoint"],
    )
    return _build_result_v2(
        manifest,
        manifest_data,
        fixture,
        fixture_sha256,
        training_identity_sha256,
        status=status,
        failure=failure,
        consumed=consumed,
        segment_consumed=_consumption(
            len(fixture["features"]) if executed_segment_steps else 0,
            executed_segment_steps,
            flops_per_step,
        ),
        initial_training_loss=initial_training_loss,
        final_training_loss=final_training_loss,
        initial_validation_loss=initial_validation_loss,
        final_validation_loss=final_validation_loss,
        early_state=early_state,
        checkpoint_refs=checkpoint_refs,
        checkpoint_bytes=checkpoint_bytes,
    )


def _validate_fixture_v2(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DLRunnerError("fixture_payload must be an object")
    try:
        snapshot = load_strict_json(canonical_bytes(payload))
    except CoreError as exc:
        raise DLRunnerError(f"fixture_payload is not strict JSON: {exc}") from exc
    if set(snapshot) != _FIXTURE_V2_FIELDS:
        raise DLRunnerError(
            f"fixture v2 fields must be exactly {sorted(_FIXTURE_V2_FIELDS)}"
        )
    if snapshot["schema"] != _FIXTURE_SCHEMA_V2:
        raise DLRunnerError(f"fixture.schema must be {_FIXTURE_SCHEMA_V2}")

    legacy_payload = {
        key: value for key, value in snapshot.items() if key in _FIXTURE_FIELDS
    }
    legacy_payload["schema"] = _FIXTURE_SCHEMA
    validated = _validate_fixture(legacy_payload)
    validation_features = snapshot["validation_features"]
    validation_targets = snapshot["validation_targets"]
    if not isinstance(validation_features, list) or not 1 <= len(
        validation_features
    ) <= _MAX_ROWS:
        raise DLRunnerError(
            f"validation_features must contain 1..{_MAX_ROWS} rows"
        )
    if not isinstance(validation_targets, list) or len(
        validation_targets
    ) != len(validation_features):
        raise DLRunnerError(
            "validation_targets must contain one value per validation row"
        )
    numeric_validation: list[list[float]] = []
    for row_index, row in enumerate(validation_features):
        if not isinstance(row, list) or len(row) != validated["feature_count"]:
            raise DLRunnerError(
                "validation rows must match the training feature width"
            )
        numeric_validation.append(
            [
                _finite_number(value, f"validation_features[{row_index}]")
                for value in row
            ]
        )
    numeric_validation_targets = [
        _finite_number(value, f"validation_targets[{index}]")
        for index, value in enumerate(validation_targets)
    ]

    policy = snapshot["early_stopping"]
    if not isinstance(policy, dict) or set(policy) != _EARLY_STOPPING_FIELDS:
        raise DLRunnerError(
            "early_stopping fields must be exactly "
            f"{sorted(_EARLY_STOPPING_FIELDS)}"
        )
    if not isinstance(policy["enabled"], bool):
        raise DLRunnerError("early_stopping.enabled must be boolean")
    patience = _bounded_integer(
        policy["patience"], "early_stopping.patience", 0, _MAX_STEPS
    )
    warmup_steps = _bounded_integer(
        policy["warmup_steps"],
        "early_stopping.warmup_steps",
        0,
        validated["requested_steps"],
    )
    min_delta = _finite_number(
        policy["min_delta"], "early_stopping.min_delta"
    )
    if min_delta < 0:
        raise DLRunnerError("early_stopping.min_delta must not be negative")
    if policy["enabled"] and patience == 0:
        raise DLRunnerError(
            "enabled early stopping requires positive patience"
        )
    if not policy["enabled"] and any(
        value != 0 for value in (patience, warmup_steps, min_delta)
    ):
        raise DLRunnerError(
            "disabled early stopping requires zero patience/min_delta/warmup"
        )

    validated.update(
        {
            "payload": snapshot,
            "validation_features": numeric_validation,
            "validation_targets": numeric_validation_targets,
            "early_stopping": {
                "enabled": policy["enabled"],
                "patience": patience,
                "min_delta": min_delta,
                "warmup_steps": warmup_steps,
            },
        }
    )
    return validated


def _validate_v2_policy(
    manifest: dict[str, Any], fixture: dict[str, Any]
) -> None:
    checkpoint = manifest["checkpoint_policy"]
    if checkpoint["selection_metric"] != "validation_loss":
        raise DLRunnerError(
            "runner 0.2.0 supports only validation_loss checkpoint selection"
        )
    if checkpoint["selection_direction"] != "minimize":
        raise DLRunnerError(
            "runner 0.2.0 supports only minimize checkpoint selection"
        )
    if manifest["optimizer"]["name"] != "sgd":
        raise DLRunnerError("runner 0.2.0 supports only the synthetic SGD optimizer")
    if manifest["scheduler"]["name"] != "none":
        raise DLRunnerError("runner 0.2.0 does not execute scheduler state")
    if not checkpoint["save_optimizer_state"]:
        raise DLRunnerError("runner 0.2.0 checkpoints require optimizer state")
    if checkpoint["save_scheduler_state"]:
        raise DLRunnerError("runner 0.2.0 must not save scheduler state")
    if fixture["early_stopping"]["enabled"] and checkpoint["retention"] not in {
        "best_and_last",
        "all",
    }:
        raise DLRunnerError(
            "early stopping requires best_and_last or all checkpoint retention"
        )


def _flops_per_step(fixture: dict[str, Any]) -> int:
    return len(fixture["features"]) * fixture["hidden_units"] * (
        fixture["feature_count"] * 6 + 8
    )


def _plan_budget_v2(
    budget: dict[str, Any],
    fixture: dict[str, Any],
    prior: dict[str, int],
    flops_per_step: int,
) -> dict[str, Any]:
    rows = len(fixture["features"])
    if prior["steps"] > fixture["requested_steps"]:
        raise DLRunnerError(
            "checkpoint consumption exceeds fixture requested_steps"
        )
    if rows > budget["max_samples"]:
        return {"allowed_steps": 0, "exhausted_dimension": "max_samples"}
    remaining_requested = fixture["requested_steps"] - prior["steps"]
    caps: list[tuple[int, str]] = []
    if budget["max_steps"] > 0:
        caps.append((budget["max_steps"] - prior["steps"], "max_steps"))
    if budget["max_epochs"] > 0:
        caps.append((budget["max_epochs"] - prior["epochs"], "max_epochs"))
    if budget["max_flops"] > 0:
        remaining_flops = budget["max_flops"] - prior["flops_proxy"]
        caps.append((int(remaining_flops // flops_per_step), "max_flops"))
    if not caps:
        raise DLRunnerError(
            "small-fixture execution requires a positive step, epoch, or FLOP cap"
        )
    normalized = [(max(0, value), name) for value, name in caps]
    allowed, dimension = min(normalized, key=lambda item: item[0])
    allowed = min(remaining_requested, allowed)
    return {
        "allowed_steps": allowed,
        "exhausted_dimension": (
            "none" if allowed == remaining_requested else dimension
        ),
    }


def _fresh_state(fixture: dict[str, Any]) -> dict[str, Any]:
    model = _initialize_model(
        fixture["feature_count"], fixture["hidden_units"], fixture["seed"]
    )
    best_metric = _loss(
        model,
        fixture["validation_features"],
        fixture["validation_targets"],
    )
    return {
        "model": model,
        "consumed": _consumption(0, 0, _flops_per_step(fixture)),
        "early_state": {
            "best_metric": _rounded(best_metric),
            "best_step": 0,
            "non_improving_steps": 0,
            "best_checkpoint": None,
        },
        "checkpoint_ref": None,
        "best_checkpoint": None,
    }


def _dry_state(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": None,
        "consumed": _consumption(0, 0, _flops_per_step(fixture)),
        "early_state": {
            "best_metric": None,
            "best_step": 0,
            "non_improving_steps": 0,
            "best_checkpoint": None,
        },
        "checkpoint_ref": None,
        "best_checkpoint": None,
    }


def _validate_checkpoint_payload(
    payload: Any,
    manifest: dict[str, Any],
    fixture: dict[str, Any],
    training_identity_sha256: str,
    flops_per_step: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DLRunnerError("checkpoint_payload must be an object")
    try:
        snapshot = load_strict_json(canonical_bytes(payload))
    except CoreError as exc:
        raise DLRunnerError(f"checkpoint_payload is not strict JSON: {exc}") from exc
    if set(snapshot) != _CHECKPOINT_FIELDS:
        raise DLRunnerError(
            f"checkpoint fields must be exactly {sorted(_CHECKPOINT_FIELDS)}"
        )
    if snapshot["schema"] != _CHECKPOINT_SCHEMA:
        raise DLRunnerError(f"checkpoint.schema must be {_CHECKPOINT_SCHEMA}")

    resume = manifest["checkpoint_policy"]["resume"]
    content_sha256 = canonical_sha256(snapshot)
    equality_checks = {
        "checkpoint_id": resume["checkpoint_id"],
        "locator": resume["locator"],
        "source_run_id": resume["source_run_id"],
        "study_id": manifest["study_id"],
        "case_sha256": manifest["case_sha256"],
        "runner": manifest["runner"],
        "training_identity_sha256": training_identity_sha256,
        "completed_steps": resume["completed_steps"],
        "completed_epochs": resume["completed_epochs"],
    }
    for field, expected in equality_checks.items():
        if snapshot[field] != expected:
            raise DLRunnerError(
                f"checkpoint {field} does not match the resume declaration"
            )
    if content_sha256 != resume["content_sha256"]:
        raise DLRunnerError("checkpoint content hash does not match the manifest")

    consumed = _validate_consumption(
        snapshot["consumed_budget"], fixture, flops_per_step
    )
    consumed_sha256 = canonical_sha256(consumed)
    if consumed_sha256 != resume["consumed_budget_sha256"]:
        raise DLRunnerError("checkpoint consumed budget hash does not match")
    if consumed["steps"] < snapshot["completed_steps"]:
        raise DLRunnerError(
            "checkpoint model progress cannot exceed cumulative consumed steps"
        )
    if consumed["epochs"] < snapshot["completed_epochs"]:
        raise DLRunnerError(
            "checkpoint model epochs cannot exceed cumulative consumed epochs"
        )

    optimizer = snapshot["optimizer_state"]
    expected_optimizer = {
        "name": "synthetic-sgd",
        "config_sha256": manifest["optimizer"]["config_sha256"],
        "learning_rate": _rounded(fixture["learning_rate"]),
    }
    if canonical_sha256(optimizer) != canonical_sha256(expected_optimizer):
        raise DLRunnerError("checkpoint optimizer state does not match this run")
    if canonical_sha256(optimizer) != resume["optimizer_state_sha256"]:
        raise DLRunnerError("checkpoint optimizer state hash does not match")
    if snapshot["scheduler_state"] is not None:
        raise DLRunnerError("runner 0.2.0 checkpoint scheduler state must be null")

    model = _validate_model_state(snapshot["model_state"], fixture)
    validation_metric = _finite_number(
        snapshot["validation_metric"], "checkpoint.validation_metric"
    )
    observed_metric = _rounded(
        _loss(
            model,
            fixture["validation_features"],
            fixture["validation_targets"],
        )
    )
    if _rounded(validation_metric) != observed_metric:
        raise DLRunnerError("checkpoint validation metric does not match model state")
    source_manifest_sha256 = snapshot["source_manifest_sha256"]
    if not _is_sha256(source_manifest_sha256):
        raise DLRunnerError("checkpoint source_manifest_sha256 is invalid")
    expected_id = _checkpoint_id(
        snapshot["source_run_id"],
        source_manifest_sha256,
        training_identity_sha256,
        snapshot["completed_steps"],
        consumed,
        model,
        validation_metric,
    )
    if snapshot["checkpoint_id"] != expected_id:
        raise DLRunnerError("checkpoint_id is inconsistent with checkpoint state")
    expected_locator = f"checkpoint://{snapshot['source_run_id']}/{expected_id}"
    if snapshot["locator"] != expected_locator:
        raise DLRunnerError("checkpoint locator is inconsistent with checkpoint state")

    current_reference = _checkpoint_reference(
        snapshot,
        content_sha256,
        consumed_sha256,
        canonical_sha256(optimizer),
    )
    early_state = _validate_early_state(
        snapshot["early_stopping_state"],
        snapshot["completed_steps"],
        validation_metric,
        current_reference,
    )
    return {
        "model": model,
        "consumed": consumed,
        "early_state": early_state,
        "checkpoint_ref": current_reference,
        "best_checkpoint": early_state["best_checkpoint"],
        "checkpoint_bytes": canonical_bytes(snapshot),
    }


def _validate_consumption(
    value: Any, fixture: dict[str, Any], flops_per_step: int
) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != _CONSUMPTION_FIELDS:
        raise DLRunnerError(
            f"checkpoint consumption fields must be {sorted(_CONSUMPTION_FIELDS)}"
        )
    result: dict[str, int] = {}
    for field in _CONSUMPTION_FIELDS:
        item = value[field]
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise DLRunnerError(
                f"checkpoint consumed_budget.{field} must be non-negative integer"
            )
        result[field] = item
    rows = len(fixture["features"])
    expected_samples = rows if result["steps"] else 0
    if result["samples"] != expected_samples:
        raise DLRunnerError("checkpoint sample consumption is inconsistent")
    if result["epochs"] != result["steps"] or result["tokens"] != 0:
        raise DLRunnerError("checkpoint epoch/token consumption is inconsistent")
    if result["flops_proxy"] != result["steps"] * flops_per_step:
        raise DLRunnerError("checkpoint FLOP consumption is inconsistent")
    return result


def _validate_model_state(
    value: Any, fixture: dict[str, Any]
) -> dict[str, Any]:
    fields = {"input_weights", "hidden_bias", "output_weights", "output_bias"}
    if not isinstance(value, dict) or set(value) != fields:
        raise DLRunnerError("checkpoint model_state has an invalid shape")
    hidden = fixture["hidden_units"]
    width = fixture["feature_count"]
    input_weights = value["input_weights"]
    hidden_bias = value["hidden_bias"]
    output_weights = value["output_weights"]
    if not isinstance(input_weights, list) or len(input_weights) != hidden:
        raise DLRunnerError("checkpoint input_weights have an invalid shape")
    numeric_input: list[list[float]] = []
    for unit, row in enumerate(input_weights):
        if not isinstance(row, list) or len(row) != width:
            raise DLRunnerError("checkpoint input_weights have an invalid shape")
        numeric_input.append(
            [
                _finite_number(item, f"checkpoint.input_weights[{unit}]")
                for item in row
            ]
        )
    if not isinstance(hidden_bias, list) or len(hidden_bias) != hidden:
        raise DLRunnerError("checkpoint hidden_bias has an invalid shape")
    if not isinstance(output_weights, list) or len(output_weights) != hidden:
        raise DLRunnerError("checkpoint output_weights have an invalid shape")
    return {
        "input_weights": numeric_input,
        "hidden_bias": [
            _finite_number(item, "checkpoint.hidden_bias")
            for item in hidden_bias
        ],
        "output_weights": [
            _finite_number(item, "checkpoint.output_weights")
            for item in output_weights
        ],
        "output_bias": _finite_number(
            value["output_bias"], "checkpoint.output_bias"
        ),
    }


def _validate_early_state(
    value: Any,
    completed_steps: int,
    validation_metric: float,
    current_reference: dict[str, Any],
) -> dict[str, Any]:
    fields = {
        "best_metric",
        "best_step",
        "non_improving_steps",
        "best_checkpoint",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise DLRunnerError("checkpoint early_stopping_state has invalid fields")
    best_metric = _finite_number(value["best_metric"], "checkpoint.best_metric")
    best_step = _bounded_integer(
        value["best_step"], "checkpoint.best_step", 0, completed_steps
    )
    non_improving = _bounded_integer(
        value["non_improving_steps"],
        "checkpoint.non_improving_steps",
        0,
        _MAX_STEPS,
    )
    best_reference = value["best_checkpoint"]
    if best_reference is None:
        if best_step != completed_steps or _rounded(best_metric) != _rounded(
            validation_metric
        ):
            raise DLRunnerError(
                "null best checkpoint is valid only when the current state is best"
            )
        best_reference = current_reference
    else:
        best_reference = _validate_checkpoint_reference(best_reference)
        if _rounded(best_reference["validation_loss"]) != _rounded(best_metric):
            raise DLRunnerError("best checkpoint metric does not match early state")
    return {
        "best_metric": _rounded(best_metric),
        "best_step": best_step,
        "non_improving_steps": non_improving,
        "best_checkpoint": best_reference,
    }


def _validate_checkpoint_reference(value: Any) -> dict[str, Any]:
    required = {
        "checkpoint_id",
        "locator",
        "content_sha256",
        "source_run_id",
        "completed_steps",
        "completed_epochs",
        "consumed_budget_sha256",
        "optimizer_state_sha256",
        "validation_loss",
        "resume_eligible",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise DLRunnerError("checkpoint reference has invalid fields")
    for field in (
        "checkpoint_id",
        "locator",
        "source_run_id",
        "content_sha256",
        "consumed_budget_sha256",
        "optimizer_state_sha256",
    ):
        if not isinstance(value[field], str) or not value[field]:
            raise DLRunnerError(f"checkpoint reference {field} is invalid")
    if not value["locator"].startswith(("artifact://", "checkpoint://")):
        raise DLRunnerError("checkpoint reference locator is invalid")
    for field in ("content_sha256", "consumed_budget_sha256", "optimizer_state_sha256"):
        if len(value[field]) != 64 or any(
            char not in "0123456789abcdef" for char in value[field]
        ):
            raise DLRunnerError(f"checkpoint reference {field} is invalid")
    for field in ("completed_steps", "completed_epochs"):
        if not isinstance(value[field], int) or isinstance(value[field], bool):
            raise DLRunnerError(f"checkpoint reference {field} is invalid")
        if value[field] < 0:
            raise DLRunnerError(f"checkpoint reference {field} is invalid")
    metric = _finite_number(value["validation_loss"], "checkpoint.validation_loss")
    if value["resume_eligible"] is not True:
        raise DLRunnerError("checkpoint reference must be resume eligible")
    result = dict(value)
    result["validation_loss"] = _rounded(metric)
    return result


def _model_snapshot(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_weights": [list(row) for row in model["input_weights"]],
        "hidden_bias": list(model["hidden_bias"]),
        "output_weights": list(model["output_weights"]),
        "output_bias": model["output_bias"],
    }


def _make_checkpoint(
    manifest: DLRunManifest,
    manifest_data: dict[str, Any],
    fixture: dict[str, Any],
    training_identity_sha256: str,
    model: dict[str, Any],
    consumed: dict[str, int],
    early_state: dict[str, Any],
    validation_loss: float,
    *,
    best_checkpoint: dict[str, Any] | None,
) -> tuple[dict[str, Any], bytes]:
    optimizer_state = {
        "name": "synthetic-sgd",
        "config_sha256": manifest_data["optimizer"]["config_sha256"],
        "learning_rate": _rounded(fixture["learning_rate"]),
    }
    early_payload = {
        "best_metric": early_state["best_metric"],
        "best_step": early_state["best_step"],
        "non_improving_steps": early_state["non_improving_steps"],
        "best_checkpoint": best_checkpoint,
    }
    checkpoint_id = _checkpoint_id(
        manifest_data["run_id"],
        manifest.sha256,
        training_identity_sha256,
        consumed["steps"],
        consumed,
        model,
        validation_loss,
    )
    locator = f"checkpoint://{manifest_data['run_id']}/{checkpoint_id}"
    payload = {
        "schema": _CHECKPOINT_SCHEMA,
        "checkpoint_id": checkpoint_id,
        "locator": locator,
        "source_run_id": manifest_data["run_id"],
        "source_manifest_sha256": manifest.sha256,
        "study_id": manifest_data["study_id"],
        "case_sha256": manifest_data["case_sha256"],
        "runner": manifest_data["runner"],
        "training_identity_sha256": training_identity_sha256,
        "completed_steps": consumed["steps"],
        "completed_epochs": consumed["epochs"],
        "consumed_budget": consumed,
        "model_state": _model_snapshot(model),
        "optimizer_state": optimizer_state,
        "scheduler_state": None,
        "early_stopping_state": early_payload,
        "validation_metric": _rounded(validation_loss),
    }
    payload_bytes = canonical_bytes(payload)
    reference = _checkpoint_reference(
        payload,
        hashlib.sha256(payload_bytes).hexdigest(),
        canonical_sha256(consumed),
        canonical_sha256(optimizer_state),
    )
    return reference, payload_bytes


def _checkpoint_reference(
    payload: dict[str, Any],
    content_sha256: str,
    consumed_budget_sha256: str,
    optimizer_state_sha256: str,
) -> dict[str, Any]:
    return {
        "checkpoint_id": payload["checkpoint_id"],
        "locator": payload["locator"],
        "content_sha256": content_sha256,
        "source_run_id": payload["source_run_id"],
        "completed_steps": payload["completed_steps"],
        "completed_epochs": payload["completed_epochs"],
        "consumed_budget_sha256": consumed_budget_sha256,
        "optimizer_state_sha256": optimizer_state_sha256,
        "validation_loss": _rounded(payload["validation_metric"]),
        "resume_eligible": True,
    }


def _checkpoint_id(
    source_run_id: str,
    source_manifest_sha256: str,
    training_identity_sha256: str,
    completed_steps: int,
    consumed: dict[str, int],
    model: dict[str, Any],
    validation_loss: float,
) -> str:
    identity_core = {
        "source_run_id": source_run_id,
        "source_manifest_sha256": source_manifest_sha256,
        "training_identity_sha256": training_identity_sha256,
        "completed_steps": completed_steps,
        "consumed_budget_sha256": canonical_sha256(consumed),
        "model_state_sha256": canonical_sha256(_model_snapshot(model)),
        "validation_loss": _rounded(validation_loss),
    }
    return f"dl-checkpoint-{canonical_sha256(identity_core)[:16]}"


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _cumulative_consumption(
    prior: dict[str, int],
    rows: int,
    segment_steps: int,
    flops_per_step: int,
) -> dict[str, int]:
    steps = prior["steps"] + segment_steps
    return {
        "samples": rows if steps else 0,
        "steps": steps,
        "epochs": prior["epochs"] + segment_steps,
        "tokens": prior["tokens"],
        "flops_proxy": prior["flops_proxy"] + segment_steps * flops_per_step,
    }


def _update_early_stopping(
    state: dict[str, Any],
    metric: float,
    step: int,
    policy: dict[str, Any],
) -> bool:
    rounded_metric = _rounded(metric)
    improved = rounded_metric < state["best_metric"] - policy["min_delta"]
    if improved:
        state["best_metric"] = rounded_metric
        state["best_step"] = step
        state["non_improving_steps"] = 0
        return True
    if policy["enabled"] and step > policy["warmup_steps"]:
        state["non_improving_steps"] += 1
    return False


def _should_early_stop(
    state: dict[str, Any], policy: dict[str, Any]
) -> bool:
    return (
        policy["enabled"]
        and state["non_improving_steps"] >= policy["patience"]
    )


def _retain_checkpoints(
    candidates: list[tuple[dict[str, Any], bytes]],
    policy: dict[str, Any],
    best_checkpoint: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], tuple[bytes, ...]]:
    retention = policy["retention"]
    if retention == "none":
        return [], ()
    by_id = {
        reference["checkpoint_id"]: (reference, payload)
        for reference, payload in candidates
    }
    selected_ids: list[str] = []
    if retention == "all":
        selected_ids = [reference["checkpoint_id"] for reference, _ in candidates]
    elif retention == "last_n":
        selected_ids = [
            reference["checkpoint_id"]
            for reference, _ in candidates[-policy["max_retained"] :]
        ]
    elif retention == "last":
        if candidates:
            selected_ids = [candidates[-1][0]["checkpoint_id"]]
    elif retention == "best_and_last":
        if best_checkpoint is not None:
            selected_ids.append(best_checkpoint["checkpoint_id"])
        if candidates:
            last_id = candidates[-1][0]["checkpoint_id"]
            if last_id not in selected_ids:
                selected_ids.append(last_id)

    references: list[dict[str, Any]] = []
    payloads: list[bytes] = []
    last_id = candidates[-1][0]["checkpoint_id"] if candidates else None
    best_id = best_checkpoint["checkpoint_id"] if best_checkpoint else None
    for checkpoint_id in selected_ids:
        if checkpoint_id in by_id:
            reference, payload = by_id[checkpoint_id]
            payloads.append(payload)
        elif best_checkpoint is not None and checkpoint_id == best_id:
            reference = best_checkpoint
        else:
            continue
        roles = []
        if checkpoint_id == best_id:
            roles.append("best")
        if checkpoint_id == last_id:
            roles.append("last")
        references.append({**reference, "roles": roles})
    return references, tuple(payloads)


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
    if (
        not isinstance(fixture_id, str)
        or not fixture_id
        or any(ch.isspace() for ch in fixture_id)
    ):
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
        raise DLRunnerError(
            "failure_injection.kind must be one of "
            f"{sorted(_FAILURE_KINDS)}"
        )
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
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not lower <= value <= upper
    ):
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
        enforceable_caps.append(
            (int(budget["max_flops"] // flops_per_step), "max_flops")
        )
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


def _predict(
    model: dict[str, Any], row: list[float]
) -> tuple[float, list[float], list[float]]:
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
            model["input_weights"][unit][index] -= (
                learning_rate * grad_input[unit][index]
            )
        model["hidden_bias"][unit] -= learning_rate * grad_hidden_bias[unit]
        model["output_weights"][unit] -= learning_rate * grad_output[unit]
    model["output_bias"] -= learning_rate * grad_output_bias

    values = [model["output_bias"], *model["hidden_bias"], *model["output_weights"]]
    values.extend(value for row in model["input_weights"] for value in row)
    if not all(
        math.isfinite(value) and abs(value) <= _MAX_ABS_VALUE
        for value in values
    ):
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
        limitations.append(
            "The terminal failure was injected and was not an observed outage."
        )
    if status == "budget_exhausted":
        limitations.append(
            "The requested fixture exceeded a declared deterministic cap."
        )

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


def _build_result_v2(
    manifest: DLRunManifest,
    manifest_data: dict[str, Any],
    fixture: dict[str, Any],
    fixture_sha256: str,
    training_identity_sha256: str,
    *,
    status: str,
    failure: dict[str, Any],
    consumed: dict[str, int],
    segment_consumed: dict[str, int],
    initial_training_loss: float | None,
    final_training_loss: float | None,
    initial_validation_loss: float | None,
    final_validation_loss: float | None,
    early_state: dict[str, Any],
    checkpoint_refs: list[dict[str, Any]],
    checkpoint_bytes: tuple[bytes, ...],
) -> DLRunResult:
    mode = manifest_data["execution_mode"]
    resume = manifest_data["checkpoint_policy"]["resume"]
    prior_sha256 = (
        resume["consumed_budget_sha256"]
        if resume["mode"] == "exact_checkpoint"
        else None
    )
    metrics = {}
    if initial_training_loss is not None:
        metrics = {
            "initial_training_mean_squared_error": _rounded(
                initial_training_loss
            ),
            "final_training_mean_squared_error": _rounded(final_training_loss),
            "initial_validation_loss": _rounded(initial_validation_loss),
            "final_validation_loss": _rounded(final_validation_loss),
        }
    policy_best = early_state["best_checkpoint"]
    retained_policy_best = (
        next(
            (
                checkpoint
                for checkpoint in checkpoint_refs
                if policy_best is not None
                and checkpoint["checkpoint_id"] == policy_best["checkpoint_id"]
            ),
            None,
        )
        if checkpoint_refs
        else None
    )
    best_checkpoint = retained_policy_best
    if best_checkpoint is None and checkpoint_refs:
        best_checkpoint = min(
            checkpoint_refs,
            key=lambda checkpoint: checkpoint["validation_loss"],
        )
    limitations = [
        "Hardware, framework, wall-clock time, and monetary cost were not observed.",
        "Checkpoint payloads were returned in memory only; no external "
        "artifact store was observed.",
    ]
    if mode == "dry_run":
        limitations.insert(0, "Dry-run validation executed no training.")
    else:
        limitations.insert(
            0,
            "Synthetic CPU fixture evidence supports runner engineering behavior only.",
        )
    if failure["synthetic_injection"]:
        limitations.append(
            "The terminal failure was injected and was not an observed outage."
        )
    if status == "budget_exhausted":
        limitations.append(
            "The requested fixture exceeded a declared deterministic cap."
        )
    if status == "early_stopped":
        limitations.append(
            "Early stopping used only the synthetic validation partition."
        )

    core = {
        "schema": _RESULT_SCHEMA_V2,
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
            "training_identity_sha256": training_identity_sha256,
            "data_provenance": "synthetic",
            "training_rows": len(fixture["features"]),
            "validation_rows": len(fixture["validation_features"]),
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
            "prior_consumption_sha256": prior_sha256,
            "limits": manifest_data["budget"],
            "consumed": consumed,
            "segment_consumed": segment_consumed,
            "cost_observation": "not_observed",
            "exhausted_dimension": (
                failure["code"].removesuffix("-exhausted")
                if failure["class"] == "budget_exhausted"
                else "none"
            ),
        },
        "metrics": metrics,
        "early_stopping": {
            "policy": fixture["early_stopping"],
            "best_metric": early_state["best_metric"],
            "best_step": early_state["best_step"],
            "non_improving_steps": early_state["non_improving_steps"],
            "triggered": status == "early_stopped",
        },
        "checkpointing": {
            "artifact_reference": "external_locator_and_hash_only",
            "retention": manifest_data["checkpoint_policy"]["retention"],
            "selected_checkpoint": best_checkpoint,
            "retained": checkpoint_refs,
            "payload_transport": "in_memory_not_persisted",
        },
        "limitations": limitations,
    }
    identity_sha256 = canonical_sha256(core)
    artifact = {"result_id": f"dl-run-result-{identity_sha256[:16]}", **core}
    return DLRunResult(
        _artifact_bytes=canonical_bytes(artifact),
        _checkpoint_bytes=checkpoint_bytes,
    )


def _rounded(value: float) -> float:
    if not math.isfinite(value):
        raise ArithmeticError("cannot serialize a non-finite metric")
    rounded = round(value, 12)
    return 0.0 if rounded == 0.0 else rounded


__all__ = ["DLRunResult", "DLRunnerError", "run_fixture", "runner_identity"]
