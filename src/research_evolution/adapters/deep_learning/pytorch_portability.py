"""Portable, public-safe PyTorch/CUDA trial receipts.

The R5 module has one execution interface.  Its implementation is added in
vertical slices; the immutable receipt type already fixes the output contract
used by the comparison module and external callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib
import platform
import re
from pathlib import Path
from typing import Any

from research_evolution.adapters.deep_learning.manifest import DLRunManifest
from research_evolution.adapters.deep_learning.pytorch_interruption import (
    pytorch_interruption_identity,
    run_pytorch_controlled_interruption_recovery,
)
from research_evolution.adapters.deep_learning.pytorch_observation import (
    pytorch_observation_identity,
)
from research_evolution.adapters.deep_learning.pytorch_reproducibility import (
    pytorch_reproducibility_identity,
    run_pytorch_same_host_reproducibility,
)
from research_evolution.adapters.types import AdapterError, _load_seam_record
from research_evolution.core import Record, canonical_sha256

_RECEIPT_SCHEMA = "dl-portability-trial-receipt/v1"
_RUNNER_NAME = "pytorch-portability-trial-runner"
_RUNNER_VERSION = "0.1.0"
_PLAN_SCHEMA = "pytorch-portability-trial-plan/v1"
_SEEDS = (7, 11, 13)
_LIMITATIONS = (
    "A receipt does not prove an independent host or participant.",
    "Only bounded synthetic single-environment engineering behavior was executed.",
    "Parent-requested child termination is not involuntary scheduler preemption.",
    "No real dataset, external checkpoint store, production workload, or upload was used.",
)


class DLPytorchPortabilityError(AdapterError):
    """A portable CUDA trial receipt could not be honestly established."""


def _semantic_violations(payload: dict[str, Any]) -> tuple[str, ...]:
    violations: list[str] = []
    same_host = payload["same_host_reproducibility"]
    expected = same_host["expected_seeds"]
    results = same_host["results"]
    result_seeds = [row["seed"] for row in results]
    if expected != [7, 11, 13] or result_seeds != expected:
        violations.append(
            "portability-seed-plan: the R5 receipt requires seeds 7, 11, and 13"
        )
    if same_host["successful_seeds"] != expected or same_host["failed_seeds"]:
        violations.append(
            "portability-seed-success: every preregistered seed must reproduce"
        )
    if same_host["exact_repeat_matches"] != len(expected):
        violations.append(
            "portability-repeat-matches: every seed requires an exact local repeat"
        )
    driver = payload["execution"]["driver"]
    if (driver["status"] == "observed") == (driver["version"] == "unavailable"):
        violations.append(
            "portability-driver-status: observed requires a version and unavailable forbids one"
        )
    privacy = payload["privacy"]
    if any(privacy.values()):
        violations.append(
            "portability-public-safe: paths, credentials, identifiers, and upload "
            "must all remain absent"
        )
    if any(_contains_local_path(value) for value in _string_values(payload)):
        violations.append(
            "portability-public-safe: receipt strings must not contain local paths"
        )
    if any(_contains_credential_shape(value) for value in _string_values(payload)):
        violations.append(
            "portability-public-safe: receipt strings must not contain credential shapes"
        )
    if any(_contains_personal_identifier(value) for value in _string_values(payload)):
        violations.append(
            "portability-public-safe: receipt strings must not contain personal identifiers"
        )
    return tuple(violations)


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    return []


def _contains_local_path(value: str) -> bool:
    return bool(
        re.search(r"[A-Za-z]:\\", value)
        or "/home/" in value
        or "/Users/" in value
        or "file://" in value.lower()
    )


def _contains_credential_shape(value: str) -> bool:
    return bool(
        re.search(r"gh[pousr]_[A-Za-z0-9]{20,}", value)
        or re.search(r"sk-[A-Za-z0-9_-]{20,}", value)
        or re.search(r"AKIA[0-9A-Z]{16}", value)
        or re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", value)
    )


def _contains_personal_identifier(value: str) -> bool:
    return bool(
        re.search(
            r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])",
            value,
        )
    )


@dataclass(frozen=True)
class DLPortabilityTrialReceipt:
    """Immutable, schema-validated R5 portability-trial receipt."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _RECEIPT_SCHEMA:
            raise AdapterError(
                f"DLPortabilityTrialReceipt wraps {_RECEIPT_SCHEMA} payloads, "
                f"got {self._record.schema_id!r}"
            )
        violations = _semantic_violations(self._record.data)
        if violations:
            raise AdapterError(
                f"invalid {_RECEIPT_SCHEMA} semantics: "
                f"{len(violations)} violation(s)",
                details=violations,
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DLPortabilityTrialReceipt":
        return cls(_load_seam_record(_RECEIPT_SCHEMA, payload))

    @classmethod
    def from_json(
        cls, source: str | bytes | bytearray
    ) -> "DLPortabilityTrialReceipt":
        return cls(_load_seam_record(_RECEIPT_SCHEMA, source))

    @property
    def sha256(self) -> str:
        return self._record.sha256

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def repository_commit(self) -> str:
        return self._record.data["repository"]["commit_oid"]


def run_pytorch_portability_trial(
    plan_payload: dict[str, Any], *, artifact_root: str | Path
) -> DLPortabilityTrialReceipt:
    """Run the fixed R5 CUDA trial and return one public-safe receipt."""

    plan = _validate_trial_plan(plan_payload)
    root = _validate_artifact_root(artifact_root)
    torch = _load_torch()
    runtime = _observe_runtime(torch)
    created_at = _utc_now()

    reproducibility_fixtures = [_reproducibility_fixture(seed) for seed in _SEEDS]
    reproducibility_manifests = [
        _reproducibility_manifest(runtime, fixture, created_at)
        for fixture in reproducibility_fixtures
    ]
    interruption_fixture = _interruption_fixture()
    interruption_manifest = _interruption_manifest(
        runtime, interruption_fixture, created_at
    )
    reproducibility_root = root / "same-host-reproducibility"
    interruption_root = root / "controlled-interruption"
    try:
        reproducibility_root.mkdir()
        interruption_root.mkdir()
        same_host = run_pytorch_same_host_reproducibility(
            reproducibility_manifests,
            reproducibility_fixtures,
            reproducibility_root,
        )
        interruption = run_pytorch_controlled_interruption_recovery(
            interruption_manifest,
            interruption_fixture,
            interruption_root,
        )
    except (AdapterError, OSError) as exc:
        raise DLPytorchPortabilityError(
            "R5 portability trial did not establish both local engineering gates"
        ) from exc

    same_host_payload = same_host.payload
    interruption_payload = interruption.payload
    if same_host_payload["execution"] != interruption_payload["execution"]:
        raise DLPytorchPortabilityError(
            "R5 local gate execution environments do not match"
        )
    if (
        same_host_payload["summary"]["successful_seeds"] != list(_SEEDS)
        or same_host_payload["summary"]["failed_seeds"]
        or same_host_payload["summary"]["exact_repeat_matches"] != len(_SEEDS)
    ):
        raise DLPytorchPortabilityError(
            "R5 same-host gate did not reproduce every preregistered seed"
        )

    repository = plan["repository"]
    trial_plan_sha256 = canonical_sha256(
        {
            "schema": _PLAN_SCHEMA,
            "repository": repository,
            "same_host": {
                "expected_seeds": list(_SEEDS),
                "fixtures": [
                    canonical_sha256(fixture)
                    for fixture in reproducibility_fixtures
                ],
            },
            "controlled_interruption_fixture_sha256": canonical_sha256(
                interruption_fixture
            ),
            "runner": pytorch_portability_identity(),
        }
    )
    execution = same_host_payload["execution"]
    equivalence = interruption_payload["equivalence"]
    core = {
        "schema": _RECEIPT_SCHEMA,
        "trial_plan_sha256": trial_plan_sha256,
        "observed_at": _utc_now(),
        "evidence_scope": (
            "real_framework_hardware_portability_trial_readiness_engineering"
        ),
        "status": "completed",
        "repository": repository,
        "runner": {
            **pytorch_portability_identity(),
            "same_host_runner_sha256": pytorch_reproducibility_identity()[
                "source_sha256"
            ],
            "interruption_runner_sha256": pytorch_interruption_identity()[
                "source_sha256"
            ],
        },
        "execution": {
            "os": execution["os"],
            "architecture": execution["architecture"],
            "python_version": execution["python_version"],
            "framework_version": execution["framework"]["version"],
            "cuda_version": execution["framework"]["backend_version"],
            "driver": same_host_payload["driver_observation"],
            "device": {
                "model": execution["hardware"]["device_model"],
                "count": execution["hardware"]["device_count"],
                "memory_bytes": execution["hardware"][
                    "memory_bytes_per_device"
                ],
                "compute_capability": execution["hardware"][
                    "compute_capability"
                ],
            },
        },
        "same_host_reproducibility": {
            "report_sha256": same_host.sha256,
            "plan_sha256": same_host.plan_sha256,
            "expected_seeds": same_host_payload["expected_seeds"],
            "successful_seeds": same_host_payload["summary"]["successful_seeds"],
            "failed_seeds": same_host_payload["summary"]["failed_seeds"],
            "exact_repeat_matches": same_host_payload["summary"]
            ["exact_repeat_matches"],
            "results": [
                {
                    "seed": row["seed"],
                    "stable_sha256": row["repeat_a"]["stable_sha256"],
                    "final_loss": row["repeat_a"]["final_loss"],
                }
                for row in same_host_payload["results"]
            ],
        },
        "controlled_interruption": {
            "observation_sha256": interruption.sha256,
            "checkpoint_confirmed": interruption_payload["interruption"]
            ["checkpoint_confirmed_before_request"],
            "spawn_identity_verified": interruption_payload["interruption"]
            ["spawn_identity_verified"],
            "model_state_sha256": equivalence["resumed_model_state_sha256"],
            "optimizer_state_sha256": equivalence[
                "resumed_optimizer_state_sha256"
            ],
            "scheduler_state_sha256": equivalence[
                "resumed_scheduler_state_sha256"
            ],
            "final_loss": equivalence["resumed_final_loss"],
            "double_charged": interruption_payload["budget_ledger"][
                "double_charged"
            ],
            "scheduler_preemption_observed": False,
        },
        "privacy": {
            "local_paths_included": False,
            "credentials_included": False,
            "personal_identifiers_included": False,
            "automatic_upload_performed": False,
        },
        "limitations": list(_LIMITATIONS),
    }
    receipt_id = f"dl-portability-receipt-{canonical_sha256(core)[:16]}"
    return DLPortabilityTrialReceipt.from_payload(
        {"receipt_id": receipt_id, **core}
    )


def pytorch_portability_identity() -> dict[str, str]:
    """Return the R5 runner identity bound to exact module bytes."""

    try:
        source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:
        raise DLPytorchPortabilityError(
            "cannot hash the PyTorch portability runner source"
        ) from exc
    return {
        "name": _RUNNER_NAME,
        "version": _RUNNER_VERSION,
        "source_sha256": source_sha256,
    }


def _validate_trial_plan(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict) or set(source) != {"schema", "repository"}:
        raise DLPytorchPortabilityError("trial plan fields are invalid")
    if source["schema"] != _PLAN_SCHEMA:
        raise DLPytorchPortabilityError("trial plan schema is invalid")
    repository = source["repository"]
    if not isinstance(repository, dict) or set(repository) != {
        "commit_oid",
        "tree_oid",
        "archive_sha256",
        "dirty",
    }:
        raise DLPytorchPortabilityError("trial plan repository binding is invalid")
    for field, length in (("commit_oid", 40), ("tree_oid", 40), ("archive_sha256", 64)):
        value = repository[field]
        if (
            not isinstance(value, str)
            or len(value) != length
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise DLPytorchPortabilityError(
                f"trial plan repository.{field} must be {length} lowercase hexadecimal characters"
            )
    if repository["dirty"] is not False:
        raise DLPytorchPortabilityError("trial plan requires dirty=false")
    return {
        "schema": source["schema"],
        "repository": dict(repository),
    }


def _load_torch() -> Any:
    try:
        torch = importlib.import_module("torch")
    except (ImportError, ModuleNotFoundError) as exc:
        raise DLPytorchPortabilityError(
            "PyTorch is unavailable; R5 never installs framework payloads"
        ) from exc
    return torch


def _observe_runtime(torch: Any) -> dict[str, Any]:
    try:
        if not torch.cuda.is_available():
            raise DLPytorchPortabilityError("PyTorch CUDA is unavailable")
        properties = torch.cuda.get_device_properties(0)
        capability = torch.cuda.get_device_capability(0)
        framework_version = str(torch.__version__)
        cuda_version = str(torch.version.cuda)
    except DLPytorchPortabilityError:
        raise
    except Exception as exc:
        raise DLPytorchPortabilityError(
            "PyTorch CUDA runtime observation failed"
        ) from exc
    if not cuda_version or cuda_version == "None":
        raise DLPytorchPortabilityError("PyTorch CUDA backend version is unavailable")
    return {
        "os": platform.system().lower(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "framework_version": framework_version,
        "cuda_version": cuda_version,
        "device_model": str(properties.name),
        "device_count": int(torch.cuda.device_count()),
        "memory_bytes": int(properties.total_memory),
        "compute_capability": f"{capability[0]}.{capability[1]}",
    }


def _reproducibility_fixture(seed: int) -> dict[str, Any]:
    return {
        "schema": "pytorch-dl-fixture/v1",
        "fixture_id": f"r5-portability-reproducibility-{seed}",
        "case_sha256": canonical_sha256(
            {
                "case": "r5-portability-reproducibility",
                "scope": "bounded-synthetic-engineering",
            }
        ),
        "samples": 16,
        "input_features": 4,
        "hidden_units": 8,
        "output_features": 1,
        "learning_rate": 0.01,
        "requested_steps": 1,
        "seed": seed,
    }


def _interruption_fixture() -> dict[str, Any]:
    return {
        "schema": "pytorch-dl-recovery-fixture/v1",
        "fixture_id": "r5-portability-controlled-interruption-001",
        "case_sha256": canonical_sha256(
            {
                "case": "r5-portability-controlled-interruption-001",
                "scope": "bounded-synthetic-engineering",
            }
        ),
        "samples": 16,
        "input_features": 4,
        "hidden_units": 8,
        "output_features": 1,
        "learning_rate": 0.01,
        "momentum": 0.9,
        "requested_steps": 4,
        "checkpoint_step": 2,
        "seed": 20260824,
        "scheduler_step_size": 2,
        "scheduler_gamma": 0.5,
    }


def _base_manifest(
    runtime: dict[str, Any],
    *,
    manifest_id: str,
    run_id: str,
    study_id: str,
    case_sha256: str,
    runner: dict[str, str],
    max_steps: int,
    optimizer: dict[str, Any],
    scheduler: dict[str, Any],
    checkpoint_policy: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    return {
        "schema": "dl-run-manifest/v1",
        "manifest_id": manifest_id,
        "run_id": run_id,
        "study_id": study_id,
        "case_sha256": case_sha256,
        "evidence_scope": "configuration_only",
        "execution_mode": "gpu_fixture",
        "runner": runner,
        "hardware": {
            "accelerator": "cuda",
            "device_model": runtime["device_model"],
            "device_count": runtime["device_count"],
            "memory_bytes_per_device": runtime["memory_bytes"],
        },
        "runtime": {
            "os": runtime["os"],
            "architecture": runtime["architecture"],
            "python_version": runtime["python_version"],
        },
        "framework": {
            "name": "pytorch",
            "version": runtime["framework_version"],
            "backend_version": runtime["cuda_version"],
            "determinism": "strict",
        },
        "container": {"kind": "none"},
        "budget": {
            "max_samples": 16,
            "max_steps": max_steps,
            "max_epochs": 0,
            "max_tokens": 0,
            "max_flops": 0,
            "cost_limit": 120,
            "cost_unit": "accelerator_seconds",
        },
        "optimizer": optimizer,
        "scheduler": scheduler,
        "checkpoint_policy": checkpoint_policy,
        "created_at": created_at,
    }


def _reproducibility_manifest(
    runtime: dict[str, Any], fixture: dict[str, Any], created_at: str
) -> DLRunManifest:
    seed = fixture["seed"]
    payload = _base_manifest(
        runtime,
        manifest_id=f"r5-portability-repro-manifest-{seed}",
        run_id=f"r5-portability-repro-run-{seed}",
        study_id="r5-portability-repro-study-001",
        case_sha256=fixture["case_sha256"],
        runner=pytorch_observation_identity(),
        max_steps=fixture["requested_steps"],
        optimizer={
            "name": "sgd",
            "config_sha256": canonical_sha256(
                {"learning_rate": fixture["learning_rate"]}
            ),
        },
        scheduler={"name": "none", "config_sha256": canonical_sha256({})},
        checkpoint_policy={
            "artifact_reference": "external_locator_and_hash_only",
            "retention": "none",
            "max_retained": 0,
            "selection_metric": "final_loss",
            "selection_direction": "minimize",
            "save_optimizer_state": False,
            "save_scheduler_state": False,
            "recovery_accounting": "cumulative_no_double_charge",
            "resume": {"mode": "fresh"},
        },
        created_at=created_at,
    )
    return DLRunManifest.from_payload(payload)


def _interruption_manifest(
    runtime: dict[str, Any], fixture: dict[str, Any], created_at: str
) -> DLRunManifest:
    payload = _base_manifest(
        runtime,
        manifest_id="r5-portability-interruption-manifest-001",
        run_id="r5-portability-interruption-run-001",
        study_id="r5-portability-interruption-study-001",
        case_sha256=fixture["case_sha256"],
        runner=pytorch_interruption_identity(),
        max_steps=fixture["requested_steps"],
        optimizer={
            "name": "sgd",
            "config_sha256": canonical_sha256(
                {
                    "learning_rate": fixture["learning_rate"],
                    "momentum": fixture["momentum"],
                }
            ),
        },
        scheduler={
            "name": "step_lr",
            "config_sha256": canonical_sha256(
                {
                    "step_size": fixture["scheduler_step_size"],
                    "gamma": fixture["scheduler_gamma"],
                }
            ),
        },
        checkpoint_policy={
            "artifact_reference": "external_locator_and_hash_only",
            "retention": "last",
            "max_retained": 1,
            "selection_metric": "final_loss",
            "selection_direction": "minimize",
            "save_optimizer_state": True,
            "save_scheduler_state": True,
            "recovery_accounting": "cumulative_no_double_charge",
            "resume": {"mode": "fresh"},
        },
        created_at=created_at,
    )
    return DLRunManifest.from_payload(payload)


def _validate_artifact_root(source: str | Path) -> Path:
    try:
        candidate = Path(source)
    except TypeError as exc:
        raise DLPytorchPortabilityError("artifact_root is invalid") from exc
    if not candidate.is_absolute():
        raise DLPytorchPortabilityError("artifact_root must be absolute")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise DLPytorchPortabilityError("artifact_root must already exist") from exc
    if not resolved.is_dir():
        raise DLPytorchPortabilityError("artifact_root must be a directory")
    repository_root = Path(__file__).resolve().parents[4]
    try:
        resolved.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise DLPytorchPortabilityError("artifact_root must remain outside the repository")
    try:
        if any(resolved.iterdir()):
            raise DLPytorchPortabilityError("artifact_root must be empty")
    except OSError as exc:
        raise DLPytorchPortabilityError("artifact_root could not be inspected") from exc
    return resolved


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


__all__ = [
    "DLPytorchPortabilityError",
    "DLPortabilityTrialReceipt",
    "pytorch_portability_identity",
    "run_pytorch_portability_trial",
]
