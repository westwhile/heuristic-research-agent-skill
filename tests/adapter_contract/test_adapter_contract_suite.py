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

A2 landed the skeleton with an empty registry. A3 registered the Math
harness and the window test now pins exactly that; A4 registers the Quant
harness, and A5 replaces the window test with an exact {math, quant}
membership assertion. A registry short of both domains proves nothing by
itself — the window test is what keeps that honest.
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
from research_evolution.adapters.math import MathAdapter
from research_evolution.core import (
    CoreError,
    canonical_bytes,
    load_record,
    load_strict_json,
)


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


# Registered adapter harnesses. A2: empty. A3: Math registered (window test
# below pins exactly this). A4: Quant registers.
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"


def _payload(family: str, kind: str, name: str) -> dict:
    return load_strict_json(
        (_FIXTURES / family / "v1" / kind / name).read_bytes()
    )


MATH_HARNESS = AdapterContractHarness(
    adapter=MathAdapter(),
    valid_domain_input=_payload("math-task", "valid", "full.json"),
    invalid_domain_input=_payload("math-task", "invalid", "missing-quantifiers.json"),
    sample_claim=_payload("math-claim", "valid", "minimal.json"),
    sample_evidence=(_payload("math-evidence", "valid", "minimal.json"),),
    sample_case=_payload("math-case", "valid", "minimal.json"),
    ceiling_probes=(
        CeilingProbe(
            label="proof-with-numeric-only-caps-at-engineering-verified",
            claim=_payload("math-claim", "valid", "full.json"),
            evidence=(_payload("math-evidence", "valid", "minimal.json"),),
            expected_ceiling="engineering_verified",
        ),
        CeilingProbe(
            label="proof-with-certificate-reaches-mathematically-verified",
            claim=_payload("math-claim", "valid", "full.json"),
            evidence=(_payload("math-evidence", "valid", "full.json"),),
            expected_ceiling="mathematically_verified",
        ),
    ),
    expected_forbidden_channels=frozenset(
        {"numeric-extrapolation-as-proof", "llm-consensus-as-proof"}
    ),
)

ADAPTERS: tuple = (MATH_HARNESS,)


class AdapterContractSuite(unittest.TestCase):
    def test_registry_window_math_only(self) -> None:
        # Fail-closed window (A3): math registered, quant pending. A4 adds
        # quant; A5 replaces this with an exact {math, quant} membership
        # assertion (seam-establishment criterion 1 needs BOTH).
        self.assertEqual([harness.adapter.domain for harness in ADAPTERS], ["math"])

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
