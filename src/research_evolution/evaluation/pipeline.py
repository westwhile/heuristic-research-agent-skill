"""Attempt/result assembly and legacy Champion/Challenger comparison.

This module wires the E3–E6 machinery into the record layer of E2:

- :func:`evaluate_case` replays one frozen artifact against one case and
  always assembles ``evaluation-attempt/v1`` once replay begins. It adds
  ``evaluation-result/v1`` only after scoring succeeds. Successful legacy
  callers continue to receive the frozen ``evaluation-run/v1`` payload.
  Publishing stays with the caller through the existing core surface.
- :func:`compare` is a fail-closed compatibility sentinel. CR5 retired
  construction of ``comparison-report/v1`` because metric dimensions are
  not paired observations; suite-level comparison lives in the separate
  :mod:`.suite_comparison` deep module.

Two contract facts shape the assembly:

- **Attempt always, result optional**: replay/scoring failure is published as
  an attempt with zero or more real output references and a diagnostic. No
  output hash or score is fabricated. A result exists only when a complete
  output was scored. ``run_payload`` remains the compatibility projection
  for legacy pass/fail consumers and is otherwise ``None``.
- **Separate candidate and output tracks**: ``candidate.sha256`` echoes
  the caller's immutable candidate descriptor; legacy per-case replay may
  use the raw output artifact as that descriptor. Suite comparison instead
  requires a stable candidate artifact/manifest across the whole arm. The
  caller binds any manifest to its raw replay members, whose bytes are
  verified by ``run_replay(artifact, artifact_sha256, ...)``. The record's
  ``output.output_sha256`` binds the canonical bytes the scorer consumed.
  Historical per-output descriptors are not rewritten into manifest pins.

Calibration evidence is single-sourced: one ``calibration_sha256`` feeds
both :func:`~.scorers.package_judge_scores` and
:func:`~.scorers.scorer_identity`, so the scores and the identity can
never disagree about which calibration artifact backs them.
"""

from __future__ import annotations

import platform
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from research_evolution.core import (
    canonical_bytes,
    load_record,
    load_strict_json,
)

from .envelope import Envelope
from .gates import (
    GATES,
    GateConfig,
    GateResult,
    assemble_verdict,
    evaluate_gates,
    gate_results_payload,
)
from .runner import ReplayResult, run_replay, runner_identity
from .scorers import (
    ScoreEntry,
    package_judge_scores,
    package_rubric_scores,
    score_vector_payload,
    score_with_checker,
    score_with_oracle,
    scorer_identity,
    validate_score_vector,
)

# Exactly the ``levels_covered`` item enum shared by both schemas.
LEVELS = frozenset({"L0", "L1"})

_LEGACY_UNPUBLISHABLE_REASON = (
    "legacy evaluation-run/v1 cannot represent verdict {verdict} without "
    "both a complete output and a non-empty score vector; the "
    "evaluation-attempt/v1 record remains publishable and no values were "
    "fabricated"
)


def interpreter_environment() -> dict[str, str]:
    """The default ``environment`` value: binds the run record to the
    interpreter that produced it (resampling reproducibility is a
    per-runtime fact)."""
    return {
        "interpreter": platform.python_implementation(),
        "interpreter_version": platform.python_version(),
    }


def _record_sha256(payload: Mapping[str, Any], what: str) -> str:
    """Validate *payload* against its core schema and return the store
    hash — fail fast on a malformed case/suite/run document.

    Serialization goes through the core canonical machine, not bare
    ``json.dumps``: a record reloaded from a store carries ``Decimal``
    values (the strict parser's frozen numeric model), and the canonical
    serializer is the one component that writes them faithfully — the
    store's own round-trip depends on it (R34).
    """
    try:
        return load_record(canonical_bytes(payload)).sha256
    except Exception as exc:
        raise ValueError(
            f"{what} payload is not a valid core record: {exc}"
        ) from exc


@dataclass(frozen=True)
class PipelineOutcome:
    """The complete outcome of one case evaluation.

    ``attempt_payload`` always exists after replay starts;
    ``result_payload`` exists only after scoring succeeds. ``run_payload``
    is the backward-compatible pass/fail projection.
    """

    run_id: str
    verdict: str
    replay: ReplayResult
    score_entries: tuple[ScoreEntry, ...] | None
    gate_results: tuple[GateResult, ...]
    scorer_id: dict[str, str]
    attempt_payload: dict[str, Any]
    result_payload: dict[str, Any] | None
    run_payload: dict[str, Any] | None
    unpublishable_reason: str | None


