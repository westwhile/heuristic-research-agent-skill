"""P7C3 contracts for repository-external real-Agent smoke execution."""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from research_evolution.core import canonical_bytes
from research_evolution.evaluation import Envelope, GateConfig, ReplayResult
from research_evolution.evolution import (
    AgentExecutionObservation,
    AgentForwardExecutionRequest,
    AgentForwardTrialError,
    AgentForwardTrialPlan,
    CodexCliAgentAdapter,
    DeterministicAgentForwardAdapter,
    run_agent_skill_forward_trial,
)
from research_evolution.evolution._process_containment import ContainedProcessResult

from .test_skill_forward_test import _plan as _p7c1_plan


def _runtime(loaded: bool, name: str, digest: str) -> dict[str, Any]:
    return {
        "loaded": loaded,
        "name": name if loaded else None,
        "skill_md_sha256": digest if loaded else None,
    }


def _trial_plan(
    *,
    expected_loaded: bool = True,
    adapter_tool: str = "deterministic-agent-forward",
    adapter_version: str = "0.1.0",
    envelope: Envelope | None = None,
) -> AgentForwardTrialPlan:
    forward = _p7c1_plan(
        adapter_tool=adapter_tool,
        envelope=envelope
        or Envelope(
            timeout_ms=2_000,
            max_output_bytes=1 << 20,
            retry_attempts=0,
            seed=None,
            notes="P7C3 Agent smoke contract",
        ),
    )
    changed = copy.copy(forward)
    object.__setattr__(
        changed,
        "gate_config",
        GateConfig(
            regression_floors=(
                ("exact_match:answer", 1.0),
                ("exact_match:route", 1.0),
                ("exact_match:skill_runtime", 1.0),
            ),
            expected_runner=(adapter_tool, adapter_version),
            expected_scorer_tool="oracle-scorer",
        ),
    )
    return AgentForwardTrialPlan(
        forward_test_plan=changed,
        prompt=(
            "Solve the bounded problem in case-input.json. If the explicitly named "
            "$research-math-workflow Skill is available, load it and compute the SHA-256 "
            "of its SKILL.md locally; otherwise report it unavailable. Return JSON only."
        ),
        reasoning_effort="fixture-reasoning",
        expected_candidate_runtime_loaded=expected_loaded,
    )


def _outputs(plan: AgentForwardTrialPlan, *, candidate_loaded: bool) -> dict[str, bytes]:
    bundle = plan.forward_test_plan.candidate_bundle
    skill_name = bundle.payload["skill"]["name"]
    digest = hashlib.sha256(plan.forward_test_plan.candidate_payload["SKILL.md"]).hexdigest()
    return {
        "baseline": canonical_bytes(
            {
                "answer": 42,
                "route": "select_candidate",
                "skill_runtime": _runtime(False, skill_name, digest),
            }
        ),
        "candidate": canonical_bytes(
            {
                "answer": 42,
                "route": "select_candidate",
                "skill_runtime": _runtime(candidate_loaded, skill_name, digest),
            }
        ),
    }


