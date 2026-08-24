from __future__ import annotations

import copy
import unittest
from pathlib import Path

from research_evolution.adapters.deep_learning.external_trial import (
    DLExternalTrialCohortReview,
    DLExternalTrialSubmission,
    build_external_trial_submission,
    review_external_trial_cohort,
)
from research_evolution.adapters.types import AdapterError
from research_evolution.core import canonical_sha256
from research_evolution.adapters.deep_learning.pytorch_portability import (
    DLPortabilityTrialReceipt,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
RECEIPT_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "adapters"
    / "dl-portability-trial-receipt"
    / "v1"
    / "valid"
    / "full.json"
)


def _receipt(filename: str = "full.json") -> DLPortabilityTrialReceipt:
    return DLPortabilityTrialReceipt.from_json(
        (RECEIPT_FIXTURE.parent / filename).read_bytes()
    )


def _attestation(
    *,
    participant_id: str = "participant-0123456789abcdef",
    identity_hash: str = "b" * 64,
    consent_hash: str = "c" * 64,
    submitted_at: str = "2026-08-24T09:00:00Z",
) -> dict:
    return {
        "schema": "dl-external-trial-attestation/v1",
        "protocol_sha256": "a" * 64,
        "submitted_at": submitted_at,
        "public_participant_id": participant_id,
        "private_identity_record_sha256": identity_hash,
        "private_consent_record_sha256": consent_hash,
        "declarations": {
            "participant_is_not_maintainer": True,
            "participant_controlled_execution": True,
            "maintainer_operated_execution": False,
            "receipt_generated_by_participant": True,
            "private_record_hashes_nonce_hardened": True,
        },
        "consent": {
            "protocol_version_accepted": True,
            "public_pseudonym_accepted": True,
            "public_technical_metadata_accepted": True,
        },
    }


class ExternalTrialSubmissionTests(unittest.TestCase):
    def test_participant_can_build_public_safe_self_declared_submission(self) -> None:
        receipt = _receipt()

        submission = build_external_trial_submission(receipt, _attestation())

        payload = submission.payload
        self.assertEqual(payload["status"], "submitted_unreviewed")
        self.assertEqual(payload["attestation"]["evidence_level"], "self_declared")
        self.assertEqual(payload["source_receipt"]["receipt_sha256"], receipt.sha256)
        self.assertEqual(
            payload["participant"]["public_participant_id"],
            "participant-0123456789abcdef",
        )
        self.assertFalse(payload["claims"]["independent_participant_verified"])
        self.assertFalse(payload["claims"]["independent_host_verified"])
        self.assertFalse(payload["claims"]["external_adoption_verified"])
        self.assertFalse(payload["claims"]["production_reliability_verified"])
        self.assertTrue(all(value is False for value in payload["privacy"].values()))

    def test_submission_rejects_tampered_hash_bound_id(self) -> None:
        submission = build_external_trial_submission(_receipt(), _attestation())
        tampered = submission.payload
        tampered["submission_id"] = "dl-external-submission-ffffffffffffffff"

        with self.assertRaises(AdapterError) as context:
            DLExternalTrialSubmission.from_payload(tampered)
        self.assertTrue(
            any("submission-id" in detail for detail in context.exception.details)
        )

    def test_submission_rejects_embedded_personal_identifier(self) -> None:
        submission = build_external_trial_submission(_receipt(), _attestation())
        tampered = submission.payload
        tampered["limitations"][0] = "contact=" + "alice" + "@" + "example.com"

        with self.assertRaises(AdapterError) as context:
            DLExternalTrialSubmission.from_payload(tampered)
        self.assertTrue(
            any("personal identifier" in detail for detail in context.exception.details)
        )

    def test_submission_requires_explicit_publication_consent(self) -> None:
        attestation = _attestation()
        attestation["consent"]["public_technical_metadata_accepted"] = False

        with self.assertRaises(AdapterError):
            build_external_trial_submission(_receipt(), attestation)


