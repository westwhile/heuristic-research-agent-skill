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

A2 landed the skeleton with an empty registry; A3/A4 registered the Math
and Quant harnesses behind a fail-closed window test. A5 replaces the
window with the permanent exact-membership assertion and adds the two
remaining seam-establishment probes: the core static purity scan
(criterion 2, decision 8a) and the core deletion subprocess test
(criterion 3, decision 8b). Phase 5 L2 registered the ML harness as the
third member (ADR-0008 decision 2); the membership pin now requires
exactly {math, quant, ml}.
"""

import copy
import os
import re
import subprocess
import sys
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
from research_evolution.adapters.ml import MLAdapter
from research_evolution.adapters.quant import QuantAdapter
from tests.contract.test_core_schemas_contract import _BANNED_TERMS
from research_evolution.core import (
    CoreError,
    canonical_bytes,
    canonical_sha256,
    load_record,
    load_strict_json,
)


@dataclass(frozen=True)
class CeilingProbe:
    """One domain maturity-cap scenario: claim + evidence must be capped.

    ``case`` overrides the harness sample case when the probe's claim is
    hash-bound to a specific case (the ML adapter's claim payload pins its
    case by canonical hash — ADR-0008 addendum A3); None means the harness
    sample case judges the probe.
    """

    label: str
    claim: dict[str, Any]
    evidence: tuple[dict[str, Any], ...]
    expected_ceiling: str
    case: "dict[str, Any] | None" = None


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


# Registered adapter harnesses. A2: empty. A3: Math. A4: Quant. A5: the
# membership assertion below pins this exact set permanently.
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"


def _payload(family: str, kind: str, name: str) -> dict:
    return load_strict_json(
        (_FIXTURES / family / "v1" / kind / name).read_bytes()
    )


def _ml_experiment_v2(name: str) -> dict:
    payload = _payload("ml-evidence", "valid", name)
    case = _payload("ml-case", "valid", "full.json")
    payload["schema"] = "ml-evidence/v2"
    payload["case_sha256"] = canonical_sha256(case)
    payload["final_evaluation"] = {
        "partition": "test",
        "split_sha256": case["split"]["sha256"],
    }
    return payload


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

QUANT_HARNESS = AdapterContractHarness(
    adapter=QuantAdapter(),
    valid_domain_input=_payload("quant-task", "valid", "full.json"),
    invalid_domain_input=_payload("quant-task", "invalid", "missing-pit-policy.json"),
    sample_claim=_payload("quant-claim", "valid", "minimal.json"),
    sample_evidence=(_payload("quant-evidence", "valid", "minimal.json"),),
    sample_case=_payload("quant-case", "valid", "minimal.json"),
    ceiling_probes=(
        CeilingProbe(
            label="oos-empirical-with-synthetic-only-caps-at-data-accepted",
            claim=_payload("quant-claim", "valid", "full.json"),
            evidence=(_payload("quant-evidence", "valid", "minimal.json"),),
            expected_ceiling="data_accepted",
        ),
        CeilingProbe(
            label="oos-empirical-with-real-pit-reaches-empirically-supported",
            claim=_payload("quant-claim", "valid", "full.json"),
            evidence=(_payload("quant-evidence", "valid", "full.json"),),
            expected_ceiling="empirically_supported",
        ),
        CeilingProbe(
            label="real-market-with-production-reaches-externally-validated",
            claim={
                **_payload("quant-claim", "valid", "full.json"),
                "claim_class": "real_market",
            },
            evidence=(_payload("quant-evidence", "valid", "production-log.json"),),
            expected_ceiling="externally_validated",
        ),
    ),
    expected_forbidden_channels=frozenset(
        {
            "future-function-features",
            "non-pit-data",
            "label-without-lead-alignment",
            "backtest-as-live-returns",
            "synthetic-as-real-data-evidence",
        }
    ),
)

ML_HARNESS = AdapterContractHarness(
    adapter=MLAdapter(),
    valid_domain_input=_payload("ml-task", "valid", "full.json"),
    invalid_domain_input=_payload("ml-task", "invalid", "missing-holdout-policy.json"),
    sample_claim=_payload("ml-claim", "valid", "minimal.json"),
    sample_evidence=(_payload("ml-evidence", "valid", "minimal.json"),),
    sample_case=_payload("ml-case", "valid", "minimal.json"),
    ceiling_probes=(
        CeilingProbe(
            label="generalization-with-synthetic-only-caps-at-engineering-verified",
            claim=_payload("ml-claim", "valid", "full.json"),
            evidence=(_ml_experiment_v2("synthetic-experiment.json"),),
            # R42d: the seed/holdout constraints register independently of
            # the provenance cap, so synthetic-only evidence lands at the
            # strictest of the three (single-seed-cap).
            expected_ceiling="engineering_verified",
            # ML claims pin their case by hash (ADR-0008 addendum A3): the
            # generalization probes are judged by the full case's contract.
            case=_payload("ml-case", "valid", "full.json"),
        ),
        CeilingProbe(
            label="generalization-single-seed-caps-at-engineering-verified",
            claim=_payload("ml-claim", "valid", "full.json"),
            evidence=(_ml_experiment_v2("single-seed-experiment.json"),),
            expected_ceiling="engineering_verified",
            case=_payload("ml-case", "valid", "full.json"),
        ),
        CeilingProbe(
            label="generalization-real-multi-seed-frozen-reaches-empirically-supported",
            claim=_payload("ml-claim", "valid", "full.json"),
            evidence=(_ml_experiment_v2("real-experiment.json"),),
            expected_ceiling="empirically_supported",
            case=_payload("ml-case", "valid", "full.json"),
        ),
    ),
    expected_forbidden_channels=frozenset(
        {
            "synthetic-as-real-data-evidence",
            "pre-split-data-preparation",
            "test-set-for-model-selection",
            "holdout-for-tuning",
            "single-seed-best-as-stable-claim",
        }
    ),
)

ADAPTERS: tuple = (MATH_HARNESS, QUANT_HARNESS, ML_HARNESS)


class AdapterContractSuite(unittest.TestCase):
    def test_registry_membership_is_exactly_math_quant_and_ml(self) -> None:
        # Seam-establishment criterion 1 (permanent pin): exactly the Math,
        # Quant, and ML harnesses are registered, and all three pass this
        # one suite. ML joined the suite in Phase 5 L2 (ADR-0008 decision 2)
        # as the third-domain evidence that the seam holds no domain
        # special cases.
        self.assertEqual(len(ADAPTERS), 3)
        self.assertEqual(
            sorted(harness.adapter.domain for harness in ADAPTERS),
            ["math", "ml", "quant"],
        )

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
                for probe in harness.ceiling_probes:
                    case = probe.case if probe.case is not None else harness.sample_case
                    contract = harness.adapter.build_evaluation_contract(
                        copy.deepcopy(case)
                    )
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


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_SRC = _REPO_ROOT / "src" / "research_evolution" / "core"
_DELETION_RUNNER = Path(__file__).resolve().parent / "_core_deletion_runner.py"

# Test files that legitimately couple to research_evolution.adapters. Any
# OTHER test file under tests/unit or tests/contract importing the adapters
# package is domain complexity leaking back toward the core and fails here.
# (The adapter schema contract test imports only the core engine — it tests
# schemas, not adapter code — so it belongs to the core partition and keeps
# passing with the adapters package deleted.)
_ADAPTER_COUPLED_TESTS = frozenset(
    {
        "tests/unit/test_adapters_types.py",
        "tests/unit/test_dl_manifest.py",
        "tests/unit/test_dl_pytorch_observation.py",
        "tests/unit/test_dl_pytorch_recovery.py",
        "tests/unit/test_dl_runner.py",
        "tests/unit/test_dl_runner_l3.py",
        "tests/unit/test_dl_selection.py",
        "tests/unit/test_dl_studies.py",
        "tests/unit/test_math_adapter.py",
        "tests/unit/test_math_importer.py",
        "tests/unit/test_ml_adapter.py",
        "tests/unit/test_ml_final_evaluation.py",
        "tests/unit/test_ml_runner.py",
        "tests/unit/test_ml_split_execution.py",
        "tests/unit/test_ml_topology.py",
        "tests/unit/test_quant_adapter.py",
    }
)


class CoreStaticPurityTest(unittest.TestCase):
    """Seam-establishment criterion 2 (ADR-0005 decision 8a): the core
    source tree carries no adapter coupling and no domain vocabulary."""

    def test_core_source_never_mentions_adapters(self) -> None:
        for path in sorted(_CORE_SRC.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                match = re.search(r"\badapters\b", text)
                self.assertIsNone(
                    match,
                    f"adapter coupling in core source {path.name}"
                    if match
                    else "",
                )

    def test_core_source_is_domain_neutral(self) -> None:
        # Same banned-vocabulary discipline as the core schema scan
        # (tests/contract/test_core_schemas_contract.py:_BANNED_TERMS),
        # extended to core source per ADR-0005 decision 8a.
        for path in sorted(_CORE_SRC.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                match = _BANNED_TERMS.search(text)
                self.assertIsNone(
                    match,
                    f"domain term {match.group(0)!r} in core source {path.name}"
                    if match
                    else "",
                )


class CoreDeletionTest(unittest.TestCase):
    """Seam-establishment criterion 3 (ADR-0005 decision 8b): with the
    adapters package made unimportable, the core test suite passes
    byte-identical and unmodified."""

    @staticmethod
    def _partition() -> tuple[list[str], set[str]]:
        coupled: set[str] = set()
        core_modules: list[str] = []
        for tree in ("tests/unit", "tests/contract"):
            for path in sorted((_REPO_ROOT / tree).glob("test_*.py")):
                relative = path.relative_to(_REPO_ROOT).as_posix()
                imports_adapters = any(
                    "adapters" in line
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.startswith(("import ", "from "))
                )
                if imports_adapters:
                    coupled.add(relative)
                else:
                    core_modules.append(relative[:-3].replace("/", "."))
        return core_modules, coupled

    def test_adapter_coupling_is_exactly_the_known_set(self) -> None:
        _, coupled = self._partition()
        self.assertEqual(coupled, _ADAPTER_COUPLED_TESTS)

    def test_core_suite_passes_with_adapters_deleted(self) -> None:
        core_modules, coupled = self._partition()
        self.assertEqual(coupled, _ADAPTER_COUPLED_TESTS)
        env = dict(os.environ)
        env["PYTHONPATH"] = (
            str(_REPO_ROOT) + os.pathsep + str(_REPO_ROOT / "src")
        )
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(_DELETION_RUNNER),
                *core_modules,
            ],
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertIn("BLOCKER-ACTIVE", completed.stdout)
        self.assertEqual(
            completed.returncode,
            0,
            f"core suite failed with adapters deleted:\n{completed.stdout}\n"
            f"{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
