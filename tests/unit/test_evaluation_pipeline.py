"""Unit tests for the E7 record assembly (evaluate_case / compare) and
the three report forms (ADR-0006 decisions 3 and 10)."""

import hashlib
import json
import platform
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from research_evolution.core import (
    canonical_bytes,
    canonical_sha256,
    load_record,
    publish_record,
    verify_record_graph,
)
from research_evolution.evaluation import (
    ComparePolicy,
    Envelope,
    GateConfig,
    ReplayResult,
    compare,
    evaluate_case,
    interpreter_environment,
    render_html,
    render_json,
    render_markdown,
)
from research_evolution.evaluation.statistics import small_sample_limitation

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "core"

ENVELOPE = Envelope(timeout_ms=1000, max_output_bytes=1 << 20, seed=7)
GENERATED_AT = "2026-08-16T12:00:00Z"
CALIBRATION_SHA = "b" * 64

# A non-canonical-but-valid artifact: whitespace the canonical form drops.
NONCANONICAL_ARTIFACT = b'{ "answer": 42 }'
CANONICAL_ARTIFACT = canonical_bytes({"answer": 42})


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _case(case_id: str = "ec-1", scorer_level: str = "oracle") -> dict:
    return {
        "schema": "evaluation-case/v1",
        "evaluation_case_id": case_id,
        "title": "Pipeline test case",
        "domain": "engineering",
        "claim_type": "engineering_claim",
        "split": "smoke",
        "input": {"content_sha256": "0" * 64},
        "evaluation_contract": {
            "scorer_level": scorer_level,
            "contract_sha256": "1" * 64,
        },
        "resources": {},
        "contamination_status": "clean",
        "created_at": GENERATED_AT,
    }


def _suite(suite_id: str, case: dict) -> dict:
    return {
        "schema": "suite/v1",
        "suite_id": suite_id,
        "title": "Pipeline test suite",
        "cases": [
            {
                "evaluation_case_id": case["evaluation_case_id"],
                "sha256": load_record(json.dumps(case)).sha256,
            }
        ],
        "frozen_at": GENERATED_AT,
    }


def _run_kwargs(case=None, suite=None, **overrides):
    case = case if case is not None else _case()
    suite = suite if suite is not None else _suite("s-1", case)
    kwargs = {
        "run_id": "er-1",
        "case": case,
        "suite": suite,
        "candidate": {"candidate_id": "cand-1", "sha256": _sha(CANONICAL_ARTIFACT)},
        "artifact": CANONICAL_ARTIFACT,
        "artifact_sha256": _sha(CANONICAL_ARTIFACT),
        "envelope": ENVELOPE,
        "scoring": {"level": "oracle", "oracle": {"answer": 42}},
        "gate_config": GateConfig(
            regression_floors=(("exact_match:answer", 1.0),),
            expected_runner=("replay-runner", "0.1.0"),
            expected_scorer_tool="oracle-scorer",
        ),
        "generated_at": GENERATED_AT,
    }
    kwargs.update(overrides)
    return kwargs


def _outcome(**overrides):
    return evaluate_case(**_run_kwargs(**overrides))