@dataclass(frozen=True)
class _PreparedEvaluation:
    """Validated, side-effect-free inputs shared by replay and live seams."""

    run_id: str
    case: Mapping[str, Any]
    suite: Mapping[str, Any]
    candidate: Mapping[str, str]
    envelope: Envelope
    scoring: Mapping[str, Any]
    gate_config: GateConfig
    generated_at: str
    levels_covered: tuple[str, ...]
    case_sha: str
    suite_sha: str
    case_id: str
    level: str
    scorer_id: dict[str, str]
    environment: dict[str, Any]
    envelope_echo: dict[str, Any]


def _prepare_evaluation(
    *,
    run_id: str,
    case: Mapping[str, Any],
    suite: Mapping[str, Any],
    candidate: Mapping[str, str],
    envelope: Envelope,
    scoring: Mapping[str, Any],
    gate_config: GateConfig,
    generated_at: str,
    levels_covered: Sequence[str] = ("L0", "L1"),
    environment: Mapping[str, Any] | None = None,
) -> _PreparedEvaluation:
    """Validate and freeze every input before any runner is started."""

    case_sha = _record_sha256(case, "case")
    suite_sha = _record_sha256(suite, "suite")
    case_id = case["evaluation_case_id"]
    membership = [
        entry
        for entry in suite["cases"]
        if entry["evaluation_case_id"] == case_id
    ]
    if not membership:
        raise ValueError(f"case {case_id!r} is not a member of the suite")
    if membership[0]["sha256"] != case_sha:
        raise ValueError(f"suite pin for case {case_id!r} does not match")

    level = scoring.get("level")
    contract_level = case["evaluation_contract"]["scorer_level"]
    if level != contract_level:
        raise ValueError(
            f"scoring level {level!r} violates the case contract level "
            f"{contract_level!r}"
        )
    unknown_levels = sorted(set(levels_covered) - LEVELS)
    if not levels_covered or unknown_levels:
        raise ValueError(f"levels_covered must be non-empty L0/L1 values: {unknown_levels}")

    calibration_sha256 = scoring.get("calibration_sha256")
    scorer_id = scorer_identity(level, calibration_sha256=calibration_sha256)

    environment_payload = (
        dict(environment) if environment is not None else interpreter_environment()
    )
    envelope_echo: dict[str, Any] = {
        "envelope_sha256": envelope.canonical_sha256,
        "timeout_ms": envelope.timeout_ms,
        "max_output_bytes": envelope.max_output_bytes,
        "retry_attempts": envelope.retry_attempts,
    }
    if envelope.seed is not None:
        envelope_echo["seed"] = envelope.seed
    if envelope.notes is not None:
        envelope_echo["notes"] = envelope.notes

    return _PreparedEvaluation(
        run_id=run_id,
        case=case,
        suite=suite,
        candidate=candidate,
        envelope=envelope,
        scoring=scoring,
        gate_config=gate_config,
        generated_at=generated_at,
        levels_covered=tuple(levels_covered),
        case_sha=case_sha,
        suite_sha=suite_sha,
        case_id=case_id,
        level=level,
        scorer_id=scorer_id,
        environment=environment_payload,
        envelope_echo=envelope_echo,
    )


