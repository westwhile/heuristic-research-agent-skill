"""P7D1A contracts for public baseline failure capture."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from research_evolution.core import (
    canonical_bytes,
    canonical_sha256,
    publish_record,
    verify_record_graph,
)
from research_evolution.evaluation import Envelope, GateConfig, ReplayResult
from research_evolution.evolution import (
    DeterministicPublicFailureAdapter,
    PublicFailureCaptureError,
    PublicFailureCapturePlan,
    PublicFailureExecutionObservation,
    capture_public_agent_failure,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "evolution" / "public-failure-capture"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _plan(name: str) -> tuple[PublicFailureCapturePlan, bytes]:
    fixture = _fixture(name)
    domain = fixture["domain"]
    case_input = canonical_bytes(fixture["case_input"])
    oracle = fixture["oracle"]
    task = {
        "schema": "research-task/v1",
        "task_id": f"p7d1a-{domain}-task",
        "title": f"P7D1A public {domain} task",
        "problem_statement": fixture["case_input"]["task"],
        "domain": domain,
        "scope": {"visibility": "public", "bounded": True},
        "resources": {"sessions": 1, "retries": 0},
        "completion_criteria": ["Return strict JSON for deterministic checking."],
        "permissions": [],
        "allowed_external_effects": [],
        "created_at": "2026-08-26T00:00:00Z",
    }
    evaluation_case = {
        "schema": "evaluation-case/v1",
        "evaluation_case_id": f"p7d1a-{domain}-evaluation-case",
        "title": f"P7D1A {domain} deterministic case",
        "domain": domain,
        "claim_type": "engineering_claim",
        "split": "development",
        "input": {"content_sha256": hashlib.sha256(case_input).hexdigest()},
        "evaluation_contract": {
            "scorer_level": "oracle",
            "contract_sha256": canonical_sha256(oracle),
        },
        "resources": {"timeout_ms": 5_000, "max_output_bytes": 65_536},
        "contamination_status": "clean",
        "created_at": "2026-08-26T00:00:00Z",
    }
    case_sha = hashlib.sha256(canonical_bytes(evaluation_case)).hexdigest()
    suite = {
        "schema": "suite/v1",
        "suite_id": f"p7d1a-{domain}-suite",
        "title": f"P7D1A {domain} one-case suite",
        "cases": [
            {
                "evaluation_case_id": evaluation_case["evaluation_case_id"],
                "sha256": case_sha,
            }
        ],
        "frozen_at": "2026-08-26T00:00:00Z",
    }
    plan = PublicFailureCapturePlan(
        capture_id=f"p7d1a-{domain}-capture",
        task=task,
        evaluation_case=evaluation_case,
        suite=suite,
        baseline={"candidate_id": "baseline-exact-main", "sha256": "a" * 64},
        public_case_input=case_input,
        output_schema={
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": ["integer", "string"]}},
            "additionalProperties": False,
        },
        prompt="Read case-input.json, solve the bounded public task, and return JSON only.",
        reasoning_effort="fixture-reasoning",
        envelope=Envelope(
            timeout_ms=5_000,
            max_output_bytes=65_536,
            retry_attempts=0,
            seed=None,
            notes="P7D1A one-attempt public capture",
        ),
        scoring={"level": "oracle", "oracle": oracle},
        gate_config=GateConfig(
            regression_floors=(("exact_match:answer", 1.0),),
            expected_runner=("deterministic-public-failure", "0.1.0"),
            expected_scorer_tool="oracle-scorer",
        ),
        case_id=f"p7d1a-{domain}-research-case",
        case_title=f"P7D1A public {domain} captured failure",
        signature_summary=fixture["signature_summary"],
        signature_sha256=hashlib.sha256(
            fixture["signature_summary"].encode("utf-8")
        ).hexdigest(),
        lineage=fixture["lineage"],
        source_project="heuristic-research-agent-skill public P7D1A fixture",
        rights="Independently authored public fixture under Apache-2.0 repository terms.",
    )
    return plan, canonical_bytes(fixture["baseline_output"])


class PublicFailureCaptureTest(unittest.TestCase):
    def test_process_tree_cleanup_failure_is_explicit_and_inconclusive(self) -> None:
        plan, output = _plan("math-fail.json")

        class CleanupFailureAdapter(DeterministicPublicFailureAdapter):
            def execute(self, request, envelope) -> PublicFailureExecutionObservation:
                observed = super().execute(request, envelope)
                return replace(
                    observed,
                    replay=ReplayResult(
                        False,
                        None,
                        None,
                        "runner_error",
                        "process-tree cleanup failed",
                        1,
                    ),
                    execution_status="cleanup_failed",
                    process_cleanup_status="failed",
                    process_tree_cleanup_verified=False,
                )

        adapter = CleanupFailureAdapter(
            output,
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )
        outcome = capture_public_agent_failure(plan, adapter)

        self.assertEqual(outcome.status, "capture_inconclusive")
        self.assertIn("process_tree_cleanup_failed", outcome.blockers)
        self.assertFalse(outcome.claims["process_tree_cleanup_verified"])
        self.assertIsNone(outcome.case_payload)

    def test_math_failure_builds_existing_closed_record_chain(self) -> None:
        plan, output = _plan("math-fail.json")
        adapter = DeterministicPublicFailureAdapter(
            output,
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )

        outcome = capture_public_agent_failure(plan, adapter)

        self.assertEqual(outcome.status, "qualified_failure")
        self.assertEqual(outcome.blockers, ())
        self.assertEqual(outcome.evaluation.verdict, "fail")
        self.assertIsNotNone(outcome.evaluation.result_payload)
        self.assertEqual(len(adapter.requests), 1)
        self.assertFalse(adapter.requests[0].workspace.exists())
        self.assertTrue(outcome.workspace_cleaned)
        self.assertTrue(outcome.claims["qualified_public_failure_captured"])
        self.assertFalse(outcome.claims["root_cause_established"])
        self.assertFalse(outcome.claims["candidate_generated"])
        self.assertEqual(
            outcome.case_payload["problem_signature"]["facets"],
            dict(plan.lineage),
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            for payload in (
                outcome.task_payload,
                outcome.run_payload,
                outcome.observation_payload,
                outcome.analysis_payload,
                outcome.case_payload,
            ):
                publish_record(canonical_bytes(payload), root=root)
            report = verify_record_graph(root)
        self.assertTrue(report.ok, report.to_dict())

    def test_quant_pass_is_not_relabelled_as_a_failure(self) -> None:
        plan, output = _plan("quant-pass.json")
        adapter = DeterministicPublicFailureAdapter(
            output,
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )

        outcome = capture_public_agent_failure(plan, adapter)

        self.assertEqual(outcome.status, "no_failure")
        self.assertEqual(outcome.evaluation.verdict, "pass")
        self.assertIsNone(outcome.run_payload)
        self.assertIsNone(outcome.observation_payload)
        self.assertIsNone(outcome.analysis_payload)
        self.assertIsNone(outcome.case_payload)

    def test_attempt_always_and_result_optional_on_adapter_failure(self) -> None:
        plan, output = _plan("math-fail.json")
        adapter = DeterministicPublicFailureAdapter(
            output,
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
            failure=("runner_error", "private local path D:\\private"),
        )

        outcome = capture_public_agent_failure(plan, adapter)

        self.assertEqual(outcome.status, "capture_inconclusive")
        self.assertEqual(outcome.evaluation.verdict, "error")
        self.assertIsNotNone(outcome.evaluation.attempt_payload)
        self.assertIsNone(outcome.evaluation.result_payload)
        self.assertIsNone(outcome.case_payload)
        serialized = canonical_bytes(outcome.evaluation.attempt_payload)
        self.assertNotIn(b"private", serialized)

    def test_output_limit_and_parse_error_are_inconclusive_without_retry(self) -> None:
        plan, output = _plan("math-fail.json")
        tiny = copy.copy(plan)
        object.__setattr__(
            tiny,
            "envelope",
            Envelope(timeout_ms=5_000, max_output_bytes=1, retry_attempts=0),
        )
        cases = (
            (tiny, output, "output_limit"),
            (plan, b"{", "parse_error"),
        )
        for active_plan, active_output, expected_status in cases:
            with self.subTest(expected_status=expected_status):
                adapter = DeterministicPublicFailureAdapter(
                    active_output,
                    model="fixture-model",
                    reasoning_effort="fixture-reasoning",
                )
                outcome = capture_public_agent_failure(active_plan, adapter)
                self.assertEqual(outcome.status, "capture_inconclusive")
                self.assertEqual(
                    outcome.evaluation.attempt_payload["execution"]["status"],
                    expected_status,
                )
                self.assertEqual(outcome.evaluation.replay.attempts, 1)
                self.assertIsNone(outcome.evaluation.result_payload)
                self.assertIsNone(outcome.case_payload)

    def test_restricted_prompt_and_output_fail_closed_without_echo(self) -> None:
        plan, output = _plan("math-fail.json")
        restricted_plan = copy.copy(plan)
        object.__setattr__(restricted_plan, "prompt", "Contact person@example.com")
        adapter = DeterministicPublicFailureAdapter(
            output,
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )
        with self.assertRaisesRegex(PublicFailureCaptureError, "restricted"):
            capture_public_agent_failure(restricted_plan, adapter)
        self.assertEqual(adapter.requests, ())

        private_output = canonical_bytes({"answer": "person@example.com"})
        adapter = DeterministicPublicFailureAdapter(
            private_output,
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )
        outcome = capture_public_agent_failure(plan, adapter)
        self.assertEqual(outcome.status, "capture_inconclusive")
        self.assertIsNone(outcome.case_payload)
        serialized = canonical_bytes(outcome.evaluation.attempt_payload)
        self.assertNotIn(b"person@example.com", serialized)

    def test_mutated_case_pin_lineage_and_retry_fail_before_execution(self) -> None:
        plan, output = _plan("math-fail.json")
        cases: list[tuple[PublicFailureCapturePlan, str]] = []
        bad_input = copy.copy(plan)
        object.__setattr__(bad_input, "public_case_input", b"{}")
        cases.append((bad_input, "case bytes"))
        bad_lineage = copy.copy(plan)
        object.__setattr__(bad_lineage, "lineage", {"origin_run_id": "only"})
        cases.append((bad_lineage, "lineage"))
        retried = copy.copy(plan)
        object.__setattr__(
            retried,
            "envelope",
            Envelope(
                timeout_ms=5_000,
                max_output_bytes=65_536,
                retry_attempts=1,
                retry_on=("runner_error",),
            ),
        )
        cases.append((retried, "forbids retries"))
        for mutated, message in cases:
            with self.subTest(message=message):
                adapter = DeterministicPublicFailureAdapter(
                    output,
                    model="fixture-model",
                    reasoning_effort="fixture-reasoning",
                )
                with self.assertRaisesRegex(PublicFailureCaptureError, message):
                    capture_public_agent_failure(mutated, adapter)
                self.assertEqual(adapter.requests, ())

    def test_real_evidence_requires_session_and_completed_turn(self) -> None:
        plan, output = _plan("math-fail.json")

        class MissingSessionAdapter(DeterministicPublicFailureAdapter):
            @property
            def evidence_class(self) -> str:
                return "real_codex_cli"

            @property
            def execution_policy(self) -> Mapping[str, Any]:
                policy = dict(super().execution_policy)
                policy["sandbox"] = "read-only"
                return policy

        adapter = MissingSessionAdapter(
            output,
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )
        outcome = capture_public_agent_failure(plan, adapter)
        self.assertEqual(outcome.status, "capture_inconclusive")
        self.assertIn("real_agent_session_missing", outcome.blockers)
        self.assertIn("real_agent_turn_incomplete", outcome.blockers)
        self.assertIsNone(outcome.case_payload)

    def test_module_exports_one_behavior_interface(self) -> None:
        import research_evolution.evolution.public_failure_capture as module

        behavior = [name for name in module.__all__ if name.startswith("capture_")]
        self.assertEqual(behavior, ["capture_public_agent_failure"])


if __name__ == "__main__":
    unittest.main()
