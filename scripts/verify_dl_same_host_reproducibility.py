"""Exact-archive gate for bounded same-host PyTorch/CUDA reproducibility.

Run this script only from an exported commit with the PyTorch-enabled
interpreter.  It binds caller-resolved Git commit/tree object IDs and archive
SHA-256 to exactly three preregistered synthetic seeds, each executed twice in
a fresh Python process.  Timing and peak memory remain observed in child
receipts but are excluded from exact repeat matching.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import tempfile
from pathlib import Path

from research_evolution.adapters.deep_learning.manifest import DLRunManifest
from research_evolution.adapters.deep_learning.pytorch_observation import (
    pytorch_observation_identity,
)
from research_evolution.adapters.deep_learning.pytorch_reproducibility import (
    run_pytorch_same_host_reproducibility,
)
from research_evolution.core import canonical_sha256, load_strict_json

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "adapters"
    / "dl-run-manifest"
    / "v1"
    / "valid"
    / "minimal.json"
)
SEEDS = (7, 11, 13)


def _hex_identifier(value: str, name: str, length: int) -> str:
    if len(value) != length or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ValueError(f"{name} must be {length} lowercase hexadecimal characters")
    return value


def _fixture(seed: int) -> dict:
    return {
        "schema": "pytorch-dl-fixture/v1",
        "fixture_id": f"exact-archive-cuda-reproducibility-{seed}",
        "case_sha256": canonical_sha256(
            {
                "case": "exact-archive-cuda-reproducibility",
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


def _runtime(torch) -> dict:
    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch CUDA is unavailable")
    properties = torch.cuda.get_device_properties(0)
    capability = torch.cuda.get_device_capability(0)
    return {
        "mode": "gpu_fixture",
        "os": platform.system().lower(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "framework": {
            "name": "pytorch",
            "version": torch.__version__,
            "backend": "cuda",
            "backend_version": torch.version.cuda,
            "determinism": "strict",
        },
        "hardware": {
            "device_model": properties.name,
            "device_count": torch.cuda.device_count(),
            "memory_bytes_per_device": properties.total_memory,
            "compute_capability": f"{capability[0]}.{capability[1]}",
        },
    }


def _manifest(runtime: dict, fixture: dict) -> DLRunManifest:
    seed = fixture["seed"]
    payload = load_strict_json(MANIFEST_FIXTURE.read_bytes())
    payload.update(
        {
            "manifest_id": f"exact-archive-cuda-repro-manifest-{seed}",
            "run_id": f"exact-archive-cuda-repro-run-{seed}",
            "study_id": "exact-archive-cuda-repro-study-001",
            "case_sha256": fixture["case_sha256"],
            "execution_mode": "gpu_fixture",
            "runner": pytorch_observation_identity(),
            "hardware": {
                "accelerator": "cuda",
                "device_model": runtime["hardware"]["device_model"],
                "device_count": runtime["hardware"]["device_count"],
                "memory_bytes_per_device": runtime["hardware"]
                ["memory_bytes_per_device"],
            },
            "runtime": {
                "os": runtime["os"],
                "architecture": runtime["architecture"],
                "python_version": runtime["python_version"],
            },
            "framework": {
                "name": "pytorch",
                "version": runtime["framework"]["version"],
                "backend_version": runtime["framework"]["backend_version"],
                "determinism": "strict",
            },
            "container": {"kind": "none"},
            "budget": {
                "max_samples": fixture["samples"],
                "max_steps": fixture["requested_steps"],
                "max_epochs": 0,
                "max_tokens": 0,
                "max_flops": 0,
                "cost_limit": 60,
                "cost_unit": "accelerator_seconds",
            },
            "optimizer": {
                "name": "sgd",
                "config_sha256": canonical_sha256(
                    {"learning_rate": fixture["learning_rate"]}
                ),
            },
            "scheduler": {
                "name": "none",
                "config_sha256": canonical_sha256({}),
            },
            "checkpoint_policy": {
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
        }
    )
    return DLRunManifest.from_payload(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--archive-sha256", required=True)
    args = parser.parse_args()
    commit = _hex_identifier(args.commit, "commit", 40)
    tree = _hex_identifier(args.tree, "tree", 40)
    archive_sha256 = _hex_identifier(args.archive_sha256, "archive_sha256", 64)

    import torch

    runtime = _runtime(torch)
    fixtures = [_fixture(seed) for seed in SEEDS]
    manifests = [_manifest(runtime, fixture) for fixture in fixtures]
    with tempfile.TemporaryDirectory(prefix="dl-repro-gate-") as temporary:
        report = run_pytorch_same_host_reproducibility(
            manifests, fixtures, temporary
        )
    payload = report.payload
    stable_projection = {
        "commit": commit,
        "tree": tree,
        "archive_sha256": archive_sha256,
        "gate_runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "plan_sha256": report.plan_sha256,
        "runner": payload["runner"],
        "execution": payload["execution"],
        "driver_observation": payload["driver_observation"],
        "results": [
            {
                "seed": row["seed"],
                "status": row["status"],
                "failure_classes": row["failure_classes"],
                "repeat_stable_sha256": [
                    row["repeat_a"].get("stable_sha256", "unavailable"),
                    row["repeat_b"].get("stable_sha256", "unavailable"),
                ],
                "final_loss": row["repeat_a"].get("final_loss", "unavailable"),
            }
            for row in payload["results"]
        ],
        "summary": payload["summary"],
        "limitations": payload["limitations"],
    }
    stable_sha256 = canonical_sha256(stable_projection)
    driver = payload["driver_observation"]
    print(
        "DL SAME-HOST REPRODUCIBILITY GATE: PASS "
        f"commit={commit} tree={tree} archive_sha256={archive_sha256} "
        f"stable_sha256={stable_sha256} report_sha256={report.sha256}"
    )
    print(
        "DL SAME-HOST REPRODUCIBILITY RESULT: "
        f"framework={runtime['framework']['version']} "
        f"cuda={runtime['framework']['backend_version']} "
        f"device={runtime['hardware']['device_model']} "
        f"compute_capability={runtime['hardware']['compute_capability']} "
        f"driver_status={driver['status']} driver_version={driver['version']} "
        f"successful_seeds={','.join(str(seed) for seed in payload['summary']['successful_seeds'])} "
        f"failed_seeds={','.join(str(seed) for seed in payload['summary']['failed_seeds']) or 'none'} "
        f"exact_repeat_matches={payload['summary']['exact_repeat_matches']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
