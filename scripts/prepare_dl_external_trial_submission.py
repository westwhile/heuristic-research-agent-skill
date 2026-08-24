"""Create one public-safe R6A submission locally without uploading it."""

from __future__ import annotations

import argparse
from pathlib import Path

from research_evolution.adapters.deep_learning.external_trial import (
    build_external_trial_submission,
)
from research_evolution.adapters.deep_learning.pytorch_portability import (
    DLPortabilityTrialReceipt,
)
from research_evolution.adapters.types import AdapterError
from research_evolution.core import canonical_bytes

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--submission-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = DLPortabilityTrialReceipt.from_json(args.receipt.read_bytes())
        submission = build_external_trial_submission(
            receipt, args.attestation.read_bytes()
        )
        destination = _new_external_output(args.submission_output)
        destination.write_bytes(canonical_bytes(submission.payload))
    except (AdapterError, OSError, ValueError):
        print(
            "DL EXTERNAL TRIAL SUBMISSION: FAIL "
            "reason=input_or_protocol_validation_failed"
        )
        return 1
    payload = submission.payload
    print(
        "DL EXTERNAL TRIAL SUBMISSION: PASS "
        f"submission_sha256={submission.sha256} "
        f"receipt_sha256={payload['source_receipt']['receipt_sha256']} "
        "evidence_level=self_declared "
        "independent_participant_verified=false "
        "independent_host_verified=false "
        "external_adoption_verified=false "
        "automatic_upload_performed=false"
    )
    return 0


def _new_external_output(source: Path) -> Path:
    if not source.is_absolute():
        raise ValueError("submission output must be an absolute path")
    parent = source.parent.resolve(strict=True)
    try:
        parent.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise ValueError("submission output must remain outside the repository")
    destination = parent / source.name
    if destination.exists():
        raise ValueError("submission output must not already exist")
    return destination


if __name__ == "__main__":
    raise SystemExit(main())
