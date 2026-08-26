"""P7C2 public synthetic forward-suite orchestration.

``run_skill_forward_suite`` is the module's single high-leverage interface.
It expands one frozen suite into the complete ``case x seed`` observation
grid, preflights every cell before execution, delegates each pair to the P7C1
forward-test seam, and assembles the existing ``suite-comparison/v1`` record
only when every cell produced both result and run records.

This module is deliberately synthetic.  It does not materialize Candidate
bytes, execute a real Agent, perform an independent review, inspect hidden
cases, or authorize publication, installation, activation, or promotion.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from research_evolution.core import CoreError, Record, canonical_bytes, load_record
from research_evolution.evaluation import (
    Envelope,
    GateConfig,
    SuiteComparePolicy,
    compare_suite,
)

from .envelope_closure import EvaluationEnvelopeClosureReceipt
from .skill_candidate import SkillCandidateBundle
from .skill_forward_test import (
    SkillForwardTestAdapter,
    SkillForwardTestError,
    SkillForwardTestOutcome,
    SkillForwardTestPlan,
    _preflight,
    run_skill_forward_test,
)
from .skill_semantic_review import SkillSemanticReviewAttestation
from .skill_static_validation import SkillStaticValidationReceipt

_LIMITATIONS = (
    "The complete grid contains synthetic conformance observations only.",
    "The orchestration reuses P7C1 adapters and does not execute a real Agent.",
    "Candidate payload bytes are verified but never materialized or runtime-loaded.",
    "The public comparison is not a Hidden Evaluator or PromotionDecision.",
    "No publication, installation, activation, promotion, or external adoption is authorized.",
)


class SkillForwardSuiteError(ValueError):
    """A P7C2 suite plan violates the fail-closed orchestration contract."""


@dataclass(frozen=True)
class ForwardSuiteCase:
    """One frozen case-specific contract reused for every preregistered seed."""

    case: Mapping[str, Any]
    case_input: bytes
    scoring: Mapping[str, Any]
    gate_config: GateConfig
    trigger_mode: str
    expected_route: str


@dataclass(frozen=True)
class SkillForwardSuitePlan:
    """All immutable inputs consumed by :func:`run_skill_forward_suite`."""

    suite_test_id: str
    candidate_manifest: Record | Mapping[str, Any] | str | bytes | bytearray
    candidate_bundle: SkillCandidateBundle | Record | Mapping[str, Any] | str | bytes | bytearray
    candidate_payload: Mapping[str, bytes]
    static_validation_receipt: (
        SkillStaticValidationReceipt | Record | Mapping[str, Any] | str | bytes | bytearray
    )
    semantic_review_attestation: (
        SkillSemanticReviewAttestation | Record | Mapping[str, Any] | str | bytes | bytearray
    )
    envelope_closure_receipt: (
        EvaluationEnvelopeClosureReceipt | Record | Mapping[str, Any] | str | bytes | bytearray
    )
    suite: Mapping[str, Any]
    cases: tuple[ForwardSuiteCase, ...]
    envelope: Envelope
    compare_policy: SuiteComparePolicy
    max_total_attempts: int
    comparison_id: str
    title: str
    generated_at: str


@dataclass(frozen=True)
class ForwardSuiteCellOutcome:
    """One case/seed cell and its paired P7C1 outcome."""

    case_id: str
    seed: int
    outcome: SkillForwardTestOutcome


@dataclass(frozen=True)
class SkillForwardSuiteOutcome:
    """A non-publishable aggregate over existing evaluation records."""

    status: str
    blockers: tuple[str, ...]
    cells: tuple[ForwardSuiteCellOutcome, ...]
    suite_comparison: Mapping[str, Any] | None
    planned_cells: int
    planned_max_attempts: int
    observed_attempts: int
    limitations: tuple[str, ...] = _LIMITATIONS

    @property
    def claims(self) -> dict[str, bool]:
        return {
            "synthetic_suite_orchestrated": self.observed_attempts > 0,
            "complete_case_seed_grid_observed": self.suite_comparison is not None,
            "real_agent_execution_observed": False,
            "real_independent_semantic_review_completed": False,
            "hidden_evaluation_completed": False,
            "candidate_materialized": False,
            "runtime_loaded": False,
            "promotion_authorized": False,
            "publication_authorized": False,
            "installation_authorized": False,
            "activation_authorized": False,
        }


def _load_suite(suite: Mapping[str, Any]) -> Record:
    try:
        record = load_record(canonical_bytes(dict(suite)))
    except (CoreError, TypeError, ValueError) as exc:
        raise SkillForwardSuiteError(f"invalid frozen suite: {exc}") from exc
    if record.schema_id != "suite/v1":
        raise SkillForwardSuiteError(
            f"expected suite/v1 for frozen suite, got {record.schema_id!r}"
        )
    return record


def _load_case(case: Mapping[str, Any]) -> Record:
    try:
        record = load_record(canonical_bytes(dict(case)))
    except (CoreError, TypeError, ValueError) as exc:
        raise SkillForwardSuiteError(f"invalid evaluation case: {exc}") from exc
    if record.schema_id != "evaluation-case/v1":
        raise SkillForwardSuiteError(f"expected evaluation-case/v1, got {record.schema_id!r}")
    return record


def _validate_budget(plan: SkillForwardSuitePlan) -> tuple[int, int]:
    if (
        isinstance(plan.max_total_attempts, bool)
        or not isinstance(plan.max_total_attempts, int)
        or plan.max_total_attempts <= 0
    ):
        raise SkillForwardSuiteError("max_total_attempts must be a positive integer")
    planned_cells = len(plan.cases) * len(plan.compare_policy.expected_seeds)
    worst_case_attempts = planned_cells * 2 * (plan.envelope.retry_attempts + 1)
    if worst_case_attempts > plan.max_total_attempts:
        raise SkillForwardSuiteError("frozen suite retry envelope exceeds max_total_attempts")
    return planned_cells, worst_case_attempts


def _validate_metric_contract(
    case_plan: ForwardSuiteCase,
    policy: SuiteComparePolicy,
) -> None:
    oracle = case_plan.scoring.get("oracle")
    if not isinstance(oracle, Mapping):
        raise SkillForwardSuiteError("every P7C2 case requires an oracle mapping")
    actual = {f"exact_match:{field}" for field in oracle}
    expected = {metric.dimension for metric in policy.metrics}
    if actual != expected:
        raise SkillForwardSuiteError(
            "case score dimensions must exactly equal the preregistered metrics"
        )


def _derive_cell_plans(
    plan: SkillForwardSuitePlan,
    adapter: SkillForwardTestAdapter,
) -> tuple[list[tuple[str, int, SkillForwardTestPlan]], int, int]:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", plan.suite_test_id) is None:
        raise SkillForwardSuiteError(
            "suite_test_id must be a portable identifier of at most 64 characters"
        )
    if plan.envelope.seed is not None:
        raise SkillForwardSuiteError(
            "suite envelope seed must be unset; expected_seeds defines the grid"
        )
    if not plan.cases:
        raise SkillForwardSuiteError("suite cases must not be empty")
    if not any(metric.role == "guardrail" for metric in plan.compare_policy.metrics):
        raise SkillForwardSuiteError("P7C2 requires at least one guardrail metric")

    planned_cells, worst_case_attempts = _validate_budget(plan)
    suite_record = _load_suite(plan.suite)
    suite_members = {
        item["evaluation_case_id"]: item["sha256"] for item in suite_record.data["cases"]
    }
    if len(suite_members) != len(suite_record.data["cases"]):
        raise SkillForwardSuiteError("frozen suite contains duplicate case identifiers")

    loaded_cases: list[tuple[ForwardSuiteCase, Record]] = []
    seen_case_ids: set[str] = set()
    for case_plan in plan.cases:
        case_record = _load_case(case_plan.case)
        case_id = case_record.data["evaluation_case_id"]
        if case_id in seen_case_ids:
            raise SkillForwardSuiteError("suite plan contains duplicate case identifiers")
        seen_case_ids.add(case_id)
        if suite_members.get(case_id) != case_record.sha256:
            raise SkillForwardSuiteError("suite plan case is not pinned by the frozen suite")
        _validate_metric_contract(case_plan, plan.compare_policy)
        loaded_cases.append((case_plan, case_record))
    if seen_case_ids != set(suite_members):
        raise SkillForwardSuiteError(
            "suite plan cases must equal the frozen suite membership exactly"
        )

    cells: list[tuple[str, int, SkillForwardTestPlan]] = []
    for case_index, (case_plan, case_record) in enumerate(
        sorted(loaded_cases, key=lambda item: item[1].data["evaluation_case_id"])
    ):
        case_id = case_record.data["evaluation_case_id"]
        for seed_index, seed in enumerate(sorted(plan.compare_policy.expected_seeds)):
            cell_plan = SkillForwardTestPlan(
                test_id=f"{plan.suite_test_id}:{case_index}:{seed_index}",
                candidate_manifest=plan.candidate_manifest,
                candidate_bundle=plan.candidate_bundle,
                candidate_payload=plan.candidate_payload,
                static_validation_receipt=plan.static_validation_receipt,
                semantic_review_attestation=plan.semantic_review_attestation,
                envelope_closure_receipt=plan.envelope_closure_receipt,
                case=case_plan.case,
                suite=plan.suite,
                case_input=case_plan.case_input,
                envelope=replace(plan.envelope, seed=seed),
                scoring=case_plan.scoring,
                gate_config=case_plan.gate_config,
                generated_at=plan.generated_at,
                trigger_mode=case_plan.trigger_mode,
                expected_route=case_plan.expected_route,
            )
            try:
                _preflight(cell_plan, adapter)
            except SkillForwardTestError as exc:
                raise SkillForwardSuiteError(
                    f"cell preflight failed for {case_id!r}, seed {seed}: {exc}"
                ) from exc
            cells.append((case_id, seed, cell_plan))
    return cells, planned_cells, worst_case_attempts


def _count_attempts(outcome: SkillForwardTestOutcome) -> int:
    total = 0
    for arm in (outcome.baseline, outcome.candidate):
        if arm is not None:
            total += int(arm.attempt_payload["execution"]["attempts"])
    return total


def _exact_candidate_ref(
    runs: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> dict[str, str]:
    references = {(run["candidate"]["candidate_id"], run["candidate"]["sha256"]) for run in runs}
    if len(references) != 1:
        raise SkillForwardSuiteError(
            f"{label} observations do not pin exactly one candidate artifact"
        )
    candidate_id, sha256 = references.pop()
    return {"candidate_id": candidate_id, "sha256": sha256}


def run_skill_forward_suite(
    plan: SkillForwardSuitePlan,
    adapter: SkillForwardTestAdapter,
) -> SkillForwardSuiteOutcome:
    """Run the complete synthetic case/seed grid and compare only complete runs."""

    cells, planned_cells, planned_max_attempts = _derive_cell_plans(plan, adapter)
    observations: list[ForwardSuiteCellOutcome] = []
    for case_id, seed, cell_plan in cells:
        observations.append(
            ForwardSuiteCellOutcome(
                case_id=case_id,
                seed=seed,
                outcome=run_skill_forward_test(cell_plan, adapter),
            )
        )

    observed_attempts = sum(_count_attempts(cell.outcome) for cell in observations)
    rejected = [cell for cell in observations if cell.outcome.status == "prerequisite_rejected"]
    if rejected:
        blockers = tuple(
            sorted(
                {
                    f"{cell.case_id}@{cell.seed}:{blocker}"
                    for cell in rejected
                    for blocker in cell.outcome.blockers
                }
            )
        )
        return SkillForwardSuiteOutcome(
            status="prerequisite_rejected",
            blockers=blockers,
            cells=tuple(observations),
            suite_comparison=None,
            planned_cells=planned_cells,
            planned_max_attempts=planned_max_attempts,
            observed_attempts=observed_attempts,
        )

    complete = all(
        cell.outcome.baseline is not None
        and cell.outcome.candidate is not None
        and cell.outcome.baseline.run_payload is not None
        and cell.outcome.candidate.run_payload is not None
        for cell in observations
    )
    if not complete:
        return SkillForwardSuiteOutcome(
            status="execution_inconclusive",
            blockers=("complete_case_seed_result_grid_unavailable",),
            cells=tuple(observations),
            suite_comparison=None,
            planned_cells=planned_cells,
            planned_max_attempts=planned_max_attempts,
            observed_attempts=observed_attempts,
        )

    champion_runs = [
        cell.outcome.baseline.run_payload
        for cell in observations
        if cell.outcome.baseline is not None and cell.outcome.baseline.run_payload is not None
    ]
    challenger_runs = [
        cell.outcome.candidate.run_payload
        for cell in observations
        if cell.outcome.candidate is not None and cell.outcome.candidate.run_payload is not None
    ]
    champion_ref = _exact_candidate_ref(champion_runs, label="baseline")
    challenger_ref = _exact_candidate_ref(challenger_runs, label="Candidate")
    try:
        comparison = compare_suite(
            suite=plan.suite,
            champion_candidate=champion_ref,
            challenger_candidate=challenger_ref,
            champion_runs=champion_runs,
            challenger_runs=challenger_runs,
            policy=plan.compare_policy,
            comparison_id=plan.comparison_id,
            title=plan.title,
            conclusion="synthetic_conformance_only_no_promotion",
            generated_at=plan.generated_at,
            limitations=_LIMITATIONS,
        )
    except (CoreError, TypeError, ValueError) as exc:
        raise SkillForwardSuiteError(f"suite comparison failed closed: {exc}") from exc

    return SkillForwardSuiteOutcome(
        status="suite_comparison_completed",
        blockers=(),
        cells=tuple(observations),
        suite_comparison=comparison,
        planned_cells=planned_cells,
        planned_max_attempts=planned_max_attempts,
        observed_attempts=observed_attempts,
    )


__all__ = [
    "ForwardSuiteCase",
    "ForwardSuiteCellOutcome",
    "SkillForwardSuiteError",
    "SkillForwardSuiteOutcome",
    "SkillForwardSuitePlan",
    "run_skill_forward_suite",
]
