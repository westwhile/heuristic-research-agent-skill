"""Controlled child-process interruption recovery for bounded PyTorch/CUDA.

The module exposes one deep interface over the R2 checkpoint implementation.
It starts one owned source child, waits for an atomically published checkpoint
commit signal, verifies the signal against the exact ``Popen`` identity and
checkpoint bytes, and only then terminates that child through its ``Popen``
object.  Fresh resume and uninterrupted-control processes must finish with
exact model, optimizer, scheduler, loss, and cumulative-step equality.

This is deliberately a controlled parent-requested termination exercise, not
an observation of scheduler preemption.  The caller supplies an existing empty
directory outside the repository; checkpoint bytes never enter the returned
record, which contains only an opaque locator, hashes, and lifecycle facts.
"""

from __future__ import annotations

import hashlib
import math
import os
import secrets
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
from .pytorch_recovery import (
    DLPytorchRecoveryError,
    _build_training,
    _invoke_stage,
    _load_torch,
    _observe_runtime,
    _public_process,
    _sha256,
    _state_sha256,
    _validate_artifact_root,
    _validate_checkpoint_file,
    _validate_equivalence,
    _validate_fixture,
    _validate_manifest,
    _validate_observed_runtime,
    _validate_stage,
    _worker_load_checkpoint,
    pytorch_recovery_identity,
)

_OBSERVATION_SCHEMA = "dl-controlled-interruption-recovery-observation/v1"
_RUNNER_NAME = "pytorch-gpu-controlled-interruption-recovery-runner"
_RUNNER_VERSION = "0.1.0"
_PROCESS_ROLES = frozenset(
    {"interruptible_source", "resume", "uninterrupted_control"}
)
_SOURCE_SIGNAL_FIELDS = frozenset(
    {
        "schema",
        "role",
        "nonce",
        "pid",
        "parent_pid",
        "completed_steps",
        "duration_seconds",
        "peak_memory_bytes",
        "execution",
        "checkpoint",
        "checkpoint_lifecycle",
    }
)
_SOURCE_SIGNAL_SCHEMA = "pytorch-controlled-interruption-commit-signal/v1"
_LIMITATIONS = (
    "Synthetic fixture only.",
    "One real PyTorch/CUDA host and its primary device only.",
    "The interruption was requested by the parent after checkpoint confirmation; no involuntary scheduler preemption was observed.",
    "The artifact store was a caller-managed local temporary directory, not a remote store.",
    "No real dataset, external scheduler service, cross-GPU, or cross-driver behavior was tested.",
    "No scientific, predictive, strategy, production, or adoption claim is supported.",
)


class DLPytorchInterruptionError(DLPytorchRecoveryError):
    """A controlled-interruption recovery receipt could not be established."""


