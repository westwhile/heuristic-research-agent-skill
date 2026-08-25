"""P7B4 contracts for the Candidate Skill semantic-review protocol."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from research_evolution.core import (
    PublicationError,
    publish_record,
    verify_record_graph,
)
from research_evolution.evolution import (
    SkillSemanticReviewAttestation,
    SkillSemanticReviewError,
    attest_skill_semantic_review_protocol,
    validate_skill_candidate,
)

from .test_skill_candidate_bundle import NOW
from .test_skill_static_validation import _inputs as _static_inputs

DIMENSIONS = (
    "task_correctness",
    "scope_and_contraindications",
    "trigger_precision",
    "failure_and_pause_boundaries",
    "negative_transfer_risk",
    "privacy_and_license",
    "rollback_and_retirement",
)


def _inputs(
    domain: str = "math",
    *,
    rejected_dimension: str | None = None,
) -> tuple[Any, Any, dict[str, Any], bytes]:
    bundle, payload, static_contract = _static_inputs(domain)
    static = validate_skill_candidate(
        bundle,
        payload,
        static_contract,
        validated_at=NOW,
    )
    evidence = json.dumps(
        {
            "domain": domain,
            "fixture": "synthetic semantic-review protocol evidence",
            "scope": "engineering contract only",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    evidence_sha = hashlib.sha256(evidence).hexdigest()
    dimensions = []
    for dimension in DIMENSIONS:
        result = "unsatisfied" if dimension == rejected_dimension else "satisfied"
        dimensions.append(
            {
                "dimension": dimension,
                "result": result,
                "rationale": (
                    f"Synthetic {domain} fixture records {result} for {dimension}."
                ),
                "evidence_sha256": evidence_sha,
            }
        )
    contract = {
        "protocol_id": "p7b4-semantic-review-protocol-v1",
        "reviewer": {
            "principal": f"synthetic-reviewer-{domain}",
            "kind": "synthetic_fixture",
            "session_id": f"synthetic-review-session-{domain}",
            "model_id": "not-applicable",
            "independence_group": f"synthetic-review-group-{domain}",
            "shared_context_with_drafter": False,
        },
        "review_evidence": {
            "name": f"reviews/{domain}-semantic-review.json",
            "media_type": "application/json",
            "sha256": evidence_sha,
            "size_bytes": len(evidence),
        },
        "dimensions": dimensions,
        "declared_outcome": (
            "protocol_reject" if rejected_dimension else "protocol_accept"
        ),
    }
    return bundle, static, contract, evidence


class SkillSemanticReviewProtocolTest(unittest.TestCase):
    def test_math_accept_and_quant_reject_use_one_protocol_seam(self) -> None:
        cases = (
            ("math", None, "protocol_accept"),
            ("quant", "negative_transfer_risk", "protocol_reject"),
        )
        attestations: list[SkillSemanticReviewAttestation] = []
        for domain, rejected, expected in cases:
            with self.subTest(domain=domain):
                bundle, static, contract, evidence = _inputs(
                    domain,
                    rejected_dimension=rejected,
                )
                attestation = attest_skill_semantic_review_protocol(
                    bundle,
                    static,
                    contract,
                    evidence,
                    reviewed_at=NOW,
                )
                attestations.append(attestation)
                self.assertEqual(attestation.payload["outcome"], expected)
                self.assertEqual(attestation.payload["blockers"], [])
                self.assertTrue(
                    attestation.payload["claims"][
                        "semantic_review_protocol_attested"
                    ]
                )
                self.assertTrue(attestation.payload["claims"]["synthetic_fixture"])
                for claim in (
                    "real_independent_semantic_review_completed",
                    "semantic_review_completed",
                    "fresh_session_validated",
                    "private_evaluation_completed",
                    "promotion_authorized",
                    "publication_authorized",
                    "installation_authorized",
                    "activation_authorized",
                    "runtime_loaded",
                ):
                    self.assertFalse(attestation.payload["claims"][claim])
        self.assertNotEqual(attestations[0].sha256, attestations[1].sha256)

    def test_reviewer_label_and_shared_context_fail_closed(self) -> None:
        bundle, static, contract, evidence = _inputs("math")
        contract["reviewer"]["principal"] = bundle.payload["drafter"]
        contract["reviewer"]["shared_context_with_drafter"] = True
        attestation = attest_skill_semantic_review_protocol(
            bundle, static, contract, evidence, reviewed_at=NOW
        )
        self.assertEqual(attestation.payload["outcome"], "protocol_inconclusive")
        self.assertEqual(
            {row["code"] for row in attestation.payload["blockers"]},
            {
                "reviewer_matches_drafter_label",
                "shared_context_with_drafter_declared",
            },
        )
        self.assertFalse(
            attestation.payload["claims"]["reviewer_label_distinct_from_drafter"]
        )
        self.assertFalse(
            attestation.payload["claims"]["shared_context_with_drafter_absent"]
        )

        bundle, static, contract, evidence = _inputs("math")
        contract["reviewer"]["principal"] = static.payload["validator"]["principal"]
        attestation = attest_skill_semantic_review_protocol(
            bundle, static, contract, evidence, reviewed_at=NOW
        )
        self.assertIn(
            "reviewer_matches_static_validator_label",
            {row["code"] for row in attestation.payload["blockers"]},
        )

    def test_evidence_mutation_and_restricted_content_are_inconclusive(self) -> None:
        bundle, static, contract, evidence = _inputs("math")
        attestation = attest_skill_semantic_review_protocol(
            bundle,
            static,
            contract,
            evidence + b"mutation",
            reviewed_at=NOW,
        )
        self.assertEqual(attestation.payload["outcome"], "protocol_inconclusive")
        self.assertEqual(
            {row["code"] for row in attestation.payload["blockers"]},
            {
                "review_evidence_hash_or_size_mismatch",
                "restricted_scan_incomplete",
            },
        )
        self.assertFalse(
            attestation.payload["claims"]["review_evidence_bytes_verified"]
        )

        bundle, static, contract, _ = _inputs("math")
        restricted = b'{"contact":"researcher@example.com"}'
        contract["review_evidence"]["sha256"] = hashlib.sha256(
            restricted
        ).hexdigest()
        contract["review_evidence"]["size_bytes"] = len(restricted)
        for row in contract["dimensions"]:
            row["evidence_sha256"] = contract["review_evidence"]["sha256"]
        attestation = attest_skill_semantic_review_protocol(
            bundle, static, contract, restricted, reviewed_at=NOW
        )
        self.assertIn(
            "restricted_content_detected",
            {row["code"] for row in attestation.payload["blockers"]},
        )
        self.assertNotIn("researcher@example.com", json.dumps(attestation.payload))

    def test_unverified_dimension_and_declared_outcome_mismatch_are_not_accepts(
        self,
    ) -> None:
        bundle, static, contract, evidence = _inputs("math")
        contract["dimensions"][0]["result"] = "unverified"
        contract["declared_outcome"] = "protocol_inconclusive"
        attestation = attest_skill_semantic_review_protocol(
            bundle, static, contract, evidence, reviewed_at=NOW
        )
        self.assertEqual(attestation.payload["outcome"], "protocol_inconclusive")
        self.assertEqual(attestation.payload["blockers"], [])

        bundle, static, contract, evidence = _inputs(
            "quant", rejected_dimension="trigger_precision"
        )
        contract["declared_outcome"] = "protocol_accept"
        attestation = attest_skill_semantic_review_protocol(
            bundle, static, contract, evidence, reviewed_at=NOW
        )
        self.assertEqual(attestation.payload["outcome"], "protocol_inconclusive")
        self.assertIn(
            "declared_outcome_mismatch",
            {row["code"] for row in attestation.payload["blockers"]},
        )

    def test_static_fail_or_cross_candidate_receipt_blocks_protocol(self) -> None:
        bundle, payload, static_contract = _static_inputs("quant")
        static_contract["registry_skills"][0] = {
            "name": bundle.payload["skill"]["name"],
            "positive_triggers": [
                bundle.payload["trigger_contract"]["positive_triggers"][0]
            ],
        }
        static_fail = validate_skill_candidate(
            bundle, payload, static_contract, validated_at=NOW
        )
        _, _, contract, evidence = _inputs("quant")
        attestation = attest_skill_semantic_review_protocol(
            bundle, static_fail, contract, evidence, reviewed_at=NOW
        )
        self.assertIn(
            "static_validation_prerequisite_not_passed",
            {row["code"] for row in attestation.payload["blockers"]},
        )

        math_bundle, math_static, _, _ = _inputs("math")
        quant_bundle, _, quant_contract, quant_evidence = _inputs("quant")
        attestation = attest_skill_semantic_review_protocol(
            quant_bundle,
            math_static,
            quant_contract,
            quant_evidence,
            reviewed_at=NOW,
        )
        self.assertEqual(attestation.payload["outcome"], "protocol_inconclusive")
        self.assertIn(
            "static_receipt_candidate_mismatch",
            {row["code"] for row in attestation.payload["blockers"]},
        )
        self.assertNotEqual(math_bundle.sha256, quant_bundle.sha256)

    def test_contract_and_wrapper_mutations_fail_closed(self) -> None:
        bundle, static, contract, evidence = _inputs("math")
        contract["dimensions"].pop()
        with self.assertRaisesRegex(SkillSemanticReviewError, "each required"):
            attest_skill_semantic_review_protocol(
                bundle, static, contract, evidence, reviewed_at=NOW
            )

        bundle, static, contract, evidence = _inputs("math")
        attestation = attest_skill_semantic_review_protocol(
            bundle, static, contract, evidence, reviewed_at=NOW
        )
        mutated = attestation.payload
        mutated["claims"]["semantic_review_completed"] = True
        with self.assertRaises(SkillSemanticReviewError):
            SkillSemanticReviewAttestation.from_payload(mutated)

    def test_graph_and_publication_recognize_protocol_attestation(self) -> None:
        bundle, static, contract, evidence = _inputs("math")
        attestation = attest_skill_semantic_review_protocol(
            bundle, static, contract, evidence, reviewed_at=NOW
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            publish_record(json.dumps(attestation.payload), root=root)
            report = verify_record_graph(root)
        self.assertFalse(report.ok)
        self.assertEqual(
            report.families, {"skill-semantic-review-attestation/v1": 1}
        )
        self.assertEqual(
            {violation.kind for violation in report.violations},
            {"dangling_reference"},
        )

        changed = attestation.payload
        restricted = "researcher@example.com"
        changed["limitations"][0] = restricted
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            with self.assertRaisesRegex(PublicationError, "restricted content"):
                publish_record(json.dumps(changed), root=root)
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
