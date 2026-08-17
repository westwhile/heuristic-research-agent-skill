"""Unit tests for the Math adapter mapping and ceiling rules (ADR-0005)."""

import unittest
from pathlib import Path

from research_evolution.adapters import (
    AdapterError,
    ClaimAssessment,
    DomainTask,
    EvaluationContract,
)
from research_evolution.adapters.math import MathAdapter
from research_evolution.core import (
    CoreError,
    canonical_bytes,
    canonical_sha256,
    load_record,
    load_strict_json,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"


def _payload(family: str, kind: str, name: str) -> dict:
    return load_strict_json((FIXTURES / family / "v1" / kind / name).read_bytes())


TASK_FULL = _payload("math-task", "valid", "full.json")
CLAIM_PROOF = _payload("math-claim", "valid", "full.json")
CLAIM_INCONCLUSIVE = _payload("math-claim", "valid", "minimal.json")
EVIDENCE_NUMERIC = _payload("math-evidence", "valid", "minimal.json")
EVIDENCE_CERTIFICATE = _payload("math-evidence", "valid", "full.json")
CASE_BOUNDED = _payload("math-case", "valid", "minimal.json")
CASE_DECIDE = _payload("math-case", "valid", "full.json")


class MathNormalizeTaskTest(unittest.TestCase):
    def test_maps_full_input_into_core_draft(self) -> None:
        task = MathAdapter().normalize_task(TASK_FULL)
        self.assertIsInstance(task, DomainTask)
        self.assertEqual(task.domain, "math")
        self.assertEqual(task.domain_schema_id, "math-task/v1")
        draft = task.to_core_task_payload()
        record = load_record(canonical_bytes(draft))
        self.assertEqual(record.schema_id, "research-task/v1")
        self.assertEqual(draft["task_id"], TASK_FULL["task_id"])
        self.assertEqual(draft["domain"], "math")
        # Caller-injected timestamp passes through; the adapter reads no clock.
        self.assertEqual(draft["created_at"], TASK_FULL["created_at"])
        context = draft["domain_context"]
        self.assertEqual(context["quantifiers"], TASK_FULL["quantifiers"])
        self.assertEqual(context["object_domain"], TASK_FULL["object_domain"])
        self.assertEqual(context["sought"], TASK_FULL["sought"])
        self.assertEqual(context["problem_id"], TASK_FULL["problem_id"])

    def test_invalid_input_fails_structured(self) -> None:
        payload = _payload("math-task", "invalid", "missing-quantifiers.json")
        with self.assertRaises(AdapterError) as ctx:
            MathAdapter().normalize_task(payload)
        self.assertNotIsInstance(ctx.exception, CoreError)
        self.assertIn("quantifiers", str(ctx.exception))

    def test_normalize_task_is_pure(self) -> None:
        adapter = MathAdapter()
        first = adapter.normalize_task(TASK_FULL)
        second = adapter.normalize_task(TASK_FULL)
        self.assertEqual(canonical_bytes(first.payload), canonical_bytes(second.payload))


class MathValidateClaimTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = MathAdapter()
        self.contract_decide = self.adapter.build_evaluation_contract(CASE_DECIDE)

    def test_proof_with_certificate_suggests_supported(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_PROOF, [EVIDENCE_CERTIFICATE], self.contract_decide
        )
        self.assertIsInstance(assessment, ClaimAssessment)
        self.assertEqual(assessment.suggested_claim_type, "mathematical_claim")
        self.assertEqual(assessment.suggested_disposition, "supported")
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "mathematically_verified"
        )
        self.assertIn("certificate-class-evidence-present", assessment.triggered_rules)

    def test_proof_with_numeric_only_is_blocked(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_PROOF, [EVIDENCE_NUMERIC], self.contract_decide
        )
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertEqual(assessment.evidence_maturity_ceiling, "engineering_verified")
        self.assertIn("numeric-evidence-ceiling", assessment.triggered_rules)
        self.assertIn("global-claim-requires-certificate", assessment.triggered_rules)
        self.assertIn("numeric-extrapolation-as-proof", " ".join(assessment.reasons))

    def test_below_case_promotion_bar_is_flagged(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_PROOF, [EVIDENCE_NUMERIC], self.contract_decide
        )
        self.assertIn("below-case-promotion-bar", assessment.triggered_rules)

    def test_non_math_path_bar_fails_closed(self) -> None:
        # R24 regression: a mathematical_claim bar outside the math path
        # (e.g. production_observed) must fail closed, never report a false
        # "meets the case promotion bar".
        for bad_bar in ("production_observed", "data_accepted"):
            contract = EvaluationContract.from_payload(
                {
                    "schema": "evaluation-contract/v1",
                    "case_sha256": canonical_sha256(CASE_DECIDE),
                    "required_evidence": [
                        {"claim_type": "mathematical_claim", "min_maturity": bad_bar}
                    ],
                    "forbidden_channels": ["numeric-extrapolation-as-proof"],
                    "checkpoints": [],
                }
            )
            with self.subTest(bar=bad_bar):
                with self.assertRaises(AdapterError) as ctx:
                    self.adapter.validate_claim(
                        CLAIM_PROOF, [EVIDENCE_NUMERIC], contract
                    )
                self.assertIn("not on the math promotion path", str(ctx.exception))

    def test_bounded_case_bar_is_met_by_numeric_ceiling(self) -> None:
        contract_bounded = self.adapter.build_evaluation_contract(CASE_BOUNDED)
        assessment = self.adapter.validate_claim(
            CLAIM_INCONCLUSIVE, [EVIDENCE_NUMERIC], contract_bounded
        )
        self.assertNotIn("below-case-promotion-bar", assessment.triggered_rules)

    def test_disproof_with_certificate_suggests_refuted(self) -> None:
        claim = dict(CLAIM_PROOF)
        claim["result"] = "disproof"
        assessment = self.adapter.validate_claim(
            claim, [EVIDENCE_CERTIFICATE], self.contract_decide
        )
        self.assertEqual(assessment.suggested_disposition, "refuted")

    def test_disproof_without_certificate_is_inconclusive(self) -> None:
        claim = dict(CLAIM_PROOF)
        claim["result"] = "disproof"
        assessment = self.adapter.validate_claim(
            claim, [EVIDENCE_NUMERIC], self.contract_decide
        )
        self.assertEqual(assessment.suggested_disposition, "inconclusive")

    def test_partial_is_a_legitimate_terminal(self) -> None:
        claim = dict(CLAIM_PROOF)
        claim["result"] = "partial"
        assessment = self.adapter.validate_claim(
            claim, [EVIDENCE_CERTIFICATE], self.contract_decide
        )
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertIn("legitimate terminal", " ".join(assessment.reasons))

    def test_error_discipline(self) -> None:
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim({"schema": "math-claim/v1"}, [], self.contract_decide)
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim(CLAIM_INCONCLUSIVE, {"not": "a list"}, self.contract_decide)
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim(CLAIM_INCONCLUSIVE, ["not-a-dict"], self.contract_decide)
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim(CLAIM_INCONCLUSIVE, [], "not-a-contract")


