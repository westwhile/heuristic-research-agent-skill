"""Immutable candidate closure and budgeted context transfer.

The module is deliberately in-process and side-effect free: callers provide
validated manifest data and exact member bytes, and receive immutable records.
It does not read files, install artifacts, activate candidates, or publish
anything.  Byte closure and context preservation are narrower claims than
semantic review.
"""

from __future__ import annotations

import hashlib
import heapq
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from research_evolution.core import (
    CoreError,
    Record,
    canonical_bytes,
    canonical_sha256,
    load_record,
)

_CANDIDATE_SCHEMA = "candidate-manifest/v1"
_CLOSURE_SCHEMA = "artifact-closure-receipt/v1"
_CONTEXT_SCHEMA = "context-bundle/v1"
_REQUIRED_MEMBER_ROLES = frozenset({"baseline", "patch", "tests"})
_RETENTION_BY_MODE = {
    "normal": frozenset({"minimal_safe", "compact", "normal_only"}),
    "compact": frozenset({"minimal_safe", "compact"}),
    "minimal_safe": frozenset({"minimal_safe"}),
}
_LIMITATIONS = (
    "Byte closure does not establish semantic review or artifact quality.",
    "Context transfer does not authorize installation, activation, or publication.",
    "Source lifecycle declarations remain subject to independent verification.",
)


class CandidateManifestError(ValueError):
    """A candidate manifest is structurally or semantically unsafe."""


class ArtifactClosureError(CandidateManifestError):
    """Exact candidate-member closure could not be established."""


class ContextBundleError(CandidateManifestError):
    """A safe context bundle could not be represented within its budget."""


def _load_candidate(source: Record | Mapping[str, Any] | str | bytes | bytearray) -> Record:
    try:
        record = source if isinstance(source, Record) else load_record(
            canonical_bytes(dict(source)) if isinstance(source, Mapping) else source
        )
    except (CoreError, TypeError, ValueError) as exc:
        raise CandidateManifestError(f"invalid {_CANDIDATE_SCHEMA}: {exc}") from exc
    if record.schema_id != _CANDIDATE_SCHEMA:
        raise CandidateManifestError(
            f"expected {_CANDIDATE_SCHEMA}, got {record.schema_id!r}"
        )
    return record


