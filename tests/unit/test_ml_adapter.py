"""Unit tests for the ML adapter mapping and ceiling rules (ADR-0008)."""

import unittest
from pathlib import Path

from research_evolution.adapters import (
    AdapterError,
    ClaimAssessment,
    DomainTask,
    EvaluationContract,
)
from research_evolution.adapters.ml import MLAdapter
from research_evolution.core import (
    CoreError,
    canonical_bytes,
    canonical_sha256,
    load_record,
    load_strict_json,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"
ADAPTER_SCHEMA_ROOT = (
    Path(__file__).resolve().parents[2] / "schemas" / "adapters"
)


def _payload(family: str, kind: str, name: str) -> dict:
    return load_strict_json((FIXTURES / family / "v1" / kind / name).read_bytes())


def _v2_contract(case: dict, required_evidence: list) -> EvaluationContract:
    """Hand-built evaluation-contract/v2 bound to *case* (hash + study)."""
    return EvaluationContract.from_payload(
        {
            "schema": "evaluation-contract/v2",
            "case_sha256": canonical_sha256(case),
            "study_id": case["study_id"],
            "required_evidence": required_evidence,
            "forbidden_channels": ["synthetic-as-real-data-evidence"],
            "checkpoints": [],
            "assessment_declaration": [
                {"dimension": dimension, "status": section["status"]}
                for dimension, section in case["assessment"].items()
            ],
        }
    )


TASK_FULL = _payload("ml-task", "valid", "full.json")
CLAIM_ENGINEERING = _payload("ml-claim", "valid", "minimal.json")
CLAIM_DATA = _payload("ml-claim", "valid", "data-acceptance.json")
CLAIM_GENERALIZATION = _payload("ml-claim", "valid", "full.json")
EVIDENCE_UNIT_TEST = _payload("ml-evidence", "valid", "minimal.json")
EVIDENCE_SYNTHETIC_RUN = _payload("ml-evidence", "valid", "synthetic-experiment.json")
EVIDENCE_SINGLE_SEED = _payload("ml-evidence", "valid", "single-seed-experiment.json")
EVIDENCE_REAL_RUN = _payload("ml-evidence", "valid", "real-experiment.json")
EVIDENCE_PUBLIC_RUN = _payload("ml-evidence", "valid", "full.json")
EVIDENCE_CALIBRATION = _payload("ml-evidence", "valid", "calibration.json")
EVIDENCE_SUBGROUP = _payload("ml-evidence", "valid", "subgroup.json")
EVIDENCE_OOD = _payload("ml-evidence", "valid", "ood.json")
EVIDENCE_DRIFT = _payload("ml-evidence", "valid", "drift.json")
EVIDENCE_DATA_AUDIT = _payload("ml-evidence", "valid", "data-audit.json")
EVIDENCE_OTHER = _payload("ml-evidence", "valid", "other.json")
EVIDENCE_DUPLICATE_SEEDS = _payload(
    "ml-evidence", "valid", "duplicate-seeds-experiment.json"
)
CASE_MINIMAL = _payload("ml-case", "valid", "minimal.json")
CASE_FULL = _payload("ml-case", "valid", "full.json")

ALL_ASSESSMENTS = (
    EVIDENCE_CALIBRATION,
    EVIDENCE_SUBGROUP,
    EVIDENCE_OOD,
    EVIDENCE_DRIFT,
)

# The frozen claim-assessment/v1 surface (ADR-0008 decision 4: the five
# fields are the whole channel — no assessment/limitations field may be
# added without an interface v2 successor). The payload also carries the
# ``schema`` tag, which the pin below subtracts before comparing.
CLAIM_ASSESSMENT_FIELDS = frozenset(
    {
        "suggested_claim_type",
        "suggested_disposition",
        "evidence_maturity_ceiling",
        "reasons",
        "triggered_rules",
    }
)


class MLNormalizeTaskTest(unittest.TestCase):
    def test_maps_full_input_into_core_draft(self) -> None:
        task = MLAdapter().normalize_task(TASK_FULL)
        self.assertIsInstance(task, DomainTask)
        self.assertEqual(task.domain, "ml")
        self.assertEqual(task.domain_schema_id, "ml-task/v1")
        # The ml domain label rides the v2 seam version (ADR-0008 L2
        # addendum); v1 stays frozen for the math/quant producers.
        self.assertEqual(task.payload["schema"], "domain-task/v2")
        draft = task.to_core_task_payload()
        record = load_record(canonical_bytes(draft))
        self.assertEqual(record.schema_id, "research-task/v1")
        self.assertEqual(draft["task_id"], TASK_FULL["task_id"])
        self.assertEqual(draft["domain"], "ml")
        # Caller-injected timestamp passes through; the adapter reads no clock.
        self.assertEqual(draft["created_at"], TASK_FULL["created_at"])
        context = draft["domain_context"]
        self.assertEqual(context["study_id"], TASK_FULL["study_id"])
        self.assertEqual(context["task_type"], TASK_FULL["task_type"])
        self.assertEqual(context["data_spec"], TASK_FULL["data_spec"])
        self.assertEqual(context["holdout_policy"], TASK_FULL["holdout_policy"])

    def test_invalid_input_fails_structured(self) -> None:
        payload = _payload("ml-task", "invalid", "missing-holdout-policy.json")
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().normalize_task(payload)
        self.assertNotIsInstance(ctx.exception, CoreError)
        self.assertIn("holdout_policy", str(ctx.exception))

    def test_normalize_task_is_pure(self) -> None:
        adapter = MLAdapter()
        first = adapter.normalize_task(TASK_FULL)
        second = adapter.normalize_task(TASK_FULL)
        self.assertEqual(canonical_bytes(first.payload), canonical_bytes(second.payload))


class MLValidateClaimTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = MLAdapter()
        # Claims pin their case by canonical hash (ADR-0008 addendum A3):
        # the engineering/data claims answer CASE_MINIMAL, the
        # generalization claim answers CASE_FULL.
        self.contract_full = self.adapter.build_evaluation_contract(CASE_FULL)
        self.contract_minimal = self.adapter.build_evaluation_contract(CASE_MINIMAL)

    def test_engineering_pass_with_evidence_suggests_supported(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_ENGINEERING, [EVIDENCE_UNIT_TEST], self.contract_minimal
        )
        self.assertIsInstance(assessment, ClaimAssessment)
        self.assertEqual(assessment.suggested_claim_type, "engineering_claim")
        self.assertEqual(assessment.suggested_disposition, "supported")
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "engineering_verified"
        )

    def test_data_acceptance_caps_at_data_accepted(self) -> None:
        # A data-acceptance claim is supported only by data_audit_report
        # evidence (ADR-0008 addendum A2 relevant-kinds matrix).
        assessment = self.adapter.validate_claim(
            CLAIM_DATA, [EVIDENCE_DATA_AUDIT], self.contract_minimal
        )
        self.assertEqual(assessment.suggested_claim_type, "data_claim")
        self.assertEqual(assessment.suggested_disposition, "supported")
        self.assertEqual(assessment.evidence_maturity_ceiling, "data_accepted")

    def test_generalization_with_synthetic_only_caps_at_engineering_verified(self) -> None:
        # Synthetic evidence can never carry a generalization claim past
        # data_accepted (forbidden channel synthetic-as-real-data-evidence).
        # R42d: the seed/holdout constraints are no longer nested behind the
        # provenance check — with no public/real experiment the missing
        # repeated-seed record also registers, pulling the ceiling to
        # engineering_verified (strictest of the three).
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [EVIDENCE_SYNTHETIC_RUN], self.contract_full
        )
        self.assertEqual(assessment.suggested_claim_type, "empirical_claim")
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "engineering_verified"
        )
        self.assertIn("synthetic-evidence-cap", assessment.triggered_rules)
        self.assertIn("single-seed-cap", assessment.triggered_rules)
        self.assertIn("frozen-holdout-missing", assessment.triggered_rules)
        self.assertIn("below-case-promotion-bar", assessment.triggered_rules)
        self.assertIn(
            "synthetic-as-real-data-evidence", " ".join(assessment.reasons)
        )

    def test_unit_test_only_evidence_is_not_experiment_backing(self) -> None:
        # Supporting kinds never lift a generalization claim by themselves.
        # R42d: with zero public/real experiments all three ceiling
        # constraints register; the strictest (single-seed-cap) binds.
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [EVIDENCE_UNIT_TEST], self.contract_full
        )
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "engineering_verified"
        )
        self.assertIn("synthetic-evidence-cap", assessment.triggered_rules)

    def test_generalization_with_real_multi_seed_frozen_reaches_supported(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], self.contract_full
        )
        self.assertEqual(assessment.suggested_disposition, "supported")
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "empirically_supported"
        )
        self.assertNotIn("below-case-promotion-bar", assessment.triggered_rules)

    def test_single_seed_caps_at_engineering_verified(self) -> None:
        # Acceptance gate, verbatim: a single-seed best value cannot support
        # a stable claim.
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [EVIDENCE_SINGLE_SEED], self.contract_full
        )
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "engineering_verified"
        )
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertIn("single-seed-cap", assessment.triggered_rules)
        self.assertIn(
            "single-seed-best-as-stable-claim", " ".join(assessment.reasons)
        )

    def test_unfrozen_multi_seed_caps_at_data_accepted(self) -> None:
        unfrozen = dict(EVIDENCE_REAL_RUN)
        unfrozen["frozen_holdout"] = False
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [unfrozen], self.contract_full
        )
        self.assertEqual(assessment.evidence_maturity_ceiling, "data_accepted")
        self.assertIn("frozen-holdout-missing", assessment.triggered_rules)

    def test_missing_ood_and_subgroup_are_named_without_moving_the_ceiling(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], self.contract_full
        )
        self.assertIn("ood-assessment-missing", assessment.triggered_rules)
        self.assertIn("subgroup-assessment-missing", assessment.triggered_rules)
        self.assertIn("calibration-not-assessed", assessment.triggered_rules)
        self.assertIn("drift-not-assessed", assessment.triggered_rules)
        # The ceiling is not moved by the missing evaluations.
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "empirically_supported"
        )

    def test_full_assessment_coverage_silences_the_gap_rules(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION,
            [EVIDENCE_REAL_RUN, *ALL_ASSESSMENTS],
            self.contract_full,
        )
        for rule in (
            "ood-assessment-missing",
            "subgroup-assessment-missing",
            "calibration-not-assessed",
            "drift-not-assessed",
        ):
            self.assertNotIn(rule, assessment.triggered_rules)
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "empirically_supported"
        )

    def test_gap_rules_do_not_fire_for_engineering_claims(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_ENGINEERING, [EVIDENCE_UNIT_TEST], self.contract_minimal
        )
        for rule in (
            "ood-assessment-missing",
            "subgroup-assessment-missing",
            "calibration-not-assessed",
            "drift-not-assessed",
        ):
            self.assertNotIn(rule, assessment.triggered_rules)

    def test_assessment_payload_has_exactly_the_frozen_five_fields(self) -> None:
        for claim, evidence, contract in (
            (CLAIM_ENGINEERING, [EVIDENCE_UNIT_TEST], self.contract_minimal),
            (CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], self.contract_full),
            (CLAIM_GENERALIZATION, [], self.contract_full),
        ):
            with self.subTest(claim_class=claim["claim_class"], evidence=len(evidence)):
                assessment = self.adapter.validate_claim(
                    claim, evidence, contract
                )
                self.assertEqual(
                    set(assessment.payload) - {"schema"},
                    CLAIM_ASSESSMENT_FIELDS,
                )

    def test_externally_validated_and_production_observed_never_granted(self) -> None:
        # No evidence class lifts any claim past empirically_supported
        # through this adapter.
        for claim, evidence, contract in (
            (CLAIM_ENGINEERING, [EVIDENCE_UNIT_TEST], self.contract_minimal),
            (CLAIM_DATA, [EVIDENCE_REAL_RUN], self.contract_minimal),
            (CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], self.contract_full),
        ):
            with self.subTest(claim_class=claim["claim_class"]):
                assessment = self.adapter.validate_claim(
                    claim, evidence, contract
                )
                self.assertNotIn(
                    assessment.evidence_maturity_ceiling,
                    ("externally_validated", "production_observed"),
                )

    def test_math_path_bar_fails_closed(self) -> None:
        # A bar outside the ML promotion path (mathematically_verified) must
        # fail closed, never report a false "meets the case promotion bar".
        contract = _v2_contract(
            CASE_FULL,
            [
                {"claim_type": "empirical_claim", "min_maturity": "mathematically_verified"}
            ],
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract)
        self.assertIn("not on the ml promotion path", str(ctx.exception))

    def test_production_bar_is_below_bar_not_an_error(self) -> None:
        # production_observed is on the governance ladder (rank 6) but above
        # every adapter ceiling: the honest report is below-case-promotion-bar.
        contract = _v2_contract(
            CASE_FULL,
            [
                {"claim_type": "empirical_claim", "min_maturity": "production_observed"}
            ],
        )
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
        )
        self.assertIn("below-case-promotion-bar", assessment.triggered_rules)

    def test_fail_outcome_maps_conservatively(self) -> None:
        claim = dict(CLAIM_GENERALIZATION)
        claim["outcome"] = "fail"
        assessment = self.adapter.validate_claim(
            claim, [EVIDENCE_REAL_RUN], self.contract_full
        )
        self.assertEqual(assessment.suggested_disposition, "refuted")
        assessment_no_evidence = self.adapter.validate_claim(
            dict(claim), [], self.contract_full
        )
        self.assertEqual(assessment_no_evidence.suggested_disposition, "inconclusive")
        self.assertIn("no-evidence", assessment_no_evidence.triggered_rules)

    def test_inconclusive_is_a_legitimate_terminal(self) -> None:
        claim = dict(CLAIM_GENERALIZATION)
        claim["outcome"] = "inconclusive"
        assessment = self.adapter.validate_claim(
            claim, [EVIDENCE_REAL_RUN], self.contract_full
        )
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertIn("legitimate terminal", " ".join(assessment.reasons))

    def test_error_discipline(self) -> None:
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim({"schema": "ml-claim/v1"}, [], self.contract_full)
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim(CLAIM_GENERALIZATION, {"not": "a list"}, self.contract_full)
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim(CLAIM_GENERALIZATION, ["not-a-dict"], self.contract_full)
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim(CLAIM_GENERALIZATION, [], "not-a-contract")


