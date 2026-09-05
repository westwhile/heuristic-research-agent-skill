from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from typing import Any

from research_evolution.core import canonical_bytes, load_record
from research_evolution.evaluation import MetricPolicy, SuiteComparePolicy
from research_evolution.evolution import (
    ConstrainedLocalProcessAdapter,
    DeterministicInProcessAdapter,
    ForwardSuiteCase,
    SkillForwardSuiteError,
    SkillForwardSuitePlan,
    run_skill_forward_suite,
)
from tests.unit.test_skill_forward_test import NOW, _outputs, _plan


def _suite_case(
    domain: str,
    suffix: str,
    base: Any,
) -> tuple[ForwardSuiteCase, dict[str, Any]]:
    case_input = canonical_bytes(
        {
            "domain": domain,
            "prompt": f"bounded synthetic P7C2 {domain} fixture {suffix}",
        }
    )
    case = {
        "schema": "evaluation-case/v1",
        "evaluation_case_id": f"p7c2-{domain}-case-{suffix}",
        "title": f"P7C2 synthetic {domain} forward-suite case {suffix}",
        "domain": domain,
        "claim_type": "engineering_claim",
        "split": "smoke",
        "input": {"content_sha256": hashlib.sha256(case_input).hexdigest()},
        "evaluation_contract": {
            "scorer_level": "oracle",
            "contract_sha256": hashlib.sha256(
                canonical_bytes({"answer": 42, "route": "select_candidate"})
            ).hexdigest(),
        },
        "resources": {"evidence_class": "synthetic_conformance"},
        "contamination_status": "clean",
        "created_at": NOW,
    }
    return (
        ForwardSuiteCase(
            case=case,
            case_input=case_input,
            scoring={
                "level": "oracle",
                "oracle": {"answer": 42, "route": "select_candidate"},
            },
            gate_config=base.gate_config,
            trigger_mode="explicit_invocation",
            expected_route="select_candidate",
        ),
        case,
    )


def _suite_plan(
    domain: str = "math",
    *,
    rejected_dimension: str | None = None,
    adapter_tool: str = "deterministic-in-process-forward-test",
    case_count: int = 2,
    seeds: tuple[int, ...] = (11, 13),
) -> SkillForwardSuitePlan:
    base = _plan(
        domain,
        rejected_dimension=rejected_dimension,
        adapter_tool=adapter_tool,
    )
    cases_and_payloads = [_suite_case(domain, str(index + 1), base) for index in range(case_count)]
    cases = tuple(item[0] for item in cases_and_payloads)
    suite_cases = [item[1] for item in cases_and_payloads]
    suite = {
        "schema": "suite/v1",
        "suite_id": f"p7c2-{domain}-forward-suite",
        "title": f"P7C2 synthetic {domain} public forward suite",
        "cases": [
            {
                "evaluation_case_id": case["evaluation_case_id"],
                "sha256": load_record(canonical_bytes(case)).sha256,
            }
            for case in suite_cases
        ],
        "frozen_at": NOW,
    }
    return SkillForwardSuitePlan(
        suite_test_id=f"p7c2-{domain}-suite-test",
        candidate_manifest=base.candidate_manifest,
        candidate_bundle=base.candidate_bundle,
        candidate_payload=base.candidate_payload,
        static_validation_receipt=base.static_validation_receipt,
        semantic_review_attestation=base.semantic_review_attestation,
        envelope_closure_receipt=base.envelope_closure_receipt,
        suite=suite,
        cases=cases,
        envelope=replace(base.envelope, seed=None, notes="synthetic P7C2 suite only"),
        compare_policy=SuiteComparePolicy(
            seed=101,
            expected_seeds=seeds,
            metrics=(
                MetricPolicy(
                    dimension="exact_match:answer",
                    direction="higher",
                    role="primary",
                    rope=0.0,
                ),
                MetricPolicy(
                    dimension="exact_match:route",
                    direction="higher",
                    role="guardrail",
                    rope=0.0,
                    noninferiority_margin=0.0,
                ),
            ),
            resamples=64,
            minimum_pairs=4,
        ),
        max_total_attempts=case_count * len(seeds) * 2,
        comparison_id=f"p7c2-{domain}-synthetic-comparison",
        title=f"P7C2 synthetic {domain} public forward-suite comparison",
        generated_at=NOW,
    )


