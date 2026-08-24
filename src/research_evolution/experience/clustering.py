"""Four-tier layered clustering and the registry-layer cluster event log.

ADR-0007 decision 4 (plan tasks 5/6): cases cluster by exact fingerprint
(``problem_signature.signature_sha256``), then structural facet fields,
then taxonomy path, then semantic proposal — in that order. Semantic
similarity only ever PROPOSES candidates; it never merges authoritatively
and never feeds any promotion decision (architecture section 4.3).

Clusters are a registry-layer derived index, not facts: the same inputs
always rebuild the same clusters (catalogs-rebuildable principle). Cluster
merge/split history lives in an append-only, hash-chained event log that
is deterministic and replayable; original cases and old indexes are never
overwritten.

The taxonomy-path tier reads the caller-side convention
``problem_signature.facets["taxonomy_path"]`` (a list of labels). The
kernel never interprets facets; this layer reads exactly one documented
key, and only when the caller passes a :class:`Taxonomy` to validate
against.
"""

import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..core import canonical_bytes, canonical_sha256, load_record

from .cases import _CASE_FAMILY
from .taxonomy import Taxonomy

TIERS = (
    "exact_fingerprint",
    "structural_fields",
    "taxonomy_path",
    "semantic_proposal",
    "singleton",
)

_CJK_RANGES = (
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0x20000, 0x2FA1F),  # Supplementary CJK ideographs
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0x31F0, 0x31FF),  # Katakana phonetic extensions
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x3130, 0x318F),  # Hangul compatibility Jamo
    (0xAC00, 0xD7AF),  # Hangul syllables
)


@dataclass(frozen=True)
class Cluster:
    """One deterministic cluster of pinned case members."""

    cluster_id: str
    tier: str
    members: tuple[dict[str, Any], ...]
    rationale: str


def _pin_case(payload: Mapping[str, Any], index: int) -> dict[str, Any]:
    try:
        record = load_record(canonical_bytes(payload))
    except Exception as exc:
        raise ValueError(f"cases[{index}] payload is not a valid core record: {exc}")
    if record.schema_id != _CASE_FAMILY:
        raise ValueError(
            f"cases[{index}] payload declares {record.schema_id!r}; "
            f"expected {_CASE_FAMILY!r}"
        )
    return record.data


def _cluster_id(tier: str, member_ids: tuple[str, ...]) -> str:
    digest = canonical_sha256({"tier": tier, "members": list(member_ids)})
    return f"{tier}-{digest[:12]}"


def _make_cluster(tier: str, members: list[dict[str, Any]], rationale: str) -> Cluster:
    pins = tuple(
        {"case_id": data["case_id"], "sha256": canonical_sha256(data)}
        for data in sorted(members, key=lambda item: item["case_id"])
    )
    member_ids = tuple(pin["case_id"] for pin in pins)
    return Cluster(
        cluster_id=_cluster_id(tier, member_ids),
        tier=tier,
        members=pins,
        rationale=rationale,
    )


def _is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return any(start <= codepoint <= end for start, end in _CJK_RANGES)


def _is_term_char(char: str) -> bool:
    return unicodedata.category(char)[0] in {"L", "M", "N"} or char == "_"