class ExternalTrialCohortReviewTests(unittest.TestCase):
    def test_coordinator_review_qualifies_trial_without_claiming_adoption(self) -> None:
        first = build_external_trial_submission(_receipt("full.json"), _attestation())
        second = build_external_trial_submission(
            _receipt("minimal.json"),
            _attestation(
                participant_id="participant-fedcba9876543210",
                identity_hash="d" * 64,
                consent_hash="e" * 64,
                submitted_at="2026-08-24T09:05:00Z",
            ),
        )
        review_plan = {
            "schema": "dl-external-trial-cohort-review-plan/v1",
            "reviewed_at": "2026-08-24T09:10:00Z",
            "protocol_sha256": "a" * 64,
            "minimum_independent_participants": 2,
            "minimum_distinct_environments": 2,
            "records": [
                _review_record(first, host_hash="1" * 64),
                _review_record(second, host_hash="2" * 64),
            ],
        }

        report = review_external_trial_cohort([first, second], review_plan)

        payload = report.payload
        self.assertEqual(
            payload["summary"]["status"],
            "eligible_for_separate_technical_comparison",
        )
        self.assertEqual(payload["summary"]["accepted_submissions"], 2)
        self.assertEqual(payload["summary"]["distinct_environments"], 2)
        self.assertEqual(
            payload["claims"]["independent_participants_evidence"],
            "coordinator_verified",
        )
        self.assertEqual(
            payload["claims"]["independent_hosts_evidence"],
            "coordinator_verified",
        )
        self.assertFalse(payload["claims"]["external_adoption_verified"])
        self.assertFalse(payload["claims"]["production_reliability_verified"])
        self.assertTrue(payload["next_gate"]["r5_technical_comparison_required"])

    def test_cohort_review_rejects_tampered_hash_bound_id(self) -> None:
        first, second, plan = _eligible_cohort_inputs()
        report = review_external_trial_cohort([first, second], plan)
        tampered = report.payload
        tampered["review_id"] = "dl-external-review-ffffffffffffffff"

        with self.assertRaises(AdapterError) as context:
            DLExternalTrialCohortReview.from_payload(tampered)
        self.assertTrue(
            any("review-id" in detail for detail in context.exception.details)
        )

    def test_duplicate_private_host_record_cannot_verify_independent_hosts(
        self,
    ) -> None:
        first = build_external_trial_submission(_receipt("full.json"), _attestation())
        second = build_external_trial_submission(
            _receipt("minimal.json"),
            _attestation(
                participant_id="participant-fedcba9876543210",
                identity_hash="d" * 64,
                consent_hash="e" * 64,
                submitted_at="2026-08-24T09:05:00Z",
            ),
        )
        shared_host_hash = "1" * 64
        report = review_external_trial_cohort(
            [first, second],
            {
                "schema": "dl-external-trial-cohort-review-plan/v1",
                "reviewed_at": "2026-08-24T09:10:00Z",
                "protocol_sha256": "a" * 64,
                "minimum_independent_participants": 2,
                "minimum_distinct_environments": 2,
                "records": [
                    _review_record(first, host_hash=shared_host_hash),
                    _review_record(second, host_hash=shared_host_hash),
                ],
            },
        )

        self.assertEqual(
            report.payload["summary"]["status"],
            "insufficient_verified_independence",
        )
        self.assertNotEqual(
            report.payload["claims"]["independent_hosts_evidence"],
            "coordinator_verified",
        )

    def test_duplicate_public_participant_cannot_form_a_cohort(self) -> None:
        first = build_external_trial_submission(_receipt("full.json"), _attestation())
        second = build_external_trial_submission(
            _receipt("minimal.json"),
            _attestation(
                identity_hash="d" * 64,
                consent_hash="e" * 64,
                submitted_at="2026-08-24T09:05:00Z",
            ),
        )
        plan = {
            "schema": "dl-external-trial-cohort-review-plan/v1",
            "reviewed_at": "2026-08-24T09:10:00Z",
            "protocol_sha256": "a" * 64,
            "minimum_independent_participants": 2,
            "minimum_distinct_environments": 2,
            "records": [
                _review_record(first, host_hash="1" * 64),
                _review_record(second, host_hash="2" * 64),
            ],
        }

        with self.assertRaises(AdapterError):
            review_external_trial_cohort([first, second], plan)

    def test_unverified_coordinator_records_remain_self_declared(self) -> None:
        first, second, plan = _eligible_cohort_inputs()
        for record in plan["records"]:
            record["participant_independence_review"] = "unverified"
            record["host_independence_review"] = "unverified"

        report = review_external_trial_cohort([first, second], plan)

        self.assertEqual(
            report.payload["summary"]["status"],
            "insufficient_verified_independence",
        )
        self.assertEqual(
            report.payload["claims"]["independent_participants_evidence"],
            "self_declared",
        )
        self.assertEqual(
            report.payload["claims"]["independent_hosts_evidence"],
            "self_declared",
        )

    def test_cohort_review_rejects_tampered_summary(self) -> None:
        first, second, plan = _eligible_cohort_inputs()
        report = review_external_trial_cohort([first, second], plan)
        tampered = report.payload
        tampered["summary"]["accepted_submissions"] = 1

        with self.assertRaises(AdapterError) as context:
            DLExternalTrialCohortReview.from_payload(tampered)
        self.assertTrue(
            any("review-counts" in detail for detail in context.exception.details)
        )

    def test_cohort_review_rejects_duplicate_hash_bound_rows_on_reload(self) -> None:
        first, second, plan = _eligible_cohort_inputs()
        payload = review_external_trial_cohort([first, second], plan).payload
        payload["submissions"][1] = copy.deepcopy(payload["submissions"][0])
        payload["summary"]["distinct_participants"] = 1
        payload["summary"]["distinct_environments"] = 1
        payload["summary"]["status"] = "insufficient_verified_independence"
        payload["claims"]["independent_hosts_evidence"] = "self_declared"
        core = {key: value for key, value in payload.items() if key != "review_id"}
        payload["review_id"] = f"dl-external-review-{canonical_sha256(core)[:16]}"

        with self.assertRaises(AdapterError) as context:
            DLExternalTrialCohortReview.from_payload(payload)
        self.assertTrue(
            any("duplicate" in detail for detail in context.exception.details)
        )

    def test_cohort_review_rejects_out_of_range_policy_on_reload(self) -> None:
        first, second, plan = _eligible_cohort_inputs()
        payload = review_external_trial_cohort([first, second], plan).payload
        payload["policy"]["minimum_independent_participants"] = 1
        core = {key: value for key, value in payload.items() if key != "review_id"}
        payload["review_id"] = f"dl-external-review-{canonical_sha256(core)[:16]}"

        with self.assertRaises(AdapterError) as context:
            DLExternalTrialCohortReview.from_payload(payload)
        self.assertTrue(
            any("policy" in detail for detail in context.exception.details)
        )