class MathEvaluationContractTest(unittest.TestCase):
    def test_bounded_case_caps_at_engineering_verified(self) -> None:
        contract = MathAdapter().build_evaluation_contract(CASE_BOUNDED)
        self.assertIsInstance(contract, EvaluationContract)
        self.assertEqual(
            contract.required_evidence,
            [{"claim_type": "mathematical_claim", "min_maturity": "engineering_verified"}],
        )

    def test_decide_case_requires_mathematically_verified(self) -> None:
        for sought_case in (CASE_DECIDE,):
            contract = MathAdapter().build_evaluation_contract(sought_case)
            self.assertEqual(
                contract.required_evidence[0]["min_maturity"],
                "mathematically_verified",
            )

    def test_case_hash_binding(self) -> None:
        contract = MathAdapter().build_evaluation_contract(CASE_BOUNDED)
        self.assertEqual(contract.case_sha256, canonical_sha256(CASE_BOUNDED))

    def test_forbidden_channels_and_checkpoints(self) -> None:
        contract = MathAdapter().build_evaluation_contract(CASE_BOUNDED)
        self.assertEqual(
            set(contract.forbidden_channels),
            {"numeric-extrapolation-as-proof", "llm-consensus-as-proof"},
        )
        self.assertEqual(len(contract.checkpoints), 5)
        self.assertTrue(contract.checkpoints[0].startswith("M0:"))
        self.assertTrue(contract.checkpoints[4].startswith("M4:"))

    def test_invalid_case_fails_structured(self) -> None:
        with self.assertRaises(AdapterError):
            MathAdapter().build_evaluation_contract({"schema": "math-case/v1"})


if __name__ == "__main__":
    unittest.main()