def _semantic_violations(payload: dict[str, Any]) -> tuple[str, ...]:
    violations: list[str] = []
    fixture = payload["fixture"]
    processes = payload["processes"]
    roles = [row["role"] for row in processes]
    if len(roles) != len(set(roles)) or set(roles) != _PROCESS_ROLES:
        violations.append(
            "interruption-process-roles: exactly one interruptible_source, resume, "
            "and uninterrupted_control process is required"
        )
    for row in processes:
        for field in ("completed_steps", "duration_seconds", "peak_memory_bytes"):
            if row[field] < 0:
                violations.append(
                    f"interruption-process-nonnegative: {row['role']}.{field} must be nonnegative"
                )

    checkpoint = payload["checkpoint"]
    lifecycle = checkpoint["lifecycle"]
    if checkpoint["size_bytes"] <= 0:
        violations.append("interruption-checkpoint-size: checkpoint must contain bytes")
    if checkpoint["completed_steps"] != fixture["checkpoint_step"]:
        violations.append(
            "interruption-checkpoint-step: checkpoint step must match the fixture"
        )
    for field in (
        "temporary_payload_verified",
        "atomic_replacement_completed",
        "authoritative_payload_verified",
    ):
        if lifecycle[field] is not True:
            violations.append(
                f"interruption-checkpoint-lifecycle: {field} must be true"
            )

    interruption = payload["interruption"]
    for field in (
        "checkpoint_confirmed_before_request",
        "spawn_identity_verified",
        "source_exit_observed",
        "source_returncode_nonzero",
    ):
        if interruption[field] is not True:
            violations.append(f"interruption-ordering: {field} must be true")
    if interruption["kind"] != "parent_requested_owned_child_termination":
        violations.append("interruption-kind: interruption kind is invalid")
    if interruption["termination_method"] != "popen_terminate":
        violations.append("interruption-method: termination must use Popen.terminate")

    equivalence = payload["equivalence"]
    for prefix in ("model", "optimizer", "scheduler"):
        if (
            equivalence[f"resumed_{prefix}_state_sha256"]
            != equivalence[f"control_{prefix}_state_sha256"]
        ):
            violations.append(
                f"interruption-{prefix}-equivalence: resumed and control hashes must match"
            )
        if equivalence[f"{prefix}_state_exact"] is not True:
            violations.append(
                f"interruption-{prefix}-exact: exact-state flag must be true"
            )
    expected_delta = abs(
        equivalence["resumed_final_loss"] - equivalence["control_final_loss"]
    )
    if equivalence["loss_absolute_delta"] != expected_delta:
        violations.append(
            "interruption-loss-delta: loss_absolute_delta must match recorded losses"
        )
    if equivalence["loss_absolute_delta"] != 0:
        violations.append("interruption-loss-equivalence: final losses must match exactly")

    ledger = payload["budget_ledger"]
    by_role = {row["role"]: row for row in processes}
    if set(by_role) == _PROCESS_ROLES:
        for role, ledger_field in (
            ("interruptible_source", "source_steps"),
            ("resume", "resume_segment_steps"),
            ("uninterrupted_control", "control_steps"),
        ):
            if by_role[role]["completed_steps"] != ledger[ledger_field]:
                violations.append(
                    f"interruption-process-budget-match: {role} steps must match {ledger_field}"
                )
    if ledger["declared_steps"] != fixture["requested_steps"]:
        violations.append(
            "interruption-budget-declared: declared steps must match fixture"
        )
    if ledger["source_steps"] != fixture["checkpoint_step"]:
        violations.append(
            "interruption-budget-source: source steps must match checkpoint"
        )
    if ledger["resume_segment_steps"] != (
        fixture["requested_steps"] - fixture["checkpoint_step"]
    ):
        violations.append(
            "interruption-budget-resume: resume must consume only remaining steps"
        )
    if ledger["resumed_cumulative_steps"] != fixture["requested_steps"]:
        violations.append(
            "interruption-budget-cumulative: resumed steps must equal declared steps"
        )
    if ledger["control_steps"] != fixture["requested_steps"]:
        violations.append(
            "interruption-budget-control: control must consume declared steps"
        )
    if ledger["double_charged"] is not False:
        violations.append("interruption-budget-double-charge: must be false")
    return tuple(violations)


@dataclass(frozen=True)
class DLControlledInterruptionRecoveryObservation:
    """Immutable schema- and semantics-validated interruption receipt."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _OBSERVATION_SCHEMA:
            raise AdapterError(
                "DLControlledInterruptionRecoveryObservation wraps "
                f"{_OBSERVATION_SCHEMA} payloads, got {self._record.schema_id!r}"
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
    ) -> "DLControlledInterruptionRecoveryObservation":
        return cls(_load_seam_record(_OBSERVATION_SCHEMA, payload))

    @classmethod
    def from_json(
        cls, source: "str | bytes | bytearray"
    ) -> "DLControlledInterruptionRecoveryObservation":
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


def pytorch_interruption_identity() -> dict[str, str]:
    """Return the R4 orchestrator identity bound to this module's bytes."""
    try:
        source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:
        raise DLPytorchInterruptionError(
            "cannot hash the PyTorch interruption runner source"
        ) from exc
    return {
        "name": _RUNNER_NAME,
        "version": _RUNNER_VERSION,
        "source_sha256": source_sha256,
    }


