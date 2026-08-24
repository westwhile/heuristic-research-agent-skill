"""Bounded same-host PyTorch/CUDA reproducibility reporting.

The public interface accepts exactly three preregistered manifests and their
synthetic fixtures.  Each seed is executed twice in a fresh Python process via
the published R1 observation runner.  Timing and memory observations remain in
the child receipts but are excluded from the stable comparison projection.

This is one concrete PyTorch deep module, not a generic framework seam.  It
establishes only same-host, primary-device engineering reproducibility.  Failed
seeds remain explicit and at least two reproduced seeds are required to issue
a report.
"""

from __future__ import annotations

import hashlib
import os
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from research_evolution.core import (
    CoreError,
    Record,
    canonical_bytes,
    canonical_sha256,
    load_strict_json,
)

from ..types import AdapterError, _load_seam_record
from .manifest import DLRunManifest
from .pytorch_observation import (
    DLObservedRun,
    pytorch_observation_identity,
    run_pytorch_gpu_fixture,
)

_REPORT_SCHEMA = "dl-same-host-reproducibility-report/v1"
_RUNNER_NAME = "pytorch-same-host-reproducibility-runner"
_RUNNER_VERSION = "0.1.0"
_FIXTURE_SCHEMA = "pytorch-dl-fixture/v1"
_REPETITIONS = ("a", "b")
_LIMITATIONS = (
    "Exactly three bounded synthetic seeds and two repetitions per seed.",
    "One real PyTorch/CUDA host and its primary device only.",
    "Timing and peak memory are observed but excluded from exact repeat matching.",
    "No real dataset or cross-GPU/cross-host portability was tested.",
    "Driver version is reported only when nvidia-smi is available and parseable.",
    "No scientific, predictive, strategy, production, or adoption claim is supported.",
)


class DLPytorchReproducibilityError(AdapterError):
    """A same-host report could not be honestly established."""


def _semantic_violations(payload: dict[str, Any]) -> tuple[str, ...]:
    violations: list[str] = []
    expected = payload["expected_seeds"]
    results = payload["results"]
    result_seeds = [row["seed"] for row in results]
    if len(expected) != len(set(expected)) or expected != sorted(expected):
        violations.append(
            "reproducibility-expected-seeds: expected seeds must be unique and sorted"
        )
    if any(seed < 0 for seed in expected):
        violations.append(
            "reproducibility-expected-seeds: expected seeds must be nonnegative"
        )
    if result_seeds != expected:
        violations.append(
            "reproducibility-result-coverage: results must cover expected seeds in order"
        )

    successful: list[int] = []
    failed: list[int] = []
    final_losses: list[float] = []
    for row in results:
        repeats = (row["repeat_a"], row["repeat_b"])
        for repeat in repeats:
            required = {"observation_sha256", "stable_sha256", "final_loss"}
            if repeat["status"] == "completed":
                if repeat["failure_class"] != "none" or not required.issubset(repeat):
                    violations.append(
                        "reproducibility-repeat-shape: completed repeats require no failure and all result fields"
                    )
            elif repeat["failure_class"] == "none" or "final_loss" in repeat:
                violations.append(
                    "reproducibility-repeat-shape: failed repeats require a failure and no final loss"
                )
        if row["status"] == "reproduced":
            successful.append(row["seed"])
            if row["failure_classes"]:
                violations.append(
                    "reproducibility-success-failure-empty: reproduced seeds cannot carry failures"
                )
            for repeat in repeats:
                if repeat["status"] != "completed" or repeat["failure_class"] != "none":
                    violations.append(
                        "reproducibility-success-repeat: reproduced seeds require two completed repeats"
                    )
                if not required.issubset(repeat):
                    violations.append(
                        "reproducibility-success-fields: completed repeats require hashes and final loss"
                    )
            if all(required.issubset(repeat) for repeat in repeats):
                if repeats[0]["stable_sha256"] != repeats[1]["stable_sha256"]:
                    violations.append(
                        "reproducibility-stable-match: reproduced repeat hashes must match"
                    )
                if repeats[0]["final_loss"] != repeats[1]["final_loss"]:
                    violations.append(
                        "reproducibility-loss-match: reproduced final losses must match"
                    )
                final_losses.append(float(repeats[0]["final_loss"]))
        else:
            failed.append(row["seed"])
            if not row["failure_classes"]:
                violations.append(
                    "reproducibility-failed-explicit: failed seeds require failure classes"
                )

    summary = payload["summary"]
    if summary["successful_seeds"] != successful:
        violations.append(
            "reproducibility-summary-success: successful seed list must match results"
        )
    if summary["failed_seeds"] != failed:
        violations.append(
            "reproducibility-summary-failure: failed seed list must match results"
        )
    if summary["exact_repeat_matches"] != len(successful):
        violations.append(
            "reproducibility-summary-matches: exact match count must equal reproduced seeds"
        )
    stats = summary["final_loss"]
    if final_losses:
        expected_stats = _statistics(final_losses)
        if canonical_bytes(stats) != canonical_bytes(expected_stats):
            violations.append(
                "reproducibility-summary-statistics: final_loss is inconsistent"
            )

    driver = payload["driver_observation"]
    if (driver["status"] == "observed") == (driver["version"] == "unavailable"):
        violations.append(
            "reproducibility-driver-status: observed requires a version and unavailable forbids one"
        )
    return tuple(violations)


