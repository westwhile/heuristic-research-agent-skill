"""P7C1 contracts for the synthetic Candidate live-execution seam."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from typing import Any

from research_evolution.core import canonical_bytes, load_record
from research_evolution.evaluation import Envelope, GateConfig
from research_evolution.evolution import (
    ConstrainedLocalProcessAdapter,
    DeterministicInProcessAdapter,
    SkillForwardTestError,
    SkillForwardTestPlan,
    attest_skill_semantic_review_protocol,
    close_evaluation_envelope,
    run_skill_forward_test,
)

from .test_evaluation_envelope_closure import REQUIRED_ROLES, _artifact_payload
from .test_evolution_incubator import _candidate
from .test_skill_candidate_bundle import NOW
from .test_skill_semantic_review import _inputs as _review_inputs
from .test_skill_static_validation import _inputs as _static_inputs


def _envelope_receipt(domain: str) -> Any:
    manifest, members = _candidate(domain)
    fixture_id = manifest["candidate_id"].removeprefix("candidate-")
    contents = {
        "authoritative_head_snapshot": f"head:{fixture_id}".encode(),
        "budget_configuration": b"budget",
        "evaluator_configuration": b"evaluator",
        "generator_configuration": b"synthetic-forward-test-generator",
        "public_data_manifest": f"data:{fixture_id}".encode(),
        "rollback_target": manifest["rollback"].encode(),
        "statistical_plan": b"synthetic-forward-test-statistical-plan",
        "tool_configuration": b"tools",
    }
    artifacts = []
    artifact_bytes = {}
    for role in REQUIRED_ROLES:
        content = contents[role]
        artifact = _artifact_payload(
            role,
            content,
            locator=f"artifacts/{role}.json",
        )
        artifacts.append(artifact)
        artifact_bytes[artifact["artifact_id"]] = content
    return manifest, close_evaluation_envelope(
        manifest,
        members,
        artifacts,
        artifact_bytes,
        closed_at=NOW,
    )


def _case(
    domain: str, expected_route: str
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    case_input = canonical_bytes(
        {
            "domain": domain,
            "prompt": f"bounded synthetic {domain} forward-test fixture",
        }
    )
    case = {
        "schema": "evaluation-case/v1",
        "evaluation_case_id": f"p7c1-{domain}-case",
        "title": f"P7C1 synthetic {domain} forward test",
        "domain": domain,
        "claim_type": "engineering_claim",
        "split": "smoke",
        "input": {"content_sha256": hashlib.sha256(case_input).hexdigest()},
        "evaluation_contract": {
            "scorer_level": "oracle",
            "contract_sha256": hashlib.sha256(
                canonical_bytes({"answer": 42, "route": expected_route})
            ).hexdigest(),
        },
        "resources": {"evidence_class": "synthetic_conformance"},
        "contamination_status": "clean",
        "created_at": NOW,
    }
    suite = {
        "schema": "suite/v1",
        "suite_id": f"p7c1-{domain}-suite",
        "title": f"P7C1 synthetic {domain} suite",
        "cases": [
            {
                "evaluation_case_id": case["evaluation_case_id"],
                "sha256": load_record(canonical_bytes(case)).sha256,
            }
        ],
        "frozen_at": NOW,
    }
    return case, suite, case_input


def _plan(
    domain: str = "math",
    *,
    rejected_dimension: str | None = None,
    adapter_tool: str = "deterministic-in-process-forward-test",
    envelope: Envelope | None = None,
    trigger_mode: str = "explicit_invocation",
) -> SkillForwardTestPlan:
    bundle, static, contract, evidence = _review_inputs(
        domain,
        rejected_dimension=rejected_dimension,
    )
    semantic = attest_skill_semantic_review_protocol(
        bundle,
        static,
        contract,
        evidence,
        reviewed_at=NOW,
    )
    deterministic_bundle, payload, _ = _static_inputs(domain)
    if deterministic_bundle.sha256 != bundle.sha256:
        raise AssertionError("fixture builders produced different candidate bundles")
    expected_route = (
        "select_candidate"
        if trigger_mode in {"explicit_invocation", "implicit_positive"}
        else "reject_candidate"
    )
    manifest, closure = _envelope_receipt(domain)
    case, suite, case_input = _case(domain, expected_route)
    return SkillForwardTestPlan(
        test_id=f"p7c1-{domain}-forward-test",
        candidate_manifest=manifest,
        candidate_bundle=bundle,
        candidate_payload=payload,
        static_validation_receipt=static,
        semantic_review_attestation=semantic,
        envelope_closure_receipt=closure,
        case=case,
        suite=suite,
        case_input=case_input,
        envelope=envelope or Envelope(
            timeout_ms=2_000,
            max_output_bytes=1 << 20,
            seed=7,
            notes="synthetic P7C1 conformance only",
        ),
        scoring={
            "level": "oracle",
            "oracle": {"answer": 42, "route": expected_route},
        },
        gate_config=GateConfig(
            regression_floors=(("exact_match:answer", 1.0),),
            expected_runner=(adapter_tool, "0.1.0"),
            expected_scorer_tool="oracle-scorer",
        ),
        generated_at=NOW,
        trigger_mode=trigger_mode,
        expected_route=expected_route,
    )


def _outputs(route: str = "select_candidate") -> dict[str, bytes]:
    return {
        "baseline": canonical_bytes({"answer": 41, "route": route}),
        "candidate": canonical_bytes({"answer": 42, "route": route}),
    }


class SkillForwardTestTest(unittest.TestCase):
    def test_math_accept_executes_both_arms_and_reuses_attempt_result(self) -> None:
        plan = _plan()
        adapter = DeterministicInProcessAdapter(_outputs(), model="fixture-model")
        outcome = run_skill_forward_test(plan, adapter)

        self.assertEqual(outcome.status, "conformance_completed")
        self.assertEqual(outcome.blockers, ())
        self.assertEqual(outcome.baseline.verdict, "fail")
        self.assertEqual(outcome.candidate.verdict, "pass")
        self.assertEqual(len(adapter.requests), 2)
        self.assertEqual({request.arm for request in adapter.requests}, {"baseline", "candidate"})
        self.assertEqual(
            {request.axes_sha256 for request in adapter.requests},
            {outcome.axes_sha256},
        )
        self.assertIsNone(adapter.requests[0].skill_bundle_sha256)
        self.assertEqual(adapter.requests[1].skill_bundle_sha256, plan.candidate_bundle.sha256)
        for arm in (outcome.baseline, outcome.candidate):
            self.assertEqual(arm.attempt_payload["schema"], "evaluation-attempt/v1")
            self.assertEqual(arm.result_payload["schema"], "evaluation-result/v1")
            self.assertEqual(arm.run_payload["schema"], "evaluation-run/v1")
            self.assertFalse(arm.attempt_payload["environment"]["runtime_loaded"])
            self.assertFalse(
                arm.attempt_payload["environment"]["real_agent_execution_claimed"]
            )
        self.assertTrue(outcome.claims["synthetic_conformance_executed"])
        for claim in (
            "real_agent_execution_observed",
            "real_independent_semantic_review_completed",
            "fresh_session_validated",
            "runtime_loaded",
            "promotion_authorized",
            "publication_authorized",
            "installation_authorized",
            "activation_authorized",
        ):
            self.assertFalse(outcome.claims[claim])

    def test_quant_protocol_reject_starts_no_adapter(self) -> None:
        plan = _plan("quant", rejected_dimension="negative_transfer_risk")
        adapter = DeterministicInProcessAdapter(_outputs(), model="fixture-model")
        outcome = run_skill_forward_test(plan, adapter)

        self.assertEqual(outcome.status, "prerequisite_rejected")
        self.assertEqual(outcome.blockers, ("semantic_protocol_reject",))
        self.assertEqual(adapter.requests, ())
        self.assertIsNone(outcome.baseline)
        self.assertIsNone(outcome.candidate)
        self.assertFalse(outcome.claims["synthetic_conformance_executed"])

    def test_both_adapters_cross_the_same_interface_and_deletion_surface(self) -> None:
        in_process = run_skill_forward_test(
            _plan(),
            DeterministicInProcessAdapter(_outputs(), model="fixture-model"),
        )
        local_process = run_skill_forward_test(
            _plan(adapter_tool="constrained-local-process-forward-test"),
            ConstrainedLocalProcessAdapter(_outputs(), model="fixture-model"),
        )
        self.assertEqual(in_process.status, local_process.status)
        self.assertEqual(in_process.baseline.verdict, local_process.baseline.verdict)
        self.assertEqual(in_process.candidate.verdict, local_process.candidate.verdict)
        self.assertNotEqual(in_process.adapter_identity, local_process.adapter_identity)
        self.assertNotEqual(in_process.axes_sha256, local_process.axes_sha256)

    def test_all_four_trigger_modes_bind_a_scored_router_outcome(self) -> None:
        cases = (
            ("explicit_invocation", "select_candidate"),
            ("implicit_positive", "select_candidate"),
            ("declared_exclusion", "reject_candidate"),
            ("adjacent_skill_conflict", "reject_candidate"),
        )
        for trigger_mode, expected_route in cases:
            with self.subTest(trigger_mode=trigger_mode):
                outcome = run_skill_forward_test(
                    _plan(trigger_mode=trigger_mode),
                    DeterministicInProcessAdapter(
                        _outputs(expected_route), model="fixture-model"
                    ),
                )
                self.assertEqual(outcome.status, "conformance_completed")
                self.assertEqual(
                    outcome.candidate.attempt_payload["environment"]["expected_route"],
                    expected_route,
                )

    def test_attempt_always_result_optional_and_retries_are_preserved(self) -> None:
        envelope = Envelope(
            timeout_ms=2_000,
            max_output_bytes=1 << 20,
            retry_attempts=1,
            retry_on=("runner_error",),
            seed=7,
        )
        plan = _plan(envelope=envelope)
        adapter = DeterministicInProcessAdapter(
            _outputs(),
            model="fixture-model",
            failures={
                "baseline": (
                    "runner_error",
                    "synthetic worker failed for person@example.com",
                )
            },
        )
        outcome = run_skill_forward_test(plan, adapter)

        self.assertEqual(outcome.status, "conformance_inconclusive")
        self.assertEqual(outcome.baseline.verdict, "error")
        self.assertEqual(outcome.baseline.attempt_payload["execution"]["attempts"], 2)
        self.assertIsNone(outcome.baseline.result_payload)
        self.assertIsNone(outcome.baseline.run_payload)
        diagnostic = outcome.baseline.attempt_payload["execution"]["diagnostics"][0][
            "detail"
        ]
        self.assertEqual(
            diagnostic,
            "adapter diagnostic suppressed by restricted-content policy",
        )
        self.assertNotIn("example.com", json.dumps(outcome.baseline.attempt_payload))
        self.assertEqual(outcome.candidate.verdict, "pass")

    def test_local_process_timeout_exit_parse_and_output_limit_fail_closed(self) -> None:
        cases = (
            (
                ConstrainedLocalProcessAdapter(
                    _outputs(), model="fixture-model", delays_ms={"baseline": 100}
                ),
                Envelope(timeout_ms=10, max_output_bytes=1 << 20, seed=7),
                "timeout",
            ),
            (
                ConstrainedLocalProcessAdapter(
                    _outputs(), model="fixture-model", exit_codes={"baseline": 17}
                ),
                Envelope(timeout_ms=2_000, max_output_bytes=1 << 20, seed=7),
                "runner_error",
            ),
            (
                ConstrainedLocalProcessAdapter(
                    {**_outputs(), "baseline": b"not-json"}, model="fixture-model"
                ),
                Envelope(timeout_ms=2_000, max_output_bytes=1 << 20, seed=7),
                "parse_error",
            ),
            (
                ConstrainedLocalProcessAdapter(
                    {
                        **_outputs(),
                        "baseline": canonical_bytes({"answer": "x" * 100}),
                    },
                    model="fixture-model",
                ),
                Envelope(timeout_ms=2_000, max_output_bytes=20, seed=7),
                "output_limit",
            ),
        )
        for adapter, envelope, expected in cases:
            with self.subTest(expected=expected):
                outcome = run_skill_forward_test(
                    _plan(
                        adapter_tool="constrained-local-process-forward-test",
                        envelope=envelope,
                    ),
                    adapter,
                )
                self.assertEqual(outcome.baseline.replay.error_class, expected)
                self.assertEqual(outcome.baseline.verdict, "error")
                self.assertIsNone(outcome.baseline.result_payload)

    def test_candidate_and_envelope_mutation_fail_before_execution(self) -> None:
        plan = _plan()
        payload = dict(plan.candidate_payload)
        payload["SKILL.md"] += b"mutation"
        mutated_plan = copy.copy(plan)
        object.__setattr__(mutated_plan, "candidate_payload", payload)
        adapter = DeterministicInProcessAdapter(_outputs(), model="fixture-model")
        with self.assertRaisesRegex(SkillForwardTestError, "hash or size mismatch"):
            run_skill_forward_test(mutated_plan, adapter)
        self.assertEqual(adapter.requests, ())

        quant_manifest, quant_closure = _envelope_receipt("quant")
        cross_plan = copy.copy(plan)
        object.__setattr__(cross_plan, "envelope_closure_receipt", quant_closure)
        with self.assertRaisesRegex(SkillForwardTestError, "exact candidate manifest"):
            run_skill_forward_test(cross_plan, adapter)
        self.assertEqual(adapter.requests, ())
        self.assertNotEqual(quant_manifest["candidate_id"], plan.candidate_manifest["candidate_id"])

    def test_non_skill_axis_trigger_and_identity_drift_fail_before_execution(self) -> None:
        plan = _plan()
        bad_route = copy.copy(plan)
        object.__setattr__(bad_route, "expected_route", "reject_candidate")
        adapter = DeterministicInProcessAdapter(_outputs(), model="fixture-model")
        with self.assertRaisesRegex(SkillForwardTestError, "trigger mode"):
            run_skill_forward_test(bad_route, adapter)
        self.assertEqual(adapter.requests, ())

        unbound_route = copy.copy(plan)
        object.__setattr__(
            unbound_route,
            "scoring",
            {"level": "oracle", "oracle": {"answer": 42}},
        )
        with self.assertRaisesRegex(SkillForwardTestError, "Router outcome"):
            run_skill_forward_test(unbound_route, adapter)
        self.assertEqual(adapter.requests, ())

        wrong_model = DeterministicInProcessAdapter(_outputs(), model="other-model")
        with self.assertRaisesRegex(SkillForwardTestError, "model differs"):
            run_skill_forward_test(plan, wrong_model)
        self.assertEqual(wrong_model.requests, ())

        wrong_runner = copy.copy(plan)
        object.__setattr__(
            wrong_runner,
            "gate_config",
            GateConfig(
                regression_floors=(("exact_match:answer", 1.0),),
                expected_runner=("different-runner", "0.1.0"),
                expected_scorer_tool="oracle-scorer",
            ),
        )
        with self.assertRaisesRegex(SkillForwardTestError, "exact adapter identity"):
            run_skill_forward_test(wrong_runner, adapter)
        self.assertEqual(adapter.requests, ())


if __name__ == "__main__":
    unittest.main()
