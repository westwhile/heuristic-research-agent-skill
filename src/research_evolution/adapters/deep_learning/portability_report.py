"""Cross-environment comparison over public-safe R5 trial receipts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from research_evolution.adapters.deep_learning.pytorch_portability import (
    DLPortabilityTrialReceipt,
)
from research_evolution.adapters.types import AdapterError, _load_seam_record
from research_evolution.core import Record, canonical_sha256

_REPORT_SCHEMA = "dl-cross-environment-reproducibility-report/v1"
_POLICY_ID = "dl-cross-environment-comparison-policy/v1"
_LIMITATIONS = (
    "Environment metadata and receipts do not prove independent hosts or participants.",
    "A comparison does not establish external adoption, production reliability, "
    "or real-data validity.",
    "Final-loss tolerance does not establish full-state numerical equivalence.",
)


class DLPortabilityReportError(AdapterError):
    """A cross-environment report could not be honestly established."""


def _semantic_violations(payload: dict[str, Any]) -> tuple[str, ...]:
    violations: list[str] = []
    if payload["summary"]["receipt_count"] != len(payload["source_receipts"]):
        violations.append(
            "portability-report-receipt-count: summary must match source receipts"
        )
    environment_count = len(
        {row["environment_sha256"] for row in payload["source_receipts"]}
    )
    if payload["summary"]["environment_count"] != environment_count:
        violations.append(
            "portability-report-environment-count: summary must match distinct environment hashes"
        )
    return tuple(violations)


@dataclass(frozen=True)
class DLCrossEnvironmentReport:
    """Immutable comparison report over exact R5 receipt bytes."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _REPORT_SCHEMA:
            raise AdapterError(
                f"DLCrossEnvironmentReport wraps {_REPORT_SCHEMA} payloads, "
                f"got {self._record.schema_id!r}"
            )
        violations = _semantic_violations(self._record.data)
        if violations:
            raise AdapterError(
                f"invalid {_REPORT_SCHEMA} semantics: {len(violations)} violation(s)",
                details=violations,
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DLCrossEnvironmentReport":
        return cls(_load_seam_record(_REPORT_SCHEMA, payload))

    @classmethod
    def from_json(
        cls, source: str | bytes | bytearray
    ) -> "DLCrossEnvironmentReport":
        return cls(_load_seam_record(_REPORT_SCHEMA, source))

    @property
    def sha256(self) -> str:
        return self._record.sha256

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data


def build_cross_environment_report(
    receipts: Iterable[DLPortabilityTrialReceipt], comparison_policy: dict[str, Any]
) -> DLCrossEnvironmentReport:
    """Compare at least two exact R5 receipts without inferring independence."""

    items = list(receipts)
    if len(items) < 2 or any(
        not isinstance(item, DLPortabilityTrialReceipt) for item in items
    ):
        raise DLPortabilityReportError(
            "at least two DLPortabilityTrialReceipt values are required"
        )
    receipt_hashes = [item.sha256 for item in items]
    receipt_ids = [item.payload["receipt_id"] for item in items]
    if len(set(receipt_hashes)) != len(items) or len(set(receipt_ids)) != len(items):
        raise DLPortabilityReportError("duplicate portability receipts are forbidden")

    policy = _validate_policy(comparison_policy)
    first = items[0].payload
    repository = first["repository"]
    plan_sha256 = first["trial_plan_sha256"]
    for item in items[1:]:
        payload = item.payload
        if payload["repository"] != repository or payload["trial_plan_sha256"] != plan_sha256:
            raise DLPortabilityReportError(
                "all receipts must bind the same repository archive and trial plan"
            )
        if payload["same_host_reproducibility"]["expected_seeds"] != policy[
            "expected_seeds"
        ]:
            raise DLPortabilityReportError(
                "receipt seed plan does not match the comparison policy"
            )

    ordered = sorted(items, key=lambda item: item.sha256)
    environments = [item.payload["execution"] for item in ordered]
    environment_hashes = [canonical_sha256(value) for value in environments]
    environment_count = len(set(environment_hashes))
    variation = _environment_variation(environments)
    tolerance = policy["final_loss_absolute_tolerance"]

    per_seed: list[dict[str, Any]] = []
    for seed in policy["expected_seeds"]:
        rows = [
            next(
                row
                for row in item.payload["same_host_reproducibility"]["results"]
                if row["seed"] == seed
            )
            for item in ordered
        ]
        losses = [float(row["final_loss"]) for row in rows]
        delta = max(losses) - min(losses)
        per_seed.append(
            {
                "seed": seed,
                "stable_state_exact": len({row["stable_sha256"] for row in rows})
                == 1,
                "final_loss_absolute_delta": delta,
                "final_loss_within_tolerance": delta <= tolerance,
            }
        )

    interruption_rows = [item.payload["controlled_interruption"] for item in ordered]
    interruption_losses = [float(row["final_loss"]) for row in interruption_rows]
    interruption_delta = max(interruption_losses) - min(interruption_losses)
    interruption = {
        "model_state_exact": len(
            {row["model_state_sha256"] for row in interruption_rows}
        )
        == 1,
        "optimizer_state_exact": len(
            {row["optimizer_state_sha256"] for row in interruption_rows}
        )
        == 1,
        "scheduler_state_exact": len(
            {row["scheduler_state_sha256"] for row in interruption_rows}
        )
        == 1,
        "final_loss_absolute_delta": interruption_delta,
        "final_loss_within_tolerance": interruption_delta <= tolerance,
    }
    exact = all(row["stable_state_exact"] for row in per_seed) and all(
        interruption[field]
        for field in (
            "model_state_exact",
            "optimizer_state_exact",
            "scheduler_state_exact",
        )
    ) and all(row["final_loss_absolute_delta"] == 0 for row in per_seed) and interruption_delta == 0
    within_tolerance = all(
        row["final_loss_within_tolerance"] for row in per_seed
    ) and interruption["final_loss_within_tolerance"]
    verdict = (
        "single_environment_only"
        if environment_count == 1
        else "exact_match"
        if exact
        else "numerically_close_not_exact"
        if within_tolerance
        else "mismatch"
    )

    core = {
        "schema": _REPORT_SCHEMA,
        "observed_at": _utc_now(),
        "evidence_scope": "cross_environment_receipt_comparison_engineering_only",
        "trial_plan_sha256": plan_sha256,
        "repository": repository,
        "policy": policy,
        "source_receipts": [
            {
                "receipt_id": item.payload["receipt_id"],
                "receipt_sha256": item.sha256,
                "environment_sha256": canonical_sha256(item.payload["execution"]),
            }
            for item in ordered
        ],
        "environment_variation": variation,
        "per_seed": per_seed,
        "controlled_interruption": interruption,
        "summary": {
            "receipt_count": len(ordered),
            "environment_count": environment_count,
            "within_environment_gates_passed": True,
            "verdict": verdict,
        },
        "claims": {
            "independent_hosts_verified": False,
            "independent_participants_verified": False,
            "external_adoption_verified": False,
            "production_reliability_verified": False,
        },
        "limitations": list(_LIMITATIONS),
    }
    report_id = f"dl-cross-environment-report-{canonical_sha256(core)[:16]}"
    return DLCrossEnvironmentReport.from_payload({"report_id": report_id, **core})


def _validate_policy(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict) or set(source) != {
        "policy_id",
        "expected_seeds",
        "final_loss_absolute_tolerance",
    }:
        raise DLPortabilityReportError("comparison policy fields are invalid")
    if source["policy_id"] != _POLICY_ID or source["expected_seeds"] != [7, 11, 13]:
        raise DLPortabilityReportError("comparison policy identity or seed plan is invalid")
    tolerance = source["final_loss_absolute_tolerance"]
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not math.isfinite(float(tolerance))
        or float(tolerance) < 0
    ):
        raise DLPortabilityReportError(
            "final_loss_absolute_tolerance must be finite and nonnegative"
        )
    return {
        "policy_id": _POLICY_ID,
        "expected_seeds": [7, 11, 13],
        "final_loss_absolute_tolerance": float(tolerance),
    }


def _environment_variation(environments: list[dict[str, Any]]) -> list[str]:
    projections = {
        "os": [row["os"] for row in environments],
        "architecture": [row["architecture"] for row in environments],
        "python_version": [row["python_version"] for row in environments],
        "framework_version": [row["framework_version"] for row in environments],
        "cuda_version": [row["cuda_version"] for row in environments],
        "driver_version": [row["driver"]["version"] for row in environments],
        "device_model": [row["device"]["model"] for row in environments],
        "compute_capability": [
            row["device"]["compute_capability"] for row in environments
        ],
    }
    return sorted(name for name, values in projections.items() if len(set(values)) > 1)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "DLCrossEnvironmentReport",
    "DLPortabilityReportError",
    "build_cross_environment_report",
]
