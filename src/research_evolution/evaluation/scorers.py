"""Scorer levels and score-vector construction (ADR-0006 decisions 5-6).

Four explicit scorer levels, recorded in every ``evaluation-run/v1``
record and every report: ``oracle``, ``deterministic_checker``,
``structured_rubric``, and ``calibrated_judge``. The first two score a
replayed output here, deterministically and offline. The last two package
scores produced by an external offline judgment process (a human or an
LLM judge working from a frozen rubric); this layer validates and
packages those scores, it does not invent them.

Level discipline (ADR-0006 rejected alternative 4): a calibrated judge
without calibration evidence must not outrank a structured rubric, so
:func:`package_judge_scores` refuses ``calibration_sha256=None`` — with
no calibration evidence there is no judge-level run, and the honest
declaration is ``structured_rubric``.

Score-vector discipline (decision 6): a run yields a vector of
per-dimension entries, never a single cross-domain aggregate. No scorer
in this module emits an aggregate dimension; :func:`validate_score_vector`
additionally rejects empty vectors and duplicate dimensions.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

# Scorer levels: exactly the ``scorer.level`` enum of
# ``evaluation-run/v1`` and the ``evaluation_contract.scorer_level`` enum
# of ``evaluation-case/v1`` — a unit test pins both equalities.
SCORER_LEVELS = frozenset(
    {"oracle", "deterministic_checker", "structured_rubric", "calibrated_judge"}
)

SCORER_VERSION = "0.1.0"

# The ``runner.tool``-style tool name recorded per level in run records.
_LEVEL_TOOLS = {
    "oracle": "oracle-scorer",
    "deterministic_checker": "deterministic-checker",
    "structured_rubric": "structured-rubric",
    "calibrated_judge": "calibrated-judge",
}

_SHA256_HEX = frozenset("0123456789abcdef")


def _require_finite_number(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return result


def _require_calibration_sha256(calibration_sha256: str | None) -> str:
    if (
        not isinstance(calibration_sha256, str)
        or len(calibration_sha256) != 64
        or any(char not in _SHA256_HEX for char in calibration_sha256)
    ):
        raise ValueError(
            "calibrated_judge requires calibration evidence: "
            "calibration_sha256 must be a 64-char lowercase hex string "
            "(ADR-0006 rejected alternative 4)"
        )
    return calibration_sha256


@dataclass(frozen=True)
class ScoreEntry:
    """One dimension of a score vector; matches ``score_vector`` items of
    ``evaluation-run/v1`` (``unit`` absent when None)."""

    dimension: str
    value: float
    unit: str | None = None

    def __post_init__(self) -> None:
        # The frozen run schema pins dimension to ^\S+$; construct nothing
        # that the schema would reject two layers downstream.
        if not isinstance(self.dimension, str) or not re.fullmatch(
            r"\S+", self.dimension
        ):
            raise ValueError(
                f"dimension must be a whitespace-free string, got {self.dimension!r}"
            )
        object.__setattr__(
            self, "value", _require_finite_number("value", self.value)
        )
        if self.unit is not None and (
            not isinstance(self.unit, str) or not self.unit.strip()
        ):
            raise ValueError("unit must be a non-empty string or None")


def _sorted(entries: list[ScoreEntry]) -> tuple[ScoreEntry, ...]:
    return tuple(sorted(entries, key=lambda entry: entry.dimension))


def _json_equal(left: Any, right: Any) -> bool:
    """Type-faithful JSON equality.

    Python's ``==`` lies about JSON values: ``True == 1``, ``None`` is
    produced by ``dict.get`` for absent keys, and container equality
    inherits both confusions. Here a bool never equals a non-bool (checked
    before the numeric branch, because ``bool`` subclasses ``int``);
    numbers still compare across int/float (JSON has one number type);
    dicts and lists recurse; anything else must share its exact type.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    return type(left) is type(right) and left == right


def score_with_oracle(
    output: Mapping[str, Any], oracle: Mapping[str, Any]
) -> tuple[ScoreEntry, ...]:
    """Exact-match scoring: one ``exact_match:<field>`` entry per oracle
    field, 1.0 when the output field is present and JSON-equal to the
    oracle value, 0.0 otherwise. Output fields outside the oracle are
    ignored — the oracle defines what is scored.
    """
    entries = [
        ScoreEntry(
            dimension=f"exact_match:{field}",
            value=1.0
            if field in output and _json_equal(output[field], expected)
            else 0.0,
        )
        for field, expected in oracle.items()
    ]
    return _sorted(entries)


