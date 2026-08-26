"""Contracts for the repository-external P7C3 Math smoke Gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path
from typing import Any

from research_evolution.core import canonical_bytes
from research_evolution.evolution import (
    DeterministicAgentForwardAdapter,
    run_agent_skill_forward_trial,
)


def _load_script() -> Any:
    path = Path(__file__).parents[2] / "scripts" / "verify_p7c3_math_agent_smoke.py"
    spec = importlib.util.spec_from_file_location("verify_p7c3_math_agent_smoke", path)
    if spec is None or spec.loader is None:
        raise AssertionError("P7C3 smoke Gate could not be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P7C3MathAgentSmokeGateTest(unittest.TestCase):
    def test_declared_exclusion_exposes_exact_public_response_contract(self) -> None:
        module = _load_script()
        generated_at = "2026-08-26T00:00:00Z"
        manifest, bundle, payload, static, semantic, closure = module._build_candidate_chain(
            model="fixture-model",
            reasoning="fixture-reasoning",
            generated_at=generated_at,
        )

        plan = module._case_plan(
            case_kind="declared-exclusion",
            generated_at=generated_at,
            manifest=manifest,
            bundle=bundle,
            payload=payload,
            static=static,
            semantic=semantic,
            envelope_closure=closure,
            runner=("deterministic-agent-forward", "0.1.0"),
        )

        case_input = json.loads(plan.forward_test_plan.case_input)
        self.assertEqual(
            case_input["response_contract"],
            {"answer": "not_applicable", "route": "reject_candidate"},
        )

    def test_repository_authored_chain_runs_both_public_cases_without_model(self) -> None:
        module = _load_script()
        generated_at = "2026-08-26T00:00:00Z"
        manifest, bundle, payload, static, semantic, closure = module._build_candidate_chain(
            model="fixture-model",
            reasoning="fixture-reasoning",
            generated_at=generated_at,
        )
        digest = hashlib.sha256(payload["SKILL.md"]).hexdigest()
        for case_kind, answer, route, loaded in (
            ("explicit-load", "42", "select_candidate", True),
            ("declared-exclusion", "not_applicable", "reject_candidate", False),
        ):
            with self.subTest(case_kind=case_kind):
                plan = module._case_plan(
                    case_kind=case_kind,
                    generated_at=generated_at,
                    manifest=manifest,
                    bundle=bundle,
                    payload=payload,
                    static=static,
                    semantic=semantic,
                    envelope_closure=closure,
                    runner=("deterministic-agent-forward", "0.1.0"),
                )
                runtime = {
                    "loaded": loaded,
                    "name": module._SKILL_NAME if loaded else None,
                    "skill_md_sha256": digest if loaded else None,
                }
                outputs = {
                    "baseline": canonical_bytes(
                        {
                            "answer": answer,
                            "route": route,
                            "skill_runtime": {
                                "loaded": False,
                                "name": None,
                                "skill_md_sha256": None,
                            },
                        }
                    ),
                    "candidate": canonical_bytes(
                        {"answer": answer, "route": route, "skill_runtime": runtime}
                    ),
                }
                adapter = DeterministicAgentForwardAdapter(
                    outputs,
                    model="fixture-model",
                    reasoning_effort="fixture-reasoning",
                )
                outcome = run_agent_skill_forward_trial(plan, adapter)
                self.assertEqual(outcome.status, "smoke_completed")
                summary = module._safe_trial_summary(outcome)
                for arm in ("baseline", "candidate"):
                    self.assertNotIn("session_id", summary["arms"][arm])
                    self.assertIn("session_id_sha256", summary["arms"][arm])
                    self.assertIn("launcher_process_started", summary["arms"][arm])
                    self.assertIn("agent_session_started", summary["arms"][arm])
                    self.assertIn("agent_turn_completed", summary["arms"][arm])
                    self.assertIn("stderr_sha256", summary["arms"][arm])
                self.assertTrue(summary["workspace_cleaned"])

    def test_safe_evidence_identifies_failed_score_dimension_without_raw_output(
        self,
    ) -> None:
        module = _load_script()
        generated_at = "2026-08-26T00:00:00Z"
        manifest, bundle, payload, static, semantic, closure = module._build_candidate_chain(
            model="fixture-model",
            reasoning="fixture-reasoning",
            generated_at=generated_at,
        )
        plan = module._case_plan(
            case_kind="declared-exclusion",
            generated_at=generated_at,
            manifest=manifest,
            bundle=bundle,
            payload=payload,
            static=static,
            semantic=semantic,
            envelope_closure=closure,
            runner=("deterministic-agent-forward", "0.1.0"),
        )
        failed_output = canonical_bytes(
            {
                "answer": "semantically-related-but-not-the-frozen-label",
                "route": "reject_candidate",
                "skill_runtime": {
                    "loaded": False,
                    "name": None,
                    "skill_md_sha256": None,
                },
            }
        )
        outcome = run_agent_skill_forward_trial(
            plan,
            DeterministicAgentForwardAdapter(
                {"baseline": failed_output, "candidate": failed_output},
                model="fixture-model",
                reasoning_effort="fixture-reasoning",
            ),
        )

        baseline = module._safe_trial_summary(outcome)["arms"]["baseline"]
        self.assertEqual(
            baseline["score_vector"],
            [
                {"dimension": "exact_match:answer", "value": 0.0},
                {"dimension": "exact_match:route", "value": 1.0},
                {"dimension": "exact_match:skill_runtime", "value": 1.0},
            ],
        )
        self.assertNotIn("output", baseline)

    def test_hex_and_time_validation_fail_closed(self) -> None:
        module = _load_script()
        with self.assertRaisesRegex(ValueError, "40 lowercase hexadecimal"):
            module._require_hex("g" * 40, 40, "commit")
        with self.assertRaisesRegex(ValueError, "timezone"):
            module._require_rfc3339("2026-08-26T00:00:00")


if __name__ == "__main__":
    unittest.main()
