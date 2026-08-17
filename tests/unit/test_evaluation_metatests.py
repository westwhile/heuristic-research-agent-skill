"""Unit tests for the E6 evaluator meta-tests (ADR-0006 decision 9):
known-good/known-bad stable distinction, and the three required mutation
classes — each demonstrated detected against the real E3/E4/E6 machinery,
with a negative control."""

import hashlib
import unittest

from research_evolution.core import canonical_bytes
from research_evolution.evaluation import Envelope, run_replay, runner_identity, scorer_identity
from research_evolution.evaluation.gates import (
    GateConfig,
    assemble_verdict,
    evaluate_gates,
)
from research_evolution.evaluation.metatests import (
    MUTATION_CLASSES,
    known_pair_check,
    mutate_drop_condition,
    mutate_invert_verdict,
    mutate_relax_resource_limit,
    mutation_check,
)
from research_evolution.evaluation.scorers import ScoreEntry

ENVELOPE = Envelope(timeout_ms=1000, max_output_bytes=1024)
CONFIG = GateConfig(
    forbidden_output_patterns=("leaked",),
    regression_floors=(("exact_match:answer", 1.0),),
    expected_runner=("replay-runner", "0.1.0"),
    expected_scorer_tool="oracle-scorer",
)

GOOD_ARTIFACT = canonical_bytes({"answer": 42})
OVERSIZE_ARTIFACT = canonical_bytes({"answer": 42, "padding": "x" * 2000})
BAD_CONTENT_ARTIFACT = canonical_bytes({"answer": "leaked secret"})

PROBES = {
    "known-good": GOOD_ARTIFACT,
    "known-bad-resource": OVERSIZE_ARTIFACT,
    "known-bad-content": BAD_CONTENT_ARTIFACT,
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pipeline(artifact: bytes, *, envelope=ENVELOPE, evaluate=evaluate_gates, assemble=assemble_verdict) -> str:
    """The mini evaluation pipeline under test: replay -> gates -> verdict."""
    replay = run_replay(artifact, _sha(artifact), envelope)
    scores = (
        (ScoreEntry("exact_match:answer", 1.0),) if replay.ok else None
    )
    results = evaluate(
        replay=replay,
        score_vector=scores,
        runner_id=runner_identity(),
        scorer_id=scorer_identity("oracle"),
        config=CONFIG,
    )
    return assemble(replay, results, scores)


class MetaMachineryTest(unittest.TestCase):
    def test_mutation_classes_are_the_three_required(self) -> None:
        self.assertEqual(
            MUTATION_CLASSES,
            frozenset({"invert_verdict", "drop_condition", "relax_resource_limit"}),
        )

    def test_known_pair_requires_distinct_expectations(self) -> None:
        with self.assertRaises(ValueError):
            known_pair_check({"a": "pass", "b": "pass"}, {"a": "pass", "b": "pass"})
        with self.assertRaises(ValueError):
            known_pair_check({"a": "pass"}, {"a": "pass", "b": "fail"})
        with self.assertRaises(ValueError):
            mutation_check("no_such_mutation", {}, {})


class MetaDetectionTest(unittest.TestCase):
    """Each required mutation class is applied to the real pipeline and
    must be detected by verdict comparison (acceptance gate)."""

    def _verdicts(self, **kwargs) -> dict[str, str]:
        return {name: _pipeline(artifact, **kwargs) for name, artifact in PROBES.items()}

    def test_known_good_known_bad_stably_distinguished(self) -> None:
        reference = self._verdicts()
        self.assertEqual(reference["known-good"], "pass")
        self.assertEqual(reference["known-bad-resource"], "error")
        self.assertEqual(reference["known-bad-content"], "fail")
        report = known_pair_check(
            {"known-good": reference["known-good"], "known-bad": reference["known-bad-content"]},
            {"known-good": "pass", "known-bad": "fail"},
        )
        self.assertTrue(report.detected, report.detail)

    def test_invert_verdict_is_detected(self) -> None:
        reference = self._verdicts()
        mutated = self._verdicts(assemble=mutate_invert_verdict(assemble_verdict))
        self.assertEqual(mutated["known-good"], "fail")
        self.assertEqual(mutated["known-bad-content"], "pass")
        report = mutation_check("invert_verdict", reference, mutated)
        self.assertTrue(report.detected, report.detail)

    def test_drop_condition_is_detected(self) -> None:
        reference = self._verdicts()
        mutated = self._verdicts(
            evaluate=mutate_drop_condition(evaluate_gates, "critical_safety")
        )
        self.assertEqual(mutated["known-bad-content"], "pass")
        report = mutation_check("drop_condition", reference, mutated)
        self.assertTrue(report.detected, report.detail)
        self.assertIn("known-bad-content", report.detail)

    def test_relax_resource_limit_is_detected(self) -> None:
        reference = self._verdicts()
        relaxed = mutate_relax_resource_limit(ENVELOPE, 100)
        mutated = self._verdicts(envelope=relaxed)
        self.assertEqual(reference["known-bad-resource"], "error")
        self.assertEqual(mutated["known-bad-resource"], "pass")
        report = mutation_check("relax_resource_limit", reference, mutated)
        self.assertTrue(report.detected, report.detail)

    def test_unmutated_control_is_never_detected(self) -> None:
        reference = self._verdicts()
        for mutation in sorted(MUTATION_CLASSES):
            report = mutation_check(mutation, reference, self._verdicts())
            self.assertFalse(report.detected, report.detail)

    def test_mutation_operator_validation(self) -> None:
        with self.assertRaises(ValueError):
            mutate_drop_condition(evaluate_gates, "no_such_gate")
        with self.assertRaises(ValueError):
            mutate_relax_resource_limit(ENVELOPE, 1)
        with self.assertRaises(ValueError):
            mutate_relax_resource_limit(ENVELOPE, True)
        relaxed = mutate_relax_resource_limit(ENVELOPE, 10)
        self.assertEqual(relaxed.max_output_bytes, ENVELOPE.max_output_bytes * 10)


if __name__ == "__main__":
    unittest.main()
