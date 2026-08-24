"""Hard gates and run-verdict assembly (ADR-0006 decision 8).

Six hard gates — ``integrity``, ``critical_safety``, ``regression``,
``resource``, ``privacy``, ``evaluator_integrity`` — are evaluated for
every run, in this fixed order, and any ``fail`` fails the run as a
whole. Every gate always reports: a gate that cannot judge (no output to
scan, no floors configured, no expectations supplied) reports
``not_applicable`` rather than staying silent, because an unlisted gate
is indistinguishable from a skipped one.

Gate inputs come from the E3 replay outcome, the E4 score vector, and a
caller-supplied :class:`GateConfig`; every check is a deterministic pure
function of those inputs. A failed gate must carry a reason; the schema
makes ``reason`` optional, this layer makes it mandatory on failure.

Verdict assembly (attempt/result and legacy run projections): a replay
failure is ``error``; any failed gate is ``fail``; a replayed but unscored run is
``inconclusive`` — a legitimate terminal, never forced into pass/fail;
otherwise ``pass``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .runner import ReplayResult
from .scorers import ScoreEntry

# Exactly the ``gate_results[].gate`` enum shared by attempt, result, legacy
# run, and the report gate summary — tests pin the equality. Order is fixed.
GATES = (
    "integrity",
    "critical_safety",
    "regression",
    "resource",
    "privacy",
    "evaluator_integrity",
)

# Exactly the shared ``gate_results[].result`` enum.
GATE_RESULTS = frozenset({"pass", "fail", "not_applicable"})

# Exactly the attempt and legacy-run verdict vocabulary; result excludes error.
VERDICTS = frozenset({"pass", "fail", "error", "inconclusive"})

_RESOURCE_ERROR_CLASSES = frozenset({"timeout", "output_limit"})


@dataclass(frozen=True)
class GateResult:
    """One gate's outcome; ``reason`` is mandatory on failure."""

    gate: str
    result: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.gate not in GATES:
            raise ValueError(f"unknown gate: {self.gate!r}")
        if self.result not in GATE_RESULTS:
            raise ValueError(f"unknown gate result: {self.result!r}")
        if self.result == "fail" and (
            not isinstance(self.reason, str) or not self.reason.strip()
        ):
            raise ValueError("a failed gate must carry a reason")


@dataclass(frozen=True)
class GateConfig:
    """Suite policy for the configurable gates. Empty configuration means
    the gate reports ``not_applicable`` — never an implicit pass."""

    forbidden_output_patterns: tuple[str, ...] = ()  # critical_safety
    privacy_patterns: tuple[str, ...] = ()  # privacy
    regression_floors: tuple[tuple[str, float], ...] = ()  # regression
    expected_runner: tuple[str, str] | None = None  # (tool, version)
    expected_scorer_tool: str | None = None  # evaluator_integrity

    def __post_init__(self) -> None:
        for name in ("forbidden_output_patterns", "privacy_patterns"):
            for pattern in getattr(self, name):
                re.compile(pattern)  # invalid policy is a construction error
        for dimension, floor in self.regression_floors:
            if not isinstance(dimension, str) or not dimension.strip():
                raise ValueError("regression floor dimension must be a string")
            if isinstance(floor, bool) or not isinstance(floor, (int, float)):
                raise ValueError("regression floor must be a number")
            # A NaN floor never compares true and would idle the gate into
            # an implicit pass; only finite floors may be configured.
            if not math.isfinite(float(floor)):
                raise ValueError(f"regression floor must be finite, got {floor!r}")
        if self.expected_runner is not None and (
            not isinstance(self.expected_runner, tuple)
            or len(self.expected_runner) != 2
            or not all(isinstance(part, str) for part in self.expected_runner)
        ):
            raise ValueError("expected_runner must be a (tool, version) pair")


def evaluate_gates(
    *,
    replay: ReplayResult,
    score_vector: tuple[ScoreEntry, ...] | None,
    runner_id: Mapping[str, str],
    scorer_id: Mapping[str, str],
    config: GateConfig,
) -> tuple[GateResult, ...]:
    """Evaluate all six gates, always, in the fixed reporting order."""
    return (
        _gate_integrity(replay),
        _gate_patterns(
            "critical_safety", replay, config.forbidden_output_patterns
        ),
        _gate_regression(replay, score_vector, config.regression_floors),
        _gate_resource(replay),
        _gate_patterns("privacy", replay, config.privacy_patterns),
        _gate_evaluator_integrity(runner_id, scorer_id, config),
    )


