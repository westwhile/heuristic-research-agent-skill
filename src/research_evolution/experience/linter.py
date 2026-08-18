"""Deterministic heuristic linter and registry policy gates (ADR-0007
decision 7, plan tasks 14/16/17, acceptance gate 8).

The four task-14 check classes are deterministic screens over documented
narrow conventions — free text cannot prove semantics, so each check is
deliberately a necessary-condition screen, and human review remains the
semantic authority:

- ``duplicate``: two chain tips with equal normalized
  ``(statement, scope)`` — exact duplicates across chains are copy
  errors, never legitimate;
- ``conflict``: two tips with equal normalized scope whose statements
  become token-equal after removing negation words, with exactly one
  side negated ("never validate" vs "validate" under one scope);
- ``precedence_cycle``: exception entries cite other heuristic ids
  (token-exact); the yields-to graph must be acyclic;
- ``dead_rule`` / ``always_triggered``: normalized scope matches a
  frozen vocabulary (``never``/``nowhere``/... vs
  ``always``/``everywhere``/...).

Vacuous rollback (gate 8's real bite): a rollback is vacuous when it
matches a frozen boilerplate phrase, keeps fewer than three content
tokens after stopword removal, or copies the statement/risk text. A
blocking rule with a vacuous rollback is REJECTED; an advisory one is
reported. An always-triggered blocking rule is likewise rejected — plan
task 17 allows only deterministic global invariants as global hard
gates, and free text cannot certify itself deterministic, so in this
phase no free-text blocking rule may claim universal scope.

Task 16's complexity budget, compression review, and staleness review
are report-severity checks; the lint run itself is a hash-bound
registry-layer report artifact (``LintReport.report_sha256``), not a
core record. ``now`` is caller-injected — the linter has no clock.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from ..core import canonical_bytes, canonical_sha256, load_record

from .clustering import _jaccard, _token_set
from .heuristics import _HEURISTIC_FAMILY, _pin_heuristic
from .patterns import _PATTERN_FAMILY

_REJECT = "reject"
_REPORT = "report"

_LINT_KINDS = (
    "duplicate",
    "conflict",
    "precedence_cycle",
    "dead_rule",
    "always_triggered",
    "vacuous_rollback",
    "complexity_budget",
    "compression_candidate",
    "staleness",
)

_NEGATION_TOKENS = frozenset({"never", "not", "no"})
_DEAD_SCOPES = frozenset({"never", "nowhere", "none", "no scope"})
_UNIVERSAL_SCOPES = frozenset({"always", "everywhere", "all", "global", "*", "everything"})
_VACUOUS_ROLLBACK_PHRASES = frozenset(
    {
        "n/a",
        "na",
        "none",
        "nothing",
        "no rollback",
        "no rollback needed",
        "not needed",
        "undo",
        "undo it",
        "revert",
        "just revert",
        "just undo it",
        "roll back",
        "rollback",
        "trivial",
    }
)
_ROLLBACK_STOPWORDS = frozenset(
    {
        "the", "a", "an", "it", "is", "to", "of", "and", "or", "be",
        "this", "that", "just", "simply", "by", "in", "on",
    }
)
_MIN_ROLLBACK_CONTENT_TOKENS = 3
_MAX_HEURISTIC_TOKENS = 200
_MAX_REGISTRY_TIPS = 50
_COMPRESSION_JACCARD = 0.8

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class LintFinding:
    """One deterministic lint finding; ``severity`` is reject or report."""

    kind: str
    severity: str
    heuristic_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class LintReport:
    """The full lint outcome plus its hash-bound report artifact."""

    findings: tuple[LintFinding, ...]
    report_entry: dict[str, Any]
    report_sha256: str

    @property
    def rejections(self) -> tuple[LintFinding, ...]:
        return tuple(f for f in self.findings if f.severity == _REJECT)


def _normalize(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


def _pins(heuristics: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    tips: list[dict[str, Any]] = []
    seen: set[str] = set()
    superseded: set[str] = set()
    datas: list[dict[str, Any]] = []
    for index, payload in enumerate(heuristics):
        record = _pin_heuristic(payload, f"heuristics[{index}]")
        data = record.data
        if data["heuristic_id"] in seen:
            raise ValueError(f"duplicate heuristic_id {data['heuristic_id']!r} in input")
        seen.add(data["heuristic_id"])
        if "supersedes" in data:
            superseded.add(data["supersedes"])
        datas.append(data)
    return [data for data in datas if data["heuristic_id"] not in superseded]


def _rollback_vacuity(data: Mapping[str, Any]) -> str | None:
    normalized = _normalize(data["rollback"])
    if normalized in _VACUOUS_ROLLBACK_PHRASES:
        return "matches a frozen vacuous phrase"
    if normalized in (_normalize(data["statement"]), _normalize(data["risk"])):
        return "copies the statement or risk text"
    content_tokens = [
        token
        for token in _token_set(normalized)
        if token not in _ROLLBACK_STOPWORDS
    ]
    if len(content_tokens) < _MIN_ROLLBACK_CONTENT_TOKENS:
        return (
            f"fewer than {_MIN_ROLLBACK_CONTENT_TOKENS} content tokens "
            "after stopword removal"
        )
    return None


def _lint_duplicates(tips: Sequence[Mapping[str, Any]]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    by_key: dict[tuple[str, str], list[str]] = {}
    for data in tips:
        key = (_normalize(data["statement"]), _normalize(data["scope"]))
        by_key.setdefault(key, []).append(data["heuristic_id"])
    for key in sorted(by_key):
        ids = sorted(by_key[key])
        if len(ids) > 1:
            findings.append(
                LintFinding(
                    kind="duplicate",
                    severity=_REJECT,
                    heuristic_ids=tuple(ids),
                    detail="identical normalized statement and scope across chains",
                )
            )
    return findings


def _lint_conflicts(tips: Sequence[Mapping[str, Any]]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    by_scope: dict[str, list[Mapping[str, Any]]] = {}
    for data in tips:
        by_scope.setdefault(_normalize(data["scope"]), []).append(data)
    for scope in sorted(by_scope):
        group = sorted(by_scope[scope], key=lambda data: data["heuristic_id"])
        for position, left in enumerate(group):
            left_tokens = _token_set(_normalize(left["statement"]))
            for right in group[position + 1 :]:
                right_tokens = _token_set(_normalize(right["statement"]))
                left_core = left_tokens - _NEGATION_TOKENS
                right_core = right_tokens - _NEGATION_TOKENS
                if not left_core or left_core != right_core:
                    continue
                left_negated = bool(left_tokens & _NEGATION_TOKENS)
                right_negated = bool(right_tokens & _NEGATION_TOKENS)
                if left_negated != right_negated:
                    ids = tuple(sorted([left["heuristic_id"], right["heuristic_id"]]))
                    findings.append(
                        LintFinding(
                            kind="conflict",
                            severity=_REJECT,
                            heuristic_ids=ids,
                            detail="same scope, negation-asymmetric statements with "
                            "identical content tokens",
                        )
                    )
    return findings


def _lint_precedence_cycles(tips: Sequence[Mapping[str, Any]]) -> list[LintFinding]:
    ids = {data["heuristic_id"] for data in tips}
    edges: dict[str, set[str]] = {}
    for data in tips:
        cited: set[str] = set()
        for entry in data["exception"]:
            for token in entry.split():
                if token in ids and token != data["heuristic_id"]:
                    cited.add(token)
        edges[data["heuristic_id"]] = cited
    findings: list[LintFinding] = []
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in sorted(edges[node]):
            if state.get(nxt) == 1:
                cycle = stack[stack.index(nxt):] + [nxt]
                findings.append(
                    LintFinding(
                        kind="precedence_cycle",
                        severity=_REJECT,
                        heuristic_ids=tuple(cycle[:-1]),
                        detail="exception citations form a precedence cycle: "
                        + " -> ".join(cycle),
                    )
            )
            elif state.get(nxt) != 2:
                visit(nxt)
        stack.pop()
        state[node] = 2

    for data in tips:
        node = data["heuristic_id"]
        if state.get(node) != 2:
            visit(node)
    return findings


def _lint_scopes(tips: Sequence[Mapping[str, Any]]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for data in sorted(tips, key=lambda item: item["heuristic_id"]):
        scope = _normalize(data["scope"])
        if scope in _DEAD_SCOPES:
            findings.append(
                LintFinding(
                    kind="dead_rule",
                    severity=_REPORT,
                    heuristic_ids=(data["heuristic_id"],),
                    detail=f"scope {scope!r} can never apply",
                )
            )
        if scope in _UNIVERSAL_SCOPES:
            blocking = data["mode"] == "blocking"
            findings.append(
                LintFinding(
                    kind="always_triggered",
                    severity=_REJECT if blocking else _REPORT,
                    heuristic_ids=(data["heuristic_id"],),
                    detail=(
                        f"universal scope {scope!r} on a blocking rule: only a "
                        "deterministic global invariant may gate globally, and "
                        "free text cannot certify that (task 17)"
                        if blocking
                        else f"universal scope {scope!r}; the rule fires everywhere"
                    ),
                )
            )
    return findings


def _lint_rollbacks(tips: Sequence[Mapping[str, Any]]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for data in sorted(tips, key=lambda item: item["heuristic_id"]):
        reason = _rollback_vacuity(data)
        if reason is None:
            continue
        blocking = data["mode"] == "blocking"
        findings.append(
            LintFinding(
                kind="vacuous_rollback",
                severity=_REJECT if blocking else _REPORT,
                heuristic_ids=(data["heuristic_id"],),
                detail=f"rollback is vacuous ({reason})"
                + (" on a blocking rule" if blocking else ""),
            )
        )
    return findings


def _lint_reports(
    tips: Sequence[Mapping[str, Any]],
    *,
    now: str,
    staleness_days: int,
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for data in sorted(tips, key=lambda item: item["heuristic_id"]):
        tokens = _token_set(
            " ".join(
                [data["statement"], data["scope"], data["risk"], data["rollback"]]
                + list(data["evidence"])
                + list(data["exception"])
            )
        )
        if len(tokens) > _MAX_HEURISTIC_TOKENS:
            findings.append(
                LintFinding(
                    kind="complexity_budget",
                    severity=_REPORT,
                    heuristic_ids=(data["heuristic_id"],),
                    detail=f"{len(tokens)} distinct content tokens exceed the "
                    f"{_MAX_HEURISTIC_TOKENS} budget",
                )
            )
    if len(tips) > _MAX_REGISTRY_TIPS:
        findings.append(
            LintFinding(
                kind="complexity_budget",
                severity=_REPORT,
                heuristic_ids=(),
                detail=f"{len(tips)} tips exceed the {_MAX_REGISTRY_TIPS} registry budget",
            )
        )
    ordered = sorted(tips, key=lambda item: item["heuristic_id"])
    for position, left in enumerate(ordered):
        for right in ordered[position + 1 :]:
            overlap = _jaccard(
                _token_set(_normalize(left["statement"])),
                _token_set(_normalize(right["statement"])),
            )
            if overlap >= _COMPRESSION_JACCARD:
                findings.append(
                    LintFinding(
                        kind="compression_candidate",
                        severity=_REPORT,
                        heuristic_ids=(left["heuristic_id"], right["heuristic_id"]),
                        detail=f"statement token overlap {overlap:.6f} suggests a merge",
                    )
                )
    try:
        now_dt = datetime.fromisoformat(now)
    except ValueError as exc:
        raise ValueError(f"now must be an RFC3339 datetime: {exc}")
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    horizon = now_dt - timedelta(days=staleness_days)
    for data in ordered:
        created = datetime.fromisoformat(data["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < horizon:
            findings.append(
                LintFinding(
                    kind="staleness",
                    severity=_REPORT,
                    heuristic_ids=(data["heuristic_id"],),
                    detail=f"tip created {data['created_at']} is older than "
                    f"{staleness_days} days relative to {now}",
                )
            )
    return findings


def lint_heuristics(
    heuristics: Sequence[Mapping[str, Any]],
    *,
    now: str,
    staleness_days: int = 90,
) -> LintReport:
    """Run every deterministic check over the chain tips of *heuristics*.

    Superseded versions are historical facts, not lint targets. Findings
    are deterministic and stably ordered; the report artifact is
    hash-bound and rebuildable, never a store record.
    """
    if isinstance(staleness_days, bool) or not isinstance(staleness_days, int):
        raise ValueError("staleness_days must be an int")
    if staleness_days < 1:
        raise ValueError("staleness_days must be positive")
    tips = _pins(heuristics)
    findings: list[LintFinding] = []
    findings.extend(_lint_duplicates(tips))
    findings.extend(_lint_conflicts(tips))
    findings.extend(_lint_precedence_cycles(tips))
    findings.extend(_lint_scopes(tips))
    findings.extend(_lint_rollbacks(tips))
    findings.extend(_lint_reports(tips, now=now, staleness_days=staleness_days))
    report_entry: dict[str, Any] = {
        "kind": "heuristic-lint-report",
        "now": now,
        "staleness_days": staleness_days,
        "tips": len(tips),
        "findings": [
            {
                "kind": finding.kind,
                "severity": finding.severity,
                "heuristic_ids": list(finding.heuristic_ids),
                "detail": finding.detail,
            }
            for finding in findings
        ],
    }
    return LintReport(
        findings=tuple(findings),
        report_entry=report_entry,
        report_sha256=canonical_sha256(report_entry),
    )


def assert_registry_clean(
    heuristics: Sequence[Mapping[str, Any]],
    *,
    now: str,
    staleness_days: int = 90,
) -> None:
    """Fail closed when any reject-severity finding exists (gate 8)."""
    report = lint_heuristics(heuristics, now=now, staleness_days=staleness_days)
    if report.rejections:
        raise ValueError(
            "registry lint rejected: "
            + "; ".join(
                f"{finding.kind} {list(finding.heuristic_ids)}: {finding.detail}"
                for finding in report.rejections
            )
        )


def assert_no_promoted_skill(pattern: Mapping[str, Any]) -> None:
    """Phase 4 registry policy: a pattern record with a populated
    ``promoted_skill`` pointer is rejected outright — there is no
    promotion path this phase (R35/R36 ledger)."""
    try:
        record = load_record(canonical_bytes(pattern))
    except Exception as exc:
        raise ValueError(f"pattern payload is not a valid core record: {exc}")
    if record.schema_id != _PATTERN_FAMILY:
        raise ValueError(
            f"pattern payload declares {record.schema_id!r}; "
            f"expected {_PATTERN_FAMILY!r}"
        )
    if "promoted_skill" in record.data:
        raise ValueError(
            "Phase 4 has no promotion path: promoted_skill must be absent"
        )
