"""Phase 2 vertical slices (ADR-0005 decisions 4/5/9; plan Phase 2 gate).

Eight clearly-labelled SYNTHETIC slice cases drive both adapters through the
same end-to-end chain: domain payload -> normalize_task -> core task
validation -> build_evaluation_contract -> validate_claim -> assessment, plus
hash binding of the import/contract artifacts into core research-evidence/v1
payloads. Every case is synthetic-level evidence: no real legacy archive and
no real market data is claimed (reports/baseline/math-research-solve-1.0.1.md;
ADR-0005 decision 9).
"""

import unittest
from pathlib import Path

from research_evolution.adapters.math import (
    MathAdapter,
    import_archive,
    snapshot_tree,
)
from research_evolution.adapters.quant import QuantAdapter
from research_evolution.core import (
    canonical_bytes,
    load_record,
    load_strict_json,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"
ARCHIVE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "math-archives" / "minimal-v8"
)


def _payload(family: str, kind: str, name: str) -> dict:
    return load_strict_json((FIXTURES / family / "v1" / kind / name).read_bytes())


MATH_TASK = _payload("math-task", "valid", "full.json")
MATH_CLAIM_PROOF = _payload("math-claim", "valid", "full.json")
MATH_EVIDENCE_NUMERIC = _payload("math-evidence", "valid", "minimal.json")
MATH_EVIDENCE_CERTIFICATE = _payload("math-evidence", "valid", "full.json")
MATH_CASE_BOUNDED = _payload("math-case", "valid", "minimal.json")
MATH_CASE_DECIDE = _payload("math-case", "valid", "full.json")

QUANT_TASK = _payload("quant-task", "valid", "full.json")
QUANT_CLAIM_ENGINEERING = _payload("quant-claim", "valid", "minimal.json")
QUANT_CLAIM_OOS = _payload("quant-claim", "valid", "full.json")
QUANT_CLAIM_REAL_MARKET = {**QUANT_CLAIM_OOS, "claim_class": "real_market"}
QUANT_EVIDENCE_SYNTHETIC = _payload("quant-evidence", "valid", "minimal.json")
QUANT_EVIDENCE_REAL_PIT = _payload("quant-evidence", "valid", "full.json")
QUANT_EVIDENCE_PRODUCTION = _payload("quant-evidence", "valid", "production-log.json")
QUANT_CASE_MINIMAL = _payload("quant-case", "valid", "minimal.json")
QUANT_CASE_FULL = _payload("quant-case", "valid", "full.json")


class MathVerticalSliceTest(unittest.TestCase):
    """Synthetic archive -> read-only import -> adapter chain -> core binding."""

    def setUp(self) -> None:
        self.adapter = MathAdapter()

    def test_archive_import_is_zero_write_and_hash_bound(self) -> None:
        before = snapshot_tree(ARCHIVE)
        result = import_archive(ARCHIVE)
        after = snapshot_tree(ARCHIVE)
        self.assertEqual(before, after)
        self.assertEqual(len(result.artifacts), 9)
        # The importer's projection binds into a core evidence payload.
        contract = self.adapter.build_evaluation_contract(MATH_CASE_DECIDE)
        evidence_payload = {
            "schema": "research-evidence/v1",
            "evidence_id": "math-slice-evidence-0001",
            "claim_ids": ["math-slice-claim-0001"],
            "producer": {"tool": "math-archive-importer", "version": "1"},
            "inputs": [
                *result.evidence_inputs(),
                {
                    "name": "evaluation-contract",
                    "kind": "config",
                    "sha256": contract.sha256,
                },
            ],
            "generated_at": "2026-08-16T12:00:00Z",
            "content_sha256": result.project_head_sha256,
            "applicability": "synthetic archive slice only",
            "evidence_level": "engineering_verified",
            "limitations": [
                "Synthetic archive fixture; not a real legacy import."
            ],
        }
        record = load_record(canonical_bytes(evidence_payload))
        self.assertEqual(record.schema_id, "research-evidence/v1")

    def test_task_normalization_flows_into_a_valid_core_task(self) -> None:
        task = self.adapter.normalize_task(MATH_TASK)
        record = load_record(canonical_bytes(task.to_core_task_payload()))
        self.assertEqual(record.schema_id, "research-task/v1")
        self.assertEqual(record.data["domain"], "math")

    def test_slice_cases(self) -> None:
        decide = self.adapter.build_evaluation_contract(MATH_CASE_DECIDE)
        bounded = self.adapter.build_evaluation_contract(MATH_CASE_BOUNDED)
        cases = (
            (
                "math-bounded-numeric",
                bounded,
                MATH_CLAIM_PROOF,
                (MATH_EVIDENCE_NUMERIC,),
                "engineering_verified",
                "inconclusive",
            ),
            (
                "math-decide-certificate-proof",
                decide,
                MATH_CLAIM_PROOF,
                (MATH_EVIDENCE_CERTIFICATE,),
                "mathematically_verified",
                "supported",
            ),
            (
                "math-decide-certificate-disproof",
                decide,
                {**MATH_CLAIM_PROOF, "result": "disproof"},
                (MATH_EVIDENCE_CERTIFICATE,),
                "mathematically_verified",
                "refuted",
            ),
            (
                "math-decide-certificate-partial",
                decide,
                {**MATH_CLAIM_PROOF, "result": "partial"},
                (MATH_EVIDENCE_CERTIFICATE,),
                "mathematically_verified",
                "inconclusive",
            ),
        )
        for label, contract, claim, evidence, ceiling, disposition in cases:
            with self.subTest(slice=label):
                assessment = self.adapter.validate_claim(claim, evidence, contract)
                self.assertEqual(assessment.evidence_maturity_ceiling, ceiling)
                self.assertEqual(assessment.suggested_disposition, disposition)