def _gate_integrity(replay: ReplayResult) -> GateResult:
    # The runner classifies an artifact pin mismatch as runner_error; that
    # is the integrity failure surface at this layer.
    if replay.error_class == "runner_error":
        return GateResult(
            "integrity", "fail", f"artifact integrity failure: {replay.error_detail}"
        )
    return GateResult("integrity", "pass")


def _gate_resource(replay: ReplayResult) -> GateResult:
    if replay.error_class in _RESOURCE_ERROR_CLASSES:
        return GateResult(
            "resource",
            "fail",
            f"envelope exceeded ({replay.error_class}): {replay.error_detail}",
        )
    return GateResult("resource", "pass")


def _gate_patterns(
    gate: str, replay: ReplayResult, patterns: tuple[str, ...]
) -> GateResult:
    if not replay.ok:
        return GateResult(gate, "not_applicable", "no output to scan")
    if not patterns:
        return GateResult(gate, "not_applicable", "no patterns configured")
    text = replay.output_bytes.decode("utf-8") if replay.output_bytes else ""
    for pattern in patterns:
        if re.search(pattern, text):
            return GateResult(gate, "fail", f"output matched forbidden {pattern!r}")
    return GateResult(gate, "pass")


def _gate_regression(
    replay: ReplayResult,
    score_vector: tuple[ScoreEntry, ...] | None,
    floors: tuple[tuple[str, float], ...],
) -> GateResult:
    if not replay.ok or score_vector is None:
        return GateResult("regression", "not_applicable", "no scored output")
    if not floors:
        return GateResult("regression", "not_applicable", "no floors configured")
    values = {entry.dimension: entry.value for entry in score_vector}
    for dimension, floor in floors:
        if dimension not in values:
            return GateResult(
                "regression",
                "fail",
                f"floored dimension {dimension!r} absent from score vector",
            )
        if values[dimension] < floor:
            return GateResult(
                "regression",
                "fail",
                f"{dimension!r} scored {values[dimension]} below floor {floor}",
            )
    return GateResult("regression", "pass")


def _gate_evaluator_integrity(
    runner_id: Mapping[str, str],
    scorer_id: Mapping[str, str],
    config: GateConfig,
) -> GateResult:
    if config.expected_runner is None and config.expected_scorer_tool is None:
        return GateResult(
            "evaluator_integrity", "not_applicable", "no expectations configured"
        )
    if config.expected_runner is not None:
        tool, version = config.expected_runner
        if runner_id.get("tool") != tool or runner_id.get("version") != version:
            return GateResult(
                "evaluator_integrity",
                "fail",
                f"runner identity {dict(runner_id)} != expected "
                f"({tool!r}, {version!r})",
            )
    if config.expected_scorer_tool is not None:
        if scorer_id.get("tool") != config.expected_scorer_tool:
            return GateResult(
                "evaluator_integrity",
                "fail",
                f"scorer tool {scorer_id.get('tool')!r} != expected "
                f"{config.expected_scorer_tool!r}",
            )
    return GateResult("evaluator_integrity", "pass")


def assemble_verdict(
    replay: ReplayResult,
    gate_results: tuple[GateResult, ...],
    score_vector: tuple[ScoreEntry, ...] | None,
) -> str:
    """The ``verdict`` of an ``evaluation-run/v1`` record (decision 8)."""
    if not replay.ok:
        return "error"
    if any(result.result == "fail" for result in gate_results):
        return "fail"
    if score_vector is None:
        return "inconclusive"
    return "pass"


def gate_results_payload(results: tuple[GateResult, ...]) -> list[dict[str, Any]]:
    """The ``gate_results`` field value for an ``evaluation-run/v1`` record."""
    payload = []
    for result in results:
        item: dict[str, Any] = {"gate": result.gate, "result": result.result}
        if result.reason is not None:
            item["reason"] = result.reason
        payload.append(item)
    return payload
