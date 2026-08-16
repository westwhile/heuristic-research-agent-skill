"""Cross-record reference and lineage checks over a reconciled record set.

Pure logic, no I/O: the store layer hands in ``family -> id -> Record`` and
this module returns violations plus informational forks. Every per-family
rule comes from the family contract registry in :mod:`._families`; this
module holds no family knowledge of its own. Fail-closed checks:

- ``duplicate_id``: the same logical id exists in two or more families —
  logical ids must be globally unique (within one family, the same id in
  multiple files is the integrity violation ``duplicate_record``);
- ``dangling_reference``: a reference names an id that exists in no family;
- ``cross_type_reference``: the id exists, but in a different family than
  the reference requires (for example a claim's ``supporting_evidence``
  naming a task id);
- ``self_reference``: a record supersedes itself;
- ``pin_mismatch``: a reference pins the target record's SHA-256 and the
  pin does not match the stored record (pins are mandatory on the
  hierarchical run/observation/analysis references, optional on
  claim/evidence; a present pin is always checked);
- ``one_way_link``: a claim lists an evidence record (or an evidence
  record lists a claim) without the reverse link — the only two-way pair;
  hierarchical references are one-directional and never raise it;
- ``lineage_cycle``: ``supersedes`` edges form a cycle;
- ``lineage_scope_mismatch``: a failure analysis supersedes an analysis
  anchored to a different observation.

Forks (two or more records superseding the same prior record) are **not**
violations; they are reported as information. The core deliberately offers
no "latest version" selection semantics.
"""

from __future__ import annotations

from typing import Any

from ._families import FAMILIES, ReferenceContract
from .records import Record


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


def _extract_references(
    data: dict[str, Any], contract: ReferenceContract
) -> list[tuple[str, str | None]]:
    """All ``(target_id, pin)`` pairs named by one reference field.

    Records reaching this point are schema-validated, so the field and its
    id keys are always present; pins are optional only where the registry
    says so.
    """
    if contract.shape == "object":
        ref = data[contract.field]
        return [(ref[contract.target_id_field], ref.get("sha256"))]
    if contract.shape == "array_of_objects":
        return [
            (ref[contract.target_id_field], ref.get("sha256"))
            for ref in data[contract.field]
        ]
    # array_of_scalars: the items themselves are the ids, never pinned.
    return [(item, None) for item in data[contract.field]]


def _reference_for_field(family: str, field: str) -> ReferenceContract:
    """The reference contract of *field* on *family* (registry-guaranteed)."""
    for contract in FAMILIES[family].references:
        if contract.field == field:
            return contract
    raise AssertionError(  # unreachable: registry pairs are symmetric
        f"no reference contract for {family} field {field!r}"
    )


def _anchor_id(
    records: dict[str, dict[str, Record]], family: str, rid: str, anchor_field: str
) -> str:
    """The lineage-scope anchor: the target id of the family's anchor field."""
    contract = _reference_for_field(family, anchor_field)
    return _extract_references(records[family][rid].data, contract)[0][0]


def check_record_graph(
    records: dict[str, dict[str, Record]],
) -> tuple[list[GraphViolation], list[tuple[str, tuple[str, ...]]]]:
    """Run every graph check. Returns ``(violations, forks)``."""
    violations: list[GraphViolation] = []

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

    # Reference and lineage checks, driven by the family contract registry.
    for family in sorted(records):
        contract = FAMILIES.get(family)
        if contract is None:
            continue  # unreachable: reconcile admits only registered families
        by_id = records[family]
        for rid in sorted(by_id):
            data: dict[str, Any] = by_id[rid].data
            if contract.supersedes is not None:
                target = data.get("supersedes")
                if target is not None:
                    if target == rid:
                        violations.append(
                            GraphViolation(
                                "self_reference",
                                f"{family} {rid!r} supersedes itself",
                            )
                        )
                    else:
                        problem = _classify_reference(
                            records, id_owners, family, target,
                            f"{family} {rid!r} supersedes",
                        )
                        if problem is not None:
                            violations.append(problem)
                        else:
                            supersedes_edges[rid] = target
                            children.setdefault(target, []).append(rid)
                            if contract.supersedes.scope == "anchor":
                                own_anchor = _anchor_id(
                                    records, family, rid,
                                    contract.supersedes.anchor_field,
                                )
                                target_anchor = _anchor_id(
                                    records, family, target,
                                    contract.supersedes.anchor_field,
                                )
                                if own_anchor != target_anchor:
                                    violations.append(
                                        GraphViolation(
                                            "lineage_scope_mismatch",
                                            f"{family} {rid!r} supersedes "
                                            f"{target!r} but their "
                                            f"{contract.supersedes.anchor_field} "
                                            f"anchors differ ({own_anchor!r} vs "
                                            f"{target_anchor!r})",
                                        )
                                    )
            for ref_contract in contract.references:
                for tid, pin in _extract_references(data, ref_contract):
                    problem = _classify_reference(
                        records,
                        id_owners,
                        ref_contract.target_family,
                        tid,
                        f"{family} {rid!r} {ref_contract.field}",
                    )
                    if problem is not None:
                        violations.append(problem)
                        continue
                    actual = records[ref_contract.target_family][tid].sha256
                    if pin is not None and pin != actual:
                        violations.append(
                            GraphViolation(
                                "pin_mismatch",
                                f"{family} {rid!r} {ref_contract.field} pins "
                                f"{tid!r} at {pin} but the stored record "
                                f"hashes to {actual}",
                            )
                        )

    # Two-way link pairs are checked once, from the lexicographically
    # smaller (family, field) side. "Which target ids does each record list"
    # is computed once per side, keeping both directions symmetric by
    # construction.
    for family in sorted(FAMILIES):
        for ref_contract in FAMILIES[family].references:
            if ref_contract.two_way_with is None:
                continue
            reverse_side = (ref_contract.target_family, ref_contract.two_way_with)
            if (family, ref_contract.field) > reverse_side:
                continue  # the pair is processed from the other side
            reverse_contract = _reference_for_field(*reverse_side)
            a_records = records.get(family, {})
            b_records = records.get(ref_contract.target_family, {})
            listed_by_a = {
                aid: {
                    tid
                    for tid, _pin in _extract_references(
                        a_records[aid].data, ref_contract
                    )
                }
                for aid in a_records
            }
            listed_by_b = {
                bid: {
                    aid
                    for aid, _pin in _extract_references(
                        b_records[bid].data, reverse_contract
                    )
                }
                for bid in b_records
            }
            for aid in sorted(a_records):
                for bid in sorted(listed_by_a[aid]):
                    if bid in b_records and aid not in listed_by_b[bid]:
                        violations.append(
                            GraphViolation(
                                "one_way_link",
                                f"{family} {aid!r} lists {bid!r} via "
                                f"{ref_contract.field} but "
                                f"{ref_contract.target_family} {bid!r} does "
                                f"not list it back via "
                                f"{ref_contract.two_way_with}",
                            )
                        )
            for bid in sorted(b_records):
                for aid in sorted(listed_by_b[bid]):
                    if aid in a_records and bid not in listed_by_a[aid]:
                        violations.append(
                            GraphViolation(
                                "one_way_link",
                                f"{ref_contract.target_family} {bid!r} lists "
                                f"{aid!r} via {ref_contract.two_way_with} "
                                f"but {family} {aid!r} does not list it "
                                f"back via {ref_contract.field}",
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
