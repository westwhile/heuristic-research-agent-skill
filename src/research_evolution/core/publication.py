"""Public facade for append-only publication and full-graph verification.

``publish_record`` is the only way records enter a store; it enforces the
create-new/append-only identity contract. ``verify_record_graph``
reconciles the manifest against the disk byte-for-byte and then runs every
cross-record check, reporting each finding as a violation instead of
raising. Storage mechanics live in :mod:`._store`, graph logic in
:mod:`._graph`; callers only see the two operations and their receipts.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ._errors import PublicationError, StoreIntegrityError
from ._graph import GraphViolation, check_record_graph
from ._restricted import scan_value_for_restricted
from ._store import (
    _find_reparse_component,
    absolutize_lexical,
    create_record_file,
    cwd_snapshot,
    entry_for_record,
    identity_of,
    lock_for_root,
    manifest_bytes,
    reconcile_store,
    record_relpath,
    replace_manifest,
)
from .records import load_record


class PublicationReceipt:
    """Attestation of one :func:`publish_record` call.

    Binds the record identity, its content hash, its store-relative path,
    whether the call created bytes (``already_present=False``) or was an
    exact replay, and the hash of the manifest after the call.
    """

    __slots__ = (
        "_schema_id",
        "_record_id",
        "_sha256",
        "_path",
        "_already_present",
        "_manifest_sha256",
    )

    def __init__(
        self,
        *,
        schema_id: str,
        record_id: str,
        sha256: str,
        path: str,
        already_present: bool,
        manifest_sha256: str,
    ) -> None:
        self._schema_id = schema_id
        self._record_id = record_id
        self._sha256 = sha256
        self._path = path
        self._already_present = already_present
        self._manifest_sha256 = manifest_sha256

    @property
    def schema_id(self) -> str:
        return self._schema_id

    @property
    def record_id(self) -> str:
        return self._record_id

    @property
    def sha256(self) -> str:
        return self._sha256

    @property
    def path(self) -> str:
        return self._path

    @property
    def already_present(self) -> bool:
        return self._already_present

    @property
    def manifest_sha256(self) -> str:
        return self._manifest_sha256

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self._schema_id,
            "id": self._record_id,
            "sha256": self._sha256,
            "path": self._path,
            "already_present": self._already_present,
            "manifest_sha256": self._manifest_sha256,
        }

    def __repr__(self) -> str:
        return (
            f"PublicationReceipt(schema_id={self._schema_id!r}, "
            f"record_id={self._record_id!r}, "
            f"already_present={self._already_present})"
        )


class GraphVerificationReport:
    """Outcome of :func:`verify_record_graph`.

    ``ok`` is true only when there are zero violations; every integrity or
    graph finding is a fail-closed :class:`GraphViolation`. Forks are
    informational and never affect ``ok``.
    """

    __slots__ = ("_violations", "_records_total", "_families", "_forks", "_manifest_sha256")

    def __init__(
        self,
        *,
        violations: list[GraphViolation],
        records_total: int,
        families: dict[str, int],
        forks: list[tuple[str, tuple[str, ...]]],
        manifest_sha256: str | None,
    ) -> None:
        self._violations = tuple(violations)
        self._records_total = records_total
        self._families = dict(families)
        self._forks = tuple(forks)
        self._manifest_sha256 = manifest_sha256

    @property
    def ok(self) -> bool:
        return not self._violations

    @property
    def violations(self) -> tuple[GraphViolation, ...]:
        return self._violations

    @property
    def records_total(self) -> int:
        return self._records_total

    @property
    def families(self) -> dict[str, int]:
        return dict(self._families)

    @property
    def forks(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return self._forks

    @property
    def manifest_sha256(self) -> str | None:
        return self._manifest_sha256

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "records_total": self._records_total,
            "families": dict(self._families),
            "violations": [violation.to_dict() for violation in self._violations],
            "forks": [
                {"superseded": parent, "children": list(children)}
                for parent, children in self._forks
            ],
            "manifest_sha256": self._manifest_sha256,
        }

    def __repr__(self) -> str:
        return (
            f"GraphVerificationReport(ok={self.ok}, "
            f"records_total={self._records_total}, "
            f"violations={len(self._violations)})"
        )


def publish_record(
    source: str | bytes | bytearray,
    *,
    root: Path | str,
    schema_root: Path | str | None = None,
) -> PublicationReceipt:
    """Validate *source* and append it to the store under *root*.

    Append-only contract (all failures raise :class:`CoreError` subclasses):

    - before anything is written, the existing store is fully reconciled
      inside the root lock; any integrity finding (corrupt, tampered, or
      half-written state) raises :class:`StoreIntegrityError`. The single
      narrow exception is an ``extra_record`` finding for the very record
      being published — its own crash-window orphan — whose bytes match and
      which is adopted without a rewrite, and only when it is the sole
      finding of the full reconciliation;
    - a new record is created atomically; existing bytes are never
      overwritten;
    - the same logical id with the same hash is an exact no-op returning
      ``already_present=True`` (a byte-identical replay changes nothing on
      disk, including the manifest);
    - the same logical id with a different hash raises
      :class:`PublicationError` — a revision must use a new id and point
      ``supersedes`` at the prior record;
    - symlinks, junctions, and any other reparse points anywhere on the
      store surface — starting with every existing lexical component of
      *root* itself — are rejected, so publishing can never write outside
      the caller-provided root. Both *root* and a non-``None``
      *schema_root* are pinned to their lexical absolute forms as the
      **first** step — before ``load_record`` or any other
      callback-capable work — and both pins derive from **one** immutable
      cwd snapshot captured once at entry (pure lexical joining, never a
      resolve; Windows drive-relative forms fail closed). The preflight,
      the lock key, the reconciliation, and every write all use the pinned
      paths, and nothing downstream consults the process cwd again. An
      in-process cwd change mid-call can therefore split neither the
      checked object from the written one nor the schema registry from the
      one the caller named.
    """
    # Pin first, before any validation or callback-capable work: one
    # immutable cwd snapshot drives both lexical absolutizations, and
    # nothing downstream consults the process cwd again.
    cwd = cwd_snapshot()
    root_path = absolutize_lexical(root, cwd)
    schema_root_path = (
        None if schema_root is None else absolutize_lexical(schema_root, cwd)
    )
    record = load_record(source, schema_root=schema_root_path)
    if record.schema_id in {
        "candidate-manifest/v1",
        "context-bundle/v1",
        "skill-candidate-bundle/v1",
        "skill-static-validation-receipt/v1",
        "skill-semantic-review-attestation/v1",
        "collaboration-window-plan/v1",
        "collaboration-ticket/v1",
        "collaboration-worker-outcome/v1",
    }:
        restricted = scan_value_for_restricted(record.data)
        if restricted:
            raise PublicationError(
                f"{record.schema_id} contains restricted content: "
                + "; ".join(restricted)
            )
    record_id = identity_of(record)
    rel = record_relpath(record.schema_id, record.sha256)
    # Containment preflight, before any lock/write: every existing lexical
    # component of the pinned root must be reparse-free and stat-able. An
    # undeterminable component raises StoreIntegrityError from the check
    # itself.
    offender = _find_reparse_component(root_path)
    if offender is not None:
        raise StoreIntegrityError(
            f"store root path component {str(offender)!r} is a symlink, "
            f"junction, or other reparse point; the caller-provided root is "
            f"the containment boundary and is never followed"
        )
    with lock_for_root(root_path):
        if root_path.exists() and not root_path.is_dir():
            raise StoreIntegrityError(
                f"store root exists but is not a directory: {str(root_path)!r}"
            )
        if root_path.is_dir():
            problems, _records, manifest_hash, entries = reconcile_store(
                root_path, schema_root=schema_root_path
            )
            # The single tolerated finding is the crash-window orphan of the
            # very record being published — expressed as strict equality of
            # the whole findings list, so no other finding (for example a
            # tampered or non-canonical manifest) can hide behind it.
            if problems and problems != [("extra_record", rel)]:
                summary = "; ".join(
                    f"{kind} ({detail})" for kind, detail in problems
                )
                raise StoreIntegrityError(
                    f"store is not clean; refusing to publish: {summary}"
                )
            if manifest_hash is None:
                raise StoreIntegrityError(
                    "store reconciliation did not return a manifest hash"
                )
            entries = entries if entries is not None else []
        else:
            entries, manifest_hash = [], None
        index = {(entry["family"], entry["id"]): entry for entry in entries}
        existing = index.get((record.schema_id, record_id))
        if existing is not None:
            if manifest_hash is None:
                raise StoreIntegrityError(
                    "an existing record requires a reconciled manifest hash"
                )
            if existing["sha256"] != record.sha256:
                raise PublicationError(
                    f"{record.schema_id} id {record_id!r} is already published "
                    f"with different content (hash {existing['sha256']} != "
                    f"{record.sha256}); published bytes are append-only — "
                    "issue a new id and point `supersedes` at the prior record"
                )
            return PublicationReceipt(
                schema_id=record.schema_id,
                record_id=record_id,
                sha256=record.sha256,
                path=rel,
                already_present=True,
                manifest_sha256=manifest_hash,
            )
        create_record_file(root_path, record)
        data = manifest_bytes(entries + [entry_for_record(record)])
        replace_manifest(root_path, data)
        return PublicationReceipt(
            schema_id=record.schema_id,
            record_id=record_id,
            sha256=record.sha256,
            path=rel,
            already_present=False,
            manifest_sha256=hashlib.sha256(data).hexdigest(),
        )


def _untrusted_root_report(kind: str, detail: str) -> GraphVerificationReport:
    """Report for a root whose containment could not be trusted at all."""
    return GraphVerificationReport(
        violations=[GraphViolation(kind, detail)],
        records_total=0,
        families={},
        forks=[],
        manifest_sha256=None,
    )


def verify_record_graph(
    root: Path | str,
    *,
    schema_root: Path | str | None = None,
) -> GraphVerificationReport:
    """Verify store integrity and every cross-record invariant under *root*.

    Integrity phase: the manifest must parse, be byte-identical to the
    deterministic rebuild of the record set, and reconcile exactly with the
    files on disk (no missing, extra, duplicate, or non-canonical records;
    no foreign objects, reparse points, or unexpected node types; reserved
    nodes must exist with their expected types). Graph phase: dangling
    references, cross-type references, self-references, pin mismatches
    (mandatory pins on the hierarchical run/observation/analysis references
    and on every case member reference, optional pins on claim/evidence),
    one-way claim/evidence links, supersedes lineage cycles, analysis
    lineage-scope mismatches, duplicate references inside one record's
    reference array, and incomplete case membership closure are all
    violations. Forks are reported as information only.

    Never raises for corruption; a corrupt store yields ``ok=False`` with
    the findings enumerated in ``violations``. Both *root* and a
    non-``None`` *schema_root* are pinned to their lexical absolute forms
    at entry — before anything else — and both pins derive from **one**
    immutable cwd snapshot captured once (pure lexical joining, never a
    resolve; Windows drive-relative or otherwise unpinnable forms degrade
    to a ``store_unreadable`` violation). The containment preflight on the
    pinned root runs before any locking and is purely lexical: it never
    resolves the path, so a hostile or broken root yields a violation, not
    an I/O exception. Nothing downstream consults the process cwd again, so
    a mid-call cwd change can split neither the checked object from the
    verified one nor the schema registry from the one the caller named.
    """
    # Pin first, before any callback-capable work or locking: one immutable
    # cwd snapshot drives both lexical absolutizations, and nothing
    # downstream consults the process cwd again. A root that cannot even be
    # pinned or statted is untrusted: report without resolving or locking.
    try:
        cwd = cwd_snapshot()
        root_path = absolutize_lexical(root, cwd)
        schema_root_path = (
            None if schema_root is None else absolutize_lexical(schema_root, cwd)
        )
        offender = _find_reparse_component(root_path)
    except StoreIntegrityError as exc:
        return _untrusted_root_report("store_unreadable", str(exc))
    if offender is not None:
        return _untrusted_root_report(
            "reparse_point",
            f"store root path component is a symlink, junction, or other "
            f"reparse point: {str(offender)!r}",
        )
    with lock_for_root(root_path):
        integrity, records, manifest_sha256, _entries = reconcile_store(
            root_path, schema_root=schema_root_path
        )
    violations = [GraphViolation(kind, detail) for kind, detail in integrity]
    graph_violations, forks = check_record_graph(records)
    violations.extend(graph_violations)
    families = {family: len(by_id) for family, by_id in sorted(records.items())}
    return GraphVerificationReport(
        violations=violations,
        records_total=sum(families.values()),
        families=families,
        forks=forks,
        manifest_sha256=manifest_sha256,
    )
