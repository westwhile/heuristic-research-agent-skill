"""Unit tests for the Quant adapter mapping and ceiling rules (ADR-0005)."""

import unittest
from pathlib import Path

from research_evolution.adapters import (
    AdapterError,
    ClaimAssessment,
    DomainTask,
    EvaluationContract,
)
from research_evolution.adapters.quant import QuantAdapter
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


TASK_FULL = _payload("quant-task", "valid", "full.json")
CLAIM_ENGINEERING = _payload("quant-claim", "valid", "minimal.json")
CLAIM_OOS = _payload("quant-claim", "valid", "full.json")
CLAIM_REAL_MARKET = {**CLAIM_OOS, "claim_class": "real_market"}
EVIDENCE_SYNTHETIC = _payload("quant-evidence", "valid", "minimal.json")
EVIDENCE_REAL_PIT = _payload("quant-evidence", "valid", "full.json")
EVIDENCE_PRODUCTION = _payload("quant-evidence", "valid", "production-log.json")
CASE_MINIMAL = _payload("quant-case", "valid", "minimal.json")
CASE_FULL = _payload("quant-case", "valid", "full.json")


class QuantNormalizeTaskTest(unittest.TestCase):
    def test_maps_full_input_into_core_draft(self) -> None:
        task = QuantAdapter().normalize_task(TASK_FULL)
        self.assertIsInstance(task, DomainTask)
        self.assertEqual(task.domain, "quant")
        self.assertEqual(task.domain_schema_id, "quant-task/v1")
        draft = task.to_core_task_payload()
        record = load_record(canonical_bytes(draft))
        self.assertEqual(record.schema_id, "research-task/v1")
        self.assertEqual(draft["task_id"], TASK_FULL["task_id"])
        self.assertEqual(draft["domain"], "quant")
        # Caller-injected timestamp passes through; the adapter reads no clock.
        self.assertEqual(draft["created_at"], TASK_FULL["created_at"])
        context = draft["domain_context"]
        self.assertEqual(context["study_id"], TASK_FULL["study_id"])
        self.assertEqual(context["universe"], TASK_FULL["universe"])
        self.assertEqual(context["calendar"], TASK_FULL["calendar"])
        self.assertEqual(context["frequency"], TASK_FULL["frequency"])
        self.assertEqual(context["pit_policy"], TASK_FULL["pit_policy"])
        self.assertEqual(context["data_spec"], TASK_FULL["data_spec"])
        self.assertEqual(context["cost_model"], TASK_FULL["cost_model"])

    def test_invalid_input_fails_structured(self) -> None:
        payload = _payload("quant-task", "invalid", "missing-pit-policy.json")
        with self.assertRaises(AdapterError) as ctx:
            QuantAdapter().normalize_task(payload)
        self.assertNotIsInstance(ctx.exception, CoreError)
        self.assertIn("pit_policy", str(ctx.exception))

    def test_normalize_task_is_pure(self) -> None:
        adapter = QuantAdapter()
        first = adapter.normalize_task(TASK_FULL)
        second = adapter.normalize_task(TASK_FULL)
        self.assertEqual(canonical_bytes(first.payload), canonical_bytes(second.payload))


class QuantValidateClaimTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = QuantAdapter()
        self.contract_full = self.adapter.build_evaluation_contract(CASE_FULL)

    def test_engineering_pass_with_evidence_suggests_supported(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_ENGINEERING, [EVIDENCE_SYNTHETIC], self.contract_full
        )
        self.assertIsInstance(assessment, ClaimAssessment)
        self.assertEqual(assessment.suggested_claim_type, "engineering_claim")
        self.assertEqual(assessment.suggested_disposition, "supported")
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "engineering_verified"
        )

    def test_oos_with_synthetic_only_caps_at_data_accepted(self) -> None:
        # R25 preset: synthetic/sample evidence can never carry an
        # out-of-sample empirical claim past data_accepted.
        assessment = self.adapter.validate_claim(
            CLAIM_OOS, [EVIDENCE_SYNTHETIC], self.contract_full
        )
        self.assertEqual(assessment.suggested_claim_type, "empirical_claim")
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertEqual(assessment.evidence_maturity_ceiling, "data_accepted")
        self.assertIn("synthetic-evidence-cap", assessment.triggered_rules)
        self.assertIn("below-case-promotion-bar", assessment.triggered_rules)
        self.assertIn(
            "synthetic-as-real-data-evidence", " ".join(assessment.reasons)
        )

    def test_oos_with_real_pit_reaches_empirically_supported(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_OOS, [EVIDENCE_REAL_PIT], self.contract_full
        )
        self.assertEqual(assessment.suggested_disposition, "supported")
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "empirically_supported"
        )
        self.assertIn("real-pit-evidence-present", assessment.triggered_rules)
        self.assertNotIn("below-case-promotion-bar", assessment.triggered_rules)

    def test_real_market_with_production_reaches_externally_validated(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_REAL_MARKET, [EVIDENCE_PRODUCTION], self.contract_full
        )
        self.assertEqual(assessment.suggested_claim_type, "strategy_claim")
        self.assertEqual(assessment.suggested_disposition, "supported")
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "externally_validated"
        )
        self.assertIn("production-evidence-present", assessment.triggered_rules)
        self.assertNotIn("below-case-promotion-bar", assessment.triggered_rules)

    def test_real_market_without_production_is_inconclusive(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_REAL_MARKET, [EVIDENCE_REAL_PIT], self.contract_full
        )
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "empirically_supported"
        )
        self.assertIn("backtest-as-live-returns", " ".join(assessment.reasons))

    def test_production_observed_is_never_granted(self) -> None:
        # ADR-0005 decision 4: no evidence class lifts any claim to
        # production_observed through this adapter.
        for claim, evidence in (
            (CLAIM_ENGINEERING, [EVIDENCE_SYNTHETIC]),
            (CLAIM_OOS, [EVIDENCE_REAL_PIT]),
            (CLAIM_REAL_MARKET, [EVIDENCE_PRODUCTION]),
        ):
            with self.subTest(claim_class=claim["claim_class"]):
                assessment = self.adapter.validate_claim(
                    claim, evidence, self.contract_full
                )
                self.assertNotEqual(
                    assessment.evidence_maturity_ceiling, "production_observed"
                )
        assessment = self.adapter.validate_claim(
            CLAIM_REAL_MARKET, [EVIDENCE_PRODUCTION], self.contract_full
        )
        self.assertIn("never granted", " ".join(assessment.reasons))

    def test_kind_provenance_mismatch_fails_closed(self) -> None:
        evidence = dict(EVIDENCE_SYNTHETIC)
        evidence["data_provenance"] = "real_pit"
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_OOS, [evidence], self.contract_full
            )
        self.assertIn("kind/provenance mismatch", str(ctx.exception))

    def test_math_path_bar_fails_closed(self) -> None:
        # R24-symmetric regression: a quant claim-type bar outside the quant
        # path (mathematically_verified) must fail closed, never report a
        # false "meets the case promotion bar".
        contract = EvaluationContract.from_payload(
            {
                "schema": "evaluation-contract/v1",
                "case_sha256": canonical_sha256(CASE_FULL),
                "required_evidence": [
                    {"claim_type": "empirical_claim", "min_maturity": "mathematically_verified"}
                ],
                "forbidden_channels": ["future-function-features"],
                "checkpoints": [],
            }
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(CLAIM_OOS, [EVIDENCE_REAL_PIT], contract)
        self.assertIn("not on the quant promotion path", str(ctx.exception))

    def test_production_bar_is_below_bar_not_an_error(self) -> None:
        # production_observed is on the quant ladder (rank 6) but above every
        # adapter ceiling: the honest report is below-case-promotion-bar.
        contract = EvaluationContract.from_payload(
            {
                "schema": "evaluation-contract/v1",
                "case_sha256": canonical_sha256(CASE_FULL),
                "required_evidence": [
                    {"claim_type": "strategy_claim", "min_maturity": "production_observed"}
                ],
                "forbidden_channels": ["future-function-features"],
                "checkpoints": [],
            }
        )
        assessment = self.adapter.validate_claim(
            CLAIM_REAL_MARKET, [EVIDENCE_PRODUCTION], contract
        )
        self.assertIn("below-case-promotion-bar", assessment.triggered_rules)

    def test_fail_outcome_maps_conservatively(self) -> None:
        claim = dict(CLAIM_OOS)
        claim["outcome"] = "fail"
        assessment = self.adapter.validate_claim(
            claim, [EVIDENCE_REAL_PIT], self.contract_full
        )
        self.assertEqual(assessment.suggested_disposition, "refuted")
        assessment_no_evidence = self.adapter.validate_claim(
            dict(claim), [], self.contract_full
        )
        self.assertEqual(assessment_no_evidence.suggested_disposition, "inconclusive")
        self.assertIn("no-evidence", assessment_no_evidence.triggered_rules)

    def test_inconclusive_is_a_legitimate_terminal(self) -> None:
        claim = dict(CLAIM_OOS)
        claim["outcome"] = "inconclusive"
        assessment = self.adapter.validate_claim(
            claim, [EVIDENCE_REAL_PIT], self.contract_full
        )
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertIn("legitimate terminal", " ".join(assessment.reasons))

    def test_error_discipline(self) -> None:
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim({"schema": "quant-claim/v1"}, [], self.contract_full)
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim(CLAIM_OOS, {"not": "a list"}, self.contract_full)
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim(CLAIM_OOS, ["not-a-dict"], self.contract_full)
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim(CLAIM_OOS, [], "not-a-contract")


class QuantEvaluationContractTest(unittest.TestCase):
    def test_minimal_case_maps_two_gates(self) -> None:
        contract = QuantAdapter().build_evaluation_contract(CASE_MINIMAL)
        self.assertIsInstance(contract, EvaluationContract)
        self.assertEqual(
            contract.required_evidence,
            [
                {"claim_type": "engineering_claim", "min_maturity": "engineering_verified"},
                {"claim_type": "data_claim", "min_maturity": "data_accepted"},
            ],
        )

    def test_full_case_maps_all_four_gates(self) -> None:
        contract = QuantAdapter().build_evaluation_contract(CASE_FULL)
        self.assertEqual(
            contract.required_evidence,
            [
                {"claim_type": "engineering_claim", "min_maturity": "engineering_verified"},
                {"claim_type": "data_claim", "min_maturity": "data_accepted"},
                {"claim_type": "empirical_claim", "min_maturity": "empirically_supported"},
                {"claim_type": "strategy_claim", "min_maturity": "externally_validated"},
            ],
        )

    def test_duplicate_gates_are_deduplicated(self) -> None:
        case = dict(CASE_MINIMAL)
        case["gates"] = ["engineering", "engineering", "data_acceptance"]
        contract = QuantAdapter().build_evaluation_contract(case)
        self.assertEqual(len(contract.required_evidence), 2)

    def test_case_hash_binding(self) -> None:
        contract = QuantAdapter().build_evaluation_contract(CASE_MINIMAL)
        self.assertEqual(contract.case_sha256, canonical_sha256(CASE_MINIMAL))

    def test_forbidden_channels_and_checkpoints(self) -> None:
        contract = QuantAdapter().build_evaluation_contract(CASE_MINIMAL)
        self.assertEqual(
            set(contract.forbidden_channels),
            {
                "future-function-features",
                "non-pit-data",
                "label-without-lead-alignment",
                "backtest-as-live-returns",
                "synthetic-as-real-data-evidence",
            },
        )
        self.assertEqual(len(contract.checkpoints), 6)
        self.assertTrue(contract.checkpoints[0].startswith("Q0:"))
        self.assertTrue(contract.checkpoints[5].startswith("Q5:"))

    def test_invalid_case_fails_structured(self) -> None:
        with self.assertRaises(AdapterError):
            QuantAdapter().build_evaluation_contract(
                _payload("quant-case", "invalid", "empty-gates.json")
            )


if __name__ == "__main__":
    unittest.main()