class MLEvaluationContractTest(unittest.TestCase):
    def test_minimal_case_maps_two_gates(self) -> None:
        contract = MLAdapter().build_evaluation_contract(CASE_MINIMAL)
        self.assertIsInstance(contract, EvaluationContract)
        # ML contracts ride the v2 seam version (ADR-0008 addendum A3): the
        # binding surface v1 does not carry.
        self.assertEqual(contract.payload["schema"], "evaluation-contract/v2")
        self.assertEqual(contract.payload["study_id"], CASE_MINIMAL["study_id"])
        self.assertEqual(
            contract.required_evidence,
            [
                {"claim_type": "engineering_claim", "min_maturity": "engineering_verified"},
                {"claim_type": "data_claim", "min_maturity": "data_accepted"},
            ],
        )

    def test_full_case_maps_all_three_gates(self) -> None:
        contract = MLAdapter().build_evaluation_contract(CASE_FULL)
        self.assertEqual(
            contract.required_evidence,
            [
                {"claim_type": "engineering_claim", "min_maturity": "engineering_verified"},
                {"claim_type": "data_claim", "min_maturity": "data_accepted"},
                {"claim_type": "empirical_claim", "min_maturity": "empirically_supported"},
            ],
        )

    def test_assessment_declaration_rides_the_contract(self) -> None:
        # The case's assessment section reaches validate_claim through the
        # v2 contract (ADR-0008 addendum A3).
        contract = MLAdapter().build_evaluation_contract(CASE_FULL)
        self.assertEqual(
            contract.payload["assessment_declaration"],
            [
                {
                    "dimension": "calibration",
                    "status": "declared",
                    "detail": "platt-scaling on an in-fold calibration split",
                },
                {"dimension": "subgroup", "status": "declared", "detail": "season"},
                {
                    "dimension": "ood",
                    "status": "declared",
                    "detail": "shifted-seasonality synthetic holdout",
                },
                {
                    "dimension": "drift",
                    "status": "declared",
                    "detail": "population-stability index per feature between train and holdout",
                },
            ],
        )
        minimal = MLAdapter().build_evaluation_contract(CASE_MINIMAL)
        declaration = minimal.payload["assessment_declaration"]
        self.assertEqual([entry["status"] for entry in declaration], ["not_performed"] * 4)
        self.assertTrue(all("detail" not in entry for entry in declaration))

    def test_duplicate_gates_are_deduplicated(self) -> None:
        case = dict(CASE_MINIMAL)
        case["gates"] = ["engineering", "engineering", "data_acceptance"]
        contract = MLAdapter().build_evaluation_contract(case)
        self.assertEqual(len(contract.required_evidence), 2)

    def test_case_hash_binding(self) -> None:
        contract = MLAdapter().build_evaluation_contract(CASE_MINIMAL)
        self.assertEqual(contract.case_sha256, canonical_sha256(CASE_MINIMAL))

    def test_forbidden_channels_and_checkpoints(self) -> None:
        contract = MLAdapter().build_evaluation_contract(CASE_MINIMAL)
        self.assertEqual(
            set(contract.forbidden_channels),
            {
                "synthetic-as-real-data-evidence",
                "pre-split-data-preparation",
                "test-set-for-model-selection",
                "holdout-for-tuning",
                "single-seed-best-as-stable-claim",
            },
        )
        self.assertEqual(len(contract.checkpoints), 7)
        self.assertTrue(contract.checkpoints[0].startswith("M0:"))
        self.assertTrue(contract.checkpoints[6].startswith("M6:"))

    def test_invalid_case_fails_structured(self) -> None:
        with self.assertRaises(AdapterError):
            MLAdapter().build_evaluation_contract(
                _payload("ml-case", "invalid", "empty-gates.json")
            )


