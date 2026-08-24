"""Bounded real PyTorch/CUDA engineering observation.

This module is deliberately a concrete deep module, not a framework plug-in
seam: only one real implementation exists.  The public runner validates a
``DLRunManifest`` and one tiny synthetic fixture, lazily imports PyTorch,
checks the declared runtime against observations, executes on ``cuda:0``, and
returns a hash-bound ``dl-run-observation/v1`` record.

The evidence ceiling is intentionally narrow.  A completed record establishes
one real framework/hardware engineering execution only.  It does not establish
real-data acceptance, scientific or predictive validity, checkpoint recovery,
cross-hardware portability, production readiness, or external adoption.
"""

from __future__ import annotations

import hashlib
import importlib
import math
import os
import platform
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from research_evolution.core import (
    CoreError,
    Record,
    canonical_bytes,
    canonical_sha256,
    load_strict_json,
)

from ..types import AdapterError, _load_seam_record
from .manifest import DLRunManifest

_OBSERVATION_SCHEMA = "dl-run-observation/v1"
_FIXTURE_SCHEMA = "pytorch-dl-fixture/v1"
_RUNNER_NAME = "pytorch-gpu-fixture-runner"
_RUNNER_VERSION = "0.1.0"
_EMPTY_CONFIG_SHA256 = canonical_sha256({})
_FIXTURE_FIELDS = frozenset(
    {
        "schema",
        "fixture_id",
        "case_sha256",
        "samples",
        "input_features",
        "hidden_units",
        "output_features",
        "learning_rate",
        "requested_steps",
        "seed",
    }
)
_INTEGER_BOUNDS = {
    "samples": (1, 256),
    "input_features": (1, 128),
    "hidden_units": (1, 256),
    "output_features": (1, 32),
    "requested_steps": (1, 10),
    "seed": (0, 2**31 - 1),
}
_COMPLETED_METRICS = frozenset({"initial_loss", "final_loss", "loss_delta"})
_CUBLAS_WORKSPACE_CONFIGS = frozenset({":4096:8", ":16:8"})
_LIMITATIONS = (
    "Synthetic fixture only.",
    "No real dataset was observed.",
    "No scientific, predictive, strategy, production, or adoption claim is supported.",
    "Only the primary CUDA device was used by this run.",
    "GPU driver version was not re-probed by this module.",
    "No external checkpoint store or recovery path was observed.",
    "No cross-hardware portability was tested.",
    "Runtime-failure resource and step accounting may be lower bounds.",
)


class DLPytorchObservationError(AdapterError):
    """The requested observation could not honestly be started or bound."""


def _semantic_violations(payload: dict[str, Any]) -> tuple[str, ...]:
    violations: list[str] = []
    status = payload["status"]
    failure_class = payload["failure"]["class"]
    metrics = payload["metrics"]
    metric_names = [metric["name"] for metric in metrics]

    if (status == "completed") != (failure_class == "none"):
        violations.append(
            "observation-status-failure-match: completed requires failure class none "
            "and failed requires a non-none failure class"
        )
    if len(metric_names) != len(set(metric_names)):
        violations.append(
            "observation-completed-metrics: metric names must not repeat"
        )
    if status == "completed" and set(metric_names) != _COMPLETED_METRICS:
        violations.append(
            "observation-completed-metrics: completed observations require exactly "
            "initial_loss, final_loss, and loss_delta"
        )

    resources = payload["resources"]
    ledger = payload["budget_ledger"]
    fixture = payload["fixture"]
    nonnegative = (
        ("resources.duration_seconds", resources["duration_seconds"]),
        ("resources.peak_memory_bytes", resources["peak_memory_bytes"]),
        ("budget_ledger.declared.max_samples", ledger["declared"]["max_samples"]),
        ("budget_ledger.declared.max_steps", ledger["declared"]["max_steps"]),
        ("budget_ledger.declared.cost_limit", ledger["declared"]["cost_limit"]),
        ("budget_ledger.consumed.samples", ledger["consumed"]["samples"]),
        ("budget_ledger.consumed.steps", ledger["consumed"]["steps"]),
        (
            "budget_ledger.consumed.accelerator_seconds",
            ledger["consumed"]["accelerator_seconds"],
        ),
    )
    for path, value in nonnegative:
        if value < 0:
            violations.append(
                f"observation-resource-nonnegative: {path} must not be negative"
            )
    if ledger["consumed"]["accelerator_seconds"] != resources["duration_seconds"]:
        violations.append(
            "observation-duration-ledger-match: resource and ledger duration must match"
        )
    if ledger["consumed"]["steps"] > fixture["requested_steps"]:
        violations.append(
            "observation-budget-bound: consumed steps exceed requested steps"
        )
    if ledger["consumed"]["samples"] > fixture["samples"]:
        violations.append(
            "observation-budget-bound: consumed samples exceed fixture samples"
        )
    if status == "completed" and (
        ledger["consumed"]["steps"] != fixture["requested_steps"]
        or ledger["consumed"]["samples"] != fixture["samples"]
    ):
        violations.append(
            "observation-completed-consumption: completed observations must account "
            "for all requested steps and fixture samples"
        )
    if status == "completed" and ledger["consumed"]["accounting"] != "exact":
        violations.append(
            "observation-completed-consumption: completed observations require "
            "exact consumption accounting"
        )
    return tuple(violations)


