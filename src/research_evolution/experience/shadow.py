"""Shadow heuristics: hypothetical-only trial records (plan task 16).

A shadow report is the Phase 4 ceiling artifact for a heuristic
(ADR-0007 decision 8): three to eight ``shadow``-status heuristics are
trialed against one research run and the module records only the
*hypothetical* decisions the heuristics would have forced.  Shadow
heuristics never mutate production behavior, records, or registries.

The report payload is deliberately a registry-layer artifact rather
than a Core record family: shadowing is a trial discipline, not an
exchange contract, and the schema layer stays at the 17 families
registered through M2 (ADR-0006 decision 1).  The payload therefore
carries no ``"schema"`` key and is not round-tripped through
:func:`research_evolution.core.load_record`; every member is pinned to
a validated heuristic or run ``Record`` so no hash is ever hand-written
(R34 note).

The module is deterministic and offline: no wall clock
(``recorded_at`` is a required caller-supplied parameter), no random
sources, no I/O, and no imports outside the Core public face.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core import canonical_sha256
from .cases import _pin_member
from .heuristics import _pin_heuristic
from .redaction import scan_for_restricted

_RUN_FAMILY = "research-run/v1"
_SHADOW_STATUS = "shadow"
_MIN_HEURISTICS = 3
_MAX_HEURISTICS = 8


@dataclass(frozen=True)
class ShadowReport:
    """Structured shadow report plus its canonical hash."""

    payload: dict[str, Any]
    sha256: str


def _pin_shadow_heuristic(heuristic: Any, index: int) -> dict[str, str]:
    record = _pin_heuristic(heuristic, f"heuristics[{index}]")
    status = record.data.get("status")
    if status != _SHADOW_STATUS:
        raise ValueError(
            "shadow reports only trial heuristics whose status is "
            f"{_SHADOW_STATUS!r}; got {status!r}"
        )
    return {
        "heuristic_id": record.data["heuristic_id"],
        "sha256": record.sha256,
    }


def record_shadow_report(
    *,
    heuristics: list[Any],
    run: Any,
    observations: list[dict[str, Any]],
    recorded_at: str,
) -> ShadowReport:
    """Assemble a deterministic shadow report payload.

    ``heuristics`` must hold three to eight distinct shadow-status
    heuristic/v1 payloads; ``run`` is the research-run/v1 payload the
    trial replays; ``observations`` covers each trialed heuristic
    exactly once with the hypothetical decision it would have forced
    and the expected difference.  All free text passes the default-deny
    scan (S7 redaction discipline); ``recorded_at`` is caller-supplied
    and required.
    """

    if not isinstance(recorded_at, str) or not recorded_at.strip():
        raise ValueError("recorded_at must be a non-empty string")
    if not isinstance(heuristics, (list, tuple)):
        raise ValueError("heuristics must be a list")
    if not (_MIN_HEURISTICS <= len(heuristics) <= _MAX_HEURISTICS):
        raise ValueError(
            "shadow reports trial between "
            f"{_MIN_HEURISTICS} and {_MAX_HEURISTICS} heuristics; got "
            f"{len(heuristics)}"
        )
    heuristic_pins = sorted(
        (_pin_shadow_heuristic(entry, index) for index, entry in enumerate(heuristics)),
        key=lambda pin: pin["heuristic_id"],
    )
    heuristic_ids = [pin["heuristic_id"] for pin in heuristic_pins]
    if len(set(heuristic_ids)) != len(heuristic_ids):
        raise ValueError("shadow heuristics must be distinct records")

    run_pin = _pin_member(run, _RUN_FAMILY, "run_id", "shadow run")

    if not isinstance(observations, (list, tuple)):
        raise ValueError("observations must be a list")
    if len(observations) != len(heuristic_pins):
        raise ValueError(
            "observations must cover each trialed heuristic exactly "
            f"once; got {len(observations)} observations for "
            f"{len(heuristic_pins)} heuristics"
        )
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise ValueError(f"observations[{index}] must be an object")
        allowed = {"heuristic_id", "hypothetical_decision", "expected_difference"}
        extra = sorted(set(observation) - allowed)
        missing = sorted(allowed - set(observation))
        if extra or missing:
            raise ValueError(
                f"observations[{index}] keys must be exactly {sorted(allowed)}; "
                f"extra={extra} missing={missing}"
            )
        heuristic_id = observation["heuristic_id"]
        if not isinstance(heuristic_id, str):
            raise ValueError(f"observations[{index}].heuristic_id must be a string")
        if heuristic_id in seen:
            raise ValueError(
                f"observations[{index}] duplicates heuristic {heuristic_id!r}"
            )
        seen.add(heuristic_id)
        decision = observation["hypothetical_decision"]
        difference = observation["expected_difference"]
        if not isinstance(decision, str) or not decision.strip():
            raise ValueError(
                f"observations[{index}].hypothetical_decision must be a "
                "non-empty string"
            )
        if not isinstance(difference, str) or not difference.strip():
            raise ValueError(
                f"observations[{index}].expected_difference must be a "
                "non-empty string"
            )
        findings = [
            *scan_for_restricted(decision, f"observations[{index}].hypothetical_decision"),
            *scan_for_restricted(
                difference, f"observations[{index}].expected_difference"
            ),
        ]
        if findings:
            raise ValueError("shadow observation rejected: " + "; ".join(findings))
        normalized.append(
            {
                "heuristic_id": heuristic_id,
                "hypothetical_decision": decision,
                "expected_difference": difference,
            }
        )
    unknown = sorted(seen - set(heuristic_ids))
    if unknown:
        raise ValueError(
            "observations reference heuristics outside the trial set: "
            + ", ".join(unknown)
        )
    normalized.sort(key=lambda entry: entry["heuristic_id"])

    payload = {
        "kind": "shadow-report",
        "run": run_pin,
        "heuristics": heuristic_pins,
        "observations": normalized,
        "recorded_at": recorded_at,
    }
    return ShadowReport(payload=payload, sha256=canonical_sha256(payload))