class EvaluateCaseTest(unittest.TestCase):
    def test_happy_path_payload_is_schema_valid(self) -> None:
        outcome = _outcome()
        self.assertEqual(outcome.verdict, "pass")
        attempt = load_record(json.dumps(outcome.attempt_payload))
        result = load_record(json.dumps(outcome.result_payload))
        self.assertEqual(attempt.schema_id, "evaluation-attempt/v1")
        self.assertEqual(result.schema_id, "evaluation-result/v1")
        self.assertEqual(
            outcome.result_payload["attempt"],
            {
                "evaluation_attempt_id": "er-1-attempt",
                "sha256": attempt.sha256,
            },
        )
        self.assertEqual(
            set(outcome.result_payload),
            {
                "schema",
                "evaluation_result_id",
                "attempt",
                "score_vector",
                "generated_at",
            },
        )
        self.assertIsNotNone(outcome.run_payload)
        record = load_record(json.dumps(outcome.run_payload))
        self.assertEqual(record.schema_id, "evaluation-run/v1")

    def test_dual_hash_tracks_diverge_for_noncanonical_artifact(self) -> None:
        # R29 ledger: raw-bytes pin and canonical output hash are two
        # tracks; a non-canonical artifact makes the divergence visible.
        outcome = _outcome(
            artifact=NONCANONICAL_ARTIFACT,
            artifact_sha256=_sha(NONCANONICAL_ARTIFACT),
        )
        self.assertEqual(outcome.verdict, "pass")
        output_sha = outcome.run_payload["output"]["output_sha256"]
        self.assertEqual(output_sha, canonical_sha256({"answer": 42}))
        self.assertNotEqual(output_sha, _sha(NONCANONICAL_ARTIFACT))

    def test_calibration_sha256_is_single_sourced(self) -> None:
        # R30 ledger: one calibration hash feeds both the judge scores and
        # the scorer identity.
        case = _case(scorer_level="calibrated_judge")
        outcome = _outcome(
            case=case,
            suite=_suite("s-1", case),
            scoring={
                "level": "calibrated_judge",
                "scores": {"accuracy": 1.0},
                "calibration_sha256": CALIBRATION_SHA,
            },
            gate_config=GateConfig(
                expected_scorer_tool="calibrated-judge"
            ),
        )
        self.assertEqual(
            outcome.run_payload["scorer"]["calibration_sha256"], CALIBRATION_SHA
        )
        self.assertEqual(
            outcome.run_payload["score_vector"],
            [{"dimension": "accuracy", "value": 1.0}],
        )

    def test_scoring_level_must_match_case_contract(self) -> None:
        with self.assertRaises(ValueError):
            _outcome(scoring={"level": "structured_rubric", "scores": {"a": 1.0}})

    def test_suite_membership_and_pin_enforced(self) -> None:
        case = _case()
        with self.assertRaises(ValueError):
            _outcome(case=case, suite=_suite("s-1", _case("ec-other")))
        stale_suite = _suite("s-1", case)
        stale_suite["cases"][0]["sha256"] = "9" * 64
        with self.assertRaises(ValueError):
            _outcome(case=case, suite=stale_suite)

    def test_gate_fail_run_is_publishable(self) -> None:
        outcome = _outcome(scoring={"level": "oracle", "oracle": {"answer": 43}})
        self.assertEqual(outcome.verdict, "fail")
        record = load_record(json.dumps(outcome.run_payload))
        self.assertEqual(record.schema_id, "evaluation-run/v1")

    def test_error_attempt_is_publishable_without_fabricated_result(self) -> None:
        outcome = _outcome(artifact_sha256="0" * 64)
        self.assertEqual(outcome.verdict, "error")
        attempt = load_record(json.dumps(outcome.attempt_payload))
        self.assertEqual(attempt.schema_id, "evaluation-attempt/v1")
        self.assertEqual(outcome.attempt_payload["execution"]["status"], "runner_error")
        self.assertEqual(
            outcome.attempt_payload["execution"]["complete_outputs"],
            [],
        )
        self.assertTrue(
            outcome.attempt_payload["execution"]["diagnostics"][0]["detail"]
        )
        self.assertIsNone(outcome.result_payload)
        self.assertIsNone(outcome.run_payload)
        self.assertIn("legacy evaluation-run/v1", outcome.unpublishable_reason)

    def test_scorer_error_preserves_completed_output_in_attempt(self) -> None:
        case = _case(scorer_level="deterministic_checker")
        outcome = _outcome(
            case=case,
            suite=_suite("s-1", case),
            scoring={
                "level": "deterministic_checker",
                "spec": {"checker": "unknown", "params": {}},
            },
            gate_config=GateConfig(),
        )
        self.assertEqual(outcome.verdict, "error")
        self.assertEqual(outcome.attempt_payload["execution"]["status"], "scorer_error")
        self.assertEqual(
            outcome.attempt_payload["execution"]["complete_outputs"],
            [{"sha256": canonical_sha256({"answer": 42})}],
        )
        self.assertIsNone(outcome.result_payload)
        self.assertIsNone(outcome.run_payload)

    def test_every_replay_failure_class_becomes_an_attempt(self) -> None:
        malformed = b"{"
        oversized_envelope = Envelope(
            timeout_ms=1000,
            max_output_bytes=1,
            seed=7,
        )
        real_cases = (
            ("runner_error", _run_kwargs(artifact_sha256="0" * 64)),
            (
                "parse_error",
                _run_kwargs(artifact=malformed, artifact_sha256=_sha(malformed)),
            ),
            (
                "output_limit",
                _run_kwargs(envelope=oversized_envelope),
            ),
        )
        for expected, kwargs in real_cases:
            with self.subTest(error_class=expected):
                outcome = evaluate_case(**kwargs)
                self.assertEqual(
                    outcome.attempt_payload["execution"]["status"],
                    expected,
                )
                self.assertTrue(
                    outcome.attempt_payload["execution"]["diagnostics"][0][
                        "detail"
                    ]
                )
                self.assertIsNone(outcome.result_payload)

        timeout = ReplayResult(
            ok=False,
            output_bytes=None,
            output_sha256=None,
            error_class="timeout",
            error_detail="synthetic monotonic-clock timeout",
            attempts=2,
        )
        with patch(
            "research_evolution.evaluation.pipeline.run_replay",
            return_value=timeout,
        ):
            outcome = _outcome()
        self.assertEqual(outcome.attempt_payload["execution"]["status"], "timeout")
        self.assertEqual(outcome.attempt_payload["execution"]["attempts"], 2)
        self.assertIsNone(outcome.result_payload)

    def test_assembled_payload_is_validated_before_return(self) -> None:
        # R33-P3 regression: the assembler validates its own product; an
        # id the schema would reject fails here, not downstream.
        with self.assertRaises(ValueError):
            _outcome(run_id="has space")

    def test_environment_defaults_to_interpreter_binding(self) -> None:
        outcome = _outcome()
        env = outcome.run_payload["environment"]
        self.assertEqual(env["interpreter"], platform.python_implementation())
        self.assertEqual(env["interpreter_version"], platform.python_version())
        custom = _outcome(environment={"note": "caller supplied"})
        self.assertEqual(custom.run_payload["environment"], {"note": "caller supplied"})

    def test_envelope_echo_and_levels(self) -> None:
        payload = _outcome().run_payload
        self.assertEqual(payload["envelope"]["envelope_sha256"], ENVELOPE.canonical_sha256)
        self.assertEqual(payload["envelope"]["seed"], 7)
        self.assertEqual(payload["levels_covered"], ["L0", "L1"])
        with self.assertRaises(ValueError):
            _outcome(levels_covered=("L2",))