class MLR42bRegressionTest(unittest.TestCase):
    """R42 review regressions (ADR-0008 addendum A2). Each test pins one
    fix; every one of them failed or was a false PASS on the first L2
    implementation."""

    def setUp(self) -> None:
        self.adapter = MLAdapter()
        self.contract_full = self.adapter.build_evaluation_contract(CASE_FULL)
        self.contract_minimal = self.adapter.build_evaluation_contract(CASE_MINIMAL)

    def test_duplicate_seeds_do_not_count_as_repetition(self) -> None:
        # R42 P1: seeds=[7,7] reached empirically_supported on the first
        # implementation; repetition is counted by UNIQUE seed.
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [EVIDENCE_DUPLICATE_SEEDS], self.contract_full
        )
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "engineering_verified"
        )
        self.assertIn("single-seed-cap", assessment.triggered_rules)
        # The independent-constraint ledger also names the missing
        # repeated-seed frozen-holdout run.
        self.assertIn("frozen-holdout-missing", assessment.triggered_rules)

    def test_assessment_only_evidence_never_lifts_generalization(self) -> None:
        # R42 P1: a lone OOD assessment reached empirically_supported on the
        # first implementation; assessment kinds only feed the gap rules.
        # R42d: with zero public/real experiments the independent
        # single-seed constraint also registers, so the ceiling is
        # engineering_verified (stricter than the synthetic cap alone).
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [EVIDENCE_OOD], self.contract_full
        )
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "engineering_verified"
        )
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertIn("synthetic-evidence-cap", assessment.triggered_rules)
        # The supplied OOD assessment silences its own gap rule only.
        self.assertNotIn("ood-assessment-missing", assessment.triggered_rules)
        for rule in (
            "subgroup-assessment-missing",
            "calibration-not-assessed",
            "drift-not-assessed",
        ):
            self.assertIn(rule, assessment.triggered_rules)

    def test_foreign_study_evidence_fails_closed(self) -> None:
        foreign = dict(EVIDENCE_REAL_RUN)
        foreign["study_id"] = "someone-elses-study"
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [foreign], self.contract_full
            )
        self.assertIn("study_id", str(ctx.exception))

    def test_data_claim_with_other_kind_is_inconclusive(self) -> None:
        # R42 P1: kind=other supported a data-acceptance claim on the first
        # implementation; the relevant-kinds matrix is load-bearing.
        assessment = self.adapter.validate_claim(
            CLAIM_DATA, [EVIDENCE_OTHER], self.contract_minimal
        )
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertIn("no-relevant-evidence", assessment.triggered_rules)

    def test_engineering_claim_with_other_kind_is_inconclusive(self) -> None:
        assessment = self.adapter.validate_claim(
            CLAIM_ENGINEERING, [EVIDENCE_OTHER], self.contract_minimal
        )
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertIn("no-relevant-evidence", assessment.triggered_rules)

    def test_empty_limitations_with_named_gaps_fails_closed(self) -> None:
        # R42 P1: an empty limitations array passed while four assessment
        # gaps were being named.
        claim = dict(CLAIM_GENERALIZATION)
        claim["limitations"] = []
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                claim, [EVIDENCE_REAL_RUN], self.contract_full
            )
        self.assertIn("limitations", str(ctx.exception))

    def test_gap_rules_fire_with_no_evidence_at_all(self) -> None:
        # R42 P1: the gap rules were gated on evidence being present.
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [], self.contract_full
        )
        for rule in (
            "ood-assessment-missing",
            "subgroup-assessment-missing",
            "calibration-not-assessed",
            "drift-not-assessed",
        ):
            self.assertIn(rule, assessment.triggered_rules)

    def test_concurrent_violations_are_all_recorded(self) -> None:
        # R42 P2: single-seed + unfrozen must record BOTH constraints; the
        # strictest ceiling wins.
        single_unfrozen = dict(EVIDENCE_SINGLE_SEED)
        single_unfrozen["frozen_holdout"] = False
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [single_unfrozen], self.contract_full
        )
        self.assertIn("single-seed-cap", assessment.triggered_rules)
        self.assertIn("frozen-holdout-missing", assessment.triggered_rules)
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "engineering_verified"
        )

    def test_generalization_maps_to_empirical_claim_only(self) -> None:
        # R42 P1: predictive_claim was an unreachable dead path. The
        # narrowed adapter never suggests it.
        for claim, evidence, contract in (
            (CLAIM_ENGINEERING, [EVIDENCE_UNIT_TEST], self.contract_minimal),
            (CLAIM_DATA, [EVIDENCE_DATA_AUDIT], self.contract_minimal),
            (CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], self.contract_full),
        ):
            with self.subTest(claim_class=claim["claim_class"]):
                assessment = self.adapter.validate_claim(claim, evidence, contract)
                self.assertIn(
                    assessment.suggested_claim_type,
                    ("engineering_claim", "data_claim", "empirical_claim"),
                )


