"""P7B1 candidate eligibility attestation contracts."""

from __future__ import annotations

import copy
import unittest
from typing import Any

from research_evolution.evolution import (
    CandidateEligibilityAttestation,
    CandidateEligibilityError,
    assess_candidate_eligibility,
    close_candidate_bundle,
)
from tests.unit.test_evolution_incubator import NOW, _candidate


CRITERIA = (
    "clear_positive_triggers",
    "clear_exclusions",
    "stable_input_contract",
    "stable_output_contract",
    "explicit_failure_pause_boundaries",
    "portable_resources",
    "measurable_gain_plan",
)


def _inputs(
    domain: str = "math",
) -> tuple[dict[str, Any], Any, dict[str, Any], dict[str, bytes]]:
    manifest, members = _candidate(domain)
    receipt = close_candidate_bundle(manifest, members, closed_at=NOW)
    source_cases = []
    for index, case in enumerate(manifest["source_cases"], start=1):
        source_cases.append(
            {
                **case,
                "independence_group": f"{domain}-problem-{index}",
                "origin_run_id": f"{domain}-run-{index}",
                "dataset_lineage_id": f"{domain}-dataset-{index}",
                "task_template_id": f"{domain}-template-{index}",
                "semantic_duplicate_group": f"{domain}-semantic-{index}",
            }
        )
    criteria = [
        {
            "criterion": criterion,
            "status": "satisfied",
            "evidence_name": f"evidence/{criterion}.json",
            "rationale": "The bounded synthetic contract declares this criterion met.",
        }
        for criterion in CRITERIA
    ]
    assessment = {
        "assessor": f"eligibility-assessor-{domain}",
        "candidate_kind": "reusable_skill_proposal",
        "source_cases": source_cases,
        "criteria": criteria,
    }
    evidence = {
        row["evidence_name"]: f"{domain}:{row['criterion']}".encode("utf-8")
        for row in criteria
    }
    return manifest, receipt, assessment, evidence


