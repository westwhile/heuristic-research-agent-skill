"""Cross-record reference and lineage checks over a reconciled record set.

Pure logic, no I/O: the store layer hands in ``family -> id -> Record`` and
this module returns violations plus informational forks. Fail-closed checks:

- ``duplicate_id``: the same logical id exists in two or more families —
  logical ids must be globally unique (within one family, the same id in
  multiple files is the integrity violation ``duplicate_record``);
- ``dangling_reference``: a reference names an id that exists in no family;
- ``cross_type_reference``: the id exists, but in a different family than the
  reference requires (for example a claim's ``supporting_evidence`` naming a
  task id);
- ``self_reference``: a claim supersedes itself;
- ``pin_mismatch``: a claim pins an evidence record's SHA-256 that does not
  match the stored record;
- ``one_way_link``: a claim lists an evidence record (or an evidence record
  lists a claim) without the reverse link;
- ``lineage_cycle``: ``supersedes`` edges among claims form a cycle.

Forks (two or more claims superseding the same prior claim) are **not**
violations; they are reported as information. The core deliberately offers
no "latest version" selection semantics.
"""

from __future__ import annotations

from typing import Any

from .records import Record

_CLAIM = "research-claim/v1"
_EVIDENCE = "research-evidence/v1"


class GraphViolation:
    """One fail-closed finding from store reconciliation or graph checks."""

    __slots__ = ("kind", "detail")

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "detail": self.detail}

    def __repr__(self) -> str:
        return f"GraphViolation(kind={self.kind!r}, detail={self.detail!r})"


def _classify_reference(
    records: dict[str, dict[str, Record]],
    id_owners: dict[str, str],
    expected_family: str,
    target: str,
    context: str,
) -> GraphViolation | None:
    if target in records.get(expected_family, {}):
        return None
    owner = id_owners.get(target)
    if owner is not None:
        return GraphViolation(
            "cross_type_reference",
            f"{context} references {target!r}, which is a {owner} id, "
            f"not a {expected_family} id",
        )
    return GraphViolation(
        "dangling_reference",
        f"{context} references {target!r}, which does not exist in the store",
    )


def _find_lineage_cycles(edges: dict[str, str]) -> list[list[str]]:
    """Find every cycle in a functional graph (each node has at most one
    outgoing ``supersedes`` edge; every target is itself a node).

    Cycles in a functional graph are pairwise disjoint, so each is reported
    exactly once. Iteration starts in sorted order and each walk demotes its
    path when done, making the output deterministic.
    """
    state: dict[str, int] = {}  # absent = unvisited; 1 = on current path; 2 = done
    cycles: list[list[str]] = []
    for start in sorted(edges):
        if start in state:
            continue
        path: list[str] = []
        node: str | None = start
        while node is not None and node not in state:
            state[node] = 1
            path.append(node)
            node = edges.get(node)
        if node is not None and state.get(node) == 1:
            cycles.append(path[path.index(node):] + [node])
        for item in path:
            state[item] = 2
    return cycles


def check_record_graph(
    records: dict[str, dict[str, Record]],
) -> tuple[list[GraphViolation], list[tuple[str, tuple[str, ...]]]]:
    """Run every graph check. Returns ``(violations, forks)``."""
    violations: list[GraphViolation] = []
    claims = records.get(_CLAIM, {})
    evidences = records.get(_EVIDENCE, {})

    id_owners: dict[str, str] = {}
    id_families: dict[str, set[str]] = {}
    for family, by_id in records.items():
        for rid in by_id:
            id_owners.setdefault(rid, family)
            id_families.setdefault(rid, set()).add(family)

    # Logical ids must be globally unique: the same id in two or more
    # families is an identity collision — never a legitimate state (unlike
    # forks, which carry meaning and stay informational). One violation per
    # colliding id, sorted for determinism.
    for rid in sorted(id_families):
        families = sorted(id_families[rid])
        if len(families) > 1:
            violations.append(
                GraphViolation(
                    "duplicate_id",
                    f"record id {rid!r} exists in multiple families: "
                    + ", ".join(families)
                    + "; logical ids must be globally unique (the same id "
                    "in multiple files within one family is the integrity "
                    "violation duplicate_record)",
                )
            )

    supersedes_edges: dict[str, str] = {}
    children: dict[str, list[str]] = {}

    for cid in sorted(claims):
        data: dict[str, Any] = claims[cid].data
        target = data.get("supersedes")
        if target is not None:
            if target == cid:
                violations.append(
                    GraphViolation(
                        "self_reference",
                        f"claim {cid!r} supersedes itself",
                    )
                )
            else:
                problem = _classify_reference(
                    records, id_owners, _CLAIM, target, f"claim {cid!r} supersedes"
                )
                if problem is not None:
                    violations.append(problem)
                else:
                    supersedes_edges[cid] = target
                    children.setdefault(target, []).append(cid)
        for ref in data["supporting_evidence"]:
            eid = ref["evidence_id"]
            problem = _classify_reference(
                records,
                id_owners,
                _EVIDENCE,
                eid,
                f"claim {cid!r} supporting_evidence",
            )
            if problem is not None:
                violations.append(problem)
                continue
            pin = ref.get("sha256")
            if pin is not None and pin != evidences[eid].sha256:
                violations.append(
                    GraphViolation(
                        "pin_mismatch",
                        f"claim {cid!r} pins evidence {eid!r} at {pin} but "
                        f"the stored record hashes to {evidences[eid].sha256}",
                    )
                )

    for eid in sorted(evidences):
        for cid in evidences[eid].data["claim_ids"]:
            problem = _classify_reference(
                records, id_owners, _CLAIM, cid, f"evidence {eid!r} claim_ids"
            )
            if problem is not None:
                violations.append(problem)

    # "Which evidence ids does each claim list" is computed once and shared
    # by both one-way directions, keeping them symmetric by construction.
    listed_by_claim = {
        cid: {ref["evidence_id"] for ref in claims[cid].data["supporting_evidence"]}
        for cid in claims
    }
    for cid in sorted(claims):
        for eid in sorted(listed_by_claim[cid]):
            if eid in evidences and cid not in evidences[eid].data["claim_ids"]:
                violations.append(
                    GraphViolation(
                        "one_way_link",
                        f"claim {cid!r} lists evidence {eid!r} but the "
                        f"evidence record does not list the claim back",
                    )
                )
    for eid in sorted(evidences):
        for cid in evidences[eid].data["claim_ids"]:
            if cid in claims and eid not in listed_by_claim[cid]:
                violations.append(
                    GraphViolation(
                        "one_way_link",
                        f"evidence {eid!r} lists claim {cid!r} but the "
                        f"claim does not list the evidence back",
                    )
                )

    for cycle in _find_lineage_cycles(supersedes_edges):
        violations.append(
            GraphViolation("lineage_cycle", "supersedes cycle: " + " -> ".join(cycle))
        )

    forks = sorted(
        (parent, tuple(sorted(kids)))
        for parent, kids in children.items()
        if len(kids) > 1
    )
    return violations, forks
