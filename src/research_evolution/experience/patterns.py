"""Pattern distillation, lifecycle versioning, and the registry index.

ADR-0007 decisions 3 and 9 (plan tasks 7/8/9): a pattern's lifecycle is
an append-only chain of immutable record versions — a transition never
edits a record, it publishes a successor with a new ``pattern_id``, an
ID-only ``supersedes`` pointer, a status snapshot, and a mandatory
rationale. This module supplies:

- :func:`distill_patterns` — build a fresh ``research-pattern/v1``
  payload from one or more source case payloads. Every source case passes
  :func:`~research_evolution.experience.assert_case_eligible` at the entry
  (R36 ledger item 3): ineligible cases never enter shareable patterns.
  A fresh distillation always lands at status ``distilled``.
- :func:`transition_pattern` — publish the next version on the chain.
  The lifecycle axis only moves forward (captured -> distilled ->
  candidate_pattern -> validated_pattern -> active_pattern) or sideways
  into a terminal state (deprecated/retired/rejected); terminal versions
  never move again. Promotion discipline (task 9): reaching
  candidate_pattern requires either at least two independent source cases
  or the single-case exception with all three attestation elements
  (reproduction, counterfactual fix, independent review) recorded into
  the rationale; a single-case pattern never goes beyond
  candidate_pattern.
- :func:`build_pattern_index` / :func:`pattern_chain` — the deterministic
  chain resolution the registry owes consumers (ADR consequences):
  status is a per-version snapshot, and the current state of a pattern is
  resolved by walking the supersedes chain.

As everywhere in this package: no clock (``created_at``/``last_validated``
are caller-injected), no I/O, plain ``ValueError`` failures, and the
assembled product is validated against its own schema before returning.
"""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..core import Record, canonical_bytes, canonical_sha256, load_record

from .cases import (
    _CASE_FAMILY,
    _scan_facets,
    assert_case_eligible,
    validate_case_payload,
)
from .redaction import scan_for_restricted

_PATTERN_FAMILY = "research-pattern/v1"

# The forward lifecycle axis and the terminal states (task 8). Terminal
# versions never transition again; anything else must move strictly
# forward along the axis.
_STATUS_ORDER = {
    "captured": 0,
    "distilled": 1,
    "candidate_pattern": 2,
    "validated_pattern": 3,
    "active_pattern": 4,
}
_TERMINAL_STATUSES = frozenset({"deprecated", "retired", "rejected"})

# Statuses a fresh promotion may claim on the merit of its source cases.
_PROMOTION_STATUSES = ("candidate_pattern", "validated_pattern", "active_pattern")


@dataclass(frozen=True)
class SingletonAttestation:
    """The three elements of the task-9 single-case exception:
    reproduction, counterfactual fix, and independent review."""

    reproduction: str
    counterfactual_fix: str
    independent_review: str

    def __post_init__(self) -> None:
        for field_name in ("reproduction", "counterfactual_fix", "independent_review"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"singleton attestation {field_name!r} must be a non-blank string"
                )


def _pin_pattern(payload: Mapping[str, Any], what: str) -> Record:
    try:
        record = load_record(canonical_bytes(payload))
    except Exception as exc:
        raise ValueError(f"{what} payload is not a valid core record: {exc}")
    if record.schema_id != _PATTERN_FAMILY:
        raise ValueError(
            f"{what} payload declares {record.schema_id!r}; "
            f"expected {_PATTERN_FAMILY!r}"
        )
    return record


