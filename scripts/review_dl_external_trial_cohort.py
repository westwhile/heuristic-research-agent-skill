"""Review public-safe R6A submissions locally without technical comparison."""

from __future__ import annotations

import argparse
from pathlib import Path

from research_evolution.adapters.deep_learning.external_trial import (
    DLExternalTrialSubmission,
    review_external_trial_cohort,
)
from research_evolution.adapters.types import AdapterError
from research_evolution.core import canonical_bytes

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", action="append", type=Path, required=True)
    parser.add_argument("--review-plan", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        submissions = [
            DLExternalTrialSubmission.from_json(path.read_bytes())
            for path in args.submission
        ]
        review = review_external_trial_cohort(
            submissions, args.review_plan.read_bytes()
        )
        destination = _new_external_output(args.review_output)
        destination.write_bytes(canonical_bytes(review.payload))
    except (AdapterError, OSError, ValueError):
        print(
            "DL EXTERNAL TRIAL COHORT REVIEW: FAIL "
            "reason=input_or_protocol_validation_failed"
        )
        return 1
    payload = review.payload
    print(
        "DL EXTERNAL TRIAL COHORT REVIEW: PASS "
        f"review_sha256={review.sha256} "
        f"submitted={payload['summary']['submitted']} "
        f"accepted={payload['summary']['accepted_submissions']} "
        f"environments={payload['summary']['distinct_environments']} "
        f"status={payload['summary']['status']} "
        "r5_technical_comparison_required=true "
        "external_adoption_verified=false "
        "production_reliability_verified=false "
        "automatic_upload_performed=false"
    )
    return 0


def _new_external_output(source: Path) -> Path:
    if not source.is_absolute():
        raise ValueError("review output must be an absolute path")
    parent = source.parent.resolve(strict=True)
    try:
        parent.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise ValueError("review output must remain outside the repository")
    destination = parent / source.name
    if destination.exists():
        raise ValueError("review output must not already exist")
    return destination


if __name__ == "__main__":
    raise SystemExit(main())
