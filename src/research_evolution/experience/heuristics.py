"""Heuristic proposals, lifecycle versioning, and the registry index.

ADR-0007 decision 7 (plan tasks 12/13/15): a heuristic is a behavioral
rule with evidence support, scope, and a rollback path. Its lifecycle is
an append-only chain of immutable record versions — same supersedes
machine as patterns (decision 3). The Phase 4 ceiling is ``shadow``:
``validated``/``promoted``/``deprecated``/``retired`` exist in the schema
vocabulary so later phases need no schema change, but they are
unreachable in this phase and are refused here; ``rejected`` is the only
reachable terminal state.

There is deliberately no multi-case requirement on the heuristic side
(unlike pattern promotion): task 15's floor is at least one pinned
regression case, enforced by the schema itself, and the shadow ceiling
means no heuristic can influence production behavior this phase. The
guardrail is the ceiling, not the source count.

No clock (``created_at`` is caller-injected), no I/O, plain
``ValueError`` failures, and every assembled payload is validated against
its own schema before returning.
"""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..core import Record, canonical_bytes, canonical_sha256, load_record

from .cases import _CASE_FAMILY, _pin_member
from .redaction import scan_for_restricted

_HEURISTIC_FAMILY = "heuristic/v1"

# Forward lifecycle axis and the Phase 4 ceiling (task 13, plan section
# 3.2). ``rejected`` is the only terminal state reachable this phase.
_STATUS_ORDER = {
    "lesson_hypothesis": 0,
    "candidate": 1,
    "shadow": 2,
}
_PHASE4_UNREACHABLE = frozenset({"validated", "promoted", "deprecated", "retired"})
_TERMINAL_STATUSES = frozenset({"rejected"})


def _pin_heuristic(payload: Mapping[str, Any], what: str) -> Record:
    try:
        record = load_record(canonical_bytes(payload))
    except Exception as exc:
        raise ValueError(f"{what} payload is not a valid core record: {exc}")
    if record.schema_id != _HEURISTIC_FAMILY:
        raise ValueError(
            f"{what} payload declares {record.schema_id!r}; "
            f"expected {_HEURISTIC_FAMILY!r}"
        )
    return record