class CandidateEligibilityTest(unittest.TestCase):
    def test_math_and_quant_cross_same_domain_neutral_seam(self) -> None:
        for domain in ("math", "quant"):
            with self.subTest(domain=domain):
                manifest, receipt, assessment, evidence = _inputs(domain)
                attestation = assess_candidate_eligibility(
                    manifest,
                    receipt,
                    assessment,
                    evidence,
                    assessed_at=NOW,
                )
                self.assertIsInstance(attestation, CandidateEligibilityAttestation)
                self.assertEqual(
                    attestation.payload["outcome"], "eligible_for_payload_drafting"
                )
                self.assertEqual(
                    attestation.payload["distinct_independence_groups"], 2
                )
                self.assertEqual(attestation.payload["blockers"], [])
                self.assertTrue(attestation.payload["claims"]["byte_closure_verified"])
                for claim in (
                    "source_independence_externally_verified",
                    "semantic_review_completed",
                    "fresh_session_validated",
                    "private_evaluation_completed",
                    "publication_authorized",
                    "installation_authorized",
                    "activation_authorized",
                ):
                    self.assertFalse(attestation.payload["claims"][claim])

    def test_non_reusable_candidate_kinds_are_terminally_ineligible(self) -> None:
        for candidate_kind in (
            "project_specific_script",
            "one_off_answer",
            "rapidly_changing_knowledge",
        ):
            with self.subTest(candidate_kind=candidate_kind):
                manifest, receipt, assessment, evidence = _inputs()
                assessment["candidate_kind"] = candidate_kind
                result = assess_candidate_eligibility(
                    manifest, receipt, assessment, evidence, assessed_at=NOW
                )
                self.assertEqual(result.payload["outcome"], "ineligible")
                self.assertIn(
                    {"code": "candidate_kind_not_reusable", "subject": candidate_kind},
                    result.payload["blockers"],
                )

    def test_source_independence_collisions_are_ineligible_not_counts(self) -> None:
        for field, code in (
            ("independence_group", "independence_group_collision"),
            ("origin_run_id", "origin_run_collision"),
            ("dataset_lineage_id", "dataset_lineage_collision"),
            ("task_template_id", "task_template_collision"),
            ("semantic_duplicate_group", "semantic_duplicate_collision"),
        ):
            with self.subTest(field=field):
                manifest, receipt, assessment, evidence = _inputs()
                assessment["source_cases"][1][field] = assessment["source_cases"][0][field]
                result = assess_candidate_eligibility(
                    manifest, receipt, assessment, evidence, assessed_at=NOW
                )
                self.assertEqual(result.payload["outcome"], "ineligible")
                self.assertIn(code, {row["code"] for row in result.payload["blockers"]})

    def test_unsatisfied_beats_unverified_and_both_are_auditable(self) -> None:
        manifest, receipt, assessment, evidence = _inputs()
        assessment["criteria"][0]["status"] = "unverified"
        deferred = assess_candidate_eligibility(
            manifest, receipt, assessment, evidence, assessed_at=NOW
        )
        self.assertEqual(deferred.payload["outcome"], "needs_more_evidence")
        self.assertEqual(deferred.payload["blockers"][0]["code"], "criterion_unverified")

        assessment["criteria"][1]["status"] = "unsatisfied"
        rejected = assess_candidate_eligibility(
            manifest, receipt, assessment, evidence, assessed_at=NOW
        )
        self.assertEqual(rejected.payload["outcome"], "ineligible")
        self.assertIn(
            "criterion_unsatisfied",
            {row["code"] for row in rejected.payload["blockers"]},
        )

    def test_exact_case_criteria_and_evidence_sets_fail_closed(self) -> None:
        manifest, receipt, assessment, evidence = _inputs()
        cases = [
            (lambda value: value["source_cases"].pop(), evidence, "source case set"),
            (lambda value: value["criteria"].pop(), evidence, "criterion set"),
            (lambda value: None, {**evidence, "evidence/extra.json": b"extra"}, "evidence set"),
        ]
        for mutate, supplied_evidence, message in cases:
            with self.subTest(message=message):
                changed = copy.deepcopy(assessment)
                mutate(changed)
                with self.assertRaisesRegex(CandidateEligibilityError, message):
                    assess_candidate_eligibility(
                        manifest,
                        receipt,
                        changed,
                        supplied_evidence,
                        assessed_at=NOW,
                    )

    def test_principal_closure_binding_and_exact_bytes_fail_closed(self) -> None:
        manifest, receipt, assessment, evidence = _inputs()
        assessment["assessor"] = manifest["principals"]["author"]
        with self.assertRaisesRegex(CandidateEligibilityError, "assessor.*author"):
            assess_candidate_eligibility(
                manifest, receipt, assessment, evidence, assessed_at=NOW
            )

        _, other_receipt, _, _ = _inputs("quant")
        with self.assertRaisesRegex(CandidateEligibilityError, "closure.*candidate"):
            assess_candidate_eligibility(
                manifest, other_receipt, _inputs()[2], evidence, assessed_at=NOW
            )

        malformed = dict(evidence)
        malformed[next(iter(malformed))] = bytearray(b"not exact bytes")  # type: ignore[assignment]
        with self.assertRaisesRegex(CandidateEligibilityError, "exact bytes"):
            assess_candidate_eligibility(
                manifest, receipt, _inputs()[2], malformed, assessed_at=NOW
            )

    def test_restricted_metadata_and_wrapper_mutation_fail_closed(self) -> None:
        manifest, receipt, assessment, evidence = _inputs()
        secret = "sk-" + "A" * 24
        assessment["criteria"][0]["rationale"] = secret
        with self.assertRaisesRegex(CandidateEligibilityError, "restricted content") as caught:
            assess_candidate_eligibility(
                manifest, receipt, assessment, evidence, assessed_at=NOW
            )
        self.assertNotIn(secret, str(caught.exception))

        manifest, receipt, assessment, evidence = _inputs()
        attestation = assess_candidate_eligibility(
            manifest, receipt, assessment, evidence, assessed_at=NOW
        )
        expected = attestation.sha256
        mutated = attestation.payload
        mutated["outcome"] = "ineligible"
        self.assertEqual(attestation.sha256, expected)
        with self.assertRaises(CandidateEligibilityError):
            CandidateEligibilityAttestation.from_payload(mutated)


if __name__ == "__main__":
    unittest.main()
