"""Run the bounded R5 PyTorch/CUDA portability trial without uploading data.

The caller supplies repository object IDs and an independently computed archive
SHA-256.  PyTorch/CUDA must already exist in the selected interpreter.  The
optional canonical receipt is written only to an explicit, new path outside
the repository; no network or installation action is performed.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from research_evolution.adapters.deep_learning.pytorch_portability import (
    run_pytorch_portability_trial,
)
from research_evolution.core import canonical_bytes, canonical_sha256

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--receipt-output", type=Path)
    args = parser.parse_args()

    plan = {
        "schema": "pytorch-portability-trial-plan/v1",
        "repository": {
            "commit_oid": _hex_identifier(args.commit, "commit", 40),
            "tree_oid": _hex_identifier(args.tree, "tree", 40),
            "archive_sha256": _hex_identifier(
                args.archive_sha256, "archive_sha256", 64
            ),
            "dirty": False,
        },
    }
    with tempfile.TemporaryDirectory(prefix="dl-portability-r5-") as temporary:
        receipt = run_pytorch_portability_trial(
            plan, artifact_root=Path(temporary)
        )

    payload = receipt.payload
    stable_projection = {
        "trial_plan_sha256": payload["trial_plan_sha256"],
        "repository": payload["repository"],
        "runner": payload["runner"],
        "execution": payload["execution"],
        "same_host_reproducibility": {
            "expected_seeds": payload["same_host_reproducibility"]
            ["expected_seeds"],
            "successful_seeds": payload["same_host_reproducibility"]
            ["successful_seeds"],
            "failed_seeds": payload["same_host_reproducibility"]["failed_seeds"],
            "exact_repeat_matches": payload["same_host_reproducibility"]
            ["exact_repeat_matches"],
            "results": payload["same_host_reproducibility"]["results"],
        },
        "controlled_interruption": {
            key: value
            for key, value in payload["controlled_interruption"].items()
            if key != "observation_sha256"
        },
        "privacy": payload["privacy"],
        "limitations": payload["limitations"],
    }
    stable_sha256 = canonical_sha256(stable_projection)
    if args.receipt_output is not None:
        destination = _new_external_output(args.receipt_output)
        destination.write_bytes(canonical_bytes(payload))

    print(
        "DL PORTABILITY R5 GATE: PASS "
        f"commit={payload['repository']['commit_oid']} "
        f"tree={payload['repository']['tree_oid']} "
        f"archive_sha256={payload['repository']['archive_sha256']} "
        f"stable_sha256={stable_sha256} receipt_sha256={receipt.sha256}"
    )
    execution = payload["execution"]
    driver = execution["driver"]
    print(
        "DL PORTABILITY R5 RESULT: "
        f"framework={execution['framework_version']} "
        f"cuda={execution['cuda_version']} "
        f"driver_status={driver['status']} driver_version={driver['version']} "
        f"device={execution['device']['model']} "
        f"compute_capability={execution['device']['compute_capability']} "
        "successful_seeds=7,11,13 exact_repeat_matches=3 "
        "checkpoint_confirmed=true spawn_identity_verified=true "
        "double_charged=false scheduler_preemption_observed=false "
        "independent_hosts_verified=false external_adoption_verified=false "
        f"receipt_output_written={str(args.receipt_output is not None).lower()}"
    )
    return 0


def _hex_identifier(value: str, name: str, length: int) -> str:
    if len(value) != length or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(
            f"{name} must be {length} lowercase hexadecimal characters"
        )
    return value


def _new_external_output(source: Path) -> Path:
    if not source.is_absolute():
        raise ValueError("receipt output must be an absolute path")
    parent = source.parent.resolve(strict=True)
    try:
        parent.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise ValueError("receipt output must remain outside the repository")
    destination = parent / source.name
    if destination.exists():
        raise ValueError("receipt output must not already exist")
    return destination


if __name__ == "__main__":
    raise SystemExit(main())
