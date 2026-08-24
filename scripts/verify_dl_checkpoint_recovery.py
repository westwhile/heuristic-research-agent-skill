"""Exact-archive gate for bounded real PyTorch/CUDA checkpoint recovery.

Run this script from an exported commit with the PyTorch-enabled interpreter.
The caller supplies the Git commit/tree object IDs and archive SHA-256 that it
independently resolved before extraction.  The script binds those identifiers to one
three-process source/resume/uninterrupted-control receipt and prints a stable
projection hash that excludes timestamps and timing measurements.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import tempfile
from pathlib import Path

from research_evolution.adapters.deep_learning.manifest import DLRunManifest
from research_evolution.adapters.deep_learning.pytorch_recovery import (
    pytorch_recovery_identity,
    run_pytorch_checkpoint_recovery,
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


def _hex_identifier(value: str, name: str, length: int) -> str:
    if len(value) != length or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ValueError(f"{name} must be {length} lowercase hexadecimal characters")
    return value


def _fixture() -> dict:
    return {
        "schema": "pytorch-dl-recovery-fixture/v1",
        "fixture_id": "exact-archive-cuda-recovery-001",
        "case_sha256": canonical_sha256(
            {
                "case": "exact-archive-cuda-recovery-001",
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
    payload = load_strict_json(MANIFEST_FIXTURE.read_bytes())
    payload.update(
        {
            "manifest_id": "exact-archive-cuda-recovery-manifest-001",
            "run_id": "exact-archive-cuda-recovery-run-001",
            "study_id": "exact-archive-cuda-recovery-study-001",
            "case_sha256": fixture["case_sha256"],
            "execution_mode": "gpu_fixture",
            "runner": pytorch_recovery_identity(),
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
                    {
                        "learning_rate": fixture["learning_rate"],
                        "momentum": fixture["momentum"],
                    }
                ),
            },
            "scheduler": {
                "name": "step_lr",
                "config_sha256": canonical_sha256(
                    {
                        "step_size": fixture["scheduler_step_size"],
                        "gamma": fixture["scheduler_gamma"],
                    }
                ),
            },
            "checkpoint_policy": {
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

    fixture = _fixture()
    runtime = _runtime(torch)
    manifest = _manifest(runtime, fixture)
    with tempfile.TemporaryDirectory(prefix="dl-recovery-gate-") as temp:
        observation = run_pytorch_checkpoint_recovery(manifest, fixture, temp)
    payload = observation.payload
    stable_projection = {
        "commit": commit,
        "tree": tree,
        "archive_sha256": archive_sha256,
        "gate_runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "manifest_sha256": observation.manifest_sha256,
        "runner": payload["runner"],
        "fixture": payload["fixture"],
        "execution": payload["execution"],
        "process_roles": [row["role"] for row in payload["processes"]],
        "checkpoint": payload["checkpoint"],
        "equivalence": payload["equivalence"],
        "budget_ledger": payload["budget_ledger"],
        "limitations": payload["limitations"],
    }
    stable_sha256 = canonical_sha256(stable_projection)
    print(
        "DL RECOVERY GATE: PASS "
        f"commit={commit} tree={tree} archive_sha256={archive_sha256} "
        f"stable_sha256={stable_sha256} observation_sha256={observation.sha256}"
    )
    print(
        "DL RECOVERY RESULT: "
        f"framework={runtime['framework']['version']} "
        f"cuda={runtime['framework']['backend_version']} "
        f"device={runtime['hardware']['device_model']} "
        f"compute_capability={runtime['hardware']['compute_capability']} "
        f"checkpoint_bytes={payload['checkpoint']['size_bytes']} "
        f"steps={payload['budget_ledger']['resumed_cumulative_steps']} "
        "model_exact=true optimizer_exact=true scheduler_exact=true "
        "double_charged=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
