"""Deterministic Phase 5 L6 ML research-memory evidence builder.

The builder composes the already-public Phase 4 experience interface with
the Phase 5 ML Adapter and synthetic runner.  It performs no writes: callers
receive canonical bytes and decide whether to compare or materialize them.
All payloads are synthetic engineering evidence and intentionally stop below
real-data, predictive, production, Skill-publication, and activation claims.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

from research_evolution.adapters import AdapterError
from research_evolution.adapters.ml import MLAdapter
from research_evolution.adapters.ml.runner import (
    run_synthetic_experiment,
    runner_identity,
)
from research_evolution.core import (
    canonical_bytes,
    canonical_sha256,
    load_record,
    load_strict_json,
)
from research_evolution.experience import (
    ArtifactInput,
    EligibilityInput,
    assert_registry_clean,
    capture_case,
    distill_patterns,
    lint_heuristics,
    propose_heuristic,
    record_shadow_report,
    transition_heuristic,
    transition_pattern,
)
from tests.unit.test_ml_runner import (
    _classification_dataset,
    _repin_selection,
    _runner_case,
)
from tests.unit.test_ml_split_execution import _group_payload, _repin_split


_ROOT = Path(__file__).resolve().parents[2]
_ML_TASK = (
    _ROOT
    / "tests"
    / "fixtures"
    / "adapters"
    / "ml-task"
    / "v1"
    / "valid"
    / "minimal.json"
)
_ML_CLAIM = (
    _ROOT
    / "tests"
    / "fixtures"
    / "adapters"
    / "ml-claim"
    / "v1"
    / "valid"
    / "full.json"
)

_STUDY_ID = "phase5-l6-synthetic-study"
_TASK_AT = "2026-08-21T08:00:00Z"
_RUN_AT = "2026-08-21T09:00:00Z"
_CASE_AT = "2026-08-21T10:00:00Z"
_PATTERN_AT = "2026-08-21T11:00:00Z"
_CANDIDATE_AT = "2026-08-21T12:00:00Z"
_SHADOW_AT = "2026-08-21T13:00:00Z"

_CASE_SPECS = {
    "protocol": {
        "case_id": "case-ml-protocol",
        "title": "Synthetic ML full protocol capture",
        "statement": (
            "The synthetic protocol, contract, repeated-seed result, and "
            "claim assessment are hash-bound in one reproducible case package."
        ),
        "signature_summary": "synthetic ml full protocol evidence capture",
        "signature_key": b"ml-l6-protocol-capture",
    },
    "negative-result": {
        "case_id": "case-ml-negative-result",
        "title": "Synthetic ML negative result retention",
        "statement": (
            "The synthetic candidate did not outperform the intercept-only "
            "baseline and the non-winning result was retained."
        ),
        "signature_summary": "synthetic ml non-winning outcome retention",
        "signature_key": b"ml-l6-negative-result",
    },
    "leakage-repair": {
        "case_id": "case-ml-leakage-repair",
        "title": "Synthetic ML protected-partition leakage repair",
        "statement": (
            "The unsafe selection declaration was rejected and the repaired "
            "validation-only declaration executed under a new case hash."
        ),
        "signature_summary": (
            "synthetic ml comparison requires matched protocol evidence pins"
        ),
        "signature_key": b"ml-l6-matched-protocol-evidence-pins",
    },
    "reproduction-difference": {
        "case_id": "case-ml-reproduction-difference",
        "title": "Synthetic ML reproduction difference attribution",
        "statement": (
            "Same-protocol replays were byte-identical while a changed seed "
            "policy produced a different case and artifact hash."
        ),
        "signature_summary": (
            "synthetic ml comparison requires matched protocol evidence pins"
        ),
        "signature_key": b"ml-l6-matched-protocol-evidence-pins",
    },
}


def _validated(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a Core payload and return an isolated JSON tree."""

    return load_record(canonical_bytes(payload)).data


def _rename_case(case: dict[str, Any], case_id: str) -> None:
    """Give a runner case stable L6 identities and refresh dependent pins."""

    case["case_id"] = case_id
    case["study_id"] = _STUDY_ID
    case["dataset"]["identity"] = f"{case_id}-dataset"
    case["split"]["identity"] = f"{case_id}-split"
    case["selection"]["identity"] = f"{case_id}-selection"
    _repin_split(case)


