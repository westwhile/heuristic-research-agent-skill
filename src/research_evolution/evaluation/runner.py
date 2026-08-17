"""Deterministic offline replay runner for L0/L1 evaluation (ADR-0006
decision 4).

The runner replays a frozen artifact — the candidate's pinned output —
and nothing more. It never touches the network, never reads process
environment, and the only clock it consults is an injectable monotonic
clock used solely for timeout enforcement; seeds and configuration arrive
frozen inside the :class:`Envelope`. The same artifact plus the same
envelope always yields the same result, and a retry re-executes the very
same deterministic attempt (retry exists because the envelope must carry
the policy, not because replay is nondeterministic).

Every failure is classified into exactly one of the four structured error
classes of ``evaluation-run/v1`` (``timeout`` / ``output_limit`` /
``parse_error`` / ``runner_error``). A failed run is data, not an
exception: :func:`run_replay` returns a :class:`ReplayResult` for every
classified failure and never raises for one. Anything outside the
taxonomy is a bug in the runner itself and is allowed to propagate.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass

from research_evolution.core import (
    StrictJsonError,
    canonical_bytes,
    load_strict_json,
)

from .envelope import Envelope

RUNNER_TOOL = "replay-runner"
RUNNER_VERSION = "0.1.0"


@dataclass(frozen=True)
class ReplayResult:
    """The outcome of one replay run; immutable and fully self-describing."""

    ok: bool
    output_bytes: bytes | None
    output_sha256: str | None
    error_class: str | None
    error_detail: str | None
    attempts: int


def runner_identity() -> dict[str, str]:
    """The ``runner`` field value for an ``evaluation-run/v1`` record."""
    return {"tool": RUNNER_TOOL, "version": RUNNER_VERSION}


def run_replay(
    artifact: bytes,
    expected_sha256: str,
    envelope: Envelope,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> ReplayResult:
    """Replay *artifact* under *envelope*.

    *artifact* is the frozen candidate output; *expected_sha256* is its
    integrity pin (the candidate/output hash the caller bound into the
    evaluation contract). *clock* is a monotonic seconds source consulted
    only for timeout enforcement — injectable so tests are deterministic.

    Per attempt the checks run in a fixed order — timeout, integrity,
    size, strict parse — so the error classification of a multiply-broken
    artifact is itself deterministic. A successful result carries the
    canonical re-serialization of the parsed output and its SHA-256: the
    hash of exactly what a scorer will consume.
    """
    attempts = 0
    while True:
        attempts += 1
        result = _attempt(artifact, expected_sha256, envelope, clock, attempts)
        if (
            result.ok
            or result.error_class not in envelope.retry_on
            or attempts > envelope.retry_attempts
        ):
            return result


def _attempt(
    artifact: bytes,
    expected_sha256: str,
    envelope: Envelope,
    clock: Callable[[], float],
    attempts: int,
) -> ReplayResult:
    start = clock()

    def timed_out() -> bool:
        return (clock() - start) * 1000 > envelope.timeout_ms

    def failure(error_class: str, detail: str) -> ReplayResult:
        return ReplayResult(
            ok=False,
            output_bytes=None,
            output_sha256=None,
            error_class=error_class,
            error_detail=detail,
            attempts=attempts,
        )

    if timed_out():
        return failure("timeout", f"exceeded {envelope.timeout_ms} ms budget")

    actual_sha256 = hashlib.sha256(artifact).hexdigest()
    if actual_sha256 != expected_sha256:
        return failure(
            "runner_error",
            "artifact integrity mismatch: expected sha256 "
            f"{expected_sha256}, got {actual_sha256}",
        )

    if len(artifact) > envelope.max_output_bytes:
        return failure(
            "output_limit",
            f"artifact is {len(artifact)} bytes; envelope cap is "
            f"{envelope.max_output_bytes}",
        )

    if timed_out():
        return failure("timeout", f"exceeded {envelope.timeout_ms} ms budget")

    try:
        parsed = load_strict_json(artifact)
    except StrictJsonError as exc:
        return failure("parse_error", str(exc))

    output = canonical_bytes(parsed)
    if timed_out():
        return failure("timeout", f"exceeded {envelope.timeout_ms} ms budget")

    return ReplayResult(
        ok=True,
        output_bytes=output,
        output_sha256=hashlib.sha256(output).hexdigest(),
        error_class=None,
        error_detail=None,
        attempts=attempts,
    )