def _two_runs():
    champion = _outcome(run_id="er-champion").run_payload
    challenger_kwargs = _run_kwargs(run_id="er-challenger")
    challenger_kwargs["scoring"] = {"level": "oracle", "oracle": {"answer": 43}}
    challenger = evaluate_case(**challenger_kwargs).run_payload
    return champion, challenger


def _compare_kwargs(**overrides):
    champion, challenger = _two_runs()
    kwargs = {
        "champion": champion,
        "challenger": challenger,
        "policy": ComparePolicy(seed=11, methods=("paired_bootstrap", "paired_exact_mcnemar")),
        "report_id": "rep-1",
        "title": "Champion vs challenger",
        "conclusion": "One smoke case differs; descriptive only.",
        "limitations": ["Single synthetic case."],
        "generated_at": GENERATED_AT,
    }
    kwargs.update(overrides)
    return kwargs


class CompareTest(unittest.TestCase):
    def test_report_payload_is_schema_valid(self) -> None:
        report = compare(**_compare_kwargs())
        record = load_record(json.dumps(report))
        self.assertEqual(record.schema_id, "comparison-report/v1")
        self.assertEqual(report["champion"]["evaluation_run_id"], "er-champion")
        self.assertEqual(len(report["champion"]["sha256"]), 64)

    def test_self_comparison_refused(self) -> None:
        # R28 ledger: champion == challenger is rejected at entry.
        champion, _ = _two_runs()
        with self.assertRaises(ValueError):
            compare(**_compare_kwargs(challenger=champion))

    def test_statistics_are_traced_and_reproducible(self) -> None:
        report = compare(**_compare_kwargs())
        self.assertEqual(
            report["methods"]["statistics"],
            ["paired_bootstrap", "paired_exact_mcnemar"],
        )
        self.assertEqual(report["methods"]["seed"], 11)
        rerun = compare(**_compare_kwargs())
        self.assertEqual(report, rerun)

    def test_mcnemar_requires_binary_dimensions(self) -> None:
        champion, challenger = _two_runs()
        champion["score_vector"] = [{"dimension": "absolute_error:x", "value": 0.4}]
        challenger["score_vector"] = [{"dimension": "absolute_error:x", "value": 0.25}]
        with self.assertRaises(ValueError):
            compare(**_compare_kwargs(champion=champion, challenger=challenger))

    def test_rare_event_requires_policy_parameters(self) -> None:
        with self.assertRaises(ValueError):
            compare(**_compare_kwargs(policy=ComparePolicy(seed=1, methods=("rare_event_upper_bound",))))

    def test_small_sample_limitation_is_appended(self) -> None:
        # R31 ledger: the gate wording is single-sourced into the report.
        report = compare(**_compare_kwargs())
        self.assertIn(small_sample_limitation(1), report["limitations"])

    def test_gate_summary_folds_not_applicable_away(self) -> None:
        # R32 ledger: gate_summary holds only decidable gates.
        report = compare(**_compare_kwargs())
        self.assertTrue(report["gate_summary"])
        self.assertTrue(
            all(entry["result"] in ("pass", "fail") for entry in report["gate_summary"])
        )
        regression = [g for g in report["gate_summary"] if g["gate"] == "regression"]
        self.assertEqual(regression[0]["result"], "fail")  # challenger failed it
        listed = {g["gate"] for g in report["gate_summary"]}
        self.assertNotIn("privacy", listed)  # unconfigured on both runs

    def test_levels_covered_is_the_intersection(self) -> None:
        champion, challenger = _two_runs()
        challenger["levels_covered"] = ["L0"]
        report = compare(**_compare_kwargs(champion=champion, challenger=challenger))
        self.assertEqual(report["levels_covered"], ["L0"])

    def test_shared_dimension_required(self) -> None:
        champion, challenger = _two_runs()
        champion["score_vector"] = [{"dimension": "a", "value": 1.0}]
        challenger["score_vector"] = [{"dimension": "b", "value": 1.0}]
        with self.assertRaises(ValueError):
            compare(**_compare_kwargs(champion=champion, challenger=challenger))


