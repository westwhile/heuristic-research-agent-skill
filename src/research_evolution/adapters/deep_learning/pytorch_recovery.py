"""Bounded real PyTorch/CUDA checkpoint-recovery observation.

The module exposes one concrete deep interface.  It validates a governed
``DLRunManifest`` and tiny synthetic fixture, then launches three fresh Python
processes: a checkpoint source, a resume segment, and an uninterrupted
control.  A successful receipt requires exact model, optimizer, and scheduler
state equality plus cumulative budget accounting without double charging.

The caller supplies an existing empty artifact directory.  Its path and the
checkpoint payload never enter the returned record; only an opaque locator,
hashes, and byte count do.  This is deliberately not a generic checkpoint
store seam: only one local-substitutable PyTorch implementation exists.
"""

from __future__ import annotations

import hashlib
import importlib
import math
import os
import platform
import subprocess
import sys
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

_OBSERVATION_SCHEMA = "dl-checkpoint-recovery-observation/v1"
_FIXTURE_SCHEMA = "pytorch-dl-recovery-fixture/v1"
_RUNNER_NAME = "pytorch-gpu-checkpoint-recovery-runner"
_RUNNER_VERSION = "0.1.0"
_CUBLAS_WORKSPACE_CONFIGS = frozenset({":4096:8", ":16:8"})
_PROCESS_ROLES = frozenset({"source", "resume", "uninterrupted_control"})
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
        "momentum",
        "requested_steps",
        "checkpoint_step",
        "seed",
        "scheduler_step_size",
        "scheduler_gamma",
    }
)
_INTEGER_BOUNDS = {
    "samples": (1, 256),
    "input_features": (1, 128),
    "hidden_units": (1, 256),
    "output_features": (1, 32),
    "requested_steps": (2, 20),
    "checkpoint_step": (1, 19),
    "seed": (0, 2**31 - 1),
    "scheduler_step_size": (1, 20),
}
_LIMITATIONS = (
    "Synthetic fixture only.",
    "One real PyTorch/CUDA host and its primary device only.",
    "The artifact store was a caller-managed local temporary directory, not a remote store.",
    "No real dataset, scheduler service, or involuntary preemption was observed.",
    "No cross-GPU or cross-driver reproducibility was tested.",
    "No scientific, predictive, strategy, production, or adoption claim is supported.",
)


class DLPytorchRecoveryError(AdapterError):
    """A recovery receipt could not be honestly established."""


def _semantic_violations(payload: dict[str, Any]) -> tuple[str, ...]:
    violations: list[str] = []
    fixture = payload["fixture"]
    processes = payload["processes"]
    roles = [row["role"] for row in processes]
    if len(roles) != len(set(roles)) or set(roles) != _PROCESS_ROLES:
        violations.append(
            "recovery-process-roles: exactly one source, resume, and "
            "uninterrupted_control process is required"
        )
    for row in processes:
        for field in ("completed_steps", "duration_seconds", "peak_memory_bytes"):
            if row[field] < 0:
                violations.append(
                    f"recovery-process-nonnegative: {row['role']}.{field} must be nonnegative"
                )

    checkpoint = payload["checkpoint"]
    if checkpoint["size_bytes"] <= 0:
        violations.append("recovery-checkpoint-size: checkpoint must contain bytes")
    if checkpoint["completed_steps"] != fixture["checkpoint_step"]:
        violations.append(
            "recovery-checkpoint-step: checkpoint step must match the fixture"
        )

    equivalence = payload["equivalence"]
    for prefix in ("model", "optimizer", "scheduler"):
        if (
            equivalence[f"resumed_{prefix}_state_sha256"]
            != equivalence[f"control_{prefix}_state_sha256"]
        ):
            violations.append(
                f"recovery-{prefix}-equivalence: resumed and control hashes must match"
            )
    expected_delta = abs(
        equivalence["resumed_final_loss"] - equivalence["control_final_loss"]
    )
    if equivalence["loss_absolute_delta"] != expected_delta:
        violations.append(
            "recovery-loss-delta: loss_absolute_delta must match the recorded losses"
        )
    if equivalence["loss_absolute_delta"] != 0:
        violations.append("recovery-loss-equivalence: final losses must match exactly")

    ledger = payload["budget_ledger"]
    by_role = {row["role"]: row for row in processes}
    if set(by_role) == _PROCESS_ROLES:
        for role, ledger_field in (
            ("source", "source_steps"),
            ("resume", "resume_segment_steps"),
            ("uninterrupted_control", "control_steps"),
        ):
            if by_role[role]["completed_steps"] != ledger[ledger_field]:
                violations.append(
                    f"recovery-process-budget-match: {role} steps must match {ledger_field}"
                )
    if ledger["declared_steps"] != fixture["requested_steps"]:
        violations.append("recovery-budget-declared: declared steps must match fixture")
    if ledger["source_steps"] != fixture["checkpoint_step"]:
        violations.append("recovery-budget-source: source steps must match checkpoint")
    if ledger["resume_segment_steps"] != (
        fixture["requested_steps"] - fixture["checkpoint_step"]
    ):
        violations.append(
            "recovery-budget-resume: resume segment must consume only remaining steps"
        )
    if ledger["resumed_cumulative_steps"] != fixture["requested_steps"]:
        violations.append(
            "recovery-budget-cumulative: resumed cumulative steps must equal declared steps"
        )
    if ledger["control_steps"] != fixture["requested_steps"]:
        violations.append("recovery-budget-control: control must consume declared steps")
    return tuple(violations)


