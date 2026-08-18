"""Deterministic retrieval MVP for research patterns (ADR-0007 decision 5).

Plan tasks 10/11 and architecture section 4.3: deterministic metadata /
text retrieval only — no embedding, no vectors. The hard problem's
signature is frozen before the query; the answer is at most a handful of
candidates, each carrying the six contract elements: applicability,
contraindications, evidence, source, last-validated, and a difference
note. An empty result is a legitimate, explicitly marked abstain — never
a silent absence. Similarity only proposes candidates; it is never an
execution or promotion basis, and only chain tips at candidate_pattern or
beyond (never terminal versions) are retrievable.

A retrieval session is a registry-layer hash-bound artifact, not a fact:
``RetrievalResult.session_entry``/``session_sha256`` let the caller
persist the session in catalogs without flooding the store. Only actual
reuse outcomes become records (decision 6, ``reuse.py``).
"""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..core import canonical_sha256

from .cases import _scan_facets
from .clustering import _jaccard, _token_set
from .patterns import PatternIndex, build_pattern_index
from .redaction import scan_for_restricted

# Only promoted, non-terminal versions serve retrieval: a distilled
# proposal is not yet a candidate, and terminal versions are done.
_RETRIEVABLE_STATUSES = ("candidate_pattern", "validated_pattern", "active_pattern")

_TIER_NAMES = ("exact_fingerprint", "structural_fields", "semantic_proposal")


@dataclass(frozen=True)
class PatternCandidate:
    """One retrieval candidate with the six contract elements plus the
    match metadata that explains why it surfaced."""

    pattern_id: str
    sha256: str
    status: str
    match_tier: str
    score: float
    applicability: dict[str, Any]
    contraindications: tuple[str, ...]
    evidence: dict[str, str]
    source_cases: tuple[dict[str, Any], ...]
    last_validated: str
    differences: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalResult:
    """The answer to one retrieval query; ``abstained`` is explicit."""

    abstained: bool
    candidates: tuple[PatternCandidate, ...]
    session_entry: dict[str, Any]
    session_sha256: str


def _shared_facet_pairs(
    query_facets: Mapping[str, Any], pattern_facets: Mapping[str, Any]
) -> int:
    return sum(
        1
        for key, value in query_facets.items()
        if key in pattern_facets and pattern_facets[key] == value
    )


def retrieve_patterns(
    *,
    signature_summary: str,
    signature_sha256: str,
    patterns: Sequence[Mapping[str, Any]] | PatternIndex,
    facets: Mapping[str, Any] | None = None,
    limit: int = 5,
    recorded_at: str,
) -> RetrievalResult:
    """Retrieve up to *limit* pattern candidates for a frozen signature.

    Ranking is deterministic: exact fingerprint first, then structural
    facet overlap, then summary-token similarity (semantic proposal).
    Ties break by ``pattern_id``. Candidates with no match at any tier are
    excluded; when nothing survives, the result is an explicit abstain.
    ``recorded_at`` is injected by the caller — this function has no clock.
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an int")
    if not 1 <= limit <= 5:
        raise ValueError("limit must be in [1, 5] (plan task 10: at most 3-5)")
    findings = scan_for_restricted(signature_summary, "query.signature_summary")
    if facets is not None:
        facet_findings: list[str] = []
        _scan_facets(facets, "query.facets", facet_findings)
        findings = findings + tuple(facet_findings)
    if findings:
        raise ValueError("restricted content refused: " + "; ".join(findings))

    index = (
        patterns
        if isinstance(patterns, PatternIndex)
        else build_pattern_index(patterns)
    )
    query_tokens = _token_set(signature_summary)

    scored: list[tuple[int, float, str, dict[str, Any]]] = []
    by_id = {data["pattern_id"]: data for data in index.records}
    for tip in index.tips:
        data = by_id[tip]
        if data["status"] not in _RETRIEVABLE_STATUSES:
            continue
        signature = data["problem_signature"]
        if signature["signature_sha256"] == signature_sha256:
            scored.append((0, 1.0, tip, data))
            continue
        shared = (
            _shared_facet_pairs(facets, signature.get("facets") or {})
            if facets is not None
            else 0
        )
        if shared > 0:
            scored.append((1, float(shared), tip, data))
            continue
        similarity = _jaccard(
            query_tokens, _token_set(signature["summary"])
        )
        if similarity > 0:
            scored.append((2, similarity, tip, data))
    scored.sort(key=lambda item: (item[0], -item[1], item[2]))

    candidates: list[PatternCandidate] = []
    for tier, score, tip, data in scored[:limit]:
        if tier == 0:
            differences = ("no signature difference: exact fingerprint match",)
        elif tier == 1:
            differences = (
                f"signature fingerprint differs; {int(score)} shared facet pair(s)",
            )
        else:
            differences = (
                "signature fingerprint differs; no shared facet pairs; "
                f"summary token overlap {score:.6f}",
                "semantic proposal only — similarity never merges, executes, "
                "or promotes",
            )
        candidates.append(
            PatternCandidate(
                pattern_id=tip,
                sha256=canonical_sha256(data),
                status=data["status"],
                match_tier=_TIER_NAMES[tier],
                score=score,
                applicability={
                    "scope": data["scope"],
                    "preconditions": list(data["preconditions"]),
                },
                contraindications=tuple(data["contraindications"]),
                evidence=dict(data["evidence"]),
                source_cases=tuple(dict(pin) for pin in data["source_cases"]),
                last_validated=data["last_validated"],
                differences=differences,
            )
        )

    session_entry: dict[str, Any] = {
        "query": {
            "summary": signature_summary,
            "signature_sha256": signature_sha256,
        },
        "candidates": [
            {"pattern_id": candidate.pattern_id, "sha256": candidate.sha256}
            for candidate in candidates
        ],
        "abstained": not candidates,
        "recorded_at": recorded_at,
    }
    if facets is not None:
        session_entry["query"]["facets"] = dict(facets)
    return RetrievalResult(
        abstained=not candidates,
        candidates=tuple(candidates),
        session_entry=session_entry,
        session_sha256=canonical_sha256(session_entry),
    )