class MLR42cRegressionTest(unittest.TestCase):
    """R42b-review regressions (ADR-0008 addendum A3). Each test pins one
    fix; every one of them was a wrong answer on the R42b implementation."""

    def setUp(self) -> None:
        self.adapter = MLAdapter()
        self.contract_full = self.adapter.build_evaluation_contract(CASE_FULL)
        self.contract_minimal = self.adapter.build_evaluation_contract(CASE_MINIMAL)

    def test_fail_with_irrelevant_evidence_is_not_refuted(self) -> None:
        # R42b P1-1: the fail direction required only non-empty evidence;
        # both terminal dispositions now require a relevant kind.
        for claim, contract, evidence in (
            (CLAIM_ENGINEERING, self.contract_minimal, [EVIDENCE_OTHER]),
            (CLAIM_DATA, self.contract_minimal, [EVIDENCE_OTHER]),
            (CLAIM_GENERALIZATION, self.contract_full, [EVIDENCE_OOD]),
        ):
            with self.subTest(claim_class=claim["claim_class"]):
                failing = dict(claim)
                failing["outcome"] = "fail"
                assessment = self.adapter.validate_claim(failing, evidence, contract)
                self.assertEqual(assessment.suggested_disposition, "inconclusive")
                self.assertIn("no-relevant-evidence", assessment.triggered_rules)

    def test_claim_case_pin_mismatch_fails_closed(self) -> None:
        # R42b P1-2: a claim must pin the exact case the contract judges.
        tampered = dict(CLAIM_GENERALIZATION)
        tampered["case_sha256"] = canonical_sha256(CASE_MINIMAL)
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                tampered, [EVIDENCE_REAL_RUN], self.contract_full
            )
        self.assertIn("case_sha256", str(ctx.exception))

    def test_foreign_case_contract_fails_closed(self) -> None:
        # R42b P1-2/P1-4 probe: the generalization claim (pinning CASE_FULL)
        # against CASE_MINIMAL's contract is rejected at the binding check.
        with self.assertRaises(AdapterError):
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], self.contract_minimal
            )

    def test_contract_study_mismatch_fails_closed(self) -> None:
        payload = dict(
            _v2_contract(
                CASE_FULL,
                [
                    {
                        "claim_type": "empirical_claim",
                        "min_maturity": "empirically_supported",
                    }
                ],
            ).payload
        )
        payload["study_id"] = "another-study"
        contract = EvaluationContract.from_payload(payload)
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
            )
        self.assertIn("study_id", str(ctx.exception))

    def test_not_performed_dimension_contradicted_by_evidence(self) -> None:
        # CASE_MINIMAL declares every dimension not_performed; supplying an
        # OOD assessment contradicts the declaration (declaration <-> result
        # comparison, both directions).
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_DATA,
                [EVIDENCE_DATA_AUDIT, EVIDENCE_OOD],
                self.contract_minimal,
            )
        self.assertIn("contradicted", str(ctx.exception))

    def test_each_gap_code_is_individually_load_bearing(self) -> None:
        # R42b P1-3: the detected gap set must be a subset of the claim's
        # declared_assessment_gaps; each dimension is checked per gap.
        for missing in ("ood", "subgroup", "calibration", "drift"):
            with self.subTest(missing=missing):
                claim = dict(CLAIM_GENERALIZATION)
                claim["declared_assessment_gaps"] = [
                    gap
                    for gap in ("calibration", "drift", "ood", "subgroup")
                    if gap != missing
                ]
                with self.assertRaises(AdapterError) as ctx:
                    self.adapter.validate_claim(
                        claim, [EVIDENCE_REAL_RUN], self.contract_full
                    )
                self.assertIn(missing, str(ctx.exception))

    def test_contract_without_applicable_bar_fails_closed(self) -> None:
        # R42b P1-4: CASE_FULL's hash and study but no generalization gate.
        contract = _v2_contract(
            CASE_FULL,
            [
                {"claim_type": "engineering_claim", "min_maturity": "engineering_verified"},
                {"claim_type": "data_claim", "min_maturity": "data_accepted"},
            ],
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
            )
        self.assertIn("no applicable bar", str(ctx.exception))

    def test_predictive_only_contract_fails_closed(self) -> None:
        # R42b P1-4: foreign entries are skipped; zero applicable bars then
        # fail closed instead of returning supported.
        contract = _v2_contract(
            CASE_FULL,
            [
                {
                    "claim_type": "predictive_claim",
                    "min_maturity": "empirically_supported",
                }
            ],
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
            )
        self.assertIn("no applicable bar", str(ctx.exception))

    def test_duplicate_applicable_bars_fail_closed(self) -> None:
        contract = _v2_contract(
            CASE_FULL,
            [
                {"claim_type": "empirical_claim", "min_maturity": "empirically_supported"},
                {"claim_type": "empirical_claim", "min_maturity": "engineering_verified"},
            ],
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
            )
        self.assertIn("duplicate bars", str(ctx.exception))

    def test_v1_contract_is_rejected(self) -> None:
        # The ML adapter requires the v2 binding surface.
        v1 = EvaluationContract.from_json(
            (FIXTURES / "evaluation-contract" / "v1" / "valid" / "minimal.json").read_bytes()
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], v1)
        self.assertIn("evaluation-contract/v2", str(ctx.exception))