def score_with_checker(
    output: Mapping[str, Any], spec: Mapping[str, Any]
) -> tuple[ScoreEntry, ...]:
    """Deterministic-checker scoring. *spec* names a checker from the MVP
    registry and its parameters; checkers are pure functions of the
    replayed output, so the same output and spec always score the same.

    MVP registry:

    - ``numeric_tolerance``: params ``field``, ``expected``, ``tolerance``.
      Emits ``within_tolerance:<field>`` (1.0/0.0) and, when the output
      field is numeric, ``absolute_error:<field>`` with unit ``absolute``.
    """
    checker = spec.get("checker")
    params = spec.get("params")
    if not isinstance(params, Mapping):
        raise ValueError("checker spec requires a params object")
    if checker == "numeric_tolerance":
        return _numeric_tolerance(output, params)
    raise ValueError(f"unknown deterministic checker: {checker!r}")


def _numeric_tolerance(
    output: Mapping[str, Any], params: Mapping[str, Any]
) -> tuple[ScoreEntry, ...]:
    field = params.get("field")
    if not isinstance(field, str) or not field:
        raise ValueError("numeric_tolerance params.field must be a string")
    expected = _require_finite_number("params.expected", params.get("expected"))
    tolerance = _require_finite_number(
        "params.tolerance", params.get("tolerance")
    )
    if tolerance < 0:
        raise ValueError("params.tolerance must be non-negative")
    actual_raw = output.get(field)
    entries = []
    if isinstance(actual_raw, bool) or not isinstance(actual_raw, (int, float)):
        entries.append(ScoreEntry(dimension=f"within_tolerance:{field}", value=0.0))
    else:
        error = abs(float(actual_raw) - expected)
        entries.append(
            ScoreEntry(
                dimension=f"within_tolerance:{field}",
                value=1.0 if error <= tolerance else 0.0,
            )
        )
        entries.append(
            ScoreEntry(
                dimension=f"absolute_error:{field}", value=error, unit="absolute"
            )
        )
    return _sorted(entries)


def package_rubric_scores(
    scores: Mapping[str, Any],
) -> tuple[ScoreEntry, ...]:
    """Validate and package externally produced structured-rubric scores.

    *scores* maps rubric dimension names to finite numbers as decided by
    the offline judgment process; this layer invents nothing.
    """
    if not isinstance(scores, Mapping) or not scores:
        raise ValueError("rubric scores must be a non-empty mapping")
    entries = [
        ScoreEntry(dimension=dimension, value=_require_finite_number(dimension, value))
        for dimension, value in scores.items()
    ]
    return _sorted(entries)


def package_judge_scores(
    scores: Mapping[str, Any], calibration_sha256: str | None
) -> tuple[ScoreEntry, ...]:
    """Validate and package calibrated-judge scores. Refuses without
    calibration evidence: no ``calibration_sha256``, no judge level."""
    _require_calibration_sha256(calibration_sha256)
    return package_rubric_scores(scores)


def validate_score_vector(entries: tuple[ScoreEntry, ...]) -> None:
    """Vector discipline: non-empty, unique dimensions (decision 6)."""
    if not entries:
        raise ValueError("score vector must not be empty")
    dimensions = [entry.dimension for entry in entries]
    if len(set(dimensions)) != len(dimensions):
        raise ValueError(f"duplicate score dimensions: {sorted(dimensions)}")


def scorer_identity(
    level: str, *, calibration_sha256: str | None = None
) -> dict[str, str]:
    """The ``scorer`` field value for an ``evaluation-run/v1`` record."""
    if level not in SCORER_LEVELS:
        raise ValueError(f"unknown scorer level: {level!r}")
    identity = {
        "level": level,
        "tool": _LEVEL_TOOLS[level],
        "version": SCORER_VERSION,
    }
    if level == "calibrated_judge":
        identity["calibration_sha256"] = _require_calibration_sha256(
            calibration_sha256
        )
    elif calibration_sha256 is not None:
        raise ValueError(
            "calibration_sha256 is only meaningful at calibrated_judge "
            "level; refusing to silently drop it"
        )
    return identity


def score_vector_payload(entries: tuple[ScoreEntry, ...]) -> list[dict[str, Any]]:
    """The ``score_vector`` field value for an ``evaluation-run/v1`` record."""
    validate_score_vector(entries)
    payload = []
    for entry in entries:
        item: dict[str, Any] = {
            "dimension": entry.dimension,
            "value": entry.value,
        }
        if entry.unit is not None:
            item["unit"] = entry.unit
        payload.append(item)
    return payload
