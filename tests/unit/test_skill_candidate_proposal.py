"""P7D1B contracts for one fail-closed Skill Candidate proposal."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from research_evolution.core import canonical_bytes, canonical_sha256, load_record
from research_evolution.evaluation import Envelope
from research_evolution.evolution import (
    DeterministicPublicFailureAdapter,
    DeterministicSkillCandidateAdapter,
    SkillCandidateGenerationObservation,
    SkillCandidateProposalError,
    SkillCandidateProposalPlan,
    capture_public_agent_failure,
    propose_skill_candidate,
)

from .test_public_failure_capture import _plan as _capture_plan

FIXTURES = (
    Path(__file__).parents[1]
    / "fixtures"
    / "evolution"
    / "skill-candidate-proposal"
)
NOW = "2026-08-26T00:00:00Z"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _case_specs(domain: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if domain == "math":
        return (
            {
                "input": {
                    "task": "Return the exact value of 37 squared.",
                    "scope": "public integer arithmetic",
                },
                "oracle": {"answer": 1369},
                "wrong": {"answer": 1368},
            },
            {
                "input": {
                    "task": "Return the exact value of 41 squared.",
                    "scope": "public integer arithmetic",
                },
                "oracle": {"answer": 1681},
                "wrong": {"answer": 1680},
            },
        )
    return (
        {
            "input": {
                "task": "Is a feature timestamp after trade time allowed?",
                "scope": "public PIT rule",
            },
            "oracle": {"answer": "not_allowed"},
            "wrong": {"answer": "allowed"},
        },
        {
            "input": {
                "task": "Is a label observed after decision time allowed as an input?",
                "scope": "public PIT rule",
            },
            "oracle": {"answer": "not_allowed"},
            "wrong": {"answer": "allowed"},
        },
    )


def _captured_cases(domain: str) -> tuple[dict[str, Any], ...]:
    fixture_name = "math-fail.json" if domain == "math" else "quant-pass.json"
    base, _ = _capture_plan(fixture_name)
    shared_summary = (
        "Verify exact arithmetic obligations before finalizing."
        if domain == "math"
        else "Reject information unavailable at the decision timestamp."
    )
    cases: list[dict[str, Any]] = []
    for index, spec in enumerate(_case_specs(domain), start=1):
        case_input = canonical_bytes(spec["input"])
        task = copy.deepcopy(base.task)
        task["task_id"] = f"p7d1b-{domain}-task-{index}"
        task["title"] = f"P7D1B public {domain} task {index}"
        task["problem_statement"] = spec["input"]["task"]
        evaluation_case = copy.deepcopy(base.evaluation_case)
        evaluation_case["evaluation_case_id"] = f"p7d1b-{domain}-evaluation-case-{index}"
        evaluation_case["title"] = f"P7D1B {domain} deterministic case {index}"
        evaluation_case["input"]["content_sha256"] = hashlib.sha256(case_input).hexdigest()
        evaluation_case["evaluation_contract"]["contract_sha256"] = canonical_sha256(
            spec["oracle"]
        )
        evaluation_case_sha = hashlib.sha256(canonical_bytes(evaluation_case)).hexdigest()
        suite = copy.deepcopy(base.suite)
        suite["suite_id"] = f"p7d1b-{domain}-suite-{index}"
        suite["cases"] = [
            {
                "evaluation_case_id": evaluation_case["evaluation_case_id"],
                "sha256": evaluation_case_sha,
            }
        ]
        lineage = {
            "independence_group": f"{domain}-public-problem-{index}",
            "origin_run_id": f"p7d1b-{domain}-run-{index}",
            "dataset_lineage_id": f"public-authored-{domain}-dataset-{index}",
            "task_template_id": f"{domain}-template-{index}",
            "semantic_duplicate_group": f"{domain}-semantic-{index}",
        }
        plan = replace(
            base,
            capture_id=f"p7d1b-{domain}-capture-{index}",
            task=task,
            evaluation_case=evaluation_case,
            suite=suite,
            public_case_input=case_input,
            scoring={"level": "oracle", "oracle": spec["oracle"]},
            case_id=f"p7d1b-{domain}-research-case-{index}",
            case_title=f"P7D1B public {domain} captured failure {index}",
            signature_summary=shared_summary,
            signature_sha256=hashlib.sha256(shared_summary.encode("utf-8")).hexdigest(),
            lineage=lineage,
        )
        adapter = DeterministicPublicFailureAdapter(
            canonical_bytes(spec["wrong"]),
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )
        outcome = capture_public_agent_failure(plan, adapter)
        if outcome.status != "qualified_failure" or outcome.case_payload is None:
            raise AssertionError("synthetic P7D1B source case was not a qualified failure")
        cases.append(outcome.case_payload)
    return tuple(cases)


def _pattern(domain: str, cases: tuple[Mapping[str, Any], ...]) -> dict[str, Any]:
    refs = []
    for payload in cases:
        record = load_record(canonical_bytes(payload))
        refs.append({"case_id": record.data["case_id"], "sha256": record.sha256})
    summary = cases[0]["problem_signature"]["summary"]
    return {
        "schema": "research-pattern/v1",
        "pattern_id": f"p7d1b-{domain}-shared-pattern",
        "problem_signature": {
            "summary": summary,
            "signature_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
            "facets": {"domain": domain, "scope": "public-failure-recovery"},
        },
        "scope": f"Bounded public {domain} failures with deterministic checkers.",
        "preconditions": ["At least two hash-pinned public failure packages exist."],
        "contraindications": ["Private, hidden, installation, or activation work."],
        "successful_tactics": ["Reconstruct the failed obligation and check it before finalizing."],
        "failed_tactics": ["Return an unchecked answer."],
        "evidence": {
            "grade": "synthetic-contract",
            "rationale": "Two synthetic failure packages exercise the P7D1B contract only.",
        },
        "confidence": "low",
        "source_cases": refs,
        "last_validated": NOW,
        "status": "candidate_pattern",
        "transition_rationale": "Captured as a reusable-candidate Pattern for contract testing.",
        "created_at": NOW,
    }


def _proposal_plan(domain: str = "math") -> SkillCandidateProposalPlan:
    cases = _captured_cases(domain)
    pattern = _pattern(domain, cases)
    return SkillCandidateProposalPlan(
        proposal_id=f"p7d1b-{domain}-proposal",
        domain=domain,
        source_cases=cases,
        source_pattern=pattern,
        baseline_bytes=canonical_bytes(
            {"baseline": "exact-main-no-skill", "domain": domain}
        ),
        test_plan={
            "schema": "p7d1b-public-forward-plan/v1",
            "domain": domain,
            "observation_unit": "case_x_frozen_envelope",
            "retries": 0,
        },
        evaluation_envelope={
            "model": "fixture-model",
            "reasoning": "fixture-reasoning",
            "tools_sha256": canonical_sha256({"tools": "read-only"}),
            "budget_sha256": canonical_sha256({"sessions": 1, "retries": 0}),
            "data_sha256": canonical_sha256({"cases": domain}),
            "evaluator_sha256": canonical_sha256({"checker": "deterministic"}),
        },
        prompt=(
            "Read candidate-context.json and return one proposal matching the output schema. "
            "Do not install, activate, publish, or execute the Candidate."
        ),
        reasoning_effort="fixture-reasoning",
        execution_envelope=Envelope(
            timeout_ms=5_000,
            max_output_bytes=131_072,
            retry_attempts=0,
            seed=None,
        ),
        candidate_id=f"p7d1b-{domain}-candidate",
        skill_name=f"public-{domain}-recovery",
        principals={
            "author": f"candidate-author-{domain}",
            "reviewer": f"reserved-reviewer-{domain}",
            "assessor": f"eligibility-assessor-{domain}",
            "drafter": f"candidate-drafter-{domain}",
        },
        authoritative_head={
            "record_id": f"exact-main-{domain}",
            "sha256": canonical_sha256({"commit": "fixture-main", "domain": domain}),
        },
        created_at=NOW,
    )


class SkillCandidateProposalTest(unittest.TestCase):
    def test_process_tree_cleanup_failure_blocks_candidate_generation(self) -> None:
        class CleanupFailureAdapter(DeterministicSkillCandidateAdapter):
            def generate(self, request, envelope) -> SkillCandidateGenerationObservation:
                observed = super().generate(request, envelope)
                return replace(
                    observed,
                    execution_status="cleanup_failed",
                    process_cleanup_status="failed",
                    process_tree_cleanup_verified=False,
                )

        adapter = CleanupFailureAdapter(
            _fixture("math-accept.json"),
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )
        outcome = propose_skill_candidate(_proposal_plan(), adapter)

        self.assertEqual(outcome.status, "proposal_inconclusive")
        self.assertIn("process_tree_cleanup_failed", outcome.blockers)
        self.assertFalse(outcome.claims["process_tree_cleanup_verified"])
        self.assertIsNone(outcome.candidate_bundle)

    def test_math_and_quant_accept_through_one_existing_schema_seam(self) -> None:
        bundles = []
        for domain in ("math", "quant"):
            with self.subTest(domain=domain):
                adapter = DeterministicSkillCandidateAdapter(
                    _fixture(f"{domain}-accept.json"),
                    model="fixture-model",
                    reasoning_effort="fixture-reasoning",
                )
                outcome = propose_skill_candidate(_proposal_plan(domain), adapter)
                self.assertEqual(outcome.status, "proposal_ready")
                self.assertEqual(outcome.blockers, ())
                self.assertEqual(len(adapter.requests), 1)
                self.assertFalse(adapter.requests[0].workspace.exists())
                self.assertTrue(outcome.workspace_cleaned)
                self.assertEqual(outcome.manifest_payload["schema"], "candidate-manifest/v1")
                self.assertEqual(
                    outcome.closure_receipt.payload["schema"],
                    "artifact-closure-receipt/v1",
                )
                self.assertEqual(
                    outcome.eligibility_attestation.payload["outcome"],
                    "eligible_for_payload_drafting",
                )
                self.assertEqual(
                    outcome.candidate_bundle.payload["schema"],
                    "skill-candidate-bundle/v1",
                )
                self.assertEqual(
                    set(outcome.payload_bytes), {"SKILL.md", "agents/openai.yaml"}
                )
                self.assertIn(
                    f"public-{domain}-recovery".encode(),
                    outcome.member_bytes["members/candidate-payload.json"],
                )
                self.assertEqual(len(outcome.eligibility_evidence_bytes), 7)
                self.assertTrue(outcome.claims["byte_closure_verified"])
                for claim in (
                    "source_independence_externally_verified",
                    "semantic_review_completed",
                    "fresh_session_validated",
                    "hidden_evaluation_completed",
                    "promotion_authorized",
                    "publication_authorized",
                    "installation_authorized",
                    "activation_authorized",
                    "runtime_loaded",
                ):
                    self.assertFalse(outcome.claims[claim])
                bundles.append(outcome.candidate_bundle.sha256)
        self.assertNotEqual(bundles[0], bundles[1])

    def test_explicit_math_and_quant_reject_fixtures_produce_no_candidate(self) -> None:
        for domain in ("math", "quant"):
            with self.subTest(domain=domain):
                adapter = DeterministicSkillCandidateAdapter(
                    _fixture(f"{domain}-reject.json"),
                    model="fixture-model",
                    reasoning_effort="fixture-reasoning",
                )
                outcome = propose_skill_candidate(_proposal_plan(domain), adapter)
                self.assertEqual(outcome.status, "proposal_rejected")
                self.assertEqual(outcome.blockers, ("candidate_contract_invalid",))
                self.assertIsNone(outcome.manifest_payload)
                self.assertIsNone(outcome.candidate_bundle)
                self.assertEqual(len(adapter.requests), 1)

    def test_case_deletion_lineage_collision_and_pattern_pin_mutation_fail_pre_call(self) -> None:
        base = _proposal_plan()
        mutations: list[tuple[SkillCandidateProposalPlan, str]] = [
            (replace(base, source_cases=base.source_cases[:-1]), "two to six"),
        ]
        changed_pattern = copy.deepcopy(base.source_pattern)
        changed_pattern["source_cases"][0]["sha256"] = "0" * 64
        mutations.append((replace(base, source_pattern=changed_pattern), "exactly pin"))

        changed_cases = list(copy.deepcopy(base.source_cases))
        changed_cases[1]["problem_signature"]["facets"]["origin_run_id"] = changed_cases[0][
            "problem_signature"
        ]["facets"]["origin_run_id"]
        collision_cases = tuple(changed_cases)
        mutations.append(
            (
                replace(
                    base,
                    source_cases=collision_cases,
                    source_pattern=_pattern("math", collision_cases),
                ),
                "origin_run_id",
            )
        )
        for plan, message in mutations:
            with self.subTest(message=message):
                adapter = DeterministicSkillCandidateAdapter(
                    _fixture("math-accept.json"),
                    model="fixture-model",
                    reasoning_effort="fixture-reasoning",
                )
                with self.assertRaisesRegex(SkillCandidateProposalError, message):
                    propose_skill_candidate(plan, adapter)
                self.assertEqual(adapter.requests, ())

    def test_restricted_plan_and_candidate_output_fail_without_echo(self) -> None:
        plan = _proposal_plan()
        restricted_plan = replace(plan, prompt="Send results to researcher@example.com")
        adapter = DeterministicSkillCandidateAdapter(
            _fixture("math-accept.json"),
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )
        with self.assertRaisesRegex(SkillCandidateProposalError, "restricted") as caught:
            propose_skill_candidate(restricted_plan, adapter)
        self.assertNotIn("researcher@example.com", str(caught.exception))
        self.assertEqual(adapter.requests, ())

        payload = json.loads(_fixture("math-accept.json"))
        secret = "researcher@example.com"
        payload["description"] = secret
        adapter = DeterministicSkillCandidateAdapter(
            canonical_bytes(payload),
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )
        outcome = propose_skill_candidate(plan, adapter)
        self.assertEqual(outcome.status, "proposal_rejected")
        self.assertEqual(outcome.blockers, ("restricted_candidate_output",))
        self.assertIsNone(outcome.payload_bytes)
        self.assertNotIn(secret, repr(outcome))

    def test_parse_output_limit_and_adapter_error_are_inconclusive_without_retry(self) -> None:
        plan = _proposal_plan()
        tiny = replace(
            plan,
            execution_envelope=Envelope(
                timeout_ms=5_000,
                max_output_bytes=1,
                retry_attempts=0,
                seed=None,
            ),
        )
        cases = (
            (tiny, _fixture("math-accept.json"), None, "generation_output_limit"),
            (plan, b"{", None, "generation_parse_error"),
            (
                plan,
                _fixture("math-accept.json"),
                ("runner_error", "private local detail"),
                "generation_runner_error",
            ),
        )
        for active_plan, output, failure, blocker in cases:
            with self.subTest(blocker=blocker):
                adapter = DeterministicSkillCandidateAdapter(
                    output,
                    model="fixture-model",
                    reasoning_effort="fixture-reasoning",
                    failure=failure,
                )
                outcome = propose_skill_candidate(active_plan, adapter)
                self.assertEqual(outcome.status, "proposal_inconclusive")
                self.assertIn(blocker, outcome.blockers)
                self.assertIsNone(outcome.candidate_bundle)
                self.assertEqual(len(adapter.requests), 1)

    def test_real_evidence_requires_started_session_and_completed_turn(self) -> None:
        class MissingSessionAdapter(DeterministicSkillCandidateAdapter):
            @property
            def evidence_class(self) -> str:
                return "real_codex_cli"

            @property
            def execution_policy(self) -> Mapping[str, Any]:
                policy = dict(super().execution_policy)
                policy["sandbox"] = "read-only"
                return policy

        adapter = MissingSessionAdapter(
            _fixture("math-accept.json"),
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )
        outcome = propose_skill_candidate(_proposal_plan(), adapter)
        self.assertEqual(outcome.status, "proposal_inconclusive")
        self.assertIn("real_agent_session_missing", outcome.blockers)
        self.assertIn("real_agent_turn_incomplete", outcome.blockers)
        self.assertIsNone(outcome.candidate_bundle)

    def test_module_exports_one_behavior_interface(self) -> None:
        import research_evolution.evolution.skill_candidate_proposal as module

        behavior = [name for name in module.__all__ if name.startswith("propose_")]
        self.assertEqual(behavior, ["propose_skill_candidate"])


if __name__ == "__main__":
    unittest.main()