class MLR42dRegressionTest(unittest.TestCase):
    """R42c/R42d/R42e/R42f-review regressions on the declaration
    completeness floor, its bounded-and-escaped diagnostics, and the
    independent ceiling ledger. Each test pins one fix; every one of them
    was a wrong answer on the corresponding pre-fix implementation."""

    def setUp(self) -> None:
        self.adapter = MLAdapter()
        self.contract_full = self.adapter.build_evaluation_contract(CASE_FULL)

    def _contract_with_declaration(self, declaration: list) -> EvaluationContract:
        """Schema-legal evaluation-contract/v2 bound to CASE_FULL whose
        assessment_declaration is replaced by the probe value. The v2
        schema keeps `dimension` free-form and sets no minItems, so every
        probe below passes schema validation — the adapter floor is the
        only gate (that is the point of the R42c findings)."""
        payload = dict(
            _v2_contract(
                CASE_FULL,
                [
                    {
                        "claim_type": "empirical_claim",
                        "min_maturity": "empirically_supported",
                    }
                ],
            ).payload
        )
        payload["assessment_declaration"] = declaration
        return EvaluationContract.from_payload(payload)

    def test_empty_assessment_declaration_fails_closed(self) -> None:
        # R42c P1-1: an empty declaration silently dropped all four gap
        # rules and still returned supported.
        contract = self._contract_with_declaration([])
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
            )
        self.assertIn("exactly 4", str(ctx.exception))

    def test_partial_assessment_declaration_fails_closed(self) -> None:
        # R42c P1-1: declaring only calibration made the other three gaps
        # vanish from the ledger.
        contract = self._contract_with_declaration(
            [
                {
                    "dimension": "calibration",
                    "status": "declared",
                    "detail": "platt scaling",
                }
            ]
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
            )
        message = str(ctx.exception)
        for missing in ("ood", "subgroup", "drift"):
            self.assertIn(missing, message)

    def test_duplicate_assessment_dimension_fails_closed(self) -> None:
        # Over-length duplicate (5 entries) hits the count fast-reject
        # (R42d: the fast-reject runs before any per-dimension work).
        over_length = self._contract_with_declaration(
            [
                {"dimension": "calibration", "status": "declared"},
                {"dimension": "subgroup", "status": "declared"},
                {"dimension": "ood", "status": "declared"},
                {"dimension": "ood", "status": "not_performed"},
                {"dimension": "drift", "status": "declared"},
            ]
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], over_length
            )
        self.assertIn("carries 5 entries", str(ctx.exception))
        # Exact-length duplicate (4 entries, drift missing) reaches the
        # single-pass duplicate check.
        exact_length = self._contract_with_declaration(
            [
                {"dimension": "calibration", "status": "declared"},
                {"dimension": "subgroup", "status": "declared"},
                {"dimension": "ood", "status": "declared"},
                {"dimension": "ood", "status": "not_performed"},
            ]
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], exact_length
            )
        self.assertIn("more than once", str(ctx.exception))

    def test_oversized_declaration_rejected_with_bounded_error(self) -> None:
        # R42d P1: the v2 schema sets no maxItems, so a schema-legal
        # contract may carry thousands of free-form dimensions. The floor
        # must reject in one pass (no per-item list.count — code-reviewed)
        # and keep the diagnostic bounded instead of expanding the unknown
        # dimension list.
        declaration = [
            {"dimension": f"extra-dimension-{index}", "status": "declared"}
            for index in range(8000)
        ]
        contract = self._contract_with_declaration(declaration)
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
            )
        message = str(ctx.exception)
        self.assertIn("8000", message)
        self.assertLess(len(message), 400)

    def test_oversized_unknown_dimension_has_bounded_error(self) -> None:
        # R42e P1: exactly-4 entries with one 200k-char unknown dimension
        # — schema-legal (no maxLength); the diagnostic must not echo it.
        huge = "x" * 200_000
        contract = self._contract_with_declaration(
            [
                {"dimension": "calibration", "status": "declared"},
                {"dimension": "subgroup", "status": "declared"},
                {"dimension": "ood", "status": "declared"},
                {"dimension": huge, "status": "declared"},
            ]
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
            )
        message = str(ctx.exception)
        self.assertLess(len(message), 500)
        self.assertNotIn(huge, message)
        self.assertIn("unknown: 1 supplied", message)

    def test_oversized_duplicate_dimension_has_bounded_error(self) -> None:
        # R42e P1: exactly-4 entries with a 200k-char dimension repeated —
        # schema-legal; the duplicate diagnostic must not echo it.
        huge = "y" * 200_000
        contract = self._contract_with_declaration(
            [
                {"dimension": "calibration", "status": "declared"},
                {"dimension": "subgroup", "status": "declared"},
                {"dimension": huge, "status": "declared"},
                {"dimension": huge, "status": "not_performed"},
            ]
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
            )
        message = str(ctx.exception)
        self.assertLess(len(message), 500)
        self.assertNotIn(huge, message)
        self.assertIn("more than once", message)

    def test_control_characters_in_unknown_dimension_are_escaped(self) -> None:
        # R42f P1: `^\S+$` excludes whitespace but not ESC/NUL/bidi
        # controls — all three schema-legal inputs must reach the error
        # only as deterministic ascii escapes, never raw.
        for bad in ("\x1b[31mINJECT", "\x00INJECT", "\u202eINJECT"):
            with self.subTest(dimension=ascii(bad)):
                contract = self._contract_with_declaration(
                    [
                        {"dimension": "calibration", "status": "declared"},
                        {"dimension": "subgroup", "status": "declared"},
                        {"dimension": "ood", "status": "declared"},
                        {"dimension": bad, "status": "declared"},
                    ]
                )
                with self.assertRaises(AdapterError) as ctx:
                    self.adapter.validate_claim(
                        CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
                    )
                message = str(ctx.exception)
                self.assertNotIn(bad, message)
                for char in ("\x1b", "\x00", "\u202e"):
                    self.assertNotIn(char, message)

    def test_control_characters_in_duplicate_dimension_are_escaped(self) -> None:
        for bad in ("\x1b[31mINJECT", "\x00INJECT", "\u202eINJECT"):
            with self.subTest(dimension=ascii(bad)):
                contract = self._contract_with_declaration(
                    [
                        {"dimension": "calibration", "status": "declared"},
                        {"dimension": "subgroup", "status": "declared"},
                        {"dimension": bad, "status": "declared"},
                        {"dimension": bad, "status": "not_performed"},
                    ]
                )
                with self.assertRaises(AdapterError) as ctx:
                    self.adapter.validate_claim(
                        CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
                    )
                message = str(ctx.exception)
                self.assertNotIn(bad, message)
                for char in ("\x1b", "\x00", "\u202e"):
                    self.assertNotIn(char, message)

    def test_unknown_assessment_dimension_fails_closed(self) -> None:
        # The free-form `dimension` string is domain-neutral at the schema
        # layer; the ml adapter rejects dimensions it cannot interpret.
        contract = self._contract_with_declaration(
            [
                {"dimension": "calibration", "status": "declared"},
                {"dimension": "subgroup", "status": "declared"},
                {"dimension": "ood", "status": "declared"},
                {"dimension": "fairness", "status": "declared"},
            ]
        )
        with self.assertRaises(AdapterError) as ctx:
            self.adapter.validate_claim(
                CLAIM_GENERALIZATION, [EVIDENCE_REAL_RUN], contract
            )
        self.assertIn("unknown", str(ctx.exception))

    def test_build_produces_exactly_the_four_dimensions(self) -> None:
        # Build-side pin: the contract floor carries each dimension once
        # (the validate-side floor is exercised by the probes above).
        dimensions = [
            entry["dimension"]
            for entry in self.contract_full.payload["assessment_declaration"]
        ]
        self.assertEqual(
            sorted(dimensions), ["calibration", "drift", "ood", "subgroup"]
        )

    def test_independent_constraints_register_for_synthetic_single_seed_unfrozen(
        self,
    ) -> None:
        # R42c P1-2 (the verbatim review probe): synthetic provenance + one
        # seed + unfrozen holdout registered ONLY synthetic-evidence-cap
        # while the seed and holdout checks sat in the provenance
        # else-branch. All three constraints now land on the ledger and the
        # strictest binds — restoring the else-nesting would leave the
        # ceiling at the falsely high data_accepted and fail this test.
        probe = dict(EVIDENCE_SYNTHETIC_RUN)
        probe["seeds"] = [7]
        probe["frozen_holdout"] = False
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [probe], self.contract_full
        )
        for rule in (
            "synthetic-evidence-cap",
            "single-seed-cap",
            "frozen-holdout-missing",
        ):
            self.assertIn(rule, assessment.triggered_rules)
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "engineering_verified"
        )

    def test_constraints_register_with_no_experiment_evidence_at_all(self) -> None:
        # The constraint predicates are vacuously true with an empty
        # public/real experiment record; none of them may be skipped.
        assessment = self.adapter.validate_claim(
            CLAIM_GENERALIZATION, [], self.contract_full
        )
        for rule in (
            "synthetic-evidence-cap",
            "single-seed-cap",
            "frozen-holdout-missing",
        ):
            self.assertIn(rule, assessment.triggered_rules)
        self.assertEqual(
            assessment.evidence_maturity_ceiling, "engineering_verified"
        )