def _unique_rows(rows: list[dict[str, Any]], field: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row[field]
        if key in result:
            raise CandidateManifestError(f"duplicate {label} {key!r}")
        result[key] = row
    return result


def _validate_candidate_semantics(record: Record) -> dict[str, Any]:
    payload = record.data
    if payload["principals"]["author"] == payload["principals"]["reviewer"]:
        raise CandidateManifestError(
            "author and reviewer principals must be distinct"
        )

    cases = _unique_rows(payload["source_cases"], "case_id", "source case")
    patterns = _unique_rows(
        payload["source_patterns"], "pattern_id", "source pattern"
    )
    overlapping_sources = set(cases) & set(patterns)
    if overlapping_sources:
        raise CandidateManifestError(
            f"source identities must be globally unique: {sorted(overlapping_sources)!r}"
        )
    expected_sources = {
        **{key: value["sha256"] for key, value in cases.items()},
        **{key: value["sha256"] for key, value in patterns.items()},
    }
    lifecycle = _unique_rows(
        payload["context"]["source_lifecycle"], "source_id", "source lifecycle"
    )
    actual_sources = {key: value["sha256"] for key, value in lifecycle.items()}
    if actual_sources != expected_sources:
        raise CandidateManifestError(
            "source lifecycle must exactly pin every declared source and no others"
        )

    members = _unique_rows(payload["members"], "name", "member")
    roles = {row["role"] for row in members.values()}
    missing_roles = _REQUIRED_MEMBER_ROLES - roles
    if missing_roles:
        raise CandidateManifestError(
            f"candidate members are missing required roles: {sorted(missing_roles)!r}"
        )
    baseline_rows = [row for row in members.values() if row["role"] == "baseline"]
    patch_rows = [row for row in members.values() if row["role"] == "patch"]
    if len(baseline_rows) != 1 or len(patch_rows) != 1:
        raise CandidateManifestError(
            "candidate must declare exactly one baseline and one patch member"
        )
    if baseline_rows[0]["sha256"] != payload["baseline_sha256"]:
        raise CandidateManifestError("baseline member does not match baseline_sha256")
    if patch_rows[0]["sha256"] != payload["patch_sha256"]:
        raise CandidateManifestError("patch member does not match patch_sha256")
    for name, row in members.items():
        if row["size_bytes"] < 0:
            raise CandidateManifestError(f"member {name!r} has a negative size")
        if len(set(row["depends_on"])) != len(row["depends_on"]):
            raise CandidateManifestError(f"member {name!r} repeats a dependency")
        if name in row["depends_on"]:
            raise CandidateManifestError(f"member {name!r} depends on itself")
        missing = set(row["depends_on"]) - set(members)
        if missing:
            raise CandidateManifestError(
                f"member {name!r} has unknown dependencies: {sorted(missing)!r}"
            )
        leaf = name.rsplit("/", 1)[-1].lower()
        if leaf in {"artifact-closure-receipt.json", "closure-receipt.json"}:
            raise CandidateManifestError(
                "closure receipt is reserved and must be generated last"
            )

    exclusions = _unique_rows(payload["exclusions"], "name", "exclusion")
    overlap = set(exclusions) & set(members)
    if overlap:
        raise CandidateManifestError(
            f"members and exclusions overlap: {sorted(overlap)!r}"
        )

    materials = _unique_rows(
        payload["context"]["materials"], "name", "context material"
    )
    if not any(row["retention"] == "minimal_safe" for row in materials.values()):
        raise CandidateManifestError(
            "at least one minimal_safe context material is required"
        )
    for name, row in materials.items():
        actual = hashlib.sha256(row["content"].encode("utf-8")).hexdigest()
        if actual != row["content_sha256"]:
            raise CandidateManifestError(
                f"context material {name!r} does not match content_sha256"
            )
    return payload


def _topological_order(members: dict[str, dict[str, Any]]) -> list[str]:
    indegree = {name: len(row["depends_on"]) for name, row in members.items()}
    children = {name: [] for name in members}
    for name, row in members.items():
        for dependency in row["depends_on"]:
            children[dependency].append(name)
    ready = [name for name, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        name = heapq.heappop(ready)
        order.append(name)
        for child in sorted(children[name]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    if len(order) != len(members):
        raise CandidateManifestError("member dependency graph contains a cycle")
    return order


def _closure_root(payload: dict[str, Any]) -> str:
    return canonical_sha256(
        {
            "candidate": payload["candidate"],
            "members": payload["members"],
            "topological_order": payload["topological_order"],
            "exclusions": payload["exclusions"],
        }
    )


def _closure_receipt_id(payload: dict[str, Any]) -> str:
    return "closure-" + canonical_sha256(
        {
            "candidate": payload["candidate"],
            "closed_at": payload["closed_at"],
            "closure_root_sha256": payload["closure_root_sha256"],
        }
    )[:16]


@dataclass(frozen=True)
class ArtifactClosureReceipt:
    """Immutable proof that all manifest-declared member bytes were closed."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _CLOSURE_SCHEMA:
            raise ArtifactClosureError(
                f"expected {_CLOSURE_SCHEMA}, got {self._record.schema_id!r}"
            )
        payload = self._record.data
        if payload["closure_root_sha256"] != _closure_root(payload):
            raise ArtifactClosureError("closure_root_sha256 does not bind receipt members")
        if payload["closure_receipt_id"] != _closure_receipt_id(payload):
            raise ArtifactClosureError(
                "closure_receipt_id does not bind the closed receipt"
            )
        names = [row["name"] for row in payload["members"]]
        if len(set(names)) != len(names) or set(names) != set(payload["topological_order"]):
            raise ArtifactClosureError(
                "topological_order must contain every member exactly once"
            )
        members = {row["name"]: row for row in payload["members"]}
        try:
            expected_order = _topological_order(members)
        except CandidateManifestError as exc:
            raise ArtifactClosureError(str(exc)) from exc
        if payload["topological_order"] != expected_order:
            raise ArtifactClosureError(
                "topological_order is not the deterministic dependency order"
            )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ArtifactClosureReceipt:
        try:
            return cls(load_record(canonical_bytes(dict(payload))))
        except ArtifactClosureError:
            raise
        except CoreError as exc:
            raise ArtifactClosureError(f"invalid {_CLOSURE_SCHEMA}: {exc}") from exc

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def sha256(self) -> str:
        return self._record.sha256


def close_candidate_bundle(
    manifest: Record | Mapping[str, Any] | str | bytes | bytearray,
    member_bytes: Mapping[str, bytes],
    *,
    closed_at: str,
) -> ArtifactClosureReceipt:
    """Verify an exact member set and return a receipt generated last.

    The function performs no I/O. Every source lifecycle declaration must be
    current, member names and dependency edges must be unique, all hashes and
    sizes must match, and the dependency graph must be acyclic.
    """

    record = _load_candidate(manifest)
    try:
        payload = _validate_candidate_semantics(record)
    except CandidateManifestError as exc:
        raise ArtifactClosureError(str(exc)) from exc
    blocked = [
        row
        for row in payload["context"]["source_lifecycle"]
        if row["status"] != "current"
    ]
    if blocked:
        details = [f"{row['source_id']}={row['status']}" for row in blocked]
        raise ArtifactClosureError(
            f"candidate has invalidated sources: {', '.join(sorted(details))}"
        )
    declared = {row["name"]: row for row in payload["members"]}
    supplied_names = set(member_bytes)
    if supplied_names != set(declared):
        missing = sorted(set(declared) - supplied_names)
        extra = sorted(supplied_names - set(declared))
        raise ArtifactClosureError(
            f"member set mismatch; missing={missing!r}, extra={extra!r}"
        )
    for name, content in member_bytes.items():
        if not isinstance(name, str) or not isinstance(content, bytes):
            raise ArtifactClosureError("member_bytes must map string names to exact bytes")
        expected = declared[name]
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != expected["sha256"] or len(content) != expected["size_bytes"]:
            raise ArtifactClosureError(f"member {name!r} hash or size mismatch")

    members = {name: declared[name] for name in sorted(declared)}
    try:
        order = _topological_order(members)
    except CandidateManifestError as exc:
        raise ArtifactClosureError(str(exc)) from exc
    core = {
        "schema": _CLOSURE_SCHEMA,
        "candidate": {
            "candidate_id": payload["candidate_id"],
            "sha256": record.sha256,
        },
        "closed_at": closed_at,
        "members": [members[name] for name in sorted(members)],
        "topological_order": order,
        "exclusions": sorted(payload["exclusions"], key=lambda row: row["name"]),
        "receipt_last": True,
        "byte_closed": True,
        "semantic_review_completed": False,
    }
    core["closure_root_sha256"] = _closure_root(core)
    core["closure_receipt_id"] = _closure_receipt_id(core)
    return ArtifactClosureReceipt.from_payload(core)


def _context_bundle_id(payload: dict[str, Any]) -> str:
    core = {key: value for key, value in payload.items() if key != "context_bundle_id"}
    return "context-" + canonical_sha256(core)[:16]


@dataclass(frozen=True)
class ContextBundle:
    """Immutable, hash-bound context that stays within its declared budget."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _CONTEXT_SCHEMA:
            raise ContextBundleError(
                f"expected {_CONTEXT_SCHEMA}, got {self._record.schema_id!r}"
            )
        payload = self._record.data
        if payload["max_bytes"] <= 0:
            raise ContextBundleError("max_bytes must be positive")
        if payload["context_bundle_id"] != _context_bundle_id(payload):
            raise ContextBundleError("context_bundle_id does not bind the bundle")
        if len(self._record.canonical_bytes) > payload["max_bytes"]:
            raise ContextBundleError("context bundle exceeds max_bytes")
        names: set[str] = set()
        for row in payload["included_materials"]:
            if row["name"] in names:
                raise ContextBundleError("context material names must be unique")
            names.add(row["name"])
            actual = hashlib.sha256(row["content"].encode("utf-8")).hexdigest()
            if actual != row["content_sha256"]:
                raise ContextBundleError(
                    f"included material {row['name']!r} does not match its hash"
                )
        omitted_names = [row["name"] for row in payload["omissions"]]
        if len(set(omitted_names)) != len(omitted_names) or names & set(omitted_names):
            raise ContextBundleError("included and omitted material names must partition cleanly")
        selected = _RETENTION_BY_MODE[payload["mode"]]
        if not any(
            row["retention"] == "minimal_safe"
            for row in payload["included_materials"]
        ):
            raise ContextBundleError("minimal-safe material was not preserved")
        if any(row["retention"] not in selected for row in payload["included_materials"]):
            raise ContextBundleError("included material violates the selected mode")
        if any(row["retention"] in selected for row in payload["omissions"]):
            raise ContextBundleError("selected-mode material appears in omissions")
        invalidated_ids = [row["source_id"] for row in payload["invalidated_sources"]]
        if len(set(invalidated_ids)) != len(invalidated_ids):
            raise ContextBundleError("invalidated source identities must be unique")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ContextBundle:
        try:
            return cls(load_record(canonical_bytes(dict(payload))))
        except ContextBundleError:
            raise
        except CoreError as exc:
            raise ContextBundleError(f"invalid {_CONTEXT_SCHEMA}: {exc}") from exc

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def sha256(self) -> str:
        return self._record.sha256


def build_context_bundle(
    manifest: Record | Mapping[str, Any] | str | bytes | bytearray,
    *,
    mode: str,
    max_bytes: int,
    built_at: str,
) -> ContextBundle:
    """Build one declared retention mode or fail instead of dropping context.

    Mode selection is exact: ``normal`` retains every material, ``compact``
    retains compact and minimal-safe material, and ``minimal_safe`` retains
    only minimal-safe material. Budget pressure never causes an undeclared
    downgrade; if the selected representation does not fit, construction
    fails closed.
    """

    if mode not in _RETENTION_BY_MODE:
        raise ContextBundleError(f"unsupported context mode {mode!r}")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ContextBundleError("max_bytes must be a positive integer")
    record = _load_candidate(manifest)
    try:
        payload = _validate_candidate_semantics(record)
    except CandidateManifestError as exc:
        raise ContextBundleError(str(exc)) from exc
    selected = _RETENTION_BY_MODE[mode]
    materials = sorted(payload["context"]["materials"], key=lambda row: row["name"])
    included = [row for row in materials if row["retention"] in selected]
    omitted = [
        {
            "name": row["name"],
            "content_sha256": row["content_sha256"],
            "retention": row["retention"],
            "reason": "excluded_by_mode",
        }
        for row in materials
        if row["retention"] not in selected
    ]
    invalidated = sorted(
        (
            row
            for row in payload["context"]["source_lifecycle"]
            if row["status"] != "current"
        ),
        key=lambda row: row["source_id"],
    )
    core = {
        "schema": _CONTEXT_SCHEMA,
        "candidate": {
            "candidate_id": payload["candidate_id"],
            "sha256": record.sha256,
        },
        "built_at": built_at,
        "mode": mode,
        "max_bytes": max_bytes,
        "objective": payload["objective"],
        "authoritative_head": payload["context"]["authoritative_head"],
        "unresolved_obligations": payload["context"]["unresolved_obligations"],
        "invalidated_sources": invalidated,
        "included_materials": included,
        "omissions": omitted,
        "minimum_safe_preserved": True,
        "claims": {
            "installation_authorized": False,
            "activation_authorized": False,
            "publication_authorized": False,
            "semantic_review_completed": False,
        },
        "limitations": list(_LIMITATIONS),
    }
    core["context_bundle_id"] = _context_bundle_id(core)
    try:
        return ContextBundle.from_payload(core)
    except ContextBundleError as exc:
        if "max_bytes" in str(exc) or "exceeds" in str(exc):
            raise ContextBundleError(
                f"selected {mode!r} context cannot fit max_bytes={max_bytes}"
            ) from exc
        raise