def _ml_claim(
    *,
    case: dict[str, Any],
    claim_id: str,
    statement: str,
    outcome: str,
) -> dict[str, Any]:
    claim = load_strict_json(_ML_CLAIM.read_bytes())
    claim["claim_id"] = claim_id
    claim["study_id"] = _STUDY_ID
    claim["case_sha256"] = canonical_sha256(case)
    claim["statement"] = statement
    claim["outcome"] = outcome
    return claim


def _protocol_bundle() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dataset, case = _group_payload()
    _rename_case(case, "ml-l6-protocol")
    adapter = MLAdapter()
    contract = adapter.build_evaluation_contract(case)
    result = run_synthetic_experiment(
        dataset, case, contract=contract, final_partition="test"
    )
    claim = _ml_claim(
        case=case,
        claim_id="ml-l6-protocol-claim",
        statement=(
            "The synthetic candidate beats the baseline on the frozen test "
            "partition across the repeated seed set."
        ),
        outcome="pass",
    )
    assessment = adapter.validate_claim(claim, [result.evidence], contract)
    bundle = {
        "kind": "ml-research-memory-capture/v1",
        "category": "protocol",
        "provenance": "synthetic",
        "protocol": {
            "dataset": dataset,
            "case": case,
            "contract": contract.payload,
            "claim": claim,
        },
        "execution": {
            "artifact": result.artifact,
            "artifact_sha256": result.artifact_sha256,
            "evidence": result.evidence,
            "assessment": assessment.payload,
        },
        "limitations": [
            "This is an in-memory synthetic engineering fixture.",
            "It does not establish real-data validity or predictive performance.",
        ],
    }
    inputs = [
        {"name": "ml case", "kind": "case", "sha256": canonical_sha256(case)},
        {
            "name": "synthetic dataset",
            "kind": "data",
            "sha256": canonical_sha256(dataset),
        },
        {
            "name": "evaluation contract",
            "kind": "config",
            "sha256": contract.sha256,
        },
    ]
    return bundle, inputs


def _negative_result_bundle() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dataset = _classification_dataset()
    dataset["targets"] = [0.0 for _ in dataset["targets"]]
    case = _runner_case(dataset)
    _rename_case(case, "ml-l6-negative-result")
    adapter = MLAdapter()
    contract = adapter.build_evaluation_contract(case)
    result = run_synthetic_experiment(
        dataset, case, contract=contract, final_partition="test"
    )
    comparison = result.artifact["parity"]["candidate_minus_baseline"]
    if any(value != 0 for value in comparison.values()):
        raise AssertionError("negative-result fixture unexpectedly beats the baseline")
    claim = _ml_claim(
        case=case,
        claim_id="ml-l6-negative-result-claim",
        statement="The synthetic candidate did not outperform the baseline.",
        outcome="inconclusive",
    )
    assessment = adapter.validate_claim(claim, [result.evidence], contract)
    bundle = {
        "kind": "ml-research-memory-capture/v1",
        "category": "negative-result",
        "provenance": "synthetic",
        "protocol": {
            "dataset": dataset,
            "case": case,
            "contract": contract.payload,
            "claim": claim,
        },
        "execution": {
            "artifact": result.artifact,
            "artifact_sha256": result.artifact_sha256,
            "candidate_minus_baseline": comparison,
            "assessment": assessment.payload,
            "retained_despite_non_winning_outcome": True,
        },
        "limitations": [
            "The all-zero target fixture exists only to exercise negative-result retention.",
            "No empirical or predictive conclusion follows from the retained result.",
        ],
    }
    inputs = [
        {"name": "ml case", "kind": "case", "sha256": canonical_sha256(case)},
        {
            "name": "synthetic dataset",
            "kind": "data",
            "sha256": canonical_sha256(dataset),
        },
        {
            "name": "evaluation contract",
            "kind": "config",
            "sha256": contract.sha256,
        },
    ]
    return bundle, inputs