def _token_set(text: str) -> frozenset[str]:
    """Tokenize Unicode terms and CJK 2--4 character n-grams.

    NFKC plus case folding makes compatibility forms deterministic. Latin
    and other non-CJK letters/numbers remain whole terms; underscores,
    ticker dots, and a leading currency marker remain attached. CJK runs
    use tagged 2--4 character n-grams so word-boundary-free text can match
    without treating every all-CJK input as an empty set.
    """

    normalized = unicodedata.normalize("NFKC", text).casefold()
    tokens: set[str] = set()
    term: list[str] = []

    def flush_term() -> None:
        value = "".join(term).strip(".")
        if value.strip("$"):
            tokens.add(value)
        term.clear()

    index = 0
    while index < len(normalized):
        char = normalized[index]
        if _is_cjk(char):
            flush_term()
            end = index + 1
            while end < len(normalized) and _is_cjk(normalized[end]):
                end += 1
            run = normalized[index:end]
            for width in range(2, min(4, len(run)) + 1):
                for offset in range(len(run) - width + 1):
                    tokens.add(f"cjk{width}:{run[offset:offset + width]}")
            index = end
            continue
        if _is_term_char(char) or char in ".$":
            term.append(char)
        else:
            flush_term()
        index += 1
    flush_term()
    return frozenset(tokens)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def cluster_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    taxonomy: Taxonomy | None = None,
    semantic_threshold: float = 0.5,
) -> tuple[Cluster, ...]:
    """Cluster case payloads by the frozen four-tier ladder.

    Every case lands in exactly one cluster; a case that matches nothing
    is an explicit one-member ``singleton`` cluster, never silently
    dropped. Tiers are tried in order: exact fingerprint, structural
    facet equality, taxonomy path (only when *taxonomy* is given and the
    case's ``taxonomy_path`` facet validates against it), and finally
    single-linkage token-Jaccard semantic proposal. Semantic clusters are
    proposals — the rationale says so — and never a merge or promotion
    decision. The result is deterministic: identical inputs rebuild
    identical clusters.
    """
    if not isinstance(semantic_threshold, (int, float)) or isinstance(
        semantic_threshold, bool
    ):
        raise ValueError("semantic_threshold must be a number")
    if not 0.0 < float(semantic_threshold) <= 1.0:
        raise ValueError("semantic_threshold must be in (0, 1]")
    datas = [_pin_case(payload, index) for index, payload in enumerate(cases)]
    seen_ids: set[str] = set()
    for data in datas:
        if data["case_id"] in seen_ids:
            raise ValueError(f"duplicate case_id {data['case_id']!r} in input")
        seen_ids.add(data["case_id"])

    clusters: list[Cluster] = []

    def emit(tier: str, groups: dict[Any, list[dict[str, Any]]], rationale: str) -> list:
        remaining: list[dict[str, Any]] = []
        for key in sorted(groups, key=str):
            group = groups[key]
            if len(group) > 1:
                clusters.append(_make_cluster(tier, group, rationale))
            else:
                remaining.extend(group)
        return remaining

    # Tier 1: exact fingerprint.
    by_fingerprint: dict[str, list[dict[str, Any]]] = {}
    for data in datas:
        by_fingerprint.setdefault(
            data["problem_signature"]["signature_sha256"], []
        ).append(data)
    remaining = emit(
        "exact_fingerprint",
        by_fingerprint,
        "identical problem_signature.signature_sha256",
    )

    # Tier 2: structural facet equality. Empty facets carry no structural
    # information, so facetless cases never merge here.
    by_facets: dict[bytes | None, list[dict[str, Any]]] = {}
    for data in remaining:
        facets = data["problem_signature"].get("facets") or {}
        key = canonical_bytes(facets) if facets else None
        by_facets.setdefault(key, []).append(data)
    remaining = emit(
        "structural_fields",
        {k: v for k, v in by_facets.items() if k is not None},
        "identical problem_signature.facets",
    ) + by_facets.get(None, [])

    # Tier 3: taxonomy path, only with a taxonomy to validate against.
    if taxonomy is not None:
        if not isinstance(taxonomy, Taxonomy):
            raise ValueError("taxonomy must be a Taxonomy")
        by_path: dict[tuple[str, ...] | None, list[dict[str, Any]]] = {}
        for data in remaining:
            raw = (data["problem_signature"].get("facets") or {}).get(
                "taxonomy_path"
            )
            path = (
                tuple(raw)
                if isinstance(raw, Sequence)
                and not isinstance(raw, (str, bytes, bytearray))
                and raw
                else None
            )
            if path is not None and (
                not all(isinstance(label, str) for label in path)
                or path not in taxonomy.paths
            ):
                path = None
            by_path.setdefault(path, []).append(data)
        remaining = emit(
            "taxonomy_path",
            {k: v for k, v in by_path.items() if k is not None},
            "shared validated taxonomy_path facet",
        ) + by_path.get(None, [])

    # Tier 4: single-linkage semantic proposal over summary tokens.
    proposals: list[list[dict[str, Any]]] = []
    proposal_tokens: list[list[frozenset[str]]] = []  # per-cluster member sets
    still: list[dict[str, Any]] = []
    for data in sorted(remaining, key=lambda item: item["case_id"]):
        tokens = _token_set(data["problem_signature"]["summary"])
        placed = False
        for index, member_sets in enumerate(proposal_tokens):
            if any(
                _jaccard(tokens, member) >= float(semantic_threshold)
                for member in member_sets
            ):
                proposals[index].append(data)
                member_sets.append(tokens)
                placed = True
                break
        if not placed:
            proposals.append([data])
            proposal_tokens.append([tokens])
    for group in proposals:
        if len(group) > 1:
            clusters.append(
                _make_cluster(
                    "semantic_proposal",
                    group,
                    "summary token similarity "
                    f">= {float(semantic_threshold)}; proposal only — not a "
                    "merge or promotion decision",
                )
            )
        else:
            still.extend(group)

    # Explicit singletons: nothing matched.
    for data in still:
        clusters.append(
            _make_cluster(
                "singleton",
                [data],
                "no tier matched; the case stands alone",
            )
        )

    return tuple(
        sorted(clusters, key=lambda cluster: cluster.cluster_id)
    )


def append_cluster_event(
    log: Sequence[Mapping[str, Any]],
    *,
    kind: str,
    cluster_ids: Sequence[str],
    rationale: str,
    at: str,
) -> tuple[dict[str, Any], ...]:
    """Append one merge/split event to the registry-layer log.

    The log is hash-chained (each entry binds its predecessor's hash) and
    deterministic; ``at`` is injected by the caller — no clock here. The
    original log is never mutated: a new tuple is returned (task 6's
    append-only discipline).
    """
    if kind not in ("merge", "split"):
        raise ValueError(f"cluster event kind must be merge or split, got {kind!r}")
    if not cluster_ids or not all(
        isinstance(cluster_id, str) and cluster_id.strip() for cluster_id in cluster_ids
    ):
        raise ValueError("cluster event needs at least one non-blank cluster id")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("cluster event rationale must be a non-blank string")
    verify_cluster_log(log)
    prev = log[-1]["event_sha256"] if log else "0" * 64
    entry: dict[str, Any] = {
        "seq": len(log),
        "kind": kind,
        "cluster_ids": sorted(cluster_ids),
        "rationale": rationale,
        "at": at,
        "prev_sha256": prev,
    }
    entry["event_sha256"] = canonical_sha256(entry)
    return tuple(log) + (entry,)


def verify_cluster_log(log: Sequence[Mapping[str, Any]]) -> None:
    """Recompute the hash chain; any truncation, reorder, or edit fails."""
    prev = "0" * 64
    for index, entry in enumerate(log):
        if entry.get("seq") != index or entry.get("prev_sha256") != prev:
            raise ValueError(f"cluster log chain broken at seq {index}")
        body = {key: value for key, value in entry.items() if key != "event_sha256"}
        if canonical_sha256(body) != entry.get("event_sha256"):
            raise ValueError(f"cluster log entry {index} hash mismatch")
        prev = entry["event_sha256"]