class QuantVerticalSliceTest(unittest.TestCase):
    """Synthetic fixtures -> adapter chain -> core binding (Q-gate ladder)."""

    def setUp(self) -> None:
        self.adapter = QuantAdapter()

    def test_task_normalization_flows_into_a_valid_core_task(self) -> None:
        task = self.adapter.normalize_task(QUANT_TASK)
        record = load_record(canonical_bytes(task.to_core_task_payload()))
        self.assertEqual(record.schema_id, "research-task/v1")
        self.assertEqual(record.data["domain"], "quant")
        self.assertEqual(
            record.data["domain_context"]["pit_policy"], QUANT_TASK["pit_policy"]
        )

    def test_contract_hash_binds_into_core_evidence(self) -> None:
        contract = self.adapter.build_evaluation_contract(QUANT_CASE_FULL)
        evidence_payload = {
            "schema": "research-evidence/v1",
            "evidence_id": "quant-slice-evidence-0001",
            "claim_ids": ["quant-claim-0002"],
            "producer": {"tool": "quant-adapter-slice", "version": "1"},
            "inputs": [
                {
                    "name": "evaluation-contract",
                    "kind": "config",
                    "sha256": contract.sha256,
                },
                {
                    "name": QUANT_EVIDENCE_REAL_PIT["evidence_id"],
                    "kind": "data",
                    "sha256": QUANT_EVIDENCE_REAL_PIT["content_sha256"],
                },
            ],
            "generated_at": "2026-08-16T12:00:00Z",
            "content_sha256": QUANT_EVIDENCE_REAL_PIT["content_sha256"],
            "applicability": "synthetic quant slice only",
            "evidence_level": "empirically_supported",
            "limitations": [
                "Synthetic fixtures; no real market data is claimed."
            ],
        }
        record = load_record(canonical_bytes(evidence_payload))
        self.assertEqual(record.schema_id, "research-evidence/v1")

    def test_slice_cases(self) -> None:
        full = self.adapter.build_evaluation_contract(QUANT_CASE_FULL)
        cases = (
            (
                "quant-engineering-synthetic",
                full,
                QUANT_CLAIM_ENGINEERING,
                (QUANT_EVIDENCE_SYNTHETIC,),
                "engineering_verified",
                "supported",
            ),
            (
                "quant-oos-synthetic-cap",
                full,
                QUANT_CLAIM_OOS,
                (QUANT_EVIDENCE_SYNTHETIC,),
                "data_accepted",
                "inconclusive",
            ),
            (
                "quant-oos-real-pit",
                full,
                QUANT_CLAIM_OOS,
                (QUANT_EVIDENCE_REAL_PIT,),
                "empirically_supported",
                "supported",
            ),
            (
                "quant-real-market-production",
                full,
                QUANT_CLAIM_REAL_MARKET,
                (QUANT_EVIDENCE_PRODUCTION,),
                "externally_validated",
                "supported",
            ),
        )
        for label, contract, claim, evidence, ceiling, disposition in cases:
            with self.subTest(slice=label):
                assessment = self.adapter.validate_claim(claim, evidence, contract)
                self.assertEqual(assessment.evidence_maturity_ceiling, ceiling)
                self.assertEqual(assessment.suggested_disposition, disposition)


if __name__ == "__main__":
    unittest.main()