def _leakage_repair_bundle() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dataset = _classification_dataset()
    repaired = _runner_case(dataset)
    _rename_case(repaired, "ml-l6-leakage-repaired")
    unsafe = copy.deepcopy(repaired)
    unsafe["case_id"] = "ml-l6-leakage-unsafe"
    unsafe["selection"]["identity"] = "ml-l6-leakage-unsafe-selection"
    unsafe["selection"]["split_used"] = "test"
    _repin_selection(unsafe)

    adapter = MLAdapter()
    try:
        adapter.build_evaluation_contract(unsafe)
    except AdapterError as exc:
        if "selection-uses-test" not in str(exc):
            raise AssertionError("unsafe case failed for the wrong reason") from exc
    else:
        raise AssertionError("unsafe selection-on-test case unexpectedly passed")

    contract = adapter.build_evaluation_contract(repaired)
    result = run_synthetic_experiment(
        dataset, repaired, contract=contract, final_partition="test"
    )
    bundle = {
        "kind": "ml-research-memory-capture/v1",
        "category": "leakage-repair",
        "provenance": "synthetic",
        "protocol": {
            "unsafe_case": unsafe,
            "repaired_case": repaired,
            "repaired_contract": contract.payload,
            "dataset": dataset,
        },
        "execution": {
            "unsafe_outcome": "rejected",
            "unsafe_rule_id": "selection-uses-test",
            "repaired_outcome": "executed",
            "repaired_artifact": result.artifact,
            "repaired_artifact_sha256": result.artifact_sha256,
            "unsafe_case_sha256": canonical_sha256(unsafe),
            "repaired_case_sha256": canonical_sha256(repaired),
        },
        "limitations": [
            "The repair proves the declared synthetic topology gate only.",
            "It does not prove that an external training implementation matches the declaration.",
        ],
    }
    inputs = [
        {
            "name": "unsafe ml case",
            "kind": "case",
            "sha256": canonical_sha256(unsafe),
        },
        {
            "name": "repaired ml case",
            "kind": "case",
            "sha256": canonical_sha256(repaired),
        },
        {
            "name": "synthetic dataset",
            "kind": "data",
            "sha256": canonical_sha256(dataset),
        },
        {
            "name": "repaired evaluation contract",
            "kind": "config",
            "sha256": contract.sha256,
        },
    ]
    return bundle, inputs


def _reproduction_difference_bundle() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dataset = _classification_dataset()
    case_a = _runner_case(dataset)
    _rename_case(case_a, "ml-l6-replay-a")
    case_b = copy.deepcopy(case_a)
    case_b["case_id"] = "ml-l6-replay-b"
    case_b["selection"]["identity"] = "ml-l6-replay-b-selection"
    case_b["selection"]["seed_set"] = [11, 13, 17]
    case_b["tuning"]["seed_count"] = 3
    _repin_selection(case_b)

    adapter = MLAdapter()
    contract_a = adapter.build_evaluation_contract(case_a)
    contract_b = adapter.build_evaluation_contract(case_b)
    result_a1 = run_synthetic_experiment(
        dataset, case_a, contract=contract_a, final_partition="test"
    )
    result_a2 = run_synthetic_experiment(
        dataset, case_a, contract=contract_a, final_partition="test"
    )
    result_b = run_synthetic_experiment(
        dataset, case_b, contract=contract_b, final_partition="test"
    )
    if result_a1.artifact_sha256 != result_a2.artifact_sha256:
        raise AssertionError("same-protocol replay was not deterministic")
    if result_a1.artifact_sha256 == result_b.artifact_sha256:
        raise AssertionError("changed seed policy did not change the artifact pin")

    bundle = {
        "kind": "ml-research-memory-capture/v1",
        "category": "reproduction-difference",
        "provenance": "synthetic",
        "protocol": {
            "dataset": dataset,
            "case_a": case_a,
            "case_b": case_b,
            "contract_a": contract_a.payload,
            "contract_b": contract_b.payload,
        },
        "execution": {
            "artifact_a": result_a1.artifact,
            "artifact_b": result_b.artifact,
            "artifact_a_sha256": result_a1.artifact_sha256,
            "artifact_a_replay_sha256": result_a2.artifact_sha256,
            "artifact_b_sha256": result_b.artifact_sha256,
            "same_protocol_replay_equal": True,
            "changed_seed_policy": True,
            "cross_protocol_artifact_equal": False,
        },
        "limitations": [
            "The observed difference is attributed to an explicit seed-policy change.",
            "No cross-runtime numerical reproducibility claim is made.",
        ],
    }
    inputs = [
        {"name": "ml case a", "kind": "case", "sha256": canonical_sha256(case_a)},
        {"name": "ml case b", "kind": "case", "sha256": canonical_sha256(case_b)},
        {
            "name": "synthetic dataset",
            "kind": "data",
            "sha256": canonical_sha256(dataset),
        },
        {
            "name": "evaluation contract a",
            "kind": "config",
            "sha256": contract_a.sha256,
        },
        {
            "name": "evaluation contract b",
            "kind": "config",
            "sha256": contract_b.sha256,
        },
    ]
    return bundle, inputs