@dataclass(frozen=True)
class DLCheckpointRecoveryObservation:
    """Immutable, schema- and semantics-validated recovery receipt."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _OBSERVATION_SCHEMA:
            raise AdapterError(
                f"DLCheckpointRecoveryObservation wraps {_OBSERVATION_SCHEMA} payloads, "
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
    def from_payload(
        cls, payload: dict[str, Any]
    ) -> "DLCheckpointRecoveryObservation":
        return cls(_load_seam_record(_OBSERVATION_SCHEMA, payload))

    @classmethod
    def from_json(
        cls, source: "str | bytes | bytearray"
    ) -> "DLCheckpointRecoveryObservation":
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


def pytorch_recovery_identity() -> dict[str, str]:
    """Return runner identity bound to the exact module bytes."""
    try:
        source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:
        raise DLPytorchRecoveryError(
            "cannot hash the PyTorch recovery runner source"
        ) from exc
    return {
        "name": _RUNNER_NAME,
        "version": _RUNNER_VERSION,
        "source_sha256": source_sha256,
    }


def run_pytorch_checkpoint_recovery(
    manifest: DLRunManifest,
    fixture_payload: dict[str, Any],
    artifact_root: str | os.PathLike[str],
) -> DLCheckpointRecoveryObservation:
    """Checkpoint and resume a bounded CUDA fixture across fresh processes.

    ``artifact_root`` must be an existing empty, non-symlink directory managed
    by the caller.  A successful call leaves one checkpoint payload there so
    its receipt can be independently inspected; callers remain responsible for
    retention and cleanup.
    """
    fixture = _validate_fixture(fixture_payload)
    manifest_data = _validate_manifest(manifest, fixture)
    root = _validate_artifact_root(artifact_root)
    torch = _load_torch()
    execution = _observe_runtime(torch)
    _validate_observed_runtime(manifest_data, execution)

    checkpoint_path = root / "checkpoint.pt"
    common = {
        "fixture": fixture["execution"],
        "fixture_sha256": fixture["sha256"],
        "runner": pytorch_recovery_identity(),
        "checkpoint_path": str(checkpoint_path),
    }
    source = _invoke_stage(root, "source", common)
    _validate_stage(source, "source", execution)
    _validate_checkpoint_file(
        checkpoint_path,
        source["checkpoint"],
        fixture["payload"]["checkpoint_step"],
    )

    continuation = {
        **common,
        "checkpoint_content_sha256": source["checkpoint"]["content_sha256"],
    }
    resume = _invoke_stage(root, "resume", continuation)
    control = _invoke_stage(root, "uninterrupted_control", common)
    _validate_stage(resume, "resume", execution)
    _validate_stage(control, "uninterrupted_control", execution)
    _validate_equivalence(resume, control)
    if (
        source["duration_seconds"] + resume["duration_seconds"]
        > float(manifest_data["budget"]["cost_limit"])
    ):
        raise DLPytorchRecoveryError(
            "resumed execution exceeded the declared accelerator_seconds cost limit"
        )

    core = {
        "schema": _OBSERVATION_SCHEMA,
        "manifest_sha256": manifest.sha256,
        "run_id": manifest_data["run_id"],
        "study_id": manifest_data["study_id"],
        "case_sha256": manifest_data["case_sha256"],
        "observed_at": _utc_now(),
        "evidence_scope": "real_framework_hardware_checkpoint_recovery_engineering",
        "status": "completed",
        "runner": pytorch_recovery_identity(),
        "fixture": {
            "fixture_sha256": fixture["sha256"],
            "seed": fixture["payload"]["seed"],
            "samples": fixture["payload"]["samples"],
            "requested_steps": fixture["payload"]["requested_steps"],
            "checkpoint_step": fixture["payload"]["checkpoint_step"],
        },
        "execution": execution,
        "processes": [
            _public_process(source),
            _public_process(resume),
            _public_process(control),
        ],
        "checkpoint": {
            "locator": (
                f"artifact://{manifest_data['run_id']}/checkpoint-"
                f"{fixture['payload']['checkpoint_step']:04d}.pt"
            ),
            **source["checkpoint"],
            "store_kind": "caller_managed_local_directory",
            "repository_persisted": False,
        },
        "equivalence": {
            "resumed_model_state_sha256": resume["model_state_sha256"],
            "control_model_state_sha256": control["model_state_sha256"],
            "model_state_exact": True,
            "resumed_optimizer_state_sha256": resume[
                "optimizer_state_sha256"
            ],
            "control_optimizer_state_sha256": control[
                "optimizer_state_sha256"
            ],
            "optimizer_state_exact": True,
            "resumed_scheduler_state_sha256": resume[
                "scheduler_state_sha256"
            ],
            "control_scheduler_state_sha256": control[
                "scheduler_state_sha256"
            ],
            "scheduler_state_exact": True,
            "resumed_final_loss": resume["final_loss"],
            "control_final_loss": control["final_loss"],
            "loss_absolute_delta": abs(
                resume["final_loss"] - control["final_loss"]
            ),
        },
        "budget_ledger": {
            "declared_steps": fixture["payload"]["requested_steps"],
            "source_steps": source["completed_steps"],
            "resume_segment_steps": resume["completed_steps"],
            "resumed_cumulative_steps": (
                source["completed_steps"] + resume["completed_steps"]
            ),
            "control_steps": control["completed_steps"],
            "accounting": "exact",
            "double_charged": False,
        },
        "limitations": list(_LIMITATIONS),
    }
    observation_id = f"dl-recovery-{canonical_sha256(core)[:16]}"
    return DLCheckpointRecoveryObservation.from_payload(
        {"observation_id": observation_id, **core}
    )


def _validate_fixture(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise DLPytorchRecoveryError("fixture_payload must be an object")
    try:
        snapshot = load_strict_json(canonical_bytes(source))
    except CoreError as exc:
        raise DLPytorchRecoveryError(
            f"fixture_payload is not strict JSON: {exc}"
        ) from exc
    if set(snapshot) != _FIXTURE_FIELDS:
        raise DLPytorchRecoveryError(
            f"fixture fields must be exactly {sorted(_FIXTURE_FIELDS)}"
        )
    if snapshot["schema"] != _FIXTURE_SCHEMA:
        raise DLPytorchRecoveryError(f"fixture.schema must be {_FIXTURE_SCHEMA}")
    _token(snapshot["fixture_id"], "fixture.fixture_id")
    _sha256(snapshot["case_sha256"], "fixture.case_sha256")
    for field, (lower, upper) in _INTEGER_BOUNDS.items():
        value = snapshot[field]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not lower <= value <= upper
        ):
            raise DLPytorchRecoveryError(
                f"fixture.{field} must be an integer in [{lower}, {upper}]"
            )
    if snapshot["checkpoint_step"] >= snapshot["requested_steps"]:
        raise DLPytorchRecoveryError(
            "fixture.checkpoint_step must be smaller than requested_steps"
        )
    for field, lower, upper, upper_inclusive in (
        ("learning_rate", 0, 1, True),
        ("momentum", 0, 1, False),
        ("scheduler_gamma", 0, 1, True),
    ):
        value = snapshot[field]
        valid_type = isinstance(value, (int, float, Decimal)) and not isinstance(
            value, bool
        )
        upper_ok = value <= upper if upper_inclusive else value < upper
        if not valid_type or not value > lower or not upper_ok:
            closing = "]" if upper_inclusive else ")"
            raise DLPytorchRecoveryError(
                f"fixture.{field} must be numeric in ({lower}, {upper}{closing}"
            )
    execution = dict(snapshot)
    for field in ("learning_rate", "momentum", "scheduler_gamma"):
        execution[field] = float(snapshot[field])
    return {
        "payload": snapshot,
        "sha256": canonical_sha256(snapshot),
        "execution": execution,
    }


def _validate_manifest(
    manifest: Any, fixture: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(manifest, DLRunManifest):
        raise DLPytorchRecoveryError("manifest must be a DLRunManifest")
    payload = manifest.payload
    identity = pytorch_recovery_identity()
    if payload["runner"] != identity:
        raise DLPytorchRecoveryError(
            "manifest.runner must match the exact PyTorch recovery runner identity"
        )
    fixture_data = fixture["payload"]
    if payload["case_sha256"] != fixture_data["case_sha256"]:
        raise DLPytorchRecoveryError(
            "manifest.case_sha256 must match fixture.case_sha256"
        )
    if payload["execution_mode"] != "gpu_fixture":
        raise DLPytorchRecoveryError("manifest.execution_mode must be gpu_fixture")
    if payload["hardware"]["accelerator"] != "cuda":
        raise DLPytorchRecoveryError("manifest.hardware.accelerator must be cuda")
    if payload["framework"]["name"] != "pytorch":
        raise DLPytorchRecoveryError("manifest.framework.name must be pytorch")
    if payload["framework"]["determinism"] != "strict":
        raise DLPytorchRecoveryError("manifest.framework.determinism must be strict")
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") not in _CUBLAS_WORKSPACE_CONFIGS:
        raise DLPytorchRecoveryError(
            "strict CUDA recovery requires CUBLAS_WORKSPACE_CONFIG=:4096:8 or :16:8"
        )
    if payload["container"] != {"kind": "none"}:
        raise DLPytorchRecoveryError(
            "runner 0.1.0 supports only manifest.container kind none"
        )
    budget = payload["budget"]
    if budget["max_samples"] < fixture_data["samples"]:
        raise DLPytorchRecoveryError("manifest sample budget is smaller than fixture")
    if budget["max_steps"] < fixture_data["requested_steps"]:
        raise DLPytorchRecoveryError("manifest step budget is smaller than fixture")
    if budget["cost_unit"] != "accelerator_seconds" or budget["cost_limit"] <= 0:
        raise DLPytorchRecoveryError(
            "manifest requires a positive accelerator_seconds cost limit"
        )
    expected_optimizer = {
        "name": "sgd",
        "config_sha256": canonical_sha256(
            {
                "learning_rate": fixture_data["learning_rate"],
                "momentum": fixture_data["momentum"],
            }
        ),
    }
    if payload["optimizer"] != expected_optimizer:
        raise DLPytorchRecoveryError(
            "manifest.optimizer must bind SGD, learning rate, and momentum"
        )
    expected_scheduler = {
        "name": "step_lr",
        "config_sha256": canonical_sha256(
            {
                "step_size": fixture_data["scheduler_step_size"],
                "gamma": fixture_data["scheduler_gamma"],
            }
        ),
    }
    if payload["scheduler"] != expected_scheduler:
        raise DLPytorchRecoveryError(
            "manifest.scheduler must bind the fixture StepLR configuration"
        )
    checkpoint = payload["checkpoint_policy"]
    if (
        checkpoint["artifact_reference"] != "external_locator_and_hash_only"
        or checkpoint["retention"] != "last"
        or checkpoint["max_retained"] != 1
        or not checkpoint["save_optimizer_state"]
        or not checkpoint["save_scheduler_state"]
        or checkpoint["recovery_accounting"] != "cumulative_no_double_charge"
        or checkpoint["resume"] != {"mode": "fresh"}
    ):
        raise DLPytorchRecoveryError(
            "runner 0.1.0 requires one fresh, exact-state checkpoint with cumulative accounting"
        )
    return payload


def _validate_artifact_root(source: str | os.PathLike[str]) -> Path:
    try:
        candidate = Path(source)
        if candidate.is_symlink():
            raise DLPytorchRecoveryError(
                "artifact_root must be a non-symlink directory"
            )
        root = candidate.resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        raise DLPytorchRecoveryError(
            "artifact_root must be an existing directory"
        ) from exc
    if not root.is_dir() or root.is_symlink():
        raise DLPytorchRecoveryError(
            "artifact_root must be a non-symlink directory"
        )
    try:
        if any(root.iterdir()):
            raise DLPytorchRecoveryError("artifact_root must be empty")
    except OSError as exc:
        raise DLPytorchRecoveryError("artifact_root cannot be inspected") from exc
    repository_root = Path(__file__).resolve().parents[4]
    if (repository_root / "pyproject.toml").is_file() and root.is_relative_to(
        repository_root
    ):
        raise DLPytorchRecoveryError("artifact_root must be outside the repository")
    return root


def _load_torch() -> Any:
    try:
        return importlib.import_module("torch")
    except (ImportError, OSError) as exc:
        raise DLPytorchRecoveryError(
            "PyTorch is not importable; no recovery was observed"
        ) from exc


def _observe_runtime(torch: Any) -> dict[str, Any]:
    try:
        if not torch.cuda.is_available():
            raise DLPytorchRecoveryError(
                "PyTorch CUDA is unavailable; no recovery was observed"
            )
        backend_version = torch.version.cuda
        if not isinstance(backend_version, str) or not backend_version:
            raise DLPytorchRecoveryError("PyTorch CUDA backend version is unavailable")
        properties = torch.cuda.get_device_properties(0)
        capability = torch.cuda.get_device_capability(0)
        system = platform.system().lower()
        if system not in {"windows", "linux"}:
            raise DLPytorchRecoveryError(
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
    except DLPytorchRecoveryError:
        raise
    except Exception as exc:
        raise DLPytorchRecoveryError(
            "PyTorch CUDA runtime probe failed; no recovery was observed"
        ) from exc


def _validate_observed_runtime(
    manifest: dict[str, Any], execution: dict[str, Any]
) -> None:
    for field in ("os", "architecture", "python_version"):
        if manifest["runtime"][field] != execution[field]:
            raise DLPytorchRecoveryError(
                f"observed runtime.{field} does not match manifest"
            )
    for field in ("name", "version", "backend_version", "determinism"):
        if manifest["framework"][field] != execution["framework"][field]:
            raise DLPytorchRecoveryError(
                f"observed framework.{field} does not match manifest"
            )
    for field in ("device_model", "device_count", "memory_bytes_per_device"):
        if manifest["hardware"][field] != execution["hardware"][field]:
            raise DLPytorchRecoveryError(
                f"observed hardware.{field} does not match manifest"
            )


def _invoke_stage(root: Path, role: str, request: dict[str, Any]) -> dict[str, Any]:
    request_path = root / f".{role}-request.json"
    result_path = root / f".{role}-result.json"
    request_path.write_bytes(canonical_bytes(request))
    command = [
        sys.executable,
        "-B",
        "-m",
        __name__,
        "--worker",
        role,
        str(request_path),
        str(result_path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if completed.returncode != 0 or not result_path.is_file():
            raise DLPytorchRecoveryError(
                f"{role} recovery process failed without a valid receipt"
            )
        result = load_strict_json(result_path.read_bytes())
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise DLPytorchRecoveryError(
                f"{role} recovery process failed without a valid receipt"
            )
        payload = result.get("payload")
        if not isinstance(payload, dict):
            raise DLPytorchRecoveryError(
                f"{role} recovery process returned an invalid receipt"
            )
        for field in ("duration_seconds", "final_loss"):
            if field in payload and isinstance(payload[field], Decimal):
                payload[field] = float(payload[field])
        return payload
    except subprocess.TimeoutExpired as exc:
        raise DLPytorchRecoveryError(f"{role} recovery process timed out") from exc
    except (OSError, CoreError) as exc:
        raise DLPytorchRecoveryError(
            f"{role} recovery process receipt could not be read"
        ) from exc
    finally:
        for path in (request_path, result_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _validate_stage(
    stage: dict[str, Any], expected_role: str, execution: dict[str, Any]
) -> None:
    required = {
        "role",
        "completed_steps",
        "duration_seconds",
        "peak_memory_bytes",
        "execution",
    }
    if not required.issubset(stage) or stage["role"] != expected_role:
        raise DLPytorchRecoveryError(
            f"{expected_role} recovery process returned an invalid receipt"
        )
    if stage["execution"] != execution:
        raise DLPytorchRecoveryError(
            f"{expected_role} recovery process runtime does not match the manifest"
        )
    if (
        not isinstance(stage["completed_steps"], int)
        or isinstance(stage["completed_steps"], bool)
        or stage["completed_steps"] < 0
        or not isinstance(stage["peak_memory_bytes"], int)
        or isinstance(stage["peak_memory_bytes"], bool)
        or stage["peak_memory_bytes"] < 0
        or not isinstance(stage["duration_seconds"], (int, float))
        or isinstance(stage["duration_seconds"], bool)
        or not math.isfinite(stage["duration_seconds"])
        or stage["duration_seconds"] < 0
    ):
        raise DLPytorchRecoveryError(
            f"{expected_role} recovery process accounting is invalid"
        )


def _validate_checkpoint_file(
    path: Path, receipt: Any, expected_completed_steps: int
) -> None:
    required = {
        "content_sha256",
        "size_bytes",
        "model_state_sha256",
        "optimizer_state_sha256",
        "scheduler_state_sha256",
        "completed_steps",
    }
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise DLPytorchRecoveryError("source checkpoint receipt is invalid")
    if (
        not isinstance(receipt["size_bytes"], int)
        or isinstance(receipt["size_bytes"], bool)
        or receipt["size_bytes"] <= 0
        or receipt["completed_steps"] != expected_completed_steps
    ):
        raise DLPytorchRecoveryError("source checkpoint receipt accounting is invalid")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DLPytorchRecoveryError("source checkpoint payload is missing") from exc
    if len(raw) != receipt["size_bytes"] or hashlib.sha256(raw).hexdigest() != receipt[
        "content_sha256"
    ]:
        raise DLPytorchRecoveryError("source checkpoint payload failed integrity verification")
    for field in (
        "content_sha256",
        "model_state_sha256",
        "optimizer_state_sha256",
        "scheduler_state_sha256",
    ):
        _sha256(receipt[field], f"checkpoint.{field}")


def _validate_equivalence(resume: dict[str, Any], control: dict[str, Any]) -> None:
    for field in (
        "model_state_sha256",
        "optimizer_state_sha256",
        "scheduler_state_sha256",
    ):
        if resume.get(field) != control.get(field):
            raise DLPytorchRecoveryError(
                f"resumed {field} does not exactly match uninterrupted control"
            )
    for stage in (resume, control):
        value = stage.get("final_loss")
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise DLPytorchRecoveryError("recovery process final loss is invalid")
    if resume["final_loss"] != control["final_loss"]:
        raise DLPytorchRecoveryError(
            "resumed final loss does not exactly match uninterrupted control"
        )


def _public_process(stage: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": stage["role"],
        "completed_steps": stage["completed_steps"],
        "duration_seconds": stage["duration_seconds"],
        "peak_memory_bytes": stage["peak_memory_bytes"],
    }


def _worker(role: str, request: dict[str, Any]) -> dict[str, Any]:
    torch = _load_torch()
    execution = _observe_runtime(torch)
    if request.get("runner") != pytorch_recovery_identity():
        raise DLPytorchRecoveryError("worker runner identity mismatch")
    fixture = request.get("fixture")
    if not isinstance(fixture, dict):
        raise DLPytorchRecoveryError("worker fixture is invalid")
    fixture = dict(fixture)
    for field in ("learning_rate", "momentum", "scheduler_gamma"):
        fixture[field] = float(fixture[field])
    checkpoint_path = Path(request.get("checkpoint_path", ""))
    if not checkpoint_path.is_absolute():
        raise DLPytorchRecoveryError("worker checkpoint path is invalid")
    model, optimizer, scheduler, features, targets, loss_function = _build_training(
        torch, fixture
    )

    if role == "resume":
        _worker_load_checkpoint(
            torch,
            checkpoint_path,
            request.get("checkpoint_content_sha256"),
            request.get("fixture_sha256"),
            fixture["checkpoint_step"],
            model,
            optimizer,
            scheduler,
        )
        steps = fixture["requested_steps"] - fixture["checkpoint_step"]
    elif role == "source":
        steps = fixture["checkpoint_step"]
    elif role == "uninterrupted_control":
        steps = fixture["requested_steps"]
    else:
        raise DLPytorchRecoveryError("worker role is invalid")

    torch.cuda.synchronize(0)
    torch.cuda.reset_peak_memory_stats(0)
    started = time.perf_counter()
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = loss_function(model(features), targets)
        loss.backward()
        optimizer.step()
        scheduler.step()
    with torch.no_grad():
        final_loss = float(loss_function(model(features), targets).item())
    torch.cuda.synchronize(0)
    duration = float(time.perf_counter() - started)
    peak_memory = int(torch.cuda.max_memory_allocated(0))
    if not math.isfinite(final_loss) or not math.isfinite(duration):
        raise DLPytorchRecoveryError("worker produced a non-finite result")

    payload = {
        "role": role,
        "completed_steps": steps,
        "duration_seconds": duration,
        "peak_memory_bytes": peak_memory,
        "execution": execution,
    }
    if role == "source":
        checkpoint = {
            "model_state": model.state_dict(),
            "optimizer_state": optimizer.state_dict(),
            "scheduler_state": scheduler.state_dict(),
            "completed_steps": steps,
            "fixture_sha256": request["fixture_sha256"],
            "runner_source_sha256": request["runner"]["source_sha256"],
        }
        temporary = checkpoint_path.with_suffix(".tmp")
        torch.save(checkpoint, temporary)
        os.replace(temporary, checkpoint_path)
        raw = checkpoint_path.read_bytes()
        payload["checkpoint"] = {
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "model_state_sha256": _state_sha256(torch, checkpoint["model_state"]),
            "optimizer_state_sha256": _state_sha256(
                torch, checkpoint["optimizer_state"]
            ),
            "scheduler_state_sha256": _state_sha256(
                torch, checkpoint["scheduler_state"]
            ),
            "completed_steps": steps,
        }
    else:
        payload.update(
            {
                "model_state_sha256": _state_sha256(torch, model.state_dict()),
                "optimizer_state_sha256": _state_sha256(
                    torch, optimizer.state_dict()
                ),
                "scheduler_state_sha256": _state_sha256(
                    torch, scheduler.state_dict()
                ),
                "final_loss": final_loss,
            }
        )
    return payload


def _build_training(torch: Any, fixture: dict[str, Any]) -> tuple[Any, ...]:
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
    optimizer = torch.optim.SGD(
        model.parameters(),
        lr=fixture["learning_rate"],
        momentum=fixture["momentum"],
    )
    scheduler = torch.optim.lr_scheduler.StepLR(
        optimizer,
        step_size=fixture["scheduler_step_size"],
        gamma=fixture["scheduler_gamma"],
    )
    return model, optimizer, scheduler, features, targets, torch.nn.MSELoss()


def _worker_load_checkpoint(
    torch: Any,
    checkpoint_path: Path,
    expected_content_sha256: Any,
    expected_fixture_sha256: Any,
    expected_completed_steps: int,
    model: Any,
    optimizer: Any,
    scheduler: Any,
) -> None:
    _sha256(expected_content_sha256, "checkpoint.content_sha256")
    try:
        raw = checkpoint_path.read_bytes()
    except OSError as exc:
        raise DLPytorchRecoveryError("checkpoint payload is missing") from exc
    if hashlib.sha256(raw).hexdigest() != expected_content_sha256:
        raise DLPytorchRecoveryError("checkpoint content hash mismatch")
    try:
        checkpoint = torch.load(
            checkpoint_path,
            map_location=torch.device("cuda:0"),
            weights_only=True,
        )
    except Exception as exc:
        raise DLPytorchRecoveryError("checkpoint payload could not be loaded") from exc
    required = {
        "model_state",
        "optimizer_state",
        "scheduler_state",
        "completed_steps",
        "fixture_sha256",
        "runner_source_sha256",
    }
    if not isinstance(checkpoint, dict) or set(checkpoint) != required:
        raise DLPytorchRecoveryError("checkpoint payload fields are invalid")
    if checkpoint["fixture_sha256"] != expected_fixture_sha256:
        raise DLPytorchRecoveryError("checkpoint fixture lineage mismatch")
    if checkpoint["completed_steps"] != expected_completed_steps:
        raise DLPytorchRecoveryError("checkpoint progress lineage mismatch")
    if checkpoint["runner_source_sha256"] != pytorch_recovery_identity()[
        "source_sha256"
    ]:
        raise DLPytorchRecoveryError("checkpoint runner lineage mismatch")
    try:
        model.load_state_dict(checkpoint["model_state"], strict=True)
        optimizer.load_state_dict(checkpoint["optimizer_state"])
        scheduler.load_state_dict(checkpoint["scheduler_state"])
    except Exception as exc:
        raise DLPytorchRecoveryError("checkpoint state restoration failed") from exc


def _state_sha256(torch: Any, value: Any) -> str:
    return canonical_sha256(_stable_state(torch, value))


def _stable_state(torch: Any, value: Any) -> Any:
    if torch.is_tensor(value):
        tensor = value.detach().cpu().contiguous()
        return {
            "kind": "tensor",
            "dtype": str(tensor.dtype),
            "shape": list(tensor.shape),
            "values": tensor.tolist(),
        }
    if isinstance(value, dict):
        return {
            str(key): _stable_state(torch, value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_stable_state(torch, item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise DLPytorchRecoveryError("checkpoint state contains an unsupported value")


def _worker_entry(argv: list[str]) -> int:
    if len(argv) != 4 or argv[0] != "--worker":
        return 2
    _, role, request_name, result_name = argv
    result_path = Path(result_name)
    try:
        request = load_strict_json(Path(request_name).read_bytes())
        if not isinstance(request, dict):
            raise DLPytorchRecoveryError("worker request is invalid")
        payload = _worker(role, request)
        result = {"ok": True, "payload": payload}
        exit_code = 0
    except Exception:
        result = {"ok": False, "error": "PyTorch checkpoint recovery worker failed."}
        exit_code = 1
    try:
        result_path.write_bytes(canonical_bytes(result))
    except OSError:
        return 1
    return exit_code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _token(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise DLPytorchRecoveryError(f"{path} must be a non-whitespace token")
    return value


def _sha256(value: Any, path: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise DLPytorchRecoveryError(f"{path} must be lowercase SHA-256")
    return value


__all__ = [
    "DLPytorchRecoveryError",
    "DLCheckpointRecoveryObservation",
    "pytorch_recovery_identity",
    "run_pytorch_checkpoint_recovery",
]


if __name__ == "__main__":
    raise SystemExit(_worker_entry(sys.argv[1:]))