def _assemble_observation(
    prepared: _PreparedEvaluation,
    replay: ReplayResult,
    runner_id: Mapping[str, str],
) -> PipelineOutcome:
    """Score and record one already-observed runner outcome.

    This is an internal seam.  Replay and P7C1 live-execution adapters cross
    it only after their inputs have passed :func:`_prepare_evaluation`.
    """

    run_id = prepared.run_id
    suite = prepared.suite
    candidate = prepared.candidate
    scoring = prepared.scoring
    gate_config = prepared.gate_config
    generated_at = prepared.generated_at
    levels_covered = prepared.levels_covered
    case_sha = prepared.case_sha
    suite_sha = prepared.suite_sha
    case_id = prepared.case_id
    level = prepared.level
    scorer_id = prepared.scorer_id
    environment_payload = prepared.environment
    envelope_echo = prepared.envelope_echo
    calibration_sha256 = scoring.get("calibration_sha256")

    entries: tuple[ScoreEntry, ...] | None = None
    scoring_error: str | None = None
    if replay.ok:
        try:
            output = load_strict_json(replay.output_bytes or b"")
            if level == "oracle":
                entries = score_with_oracle(output, scoring["oracle"])
            elif level == "deterministic_checker":
                entries = score_with_checker(output, scoring["spec"])
            elif level == "structured_rubric":
                entries = package_rubric_scores(scoring["scores"])
            else:
                entries = package_judge_scores(
                    scoring["scores"], calibration_sha256
                )
            validate_score_vector(entries)
        except (KeyError, TypeError, ValueError) as exc:
            # Do not echo caller-controlled scorer configuration or output
            # values into an append-only diagnostic. The structured class
            # identifies the failure; any detailed trace belongs in a
            # separately governed, hash-bound artifact.
            scoring_error = (
                f"{type(exc).__name__}: scoring configuration or output "
                "could not be scored"
            )

    gate_results = evaluate_gates(
        replay=replay,
        score_vector=entries,
        runner_id=runner_id,
        scorer_id=scorer_id,
        config=gate_config,
    )
    verdict = (
        "error"
        if scoring_error is not None
        else assemble_verdict(replay, gate_results, entries)
    )

    complete_outputs: list[dict[str, str]] = []
    diagnostics: list[dict[str, str]] = []
    if replay.ok:
        if replay.output_sha256 is None:
            raise RuntimeError("successful replay omitted output_sha256")
        complete_outputs.append({"sha256": replay.output_sha256})
    if scoring_error is not None:
        execution_status = "scorer_error"
        diagnostics.append(
            {
                "detail": scoring_error,
            }
        )
    elif replay.ok:
        execution_status = "completed"
    else:
        execution_status = replay.error_class or "runner_error"
        diagnostics.append(
            {
                "detail": replay.error_detail or "replay failed without detail",
            }
        )

    attempt_payload: dict[str, Any] = {
        "schema": "evaluation-attempt/v1",
        "evaluation_attempt_id": f"{run_id}-attempt",
        "case": {"evaluation_case_id": case_id, "sha256": case_sha},
        "suite": {"suite_id": suite["suite_id"], "sha256": suite_sha},
        "candidate": dict(candidate),
        "envelope": envelope_echo,
        "runner": dict(runner_id),
        "scorer": scorer_id,
        "environment": environment_payload,
        "execution": {
            "status": execution_status,
            "attempts": replay.attempts,
            "complete_outputs": complete_outputs,
            "partial_outputs": [],
            "artifacts": [],
            "diagnostics": diagnostics,
        },
        "gate_results": gate_results_payload(gate_results),
        "verdict": verdict,
        "levels_covered": list(levels_covered),
        "generated_at": generated_at,
    }
    attempt_sha = _record_sha256(attempt_payload, "assembled attempt")

    result_payload: dict[str, Any] | None = None
    if replay.ok and scoring_error is None and entries is not None:
        result_payload = {
            "schema": "evaluation-result/v1",
            "evaluation_result_id": f"{run_id}-result",
            "attempt": {
                "evaluation_attempt_id": f"{run_id}-attempt",
                "sha256": attempt_sha,
            },
            "score_vector": score_vector_payload(entries),
            "generated_at": generated_at,
        }
        _record_sha256(result_payload, "assembled result")

    run_payload: dict[str, Any] | None = None
    unpublishable_reason: str | None = None
    if verdict in ("pass", "fail"):
        run_payload = {
            "schema": "evaluation-run/v1",
            "evaluation_run_id": run_id,
            "case": {"evaluation_case_id": case_id, "sha256": case_sha},
            "suite": {"suite_id": suite["suite_id"], "sha256": suite_sha},
            "candidate": dict(candidate),
            "envelope": envelope_echo,
            "runner": dict(runner_id),
            "environment": environment_payload,
            "output": {"output_sha256": replay.output_sha256},
            "scorer": scorer_id,
            "score_vector": score_vector_payload(entries or ()),
            "gate_results": gate_results_payload(gate_results),
            "verdict": verdict,
            "levels_covered": list(levels_covered),
            "generated_at": generated_at,
        }
        # Validate the assembled product, not just the inputs (R33-P3): a
        # payload this function declares schema-shaped must actually be.
        _record_sha256(run_payload, "assembled run")
    else:
        unpublishable_reason = _LEGACY_UNPUBLISHABLE_REASON.format(verdict=verdict)

    return PipelineOutcome(
        run_id=run_id,
        verdict=verdict,
        replay=replay,
        score_entries=entries,
        gate_results=gate_results,
        scorer_id=scorer_id,
        attempt_payload=attempt_payload,
        result_payload=result_payload,
        run_payload=run_payload,
        unpublishable_reason=unpublishable_reason,
    )


