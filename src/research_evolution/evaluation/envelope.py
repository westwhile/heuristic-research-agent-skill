"""Replay envelopes: the frozen execution contract of an L0/L1 run.

ADR-0006 decisions 3-4: timeout, output size cap, structured error
classification, and the retry policy (count, conditions, determinism) are
frozen in the envelope and bound into every ``evaluation-run/v1`` record
as ``envelope.envelope_sha256`` (canonical SHA-256 of :meth:`to_dict`).
The record's optional echo fields (``timeout_ms``/``max_output_bytes``/
``retry_attempts``/``seed``/``notes``) are a convenience subset of this
contract; ``retry_on`` is bound through the hash alone.

``ERROR_CLASSES`` is exactly the ``error_class`` enum of
``evaluation-run/v1`` — the schema and this module must change together;
a unit test pins that equality.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research_evolution.core import canonical_sha256

# Structured error classification (ADR-0006 decision 4). Mirrors the
# ``error_class`` enum of schemas/core/evaluation-run-v1.schema.json.
ERROR_CLASSES = frozenset(
    {"timeout", "output_limit", "parse_error", "runner_error"}
)


def _require_int(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {value!r}")


@dataclass(frozen=True)
class Envelope:
    """The frozen execution envelope of one replay run.

    The retry policy is deterministic by construction: a fixed attempt
    count over a fixed set of retryable error classes, with no backoff,
    jitter, or clock-dependent condition. ``retry_on`` is normalized to a
    sorted duplicate-free tuple so the same policy always hashes the same.
    """

    timeout_ms: int
    max_output_bytes: int
    retry_attempts: int = 0
    retry_on: tuple[str, ...] = ()
    seed: int | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        _require_int("timeout_ms", self.timeout_ms)
        _require_int("max_output_bytes", self.max_output_bytes)
        _require_int("retry_attempts", self.retry_attempts)
        if self.timeout_ms <= 0:
            raise ValueError(f"timeout_ms must be positive, got {self.timeout_ms}")
        if self.max_output_bytes <= 0:
            raise ValueError(
                f"max_output_bytes must be positive, got {self.max_output_bytes}"
            )
        if self.retry_attempts < 0:
            raise ValueError(
                f"retry_attempts must be non-negative, got {self.retry_attempts}"
            )
        unknown = sorted(set(self.retry_on) - ERROR_CLASSES)
        if unknown:
            raise ValueError(
                f"retry_on entries outside the error taxonomy: {unknown}"
            )
        object.__setattr__(self, "retry_on", tuple(sorted(set(self.retry_on))))
        if self.seed is not None:
            _require_int("seed", self.seed)

    def to_dict(self) -> dict[str, Any]:
        """The canonical-bound payload; optional fields absent when unset."""
        payload: dict[str, Any] = {
            "timeout_ms": self.timeout_ms,
            "max_output_bytes": self.max_output_bytes,
            "retry_attempts": self.retry_attempts,
            "retry_on": list(self.retry_on),
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.notes is not None:
            payload["notes"] = self.notes
        return payload

    @property
    def canonical_sha256(self) -> str:
        """The hash bound into ``evaluation-run/v1`` as ``envelope_sha256``."""
        return canonical_sha256(self.to_dict())