@dataclass(frozen=True)
class DLSameHostReproducibilityReport:
    """Immutable, schema- and semantics-validated same-host report."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _REPORT_SCHEMA:
            raise AdapterError(
                f"DLSameHostReproducibilityReport wraps {_REPORT_SCHEMA} payloads, "
                f"got {self._record.schema_id!r}"
            )
        violations = _semantic_violations(self._record.data)
        if violations:
            raise AdapterError(
                f"invalid {_REPORT_SCHEMA} semantics: {len(violations)} violation(s)",
                details=violations,
            )

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any]
    ) -> "DLSameHostReproducibilityReport":
        return cls(_load_seam_record(_REPORT_SCHEMA, payload))

    @classmethod
    def from_json(
        cls, source: "str | bytes | bytearray"
    ) -> "DLSameHostReproducibilityReport":
        return cls(_load_seam_record(_REPORT_SCHEMA, source))

    @property
    def sha256(self) -> str:
        return self._record.sha256

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def plan_sha256(self) -> str:
        return self._record.data["plan_sha256"]


def pytorch_reproducibility_identity() -> dict[str, str]:
    """Return orchestrator identity bound to exact module bytes."""
    try:
        source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:
        raise DLPytorchReproducibilityError(
            "cannot hash the PyTorch reproducibility runner source"
        ) from exc
    return {
        "name": _RUNNER_NAME,
        "version": _RUNNER_VERSION,
        "source_sha256": source_sha256,
    }


def run_pytorch_same_host_reproducibility(
    manifests: Sequence[DLRunManifest],
    fixtures: Sequence[dict[str, Any]],
    scratch_root: str | os.PathLike[str],
) -> DLSameHostReproducibilityReport:
    """Execute three seeds twice each in fresh PyTorch/CUDA processes."""
    plan = _validate_plan(manifests, fixtures)
    root = _validate_scratch_root(scratch_root)
    results: list[dict[str, Any]] = []
    execution: dict[str, Any] | None = None

    for entry in plan["entries"]:
        repeats: list[dict[str, Any]] = []
        for repeat in _REPETITIONS:
            repeats.append(
                _attempt_repeat(
                    root,
                    entry["seed"],
                    repeat,
                    entry["manifest"],
                    entry["fixture"],
                )
            )
        for repeat in repeats:
            observed_execution = repeat.pop("_execution", None)
            if observed_execution is not None:
                if execution is None:
                    execution = observed_execution
                elif execution != observed_execution:
                    raise DLPytorchReproducibilityError(
                        "repeat execution environments do not match"
                    )
        results.append(_build_seed_result(entry["seed"], repeats[0], repeats[1]))

    successful = [row["seed"] for row in results if row["status"] == "reproduced"]
    failed = [row["seed"] for row in results if row["status"] == "failed"]
    if execution is None or len(successful) < 2:
        raise DLPytorchReproducibilityError(
            "fewer than two seeds reproduced; no same-host report was issued"
        )
    losses = [
        float(row["repeat_a"]["final_loss"])
        for row in results
        if row["status"] == "reproduced"
    ]
    runner = {
        **pytorch_reproducibility_identity(),
        "observation_runner": pytorch_observation_identity(),
    }
    core = {
        "schema": _REPORT_SCHEMA,
        "plan_sha256": plan["sha256"],
        "observed_at": _utc_now(),
        "evidence_scope": "real_framework_hardware_same_host_reproducibility_engineering",
        "runner": runner,
        "execution": execution,
        "driver_observation": _observe_driver(),
        "repetitions_per_seed": 2,
        "expected_seeds": plan["seeds"],
        "results": results,
        "summary": {
            "successful_seeds": successful,
            "failed_seeds": failed,
            "exact_repeat_matches": len(successful),
            "final_loss": _statistics(losses),
        },
        "limitations": list(_LIMITATIONS),
    }
    report_id = f"dl-same-host-{canonical_sha256(core)[:16]}"
    return DLSameHostReproducibilityReport.from_payload(
        {"report_id": report_id, **core}
    )


def _validate_plan(
    manifests: Sequence[DLRunManifest], fixtures: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    if (
        not isinstance(manifests, Sequence)
        or isinstance(manifests, (str, bytes))
        or not isinstance(fixtures, Sequence)
        or isinstance(fixtures, (str, bytes))
    ):
        raise DLPytorchReproducibilityError("manifests and fixtures must be sequences")
    if len(manifests) != 3 or len(fixtures) != 3:
        raise DLPytorchReproducibilityError(
            "exactly three manifests and fixtures are required"
        )
    entries: list[dict[str, Any]] = []
    frozen_manifests: list[dict[str, Any]] = []
    frozen_fixtures: list[dict[str, Any]] = []
    for index, (manifest, fixture_source) in enumerate(zip(manifests, fixtures)):
        if not isinstance(manifest, DLRunManifest):
            raise DLPytorchReproducibilityError(
                f"manifests[{index}] must be a DLRunManifest"
            )
        if manifest.payload["runner"] != pytorch_observation_identity():
            raise DLPytorchReproducibilityError(
                "every manifest must bind the exact R1 observation runner"
            )
        if not isinstance(fixture_source, dict):
            raise DLPytorchReproducibilityError(
                f"fixtures[{index}] must be an object"
            )
        try:
            fixture = load_strict_json(canonical_bytes(fixture_source))
        except CoreError as exc:
            raise DLPytorchReproducibilityError(
                f"fixtures[{index}] is not strict JSON"
            ) from exc
        if fixture.get("schema") != _FIXTURE_SCHEMA:
            raise DLPytorchReproducibilityError(
                f"fixtures[{index}].schema must be {_FIXTURE_SCHEMA}"
            )
        seed = fixture.get("seed")
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            raise DLPytorchReproducibilityError(
                f"fixtures[{index}].seed must be a nonnegative integer"
            )
        if fixture.get("case_sha256") != manifest.payload["case_sha256"]:
            raise DLPytorchReproducibilityError(
                f"fixtures[{index}] case does not match its manifest"
            )
        entries.append(
            {
                "seed": seed,
                "manifest": manifest.payload,
                "fixture": fixture,
                "manifest_sha256": manifest.sha256,
                "fixture_sha256": canonical_sha256(fixture),
            }
        )
        frozen_manifest = manifest.payload
        for field in ("manifest_id", "run_id", "created_at"):
            frozen_manifest.pop(field)
        frozen_manifests.append(frozen_manifest)
        frozen_fixture = dict(fixture)
        for field in ("fixture_id", "seed"):
            frozen_fixture.pop(field, None)
        frozen_fixtures.append(frozen_fixture)
    seeds = [entry["seed"] for entry in entries]
    if len(seeds) != len(set(seeds)) or seeds != sorted(seeds):
        raise DLPytorchReproducibilityError(
            "fixture seeds must be unique and supplied in sorted order"
        )
    if any(item != frozen_manifests[0] for item in frozen_manifests[1:]):
        raise DLPytorchReproducibilityError(
            "manifests differ on a frozen axis other than identity/time"
        )
    if any(item != frozen_fixtures[0] for item in frozen_fixtures[1:]):
        raise DLPytorchReproducibilityError(
            "fixtures differ on a frozen axis other than identity/seed"
        )
    plan_projection = [
        {
            "seed": entry["seed"],
            "manifest_sha256": entry["manifest_sha256"],
            "fixture_sha256": entry["fixture_sha256"],
        }
        for entry in entries
    ]
    return {
        "entries": entries,
        "seeds": seeds,
        "sha256": canonical_sha256(plan_projection),
    }


def _validate_scratch_root(source: str | os.PathLike[str]) -> Path:
    try:
        candidate = Path(source)
        if candidate.is_symlink():
            raise DLPytorchReproducibilityError(
                "scratch_root must be a non-symlink directory"
            )
        root = candidate.resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        raise DLPytorchReproducibilityError(
            "scratch_root must be an existing directory"
        ) from exc
    if not root.is_dir():
        raise DLPytorchReproducibilityError("scratch_root must be a directory")
    repository_root = Path(__file__).resolve().parents[4]
    if (repository_root / "pyproject.toml").is_file() and root.is_relative_to(
        repository_root
    ):
        raise DLPytorchReproducibilityError(
            "scratch_root must be outside the repository"
        )
    try:
        if any(root.iterdir()):
            raise DLPytorchReproducibilityError("scratch_root must be empty")
    except OSError as exc:
        raise DLPytorchReproducibilityError("scratch_root cannot be inspected") from exc
    return root


def _attempt_repeat(
    root: Path,
    seed: int,
    repeat: str,
    manifest: dict[str, Any],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    try:
        observation = _invoke_repeat(root, seed, repeat, manifest, fixture)
    except (DLPytorchReproducibilityError, AdapterError, OSError):
        return {"status": "failed", "failure_class": "process_error"}
    payload = observation.payload
    stable = {
        "status": payload["status"],
        "runner": payload["runner"],
        "fixture": payload["fixture"],
        "execution": payload["execution"],
        "metrics": payload["metrics"],
        "budget": {
            "declared": payload["budget_ledger"]["declared"],
            "consumed": {
                "samples": payload["budget_ledger"]["consumed"]["samples"],
                "steps": payload["budget_ledger"]["consumed"]["steps"],
                "accounting": payload["budget_ledger"]["consumed"]["accounting"],
            },
        },
        "checkpointing": payload["checkpointing"],
        "failure": payload["failure"],
        "limitations": payload["limitations"],
    }
    result = {
        "status": payload["status"],
        "failure_class": observation.failure_class,
        "observation_sha256": observation.sha256,
        "stable_sha256": canonical_sha256(stable),
        "_execution": payload["execution"],
    }
    if observation.status == "completed":
        metrics = {row["name"]: float(row["value"]) for row in payload["metrics"]}
        result["final_loss"] = metrics["final_loss"]
    return result


def _invoke_repeat(
    root: Path,
    seed: int,
    repeat: str,
    manifest: dict[str, Any],
    fixture: dict[str, Any],
) -> DLObservedRun:
    stem = f"seed-{seed}-{repeat}"
    request_path = root / f".{stem}-request.json"
    result_path = root / f".{stem}-result.json"
    request_path.write_bytes(
        canonical_bytes({"manifest": manifest, "fixture": fixture})
    )
    command = [
        sys.executable,
        "-B",
        "-m",
        __name__,
        "--worker",
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
            raise DLPytorchReproducibilityError(
                "reproducibility worker failed without a valid receipt"
            )
        result = load_strict_json(result_path.read_bytes())
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise DLPytorchReproducibilityError(
                "reproducibility worker failed without a valid receipt"
            )
        payload = result.get("payload")
        if not isinstance(payload, dict):
            raise DLPytorchReproducibilityError(
                "reproducibility worker returned an invalid receipt"
            )
        return DLObservedRun.from_payload(payload)
    except subprocess.TimeoutExpired as exc:
        raise DLPytorchReproducibilityError(
            "reproducibility worker timed out"
        ) from exc
    except (OSError, CoreError) as exc:
        raise DLPytorchReproducibilityError(
            "reproducibility worker receipt could not be read"
        ) from exc
    finally:
        for path in (request_path, result_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _build_seed_result(
    seed: int, repeat_a: dict[str, Any], repeat_b: dict[str, Any]
) -> dict[str, Any]:
    public_a = _public_repeat(repeat_a)
    public_b = _public_repeat(repeat_b)
    reproduced = (
        repeat_a["status"] == "completed"
        and repeat_b["status"] == "completed"
        and repeat_a.get("stable_sha256") == repeat_b.get("stable_sha256")
        and repeat_a.get("final_loss") == repeat_b.get("final_loss")
    )
    failures: list[str] = []
    if not reproduced:
        for repeat in (repeat_a, repeat_b):
            if repeat["status"] != "completed":
                failures.append(repeat["failure_class"])
        if not failures:
            failures.append("repeat_mismatch")
    return {
        "seed": seed,
        "status": "reproduced" if reproduced else "failed",
        "failure_classes": sorted(set(failures)),
        "repeat_a": public_a,
        "repeat_b": public_b,
    }


def _public_repeat(repeat: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in repeat.items() if not key.startswith("_")}


def _statistics(values: list[float]) -> dict[str, Any]:
    if not values:
        raise DLPytorchReproducibilityError("no successful final losses to summarize")
    return {
        "count": len(values),
        "mean": float(statistics.fmean(values)),
        "population_variance": float(statistics.pvariance(values)),
        "minimum": float(min(values)),
        "maximum": float(max(values)),
    }


def _observe_driver() -> dict[str, str]:
    command = [
        "nvidia-smi",
        "--query-gpu=driver_version",
        "--format=csv,noheader",
        "--id=0",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "source": "nvidia-smi", "version": "unavailable"}
    version = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if result.returncode != 0 or re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", version) is None:
        return {"status": "unavailable", "source": "nvidia-smi", "version": "unavailable"}
    return {"status": "observed", "source": "nvidia-smi", "version": version}


def _worker(request: dict[str, Any]) -> dict[str, Any]:
    manifest = DLRunManifest.from_payload(request["manifest"])
    observation = run_pytorch_gpu_fixture(manifest, request["fixture"])
    return observation.payload


def _worker_entry(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != "--worker":
        return 2
    _, request_name, result_name = argv
    result_path = Path(result_name)
    try:
        request = load_strict_json(Path(request_name).read_bytes())
        if not isinstance(request, dict) or set(request) != {"manifest", "fixture"}:
            raise DLPytorchReproducibilityError("worker request is invalid")
        result = {"ok": True, "payload": _worker(request)}
        exit_code = 0
    except Exception:
        result = {"ok": False, "error": "PyTorch reproducibility worker failed."}
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


__all__ = [
    "DLPytorchReproducibilityError",
    "DLSameHostReproducibilityReport",
    "pytorch_reproducibility_identity",
    "run_pytorch_same_host_reproducibility",
]


if __name__ == "__main__":
    raise SystemExit(_worker_entry(sys.argv[1:]))