def evaluate_case(
    *,
    run_id: str,
    case: Mapping[str, Any],
    suite: Mapping[str, Any],
    candidate: Mapping[str, str],
    artifact: bytes,
    artifact_sha256: str,
    envelope: Envelope,
    scoring: Mapping[str, Any],
    gate_config: GateConfig,
    generated_at: str,
    levels_covered: Sequence[str] = ("L0", "L1"),
    environment: Mapping[str, Any] | None = None,
) -> PipelineOutcome:
    """Replay, score, gate, and assemble attempt/result record payloads.

    *scoring* declares the level and its inputs:
    ``{"level": "oracle", "oracle": {...}}``,
    ``{"level": "deterministic_checker", "spec": {...}}``,
    ``{"level": "structured_rubric", "scores": {...}}``, or
    ``{"level": "calibrated_judge", "scores": {...},
    "calibration_sha256": "..."}``. The level must equal the case's
    ``evaluation_contract.scorer_level`` — the case contract, not the
    caller's mood, decides how its outputs are scored.
    """

    prepared = _prepare_evaluation(
        run_id=run_id,
        case=case,
        suite=suite,
        candidate=candidate,
        envelope=envelope,
        scoring=scoring,
        gate_config=gate_config,
        generated_at=generated_at,
        levels_covered=levels_covered,
        environment=environment,
    )
    replay = run_replay(artifact, artifact_sha256, envelope)
    return _assemble_observation(prepared, replay, runner_identity())


@dataclass(frozen=True)
class ComparePolicy:
    """The traced comparison policy: which statistics, with what seed and
    parameters. ``seed`` is required — no untraced resampling."""

    seed: int
    methods: tuple[str, ...] = ("paired_bootstrap",)
    resamples: int = 2000
    confidence: float = 0.95
    rare_event: tuple[int, int] | None = None  # (events, trials)


def compare(
    *,
    champion: Mapping[str, Any],
    challenger: Mapping[str, Any],
    policy: ComparePolicy,
    report_id: str,
    title: str,
    conclusion: str,
    limitations: Sequence[str] = (),
    generated_at: str,
) -> dict[str, Any]:
    """Reject the retired per-run inferential comparison interface.

    ``comparison-report/v1`` remains loadable as an immutable historical
    family, but treating metric dimensions as paired observations is not
    statistically valid. New comparisons must use ``compare_suite``.
    """
    raise ValueError(
        "comparison-report/v1 construction is retired: metric dimensions are not "
        "observations; use compare_suite() with case/seed/envelope pairs"
    )


def _fold_gate_summary(
    champion: Mapping[str, Any], challenger: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Fold both runs' gate results into the report's gate summary.

    ``comparison-report/v1`` allows only pass/fail in ``gate_summary``;
    the folding rule is: any fail fails the gate (reasons joined),
    otherwise any pass passes it, and a gate both sides marked
    ``not_applicable`` is omitted — only decidable gates are listed.
    """
    summary: list[dict[str, Any]] = []
    for gate in GATES:
        sides = []
        for run in (champion, challenger):
            for entry in run["gate_results"]:
                if entry["gate"] == gate:
                    sides.append(entry)
        results = {entry["result"] for entry in sides}
        if "fail" in results:
            reasons = [
                entry.get("reason", "")
                for entry in sides
                if entry["result"] == "fail"
            ]
            item: dict[str, Any] = {"gate": gate, "result": "fail"}
            if any(reasons):
                item["reason"] = "; ".join(r for r in reasons if r)
            summary.append(item)
        elif "pass" in results:
            summary.append({"gate": gate, "result": "pass"})
    return summary