class AgentForwardTrialTest(unittest.TestCase):
    def test_deep_interface_projects_only_candidate_and_cleans_both_workspaces(self) -> None:
        plan = _trial_plan()
        adapter = DeterministicAgentForwardAdapter(
            _outputs(plan, candidate_loaded=True),
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )

        outcome = run_agent_skill_forward_trial(plan, adapter)

        self.assertEqual(outcome.status, "smoke_completed")
        self.assertEqual(outcome.blockers, ())
        self.assertTrue(outcome.workspace_cleaned)
        self.assertEqual(outcome.baseline.verdict, "pass")
        self.assertEqual(outcome.candidate.verdict, "pass")
        self.assertEqual(len(adapter.requests), 2)
        self.assertEqual(
            {request.axes_sha256 for request in adapter.requests},
            {outcome.axes_sha256},
        )
        snapshots = dict(adapter.workspace_snapshots)
        self.assertFalse(any(name.startswith(".agents/") for name in snapshots["baseline"]))
        self.assertIn(
            ".agents/skills/research-math-workflow/SKILL.md",
            snapshots["candidate"],
        )
        self.assertTrue(all(not request.workspace.exists() for request in adapter.requests))
        self.assertFalse(outcome.claims["real_agent_session_observed"])
        self.assertFalse(outcome.claims["real_agent_turn_completed"])
        self.assertTrue(outcome.claims["runtime_expectation_verified"])
        self.assertTrue(outcome.claims["candidate_runtime_loaded"])
        self.assertFalse(outcome.claims["fresh_session_validated"])
        self.assertFalse(outcome.claims["promotion_authorized"])

    def test_declared_exclusion_can_keep_available_candidate_unloaded(self) -> None:
        plan = _trial_plan(expected_loaded=False)
        adapter = DeterministicAgentForwardAdapter(
            _outputs(plan, candidate_loaded=False),
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )

        outcome = run_agent_skill_forward_trial(plan, adapter)

        self.assertEqual(outcome.status, "smoke_completed")
        self.assertFalse(outcome.claims["candidate_runtime_loaded"])
        self.assertTrue(outcome.claims["runtime_expectation_verified"])
        self.assertTrue(
            outcome.candidate.attempt_payload["environment"]["candidate_payload_materialized"]
        )

    def test_runtime_mismatch_is_scored_and_rejected_without_hiding_output(self) -> None:
        plan = _trial_plan(expected_loaded=True)
        adapter = DeterministicAgentForwardAdapter(
            _outputs(plan, candidate_loaded=False),
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )

        outcome = run_agent_skill_forward_trial(plan, adapter)

        self.assertEqual(outcome.status, "smoke_rejected")
        self.assertIn("candidate_runtime_expectation_failed", outcome.blockers)
        self.assertEqual(outcome.candidate.verdict, "fail")
        self.assertIsNotNone(outcome.candidate.result_payload)
        self.assertFalse(
            outcome.candidate.attempt_payload["environment"]["runtime_expectation_verified"]
        )

    def test_runtime_match_components_identify_digest_mismatch(self) -> None:
        plan = _trial_plan(expected_loaded=True)
        outputs = _outputs(plan, candidate_loaded=True)
        skill_name = plan.forward_test_plan.candidate_bundle.payload["skill"]["name"]
        outputs["candidate"] = canonical_bytes(
            {
                "answer": 42,
                "route": "select_candidate",
                "skill_runtime": {
                    "loaded": True,
                    "name": skill_name,
                    "skill_md_sha256": "f" * 64,
                },
            }
        )
        adapter = DeterministicAgentForwardAdapter(
            outputs,
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )

        outcome = run_agent_skill_forward_trial(plan, adapter)

        environment = outcome.candidate.attempt_payload["environment"]
        self.assertEqual(
            {
                name: environment[name]
                for name in (
                    "runtime_loaded_matches",
                    "runtime_name_matches",
                    "runtime_digest_matches",
                )
            },
            {
                "runtime_loaded_matches": True,
                "runtime_name_matches": True,
                "runtime_digest_matches": False,
            },
        )

    def test_runtime_match_components_identify_name_mismatch(self) -> None:
        plan = _trial_plan(expected_loaded=True)
        outputs = _outputs(plan, candidate_loaded=True)
        skill_digest = hashlib.sha256(
            plan.forward_test_plan.candidate_payload["SKILL.md"]
        ).hexdigest()
        outputs["candidate"] = canonical_bytes(
            {
                "answer": 42,
                "route": "select_candidate",
                "skill_runtime": {
                    "loaded": True,
                    "name": "different-skill",
                    "skill_md_sha256": skill_digest,
                },
            }
        )
        adapter = DeterministicAgentForwardAdapter(
            outputs,
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
        )

        outcome = run_agent_skill_forward_trial(plan, adapter)

        environment = outcome.candidate.attempt_payload["environment"]
        self.assertEqual(
            {
                name: environment[name]
                for name in (
                    "runtime_loaded_matches",
                    "runtime_name_matches",
                    "runtime_digest_matches",
                )
            },
            {
                "runtime_loaded_matches": True,
                "runtime_name_matches": False,
                "runtime_digest_matches": True,
            },
        )

    def test_failed_agent_attempt_remains_and_result_is_optional(self) -> None:
        plan = _trial_plan()
        adapter = DeterministicAgentForwardAdapter(
            _outputs(plan, candidate_loaded=True),
            model="fixture-model",
            reasoning_effort="fixture-reasoning",
            failures={"baseline": ("runner_error", "private message")},
        )

        outcome = run_agent_skill_forward_trial(plan, adapter)

        self.assertEqual(outcome.status, "smoke_inconclusive")
        self.assertEqual(outcome.baseline.verdict, "error")
        self.assertIsNone(outcome.baseline.result_payload)
        self.assertEqual(
            outcome.baseline.attempt_payload["execution"]["diagnostics"][0]["detail"],
            "deterministic Agent adapter failed",
        )
        self.assertEqual(outcome.candidate.verdict, "pass")

    def test_seed_retry_restricted_prompt_and_axis_drift_fail_before_execution(self) -> None:
        cases: list[tuple[AgentForwardTrialPlan, str]] = []
        seeded = _trial_plan(envelope=Envelope(timeout_ms=2_000, max_output_bytes=1 << 20, seed=7))
        cases.append((seeded, "provider seed"))
        retried = _trial_plan(
            envelope=Envelope(
                timeout_ms=2_000,
                max_output_bytes=1 << 20,
                retry_attempts=1,
                retry_on=("runner_error",),
            )
        )
        cases.append((retried, "automatic retries"))
        restricted = copy.copy(_trial_plan())
        object.__setattr__(restricted, "prompt", "contact person@example.com")
        cases.append((restricted, "restricted content"))
        no_runtime_floor = copy.copy(_trial_plan())
        changed_forward = copy.copy(no_runtime_floor.forward_test_plan)
        object.__setattr__(
            changed_forward,
            "gate_config",
            GateConfig(
                regression_floors=(("exact_match:answer", 1.0),),
                expected_runner=("deterministic-agent-forward", "0.1.0"),
                expected_scorer_tool="oracle-scorer",
            ),
        )
        object.__setattr__(no_runtime_floor, "forward_test_plan", changed_forward)
        cases.append((no_runtime_floor, "runtime digest oracle"))

        for plan, message in cases:
            with self.subTest(message=message):
                adapter = DeterministicAgentForwardAdapter(
                    _outputs(plan, candidate_loaded=True),
                    model="fixture-model",
                    reasoning_effort="fixture-reasoning",
                )
                with self.assertRaisesRegex(AgentForwardTrialError, message):
                    run_agent_skill_forward_trial(plan, adapter)
                self.assertEqual(adapter.requests, ())

    def test_executor_policy_drift_fails_before_materialization(self) -> None:
        plan = _trial_plan()
        adapter = DeterministicAgentForwardAdapter(
            _outputs(plan, candidate_loaded=True),
            model="fixture-model",
            reasoning_effort="different-reasoning",
        )
        with self.assertRaisesRegex(AgentForwardTrialError, "reasoning differs"):
            run_agent_skill_forward_trial(plan, adapter)
        self.assertEqual(adapter.requests, ())

    def test_module_exports_one_behavior_interface(self) -> None:
        import research_evolution.evolution.agent_forward_trial as module

        behavior = [name for name in module.__all__ if name.startswith("run_")]
        self.assertEqual(behavior, ["run_agent_skill_forward_trial"])


