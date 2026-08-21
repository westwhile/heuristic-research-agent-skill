"""L4 contract and mutation tests for ML final-evaluation binding."""

import copy
import unittest
from pathlib import Path
from unittest import mock

from research_evolution.adapters import AdapterError, EvaluationContract
from research_evolution.adapters.ml import MLAdapter
from research_evolution.adapters.ml import _evidence
from research_evolution.core import canonical_sha256, load_strict_json

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"


def _fixture(family: str, name: str, *, version: str = "v1") -> dict:
    return load_strict_json(
        (FIXTURES / family / version / "valid" / name).read_bytes()
    )


CASE = _fixture("ml-case", "full.json")
CLAIM = _fixture("ml-claim", "full.json")
EVIDENCE_V1 = _fixture("ml-evidence", "real-experiment.json")


def _evidence_v2(*, case_sha256: str | None = None) -> dict:
    payload = copy.deepcopy(EVIDENCE_V1)
    payload["schema"] = "ml-evidence/v2"
    payload["case_sha256"] = case_sha256 or canonical_sha256(CASE)
    payload["final_evaluation"] = {
        "partition": "test",
        "split_sha256": CASE["split"]["sha256"],
    }
    return payload


class MLFinalEvaluationContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = MLAdapter()
        self.contract = self.adapter.build_evaluation_contract(CASE)

    def test_builder_carries_case_side_selection_and_split_pins(self) -> None:
        payload = self.contract.payload
        self.assertEqual(payload["schema"], "evaluation-contract/v3")
        self.assertEqual(
            payload["selection_partition"], CASE["selection"]["split_used"]
        )
        self.assertEqual(payload["selection_sha256"], CASE["selection"]["sha256"])
        self.assertEqual(payload["split_sha256"], CASE["split"]["sha256"])

    def test_v1_experiment_cannot_support_generalization(self) -> None:
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(CLAIM, [EVIDENCE_V1], self.contract)
        self.assertIn("ml-evidence/v2", str(ctx.exception))

    def test_v2_contract_cannot_judge_current_ml_claim(self) -> None:
        legacy = EvaluationContract.from_json(
            (FIXTURES / "evaluation-contract" / "v2" / "valid" / "full.json").read_bytes()
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(CLAIM, [_evidence_v2()], legacy)
        self.assertIn("evaluation-contract/v3", str(ctx.exception))

    def test_final_evaluation_must_use_protected_partition(self) -> None:
        unsafe = _evidence_v2()
        unsafe["final_evaluation"]["partition"] = "validation"
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(CLAIM, [unsafe], self.contract)
        self.assertIn("final-evaluation-not-protected", str(ctx.exception))

    def test_final_evaluation_must_use_contract_split_pin(self) -> None:
        unsafe = _evidence_v2()
        unsafe["final_evaluation"]["split_sha256"] = "0" * 64
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(CLAIM, [unsafe], self.contract)
        self.assertIn("final-evaluation-split-mismatch", str(ctx.exception))

    def test_experiment_evidence_must_pin_the_contract_case(self) -> None:
        foreign_case = copy.deepcopy(CASE)
        foreign_case["model"]["hyperparameters"]["max_depth"] = 99
        unsafe = _evidence_v2(case_sha256=canonical_sha256(foreign_case))
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(CLAIM, [unsafe], self.contract)
        self.assertIn("final-evaluation-case-mismatch", str(ctx.exception))

    def test_hand_built_contract_cannot_select_on_test(self) -> None:
        payload = self.contract.payload
        payload["selection_partition"] = "test"
        unsafe = EvaluationContract.from_payload(payload)
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(CLAIM, [_evidence_v2()], unsafe)
        self.assertIn("selection-uses-protected-partition", str(ctx.exception))


class MLFinalEvaluationMutationTest(unittest.TestCase):
    """Dropping each real predicate must recreate a false PASS."""

    def setUp(self) -> None:
        self.adapter = MLAdapter()
        self.contract = self.adapter.build_evaluation_contract(CASE)

    def test_selection_predicate_is_load_bearing(self) -> None:
        payload = self.contract.payload
        payload["selection_partition"] = "test"
        unsafe = EvaluationContract.from_payload(payload)
        with mock.patch.object(_evidence, "_SELECTION_CONTRACT_PREDICATES", ()):
            assessment = self.adapter.validate_claim(CLAIM, [_evidence_v2()], unsafe)
        self.assertEqual(assessment.suggested_disposition, "supported")

    def test_case_binding_predicate_is_load_bearing(self) -> None:
        foreign_case = copy.deepcopy(CASE)
        foreign_case["model"]["hyperparameters"]["max_depth"] = 99
        unsafe = _evidence_v2(case_sha256=canonical_sha256(foreign_case))
        weakened = tuple(
            item
            for item in _evidence._FINAL_EVALUATION_PREDICATES
            if item[0] != "final-evaluation-case-mismatch"
        )
        with mock.patch.object(
            _evidence, "_FINAL_EVALUATION_PREDICATES", weakened
        ):
            assessment = self.adapter.validate_claim(
                CLAIM, [unsafe], self.contract
            )
        self.assertEqual(assessment.suggested_disposition, "supported")

    def test_each_final_evaluation_predicate_is_load_bearing(self) -> None:
        probes = {
            "final-evaluation-not-protected": ("partition", "validation"),
            "final-evaluation-split-mismatch": ("split_sha256", "0" * 64),
        }
        original = _evidence._FINAL_EVALUATION_PREDICATES
        for rule_id, (field, value) in probes.items():
            with self.subTest(rule=rule_id):
                unsafe = _evidence_v2()
                unsafe["final_evaluation"][field] = value
                weakened = tuple(item for item in original if item[0] != rule_id)
                with mock.patch.object(
                    _evidence, "_FINAL_EVALUATION_PREDICATES", weakened
                ):
                    assessment = self.adapter.validate_claim(
                        CLAIM, [unsafe], self.contract
                    )
                self.assertEqual(assessment.suggested_disposition, "supported")


if __name__ == "__main__":
    unittest.main()
