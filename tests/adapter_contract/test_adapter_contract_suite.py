"""Single parameterized contract suite for domain adapters (ADR-0005 decision 6).

The SAME suite runs against every registered adapter harness; both the Math
and the Quant adapter passing this one suite is seam-establishment
criterion 1 (of 3: shared suite, core static purity, deletion test).
Per-adapter suites are rejected (ADR-0005 rejected option 6): two suites
would drift, and only one suite is evidence of one contract.

Each registered harness supplies the domain fixtures the generic suite
needs — valid/invalid domain input, a sample claim with evidence, a sample
case, maturity-ceiling probes, and the forbidden channels the domain
contract must enumerate. The suite never hardcodes domain content.

A2 lands the skeleton with an empty registry; the fail-closed window test
below pins that state. A3 registers the Math harness, A4 the Quant harness,
and A5 replaces the window test with an exact {math, quant} membership
assertion. An empty-registry pass proves nothing by itself — the window
test is what keeps that honest.
"""

import copy
import os
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_evolution.adapters import (
    AdapterError,
    ClaimAssessment,
    DomainAdapter,
    DomainTask,
    EvaluationContract,
)
from research_evolution.core import CoreError, canonical_bytes, load_record


@dataclass(frozen=True)
class CeilingProbe:
    """One domain maturity-cap scenario: claim + evidence must be capped."""

    label: str
    claim: dict[str, Any]
    evidence: tuple[dict[str, Any], ...]
    expected_ceiling: str


@dataclass(frozen=True)
class AdapterContractHarness:
    """Everything the shared suite needs to exercise one domain adapter."""

    adapter: DomainAdapter
    valid_domain_input: dict[str, Any]
    invalid_domain_input: dict[str, Any]
    sample_claim: dict[str, Any]
    sample_evidence: tuple[dict[str, Any], ...]
    sample_case: dict[str, Any]
    ceiling_probes: tuple[CeilingProbe, ...] = ()
    expected_forbidden_channels: frozenset = frozenset()


# Registered adapter harnesses. A2: empty (window test below pins this).
# A3: Math registers. A4: Quant registers.
ADAPTERS: tuple = ()


class AdapterContractSuite(unittest.TestCase):
    def test_registry_window_no_adapters_yet(self) -> None:
        # Fail-closed window (A2). Shrink plan: A3 registers math, A4 quant;
        # A5 replaces this with an exact {math, quant} membership assertion.
        self.assertEqual(ADAPTERS, ())

    def test_harness_adapters_implement_the_abc(self) -> None:
        for harness in ADAPTERS:
            with self.subTest(adapter=harness.adapter.domain):
                self.assertIsInstance(harness.adapter, DomainAdapter)

    def test_normalize_task_shape_and_core_draft(self) -> None:
        for harness in ADAPTERS:
            with self.subTest(adapter=harness.adapter.domain):
                task = harness.adapter.normalize_task(
                    copy.deepcopy(harness.valid_domain_input)
                )
                self.assertIsInstance(task, DomainTask)
                self.assertEqual(task.domain, harness.adapter.domain)
                # The mapped draft must validate as a core research-task/v1.
                record = load_record(canonical_bytes(task.to_core_task_payload()))
                self.assertEqual(record.schema_id, "research-task/v1")

    def test_normalize_task_is_pure(self) -> None:
        for harness in ADAPTERS:
            with self.subTest(adapter=harness.adapter.domain):
                first = harness.adapter.normalize_task(
                    copy.deepcopy(harness.valid_domain_input)
                )
                second = harness.adapter.normalize_task(
                    copy.deepcopy(harness.valid_domain_input)
                )
                self.assertEqual(
                    canonical_bytes(first.payload), canonical_bytes(second.payload)
                )

    def test_invalid_domain_input_fails_structured(self) -> None:
        for harness in ADAPTERS:
            with self.subTest(adapter=harness.adapter.domain):
                with self.assertRaises(AdapterError) as ctx:
                    harness.adapter.normalize_task(
                        copy.deepcopy(harness.invalid_domain_input)
                    )
                self.assertNotIsInstance(ctx.exception, CoreError)

    def test_validate_claim_returns_a_suggestion(self) -> None:
        for harness in ADAPTERS:
            with self.subTest(adapter=harness.adapter.domain):
                contract = harness.adapter.build_evaluation_contract(
                    copy.deepcopy(harness.sample_case)
                )
                assessment = harness.adapter.validate_claim(
                    copy.deepcopy(harness.sample_claim),
                    copy.deepcopy(list(harness.sample_evidence)),
                    contract,
                )
                self.assertIsInstance(assessment, ClaimAssessment)
                self.assertGreaterEqual(len(assessment.reasons), 1)

    def test_maturity_ceiling_probes(self) -> None:
        for harness in ADAPTERS:
            with self.subTest(adapter=harness.adapter.domain):
                contract = harness.adapter.build_evaluation_contract(
                    copy.deepcopy(harness.sample_case)
                )
                for probe in harness.ceiling_probes:
                    assessment = harness.adapter.validate_claim(
                        copy.deepcopy(probe.claim),
                        copy.deepcopy(list(probe.evidence)),
                        contract,
                    )
                    self.assertEqual(
                        assessment.evidence_maturity_ceiling,
                        probe.expected_ceiling,
                        probe.label,
                    )

    def test_forbidden_channels_cover_the_harness_declaration(self) -> None:
        for harness in ADAPTERS:
            with self.subTest(adapter=harness.adapter.domain):
                contract = harness.adapter.build_evaluation_contract(
                    copy.deepcopy(harness.sample_case)
                )
                self.assertIsInstance(contract, EvaluationContract)
                self.assertTrue(
                    harness.expected_forbidden_channels.issubset(
                        set(contract.forbidden_channels)
                    ),
                    f"missing forbidden channels: "
                    f"{harness.expected_forbidden_channels - set(contract.forbidden_channels)}",
                )

    def test_operations_have_zero_filesystem_side_effects(self) -> None:
        for harness in ADAPTERS:
            with self.subTest(adapter=harness.adapter.domain):
                with tempfile.TemporaryDirectory() as tmp:
                    previous_cwd = os.getcwd()
                    os.chdir(tmp)
                    try:
                        harness.adapter.normalize_task(
                            copy.deepcopy(harness.valid_domain_input)
                        )
                        contract = harness.adapter.build_evaluation_contract(
                            copy.deepcopy(harness.sample_case)
                        )
                        harness.adapter.validate_claim(
                            copy.deepcopy(harness.sample_claim),
                            copy.deepcopy(list(harness.sample_evidence)),
                            contract,
                        )
                        leftovers = list(Path(tmp).rglob("*"))
                    finally:
                        os.chdir(previous_cwd)
                    self.assertEqual(leftovers, [], "adapter wrote into cwd")


if __name__ == "__main__":
    unittest.main()
