"""Unit tests for the E6 hard gates and verdict assembly (ADR-0006
decision 8)."""

import hashlib
import json
import unittest
from pathlib import Path

from research_evolution.core import canonical_bytes
from research_evolution.evaluation import (
    Envelope,
    ScoreEntry,
    run_replay,
    runner_identity,
    scorer_identity,
)
from research_evolution.evaluation.gates import (
    GATE_RESULTS,
    GATES,
    VERDICTS,
    GateConfig,
    GateResult,
    assemble_verdict,
    evaluate_gates,
    gate_results_payload,
)

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas" / "core"

GOOD_ARTIFACT = canonical_bytes({"answer": 42})
BAD_CONTENT_ARTIFACT = canonical_bytes({"answer": "leaked absolute path"})


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _replay_ok(artifact: bytes = GOOD_ARTIFACT):
    return run_replay(artifact, _sha(artifact), Envelope(1000, 1 << 20))


def _config(**overrides) -> GateConfig:
    params = {
        "forbidden_output_patterns": ("absolute path",),
        "privacy_patterns": (r"/home/\w+",),
        "regression_floors": (("exact_match:answer", 1.0),),
        "expected_runner": ("replay-runner", "0.1.0"),
        "expected_scorer_tool": "oracle-scorer",
    }
    params.update(overrides)
    return GateConfig(**params)


def _evaluate(replay=None, scores=(ScoreEntry("exact_match:answer", 1.0),), config=None):
    return evaluate_gates(
        replay=replay if replay is not None else _replay_ok(),
        score_vector=scores,
        runner_id=runner_identity(),
        scorer_id=scorer_identity("oracle"),
        config=config if config is not None else _config(),
    )


class GateEnumPinTest(unittest.TestCase):
    def test_gates_match_run_schema_enum(self) -> None:
        schema = json.loads(
            (SCHEMAS / "evaluation-run-v1.schema.json").read_text(encoding="utf-8")
        )
        items = schema["properties"]["gate_results"]["items"]["properties"]
        self.assertEqual(set(items["gate"]["enum"]), set(GATES))
        self.assertEqual(set(items["result"]["enum"]), set(GATE_RESULTS))
        verdict = schema["properties"]["verdict"]["enum"]
        self.assertEqual(set(verdict), set(VERDICTS))

    def test_gates_match_report_schema_enum(self) -> None:
        schema = json.loads(
            (SCHEMAS / "comparison-report-v1.schema.json").read_text(encoding="utf-8")
        )
        items = schema["properties"]["gate_summary"]["items"]["properties"]
        self.assertEqual(set(items["gate"]["enum"]), set(GATES))


class GateResultTest(unittest.TestCase):
    def test_fail_requires_reason(self) -> None:
        with self.assertRaises(ValueError):
            GateResult("integrity", "fail")
        with self.assertRaises(ValueError):
            GateResult("integrity", "fail", "   ")
        self.assertIsNone(GateResult("integrity", "pass").reason)

    def test_unknown_gate_and_result_rejected(self) -> None:
        with self.assertRaises(ValueError):
            GateResult("no_such_gate", "pass")
        with self.assertRaises(ValueError):
            GateResult("integrity", "maybe")

    def test_config_validation(self) -> None:
        # R32-P3 regression: a NaN floor never compares true and would idle
        # the gate into an implicit pass — refused at construction.
        with self.assertRaises(ValueError):
            GateConfig(regression_floors=(("exact_match:answer", float("nan")),))
        with self.assertRaises(ValueError):
            GateConfig(regression_floors=(("exact_match:answer", True),))
        # R32-P4-b: expected_runner shape checked at construction.
        with self.assertRaises(ValueError):
            GateConfig(expected_runner=("replay-runner", "0.1.0", "extra"))
        with self.assertRaises(ValueError):
            GateConfig(expected_runner=("replay-runner", 1))
        self.assertEqual(
            GateConfig(expected_runner=("replay-runner", "0.1.0")).expected_runner,
            ("replay-runner", "0.1.0"),
        )