def _pin_regression_cases(
    cases: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    pins = [
        _pin_member(payload, _CASE_FAMILY, "case_id", f"regression_cases[{index}]")
        for index, payload in enumerate(cases)
    ]
    seen = {pin["case_id"] for pin in pins}
    if len(seen) != len(pins):
        raise ValueError("regression_cases must be distinct case records")
    return pins


def _scan_heuristic_text(fields: Sequence[tuple[str, Any]]) -> None:
    findings: list[str] = []
    for name, value in fields:
        if isinstance(value, str):
            findings.extend(scan_for_restricted(value, name))
        else:
            for index, item in enumerate(value):
                findings.extend(scan_for_restricted(item, f"{name}[{index}]"))
    if findings:
        raise ValueError("restricted content refused: " + "; ".join(findings))


def propose_heuristic(
    *,
    heuristic_id: str,
    statement: str,
    scope: str,
    mode: str,
    evidence: Sequence[str],
    risk: str,
    rollback: str,
    transition_rationale: str,
    regression_cases: Sequence[Mapping[str, Any]],
    created_at: str,
    exception: Sequence[str] = (),
) -> dict[str, Any]:
    """Assemble one fresh ``heuristic/v1`` payload at ``lesson_hypothesis``.

    ``regression_cases`` are payloads of already-existing
    research-case-package/v2 records, each validated and pinned by hash
    (task 15's mandatory association). Promotion to ``candidate`` and
    ``shadow`` goes through :func:`transition_heuristic`.
    """
    pins = _pin_regression_cases(regression_cases)
    _scan_heuristic_text(
        (
            ("statement", statement),
            ("scope", scope),
            ("evidence", evidence),
            ("exception", exception),
            ("risk", risk),
            ("rollback", rollback),
            ("transition_rationale", transition_rationale),
        )
    )
    payload: dict[str, Any] = {
        "schema": _HEURISTIC_FAMILY,
        "heuristic_id": heuristic_id,
        "statement": statement,
        "scope": scope,
        "mode": mode,
        "evidence": list(evidence),
        "exception": list(exception),
        "risk": risk,
        "rollback": rollback,
        "status": "lesson_hypothesis",
        "transition_rationale": transition_rationale,
        "regression_cases": pins,
        "created_at": created_at,
    }
    try:
        load_record(canonical_bytes(payload))
    except Exception as exc:
        raise ValueError(f"assembled heuristic payload is not a valid core record: {exc}")
    return payload


def transition_heuristic(
    *,
    heuristic: Mapping[str, Any],
    new_heuristic_id: str,
    status: str,
    transition_rationale: str,
    created_at: str,
    statement: str | None = None,
    scope: str | None = None,
    mode: str | None = None,
    evidence: Sequence[str] | None = None,
    exception: Sequence[str] | None = None,
    risk: str | None = None,
    rollback: str | None = None,
    regression_cases: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Publish the next lifecycle version of a heuristic.

    The successor carries a fresh ``heuristic_id``, ``supersedes``
    pointing at the predecessor, the new status snapshot, and the
    mandatory rationale; unmentioned fields are copied unchanged.
    Lifecycle guard: the axis only moves forward (lesson_hypothesis ->
    candidate -> shadow); ``rejected`` is reachable sideways and then
    frozen; the four later vocabulary states are refused outright (the
    Phase 4 ceiling is shadow).
    """
    record = _pin_heuristic(heuristic, "heuristic")
    old = record.data
    old_id = old["heuristic_id"]
    if new_heuristic_id == old_id:
        raise ValueError(f"successor id {new_heuristic_id!r} equals the predecessor id")
    old_status = old["status"]
    if old_status in _TERMINAL_STATUSES:
        raise ValueError(f"heuristic {old_id!r} is terminal ({old_status}); it never moves")
    if status in _PHASE4_UNREACHABLE:
        raise ValueError(
            f"status {status!r} is beyond the Phase 4 ceiling: shadow is the "
            "highest reachable state this phase"
        )
    if status not in _STATUS_ORDER and status not in _TERMINAL_STATUSES:
        raise ValueError(f"unknown heuristic status {status!r}")
    if old_status in _PHASE4_UNREACHABLE:
        raise ValueError(
            f"heuristic {old_id!r} sits at {old_status}, which is unreachable "
            "in Phase 4; refusing to extend the chain"
        )
    if status not in _TERMINAL_STATUSES and _STATUS_ORDER[status] <= _STATUS_ORDER[old_status]:
        raise ValueError(
            f"lifecycle moves strictly forward: {old_status} -> {status} refused"
        )

    if regression_cases is not None:
        pins = _pin_regression_cases(regression_cases)
    else:
        pins = [dict(pin) for pin in old["regression_cases"]]

    text_fields: list[tuple[str, Any]] = [("transition_rationale", transition_rationale)]
    for name, value in (
        ("statement", statement),
        ("scope", scope),
        ("evidence", evidence),
        ("exception", exception),
        ("risk", risk),
        ("rollback", rollback),
    ):
        if value is not None:
            text_fields.append((name, value))
    _scan_heuristic_text(text_fields)

    payload: dict[str, Any] = dict(old)
    payload["heuristic_id"] = new_heuristic_id
    payload["supersedes"] = old_id
    payload["status"] = status
    payload["transition_rationale"] = transition_rationale
    payload["created_at"] = created_at
    payload["regression_cases"] = pins
    for name, value in (
        ("statement", statement),
        ("scope", scope),
        ("mode", mode),
        ("evidence", evidence),
        ("exception", exception),
        ("risk", risk),
        ("rollback", rollback),
    ):
        if value is not None:
            payload[name] = list(value) if isinstance(value, (list, tuple)) else value
    try:
        load_record(canonical_bytes(payload))
    except Exception as exc:
        raise ValueError(f"assembled heuristic payload is not a valid core record: {exc}")
    return payload


@dataclass(frozen=True)
class HeuristicIndex:
    """A deterministic, rebuildable registry index over heuristic records."""

    records: tuple[dict[str, Any], ...]
    tips: tuple[str, ...]
    sha256: str


def build_heuristic_index(heuristics: Sequence[Mapping[str, Any]]) -> HeuristicIndex:
    """Validate heuristic payloads and compute the chain tips.

    Mirrors :func:`build_pattern_index`: tips are versions no other
    record supersedes, forks surface as multiple tips, and the index hash
    binds the exact record set.
    """
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, payload in enumerate(heuristics):
        record = _pin_heuristic(payload, f"heuristics[{index}]")
        heuristic_id = record.data["heuristic_id"]
        if heuristic_id in seen:
            raise ValueError(f"duplicate heuristic_id {heuristic_id!r} in input")
        seen.add(heuristic_id)
        records.append(record.data)
    records.sort(key=lambda data: data["heuristic_id"])
    superseded = {data["supersedes"] for data in records if "supersedes" in data}
    tips = tuple(
        data["heuristic_id"]
        for data in records
        if data["heuristic_id"] not in superseded
    )
    sha = canonical_sha256(
        {"records": sorted(canonical_sha256(record) for record in records)}
    )
    return HeuristicIndex(records=tuple(records), tips=tips, sha256=sha)


def heuristic_chain(index: HeuristicIndex, tip: str) -> tuple[dict[str, Any], ...]:
    """Walk a heuristic chain from *tip* back to its root (fail closed)."""
    if not isinstance(index, HeuristicIndex):
        raise ValueError("index must be a HeuristicIndex")
    by_id = {data["heuristic_id"]: data for data in index.records}
    if tip not in by_id:
        raise ValueError(f"tip {tip!r} is not in the index")
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: str | None = tip
    while current is not None:
        if current in seen:
            raise ValueError(f"heuristic chain contains a cycle at {current!r}")
        data = by_id.get(current)
        if data is None:
            raise ValueError(
                f"heuristic chain broken: predecessor {current!r} is missing "
                "from the index"
            )
        seen.add(current)
        chain.append(data)
        current = data.get("supersedes")
    return tuple(chain)