def _core_task() -> dict[str, Any]:
    payload = load_strict_json(_ML_TASK.read_bytes())
    payload["task_id"] = "task-ml-l6-research-memory"
    payload["study_id"] = _STUDY_ID
    payload["title"] = "Synthetic ML research-memory qualification"
    payload["statement"] = (
        "Can the existing experience machinery capture ML protocol, negative "
        "result, leakage repair, and reproduction-difference episodes?"
    )
    payload["completion_criteria"] = [
        "Four synthetic ML case packages rebuild byte-identically.",
        "Only cross-case evidence enters a candidate pattern.",
        "Three heuristics remain hypothetical shadow records.",
    ]
    payload["created_at"] = _TASK_AT
    return _validated(MLAdapter().normalize_task(payload).to_core_task_payload())


def _core_run(
    *,
    slug: str,
    task: dict[str, Any],
    inputs: list[dict[str, Any]],
) -> dict[str, Any]:
    return _validated(
        {
            "schema": "research-run/v1",
            "run_id": f"run-ml-l6-{slug}",
            "task": {
                "task_id": task["task_id"],
                "sha256": canonical_sha256(task),
            },
            "executor": runner_identity(),
            "environment": [
                {
                    "name": "execution envelope",
                    "version": "stdlib-in-memory-v1",
                    "details": "Synthetic deterministic evidence-pack replay.",
                }
            ],
            "inputs": [
                *inputs,
                {
                    "name": "runner identity",
                    "kind": "runner",
                    "sha256": canonical_sha256(runner_identity()),
                },
            ],
            "randomness": {
                "mode": "fixed_seed",
                "seed": 3,
                "details": "The complete seed set is pinned inside the ML case artifact.",
            },
            "started_at": _RUN_AT,
            "completed_at": _RUN_AT,
        }
    )