def run_pytorch_controlled_interruption_recovery(
    manifest: DLRunManifest,
    fixture_payload: dict[str, Any],
    artifact_root: str | os.PathLike[str],
) -> DLControlledInterruptionRecoveryObservation:
    """Recover exactly after terminating one verified, owned source child."""
    fixture = _validate_fixture(fixture_payload)
    manifest_data = _validate_interruption_manifest(manifest, fixture)
    root = _validate_artifact_root(artifact_root)
    torch = _load_torch()
    execution = _observe_runtime(torch)
    _validate_observed_runtime(manifest_data, execution)

    checkpoint_path = root / "checkpoint.pt"
    source = _interrupt_after_commit(
        root,
        {
            "fixture": fixture["execution"],
            "fixture_sha256": fixture["sha256"],
            "runner": pytorch_interruption_identity(),
            "checkpoint_implementation": pytorch_recovery_identity(),
            "checkpoint_path": str(checkpoint_path),
        },
        execution,
    )
    _validate_stage(source, "interruptible_source", execution)
    _validate_checkpoint_file(
        checkpoint_path,
        source["checkpoint"],
        fixture["payload"]["checkpoint_step"],
    )

    recovery_common = {
        "fixture": fixture["execution"],
        "fixture_sha256": fixture["sha256"],
        "runner": pytorch_recovery_identity(),
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_content_sha256": source["checkpoint"]["content_sha256"],
    }
    resume = _invoke_stage(root, "resume", recovery_common)
    control = _invoke_stage(root, "uninterrupted_control", recovery_common)
    _validate_stage(resume, "resume", execution)
    _validate_stage(control, "uninterrupted_control", execution)
    _validate_equivalence(resume, control)
    if (
        source["duration_seconds"] + resume["duration_seconds"]
        > float(manifest_data["budget"]["cost_limit"])
    ):
        raise DLPytorchInterruptionError(
            "resumed execution exceeded the declared accelerator_seconds cost limit"
        )

    core = {
        "schema": _OBSERVATION_SCHEMA,
        "manifest_sha256": manifest.sha256,
        "run_id": manifest_data["run_id"],
        "study_id": manifest_data["study_id"],
        "case_sha256": manifest_data["case_sha256"],
        "observed_at": _utc_now(),
        "evidence_scope": (
            "real_framework_hardware_controlled_child_process_"
            "interruption_recovery_engineering"
        ),
        "status": "completed",
        "runner": {
            **pytorch_interruption_identity(),
            "checkpoint_implementation": pytorch_recovery_identity(),
        },
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
        "interruption": source["interruption"],
        "checkpoint": {
            "locator": (
                f"artifact://{manifest_data['run_id']}/controlled-interruption-"
                f"checkpoint-{fixture['payload']['checkpoint_step']:04d}.pt"
            ),
            **source["checkpoint"],
            "store_kind": "caller_managed_local_directory",
            "repository_persisted": False,
            "lifecycle": source["checkpoint_lifecycle"],
        },
        "equivalence": {
            "resumed_model_state_sha256": resume["model_state_sha256"],
            "control_model_state_sha256": control["model_state_sha256"],
            "model_state_exact": True,
            "resumed_optimizer_state_sha256": resume["optimizer_state_sha256"],
            "control_optimizer_state_sha256": control["optimizer_state_sha256"],
            "optimizer_state_exact": True,
            "resumed_scheduler_state_sha256": resume["scheduler_state_sha256"],
            "control_scheduler_state_sha256": control["scheduler_state_sha256"],
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
    observation_id = f"dl-interruption-{canonical_sha256(core)[:16]}"
    return DLControlledInterruptionRecoveryObservation.from_payload(
        {"observation_id": observation_id, **core}
    )


def _validate_interruption_manifest(
    manifest: Any, fixture: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(manifest, DLRunManifest):
        raise DLPytorchInterruptionError("manifest must be a DLRunManifest")
    payload = manifest.payload
    if payload["runner"] != pytorch_interruption_identity():
        raise DLPytorchInterruptionError(
            "manifest.runner must match the exact interruption runner identity"
        )
    # Reuse the R2 manifest contract without widening its public interface.
    proxy = manifest.payload
    proxy["runner"] = pytorch_recovery_identity()
    try:
        _validate_manifest(DLRunManifest.from_payload(proxy), fixture)
    except (AdapterError, DLPytorchRecoveryError) as exc:
        raise DLPytorchInterruptionError(
            "manifest does not satisfy the checkpoint recovery contract"
        ) from exc
    return payload


def _interrupt_after_commit(
    root: Path, request: dict[str, Any], execution: dict[str, Any]
) -> dict[str, Any]:
    nonce = secrets.token_hex(16)
    request_path = root / ".interruptible-source-request.json"
    signal_path = root / ".interruptible-source-committed.json"
    request_payload = {
        **request,
        "nonce": nonce,
        "parent_pid": os.getpid(),
        "signal_path": str(signal_path),
    }
    request_path.write_bytes(canonical_bytes(request_payload))
    command = [
        _direct_python_executable(),
        "-B",
        "-m",
        __name__,
        "--source-worker",
        str(request_path),
        str(signal_path),
    ]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process: subprocess.Popen[Any] | None = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
            env=_child_environment(),
        )
        signal = _wait_for_commit_signal(signal_path, process, timeout_seconds=120)
        source = _validate_commit_signal(
            signal,
            process,
            expected_nonce=nonce,
            expected_parent_pid=os.getpid(),
            checkpoint_path=Path(request["checkpoint_path"]),
            execution=execution,
        )
        termination = _terminate_verified_child(process, expected_pid=signal["pid"])
        source["interruption"] = termination
        return source
    except DLPytorchInterruptionError:
        raise
    except (OSError, CoreError, ValueError, TypeError) as exc:
        raise DLPytorchInterruptionError(
            "interruptible source process could not establish a valid commit signal"
        ) from exc
    finally:
        if process is not None:
            _cleanup_spawned_child(process)
        for path in (request_path, signal_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _wait_for_commit_signal(
    signal_path: Path,
    process: subprocess.Popen[Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if signal_path.is_file():
            try:
                payload = load_strict_json(signal_path.read_bytes())
            except (OSError, CoreError) as exc:
                raise DLPytorchInterruptionError(
                    "checkpoint commit signal is unreadable"
                ) from exc
            if not isinstance(payload, dict):
                raise DLPytorchInterruptionError(
                    "checkpoint commit signal must be an object"
                )
            return payload
        returncode = process.poll()
        if returncode is not None:
            raise DLPytorchInterruptionError(
                "source child exited before checkpoint confirmation"
            )
        time.sleep(0.01)
    raise DLPytorchInterruptionError(
        "source child was not interrupted because checkpoint confirmation timed out"
    )


def _direct_python_executable() -> str:
    """Resolve the process that will execute Python, bypassing venv launchers."""
    source = getattr(sys, "_base_executable", None) or sys.executable
    try:
        executable = Path(source).resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        raise DLPytorchInterruptionError(
            "direct Python executable could not be resolved"
        ) from exc
    if not executable.is_file():
        raise DLPytorchInterruptionError("direct Python executable is not a file")
    return str(executable)


def _child_environment() -> dict[str, str]:
    """Carry the caller's already-resolved import paths into the direct child."""
    environment = os.environ.copy()
    entries = [str(Path(entry).resolve()) for entry in sys.path if entry]
    if not entries:
        raise DLPytorchInterruptionError("child Python import path is empty")
    environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(entries))
    return environment


def _validate_commit_signal(
    signal: dict[str, Any],
    process: subprocess.Popen[Any],
    *,
    expected_nonce: str,
    expected_parent_pid: int,
    checkpoint_path: Path,
    execution: dict[str, Any],
) -> dict[str, Any]:
    if set(signal) != _SOURCE_SIGNAL_FIELDS:
        raise DLPytorchInterruptionError("checkpoint commit signal fields are invalid")
    if signal["schema"] != _SOURCE_SIGNAL_SCHEMA:
        raise DLPytorchInterruptionError("checkpoint commit signal schema is invalid")
    if signal["role"] != "interruptible_source":
        raise DLPytorchInterruptionError("checkpoint commit signal role is invalid")
    if signal["nonce"] != expected_nonce:
        raise DLPytorchInterruptionError("checkpoint commit signal is stale")
    if signal["pid"] != process.pid:
        raise DLPytorchInterruptionError(
            "checkpoint commit signal PID does not identify the spawned child"
        )
    if signal["parent_pid"] != expected_parent_pid:
        raise DLPytorchInterruptionError(
            "checkpoint commit signal parent PID does not identify the orchestrator"
        )
    if process.poll() is not None:
        raise DLPytorchInterruptionError(
            "spawned child exited after checkpoint confirmation but before termination"
        )
    stage = dict(signal)
    for field in ("duration_seconds",):
        if isinstance(stage[field], Decimal):
            stage[field] = float(stage[field])
    _validate_stage(stage, "interruptible_source", execution)
    lifecycle = stage["checkpoint_lifecycle"]
    if lifecycle != {
        "temporary_payload_verified": True,
        "atomic_replacement_completed": True,
        "authoritative_payload_verified": True,
    }:
        raise DLPytorchInterruptionError(
            "checkpoint lifecycle was not fully committed before interruption"
        )
    try:
        _validate_checkpoint_file(
            checkpoint_path, stage["checkpoint"], stage["completed_steps"]
        )
    except DLPytorchRecoveryError as exc:
        raise DLPytorchInterruptionError(
            "checkpoint commit signal failed authoritative integrity verification"
        ) from exc
    pending_path = checkpoint_path.with_name(f".{checkpoint_path.name}.pending")
    if pending_path.exists():
        raise DLPytorchInterruptionError(
            "checkpoint temporary payload still exists after commit signal"
        )
    return {
        "role": stage["role"],
        "completed_steps": stage["completed_steps"],
        "duration_seconds": stage["duration_seconds"],
        "peak_memory_bytes": stage["peak_memory_bytes"],
        "execution": stage["execution"],
        "checkpoint": stage["checkpoint"],
        "checkpoint_lifecycle": lifecycle,
    }


def _terminate_verified_child(
    process: subprocess.Popen[Any], *, expected_pid: int
) -> dict[str, Any]:
    if process.pid != expected_pid or process.poll() is not None:
        raise DLPytorchInterruptionError(
            "refusing to terminate a process without live spawned-child identity"
        )
    process.terminate()
    try:
        returncode = process.wait(timeout=10)
    except subprocess.TimeoutExpired as exc:
        # Fail closed: this run did not observe the requested termination.  A
        # later finally block may clean up the same owned Popen object.
        raise DLPytorchInterruptionError(
            "spawned source child did not exit after Popen.terminate"
        ) from exc
    if returncode == 0:
        raise DLPytorchInterruptionError(
            "source child exited normally instead of observing termination"
        )
    return {
        "kind": "parent_requested_owned_child_termination",
        "checkpoint_confirmed_before_request": True,
        "spawn_identity_verified": True,
        "termination_method": "popen_terminate",
        "source_exit_observed": True,
        "source_returncode_nonzero": True,
    }


def _cleanup_spawned_child(process: subprocess.Popen[Any]) -> None:
    """Best-effort cleanup scoped only to the exact child object we spawned."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _source_worker(request: dict[str, Any], signal_path: Path) -> None:
    torch = _load_torch()
    execution = _observe_runtime(torch)
    if request.get("runner") != pytorch_interruption_identity():
        raise DLPytorchInterruptionError("source worker runner identity mismatch")
    if request.get("checkpoint_implementation") != pytorch_recovery_identity():
        raise DLPytorchInterruptionError(
            "source worker checkpoint implementation identity mismatch"
        )
    fixture = request.get("fixture")
    if not isinstance(fixture, dict):
        raise DLPytorchInterruptionError("source worker fixture is invalid")
    fixture = dict(fixture)
    for field in ("learning_rate", "momentum", "scheduler_gamma"):
        fixture[field] = float(fixture[field])
    nonce = request.get("nonce")
    if (
        not isinstance(nonce, str)
        or len(nonce) != 32
        or any(char not in "0123456789abcdef" for char in nonce)
    ):
        raise DLPytorchInterruptionError("source worker nonce is invalid")
    parent_pid = request.get("parent_pid")
    if not isinstance(parent_pid, int) or isinstance(parent_pid, bool) or parent_pid <= 0:
        raise DLPytorchInterruptionError("source worker parent pid is invalid")
    checkpoint_path = Path(request.get("checkpoint_path", ""))
    if not checkpoint_path.is_absolute() or not signal_path.is_absolute():
        raise DLPytorchInterruptionError("source worker paths are invalid")
    if signal_path != Path(request.get("signal_path", "")):
        raise DLPytorchInterruptionError("source worker signal path mismatch")

    model, optimizer, scheduler, features, targets, loss_function = _build_training(
        torch, fixture
    )
    steps = fixture["checkpoint_step"]
    torch.cuda.synchronize(0)
    torch.cuda.reset_peak_memory_stats(0)
    started = time.perf_counter()
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = loss_function(model(features), targets)
        loss.backward()
        optimizer.step()
        scheduler.step()
    torch.cuda.synchronize(0)
    duration = float(time.perf_counter() - started)
    peak_memory = int(torch.cuda.max_memory_allocated(0))
    if not math.isfinite(duration):
        raise DLPytorchInterruptionError("source worker duration is non-finite")

    checkpoint = {
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "scheduler_state": scheduler.state_dict(),
        "completed_steps": steps,
        "fixture_sha256": request["fixture_sha256"],
        "runner_source_sha256": request["checkpoint_implementation"][
            "source_sha256"
        ],
    }
    receipt, lifecycle = _commit_checkpoint_atomically(
        torch,
        checkpoint_path,
        checkpoint,
        expected_fixture_sha256=request["fixture_sha256"],
        expected_completed_steps=steps,
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
    )
    signal = {
        "schema": _SOURCE_SIGNAL_SCHEMA,
        "role": "interruptible_source",
        "nonce": nonce,
        "pid": os.getpid(),
        "parent_pid": parent_pid,
        "completed_steps": steps,
        "duration_seconds": duration,
        "peak_memory_bytes": peak_memory,
        "execution": execution,
        "checkpoint": receipt,
        "checkpoint_lifecycle": lifecycle,
    }
    temporary_signal = signal_path.with_name(f".{signal_path.name}.pending")
    temporary_signal.write_bytes(canonical_bytes(signal))
    os.replace(temporary_signal, signal_path)
    while True:
        time.sleep(1)


def _commit_checkpoint_atomically(
    torch: Any,
    checkpoint_path: Path,
    checkpoint: dict[str, Any],
    *,
    expected_fixture_sha256: str,
    expected_completed_steps: int,
    model: Any,
    optimizer: Any,
    scheduler: Any,
) -> tuple[dict[str, Any], dict[str, bool]]:
    temporary = checkpoint_path.with_name(f".{checkpoint_path.name}.pending")
    if checkpoint_path.exists() or temporary.exists():
        raise DLPytorchInterruptionError(
            "checkpoint destination must not exist before atomic commit"
        )
    try:
        torch.save(checkpoint, temporary)
        raw = temporary.read_bytes()
        receipt = {
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "model_state_sha256": _state_sha256(torch, checkpoint["model_state"]),
            "optimizer_state_sha256": _state_sha256(
                torch, checkpoint["optimizer_state"]
            ),
            "scheduler_state_sha256": _state_sha256(
                torch, checkpoint["scheduler_state"]
            ),
            "completed_steps": expected_completed_steps,
        }
        _validate_checkpoint_file(temporary, receipt, expected_completed_steps)
        _worker_load_checkpoint(
            torch,
            temporary,
            receipt["content_sha256"],
            expected_fixture_sha256,
            expected_completed_steps,
            model,
            optimizer,
            scheduler,
        )
        os.replace(temporary, checkpoint_path)
        _validate_checkpoint_file(checkpoint_path, receipt, expected_completed_steps)
        _worker_load_checkpoint(
            torch,
            checkpoint_path,
            receipt["content_sha256"],
            expected_fixture_sha256,
            expected_completed_steps,
            model,
            optimizer,
            scheduler,
        )
        return receipt, {
            "temporary_payload_verified": True,
            "atomic_replacement_completed": True,
            "authoritative_payload_verified": True,
        }
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _source_worker_entry(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != "--source-worker":
        return 2
    _, request_name, signal_name = argv
    try:
        request = load_strict_json(Path(request_name).read_bytes())
        if not isinstance(request, dict):
            raise DLPytorchInterruptionError("source worker request is invalid")
        _source_worker(request, Path(signal_name))
    except Exception:
        return 1
    return 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


__all__ = [
    "DLPytorchInterruptionError",
    "DLControlledInterruptionRecoveryObservation",
    "pytorch_interruption_identity",
    "run_pytorch_controlled_interruption_recovery",
]


if __name__ == "__main__":
    raise SystemExit(_source_worker_entry(sys.argv[1:]))