def _pin_source_cases(
    cases: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not cases:
        raise ValueError("a pattern needs at least one source case")
    pins: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, payload in enumerate(cases):
        assert_case_eligible(payload)
        record = validate_case_payload(payload)
        case_id = record.data["case_id"]
        if case_id in seen:
            raise ValueError(
                f"source case {case_id!r} appears twice: source cases must be "
                "independent records"
            )
        seen.add(case_id)
        pins.append({"case_id": case_id, "sha256": record.sha256})
    return pins


def _scan_text_fields(fields: Sequence[tuple[str, Any]]) -> None:
    findings: list[str] = []
    for name, value in fields:
        if isinstance(value, str):
            findings.extend(scan_for_restricted(value, name))
        else:
            for index, item in enumerate(value):
                findings.extend(scan_for_restricted(item, f"{name}[{index}]"))
    if findings:
        raise ValueError("restricted content refused: " + "; ".join(findings))


def distill_patterns(
    *,
    cases: Sequence[Mapping[str, Any]],
    pattern_id: str,
    created_at: str,
    last_validated: str,
    scope: str,
    successful_tactics: Sequence[str],
    evidence_grade: str,
    evidence_rationale: str,
    confidence: str,
    transition_rationale: str,
    preconditions: Sequence[str] = (),
    contraindications: Sequence[str] = (),
    failed_tactics: Sequence[str] = (),
    signature_summary: str | None = None,
    signature_sha256: str | None = None,
    signature_facets: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Distill one fresh ``research-pattern/v1`` payload from source cases.

    The pattern signature is copied from the source cases when they all
    share one exact fingerprint; otherwise the caller must supply
    ``signature_summary``/``signature_sha256`` explicitly (distillation
    judgment across differing cases is the caller's call). One call
    distills one pattern proposal; the §4.3 "proposal set" is the caller
    iterating over its clusters. The result always has status
    ``distilled`` — reaching ``candidate_pattern`` is a
    :func:`transition_pattern` promotion with its own discipline.
    """
    pins = _pin_source_cases(cases)
    records = [validate_case_payload(payload) for payload in cases]

    if signature_sha256 is None:
        fingerprints = {
            record.data["problem_signature"]["signature_sha256"] for record in records
        }
        if len(fingerprints) != 1:
            raise ValueError(
                "source cases disagree on signature_sha256; supply "
                "signature_summary/signature_sha256 explicitly"
            )
        first_signature = records[0].data["problem_signature"]
        sig_summary = first_signature["summary"]
        sig_sha = first_signature["signature_sha256"]
        sig_facets = first_signature.get("facets")
    else:
        if signature_summary is None:
            raise ValueError("signature_summary is required with signature_sha256")
        sig_summary = signature_summary
        sig_sha = signature_sha256
        sig_facets = signature_facets

    _scan_text_fields(
        (
            ("scope", scope),
            ("preconditions", preconditions),
            ("contraindications", contraindications),
            ("successful_tactics", successful_tactics),
            ("failed_tactics", failed_tactics),
            ("evidence.grade", evidence_grade),
            ("evidence.rationale", evidence_rationale),
            ("transition_rationale", transition_rationale),
            ("problem_signature.summary", sig_summary),
        )
    )
    if sig_facets is not None:
        facet_findings: list[str] = []
        _scan_facets(sig_facets, "problem_signature.facets", facet_findings)
        if facet_findings:
            raise ValueError("restricted content refused: " + "; ".join(facet_findings))

    signature: dict[str, Any] = {
        "summary": sig_summary,
        "signature_sha256": sig_sha,
    }
    if sig_facets is not None:
        signature["facets"] = dict(sig_facets)

    payload: dict[str, Any] = {
        "schema": _PATTERN_FAMILY,
        "pattern_id": pattern_id,
        "problem_signature": signature,
        "scope": scope,
        "preconditions": list(preconditions),
        "contraindications": list(contraindications),
        "successful_tactics": list(successful_tactics),
        "failed_tactics": list(failed_tactics),
        "evidence": {"grade": evidence_grade, "rationale": evidence_rationale},
        "confidence": confidence,
        "source_cases": pins,
        "last_validated": last_validated,
        "status": "distilled",
        "transition_rationale": transition_rationale,
        "created_at": created_at,
    }
    try:
        load_record(canonical_bytes(payload))
    except Exception as exc:
        raise ValueError(f"assembled pattern payload is not a valid core record: {exc}")
    return payload


def transition_pattern(
    *,
    pattern: Mapping[str, Any],
    new_pattern_id: str,
    status: str,
    transition_rationale: str,
    created_at: str,
    last_validated: str | None = None,
    confidence: str | None = None,
    evidence_grade: str | None = None,
    evidence_rationale: str | None = None,
    scope: str | None = None,
    preconditions: Sequence[str] | None = None,
    contraindications: Sequence[str] | None = None,
    successful_tactics: Sequence[str] | None = None,
    failed_tactics: Sequence[str] | None = None,
    source_cases: Sequence[Mapping[str, Any]] | None = None,
    singleton_attestation: SingletonAttestation | None = None,
) -> dict[str, Any]:
    """Publish the next lifecycle version of a pattern.

    The successor carries a fresh ``pattern_id``, ``supersedes`` pointing
    at the predecessor's id, the new status snapshot, and the mandatory
    rationale; unmentioned content fields are copied from the predecessor
    unchanged. Lifecycle guard: terminal versions never move; non-terminal
    versions move strictly forward along the axis or sideways into a
    terminal state. Promotion guard (task 9): candidate_pattern with a
    single source case requires the three-element attestation, which is
    recorded into the rationale; validated_pattern/active_pattern always
    require at least two independent source cases.
    """
    record = _pin_pattern(pattern, "pattern")
    old = record.data
    old_id = old["pattern_id"]
    if new_pattern_id == old_id:
        raise ValueError(f"successor id {new_pattern_id!r} equals the predecessor id")
    old_status = old["status"]
    if old_status in _TERMINAL_STATUSES:
        raise ValueError(f"pattern {old_id!r} is terminal ({old_status}); it never moves")
    if status not in _STATUS_ORDER and status not in _TERMINAL_STATUSES:
        raise ValueError(f"unknown pattern status {status!r}")
    if status not in _TERMINAL_STATUSES and _STATUS_ORDER[status] <= _STATUS_ORDER[old_status]:
        raise ValueError(
            f"lifecycle moves strictly forward: {old_status} -> {status} refused"
        )

    if source_cases is not None:
        pins = _pin_source_cases(source_cases)
    else:
        pins = [dict(pin) for pin in old["source_cases"]]

    rationale = transition_rationale
    if status in _PROMOTION_STATUSES and len(pins) == 1:
        if status != "candidate_pattern":
            raise ValueError(
                "a single-case pattern never goes beyond candidate_pattern "
                "(task 9)"
            )
        if singleton_attestation is None:
            raise ValueError(
                "single-case promotion to candidate_pattern needs all three "
                "attestation elements (reproduction, counterfactual fix, "
                "independent review)"
            )
        rationale = (
            f"{transition_rationale} Singleton exception attestation: "
            f"reproduction={singleton_attestation.reproduction}; "
            f"counterfactual fix={singleton_attestation.counterfactual_fix}; "
            f"independent review={singleton_attestation.independent_review}."
        )
    if singleton_attestation is not None and status != "candidate_pattern":
        raise ValueError(
            "singleton attestation only applies to a candidate_pattern transition"
        )
    if singleton_attestation is not None and len(pins) != 1:
        raise ValueError("singleton attestation only applies to single-case patterns")

    text_fields: list[tuple[str, Any]] = [("transition_rationale", rationale)]
    for name, value in (
        ("scope", scope),
        ("preconditions", preconditions),
        ("contraindications", contraindications),
        ("successful_tactics", successful_tactics),
        ("failed_tactics", failed_tactics),
        ("evidence.grade", evidence_grade),
        ("evidence.rationale", evidence_rationale),
    ):
        if value is not None:
            text_fields.append((name, value))
    _scan_text_fields(text_fields)

    payload: dict[str, Any] = dict(old)
    payload["pattern_id"] = new_pattern_id
    payload["supersedes"] = old_id
    payload["status"] = status
    payload["transition_rationale"] = rationale
    payload["created_at"] = created_at
    payload["source_cases"] = pins
    if last_validated is not None:
        payload["last_validated"] = last_validated
    if confidence is not None:
        payload["confidence"] = confidence
    if evidence_grade is not None or evidence_rationale is not None:
        payload["evidence"] = {
            "grade": evidence_grade if evidence_grade is not None else old["evidence"]["grade"],
            "rationale": (
                evidence_rationale
                if evidence_rationale is not None
                else old["evidence"]["rationale"]
            ),
        }
    for name, value in (
        ("scope", scope),
        ("preconditions", preconditions),
        ("contraindications", contraindications),
        ("successful_tactics", successful_tactics),
        ("failed_tactics", failed_tactics),
    ):
        if value is not None:
            payload[name] = list(value)
    try:
        load_record(canonical_bytes(payload))
    except Exception as exc:
        raise ValueError(f"assembled pattern payload is not a valid core record: {exc}")
    return payload


@dataclass(frozen=True)
class PatternIndex:
    """A deterministic, rebuildable registry index over pattern records."""

    records: tuple[dict[str, Any], ...]
    tips: tuple[str, ...]
    sha256: str


def build_pattern_index(patterns: Sequence[Mapping[str, Any]]) -> PatternIndex:
    """Validate pattern payloads and compute the chain tips.

    Tips are versions no other record supersedes — the current snapshot of
    each chain. Forks (two versions superseding one predecessor) surface
    as two tips; nothing is hidden. The index hash binds the exact record
    set, so the index is a rebuildable derivation, not a fact source.
    """
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, payload in enumerate(patterns):
        record = _pin_pattern(payload, f"patterns[{index}]")
        pattern_id = record.data["pattern_id"]
        if pattern_id in seen:
            raise ValueError(f"duplicate pattern_id {pattern_id!r} in input")
        seen.add(pattern_id)
        records.append(record.data)
    records.sort(key=lambda data: data["pattern_id"])
    superseded = {data["supersedes"] for data in records if "supersedes" in data}
    tips = tuple(
        data["pattern_id"] for data in records if data["pattern_id"] not in superseded
    )
    sha = canonical_sha256(
        {"records": sorted(canonical_sha256(record) for record in records)}
    )
    return PatternIndex(records=tuple(records), tips=tips, sha256=sha)


def pattern_chain(index: PatternIndex, tip: str) -> tuple[dict[str, Any], ...]:
    """Walk a chain from *tip* back to its root, deterministically.

    A missing predecessor means the index is incomplete; a cycle means
    corruption. Both fail closed — the graph verifier normally catches
    them first at publication time.
    """
    if not isinstance(index, PatternIndex):
        raise ValueError("index must be a PatternIndex")
    by_id = {data["pattern_id"]: data for data in index.records}
    if tip not in by_id:
        raise ValueError(f"tip {tip!r} is not in the index")
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: str | None = tip
    while current is not None:
        if current in seen:
            raise ValueError(f"pattern chain contains a cycle at {current!r}")
        data = by_id.get(current)
        if data is None:
            raise ValueError(
                f"pattern chain broken: predecessor {current!r} is missing "
                "from the index"
            )
        seen.add(current)
        chain.append(data)
        current = data.get("supersedes")
    return tuple(chain)
