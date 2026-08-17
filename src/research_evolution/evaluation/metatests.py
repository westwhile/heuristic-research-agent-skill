"""Evaluator meta-tests (ADR-0006 decision 9).

Meta-tests make the evaluator itself a test subject. Three classes are
part of every evaluation suite:

- **known-good / known-bad**: two reference probes with known expected
  verdicts must be stably distinguished — a pipeline that cannot tell
  them apart cannot evaluate anything;
- **evaluator mutation**: a deliberately corrupted evaluator must be
  *detected* by outcome comparison against the reference. The three
  required mutation classes (decision 9) are implemented as operators on
  the real machinery, not as textual mocks:
  ``invert_verdict`` (wraps :func:`~.gates.assemble_verdict`),
  ``drop_condition`` (forces one gate to pass), and
  ``relax_resource_limit`` (inflates the frozen envelope caps).

A mutation is detected iff it changes at least one probe's verdict; the
report names the changed probes. The negative control — an unmutated
pipeline — must never be "detected".
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Mapping

from . import gates as _gates
from .envelope import Envelope

# The three mutation classes required by ADR-0006 decision 9.
MUTATION_CLASSES = frozenset(
    {"invert_verdict", "drop_condition", "relax_resource_limit"}
)


@dataclass(frozen=True)
class MetaTestReport:
    """One meta-test outcome: what ran, and whether it behaved as the
    discipline requires (distinction stable / mutation detected)."""

    kind: str
    detected: bool
    detail: str


def known_pair_check(
    reference_verdicts: Mapping[str, str],
    expected_verdicts: Mapping[str, str],
) -> MetaTestReport:
    """known-good/known-bad: the reference pipeline's verdicts on the
    probe pair must equal the known expectations, and the two expectations
    must differ (a pair that expects the same verdict proves nothing)."""
    reference = dict(reference_verdicts)
    expected = dict(expected_verdicts)
    if set(reference) != set(expected):
        raise ValueError("reference and expected probe sets differ")
    if len(set(expected.values())) < 2:
        raise ValueError("the known pair must expect distinct verdicts")
    mismatches = sorted(
        probe
        for probe in expected
        if reference[probe] != expected[probe]
    )
    if mismatches:
        return MetaTestReport(
            kind="known_good_known_bad",
            detected=False,
            detail=f"probes not stably distinguished: {mismatches}",
        )
    return MetaTestReport(
        kind="known_good_known_bad",
        detected=True,
        detail="known-good and known-bad stably distinguished",
    )


def mutation_check(
    mutation: str,
    reference_verdicts: Mapping[str, str],
    mutated_verdicts: Mapping[str, str],
) -> MetaTestReport:
    """A mutation is detected iff it changed at least one probe verdict."""
    if mutation not in MUTATION_CLASSES:
        raise ValueError(f"unknown mutation class: {mutation!r}")
    reference = dict(reference_verdicts)
    mutated = dict(mutated_verdicts)
    if set(reference) != set(mutated):
        raise ValueError("reference and mutated probe sets differ")
    changed = sorted(
        probe for probe in reference if reference[probe] != mutated[probe]
    )
    if changed:
        return MetaTestReport(
            kind=mutation,
            detected=True,
            detail=f"verdicts changed for probes: {changed}",
        )
    return MetaTestReport(
        kind=mutation,
        detected=False,
        detail="mutation changed no probe verdict — the evaluator "
        "would not notice this corruption",
    )


# -- mutation operators on the real machinery -------------------------------


def mutate_invert_verdict(
    assemble: Callable[..., str],
) -> Callable[..., str]:
    """invert_verdict: wrap verdict assembly, swapping pass and fail."""

    def mutated(*args: Any, **kwargs: Any) -> str:
        verdict = assemble(*args, **kwargs)
        if verdict == "pass":
            return "fail"
        if verdict == "fail":
            return "pass"
        return verdict

    return mutated


def mutate_drop_condition(
    evaluate: Callable[..., tuple[_gates.GateResult, ...]], gate: str
) -> Callable[..., tuple[_gates.GateResult, ...]]:
    """drop_condition: wrap gate evaluation, forcing one gate to pass."""
    if gate not in _gates.GATES:
        raise ValueError(f"unknown gate: {gate!r}")

    def mutated(*args: Any, **kwargs: Any) -> tuple[_gates.GateResult, ...]:
        return tuple(
            _gates.GateResult(result.gate, "pass")
            if result.gate == gate
            else result
            for result in evaluate(*args, **kwargs)
        )

    return mutated


def mutate_relax_resource_limit(envelope: Envelope, multiplier: int) -> Envelope:
    """relax_resource_limit: a new envelope with inflated caps."""
    if isinstance(multiplier, bool) or not isinstance(multiplier, int) or multiplier <= 1:
        raise ValueError(f"multiplier must be an integer > 1, got {multiplier!r}")
    return dataclasses.replace(
        envelope,
        timeout_ms=envelope.timeout_ms * multiplier,
        max_output_bytes=envelope.max_output_bytes * multiplier,
    )
