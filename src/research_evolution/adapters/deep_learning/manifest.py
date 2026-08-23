"""Immutable deep-learning execution manifest (ADR-0009).

The manifest is a configuration declaration, not execution evidence.  This
module concentrates the cross-field rules that the repository's deliberately
small JSON-Schema engine cannot express: positive resource bounds, compatible
execution-mode/hardware pairs, container pin completeness, retention counts,
and exact-checkpoint recovery state.

Apart from the existing Adapter schema loader reading packaged schema
definitions, no operation reads caller data or artifacts, probes hardware,
reads a clock, accesses a network, or loads a model.  Callers supply every
fact, including ``created_at``.  A later runner may bind observations to
:attr:`DLRunManifest.sha256`, but constructing this object can never prove
that CPU or GPU training happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research_evolution.core import Record

from ..types import AdapterError, _load_seam_record

_SCHEMA_ID = "dl-run-manifest/v1"
_GPU_ACCELERATORS = frozenset({"cuda", "rocm", "mps"})
_BUDGET_FIELDS = (
    "max_samples",
    "max_steps",
    "max_epochs",
    "max_tokens",
    "max_flops",
    "cost_limit",
)
_WORK_CAP_FIELDS = (
    "max_steps",
    "max_epochs",
    "max_tokens",
    "max_flops",
    "cost_limit",
)
_RESUME_FIELDS = frozenset(
    {
        "checkpoint_id",
        "locator",
        "content_sha256",
        "source_run_id",
        "completed_steps",
        "completed_epochs",
        "consumed_budget_sha256",
        "optimizer_state_sha256",
        "scheduler_state_sha256",
    }
)
_EXACT_RESUME_REQUIRED = frozenset(
    {
        "checkpoint_id",
        "locator",
        "content_sha256",
        "source_run_id",
        "completed_steps",
        "completed_epochs",
        "consumed_budget_sha256",
        "optimizer_state_sha256",
    }
)


def _semantic_violations(payload: dict[str, Any]) -> tuple[str, ...]:
    """Return stable, caller-text-free semantic diagnostics."""
    violations: list[str] = []
    hardware = payload["hardware"]
    runtime = payload["runtime"]
    framework = payload["framework"]
    container = payload["container"]
    budget = payload["budget"]
    checkpoint = payload["checkpoint_policy"]
    resume = checkpoint["resume"]

    if hardware["device_count"] <= 0:
        violations.append(
            "dl-device-count-positive: hardware.device_count must be greater than zero"
        )
    if hardware["memory_bytes_per_device"] <= 0:
        violations.append(
            "dl-device-memory-positive: hardware.memory_bytes_per_device must be greater than zero"
        )

    for field in _BUDGET_FIELDS:
        if budget[field] < 0:
            violations.append(
                f"dl-budget-nonnegative: budget.{field} must not be negative"
            )
    if budget["max_samples"] <= 0:
        violations.append(
            "dl-sample-budget-positive: budget.max_samples must be greater than zero"
        )
    if not any(budget[field] > 0 for field in _WORK_CAP_FIELDS):
        violations.append(
            "dl-work-budget-required: at least one work or cost cap must be greater than zero"
        )

    mode = payload["execution_mode"]
    accelerator = hardware["accelerator"]
    if mode == "cpu_fixture" and accelerator != "cpu":
        violations.append(
            "dl-mode-accelerator-match: cpu_fixture requires the cpu accelerator"
        )
    if mode in {"gpu_fixture", "gpu_training"} and accelerator not in _GPU_ACCELERATORS:
        violations.append(
            "dl-mode-accelerator-match: GPU modes require cuda, rocm, or mps"
        )

    has_backend_version = "backend_version" in framework
    if accelerator in {"cuda", "rocm"} and not has_backend_version:
        violations.append(
            "dl-backend-version-required: cuda and rocm require framework.backend_version"
        )
    if accelerator in {"cpu", "mps"} and has_backend_version:
        violations.append(
            "dl-backend-version-forbidden: cpu and mps must omit framework.backend_version"
        )
    if accelerator == "rocm" and runtime["os"] != "linux":
        violations.append("dl-runtime-accelerator-match: rocm requires linux")
    if accelerator == "mps" and runtime["os"] != "macos":
        violations.append("dl-runtime-accelerator-match: mps requires macos")
    if accelerator == "cuda" and runtime["os"] not in {"windows", "linux"}:
        violations.append("dl-runtime-accelerator-match: cuda requires windows or linux")

    container_kind = container["kind"]
    container_pins = {"image", "digest_sha256"}
    present_container_pins = container_pins.intersection(container)
    if container_kind == "none" and present_container_pins:
        violations.append(
            "dl-container-pins-forbidden: container kind none must omit image and digest"
        )
    if container_kind != "none" and present_container_pins != container_pins:
        violations.append(
            "dl-container-pins-required: a container requires both image and digest"
        )

    retention = checkpoint["retention"]
    max_retained = checkpoint["max_retained"]
    expected_exact_counts = {"none": 0, "last": 1, "best_and_last": 2, "all": 0}
    if retention in expected_exact_counts and max_retained != expected_exact_counts[retention]:
        violations.append(
            "dl-retention-count-match: max_retained does not match the retention policy"
        )
    if retention == "last_n" and max_retained <= 0:
        violations.append(
            "dl-retention-count-match: last_n requires max_retained greater than zero"
        )
    if max_retained < 0:
        violations.append(
            "dl-retention-count-nonnegative: checkpoint_policy.max_retained must not be negative"
        )

    scheduler_enabled = payload["scheduler"]["name"] != "none"
    if not scheduler_enabled and checkpoint["save_scheduler_state"]:
        violations.append(
            "dl-scheduler-state-forbidden: scheduler none cannot save scheduler state"
        )

    resume_mode = resume["mode"]
    present_resume_fields = _RESUME_FIELDS.intersection(resume)
    if resume_mode == "fresh" and present_resume_fields:
        violations.append(
            "dl-fresh-resume-empty: a fresh run must not declare checkpoint state"
        )
    if resume_mode == "exact_checkpoint":
        missing = _EXACT_RESUME_REQUIRED.difference(resume)
        if missing:
            violations.append(
                "dl-exact-resume-complete: exact checkpoint recovery requires "
                "all lineage and optimizer fields"
            )
        if not checkpoint["save_optimizer_state"]:
            violations.append(
                "dl-exact-resume-optimizer: exact recovery requires optimizer state retention"
            )
        if scheduler_enabled:
            if not checkpoint["save_scheduler_state"]:
                violations.append(
                    "dl-exact-resume-scheduler: exact recovery with a scheduler "
                    "requires scheduler state retention"
                )
            if "scheduler_state_sha256" not in resume:
                violations.append(
                    "dl-exact-resume-scheduler: exact recovery with a scheduler "
                    "requires its state hash"
                )
        elif "scheduler_state_sha256" in resume:
            violations.append(
                "dl-exact-resume-scheduler: scheduler state is forbidden when scheduler is none"
            )

        completed_steps = resume.get("completed_steps")
        completed_epochs = resume.get("completed_epochs")
        if completed_steps is not None and completed_steps < 0:
            violations.append(
                "dl-resume-progress-nonnegative: completed_steps must not be negative"
            )
        if completed_epochs is not None and completed_epochs < 0:
            violations.append(
                "dl-resume-progress-nonnegative: completed_epochs must not be negative"
            )
        if (
            completed_steps is not None
            and budget["max_steps"] > 0
            and completed_steps > budget["max_steps"]
        ):
            violations.append(
                "dl-resume-within-budget: completed_steps exceeds the declared step cap"
            )
        if (
            completed_epochs is not None
            and budget["max_epochs"] > 0
            and completed_epochs > budget["max_epochs"]
        ):
            violations.append(
                "dl-resume-within-budget: completed_epochs exceeds the declared epoch cap"
            )

    return tuple(violations)


@dataclass(frozen=True)
class DLRunManifest:
    """Validated, hash-bound declaration consumed by future DL runners.

    The interface deliberately exposes the canonical payload and a few
    decision-relevant facts only.  Hardware probing, budget accounting,
    checkpoint I/O, and training remain outside this manifest module.
    """

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _SCHEMA_ID:
            raise AdapterError(
                f"DLRunManifest wraps {_SCHEMA_ID} payloads, got {self._record.schema_id!r}"
            )
        violations = _semantic_violations(self._record.data)
        if violations:
            raise AdapterError(
                f"invalid {_SCHEMA_ID} semantics: {len(violations)} violation(s)",
                details=violations,
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DLRunManifest":
        """Build from a programmatic strict-JSON tree."""
        return cls(_load_seam_record(_SCHEMA_ID, payload))

    @classmethod
    def from_json(cls, source: "str | bytes | bytearray") -> "DLRunManifest":
        """Build from strict JSON text or bytes."""
        return cls(_load_seam_record(_SCHEMA_ID, source))

    @property
    def sha256(self) -> str:
        """Canonical SHA-256 of the complete configuration declaration."""
        return self._record.sha256

    @property
    def payload(self) -> dict[str, Any]:
        """Return a defensive copy of the validated payload."""
        return self._record.data

    @property
    def case_sha256(self) -> str:
        return self._record.data["case_sha256"]

    @property
    def requests_gpu(self) -> bool:
        """Whether the requested mode is GPU-backed; never proof it ran."""
        return self._record.data["execution_mode"] in {"gpu_fixture", "gpu_training"}

    @property
    def resume_mode(self) -> str:
        return self._record.data["checkpoint_policy"]["resume"]["mode"]