class MLCaseTopologyFixtureTest(unittest.TestCase):
    """The unsafe topology fixtures are schema-legal by design (ADR-0008
    decision 3): they become semantic-rejection positives when the L3
    leakage rules land. This test pins only their structural validity."""

    def test_unsafe_fixtures_load_as_valid_ml_case_payloads(self) -> None:
        names = [
            "unsafe-fit-scope-full-data.json",
            "unsafe-sampling-scope.json",
            "unsafe-scope-upstream-mismatch.json",
            "unsafe-target-encoding.json",
            "unsafe-feature-selection.json",
            "unsafe-tuning-split-test.json",
            "unsafe-tuning-split-future-holdout.json",
            "unsafe-selection-split-test.json",
        ]
        for name in names:
            with self.subTest(fixture=name):
                record = load_record(
                    (FIXTURES / "ml-case" / "v1" / "valid" / name).read_bytes(),
                    schema_root=ADAPTER_SCHEMA_ROOT,
                )
                self.assertEqual(record.schema_id, "ml-case/v1")

    def test_unsafe_fixture_pins_are_internally_consistent(self) -> None:
        # Every unsafe fixture keeps its DAG pins coherent (split points at
        # the dataset) so exactly one semantic rule family fires per fixture
        # when L3 lands — except the upstream-mismatch fixture, whose
        # preprocessing step deliberately pins at the dataset.
        for name in (
            "unsafe-fit-scope-full-data.json",
            "unsafe-sampling-scope.json",
            "unsafe-target-encoding.json",
            "unsafe-feature-selection.json",
            "unsafe-tuning-split-test.json",
            "unsafe-tuning-split-future-holdout.json",
            "unsafe-selection-split-test.json",
        ):
            with self.subTest(fixture=name):
                payload = _payload("ml-case", "valid", name)
                dataset_sha = payload["dataset"]["sha256"]
                self.assertEqual(payload["split"]["input_sha256"], dataset_sha)
        mismatch = _payload("ml-case", "valid", "unsafe-scope-upstream-mismatch.json")
        self.assertEqual(
            mismatch["preprocessing"][0]["input_sha256"],
            mismatch["dataset"]["sha256"],
        )
        self.assertEqual(mismatch["preprocessing"][0]["fit_scope"], "train_only")


if __name__ == "__main__":
    unittest.main()
