"""Compare public-safe R5 receipts locally without uploading them."""

from __future__ import annotations

import argparse
from pathlib import Path

from research_evolution.adapters.deep_learning.portability_report import (
    build_cross_environment_report,
)
from research_evolution.adapters.deep_learning.pytorch_portability import (
    DLPortabilityTrialReceipt,
)
from research_evolution.core import canonical_bytes, canonical_sha256

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", action="append", type=Path, required=True)
    parser.add_argument(
        "--final-loss-absolute-tolerance", type=float, default=1e-12
    )
    parser.add_argument("--report-output", type=Path)
    args = parser.parse_args()

    receipts = [
        DLPortabilityTrialReceipt.from_json(path.read_bytes())
        for path in args.receipt
    ]
    report = build_cross_environment_report(
        receipts,
        {
            "policy_id": "dl-cross-environment-comparison-policy/v1",
            "expected_seeds": [7, 11, 13],
            "final_loss_absolute_tolerance": (
                args.final_loss_absolute_tolerance
            ),
        },
    )
    payload = report.payload
    stable_projection = {
        key: value
        for key, value in payload.items()
        if key not in {"report_id", "observed_at"}
    }
    if args.report_output is not None:
        destination = _new_external_output(args.report_output)
        destination.write_bytes(canonical_bytes(payload))
    print(
        "DL CROSS-ENVIRONMENT RECEIPT COMPARISON: PASS "
        f"stable_sha256={canonical_sha256(stable_projection)} "
        f"report_sha256={report.sha256} "
        f"receipts={payload['summary']['receipt_count']} "
        f"environments={payload['summary']['environment_count']} "
        f"verdict={payload['summary']['verdict']} "
        "independent_hosts_verified=false "
        "independent_participants_verified=false "
        "external_adoption_verified=false "
        f"report_output_written={str(args.report_output is not None).lower()}"
    )
    return 0


def _new_external_output(source: Path) -> Path:
    if not source.is_absolute():
        raise ValueError("report output must be an absolute path")
    parent = source.parent.resolve(strict=True)
    try:
        parent.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise ValueError("report output must remain outside the repository")
    destination = parent / source.name
    if destination.exists():
        raise ValueError("report output must not already exist")
    return destination


if __name__ == "__main__":
    raise SystemExit(main())
