"""Deterministic Phase 6 L4 reports over synthetic DL fixture evidence.

One in-process interface consumes L3 selection artifacts together with the
exact runner results they selected from.  It preserves failed/missing seeds,
checks the observable frozen axes, and refuses a comparison when the declared
resource envelope is not matched.  The module never executes training, opens
checkpoint payloads, probes hardware, reads a clock, or touches the filesystem.

The resulting report is synthetic engineering evidence.  Even an eligible
compute-matched report is descriptive: it is not a confidence interval, a
causal estimate, a framework/GPU observation, or a model-capability claim.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from research_evolution.core import (
    CoreError,
    canonical_bytes,
    canonical_sha256,
    load_strict_json,
)

from .manifest import DLRunManifest
from .runner import DLRunResult
from .selection import DLSelectionResult

REPORTER_NAME = "reference-dl-study-reporter"
REPORTER_VERSION = "0.1.0"

_PLAN_SCHEMA = "synthetic-dl-study-plan/v1"
_REPORT_SCHEMA = "synthetic-dl-study-report/v1"
_SELECTION_SCHEMA = "synthetic-dl-selection-result/v1"
_RUN_SCHEMA = "synthetic-dl-run-result/v2"
_PLAN_FIELDS = frozenset(
    {
        "schema",
        "report_id",
        "comparison_kind",
        "declared_factor",
        "matching_dimension",
        "arms",
    }
)
_ARM_FIELDS = frozenset({"arm_id", "role", "selection_id"})
_KINDS = frozenset({"ablation", "scale", "compute_matched"})
_FACTORS = {
    "ablation": "early_stopping",
    "scale": "hidden_units",
    "compute_matched": "hidden_units",
}
_MATCHING_DIMENSIONS = {
    "ablation": "all_consumed_dimensions",
    "scale": "none",
    "compute_matched": "flops_proxy",
}
_CONSUMPTION_FIELDS = (
    "samples",
    "steps",
    "epochs",
    "tokens",
    "flops_proxy",
)
_COMPUTE_MATCH_FIELDS = ("samples", "tokens", "flops_proxy")
class DLStudyError(Exception):
    """Malformed or cross-bound study evidence."""


@dataclass(frozen=True)
class DLStudyArmEvidence:
    """One selection artifact and its exact observed execution inputs/results."""

    selection: DLSelectionResult
    runs: tuple[DLRunResult, ...]
    manifests: tuple[DLRunManifest, ...]
    fixtures: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class DLStudyReport:
    """Immutable canonical L4 study report."""

    _artifact_bytes: bytes

    @property
    def artifact(self) -> dict[str, Any]:
        return load_strict_json(self._artifact_bytes)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self._artifact_bytes).hexdigest()

    @property
    def status(self) -> str:
        return self.artifact["comparison"]["status"]


def reporter_identity() -> dict[str, str]:
    return {"name": REPORTER_NAME, "version": REPORTER_VERSION}


def build_fixture_study_report(
    plan_payload: dict[str, Any],
    evidence_by_arm: Mapping[str, DLStudyArmEvidence],
) -> DLStudyReport:
    """Build one hash-bound ablation, scale, or compute-matched report.

    Structural contradictions raise :class:`DLStudyError`.  Incomplete seeds
    and resource mismatches are expected study outcomes and remain explicit in
    the returned artifact; they never disappear behind a best checkpoint.
    """
    plan = _validate_plan(plan_payload)
    evidence = _validate_evidence_mapping(evidence_by_arm, plan)
    arms = [
        _summarize_arm(arm_plan, evidence[arm_plan["arm_id"]])
        for arm_plan in plan["arms"]
    ]
    baseline = next(arm for arm in arms if arm["role"] == "baseline")
    candidate = next(arm for arm in arms if arm["role"] == "candidate")
    _validate_frozen_axes(plan, baseline, candidate)
    comparison = _compare(plan, baseline, candidate)

    failures = [
        {"arm_id": arm["arm_id"], **failure}
        for arm in arms
        for failure in arm["failures"]
    ]
    arm_artifacts = [_public_arm(arm) for arm in arms]
    core = {
        "schema": _REPORT_SCHEMA,
        "report_id": plan["report_id"],
        "study_plan_sha256": canonical_sha256(plan["payload"]),
        "reporter": reporter_identity(),
        "comparison_kind": plan["comparison_kind"],
        "declared_factor": plan["declared_factor"],
        "matching_dimension": plan["matching_dimension"],
        "evidence_scope": "synthetic_engineering",
        "arms": arm_artifacts,
        "comparison": comparison,
        "failure_inventory": failures,
        "hardware_framework_observation": {
            "hardware": "declared_not_observed",
            "framework": "not_loaded",
            "gpu_execution": "not_performed",
        },
        "artifact_retention": {
            "report_contains": "locator_hash_and_lineage_only",
            "checkpoint_payloads": "not_read_or_persisted",
        },
        "limitations": [
            "All inputs are deterministic synthetic CPU fixture artifacts.",
            "Observed ranges are descriptive and are not confidence intervals.",
            "A selected checkpoint does not establish multi-seed stability.",
            "No causal or model-capability claim is allowed by this report.",
            "No framework, GPU, real dataset, wall-clock cost, or external "
            "checkpoint store was observed.",
        ],
    }
    return DLStudyReport(canonical_bytes(core))


def _validate_plan(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DLStudyError("plan_payload must be an object")
    try:
        snapshot = load_strict_json(canonical_bytes(payload))
    except CoreError as exc:
        raise DLStudyError(f"plan_payload is not strict JSON: {exc}") from exc
    if set(snapshot) != _PLAN_FIELDS:
        raise DLStudyError(f"study plan fields must be exactly {sorted(_PLAN_FIELDS)}")
    if snapshot["schema"] != _PLAN_SCHEMA:
        raise DLStudyError(f"study plan schema must be {_PLAN_SCHEMA}")
    _token(snapshot["report_id"], "study.report_id")
    kind = snapshot["comparison_kind"]
    if kind not in _KINDS:
        raise DLStudyError(f"comparison_kind must be one of {sorted(_KINDS)}")
    if snapshot["declared_factor"] != _FACTORS[kind]:
        raise DLStudyError(
            f"{kind} requires declared_factor {_FACTORS[kind]!r}"
        )
    if snapshot["matching_dimension"] != _MATCHING_DIMENSIONS[kind]:
        raise DLStudyError(
            f"{kind} requires matching_dimension "
            f"{_MATCHING_DIMENSIONS[kind]!r}"
        )

    arms = snapshot["arms"]
    if not isinstance(arms, list) or len(arms) != 2:
        raise DLStudyError("study plan requires exactly two arms")
    seen_ids: set[str] = set()
    seen_roles: set[str] = set()
    seen_selections: set[str] = set()
    for index, arm in enumerate(arms):
        if not isinstance(arm, dict) or set(arm) != _ARM_FIELDS:
            raise DLStudyError(
                f"arms[{index}] fields must be exactly {sorted(_ARM_FIELDS)}"
            )
        arm_id = _token(arm["arm_id"], f"arms[{index}].arm_id")
        selection_id = _token(
            arm["selection_id"], f"arms[{index}].selection_id"
        )
        role = arm["role"]
        if role not in {"baseline", "candidate"}:
            raise DLStudyError("arm role must be baseline or candidate")
        if arm_id in seen_ids or role in seen_roles or selection_id in seen_selections:
            raise DLStudyError("arm ids, roles, and selection ids must be unique")
        seen_ids.add(arm_id)
        seen_roles.add(role)
        seen_selections.add(selection_id)
    if seen_roles != {"baseline", "candidate"}:
        raise DLStudyError("study plan requires baseline and candidate roles")
    return {**snapshot, "payload": snapshot}


def _validate_evidence_mapping(
    value: Any, plan: dict[str, Any]
) -> dict[str, DLStudyArmEvidence]:
    if not isinstance(value, Mapping):
        raise DLStudyError("evidence_by_arm must be a mapping")
    expected = {arm["arm_id"] for arm in plan["arms"]}
    if set(value) != expected:
        raise DLStudyError("evidence_by_arm keys must exactly match planned arm ids")
    evidence: dict[str, DLStudyArmEvidence] = {}
    for arm_id in expected:
        item = value[arm_id]
        if not isinstance(item, DLStudyArmEvidence):
            raise DLStudyError("each arm must be DLStudyArmEvidence")
        if not isinstance(item.selection, DLSelectionResult):
            raise DLStudyError("arm selection must be DLSelectionResult")
        if not isinstance(item.runs, tuple) or not all(
            isinstance(run, DLRunResult) for run in item.runs
        ):
            raise DLStudyError("arm runs must be a tuple of DLRunResult")
        if not isinstance(item.manifests, tuple) or not all(
            isinstance(manifest, DLRunManifest) for manifest in item.manifests
        ):
            raise DLStudyError("arm manifests must be a tuple of DLRunManifest")
        if not isinstance(item.fixtures, tuple) or not all(
            isinstance(fixture, dict) for fixture in item.fixtures
        ):
            raise DLStudyError("arm fixtures must be a tuple of objects")
        if not (
            len(item.runs) == len(item.manifests) == len(item.fixtures)
        ):
            raise DLStudyError("arm runs, manifests, and fixtures must have equal length")
        evidence[arm_id] = item
    return evidence


def _summarize_arm(
    arm_plan: dict[str, Any], evidence: DLStudyArmEvidence
) -> dict[str, Any]:
    selection = evidence.selection.artifact
    if selection.get("schema") != _SELECTION_SCHEMA:
        raise DLStudyError("study reporter requires selector 0.1 artifacts")
    if selection["selection_id"] != arm_plan["selection_id"]:
        raise DLStudyError("selection_id does not match the study plan")
    if selection["evidence_scope"] != "synthetic_engineering":
        raise DLStudyError("selection evidence scope is not synthetic_engineering")

    observed: dict[
        str, tuple[DLRunResult, dict[str, Any], dict[str, Any], dict[str, Any]]
    ] = {}
    for result, manifest, fixture_payload in zip(
        evidence.runs, evidence.manifests, evidence.fixtures, strict=True
    ):
        artifact = result.artifact
        if artifact.get("schema") != _RUN_SCHEMA:
            raise DLStudyError("study reporter requires runner 0.2 artifacts")
        run_id = artifact["run_id"]
        if run_id in observed:
            raise DLStudyError("duplicate run result in study arm")
        if artifact["study_id"] != selection["study_id"]:
            raise DLStudyError("run study_id does not match selection")
        if artifact["case_sha256"] != selection["case_sha256"]:
            raise DLStudyError("run case_sha256 does not match selection")
        if artifact["evidence_scope"] != "synthetic_engineering":
            raise DLStudyError("study comparisons require executed synthetic fixtures")
        if artifact["execution"] != {
            "mode": "cpu_fixture",
            "observation": "synthetic_cpu_fixture",
            "hardware": "declared_not_observed",
            "framework": "not_loaded",
        }:
            raise DLStudyError("run execution envelope is outside L4 synthetic CPU scope")
        manifest_payload = manifest.payload
        if manifest_payload["run_id"] != run_id:
            raise DLStudyError("manifest run_id does not match supplied run")
        if manifest.sha256 != artifact["manifest_sha256"]:
            raise DLStudyError("manifest hash does not match supplied run")
        if manifest_payload["study_id"] != selection["study_id"]:
            raise DLStudyError("manifest study_id does not match selection")
        if manifest_payload["case_sha256"] != selection["case_sha256"]:
            raise DLStudyError("manifest case_sha256 does not match selection")
        if manifest_payload["execution_mode"] != "cpu_fixture":
            raise DLStudyError("study comparisons require cpu_fixture manifests")
        if manifest.resume_mode != "fresh":
            raise DLStudyError("study comparisons require fresh-run manifests")
        try:
            fixture = load_strict_json(canonical_bytes(fixture_payload))
        except CoreError as exc:
            raise DLStudyError(f"fixture is not strict JSON: {exc}") from exc
        if canonical_sha256(fixture) != artifact["fixture"]["content_sha256"]:
            raise DLStudyError("fixture hash does not match supplied run")
        if fixture.get("schema") != "synthetic-dl-fixture/v2":
            raise DLStudyError("study comparisons require fixture v2")
        if fixture.get("seed") != artifact["fixture"]["seed"]:
            raise DLStudyError("fixture seed does not match supplied run")
        if manifest_payload["budget"] != artifact["budget_ledger"]["limits"]:
            raise DLStudyError("manifest budget does not match supplied run")
        observed[run_id] = (result, artifact, manifest_payload, fixture)

    selection_rows = {row["run_id"]: row for row in selection["runs"]}
    observed_rows = {
        run_id for run_id, row in selection_rows.items() if row["status"] != "missing"
    }
    if set(observed) != observed_rows:
        raise DLStudyError("run results do not exactly match selection observations")
    for run_id, (result, artifact, _manifest, _fixture) in observed.items():
        row = selection_rows[run_id]
        if row["result_sha256"] != result.sha256:
            raise DLStudyError("selection result hash does not match supplied run")
        if row["seed"] != artifact["fixture"]["seed"]:
            raise DLStudyError("selection seed does not match supplied run")

    profiles = [
        _run_profile(item[1], item[2], item[3]) for item in observed.values()
    ]
    if not profiles:
        raise DLStudyError("study arm must contain at least one observed run")
    common_profile = profiles[0]
    for profile in profiles[1:]:
        if profile != common_profile:
            raise DLStudyError("runs within one arm do not share a comparison profile")

    successful_runs = [
        observed[row["run_id"]][1]
        for row in selection["runs"]
        if row["eligible"]
    ]
    consumed_by_seed = [
        {
            "seed": artifact["fixture"]["seed"],
            "consumed": artifact["budget_ledger"]["consumed"],
        }
        for artifact in successful_runs
    ]
    failures = [
        {
            "run_id": row["run_id"],
            "seed": row["seed"],
            "status": row["status"],
            "failure_class": row["failure_class"],
            "ineligibility_reason": row["ineligibility_reason"],
        }
        for row in selection["runs"]
        if not row["eligible"]
    ]
    counts = selection["counts"]
    complete = (
        selection["status"] == "completed"
        and counts["successful"] == counts["expected"]
        and counts["failed"] == 0
        and counts["missing"] == 0
    )
    return {
        "arm_id": arm_plan["arm_id"],
        "role": arm_plan["role"],
        "selection_id": selection["selection_id"],
        "selection_result_sha256": evidence.selection.sha256,
        "study_id": selection["study_id"],
        "case_sha256": selection["case_sha256"],
        "runner": common_profile["runner"],
        "expected_seeds": [row["seed"] for row in selection["runs"]],
        "counts": counts,
        "complete_for_comparison": complete,
        "aggregate": selection["aggregate"],
        "selected_checkpoint": selection["selected_checkpoint"],
        "profile": common_profile,
        "consumed_by_seed": consumed_by_seed,
        "failures": failures,
    }


def _run_profile(
    artifact: dict[str, Any],
    manifest: dict[str, Any],
    fixture_payload: dict[str, Any],
) -> dict[str, Any]:
    fixture = artifact["fixture"]
    data_identity = {
        "features": fixture_payload["features"],
        "targets": fixture_payload["targets"],
        "validation_features": fixture_payload["validation_features"],
        "validation_targets": fixture_payload["validation_targets"],
    }
    return {
        "runner": artifact["runner"],
        "fixture_id": fixture["fixture_id"],
        "data_sha256": canonical_sha256(data_identity),
        "training_rows": fixture["training_rows"],
        "validation_rows": fixture["validation_rows"],
        "feature_count": fixture["feature_count"],
        "hidden_units": fixture["hidden_units"],
        "learning_rate": fixture_payload["learning_rate"],
        "requested_steps": fixture["requested_steps"],
        "early_stopping": artifact["early_stopping"]["policy"],
        "budget_limits": artifact["budget_ledger"]["limits"],
        "accounting": artifact["budget_ledger"]["accounting"],
        "execution_mode": manifest["execution_mode"],
        "hardware_declaration": manifest["hardware"],
        "runtime_declaration": manifest["runtime"],
        "framework_declaration": manifest["framework"],
        "container_declaration": manifest["container"],
        "optimizer_declaration": manifest["optimizer"],
        "scheduler_declaration": manifest["scheduler"],
        "checkpoint_policy": manifest["checkpoint_policy"],
    }


def _validate_frozen_axes(
    plan: dict[str, Any], baseline: dict[str, Any], candidate: dict[str, Any]
) -> None:
    for field in ("case_sha256", "runner", "expected_seeds"):
        if baseline[field] != candidate[field]:
            raise DLStudyError(f"comparison frozen axis {field} differs between arms")
    shared_profile_fields = (
        "fixture_id",
        "data_sha256",
        "training_rows",
        "validation_rows",
        "feature_count",
        "learning_rate",
        "budget_limits",
        "accounting",
        "execution_mode",
        "hardware_declaration",
        "runtime_declaration",
        "framework_declaration",
        "container_declaration",
        "optimizer_declaration",
        "scheduler_declaration",
        "checkpoint_policy",
    )
    for field in shared_profile_fields:
        if baseline["profile"][field] != candidate["profile"][field]:
            raise DLStudyError(f"comparison frozen axis {field} differs between arms")

    kind = plan["comparison_kind"]
    baseline_profile = baseline["profile"]
    candidate_profile = candidate["profile"]
    if kind == "ablation":
        if baseline_profile["early_stopping"] == candidate_profile["early_stopping"]:
            raise DLStudyError("ablation arms must differ on early_stopping")
        for field in ("hidden_units", "requested_steps"):
            if baseline_profile[field] != candidate_profile[field]:
                raise DLStudyError(
                    f"ablation changed undeclared axis {field}"
                )
    else:
        if baseline_profile["hidden_units"] == candidate_profile["hidden_units"]:
            raise DLStudyError(f"{kind} arms must differ on hidden_units")
        if baseline_profile["early_stopping"] != candidate_profile["early_stopping"]:
            raise DLStudyError(f"{kind} changed undeclared early_stopping axis")
        if kind == "scale":
            for field in ("requested_steps",):
                if baseline_profile[field] != candidate_profile[field]:
                    raise DLStudyError(f"scale changed undeclared axis {field}")


def _compare(
    plan: dict[str, Any], baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    complete = baseline["complete_for_comparison"] and candidate[
        "complete_for_comparison"
    ]
    kind = plan["comparison_kind"]
    if not complete:
        status = "incomplete_evidence"
        resource_parity = False
        comparison_allowed = False
        mismatch_fields = ["failed_or_missing_expected_runs"]
    else:
        baseline_by_seed = {
            entry["seed"]: entry["consumed"]
            for entry in baseline["consumed_by_seed"]
        }
        candidate_by_seed = {
            entry["seed"]: entry["consumed"]
            for entry in candidate["consumed_by_seed"]
        }
        if kind == "ablation":
            fields = _CONSUMPTION_FIELDS
        else:
            fields = _COMPUTE_MATCH_FIELDS
        cap_fields = tuple(baseline["profile"]["budget_limits"])
        mismatch_fields = _resource_mismatches(
            baseline_by_seed,
            candidate_by_seed,
            baseline["profile"]["budget_limits"],
            candidate["profile"]["budget_limits"],
            fields,
            cap_fields,
        )
        resource_parity = not mismatch_fields
        if kind == "scale":
            status = "descriptive_scale_only"
            comparison_allowed = False
        elif resource_parity:
            status = "eligible_descriptive_comparison"
            comparison_allowed = True
        else:
            status = "descriptive_only_resource_mismatch"
            comparison_allowed = False

    mean_difference = None
    if (
        comparison_allowed
        and baseline["aggregate"] is not None
        and candidate["aggregate"] is not None
    ):
        mean_difference = round(
            candidate["aggregate"]["mean"] - baseline["aggregate"]["mean"],
            12,
        )
        if mean_difference == 0.0:
            mean_difference = 0.0
    return {
        "status": status,
        "comparison_allowed": comparison_allowed,
        "capability_claim_allowed": False,
        "resource_parity": resource_parity,
        "resource_mismatch_fields": mismatch_fields,
        "metric": "validation_loss",
        "direction": "minimize",
        "candidate_minus_baseline_mean": mean_difference,
        "interval_kind": "observed_range_not_confidence_interval",
        "interpretation": (
            "Descriptive synthetic engineering comparison only; no causal, "
            "stability, framework, GPU, or capability conclusion."
        ),
    }


def _resource_mismatches(
    baseline_by_seed: dict[int, dict[str, Any]],
    candidate_by_seed: dict[int, dict[str, Any]],
    baseline_limits: dict[str, Any],
    candidate_limits: dict[str, Any],
    consumed_fields: Sequence[str],
    cap_fields: Sequence[str],
) -> list[str]:
    mismatches: list[str] = []
    if set(baseline_by_seed) != set(candidate_by_seed):
        mismatches.append("successful_seed_set")
        return mismatches
    for field in cap_fields:
        if baseline_limits[field] != candidate_limits[field]:
            mismatches.append(f"budget_limits.{field}")
    for seed in sorted(baseline_by_seed):
        for field in consumed_fields:
            if baseline_by_seed[seed][field] != candidate_by_seed[seed][field]:
                mismatches.append(f"seed[{seed}].consumed.{field}")
    return mismatches


def _public_arm(arm: dict[str, Any]) -> dict[str, Any]:
    return {
        "arm_id": arm["arm_id"],
        "role": arm["role"],
        "selection_id": arm["selection_id"],
        "selection_result_sha256": arm["selection_result_sha256"],
        "study_id": arm["study_id"],
        "case_sha256": arm["case_sha256"],
        "runner": arm["runner"],
        "expected_seeds": arm["expected_seeds"],
        "counts": arm["counts"],
        "complete_for_comparison": arm["complete_for_comparison"],
        "aggregate": arm["aggregate"],
        "selected_checkpoint": arm["selected_checkpoint"],
        "comparison_profile": arm["profile"],
        "consumed_by_seed": arm["consumed_by_seed"],
    }


def _token(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise DLStudyError(f"{path} must be a non-whitespace token")
    return value


__all__ = [
    "DLStudyArmEvidence",
    "DLStudyError",
    "DLStudyReport",
    "build_fixture_study_report",
    "reporter_identity",
]
