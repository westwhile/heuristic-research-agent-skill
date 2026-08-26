"""Run the bounded P7C3 Math Candidate smoke against an exact Git commit.

The script performs exactly two public cases with baseline/Candidate arms (four
fresh Codex processes total). Candidate bytes are projected only into module-
owned temporary workspaces. Raw JSONL, final outputs, session identifiers, and
local paths are never written to the evidence file; only sanitized hashes and
counts leave the temporary workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from research_evolution.core import canonical_bytes, canonical_sha256, load_record
from research_evolution.core._restricted import scan_for_restricted
from research_evolution.evaluation import Envelope, GateConfig
from research_evolution.evolution import (
    AgentForwardTrialPlan,
    CodexCliAgentAdapter,
    assess_candidate_eligibility,
    attest_skill_semantic_review_protocol,
    close_candidate_bundle,
    close_evaluation_envelope,
    draft_skill_candidate_bundle,
    run_agent_skill_forward_trial,
    validate_skill_candidate,
)
from research_evolution.evolution.skill_forward_test import SkillForwardTestPlan

_CRITERIA = (
    "clear_positive_triggers",
    "clear_exclusions",
    "stable_input_contract",
    "stable_output_contract",
    "explicit_failure_pause_boundaries",
    "portable_resources",
    "measurable_gain_plan",
)
_DIMENSIONS = (
    "task_correctness",
    "scope_and_contraindications",
    "trigger_precision",
    "failure_and_pause_boundaries",
    "negative_transfer_risk",
    "privacy_and_license",
    "rollback_and_retirement",
)
_REQUIRED_ARTIFACT_ROLES = (
    "authoritative_head_snapshot",
    "budget_configuration",
    "evaluator_configuration",
    "generator_configuration",
    "public_data_manifest",
    "rollback_target",
    "statistical_plan",
    "tool_configuration",
)
_HEX_40 = set("0123456789abcdef")
_HEX_64 = set("0123456789abcdef")
_SKILL_NAME = "p7c3-math-forward-probe"


def _sha(content: bytes | str) -> str:
    raw = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(raw).hexdigest()


def _require_hex(value: str, length: int, label: str) -> str:
    allowed = _HEX_40 if length == 40 else _HEX_64
    if len(value) != length or any(char not in allowed for char in value):
        raise ValueError(f"{label} must be {length} lowercase hexadecimal characters")
    return value


def _require_rfc3339(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("generated_at must carry a timezone")
    return value


def _candidate_manifest(
    *, model: str, reasoning: str, generated_at: str
) -> tuple[dict[str, Any], dict[str, bytes]]:
    fixture_id = "p7c3-math-real-agent-smoke"
    members = {
        "members/baseline.bin": b"baseline:no-candidate-skill",
        "members/patch.bin": b"patch:add-p7c3-math-forward-probe",
        "members/tests.json": canonical_bytes({"cases": ["explicit-load", "declared-exclusion"]}),
    }
    source_cases = [
        {"case_id": "p7c3-source-math-a", "sha256": _sha("case:p7c3-source-math-a")},
        {"case_id": "p7c3-source-math-b", "sha256": _sha("case:p7c3-source-math-b")},
    ]
    pattern = {
        "pattern_id": "p7c3-pattern-math-bounded-workflow",
        "sha256": _sha("pattern:p7c3-pattern-math-bounded-workflow"),
    }
    head_content = f"head:{fixture_id}"
    materials = [
        {
            "name": "safe-summary",
            "content_sha256": _sha("Bounded public Math smoke candidate."),
            "content": "Bounded public Math smoke candidate.",
            "retention": "minimal_safe",
        },
        {
            "name": "compact-detail",
            "content_sha256": _sha("No external or hidden source material."),
            "content": "No external or hidden source material.",
            "retention": "compact",
        },
        {
            "name": "normal-detail",
            "content_sha256": _sha("Runtime digest is a byte-access probe only."),
            "content": "Runtime digest is a byte-access probe only.",
            "retention": "normal_only",
        },
    ]
    manifest = {
        "schema": "candidate-manifest/v1",
        "candidate_id": f"candidate-{fixture_id}",
        "status": "staged_candidate",
        "objective": "Probe bounded Math Skill loading in a real ephemeral Agent process.",
        "principals": {
            "author": "p7c3-repository-fixture-author",
            "reviewer": "p7c3-repository-fixture-reviewer-label",
        },
        "baseline_sha256": _sha(members["members/baseline.bin"]),
        "patch_sha256": _sha(members["members/patch.bin"]),
        "source_cases": source_cases,
        "source_patterns": [pattern],
        "evaluation_envelope": {
            "model": model,
            "reasoning": reasoning,
            "tools_sha256": _sha("codex-cli:read-only:no-network"),
            "budget_sha256": _sha("four-processes:max:single-attempt"),
            "data_sha256": _sha("public-p7c3-math-smoke-cases-v1"),
            "evaluator_sha256": _sha("oracle:answer-route-runtime-digest"),
        },
        "members": [
            {
                "name": name,
                "role": role,
                "sha256": _sha(content),
                "size_bytes": len(content),
                "depends_on": dependencies,
            }
            for name, role, content, dependencies in (
                ("members/baseline.bin", "baseline", members["members/baseline.bin"], []),
                (
                    "members/patch.bin",
                    "patch",
                    members["members/patch.bin"],
                    ["members/baseline.bin"],
                ),
                (
                    "members/tests.json",
                    "tests",
                    members["members/tests.json"],
                    ["members/patch.bin"],
                ),
            )
        ],
        "exclusions": [
            {
                "name": "private/inputs.json",
                "reason": "Private and hidden inputs are outside this public smoke.",
            }
        ],
        "risks": ["The single-operator smoke may be inconclusive or fail."],
        "rollback": "Keep the immutable no-Skill baseline selected.",
        "context": {
            "authoritative_head": {
                "record_id": f"head-{fixture_id}",
                "sha256": _sha(head_content),
            },
            "unresolved_obligations": [
                "Independent semantic and fresh-session review remains open."
            ],
            "source_lifecycle": [
                *[
                    {
                        "source_id": row["case_id"],
                        "sha256": row["sha256"],
                        "status": "current",
                        "rationale": "Repository-authored public fixture is current.",
                    }
                    for row in source_cases
                ],
                {
                    "source_id": pattern["pattern_id"],
                    "sha256": pattern["sha256"],
                    "status": "current",
                    "rationale": "Repository-authored public fixture is current.",
                },
            ],
            "materials": materials,
        },
        "claims": {
            "installation_authorized": False,
            "activation_authorized": False,
            "publication_authorized": False,
            "semantic_review_completed": False,
        },
        "created_at": generated_at,
    }
    return manifest, members


def _artifact(role: str, content: bytes, *, generated_at: str) -> dict[str, Any]:
    return {
        "schema": "artifact-record/v1",
        "artifact_id": f"artifact-p7c3-{role}",
        "role": role,
        "media_type": "application/octet-stream",
        "content_sha256": _sha(content),
        "size_bytes": len(content),
        "storage_class": "core_store",
        "locator": f"artifacts/{role}.json",
        "redaction_state": "not_required",
        "created_at": generated_at,
    }


def _build_candidate_chain(
    *, model: str, reasoning: str, generated_at: str
) -> tuple[
    dict[str, Any],
    Any,
    dict[str, bytes],
    Any,
    Any,
    Any,
]:
    manifest, members = _candidate_manifest(
        model=model, reasoning=reasoning, generated_at=generated_at
    )
    closure = close_candidate_bundle(manifest, members, closed_at=generated_at)
    source_cases = [
        {
            **case,
            "independence_group": f"math-problem-{index}",
            "origin_run_id": f"math-origin-run-{index}",
            "dataset_lineage_id": f"math-public-fixture-{index}",
            "task_template_id": f"math-template-{index}",
            "semantic_duplicate_group": f"math-semantic-{index}",
        }
        for index, case in enumerate(manifest["source_cases"], start=1)
    ]
    criteria = [
        {
            "criterion": criterion,
            "status": "satisfied",
            "evidence_name": f"evidence/{criterion}.json",
            "rationale": "The bounded repository-authored smoke contract declares this met.",
        }
        for criterion in _CRITERIA
    ]
    eligibility_evidence = {
        row["evidence_name"]: f"p7c3-math:{row['criterion']}".encode() for row in criteria
    }
    eligibility = assess_candidate_eligibility(
        manifest,
        closure,
        {
            "assessor": "p7c3-eligibility-assessor",
            "candidate_kind": "reusable_skill_proposal",
            "source_cases": source_cases,
            "criteria": criteria,
        },
        eligibility_evidence,
        assessed_at=generated_at,
    )
    description = (
        "Guide a bounded public arithmetic check when explicitly invoked; do not use for an "
        "unbounded or production mathematical operation."
    )
    skill_md = (
        "---\n"
        f"name: {_SKILL_NAME}\n"
        f"description: {description}\n"
        "---\n\n"
        "# P7C3 Math forward probe\n\n"
        "For an explicitly invoked bounded arithmetic check, read `references/math.md`, "
        "perform the exact arithmetic, and stop if the task is unbounded or production-facing.\n"
    ).encode()
    reference = (
        b"# Public Math reference\n\n"
        b"Use exact integer arithmetic. Six multiplied by seven equals forty-two. "
        b"This repository-authored probe contains no external material.\n"
    )
    openai_yaml = (
        "interface:\n"
        '  display_name: "P7C3 Math Forward Probe"\n'
        '  short_description: "Bounded public arithmetic smoke"\n'
        f'  default_prompt: "Use ${_SKILL_NAME} for one bounded arithmetic check."\n'
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    ).encode()
    payload = {
        "SKILL.md": skill_md,
        "references/math.md": reference,
        "agents/openai.yaml": openai_yaml,
    }
    draft_contract = {
        "drafter": "p7c3-candidate-drafter",
        "skill_name": _SKILL_NAME,
        "description": description,
        "positive_triggers": ["bounded public arithmetic check"],
        "exclusions": ["unbounded or production mathematical operation"],
        "payload_members": [
            {
                "name": "SKILL.md",
                "role": "skill_instructions",
                "media_type": "text/markdown",
                "depends_on": [],
            },
            {
                "name": "references/math.md",
                "role": "reference",
                "media_type": "text/markdown",
                "depends_on": ["SKILL.md"],
            },
            {
                "name": "agents/openai.yaml",
                "role": "agent_metadata",
                "media_type": "application/yaml",
                "depends_on": ["SKILL.md"],
            },
        ],
        "rollback_plan": "Retain the immutable no-Skill baseline.",
        "retirement_plan": "Retire only through a separately reviewed successor.",
    }
    bundle = draft_skill_candidate_bundle(
        eligibility,
        draft_contract,
        payload,
        eligibility_evidence,
        drafted_at=generated_at,
    )
    static_contract = {
        "validator": "p7c3-static-validator",
        "policy_id": "p7c3-static-policy-v1",
        "registry_skills": [],
        "router_examples": [
            {"prompt": "bounded public arithmetic check", "expected": "select_candidate"},
            {
                "prompt": "unbounded or production mathematical operation",
                "expected": "reject_candidate",
            },
        ],
        "baseline_payload_members": [],
    }
    static = validate_skill_candidate(bundle, payload, static_contract, validated_at=generated_at)
    review_evidence = canonical_bytes(
        {
            "domain": "math",
            "fixture": "P7C3 repository-authored semantic protocol fixture",
            "scope": "engineering protocol only",
        }
    )
    review_sha = _sha(review_evidence)
    semantic_contract = {
        "protocol_id": "p7c3-semantic-review-protocol-v1",
        "reviewer": {
            "principal": "p7c3-synthetic-reviewer",
            "kind": "synthetic_fixture",
            "session_id": "p7c3-synthetic-review-session",
            "model_id": "not-applicable",
            "independence_group": "p7c3-synthetic-review-group",
            "shared_context_with_drafter": False,
        },
        "review_evidence": {
            "name": "reviews/p7c3-math-semantic-protocol.json",
            "media_type": "application/json",
            "sha256": review_sha,
            "size_bytes": len(review_evidence),
        },
        "dimensions": [
            {
                "dimension": dimension,
                "result": "satisfied",
                "rationale": f"Synthetic protocol records {dimension} as satisfied.",
                "evidence_sha256": review_sha,
            }
            for dimension in _DIMENSIONS
        ],
        "declared_outcome": "protocol_accept",
    }
    semantic = attest_skill_semantic_review_protocol(
        bundle,
        static,
        semantic_contract,
        review_evidence,
        reviewed_at=generated_at,
    )
    fixture_id = manifest["candidate_id"].removeprefix("candidate-")
    artifact_contents = {
        "authoritative_head_snapshot": f"head:{fixture_id}".encode(),
        "budget_configuration": b"four-processes:max:single-attempt",
        "evaluator_configuration": b"oracle:answer-route-runtime-digest",
        "generator_configuration": b"repository-authored-p7c3-smoke-v1",
        "public_data_manifest": b"public-p7c3-math-smoke-cases-v1",
        "rollback_target": manifest["rollback"].encode("utf-8"),
        "statistical_plan": b"single-operator-smoke:no-inference",
        "tool_configuration": b"codex-cli:read-only:no-network",
    }
    artifacts = [
        _artifact(role, artifact_contents[role], generated_at=generated_at)
        for role in _REQUIRED_ARTIFACT_ROLES
    ]
    artifact_bytes = {
        artifact["artifact_id"]: artifact_contents[artifact["role"]] for artifact in artifacts
    }
    envelope_closure = close_evaluation_envelope(
        manifest,
        members,
        artifacts,
        artifact_bytes,
        closed_at=generated_at,
    )
    return manifest, bundle, payload, static, semantic, envelope_closure


def _case_plan(
    *,
    case_kind: str,
    generated_at: str,
    manifest: dict[str, Any],
    bundle: Any,
    payload: dict[str, bytes],
    static: Any,
    semantic: Any,
    envelope_closure: Any,
    runner: tuple[str, str],
) -> AgentForwardTrialPlan:
    if case_kind == "explicit-load":
        case_input = canonical_bytes(
            {
                "task": "Compute the exact integer value of six multiplied by seven.",
                "scope": "bounded public arithmetic check",
            }
        )
        answer = "42"
        route = "select_candidate"
        trigger_mode = "explicit_invocation"
        expected_loaded = True
        invocation = (
            f"Explicitly invoke ${_SKILL_NAME} if it is available. If it is absent, solve "
            "the public arithmetic task without a Skill."
        )
    elif case_kind == "declared-exclusion":
        case_input = canonical_bytes(
            {
                "task": "Classify whether an unbounded production operation is in scope.",
                "scope": "unbounded or production mathematical operation",
                "response_contract": {
                    "answer": "not_applicable",
                    "route": "reject_candidate",
                },
            }
        )
        answer = "not_applicable"
        route = "reject_candidate"
        trigger_mode = "declared_exclusion"
        expected_loaded = False
        invocation = "Do not invoke or read any Skill for this declared exclusion."
    else:
        raise ValueError("unknown P7C3 case kind")
    oracle = {"answer": answer, "route": route}
    case = {
        "schema": "evaluation-case/v1",
        "evaluation_case_id": f"p7c3-math-{case_kind}",
        "title": f"P7C3 Math {case_kind}",
        "domain": "math",
        "claim_type": "engineering_claim",
        "split": "smoke",
        "input": {"content_sha256": _sha(case_input)},
        "evaluation_contract": {
            "scorer_level": "oracle",
            "contract_sha256": canonical_sha256(oracle),
        },
        "resources": {
            "evidence_class": "public_real_agent_smoke",
            "provider_randomness": "unseeded",
        },
        "contamination_status": "clean",
        "created_at": generated_at,
    }
    case_sha = load_record(canonical_bytes(case)).sha256
    suite = {
        "schema": "suite/v1",
        "suite_id": f"p7c3-math-{case_kind}-suite",
        "title": f"P7C3 public Math {case_kind} suite",
        "cases": [{"evaluation_case_id": case["evaluation_case_id"], "sha256": case_sha}],
        "frozen_at": generated_at,
    }
    forward = SkillForwardTestPlan(
        test_id=f"p7c3-math-{case_kind}-trial",
        candidate_manifest=manifest,
        candidate_bundle=bundle,
        candidate_payload=payload,
        static_validation_receipt=static,
        semantic_review_attestation=semantic,
        envelope_closure_receipt=envelope_closure,
        case=case,
        suite=suite,
        case_input=case_input,
        envelope=Envelope(
            timeout_ms=600_000,
            max_output_bytes=65_536,
            retry_attempts=0,
            seed=None,
            notes="P7C3 provider-unseeded single-operator real Agent smoke",
        ),
        scoring={"level": "oracle", "oracle": oracle},
        gate_config=GateConfig(
            regression_floors=(
                ("exact_match:answer", 1.0),
                ("exact_match:route", 1.0),
                ("exact_match:skill_runtime", 1.0),
            ),
            expected_runner=runner,
            expected_scorer_tool="oracle-scorer",
        ),
        generated_at=generated_at,
        trigger_mode=trigger_mode,
        expected_route=route,
    )
    prompt = (
        "Read case-input.json in the current isolated workspace. "
        f"{invocation} Return only JSON matching the supplied schema. Set skill_runtime.loaded "
        "to true only after actually reading the selected Skill's SKILL.md; when loaded, report "
        "its exact name and locally computed lowercase SHA-256. If no Skill was read, set loaded "
        "to false and both remaining skill_runtime fields to null. Do not guess a digest."
    )
    return AgentForwardTrialPlan(
        forward_test_plan=forward,
        prompt=prompt,
        reasoning_effort=manifest["evaluation_envelope"]["reasoning"],
        expected_candidate_runtime_loaded=expected_loaded,
    )


def _safe_trial_summary(outcome: Any) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    for arm in ("baseline", "candidate"):
        pipeline = getattr(outcome, arm)
        observation = outcome.observations[arm]
        environment = pipeline.attempt_payload["environment"]
        arms[arm] = {
            "verdict": pipeline.verdict,
            "attempt_sha256": canonical_sha256(pipeline.attempt_payload),
            "result_sha256": canonical_sha256(pipeline.result_payload)
            if pipeline.result_payload is not None
            else None,
            "run_sha256": canonical_sha256(pipeline.run_payload)
            if pipeline.run_payload is not None
            else None,
            "score_vector": [dict(entry) for entry in pipeline.result_payload["score_vector"]]
            if pipeline.result_payload is not None
            else None,
            "output_sha256": observation.replay.output_sha256,
            "launcher_process_started": observation.launcher_process_started,
            "agent_session_started": observation.agent_session_started,
            "agent_turn_completed": observation.agent_turn_completed,
            "runtime_loaded": observation.runtime_loaded,
            "runtime_expectation_verified": environment["runtime_expectation_verified"],
            "session_id_sha256": environment.get("session_id_sha256"),
            "transcript_sha256": observation.transcript_sha256,
            "stderr_sha256": observation.stderr_sha256,
            "usage": observation.usage,
        }
    return {
        "status": outcome.status,
        "blockers": list(outcome.blockers),
        "axes_sha256": outcome.axes_sha256,
        "workspace_cleaned": outcome.workspace_cleaned,
        "claims": outcome.claims,
        "arms": arms,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--powershell", type=Path, required=True)
    parser.add_argument("--cli-version", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    commit = _require_hex(args.commit, 40, "commit")
    tree = _require_hex(args.tree, 40, "tree")
    archive_sha = _require_hex(args.archive_sha256, 64, "archive_sha256")
    generated_at = _require_rfc3339(args.generated_at)
    repository_root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.is_relative_to(repository_root):
        raise ValueError("P7C3 evidence output must remain outside the repository")
    if not output.parent.is_dir():
        raise ValueError("P7C3 evidence output parent must already exist")
    if output.exists():
        raise ValueError("P7C3 evidence output must not overwrite an existing file")

    manifest, bundle, payload, static, semantic, envelope_closure = _build_candidate_chain(
        model=args.model,
        reasoning=args.reasoning,
        generated_at=generated_at,
    )
    adapter = CodexCliAgentAdapter(
        args.launcher,
        powershell=args.powershell,
        cli_version=args.cli_version,
        model=args.model,
        reasoning_effort=args.reasoning,
    )
    outcomes = []
    for case_kind in ("explicit-load", "declared-exclusion"):
        plan = _case_plan(
            case_kind=case_kind,
            generated_at=generated_at,
            manifest=manifest,
            bundle=bundle,
            payload=payload,
            static=static,
            semantic=semantic,
            envelope_closure=envelope_closure,
            runner=(adapter.identity["tool"], adapter.identity["version"]),
        )
        outcomes.append((case_kind, run_agent_skill_forward_trial(plan, adapter)))

    summaries = [
        {"case_kind": case_kind, **_safe_trial_summary(outcome)} for case_kind, outcome in outcomes
    ]
    session_hashes = [
        trial["arms"][arm]["session_id_sha256"]
        for trial in summaries
        for arm in ("baseline", "candidate")
    ]
    all_completed = all(trial["status"] == "smoke_completed" for trial in summaries)
    observed_launcher_processes = sum(
        int(trial["arms"][arm]["launcher_process_started"])
        for trial in summaries
        for arm in ("baseline", "candidate")
    )
    observed_agent_sessions = sum(
        int(trial["arms"][arm]["agent_session_started"])
        for trial in summaries
        for arm in ("baseline", "candidate")
    )
    completed_agent_turns = sum(
        int(trial["arms"][arm]["agent_turn_completed"])
        for trial in summaries
        for arm in ("baseline", "candidate")
    )
    four_distinct_sessions = (
        all(isinstance(value, str) for value in session_hashes)
        and len(session_hashes) == 4
        and len(set(session_hashes)) == 4
    )
    smoke_passed = (
        all_completed
        and four_distinct_sessions
        and observed_agent_sessions == 4
        and completed_agent_turns == 4
    )
    evidence = {
        "schema": "p7c3-real-agent-smoke-evidence/v1",
        "repository": {
            "commit": commit,
            "tree": tree,
            "archive_sha256": archive_sha,
        },
        "runner": {
            **dict(adapter.identity),
            "reasoning_effort": args.reasoning,
            "policy": dict(adapter.execution_policy),
        },
        "candidate": {
            "candidate_manifest_sha256": load_record(canonical_bytes(manifest)).sha256,
            "skill_candidate_bundle_id": bundle.payload["skill_candidate_bundle_id"],
            "skill_candidate_bundle_sha256": bundle.sha256,
            "skill_name": _SKILL_NAME,
            "skill_md_sha256": _sha(payload["SKILL.md"]),
            "payload_byte_closed": bundle.payload["closure"]["payload_byte_closed"],
            "ephemeral_only": True,
        },
        "trials": summaries,
        "summary": {
            "planned_agent_executions": 4,
            "observed_launcher_processes": observed_launcher_processes,
            "observed_agent_sessions": observed_agent_sessions,
            "completed_agent_turns": completed_agent_turns,
            "four_distinct_ephemeral_sessions": four_distinct_sessions,
            "all_trials_completed": all_completed,
            "raw_transcripts_persisted": False,
            "raw_session_ids_persisted": False,
            "candidate_installed": False,
            "candidate_activated": False,
            "independent_forward_acceptance": False,
            "hidden_evaluation": False,
            "promotion": False,
        },
        "evidence_ceiling": (
            "P7C3_REAL_AGENT_SMOKE_RECORDED / ZERO_INDEPENDENT_FORWARD_ACCEPTANCES "
            "/ ZERO_HIDDEN_EVALUATIONS / ZERO_PROMOTIONS"
            if smoke_passed
            else "P7C3_REAL_AGENT_SMOKE_ATTEMPT_RECORDED / ZERO_VALIDATED_REAL_AGENT_SMOKES "
            "/ ZERO_INDEPENDENT_FORWARD_ACCEPTANCES / ZERO_PROMOTIONS"
        ),
        "generated_at": generated_at,
    }
    raw = canonical_bytes(evidence)
    if scan_for_restricted(raw.decode("utf-8"), "p7c3_smoke_evidence"):
        raise ValueError("sanitized P7C3 evidence unexpectedly contains restricted content")
    output.write_bytes(raw + b"\n")
    print(
        "P7C3 AGENT SMOKE: "
        f"{'PASS' if smoke_passed else 'FAIL'} "
        f"launcher_processes={observed_launcher_processes} "
        f"agent_sessions={observed_agent_sessions} "
        f"completed_turns={completed_agent_turns} "
        f"distinct_ephemeral_sessions={str(four_distinct_sessions).lower()} "
        f"evidence_sha256={_sha(raw)}"
    )
    return 0 if smoke_passed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"P7C3 AGENT SMOKE: FAIL ({type(exc).__name__}: {exc})", file=sys.stderr)
        raise SystemExit(1) from None
