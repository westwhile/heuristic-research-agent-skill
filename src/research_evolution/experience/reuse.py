"""Reuse outcome records and rebuildable aggregates (ADR-0007 decision 6).

Plan task 11 and acceptance gate 7: when a run actually uses a pattern,
the run records the pinned pattern snapshot it used and the outcome it
observed (helped / neutral / harmed / not_applicable). Reuse feedback
never writes back into a pattern record — per-pattern outcome tallies are
a rebuildable registry-layer derivation (:func:`reuse_summary`), never a
pattern field.
"""

from typing import Any, Mapping, Sequence

from ..core import canonical_bytes, load_record

from .cases import _RUN_FAMILY, _pin_member
from .patterns import _PATTERN_FAMILY
from .redaction import scan_for_restricted

_REUSE_FAMILY = "reuse-event/v1"
_OUTCOMES = ("helped", "neutral", "harmed", "not_applicable")


def record_reuse_outcome(
    *,
    reuse_event_id: str,
    run: Mapping[str, Any],
    pattern: Mapping[str, Any],
    outcome: str,
    recorded_at: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Assemble one publishable ``reuse-event/v1`` payload.

    *run* and *pattern* are payloads of already-existing records; both are
    validated and pinned by hash, and the pattern pin binds the exact
    snapshot version that was used. ``recorded_at`` is injected by the
    caller — no clock here. The assembled payload is validated against its
    own schema before returning.
    """
    run_pin = _pin_member(run, _RUN_FAMILY, "run_id", "run")
    pattern_pin = _pin_member(pattern, _PATTERN_FAMILY, "pattern_id", "pattern")
    if note is not None:
        findings = scan_for_restricted(note, "note")
        if findings:
            raise ValueError("restricted content refused: " + "; ".join(findings))

    payload: dict[str, Any] = {
        "schema": _REUSE_FAMILY,
        "reuse_event_id": reuse_event_id,
        "run": run_pin,
        "pattern": pattern_pin,
        "outcome": outcome,
        "recorded_at": recorded_at,
    }
    if note is not None:
        payload["note"] = note
    try:
        load_record(canonical_bytes(payload))
    except Exception as exc:
        raise ValueError(f"assembled reuse event payload is not a valid core record: {exc}")
    return payload


def reuse_summary(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Rebuildable per-pattern outcome tallies over reuse-event payloads.

    Every event is validated; tallies key on the pinned pattern snapshot
    hash, so two versions of one pattern never blend. The result is
    deterministic and derivable from the event set at any time — it is
    registry-layer index data, not record content.
    """
    tallies: dict[str, dict[str, Any]] = {}
    for index, payload in enumerate(events):
        try:
            record = load_record(canonical_bytes(payload))
        except Exception as exc:
            raise ValueError(
                f"events[{index}] payload is not a valid core record: {exc}"
            )
        if record.schema_id != _REUSE_FAMILY:
            raise ValueError(
                f"events[{index}] payload declares {record.schema_id!r}; "
                f"expected {_REUSE_FAMILY!r}"
            )
        data = record.data
        pin = data["pattern"]
        bucket = tallies.setdefault(
            pin["sha256"],
            {
                "pattern_id": pin["pattern_id"],
                "helped": 0,
                "neutral": 0,
                "harmed": 0,
                "not_applicable": 0,
                "total": 0,
            },
        )
        bucket[data["outcome"]] += 1
        bucket["total"] += 1
    return {
        "events": len(events),
        "patterns": {key: tallies[key] for key in sorted(tallies)},
    }
