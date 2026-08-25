"""Suite-level paired comparison over frozen case/seed/envelope observations."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from research_evolution.core import canonical_sha256

from .pipeline import _fold_gate_summary, _record_sha256
from .statistics import paired_bootstrap, paired_permutation, small_sample_limitation

OBSERVATION_UNIT = "case_seed_frozen_envelope"


@dataclass(frozen=True)
class MetricPolicy:
    """Pre-registered interpretation for one score dimension."""

    dimension: str
    direction: str
    role: str
    rope: float
    noninferiority_margin: float | None = None

    def __post_init__(self) -> None:
        if not self.dimension or any(char.isspace() for char in self.dimension):
            raise ValueError("metric dimension must be non-blank and contain no whitespace")
        if self.direction not in {"higher", "lower"}:
            raise ValueError("metric direction must be 'higher' or 'lower'")
        if self.role not in {"primary", "guardrail"}:
            raise ValueError("metric role must be 'primary' or 'guardrail'")
        _require_non_negative("rope", self.rope)
        if self.role == "guardrail" and self.noninferiority_margin is None:
            raise ValueError("guardrail metrics require noninferiority_margin")
        if self.role == "primary" and self.noninferiority_margin is not None:
            raise ValueError("primary metrics must not declare noninferiority_margin")
        if self.noninferiority_margin is not None:
            _require_non_negative("noninferiority_margin", self.noninferiority_margin)


@dataclass(frozen=True)
class SuiteComparePolicy:
    """Frozen suite analysis policy; all metric choices are pre-registered."""

    seed: int
    expected_seeds: tuple[int, ...]
    metrics: tuple[MetricPolicy, ...]
    resamples: int = 2000
    confidence: float = 0.95
    familywise_error_rate: float = 0.05
    minimum_pairs: int = 30

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if not self.expected_seeds or len(set(self.expected_seeds)) != len(
            self.expected_seeds
        ):
            raise ValueError("expected_seeds must be non-empty and unique")
        if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in self.expected_seeds):
            raise ValueError("every expected seed must be an integer")
        if not self.metrics or len({metric.dimension for metric in self.metrics}) != len(
            self.metrics
        ):
            raise ValueError("metrics must be non-empty with unique dimensions")
        if sum(metric.role == "primary" for metric in self.metrics) != 1:
            raise ValueError("exactly one primary metric is required")
        if isinstance(self.resamples, bool) or not isinstance(self.resamples, int):
            raise ValueError("resamples must be an integer")
        if self.resamples <= 0:
            raise ValueError("resamples must be positive")
        if not 0.0 < float(self.confidence) < 1.0:
            raise ValueError("confidence must be in (0, 1)")
        if not 0.0 < float(self.familywise_error_rate) < 1.0:
            raise ValueError("familywise_error_rate must be in (0, 1)")
        if isinstance(self.minimum_pairs, bool) or not isinstance(self.minimum_pairs, int):
            raise ValueError("minimum_pairs must be an integer")
        if self.minimum_pairs <= 0:
            raise ValueError("minimum_pairs must be positive")


def _require_non_negative(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


def _holm_adjust(p_values: Sequence[float]) -> list[float]:
    order = sorted(range(len(p_values)), key=lambda index: (p_values[index], index))
    adjusted = [0.0] * len(p_values)
    running = 0.0
    total = len(p_values)
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (total - rank) * p_values[index]))
        adjusted[index] = running
    return adjusted


def _score_map(run: Mapping[str, Any]) -> dict[str, tuple[float, str | None]]:
    result: dict[str, tuple[float, str | None]] = {}
    for entry in run["score_vector"]:
        dimension = entry["dimension"]
        if dimension in result:
            raise ValueError(f"duplicate score dimension {dimension!r}")
        result[dimension] = (float(entry["value"]), entry.get("unit"))
    return result


def _index_runs(
    runs: Sequence[Mapping[str, Any]],
    *,
    side: str,
    suite: Mapping[str, Any],
    suite_sha: str,
    expected_seeds: tuple[int, ...],
) -> tuple[
    dict[tuple[str, int], tuple[Mapping[str, Any], str]],
    str,
]:
    if not runs:
        raise ValueError(f"{side}_runs must not be empty")
    members = {
        item["evaluation_case_id"]: item["sha256"] for item in suite["cases"]
    }
    indexed: dict[tuple[str, int], tuple[Mapping[str, Any], str]] = {}
    candidate_id: str | None = None
    for run in runs:
        run_sha = _record_sha256(run, f"{side} run")
        if run["suite"] != {"suite_id": suite["suite_id"], "sha256": suite_sha}:
            raise ValueError(f"{side} run does not pin the frozen suite")
        case_id = run["case"]["evaluation_case_id"]
        if members.get(case_id) != run["case"]["sha256"]:
            raise ValueError(f"{side} run case pin is not a frozen suite member")
        seed = run["envelope"].get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError(f"{side} run must echo an integer envelope seed")
        key = (case_id, seed)
        if key in indexed:
            raise ValueError(f"duplicate {side} observation for case/seed {key!r}")
        if candidate_id is None:
            candidate_id = run["candidate"]["candidate_id"]
        elif candidate_id != run["candidate"]["candidate_id"]:
            raise ValueError(f"{side} runs must name exactly one candidate")
        indexed[key] = (run, run_sha)

    expected = {
        (case_id, seed)
        for case_id in members
        for seed in expected_seeds
    }
    actual = set(indexed)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"{side} run coverage must equal suite cases x expected seeds; "
            f"missing={missing!r}, extra={extra!r}"
        )
    assert candidate_id is not None
    return indexed, candidate_id


def compare_suite(
    *,
    suite: Mapping[str, Any],
    champion_candidate: Mapping[str, str],
    challenger_candidate: Mapping[str, str],
    champion_runs: Sequence[Mapping[str, Any]],
    challenger_runs: Sequence[Mapping[str, Any]],
    policy: SuiteComparePolicy,
    comparison_id: str,
    title: str,
    conclusion: str,
    generated_at: str,
    limitations: Sequence[str] = (),
) -> dict[str, Any]:
    """Compare two candidates over a complete frozen suite observation grid."""

    suite_sha = _record_sha256(suite, "suite")
    champion_index, champion_candidate_id = _index_runs(
        champion_runs,
        side="champion",
        suite=suite,
        suite_sha=suite_sha,
        expected_seeds=policy.expected_seeds,
    )
    challenger_index, challenger_candidate_id = _index_runs(
        challenger_runs,
        side="challenger",
        suite=suite,
        suite_sha=suite_sha,
        expected_seeds=policy.expected_seeds,
    )
    if champion_candidate_id != champion_candidate.get("candidate_id"):
        raise ValueError("champion candidate manifest does not match champion runs")
    if challenger_candidate_id != challenger_candidate.get("candidate_id"):
        raise ValueError("challenger candidate manifest does not match challenger runs")
    if set(champion_candidate) != {"candidate_id", "sha256"} or set(
        challenger_candidate
    ) != {"candidate_id", "sha256"}:
        raise ValueError("candidate manifest references require candidate_id and sha256")
    if champion_candidate["sha256"] == challenger_candidate["sha256"]:
        raise ValueError("champion and challenger pin the same candidate artifact")

    metric_dimensions = {metric.dimension for metric in policy.metrics}
    pairs: list[dict[str, Any]] = []
    values: dict[str, tuple[list[float], list[float], str | None]] = {}
    units_seen: set[str] = set()
    for metric in policy.metrics:
        values[metric.dimension] = ([], [], None)

    ordered_keys = sorted(champion_index)
    for key in ordered_keys:
        champion, champion_sha = champion_index[key]
        challenger, challenger_sha = challenger_index[key]
        for field in ("envelope", "runner", "scorer", "environment", "levels_covered"):
            if champion[field] != challenger[field]:
                raise ValueError(f"candidate-only comparison requires equal {field}")
        champion_scores = _score_map(champion)
        challenger_scores = _score_map(challenger)
        if set(champion_scores) != metric_dimensions or set(challenger_scores) != metric_dimensions:
            raise ValueError("score dimensions must exactly equal pre-registered metrics")
        for metric in policy.metrics:
            champ_value, champ_unit = champion_scores[metric.dimension]
            chall_value, chall_unit = challenger_scores[metric.dimension]
            if champ_unit != chall_unit:
                raise ValueError(f"metric unit mismatch for {metric.dimension!r}")
            champions, challengers, established_unit = values[metric.dimension]
            if metric.dimension in units_seen and established_unit != champ_unit:
                raise ValueError(f"metric unit drift for {metric.dimension!r}")
            champions.append(champ_value)
            challengers.append(chall_value)
            values[metric.dimension] = (champions, challengers, champ_unit)
            units_seen.add(metric.dimension)
        case_id, seed = key
        pairs.append(
            {
                "case": {
                    "evaluation_case_id": case_id,
                    "sha256": champion["case"]["sha256"],
                },
                "seed": seed,
                "envelope_sha256": champion["envelope"]["envelope_sha256"],
                "champion_evaluation_run_id": champion["evaluation_run_id"],
                "challenger_evaluation_run_id": challenger["evaluation_run_id"],
            }
        )

    metric_payloads: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    raw_p_values: list[float] = []
    for metric in policy.metrics:
        champions, challengers, unit = values[metric.dimension]
        if metric.direction == "higher":
            oriented_champion = champions
            oriented_challenger = challengers
        else:
            oriented_champion = [-value for value in champions]
            oriented_challenger = [-value for value in challengers]
        permutation = paired_permutation(
            oriented_champion,
            oriented_challenger,
            seed=policy.seed,
            resamples=policy.resamples,
        )
        bootstrap = paired_bootstrap(
            oriented_champion,
            oriented_challenger,
            seed=policy.seed,
            resamples=policy.resamples,
            confidence=policy.confidence,
        )
        raw_p_values.append(permutation.estimates["p_value"])
        traces.append(
            {
                "dimension": metric.dimension,
                "permutation": permutation.trace_payload(),
                "bootstrap": bootstrap.trace_payload(),
            }
        )
        item: dict[str, Any] = {
            "dimension": metric.dimension,
            "direction": metric.direction,
            "role": metric.role,
            "n_pairs": len(champions),
            "mean_difference": bootstrap.estimates["mean_difference"],
            "ci_low": bootstrap.estimates["ci_low"],
            "ci_high": bootstrap.estimates["ci_high"],
            "p_value": permutation.estimates["p_value"],
            "adjusted_p_value": 1.0,
            "rank_biserial": permutation.estimates["rank_biserial"],
            "rope": float(metric.rope),
            "inference_status": "insufficient_pairs",
        }
        if unit is not None:
            item["unit"] = unit
        if metric.noninferiority_margin is not None:
            item["noninferiority_margin"] = float(metric.noninferiority_margin)
        metric_payloads.append(item)

    adjusted = _holm_adjust(raw_p_values)
    for item, metric, adjusted_p in zip(
        metric_payloads, policy.metrics, adjusted, strict=True
    ):
        item["adjusted_p_value"] = adjusted_p
        if item["n_pairs"] < policy.minimum_pairs:
            continue
        if metric.role == "guardrail":
            margin_value = metric.noninferiority_margin
            if margin_value is None:
                raise ValueError("guardrail metric is missing noninferiority_margin")
            margin = float(margin_value)
            if item["ci_low"] >= -margin:
                item["inference_status"] = "noninferior"
            elif item["ci_high"] < -margin:
                item["inference_status"] = "regression_supported"
            else:
                item["inference_status"] = "inconclusive"
        elif (
            item["ci_low"] > float(metric.rope)
            and adjusted_p <= policy.familywise_error_rate
        ):
            item["inference_status"] = "improvement_supported"
        elif (
            item["ci_high"] < -float(metric.rope)
            and adjusted_p <= policy.familywise_error_rate
        ):
            item["inference_status"] = "regression_supported"
        else:
            item["inference_status"] = "inconclusive"

    all_runs = list(champion_runs) + list(challenger_runs)
    levels = sorted(set.intersection(*(set(run["levels_covered"]) for run in all_runs)))
    if not levels:
        raise ValueError("all runs must share at least one coverage level")
    if not conclusion or not conclusion.strip():
        raise ValueError("conclusion must be a non-blank string")
    all_limitations = list(limitations)
    caution = small_sample_limitation(len(pairs))
    if caution is not None and caution not in all_limitations:
        all_limitations.append(caution)

    payload = {
        "schema": "suite-comparison/v1",
        "suite_comparison_id": comparison_id,
        "title": title,
        "suite": {"suite_id": suite["suite_id"], "sha256": suite_sha},
        "champion": dict(champion_candidate),
        "challenger": dict(challenger_candidate),
        "champion_runs": [
            {"evaluation_run_id": run["evaluation_run_id"], "sha256": sha}
            for run, sha in (champion_index[key] for key in ordered_keys)
        ],
        "challenger_runs": [
            {"evaluation_run_id": run["evaluation_run_id"], "sha256": sha}
            for run, sha in (challenger_index[key] for key in ordered_keys)
        ],
        "observation_unit": OBSERVATION_UNIT,
        "expected_seeds": list(policy.expected_seeds),
        "pairs": pairs,
        "methods": {
            "statistics": ["paired_permutation", "paired_bootstrap"],
            "parameters_sha256": canonical_sha256(
                {
                    "policy": {
                        "seed": policy.seed,
                        "expected_seeds": list(policy.expected_seeds),
                        "resamples": policy.resamples,
                        "confidence": policy.confidence,
                        "familywise_error_rate": policy.familywise_error_rate,
                        "minimum_pairs": policy.minimum_pairs,
                    },
                    "metrics": traces,
                }
            ),
            "seed": policy.seed,
            "resamples": policy.resamples,
            "confidence": policy.confidence,
            "familywise_error_rate": policy.familywise_error_rate,
            "minimum_pairs": policy.minimum_pairs,
            "multiple_comparison_adjustment": "holm",
        },
        "metrics": metric_payloads,
        "gate_summary": _fold_gate_summary(all_runs[0], all_runs[0])
        if len(all_runs) == 1
        else _fold_many_gates(all_runs),
        "levels_covered": levels,
        "conclusion": conclusion,
        "limitations": all_limitations,
        "generated_at": generated_at,
    }
    _record_sha256(payload, "assembled suite comparison")
    return payload


def _fold_many_gates(runs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    folded = dict(runs[0])
    folded["gate_results"] = list(runs[0]["gate_results"])
    for run in runs[1:]:
        summary = _fold_gate_summary(folded, run)
        folded["gate_results"] = summary
    return list(folded["gate_results"])