@dataclass(frozen=True)
class DLObservedRun:
    """Immutable, schema-validated real-framework engineering observation."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _OBSERVATION_SCHEMA:
            raise AdapterError(
                f"DLObservedRun wraps {_OBSERVATION_SCHEMA} payloads, "
                f"got {self._record.schema_id!r}"
            )
        violations = _semantic_violations(self._record.data)
        if violations:
            raise AdapterError(
                f"invalid {_OBSERVATION_SCHEMA} semantics: "
                f"{len(violations)} violation(s)",
                details=violations,
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DLObservedRun":
        return cls(_load_seam_record(_OBSERVATION_SCHEMA, payload))

    @classmethod
    def from_json(cls, source: "str | bytes | bytearray") -> "DLObservedRun":
        return cls(_load_seam_record(_OBSERVATION_SCHEMA, source))

    @property
    def sha256(self) -> str:
        return self._record.sha256

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def manifest_sha256(self) -> str:
        return self._record.data["manifest_sha256"]

    @property
    def status(self) -> str:
        return self._record.data["status"]

    @property
    def failure_class(self) -> str:
        return self._record.data["failure"]["class"]


def pytorch_observation_identity() -> dict[str, str]:
    """Return the runner identity, including the exact module-byte SHA-256."""
    try:
        source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:
        raise DLPytorchObservationError(
            "cannot hash the PyTorch observation runner source"
        ) from exc
    return {
        "name": _RUNNER_NAME,
        "version": _RUNNER_VERSION,
        "source_sha256": source_sha256,
    }


def run_pytorch_gpu_fixture(
    manifest: DLRunManifest, fixture_payload: dict[str, Any]
) -> DLObservedRun:
    """Execute one bounded synthetic PyTorch fixture on ``cuda:0``.

    Configuration and environment mismatches raise
    :class:`DLPytorchObservationError` because execution was not honestly
    established.  A failure after the runtime is bound is returned as a
    failed observation with stable, non-sensitive diagnostics.
    """
    fixture = _validate_fixture(fixture_payload)
    manifest_data = _validate_manifest(manifest, fixture)
    torch = _load_torch()
    execution = _observe_runtime(torch)
    _validate_observed_runtime(manifest_data, execution)
    observed_at = _utc_now()

    attempt_started = time.perf_counter()
    try:
        outcome = _execute_fixture(torch, fixture["execution"])
    except Exception:
        duration = max(float(time.perf_counter() - attempt_started), 0.0)
        try:
            peak_memory = int(torch.cuda.max_memory_allocated(0))
        except Exception:
            peak_memory = 0
        outcome = {
            "metrics": [],
            "resources": {
                "duration_seconds": duration,
                "peak_memory_bytes": peak_memory,
            },
            "completed_steps": 0,
            "accounting": "lower_bound",
            "failure_class": "runtime_error",
            "failure_message": "PyTorch fixture execution failed.",
        }

    duration = outcome["resources"]["duration_seconds"]
    if "failure_class" in outcome:
        status = "failed"
        failure = {
            "class": outcome["failure_class"],
            "message": outcome["failure_message"],
        }
    elif duration > float(manifest_data["budget"]["cost_limit"]):
        status = "failed"
        failure = {
            "class": "budget_exhausted",
            "message": "Observed accelerator duration exceeded the declared cost limit.",
        }
    else:
        status = "completed"
        failure = {"class": "none", "message": "none"}

    completed_steps = outcome["completed_steps"]
    consumed_samples = fixture["payload"]["samples"] if completed_steps > 0 else 0
    identity = pytorch_observation_identity()
    core = {
        "schema": _OBSERVATION_SCHEMA,
        "manifest_sha256": manifest.sha256,
        "run_id": manifest_data["run_id"],
        "study_id": manifest_data["study_id"],
        "case_sha256": manifest_data["case_sha256"],
        "observed_at": observed_at,
        "evidence_scope": "real_framework_hardware_engineering",
        "status": status,
        "runner": identity,
        "fixture": {
            "fixture_sha256": fixture["sha256"],
            "seed": fixture["payload"]["seed"],
            "samples": fixture["payload"]["samples"],
            "requested_steps": fixture["payload"]["requested_steps"],
        },
        "execution": execution,
        "metrics": outcome["metrics"],
        "resources": outcome["resources"],
        "budget_ledger": {
            "declared": {
                "max_samples": manifest_data["budget"]["max_samples"],
                "max_steps": manifest_data["budget"]["max_steps"],
                "cost_limit": manifest_data["budget"]["cost_limit"],
                "cost_unit": manifest_data["budget"]["cost_unit"],
            },
            "consumed": {
                "samples": consumed_samples,
                "steps": completed_steps,
                "accelerator_seconds": duration,
                "accounting": outcome["accounting"],
            },
        },
        "checkpointing": {
            "performed": False,
            "external_store_observed": False,
        },
        "failure": failure,
        "limitations": list(_LIMITATIONS),
    }
    observation_id = f"dl-observation-{canonical_sha256(core)[:16]}"
    return DLObservedRun.from_payload({"observation_id": observation_id, **core})


def _validate_fixture(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise DLPytorchObservationError("fixture_payload must be an object")
    try:
        snapshot = load_strict_json(canonical_bytes(source))
    except CoreError as exc:
        raise DLPytorchObservationError(
            f"fixture_payload is not strict JSON: {exc}"
        ) from exc
    if set(snapshot) != _FIXTURE_FIELDS:
        raise DLPytorchObservationError(
            f"fixture fields must be exactly {sorted(_FIXTURE_FIELDS)}"
        )
    if snapshot["schema"] != _FIXTURE_SCHEMA:
        raise DLPytorchObservationError(
            f"fixture.schema must be {_FIXTURE_SCHEMA}"
        )
    _token(snapshot["fixture_id"], "fixture.fixture_id")
    _sha256(snapshot["case_sha256"], "fixture.case_sha256")
    for field, (lower, upper) in _INTEGER_BOUNDS.items():
        value = snapshot[field]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not lower <= value <= upper
        ):
            raise DLPytorchObservationError(
                f"fixture.{field} must be an integer in [{lower}, {upper}]"
            )
    learning_rate = snapshot["learning_rate"]
    if (
        isinstance(learning_rate, bool)
        or not isinstance(learning_rate, (int, float, Decimal))
        or not 0 < learning_rate <= 1
    ):
        raise DLPytorchObservationError(
            "fixture.learning_rate must be numeric in (0, 1]"
        )
    return {
        "payload": snapshot,
        "sha256": canonical_sha256(snapshot),
        "execution": {**snapshot, "learning_rate": float(learning_rate)},
    }


def _validate_manifest(
    manifest: Any, fixture: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(manifest, DLRunManifest):
        raise DLPytorchObservationError("manifest must be a DLRunManifest")
    payload = manifest.payload
    identity = pytorch_observation_identity()
    if payload["runner"] != identity:
        raise DLPytorchObservationError(
            "manifest.runner must match the exact PyTorch observation runner identity"
        )
    if payload["case_sha256"] != fixture["payload"]["case_sha256"]:
        raise DLPytorchObservationError(
            "manifest.case_sha256 must match fixture.case_sha256"
        )
    if payload["execution_mode"] != "gpu_fixture":
        raise DLPytorchObservationError("manifest.execution_mode must be gpu_fixture")
    if payload["hardware"]["accelerator"] != "cuda":
        raise DLPytorchObservationError("manifest.hardware.accelerator must be cuda")
    if payload["framework"]["name"] != "pytorch":
        raise DLPytorchObservationError("manifest.framework.name must be pytorch")
    if payload["framework"]["determinism"] != "strict":
        raise DLPytorchObservationError(
            "manifest.framework.determinism must be strict"
        )
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") not in _CUBLAS_WORKSPACE_CONFIGS:
        raise DLPytorchObservationError(
            "strict CUDA observation requires CUBLAS_WORKSPACE_CONFIG=:4096:8 "
            "or :16:8"
        )
    if payload["container"] != {"kind": "none"}:
        raise DLPytorchObservationError(
            "runner 0.1.0 supports only manifest.container kind none"
        )
    budget = payload["budget"]
    fixture_data = fixture["payload"]
    if budget["max_samples"] < fixture_data["samples"]:
        raise DLPytorchObservationError(
            "manifest sample budget is smaller than the fixture"
        )
    if budget["max_steps"] < fixture_data["requested_steps"]:
        raise DLPytorchObservationError(
            "manifest step budget is smaller than the fixture"
        )
    if budget["cost_unit"] != "accelerator_seconds" or budget["cost_limit"] <= 0:
        raise DLPytorchObservationError(
            "manifest requires a positive accelerator_seconds cost limit"
        )
    expected_optimizer = {
        "name": "sgd",
        "config_sha256": canonical_sha256(
            {"learning_rate": fixture_data["learning_rate"]}
        ),
    }
    if payload["optimizer"] != expected_optimizer:
        raise DLPytorchObservationError(
            "manifest.optimizer must bind SGD and the fixture learning rate"
        )
    if payload["scheduler"] != {
        "name": "none",
        "config_sha256": _EMPTY_CONFIG_SHA256,
    }:
        raise DLPytorchObservationError("manifest.scheduler must be the empty scheduler")
    checkpoint = payload["checkpoint_policy"]
    if (
        checkpoint["retention"] != "none"
        or checkpoint["max_retained"] != 0
        or checkpoint["save_optimizer_state"]
        or checkpoint["save_scheduler_state"]
        or checkpoint["resume"] != {"mode": "fresh"}
    ):
        raise DLPytorchObservationError(
            "runner 0.1.0 requires fresh execution with checkpoint retention disabled"
        )
    return payload


def _load_torch() -> Any:
    try:
        return importlib.import_module("torch")
    except (ImportError, OSError) as exc:
        raise DLPytorchObservationError(
            "PyTorch is not importable; no execution was observed"
        ) from exc


def _observe_runtime(torch: Any) -> dict[str, Any]:
    try:
        if not torch.cuda.is_available():
            raise DLPytorchObservationError(
                "PyTorch CUDA is unavailable; no GPU execution was observed"
            )
        backend_version = torch.version.cuda
        if not isinstance(backend_version, str) or not backend_version:
            raise DLPytorchObservationError(
                "PyTorch CUDA backend version is unavailable"
            )
        properties = torch.cuda.get_device_properties(0)
        capability = torch.cuda.get_device_capability(0)
        system = platform.system().lower()
        if system not in {"windows", "linux"}:
            raise DLPytorchObservationError(
                "runner 0.1.0 supports only Windows and Linux CUDA hosts"
            )
        return {
            "mode": "gpu_fixture",
            "os": system,
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "framework": {
                "name": "pytorch",
                "version": torch.__version__,
                "backend": "cuda",
                "backend_version": backend_version,
                "determinism": "strict",
            },
            "hardware": {
                "device_model": properties.name,
                "device_count": torch.cuda.device_count(),
                "memory_bytes_per_device": properties.total_memory,
                "compute_capability": f"{capability[0]}.{capability[1]}",
            },
        }
    except DLPytorchObservationError:
        raise
    except Exception as exc:
        raise DLPytorchObservationError(
            "PyTorch CUDA runtime probe failed; no execution was observed"
        ) from exc


def _validate_observed_runtime(
    manifest: dict[str, Any], execution: dict[str, Any]
) -> None:
    expected_runtime = manifest["runtime"]
    for field in ("os", "architecture", "python_version"):
        if expected_runtime[field] != execution[field]:
            raise DLPytorchObservationError(
                f"observed runtime.{field} does not match manifest"
            )
    expected_framework = manifest["framework"]
    observed_framework = execution["framework"]
    for field in ("name", "version", "backend_version", "determinism"):
        if expected_framework[field] != observed_framework[field]:
            raise DLPytorchObservationError(
                f"observed framework.{field} does not match manifest"
            )
    expected_hardware = manifest["hardware"]
    observed_hardware = execution["hardware"]
    for field in ("device_model", "device_count", "memory_bytes_per_device"):
        if expected_hardware[field] != observed_hardware[field]:
            raise DLPytorchObservationError(
                f"observed hardware.{field} does not match manifest"
            )


def _execute_fixture(torch: Any, fixture: dict[str, Any]) -> dict[str, Any]:
    seed = fixture["seed"]
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda:0")
    generator = torch.Generator(device=device)
    generator.manual_seed(seed)
    model = torch.nn.Sequential(
        torch.nn.Linear(fixture["input_features"], fixture["hidden_units"]),
        torch.nn.Tanh(),
        torch.nn.Linear(fixture["hidden_units"], fixture["output_features"]),
    ).to(device)
    features = torch.randn(
        (fixture["samples"], fixture["input_features"]),
        generator=generator,
        device=device,
    )
    true_weights = torch.randn(
        (fixture["input_features"], fixture["output_features"]),
        generator=generator,
        device=device,
    )
    targets = features @ true_weights
    optimizer = torch.optim.SGD(model.parameters(), lr=fixture["learning_rate"])
    loss_function = torch.nn.MSELoss()

    torch.cuda.synchronize(0)
    torch.cuda.reset_peak_memory_stats(0)
    started = time.perf_counter()
    with torch.no_grad():
        initial_loss = float(loss_function(model(features), targets).item())
    for _ in range(fixture["requested_steps"]):
        optimizer.zero_grad(set_to_none=True)
        loss = loss_function(model(features), targets)
        loss.backward()
        optimizer.step()
    with torch.no_grad():
        final_loss = float(loss_function(model(features), targets).item())
    torch.cuda.synchronize(0)
    duration = float(time.perf_counter() - started)
    peak_memory = int(torch.cuda.max_memory_allocated(0))
    if not all(math.isfinite(value) for value in (initial_loss, final_loss, duration)):
        return {
            "metrics": [],
            "resources": {
                "duration_seconds": duration if math.isfinite(duration) else 0.0,
                "peak_memory_bytes": peak_memory,
            },
            "completed_steps": fixture["requested_steps"],
            "failure_class": "numerical_failure",
            "failure_message": "PyTorch fixture produced a non-finite observation.",
            "accounting": "exact",
        }
    return {
        "metrics": [
            {"name": "initial_loss", "value": initial_loss},
            {"name": "final_loss", "value": final_loss},
            {"name": "loss_delta", "value": final_loss - initial_loss},
        ],
        "resources": {
            "duration_seconds": duration,
            "peak_memory_bytes": peak_memory,
        },
        "completed_steps": fixture["requested_steps"],
        "accounting": "exact",
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _token(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise DLPytorchObservationError(f"{path} must be a non-whitespace token")
    return value


def _sha256(value: Any, path: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise DLPytorchObservationError(f"{path} must be lowercase SHA-256")
    return value


__all__ = [
    "DLPytorchObservationError",
    "DLObservedRun",
    "pytorch_observation_identity",
    "run_pytorch_gpu_fixture",
]