def _core_claim_and_evidence(
    *, slug: str, statement: str, bundle_bytes: bytes, inputs: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    claim_id = f"claim-ml-l6-{slug}"
    evidence = _validated(
        {
            "schema": "research-evidence/v1",
            "evidence_id": f"evidence-ml-l6-{slug}",
            "claim_ids": [claim_id],
            "producer": {"tool": "ml-l6-evidence-builder", "version": "1.0"},
            "inputs": inputs,
            "generated_at": _CASE_AT,
            "content_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
            "content_locator": f"evidence/ml/captures/{slug}.json",
            "applicability": "Synthetic Phase 5 L6 engineering qualification only.",
            "evidence_level": "engineering-only",
            "limitations": [
                "Synthetic inputs have no real-data acceptance evidence.",
                "This evidence does not establish predictive or production performance.",
            ],
        }
    )
    claim = _validated(
        {
            "schema": "research-claim/v1",
            "claim_id": claim_id,
            "claim_type": "engineering_claim",
            "statement": statement,
            "scope": "The frozen synthetic Phase 5 L6 evidence bundle.",
            "disposition": "supported",
            "evidence_maturity": "engineering_verified",
            "supporting_evidence": [
                {
                    "evidence_id": evidence["evidence_id"],
                    "sha256": canonical_sha256(evidence),
                }
            ],
            "limitations": [
                "The claim covers deterministic repository machinery only."
            ],
            "non_entailments": [
                "Does not establish real-data acceptance.",
                "Does not establish model generalization or market evidence.",
                "Does not authorize Skill publication, installation, or activation.",
            ],
            "created_at": _CASE_AT,
        }
    )
    return claim, evidence


def _observation_and_analysis(
    *, slug: str, run: dict[str, Any], facts: list[str], hypotheses: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    observation = _validated(
        {
            "schema": "research-failure-observation/v1",
            "observation_id": f"observation-ml-l6-{slug}",
            "run": {
                "run_id": run["run_id"],
                "sha256": canonical_sha256(run),
            },
            "observer": {"tool": "ml-l6-evidence-builder", "version": "1.0"},
            "facts": facts,
            "observed_at": _CASE_AT,
        }
    )
    analysis = _validated(
        {
            "schema": "research-failure-analysis/v1",
            "analysis_id": f"analysis-ml-l6-{slug}",
            "observation": {
                "observation_id": observation["observation_id"],
                "sha256": canonical_sha256(observation),
            },
            "hypotheses": hypotheses,
            "created_at": _CASE_AT,
        }
    )
    return observation, analysis


def _case_package(
    *,
    slug: str,
    task: dict[str, Any],
    run: dict[str, Any],
    claim: dict[str, Any],
    evidence: dict[str, Any],
    bundle: dict[str, Any],
    observations: list[dict[str, Any]] | None = None,
    analyses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    spec = _CASE_SPECS[slug]
    bundle_bytes = canonical_bytes(bundle)
    protocol_bytes = canonical_bytes(bundle["protocol"])
    timeline = [
        (_RUN_AT, "Synthetic protocol and comparison inputs were frozen."),
        (_CASE_AT, "The outcome and limitations were captured without promotion."),
    ]
    return capture_case(
        case_id=spec["case_id"],
        title=spec["title"],
        created_at=_CASE_AT,
        task=task,
        runs=[run],
        claims=[claim],
        evidence=[evidence],
        observations=observations or [],
        analyses=analyses or [],
        signature_summary=spec["signature_summary"],
        signature_sha256=hashlib.sha256(spec["signature_key"]).hexdigest(),
        signature_facets={"domain": "ml", "category": slug},
        inputs=[ArtifactInput("protocol.json", protocol_bytes)],
        outputs=[
            ArtifactInput(
                "capture.json",
                bundle_bytes,
                f"evidence/ml/captures/{slug}.json",
            )
        ],
        environment_tool=runner_identity()["tool"],
        environment_version=runner_identity()["version"],
        environment_details="Standard-library, deterministic, in-memory synthetic runner.",
        privacy_review_status="passed",
        export_mode="benchmark_candidate",
        eligibility=EligibilityInput(True, True, True, True),
        source_project="phase5-l6-synthetic",
        decision_timeline=timeline,
        open_questions=[
            "How does this behavior change with accepted real data and an external executor?"
        ],
    )


def _patterns(cases: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    source_cases = [cases["leakage-repair"], cases["reproduction-difference"]]
    distilled = distill_patterns(
        cases=source_cases,
        pattern_id="pattern-ml-pinned-comparison-v1",
        created_at=_PATTERN_AT,
        last_validated=_PATTERN_AT,
        scope="Synthetic ML protocol and replay comparison review.",
        preconditions=[
            "Compared cases expose data, case, contract, runner, and result pins."
        ],
        contraindications=[
            "Do not infer real-data model quality from synthetic replay evidence."
        ],
        successful_tactics=[
            "Compare exact protocol and evidence pins before interpreting a result difference."
        ],
        failed_tactics=[
            "Treating differently pinned runs as a same-protocol reproduction."
        ],
        evidence_grade="synthetic engineering evidence",
        evidence_rationale=(
            "Two independent synthetic cases demonstrate pin-first comparison discipline."
        ),
        confidence="low",
        transition_rationale="Initial cross-case distillation from two eligible ML cases.",
    )
    candidate = transition_pattern(
        pattern=distilled,
        new_pattern_id="pattern-ml-pinned-comparison-v2",
        status="candidate_pattern",
        transition_rationale=(
            "Two independent synthetic cases support candidate review; no active or Skill status."
        ),
        created_at=_CANDIDATE_AT,
        last_validated=_CANDIDATE_AT,
    )
    return distilled, candidate


def _heuristics(
    cases: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    specs = (
        {
            "slug": "protected-selection",
            "statement": "Stop comparison when model selection cites a protected final partition.",
            "scope": "ML selection-record review",
            "mode": "blocking",
            "evidence": ["The leakage-repair case records a selection-on-test rejection."],
            "exception": ["None for declared test or future-holdout selection."],
            "risk": "An unsafe selection record can contaminate the reported final evaluation.",
            "rollback": "Restore the validation-only selection record and rebuild every dependent pin.",
            "case": cases["leakage-repair"],
        },
        {
            "slug": "negative-result-retention",
            "statement": "Retain non-winning outcomes alongside successful synthetic runs.",
            "scope": "ML experiment evidence capture",
            "mode": "advisory",
            "evidence": ["The negative-result case preserves a zero-delta comparison."],
            "exception": ["Storage may be metrics-only when the raw payload is not exportable."],
            "risk": "Winner-only retention hides selection bias and failure frequency.",
            "rollback": "Restore the complete trial inventory from the frozen manifest and re-audit it.",
            "case": cases["negative-result"],
        },
        {
            "slug": "replay-pin-match",
            "statement": "Refuse same-protocol replay claims when any comparison pin differs.",
            "scope": "ML reproduction comparison",
            "mode": "blocking",
            "evidence": ["The reproduction case attributes a changed artifact to a changed seed policy."],
            "exception": ["A declared protocol-change comparison may proceed under a different claim."],
            "risk": "Configuration drift can be mislabeled as nondeterministic execution.",
            "rollback": "Restore the original protocol pins and rerun the deterministic comparison.",
            "case": cases["reproduction-difference"],
        },
    )
    all_versions: list[dict[str, Any]] = []
    tips: list[dict[str, Any]] = []
    for spec in specs:
        slug = spec["slug"]
        root = propose_heuristic(
            heuristic_id=f"heuristic-ml-{slug}-v1",
            statement=spec["statement"],
            scope=spec["scope"],
            mode=spec["mode"],
            evidence=spec["evidence"],
            exception=spec["exception"],
            risk=spec["risk"],
            rollback=spec["rollback"],
            transition_rationale="Initial synthetic lesson hypothesis.",
            regression_cases=[spec["case"]],
            created_at=_PATTERN_AT,
        )
        candidate = transition_heuristic(
            heuristic=root,
            new_heuristic_id=f"heuristic-ml-{slug}-v2",
            status="candidate",
            transition_rationale="Regression case is pinned; advance for shadow preparation.",
            created_at=_CANDIDATE_AT,
        )
        shadow = transition_heuristic(
            heuristic=candidate,
            new_heuristic_id=f"heuristic-ml-{slug}-v3",
            status="shadow",
            transition_rationale="Trial only as a hypothetical decision; no behavior change.",
            created_at=_SHADOW_AT,
        )
        all_versions.extend((root, candidate, shadow))
        tips.append(shadow)
    return all_versions, tips


def build_ml_research_memory_pack() -> dict[str, Any]:
    """Build the complete L6 ML subtree as canonical bytes."""

    task = _core_task()
    raw_bundles = {
        "protocol": _protocol_bundle(),
        "negative-result": _negative_result_bundle(),
        "leakage-repair": _leakage_repair_bundle(),
        "reproduction-difference": _reproduction_difference_bundle(),
    }

    files: dict[str, bytes] = {}
    records: list[dict[str, Any]] = [task]
    cases: dict[str, dict[str, Any]] = {}
    runs: dict[str, dict[str, Any]] = {}

    files["evidence/ml/records/task-ml-l6.json"] = canonical_bytes(task)
    for slug, (bundle, input_pins) in raw_bundles.items():
        bundle_bytes = canonical_bytes(bundle)
        files[f"evidence/ml/captures/{slug}.json"] = bundle_bytes
        run = _core_run(slug=slug, task=task, inputs=input_pins)
        runs[slug] = run
        claim, evidence = _core_claim_and_evidence(
            slug=slug,
            statement=_CASE_SPECS[slug]["statement"],
            bundle_bytes=bundle_bytes,
            inputs=input_pins,
        )
        observations: list[dict[str, Any]] = []
        analyses: list[dict[str, Any]] = []
        if slug == "leakage-repair":
            observation, analysis = _observation_and_analysis(
                slug=slug,
                run=run,
                facts=[
                    "The unsafe declaration used test for model selection.",
                    "The public Adapter entry rejected it with selection-uses-test.",
                    "The repaired declaration used validation and produced a result artifact.",
                ],
                hypotheses=[
                    "The changed selection partition explains the unsafe-to-safe outcome difference."
                ],
            )
            observations.append(observation)
            analyses.append(analysis)
        elif slug == "reproduction-difference":
            observation, analysis = _observation_and_analysis(
                slug=slug,
                run=run,
                facts=[
                    "Two replays of protocol A produced the same artifact hash.",
                    "Protocol B declared a different seed set and produced a different artifact hash.",
                ],
                hypotheses=[
                    "The explicit seed-policy change explains the cross-protocol artifact difference."
                ],
            )
            observations.append(observation)
            analyses.append(analysis)
        case = _case_package(
            slug=slug,
            task=task,
            run=run,
            claim=claim,
            evidence=evidence,
            bundle=bundle,
            observations=observations,
            analyses=analyses,
        )
        cases[slug] = case
        record_group = [run, claim, evidence, *observations, *analyses, case]
        records.extend(record_group)
        files[f"evidence/ml/records/run-ml-l6-{slug}.json"] = canonical_bytes(run)
        files[f"evidence/ml/records/claim-ml-l6-{slug}.json"] = canonical_bytes(claim)
        files[f"evidence/ml/records/evidence-ml-l6-{slug}.json"] = canonical_bytes(evidence)
        for observation in observations:
            files[
                f"evidence/ml/records/observation-ml-l6-{slug}.json"
            ] = canonical_bytes(observation)
        for analysis in analyses:
            files[
                f"evidence/ml/records/analysis-ml-l6-{slug}.json"
            ] = canonical_bytes(analysis)
        files[f"evidence/ml/cases/{_CASE_SPECS[slug]['case_id']}.json"] = canonical_bytes(case)

    patterns = _patterns(cases)
    records.extend(patterns)
    for pattern in patterns:
        files[f"evidence/ml/patterns/{pattern['pattern_id']}.json"] = canonical_bytes(pattern)

    heuristic_versions, heuristic_tips = _heuristics(cases)
    records.extend(heuristic_versions)
    for heuristic in heuristic_versions:
        files[
            f"evidence/ml/heuristics/{heuristic['heuristic_id']}.json"
        ] = canonical_bytes(heuristic)

    assert_registry_clean(heuristic_versions, now=_SHADOW_AT)
    lint_report = lint_heuristics(heuristic_versions, now=_SHADOW_AT)
    files["evidence/ml/shadow/heuristic-lint-report.json"] = canonical_bytes(
        lint_report.report_entry
    )
    observations = [
        {
            "heuristic_id": heuristic["heuristic_id"],
            "hypothetical_decision": "would stop or annotate the synthetic review",
            "expected_difference": "the evidence package would expose the guarded limitation",
        }
        for heuristic in heuristic_tips
    ]
    shadow_report = record_shadow_report(
        heuristics=heuristic_tips,
        run=runs["protocol"],
        observations=observations,
        recorded_at=_SHADOW_AT,
    )
    files["evidence/ml/shadow/shadow-report.json"] = canonical_bytes(
        shadow_report.payload
    )

    return {
        "files": files,
        "records": records,
        "cases": cases,
        "patterns": patterns,
        "heuristic_versions": heuristic_versions,
        "heuristic_tips": heuristic_tips,
        "lint_report": lint_report,
        "shadow_report": shadow_report,
        "bundles": {slug: bundle for slug, (bundle, _) in raw_bundles.items()},
    }


__all__ = ["build_ml_research_memory_pack"]
