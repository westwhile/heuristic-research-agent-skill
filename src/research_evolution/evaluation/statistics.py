"""Comparison statistics for Champion/Challenger evaluation (ADR-0006
decision 7).

Three methods, matching the ``methods.statistics`` enum of
``comparison-report/v1`` exactly:

- ``paired_exact_mcnemar`` — exact two-sided McNemar test on discordant
  pairs, computed with arbitrary-precision integer arithmetic (no
  dependency, no approximation);
- ``paired_bootstrap`` — rank-index percentile interval for the mean of
  paired per-case differences, resampled with ``random.Random(seed)``;
  the seed is a required parameter and is always traced;
- ``rare_event_upper_bound`` — exact one-sided Clopper-Pearson upper
  bound for an event rate (closed form at zero events, deterministic
  bisection on the exact binomial tail otherwise).

Trace discipline: every result carries its full parameter set, and
``parameters_sha256`` binds ``{"method": ..., "parameters": ...}`` so a
report can pin the exact computation (the ``methods.parameters_sha256``
field of ``comparison-report/v1``). Given the same traced parameters,
every method here reproduces its output bit-for-bit — golden-pinned in
the unit tests.

Claim discipline (acceptance gate): these functions return data, never
verdicts. A 20–30-case sample cannot support a significance claim about
overall accuracy; :func:`small_sample_limitation` single-sources the
limitation sentence the report layer (E7) must include at that scale.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from math import comb
from typing import Any, Sequence

from research_evolution.core import canonical_sha256

# Exactly the ``methods.statistics`` item enum of
# ``comparison-report/v1`` — a unit test pins the equality.
STATISTICAL_METHODS = frozenset(
    {"paired_exact_mcnemar", "paired_bootstrap", "rare_event_upper_bound"}
)

# Below this many paired cases the acceptance gate forbids significance
# claims about overall accuracy (plan Phase 3 gate: "20–30 cases").
SMALL_SAMPLE_THRESHOLD = 30


def small_sample_limitation(n_cases: int) -> str | None:
    """The standard limitation sentence for small comparison samples, or
    None when the sample clears the gate threshold."""
    if n_cases < SMALL_SAMPLE_THRESHOLD:
        return (
            f"Small paired sample ({n_cases} cases): no statistical "
            "significance is claimed for overall accuracy at this scale."
        )
    return None


@dataclass(frozen=True)
class StatisticResult:
    """One traced statistical computation: method, full parameters, and
    the resulting estimates. ``parameters_sha256`` is the canonical hash
    of the trace payload, ready for ``methods.parameters_sha256``."""

    method: str
    parameters: dict[str, Any]
    estimates: dict[str, float]

    def __post_init__(self) -> None:
        if self.method not in STATISTICAL_METHODS:
            raise ValueError(f"unknown statistical method: {self.method!r}")

    def trace_payload(self) -> dict[str, Any]:
        return {"method": self.method, "parameters": self.parameters}

    @property
    def parameters_sha256(self) -> str:
        return canonical_sha256(self.trace_payload())


def _require_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    return value


def _require_confidence(confidence: Any) -> float:
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError(f"confidence must be a number, got {confidence!r}")
    result = float(confidence)
    if not 0.0 < result < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence!r}")
    return result


def mcnemar_exact(champion_only: int, challenger_only: int) -> StatisticResult:
    """Exact two-sided McNemar test.

    *champion_only* is the number of paired cases only the champion got
    right, *champion_only*'s counterpart *challenger_only* the reverse.
    Under the null the discordant split is Binomial(n, 1/2); the exact
    two-sided p-value is ``min(1, 2 * P(X <= min(b, c)))``.
    """
    b = _require_int("champion_only", champion_only)
    c = _require_int("challenger_only", challenger_only)
    if b < 0 or c < 0:
        raise ValueError("discordant pair counts must be non-negative")
    n = b + c
    if n == 0:
        p_value = 1.0
    else:
        tail = sum(comb(n, k) for k in range(0, min(b, c) + 1))
        p_value = min(1.0, 2.0 * tail / 2**n)
    return StatisticResult(
        method="paired_exact_mcnemar",
        parameters={"champion_only": b, "challenger_only": c},
        estimates={"p_value": p_value, "discordant_pairs": float(n)},
    )


def paired_bootstrap(
    champion: Sequence[float],
    challenger: Sequence[float],
    *,
    seed: int,
    resamples: int = 10000,
    confidence: float = 0.95,
) -> StatisticResult:
    """Rank-index percentile bootstrap for the mean paired difference
    (challenger minus champion, per case).

    Resampling uses ``random.Random(seed)`` — the same traced seed
    reproduces the interval exactly. The interval takes order statistics
    at ``floor((1 ± confidence) / 2 * resamples)`` ranks of the sorted
    resample means.
    """
    if len(champion) != len(challenger):
        raise ValueError("paired inputs must have equal length")
    n = len(champion)
    if n == 0:
        raise ValueError("paired inputs must not be empty")
    differences = []
    for index, (champ, chall) in enumerate(zip(champion, challenger)):
        for name, value in ((f"champion[{index}]", champ), (f"challenger[{index}]", chall)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number, got {value!r}")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite, got {value!r}")
        differences.append(float(chall) - float(champ))
    seed = _require_int("seed", seed)
    resamples = _require_int("resamples", resamples)
    if resamples <= 0:
        raise ValueError(f"resamples must be positive, got {resamples}")
    confidence = _require_confidence(confidence)

    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        means.append(
            sum(differences[i] for i in rng.choices(range(n), k=n)) / n
        )
    means.sort()
    tail = (1.0 - confidence) / 2.0
    low_rank = min(resamples - 1, max(0, int(math.floor(tail * resamples))))
    high_rank = min(
        resamples - 1, max(0, int(math.floor((1.0 - tail) * resamples)))
    )
    return StatisticResult(
        method="paired_bootstrap",
        parameters={
            "n_cases": n,
            "resamples": resamples,
            "confidence": confidence,
            "seed": seed,
        },
        estimates={
            "mean_difference": sum(differences) / n,
            "ci_low": means[low_rank],
            "ci_high": means[high_rank],
        },
    )


def rare_event_upper_bound(
    events: int, trials: int, *, confidence: float = 0.95
) -> StatisticResult:
    """Exact one-sided Clopper-Pearson upper bound for an event rate with
    *events* occurrences in *trials* trials.

    Closed form at zero events (``1 - tail_mass ** (1 / n)``); otherwise
    deterministic bisection on the exact binomial tail
    ``P(X <= events | trials, p) = tail_mass``.
    """
    events = _require_int("events", events)
    trials = _require_int("trials", trials)
    if trials <= 0:
        raise ValueError(f"trials must be positive, got {trials}")
    if not 0 <= events <= trials:
        raise ValueError(f"events must be in [0, trials], got {events}")
    confidence = _require_confidence(confidence)
    tail_mass = 1.0 - confidence

    if events == 0:
        upper = 1.0 - tail_mass ** (1.0 / trials)
    else:

        def tail_probability(p: float) -> float:
            return sum(
                comb(trials, k) * p**k * (1.0 - p) ** (trials - k)
                for k in range(0, events + 1)
            )

        low, high = 0.0, 1.0
        for _ in range(200):  # deterministic fixed-iteration bisection
            mid = (low + high) / 2.0
            if tail_probability(mid) > tail_mass:
                low = mid
            else:
                high = mid
        upper = (low + high) / 2.0

    return StatisticResult(
        method="rare_event_upper_bound",
        parameters={
            "events": events,
            "trials": trials,
            "confidence": confidence,
        },
        estimates={"upper_bound": upper},
    )