def _review_record(submission, *, host_hash: str) -> dict:
    participant = submission.payload["participant"]
    return {
        "submission_sha256": submission.sha256,
        "public_participant_id": participant["public_participant_id"],
        "private_identity_record_sha256": participant[
            "private_identity_record_sha256"
        ],
        "private_consent_record_sha256": participant[
            "private_consent_record_sha256"
        ],
        "private_host_record_sha256": host_hash,
        "private_host_record_hash_nonce_hardened": True,
        "disposition": "accepted",
        "receipt_binding_review": "verified",
        "participant_independence_review": "verified",
        "host_independence_review": "verified",
        "consent_review": "verified",
    }


def _eligible_cohort_inputs():
    first = build_external_trial_submission(_receipt("full.json"), _attestation())
    second = build_external_trial_submission(
        _receipt("minimal.json"),
        _attestation(
            participant_id="participant-fedcba9876543210",
            identity_hash="d" * 64,
            consent_hash="e" * 64,
            submitted_at="2026-08-24T09:05:00Z",
        ),
    )
    plan = {
        "schema": "dl-external-trial-cohort-review-plan/v1",
        "reviewed_at": "2026-08-24T09:10:00Z",
        "protocol_sha256": "a" * 64,
        "minimum_independent_participants": 2,
        "minimum_distinct_environments": 2,
        "records": [
            _review_record(first, host_hash="1" * 64),
            _review_record(second, host_hash="2" * 64),
        ],
    }
    return first, second, plan


if __name__ == "__main__":
    unittest.main()
