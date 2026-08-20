"""Unit tests for the frozen seam exchange types (ADR-0005 decisions 1-5)."""

import dataclasses
import unittest
from pathlib import Path

import research_evolution.adapters as adapters
from research_evolution.adapters import (
    AdapterError,
    ClaimAssessment,
    DomainAdapter,
    DomainTask,
    EvaluationContract,
)
from research_evolution.core import (
    CoreError,
    canonical_bytes,
    canonical_sha256,
    load_record,
    load_strict_json,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"
CORE_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "core"

EXPECTED_PUBLIC_SURFACE = [
    "AdapterError",
    "ClaimAssessment",
    "DomainAdapter",
    "DomainTask",
    "EvaluationContract",
]


def _fixture_bytes(family: str, name: str) -> bytes:
    return (FIXTURES / family / "v1" / "valid" / name).read_bytes()


class AdapterPublicSurfaceTest(unittest.TestCase):
    def test_all_is_pinned(self) -> None:
        self.assertEqual(adapters.__all__, EXPECTED_PUBLIC_SURFACE)
        for name in EXPECTED_PUBLIC_SURFACE:
            self.assertTrue(hasattr(adapters, name), name)

    def test_core_surface_is_untouched(self) -> None:
        import research_evolution.core as core

        self.assertEqual(len(core.__all__), 18)


class DomainTaskTest(unittest.TestCase):
    def test_full_fixture_accessors_and_hash(self) -> None:
        raw = _fixture_bytes("domain-task", "full.json")
        task = DomainTask.from_json(raw)
        self.assertEqual(task.domain, "math")
        self.assertEqual(task.domain_schema_id, "math-task/v1")
        self.assertEqual(task.sha256, canonical_sha256(load_strict_json(raw)))
        self.assertEqual(task.payload["core_task_draft"]["domain"], "math")

    def test_core_task_draft_loads_as_research_task(self) -> None:
        task = DomainTask.from_json(_fixture_bytes("domain-task", "full.json"))
        record = load_record(canonical_bytes(task.to_core_task_payload()))
        self.assertEqual(record.schema_id, "research-task/v1")

    def test_from_payload_matches_from_json(self) -> None:
        raw = _fixture_bytes("domain-task", "minimal.json")
        self.assertEqual(
            DomainTask.from_payload(load_strict_json(raw)).sha256,
            DomainTask.from_json(raw).sha256,
        )

    def test_construction_is_pure(self) -> None:
        raw = _fixture_bytes("domain-task", "full.json")
        self.assertEqual(
            DomainTask.from_json(raw).sha256, DomainTask.from_json(raw).sha256
        )

    def test_input_mutation_does_not_reach_the_instance(self) -> None:
        payload = load_strict_json(_fixture_bytes("domain-task", "full.json"))
        task = DomainTask.from_payload(payload)
        before = task.sha256
        payload["domain"] = "quant"
        payload["domain_payload"]["injected"] = True
        payload["core_task_draft"]["task_id"] = "mutated"
        self.assertEqual(task.sha256, before)
        self.assertEqual(task.domain, "math")
        self.assertNotIn("injected", task.domain_payload)

    def test_returned_payload_mutation_does_not_reach_the_instance(self) -> None:
        task = DomainTask.from_json(_fixture_bytes("domain-task", "full.json"))
        before = task.sha256
        task.payload["domain"] = "quant"
        task.to_core_task_payload()["task_id"] = "mutated"
        self.assertEqual(task.sha256, before)
        self.assertEqual(task.domain, "math")

    def test_frozen(self) -> None:
        task = DomainTask.from_json(_fixture_bytes("domain-task", "minimal.json"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            task._record = None

    def test_invalid_payload_fails_as_adapter_error(self) -> None:
        with self.assertRaises(AdapterError) as ctx:
            DomainTask.from_payload({"schema": "domain-task/v1", "domain": "math"})
        self.assertNotIsInstance(ctx.exception, CoreError)
        self.assertIsInstance(ctx.exception.__cause__, CoreError)
        self.assertGreater(len(ctx.exception.details), 0)

    def test_wrong_seam_schema_fails_as_adapter_error(self) -> None:
        with self.assertRaises(AdapterError) as ctx:
            DomainTask.from_json(_fixture_bytes("claim-assessment", "minimal.json"))
        self.assertIn("expected one of", str(ctx.exception))

    def test_v2_payload_is_accepted(self) -> None:
        # ADR-0008 L2 addendum: the v2 seam version carries the ml domain.
        task = DomainTask.from_json(
            (FIXTURES / "domain-task" / "v2" / "valid" / "minimal.json").read_bytes()
        )
        self.assertEqual(task.domain, "ml")
        self.assertEqual(task.domain_schema_id, "ml-task/v1")

    def test_v1_payload_remains_accepted(self) -> None:
        # The frozen v1 stays live for the math/quant producers.
        task = DomainTask.from_json(_fixture_bytes("domain-task", "minimal.json"))
        self.assertEqual(task.domain, "math")

    def test_unknown_future_version_fails_closed(self) -> None:
        payload = load_strict_json(
            (FIXTURES / "domain-task" / "v2" / "valid" / "minimal.json").read_bytes()
        )
        payload["schema"] = "domain-task/v3"
        with self.assertRaises(AdapterError):
            DomainTask.from_payload(payload)

    def test_v2_rejects_unlisted_domain(self) -> None:
        # dl is deliberately NOT in the v2 vocabulary (Phase 6 will need its
        # own governed schema version).
        with self.assertRaises(AdapterError) as ctx:
            DomainTask.from_json(
                (FIXTURES / "domain-task" / "v2" / "invalid" / "bad-domain.json").read_bytes()
            )
        self.assertIn("domain-task/v2", str(ctx.exception))

    def test_direct_construction_with_foreign_record_fails(self) -> None:
        core_record = load_record(
            (CORE_FIXTURES / "research-task/v1/valid/minimal.json").read_bytes()
        )
        with self.assertRaises(AdapterError):
            DomainTask(core_record)


class ClaimAssessmentTest(unittest.TestCase):
    def test_accessors(self) -> None:
        assessment = ClaimAssessment.from_json(
            _fixture_bytes("claim-assessment", "full.json")
        )
        self.assertEqual(assessment.suggested_claim_type, "empirical_claim")
        self.assertEqual(assessment.suggested_disposition, "supported")
        self.assertEqual(assessment.evidence_maturity_ceiling, "data_accepted")
        self.assertEqual(len(assessment.reasons), 2)
        self.assertEqual(
            assessment.triggered_rules, ["synthetic-data-ceiling", "pit-alignment-check"]
        )

    def test_ceiling_is_schema_enumerated(self) -> None:
        payload = load_strict_json(_fixture_bytes("claim-assessment", "minimal.json"))
        payload["evidence_maturity_ceiling"] = "production_ready"
        with self.assertRaises(AdapterError):
            ClaimAssessment.from_payload(payload)


class EvaluationContractTest(unittest.TestCase):
    def test_accessors(self) -> None:
        contract = EvaluationContract.from_json(
            _fixture_bytes("evaluation-contract", "full.json")
        )
        self.assertEqual(len(contract.case_sha256), 64)
        self.assertEqual(
            [entry["claim_type"] for entry in contract.required_evidence],
            ["engineering_claim", "data_claim", "empirical_claim"],
        )
        self.assertIn("future-function-features", contract.forbidden_channels)
        self.assertTrue(any(q.startswith("Q4:") for q in contract.checkpoints))

    def test_hash_binds_payload(self) -> None:
        raw = _fixture_bytes("evaluation-contract", "minimal.json")
        contract = EvaluationContract.from_json(raw)
        self.assertEqual(contract.sha256, canonical_sha256(load_strict_json(raw)))

    def test_v2_payload_is_accepted(self) -> None:
        # ADR-0008 addendum A3: v2 adds the study/assessment binding surface
        # while v1 stays live for the math/quant producers.
        contract = EvaluationContract.from_json(
            (FIXTURES / "evaluation-contract" / "v2" / "valid" / "minimal.json").read_bytes()
        )
        self.assertEqual(len(contract.case_sha256), 64)
        self.assertEqual(contract.payload["study_id"], "synthetic-ml-study-001")
        self.assertEqual(len(contract.payload["assessment_declaration"]), 4)

    def test_unknown_future_version_fails_closed(self) -> None:
        payload = load_strict_json(
            (FIXTURES / "evaluation-contract" / "v2" / "valid" / "minimal.json").read_bytes()
        )
        payload["schema"] = "evaluation-contract/v3"
        with self.assertRaises(AdapterError):
            EvaluationContract.from_payload(payload)


class DomainAdapterContractTest(unittest.TestCase):
    def test_incomplete_adapter_cannot_instantiate(self) -> None:
        class _Incomplete(DomainAdapter):
            pass

        with self.assertRaises(TypeError):
            _Incomplete()

    def test_minimal_concrete_adapter_instantiates(self) -> None:
        class _Fake(DomainAdapter):
            @property
            def domain(self) -> str:
                return "math"

            def normalize_task(self, domain_input):
                return DomainTask.from_json(
                    _fixture_bytes("domain-task", "minimal.json")
                )

            def validate_claim(self, claim, evidence, contract):
                return ClaimAssessment.from_json(
                    _fixture_bytes("claim-assessment", "minimal.json")
                )

            def build_evaluation_contract(self, case):
                return EvaluationContract.from_json(
                    _fixture_bytes("evaluation-contract", "minimal.json")
                )

        fake = _Fake()
        self.assertEqual(fake.domain, "math")
        self.assertIsInstance(fake.normalize_task({}), DomainTask)
        self.assertIsInstance(fake.validate_claim({}, (), None), ClaimAssessment)
        self.assertIsInstance(fake.build_evaluation_contract({}), EvaluationContract)


if __name__ == "__main__":
    unittest.main()