class EvaluateGatesTest(unittest.TestCase):
    def test_all_six_reported_in_fixed_order(self) -> None:
        results = _evaluate()
        self.assertEqual([r.gate for r in results], list(GATES))
        self.assertTrue(all(r.result == "pass" for r in results))

    def test_unconfigured_gates_are_not_applicable(self) -> None:
        results = _evaluate(config=GateConfig())
        by_gate = {r.gate: r.result for r in results}
        self.assertEqual(by_gate["integrity"], "pass")
        self.assertEqual(by_gate["resource"], "pass")
        self.assertEqual(by_gate["critical_safety"], "not_applicable")
        self.assertEqual(by_gate["privacy"], "not_applicable")
        self.assertEqual(by_gate["regression"], "not_applicable")
        self.assertEqual(by_gate["evaluator_integrity"], "not_applicable")

    def test_integrity_follows_runner_error(self) -> None:
        replay = run_replay(GOOD_ARTIFACT, "0" * 64, Envelope(1000, 1 << 20))
        results = _evaluate(replay=replay)
        by_gate = {r.gate: r for r in results}
        self.assertEqual(by_gate["integrity"].result, "fail")
        self.assertIn("integrity failure", by_gate["integrity"].reason)
        # No output exists to scan: content gates stand down.
        self.assertEqual(by_gate["critical_safety"].result, "not_applicable")
        self.assertEqual(by_gate["resource"].result, "pass")

    def test_resource_gate_catches_envelope_errors(self) -> None:
        artifact = b"x" * 100
        replay = run_replay(artifact, _sha(artifact), Envelope(1000, 10))
        by_gate = {r.gate: r.result for r in _evaluate(replay=replay)}
        self.assertEqual(by_gate["resource"], "fail")
        self.assertEqual(by_gate["integrity"], "pass")

    def test_safety_and_privacy_patterns(self) -> None:
        by_gate = {r.gate: r.result for r in _evaluate(replay=_replay_ok(BAD_CONTENT_ARTIFACT))}
        self.assertEqual(by_gate["critical_safety"], "fail")
        artifact = canonical_bytes({"note": "saw /home/alice in output"})
        by_gate = {r.gate: r.result for r in _evaluate(replay=_replay_ok(artifact))}
        self.assertEqual(by_gate["privacy"], "fail")

    def test_regression_floors(self) -> None:
        below = _evaluate(scores=(ScoreEntry("exact_match:answer", 0.0),))
        self.assertEqual(
            {r.gate: r.result for r in below}["regression"], "fail"
        )
        missing = _evaluate(scores=(ScoreEntry("other:dimension", 1.0),))
        regression = {r.gate: r for r in missing}["regression"]
        self.assertEqual(regression.result, "fail")
        self.assertIn("absent", regression.reason)

    def test_evaluator_integrity_identity_mismatch(self) -> None:
        results = evaluate_gates(
            replay=_replay_ok(),
            score_vector=(ScoreEntry("exact_match:answer", 1.0),),
            runner_id={"tool": "mystery-runner", "version": "9.9"},
            scorer_id=scorer_identity("oracle"),
            config=_config(),
        )
        gate = {r.gate: r for r in results}["evaluator_integrity"]
        self.assertEqual(gate.result, "fail")
        self.assertIn("mystery-runner", gate.reason)


class VerdictTest(unittest.TestCase):
    def test_verdict_matrix(self) -> None:
        gates_ok = _evaluate()
        self.assertEqual(assemble_verdict(_replay_ok(), gates_ok, (ScoreEntry("d", 1.0),)), "pass")
        self.assertEqual(assemble_verdict(_replay_ok(), gates_ok, None), "inconclusive")
        replay_error = run_replay(GOOD_ARTIFACT, "0" * 64, Envelope(1000, 1 << 20))
        self.assertEqual(assemble_verdict(replay_error, _evaluate(replay=replay_error), None), "error")
        gates_fail = _evaluate(scores=(ScoreEntry("exact_match:answer", 0.0),))
        self.assertEqual(
            assemble_verdict(_replay_ok(), gates_fail, (ScoreEntry("exact_match:answer", 0.0),)),
            "fail",
        )

    def test_gate_results_payload_shape(self) -> None:
        payload = gate_results_payload(_evaluate())
        self.assertEqual(len(payload), 6)
        self.assertEqual(
            payload[0], {"gate": "integrity", "result": "pass"}
        )
        failing = _evaluate(scores=(ScoreEntry("exact_match:answer", 0.0),))
        regression = [p for p in gate_results_payload(failing) if p["gate"] == "regression"][0]
        self.assertEqual(regression["result"], "fail")
        self.assertIn("reason", regression)


if __name__ == "__main__":
    unittest.main()