class CodexCliAgentAdapterTest(unittest.TestCase):
    def test_codex_adapter_freezes_least_privilege_and_suppresses_environment(self) -> None:
        output = canonical_bytes(
            {
                "answer": 42,
                "route": "select_candidate",
                "skill_runtime": {
                    "loaded": True,
                    "name": "p7c3-math-probe",
                    "skill_md_sha256": "a" * 64,
                },
            }
        )
        captured: dict[str, Any] = {}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher = root / "codex-cli.ps1"
            powershell = root / "pwsh.exe"
            launcher.write_text("# fixture", encoding="utf-8")
            powershell.write_bytes(b"fixture")
            workspace = root / "workspace"
            workspace.mkdir()
            schema = workspace / "schema.json"
            schema.write_text("{}", encoding="utf-8")
            final = workspace / "final.json"
            request = AgentForwardExecutionRequest(
                trial_id="p7c3-adapter-contract",
                arm="candidate",
                workspace=workspace,
                prompt="bounded public prompt",
                output_schema_path=schema,
                final_output_path=final,
                skill_name="p7c3-math-probe",
                skill_md_sha256="a" * 64,
                candidate_bundle_sha256="b" * 64,
                axes_sha256="c" * 64,
            )
            adapter = CodexCliAgentAdapter(
                launcher,
                powershell=powershell,
                cli_version="0.146.0",
                model="gpt-5.6-sol",
                reasoning_effort="xhigh",
            )

            def fake_run(command: list[str], **kwargs: Any) -> ContainedProcessResult:
                captured["command"] = command
                captured["kwargs"] = kwargs
                final.write_bytes(output)
                trace = (
                    b'{"type":"thread.started","thread_id":"fresh-session-1"}\n'
                    b'{"type":"turn.completed","usage":{"input_tokens":12,'
                    b'"output_tokens":8}}\n'
                )
                return ContainedProcessResult(
                    returncode=0,
                    stdout=trace,
                    stderr=b"private stderr",
                    process_started=True,
                    execution_status="completed",
                    process_cleanup_status="not_required",
                    process_tree_cleanup_verified=True,
                )

            secret_env = {
                "GH_TOKEN": "not-forwarded",
                "OPENAI_API_KEY": "not-forwarded",
                "CODEX_API_KEY": "not-forwarded",
                "SECRET_THING": "not-forwarded",
            }
            with (
                patch.dict(os.environ, secret_env, clear=False),
                patch(
                    "research_evolution.evolution.agent_forward_trial.run_process_contained",
                    side_effect=fake_run,
                ),
            ):
                observed = adapter.execute(
                    request,
                    Envelope(timeout_ms=2_000, max_output_bytes=1 << 20),
                )

        command = captured["command"]
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("read-only", command)
        self.assertEqual(command.count("--config"), 5)
        self.assertNotIn("-c", command)
        self.assertIn('approval_policy="never"', command)
        self.assertIn('web_search="disabled"', command)
        self.assertNotIn("danger-full-access", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        forwarded = {key.upper() for key in captured["kwargs"]["env"]}
        self.assertTrue(forwarded.isdisjoint(secret_env))
        self.assertTrue(observed.launcher_process_started)
        self.assertTrue(observed.agent_session_started)
        self.assertTrue(observed.agent_turn_completed)
        self.assertEqual(observed.session_id, "fresh-session-1")
        self.assertTrue(observed.runtime_loaded)
        self.assertEqual(observed.execution_status, "completed")
        self.assertEqual(observed.process_cleanup_status, "not_required")
        self.assertTrue(observed.process_tree_cleanup_verified)
        self.assertEqual(observed.observed_skill_sha256, "a" * 64)
        self.assertEqual(observed.usage, {"input_tokens": 12, "output_tokens": 8})
        self.assertEqual(
            observed.stderr_sha256,
            hashlib.sha256(b"private stderr").hexdigest(),
        )
        self.assertNotIn("private stderr", str(observed))

    def test_cleanup_failure_overrides_timeout_and_blocks_execution_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher = root / "codex-cli.ps1"
            powershell = root / "pwsh.exe"
            launcher.write_text("# fixture", encoding="utf-8")
            powershell.write_bytes(b"fixture")
            workspace = root / "workspace"
            workspace.mkdir()
            schema = workspace / "schema.json"
            schema.write_text("{}", encoding="utf-8")
            request = AgentForwardExecutionRequest(
                trial_id="p7d3-cleanup-failure",
                arm="baseline",
                workspace=workspace,
                prompt="bounded public prompt",
                output_schema_path=schema,
                final_output_path=workspace / "final.json",
                skill_name="p7c3-math-probe",
                skill_md_sha256="a" * 64,
                candidate_bundle_sha256="b" * 64,
                axes_sha256="c" * 64,
            )
            adapter = CodexCliAgentAdapter(
                launcher,
                powershell=powershell,
                cli_version="0.146.0",
                model="gpt-5.6-sol",
                reasoning_effort="xhigh",
            )
            failed = ContainedProcessResult(
                returncode=1,
                stdout=b'{{"type":"thread.started","thread_id":"private-session"}}\n',
                stderr=b"private cleanup detail",
                process_started=True,
                execution_status="cleanup_failed",
                process_cleanup_status="failed",
                process_tree_cleanup_verified=False,
            )
            with patch(
                "research_evolution.evolution.agent_forward_trial.run_process_contained",
                return_value=failed,
            ):
                observed = adapter.execute(
                    request,
                    Envelope(timeout_ms=20, max_output_bytes=1 << 20),
                )

        self.assertEqual(observed.replay.error_class, "runner_error")
        self.assertEqual(observed.replay.error_detail, "Codex CLI process-tree cleanup failed")
        self.assertEqual(observed.execution_status, "cleanup_failed")
        self.assertEqual(observed.process_cleanup_status, "failed")
        self.assertFalse(observed.process_tree_cleanup_verified)
        self.assertNotIn("private-session", str(observed))
        self.assertNotIn("private cleanup detail", str(observed))

    def test_launcher_failure_is_not_claimed_as_real_agent_execution(self) -> None:
        plan = _trial_plan(
            expected_loaded=True,
            adapter_tool="codex-cli-agent-forward",
            adapter_version="0.146.0",
        )
        failure = b"Cannot bind parameter because CodexArgs is specified more than once"

        class LauncherFailureAdapter:
            evidence_class = "real_codex_cli"
            identity = {
                "tool": "codex-cli-agent-forward",
                "version": "0.146.0",
                "model": "fixture-model",
            }
            execution_policy = {
                "reasoning_effort": "fixture-reasoning",
                "sandbox": "read-only",
                "approval_policy": "never",
                "ephemeral": True,
                "web_search": "disabled",
                "trace_max_bytes": 4 << 20,
            }

            def execute(
                self,
                request: AgentForwardExecutionRequest,
                envelope: Envelope,
            ) -> AgentExecutionObservation:
                del request, envelope
                return AgentExecutionObservation(
                    replay=ReplayResult(
                        False,
                        None,
                        None,
                        "runner_error",
                        "Codex CLI exited with code 1",
                        1,
                    ),
                    launcher_process_started=True,
                    agent_session_started=False,
                    agent_turn_completed=False,
                    session_id=None,
                    runtime_loaded=False,
                    observed_skill_name=None,
                    observed_skill_sha256=None,
                    transcript_sha256=None,
                    stderr_sha256=hashlib.sha256(failure).hexdigest(),
                    usage={},
                    execution_status="completed",
                    process_cleanup_status="not_required",
                    process_tree_cleanup_verified=True,
                )

        outcome = run_agent_skill_forward_trial(plan, LauncherFailureAdapter())

        self.assertEqual(outcome.status, "smoke_inconclusive")
        self.assertFalse(outcome.claims["real_agent_session_observed"])
        self.assertFalse(outcome.claims["real_agent_turn_completed"])
        self.assertFalse(outcome.claims["distinct_ephemeral_sessions_observed"])
        for arm in ("baseline", "candidate"):
            observation = outcome.observations[arm]
            self.assertTrue(observation.launcher_process_started)
            self.assertFalse(observation.agent_session_started)
            self.assertFalse(observation.agent_turn_completed)
            self.assertEqual(observation.stderr_sha256, hashlib.sha256(failure).hexdigest())
            self.assertNotIn(failure.decode("ascii"), str(observation))
            self.assertIn(f"{arm}_agent_session_missing", outcome.blockers)


if __name__ == "__main__":
    unittest.main()