class ReportFormsTest(unittest.TestCase):
    def test_three_forms_carry_the_same_content(self) -> None:
        report = compare(**_compare_kwargs())
        as_json = render_json(report)
        as_markdown = render_markdown(report)
        as_html = render_html(report)
        # JSON form is the canonical identity of the payload itself.
        self.assertEqual(as_json, canonical_bytes(report))
        self.assertEqual(load_record(as_json).schema_id, "comparison-report/v1")
        for key_value in (
            report["report_id"],
            report["champion"]["sha256"],
            report["challenger"]["sha256"],
            report["methods"]["parameters_sha256"],
            report["conclusion"],
        ):
            self.assertIn(str(key_value), as_markdown)
            self.assertIn(str(key_value), as_html)
        self.assertIn("exact_match:answer", as_markdown)
        self.assertIn("exact_match:answer", as_html)
        self.assertIn("L0", as_html)

    def test_html_escapes_injection(self) -> None:
        report = compare(
            **_compare_kwargs(conclusion='<script>alert("x")</script>')
        )
        as_html = render_html(report)
        self.assertNotIn("<script>", as_html)
        self.assertIn("&lt;script&gt;", as_html)

    def test_markdown_escapes_pipes(self) -> None:
        report = compare(**_compare_kwargs(conclusion="a | b"))
        self.assertIn("a \\| b", render_markdown(report))

    def test_rendering_is_deterministic(self) -> None:
        report = compare(**_compare_kwargs())
        self.assertEqual(render_markdown(report), render_markdown(report))
        self.assertEqual(render_html(report), render_html(report))
        self.assertEqual(render_json(report), render_json(report))

    def test_interpreter_environment_shape(self) -> None:
        env = interpreter_environment()
        self.assertEqual(set(env), {"interpreter", "interpreter_version"})