class SkillForwardSuiteTests(unittest.TestCase):
    def test_both_domains_bind_report_candidates_to_every_run(self) -> None:
        for domain in ("math", "quant"):
            with self.subTest(domain=domain):
                adapter = DeterministicInProcessAdapter(_outputs(), model="fixture-model")
                outcome = run_skill_forward_suite(_suite_plan(domain), adapter)
                comparison = outcome.suite_comparison
                self.assertIsNotNone(comparison)
                for cell in outcome.cells:
                    self.assertEqual(
                        cell.outcome.baseline.run_payload["candidate"], comparison["champion"]
                    )
                    self.assertEqual(
                        cell.outcome.candidate.run_payload["candidate"], comparison["challenger"]
                    )

    def test_math_accept_runs_complete_case_seed_grid_and_existing_comparison(self) -> None:
        adapter = DeterministicInProcessAdapter(_outputs(), model="fixture-model")
        outcome = run_skill_forward_suite(_suite_plan(), adapter)

        self.assertEqual(outcome.status, "suite_comparison_completed")
        self.assertEqual(outcome.blockers, ())
        self.assertEqual(outcome.planned_cells, 4)
        self.assertEqual(outcome.planned_max_attempts, 8)
        self.assertEqual(outcome.observed_attempts, 8)
        self.assertEqual(len(outcome.cells), 4)
        self.assertEqual(len(adapter.requests), 8)
        self.assertEqual(
            {(cell.case_id, cell.seed) for cell in outcome.cells},
            {
                ("p7c2-math-case-1", 11),
                ("p7c2-math-case-1", 13),
                ("p7c2-math-case-2", 11),
                ("p7c2-math-case-2", 13),
            },
        )
        comparison = outcome.suite_comparison
        self.assertIsNotNone(comparison)
        assert comparison is not None
        self.assertEqual(comparison["schema"], "suite-comparison/v1")
        self.assertEqual(comparison["observation_unit"], "case_seed_frozen_envelope")
        self.assertEqual(len(comparison["pairs"]), 4)
        self.assertEqual(
            {metric["role"] for metric in comparison["metrics"]},
            {"primary", "guardrail"},
        )
        self.assertEqual(comparison["conclusion"], "synthetic_conformance_only_no_promotion")
        self.assertTrue(outcome.claims["complete_case_seed_grid_observed"])
        for claim in (
            "real_agent_execution_observed",
            "real_independent_semantic_review_completed",
            "hidden_evaluation_completed",
            "candidate_materialized",
            "runtime_loaded",
            "promotion_authorized",
            "publication_authorized",
            "installation_authorized",
            "activation_authorized",
        ):
            self.assertFalse(outcome.claims[claim])

    def test_quant_protocol_reject_preserves_full_grid_without_execution(self) -> None:
        adapter = DeterministicInProcessAdapter(_outputs(), model="fixture-model")
        outcome = run_skill_forward_suite(
            _suite_plan("quant", rejected_dimension="negative_transfer_risk"),
            adapter,
        )

        self.assertEqual(outcome.status, "prerequisite_rejected")
        self.assertEqual(len(outcome.cells), 4)
        self.assertEqual(adapter.requests, ())
        self.assertEqual(outcome.observed_attempts, 0)
        self.assertIsNone(outcome.suite_comparison)
        self.assertEqual(len(outcome.blockers), 4)

    def test_failure_attempts_are_not_selectively_excluded(self) -> None:
        adapter = DeterministicInProcessAdapter(
            _outputs(),
            model="fixture-model",
            failures={"candidate": ("runner_error", "synthetic failure")},
        )
        outcome = run_skill_forward_suite(_suite_plan(), adapter)

        self.assertEqual(outcome.status, "execution_inconclusive")
        self.assertEqual(len(adapter.requests), 8)
        self.assertEqual(outcome.observed_attempts, 8)
        self.assertEqual(len(outcome.cells), 4)
        self.assertIsNone(outcome.suite_comparison)
        for cell in outcome.cells:
            self.assertIsNotNone(cell.outcome.baseline)
            self.assertIsNotNone(cell.outcome.candidate)
            assert cell.outcome.candidate is not None
            self.assertEqual(
                cell.outcome.candidate.attempt_payload["execution"]["status"],
                "runner_error",
            )

    def test_budget_rejects_before_any_adapter_call(self) -> None:
        plan = _suite_plan()
        adapter = DeterministicInProcessAdapter(_outputs(), model="fixture-model")
        with self.assertRaisesRegex(SkillForwardSuiteError, "max_total_attempts"):
            run_skill_forward_suite(replace(plan, max_total_attempts=7), adapter)
        self.assertEqual(adapter.requests, ())

    def test_case_deletion_rejects_before_any_adapter_call(self) -> None:
        plan = _suite_plan()
        adapter = DeterministicInProcessAdapter(_outputs(), model="fixture-model")
        with self.assertRaisesRegex(SkillForwardSuiteError, "membership exactly"):
            run_skill_forward_suite(replace(plan, cases=plan.cases[:-1]), adapter)
        self.assertEqual(adapter.requests, ())

    def test_metric_mutation_rejects_before_any_adapter_call(self) -> None:
        plan = _suite_plan()
        mutated_case = replace(
            plan.cases[0],
            scoring={"level": "oracle", "oracle": {"answer": 42}},
        )
        adapter = DeterministicInProcessAdapter(_outputs(), model="fixture-model")
        with self.assertRaisesRegex(SkillForwardSuiteError, "preregistered metrics"):
            run_skill_forward_suite(replace(plan, cases=(mutated_case, *plan.cases[1:])), adapter)
        self.assertEqual(adapter.requests, ())

    def test_seed_is_owned_only_by_compare_policy(self) -> None:
        plan = _suite_plan()
        adapter = DeterministicInProcessAdapter(_outputs(), model="fixture-model")
        with self.assertRaisesRegex(SkillForwardSuiteError, "seed must be unset"):
            run_skill_forward_suite(
                replace(plan, envelope=replace(plan.envelope, seed=99)), adapter
            )
        self.assertEqual(adapter.requests, ())

    def test_both_existing_adapters_cross_the_same_suite_interface(self) -> None:
        in_process = run_skill_forward_suite(
            _suite_plan(case_count=1, seeds=(17,)),
            DeterministicInProcessAdapter(_outputs(), model="fixture-model"),
        )
        local_process = run_skill_forward_suite(
            _suite_plan(
                adapter_tool="constrained-local-process-forward-test",
                case_count=1,
                seeds=(17,),
            ),
            ConstrainedLocalProcessAdapter(_outputs(), model="fixture-model"),
        )
        self.assertEqual(in_process.status, local_process.status)
        self.assertEqual(in_process.observed_attempts, local_process.observed_attempts)
        self.assertEqual(
            in_process.suite_comparison["observation_unit"],
            local_process.suite_comparison["observation_unit"],
        )


if __name__ == "__main__":
    unittest.main()