class StoreRoundTripTest(unittest.TestCase):
    """R34 regression: a run reloaded from a store carries Decimal score
    values (the strict parser's frozen numeric model). The publish ->
    load -> compare design workflow must work end to end."""

    def test_publish_load_compare_round_trip(self) -> None:
        case = _case(scorer_level="structured_rubric")
        suite = _suite("s-rt", case)

        def run(run_id: str, clarity: float) -> dict:
            return evaluate_case(
                **_run_kwargs(
                    run_id=run_id,
                    case=case,
                    suite=suite,
                    scoring={
                        "level": "structured_rubric",
                        "scores": {"clarity": clarity, "soundness": 1.0},
                    },
                    gate_config=GateConfig(),
                )
            ).run_payload

        champion = run("er-rt-champion", 0.5)
        challenger = run("er-rt-challenger", 0.25)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            reloaded = {}
            for name, payload in (("champion", champion), ("challenger", challenger)):
                receipt = publish_record(canonical_bytes(payload), root=root)
                self.assertFalse(receipt.already_present)
                reloaded[name] = load_record((root / receipt.path).read_bytes()).data
        # The seam this guards: fractional scores reload as Decimal.
        self.assertTrue(
            any(
                isinstance(entry["value"], Decimal)
                for entry in reloaded["champion"]["score_vector"]
            )
        )
        report = compare(
            champion=reloaded["champion"],
            challenger=reloaded["challenger"],
            policy=ComparePolicy(seed=11, methods=("paired_bootstrap",), resamples=200),
            report_id="rt-1",
            title="store round-trip regression",
            conclusion="store-reloaded runs compare cleanly",
            generated_at=GENERATED_AT,
        )
        record = load_record(render_json(report))
        self.assertEqual(record.schema_id, "comparison-report/v1")
        self.assertEqual(report["methods"]["statistics"], ["paired_bootstrap"])

    def test_attempt_result_publication_and_graph_round_trip(self) -> None:
        case = _case()
        suite = _suite("s-attempt-result", case)
        outcome = _outcome(case=case, suite=suite, run_id="er-attempt-result")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            for payload in (
                case,
                suite,
                outcome.attempt_payload,
                outcome.result_payload,
            ):
                publish_record(canonical_bytes(payload), root=root)
            report = verify_record_graph(root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(
            report.families,
            {
                "evaluation-attempt/v1": 1,
                "evaluation-case/v1": 1,
                "evaluation-result/v1": 1,
                "suite/v1": 1,
            },
        )

    def test_result_attempt_pin_mismatch_fails_graph_verification(self) -> None:
        case = _case()
        suite = _suite("s-attempt-pin", case)
        outcome = _outcome(case=case, suite=suite, run_id="er-attempt-pin")
        result = dict(outcome.result_payload)
        result["attempt"] = dict(result["attempt"])
        result["attempt"]["sha256"] = "f" * 64
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            for payload in (case, suite, outcome.attempt_payload, result):
                publish_record(canonical_bytes(payload), root=root)
            report = verify_record_graph(root)
        self.assertFalse(report.ok)
        self.assertEqual(
            {violation.kind for violation in report.violations},
            {"pin_mismatch"},
        )


if __name__ == "__main__":
    unittest.main()
