"""Append-only record store: on-disk layout, atomic writes, and the manifest.

Layout under an explicit caller-provided root::

    <root>/
        manifest.json     derived index; canonical bytes; replaced atomically
        records/
            research-task/v1/<sha256>.json
            research-claim/v1/<sha256>.json
            research-evidence/v1/<sha256>.json
        .tmp/             transient write staging; outside the verified surface

Records are content-addressed: the file name is the record's canonical
SHA-256, never its logical id. Schema ids allow any non-whitespace string
(including ``/``, device names, or case-only variants), so using ids as file
names would import path-traversal and filesystem-alias hazards into the
store.

Append-only rules (fail closed):

- a record file is created exactly once: a fully written, fsynced temporary
  file is committed with a same-volume hard link that never overwrites;
- every publish first reconciles the existing store inside the root lock —
  any integrity finding aborts the write with :class:`StoreIntegrityError`
  before a single byte is written (one narrow exception: an ``extra_record``
  finding for the very record being published, i.e. the crash-window orphan
  whose stored bytes match, which is adopted without a rewrite);
- republishing the same logical id with the same hash is an exact no-op
  (``already_present``) and touches no bytes on disk;
- republishing the same logical id with a different hash raises
  :class:`PublicationError` — a revision is a new id plus ``supersedes``;
- symbolic links, junctions, and other reparse points are rejected
  everywhere on the store surface — including the caller-provided root
  itself and every existing lexical ancestor component of it, which is the
  containment boundary and is never followed — as well as
  ``manifest.json``, ``records/``, ``.tmp/``, and every node inside the
  records tree; relative roots are first absolutized lexically against a
  single entry cwd snapshot (:func:`absolutize_lexical`: string joining
  only, never a resolve, never a re-read of the cwd), so a cwd that itself
  sits under a junction is rejected too; detection is
  lstat-based and consults ``FILE_ATTRIBUTE_REPARSE_POINT`` on Windows, so
  every reparse tag (not only symlinks and junctions) is rejected; a stat
  failure other than nonexistence makes a node *undeterminable* and fails
  closed (``store_unreadable`` in verification, :class:`StoreIntegrityError`
  in publish) — "cannot tell" is never treated as "safe"; the on-disk walk
  never follows them, so the store neither writes nor attests bytes outside
  the caller-provided root;
- the manifest is a *derived* index: verification rebuilds it from the
  records on disk and byte-compares, so any added, removed, altered, or
  non-canonically rewritten entry fails closed.

Crash consistency: the records namespace only ever changes via the atomic
link, and the manifest via atomic replace, so an interrupted publish never
leaves a visible half-record or half-manifest. A crash between the record
link and the manifest replace leaves one complete but unregistered record
file (verification reports ``extra_record``); republishing that very record
adopts the byte-identical orphan without a rewrite. A crash during the very
first publish leaves ``records/`` without a manifest (``manifest_missing``)
and publishing refuses to write until the residue is cleaned up manually.
Orphaned ``.tmp/`` staging files are invisible to verification.
Concurrency is serialized per store root for in-process callers;
cross-process publishing is out of scope for this batch. The public
operations capture one immutable cwd snapshot at entry and pin both the
store root and the schema root lexically against that same snapshot; the
preflight, the lock key, the reconciliation, and all I/O use the pinned
paths and never consult the process cwd again, so an in-process cwd change
mid-call can split neither the checked object from the written or verified
one nor the two pinned paths from each other. Guards are check-then-act
under that process-local lock; an external process racing the filesystem
between the check and the write is out of scope.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import threading
from pathlib import Path, PurePosixPath
from typing import Any

from ._canonical import canonical_bytes
from ._errors import (
    CoreError,
    PublicationError,
    StoreIntegrityError,
    StrictJsonError,
)
from ._paths import validate_safe_relative_path
from ._strict_json import load_strict_json
from .records import Record, load_record

RECORDS_DIR = "records"
MANIFEST_NAME = "manifest.json"
TMP_DIR = ".tmp"
MANIFEST_KIND = "core-manifest/v1"

# Windows file-attribute bit marking any reparse point (symlink, junction,
# or any other tag). ``stat.FILE_ATTRIBUTE_REPARSE_POINT`` exists on Windows
# builds; the literal fallback keeps the check total elsewhere.
_FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

# Logical identity field per publishable schema family. Families outside this
# table are rejected at publish time; the table is kernel-private v1 knowledge,
# not caller configuration.
_ID_FIELDS = {
    "research-task/v1": "task_id",
    "research-claim/v1": "claim_id",
    "research-evidence/v1": "evidence_id",
}

_ENTRY_KEYS = frozenset({"family", "id", "sha256", "path"})
_SHA256_TEXT = re.compile(r"^[0-9a-f]{64}$")
_RECORD_FILE_NAME = re.compile(r"^[0-9a-f]{64}\.json$")

# Lock entries are intentionally never removed: lock identity stability is
# the serialization guarantee — an eviction scheme would have to prove, at
# removal time, that no thread can still acquire the old lock object, which
# is the classic hard-to-get-right window. The residency is bounded and
# negligible (a path string plus one lock per distinct lexical root; real
# callers use a handful of repository roots, and test processes with many
# temporary roots are short-lived). Introduce a hold-counted entry scheme
# only if a long-lived service ever publishes to an unbounded set of
# distinct roots. Same accepted-boundary class: the key is purely lexical
# (normcase), so two lexically different spellings of one physical root
# (8.3 aliases, SUBST drives) still map to two locks.
_ROOT_LOCKS: dict[str, threading.Lock] = {}
_ROOT_LOCKS_GUARD = threading.Lock()


def cwd_snapshot() -> str:
    """The process cwd, captured once for lexical path pinning.

    Public entry points take this snapshot a single time and derive every
    path they use from it, so a concurrent ``os.chdir`` mid-call cannot
    re-target the store or the schema registry. A missing or unreadable
    cwd makes relative roots undeterminable and fails closed.
    """
    try:
        return os.getcwd()
    except OSError as exc:
        raise StoreIntegrityError(
            f"cannot determine the process cwd: {exc}; relative store or "
            f"schema roots are undeterminable"
        ) from exc


def absolutize_lexical(path: Path | str, cwd: str) -> Path:
    """Absolutize *path* lexically against the immutable *cwd* snapshot.

    Pure string work: this never resolves the path and never re-reads the
    process cwd, so the result cannot drift mid-call. Windows
    drive-relative forms (``C:foo``) cannot be pinned against a single cwd
    snapshot — each drive carries its own cwd — and fail closed;
    root-relative forms take the snapshot's drive; absolute and UNC forms
    pass through with lexical normalization only.
    """
    text = os.fspath(path)
    if os.name == "nt":
        text = text.replace("/", "\\")
        drive, rest = os.path.splitdrive(text)
        if drive:
            if rest.startswith("\\") or (drive.startswith("\\\\") and not rest):
                # Drive-absolute, UNC, or a bare UNC share root.
                absolute = drive + rest
            else:
                raise StoreIntegrityError(
                    f"drive-relative path {text!r} cannot be pinned against a "
                    f"single cwd snapshot; use a drive-absolute path"
                )
        elif text.startswith("\\"):
            cwd_drive, _ = os.path.splitdrive(cwd)
            if not cwd_drive:
                raise StoreIntegrityError(
                    f"root-relative path {text!r} cannot be pinned against "
                    f"cwd snapshot {cwd!r}; use a drive-absolute path"
                )
            absolute = cwd_drive + text
        else:
            absolute = cwd + "\\" + text
    else:
        absolute = text if text.startswith("/") else cwd + "/" + text
    return Path(os.path.normpath(absolute))


def lock_for_root(root: Path) -> threading.Lock:
    """Process-local lock serializing all writes to one store root.

    The key is purely lexical (``normcase`` of the caller-pinned path): it
    never resolves, never re-reads the process cwd, and never touches the
    filesystem, so taking the lock cannot follow a reparse point or leak an
    I/O error. Callers must pass the lexical absolute root pinned at the
    public entry (:func:`absolutize_lexical`) and run the containment
    preflight (:func:`_find_reparse_component`) before locking.
    """
    key = os.path.normcase(str(root))
    with _ROOT_LOCKS_GUARD:
        lock = _ROOT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _ROOT_LOCKS[key] = lock
        return lock


def _stat_is_reparse(info: os.stat_result) -> bool:
    """True when an lstat result describes a symlink or any reparse point.

    On Windows this consults ``FILE_ATTRIBUTE_REPARSE_POINT``, so junctions
    and every other reparse tag — not only symlinks — are covered. The stat
    never follows links.
    """
    if stat.S_ISLNK(info.st_mode):
        return True
    attrs = getattr(info, "st_file_attributes", 0)  # Windows only
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def _is_reparse(point: Path) -> bool:
    """True for any symlink or reparse point at *point*, broken or not.

    Only :class:`FileNotFoundError` means "definitely absent" (False). Any
    other stat failure makes the node *undeterminable*, which fails closed:
    :class:`StoreIntegrityError` is raised rather than treating the node as
    safe.
    """
    try:
        info = os.lstat(str(point))
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StoreIntegrityError(
            f"cannot stat {str(point)!r}: {exc}; an undeterminable node is "
            f"never treated as safe"
        ) from exc
    return _stat_is_reparse(info)


def _find_reparse_component(path: Path) -> Path | None:
    """Return the first existing lexical component of *path* that is a
    symlink, junction, or other reparse point — or ``None``.

    *path* must be the lexical absolute path pinned at the public entry
    (:func:`absolutize_lexical`); this function performs no absolutizing of
    its own and never consults the process cwd, so the components checked
    here are exactly the ones the later I/O will use — including a cwd that
    itself sits under a junction, which the pinned path already contains.
    The walk checks every existing component from the anchor down to the
    final node, following nothing. It stops at the first nonexistent
    component (deeper components cannot exist either). A stat failure other
    than nonexistence fails closed with :class:`StoreIntegrityError`.
    """
    parts = path.parts
    if not parts:
        return None
    if path.anchor:
        node = Path(path.anchor)
        rest = parts[1:]
    else:  # pragma: no cover - a pinned absolute path always has an anchor
        node = Path(".")
        rest = parts
    for part in rest:
        node = node / part
        try:
            info = os.lstat(str(node))
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StoreIntegrityError(
                f"cannot stat store root component {str(node)!r}: {exc}; an "
                f"undeterminable node is never treated as safe"
            ) from exc
        if _stat_is_reparse(info):
            return node
    return None


def _node_state(point: Path) -> tuple[str, OSError | None]:
    """Classify a reserved store node with a single lstat, never following.

    States: ``reparse`` / ``dir`` / ``file`` / ``other`` / ``absent`` /
    ``unreadable`` — the last means the stat failed for a reason other than
    nonexistence, so the node might be anything and is never treated as
    safe; the OSError is returned alongside for diagnostics.
    """
    try:
        info = os.lstat(str(point))
    except FileNotFoundError:
        return "absent", None
    except OSError as exc:
        return "unreadable", exc
    if _stat_is_reparse(info):
        return "reparse", None
    if stat.S_ISDIR(info.st_mode):
        return "dir", None
    if stat.S_ISREG(info.st_mode):
        return "file", None
    return "other", None


def _check_no_reparse_components(root: Path, rel: str) -> None:
    """Fail closed if any existing parent component of ``root/rel`` is a
    symlink, junction, or other reparse point."""
    node = root
    for part in PurePosixPath(rel).parts[:-1]:
        node = node / part
        if _is_reparse(node):
            raise StoreIntegrityError(
                f"store path component {str(node)!r} is a symlink or "
                f"junction; refusing to write through it"
            )


def _scan_record_files(
    root: Path, problems: list[tuple[str, str]]
) -> list[tuple[Path, str]]:
    """Iteratively collect regular files under ``root/records``.

    Symlinks, junctions, and other reparse points are reported as
    violations and never followed; nodes that are neither regular files nor
    directories are foreign objects. The result is sorted by relative POSIX
    path for deterministic reporting.
    """
    found: list[tuple[Path, str]] = []
    stack = [root / RECORDS_DIR]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                children = sorted(it, key=lambda entry: entry.name)
        except OSError as exc:
            problems.append(
                ("store_unreadable", f"{str(current)!r}: cannot list: {exc}")
            )
            continue
        for entry in children:
            point = Path(entry.path)
            rel = point.relative_to(root).as_posix()
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                problems.append(
                    ("store_unreadable", f"{rel}: cannot stat: {exc}")
                )
                continue
            if _stat_is_reparse(info):
                problems.append(("reparse_point", rel))
            elif stat.S_ISDIR(info.st_mode):
                stack.append(point)
            elif stat.S_ISREG(info.st_mode):
                found.append((point, rel))
            else:
                problems.append(
                    ("foreign_object", f"{rel} (unsupported node type)")
                )
    found.sort(key=lambda item: item[1])
    return found


def identity_of(record: Record) -> str:
    """The record's logical id, per its family's identity field."""
    field = _ID_FIELDS.get(record.schema_id)
    if field is None:
        known = ", ".join(sorted(_ID_FIELDS))
        raise PublicationError(
            f"schema {record.schema_id!r} has no known identity field; "
            f"publishable families: {known}"
        )
    value = record.data.get(field)
    if not isinstance(value, str):  # unreachable for validated records
        raise PublicationError(
            f"identity field {field!r} of {record.schema_id!r} is not a string"
        )
    return value


def record_relpath(schema_id: str, sha256: str) -> str:
    """POSIX path of a record file relative to the store root."""
    return validate_safe_relative_path(f"{RECORDS_DIR}/{schema_id}/{sha256}.json")


def entry_for_record(record: Record) -> dict[str, str]:
    """The manifest entry describing one stored record."""
    return {
        "family": record.schema_id,
        "id": identity_of(record),
        "sha256": record.sha256,
        "path": record_relpath(record.schema_id, record.sha256),
    }


def manifest_object(entries: list[dict[str, str]]) -> dict[str, Any]:
    """Deterministic manifest document: entries sorted by (family, id)."""
    ordered = sorted(entries, key=lambda e: (e["family"], e["id"]))
    return {
        "manifest": MANIFEST_KIND,
        "records": [
            {
                "family": entry["family"],
                "id": entry["id"],
                "sha256": entry["sha256"],
                "path": entry["path"],
            }
            for entry in ordered
        ],
    }


def manifest_bytes(entries: list[dict[str, str]]) -> bytes:
    return canonical_bytes(manifest_object(entries))


def _entry_or_problem(item: Any, index: int, problems: list[str]) -> dict[str, str] | None:
    where = f"records[{index}]"
    if not isinstance(item, dict):
        problems.append(f"{where} is not an object")
        return None
    keys = set(item)
    if keys != _ENTRY_KEYS:
        problems.append(
            f"{where} must have exactly the keys family/id/sha256/path, "
            f"got {sorted(keys)}"
        )
        return None
    entry = {key: item[key] for key in _ENTRY_KEYS}
    for key, value in entry.items():
        if not isinstance(value, str):
            problems.append(f"{where}.{key} must be a string")
    if any(not isinstance(v, str) for v in entry.values()):
        return None
    if not _SHA256_TEXT.fullmatch(entry["sha256"]):
        problems.append(f"{where}.sha256 is not 64 lowercase hex digits")
        return None
    try:
        expected = record_relpath(entry["family"], entry["sha256"])
    except CoreError as exc:
        problems.append(f"{where}.family/sha256 do not form a safe path: {exc}")
        return None
    if entry["path"] != expected:
        problems.append(
            f"{where}.path {entry['path']!r} does not match the path derived "
            f"from family and sha256 ({expected!r})"
        )
        return None
    return {"family": entry["family"], "id": entry["id"],
            "sha256": entry["sha256"], "path": entry["path"]}


def parse_manifest(raw: bytes) -> list[dict[str, str]]:
    """Strictly parse and structurally validate manifest bytes.

    Raises :class:`StoreIntegrityError` on any malformation, including
    duplicate ``(family, id)`` entries or duplicate paths.
    """
    try:
        obj = load_strict_json(raw)
    except StrictJsonError as exc:
        raise StoreIntegrityError(f"manifest is not strict JSON: {exc}") from exc
    problems: list[str] = []
    extra_keys = sorted(set(obj) - {"manifest", "records"})
    if extra_keys:
        problems.append(f"unexpected manifest key(s): {', '.join(extra_keys)}")
    if obj.get("manifest") != MANIFEST_KIND:
        problems.append(f'"manifest" must be {MANIFEST_KIND!r}')
    entries: list[dict[str, str]] = []
    items = obj.get("records")
    if not isinstance(items, list):
        problems.append('"records" must be an array')
    else:
        seen_keys: set[tuple[str, str]] = set()
        seen_paths: set[str] = set()
        for index, item in enumerate(items):
            entry = _entry_or_problem(item, index, problems)
            if entry is None:
                continue
            key = (entry["family"], entry["id"])
            if key in seen_keys:
                problems.append(
                    f"duplicate entry for {entry['family']} id {entry['id']!r}"
                )
            seen_keys.add(key)
            if entry["path"] in seen_paths:
                problems.append(f"duplicate path {entry['path']!r}")
            seen_paths.add(entry["path"])
            entries.append(entry)
    if problems:
        raise StoreIntegrityError("manifest is malformed: " + "; ".join(problems))
    return entries


def _cleanup_staged(path: Path) -> None:
    """Best-effort removal of a staged temporary file.

    Cleanup must never leak a bare OS error nor mask the wrapped primary
    error: a leftover in ``.tmp/`` is invisible to verification (the
    crash-consistency contract), so a failing unlink (for example a
    transient antivirus lock on Windows) is swallowed and the primary
    error keeps propagating.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_filled_temp(root: Path, data: bytes, prefix: str) -> Path:
    tmp_dir = root / TMP_DIR
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StoreIntegrityError(
            f"cannot create staging directory {str(tmp_dir)!r}: {exc}"
        ) from exc
    if _is_reparse(tmp_dir):
        raise StoreIntegrityError(
            f"{TMP_DIR}/ is a symlink or junction; refusing to stage writes"
        )
    try:
        fd, name = tempfile.mkstemp(dir=tmp_dir, prefix=prefix, suffix=".tmp")
    except OSError as exc:
        raise StoreIntegrityError(
            f"cannot stage a temporary file in {str(tmp_dir)!r}: {exc}"
        ) from exc
    try:
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise StoreIntegrityError(
                f"cannot write staged bytes into {str(name)!r}: {exc}"
            ) from exc
    except BaseException:
        _cleanup_staged(Path(name))
        raise
    return Path(name)


def create_record_file(root: Path, record: Record) -> None:
    """Commit the record's canonical bytes into the store, never overwriting.

    A same-name file with identical bytes (the same content already linked by
    an earlier id, or this record's own crash-window orphan) is adopted
    without a write; different bytes — or any reparse point — under a
    content-derived name mean on-disk corruption and fail closed.
    """
    data = record.canonical_bytes
    rel = record_relpath(record.schema_id, record.sha256)
    _check_no_reparse_components(root, rel)
    final = root / Path(rel)
    try:
        final.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StoreIntegrityError(
            f"cannot create store directory {str(final.parent)!r}: {exc}"
        ) from exc
    tmp = _write_filled_temp(root, data, ".rc-")
    try:
        try:
            os.link(tmp, final)
        except FileExistsError:
            if _is_reparse(final):
                raise StoreIntegrityError(
                    f"record file {rel!r} is a symlink or junction; the store "
                    f"is corrupt"
                )
            try:
                same_bytes = final.read_bytes() == data
            except OSError as exc:
                raise StoreIntegrityError(
                    f"record file {rel!r} exists but cannot be read: {exc}"
                ) from exc
            if same_bytes:
                return
            raise StoreIntegrityError(
                f"record file {rel!r} exists with bytes that do not match its "
                f"content-derived name; the store is corrupt"
            )
        except OSError as exc:
            raise StoreIntegrityError(
                f"cannot link record file {rel!r} into the store: {exc}"
            ) from exc
    finally:
        _cleanup_staged(tmp)


def replace_manifest(root: Path, data: bytes) -> None:
    target = root / MANIFEST_NAME
    if _is_reparse(target):
        raise StoreIntegrityError(
            f"{MANIFEST_NAME} is a symlink or junction; refusing to replace it"
        )
    tmp = _write_filled_temp(root, data, ".mf-")
    try:
        try:
            os.replace(tmp, target)
        except OSError as exc:
            raise StoreIntegrityError(
                f"cannot replace {MANIFEST_NAME}: {exc}"
            ) from exc
    finally:
        _cleanup_staged(tmp)


def _load_disk_record(
    path: Path, rel: str, problems: list[tuple[str, str]], schema_root: Any
) -> Record | None:
    parts = PurePosixPath(rel).parts
    if len(parts) != 4 or parts[0] != RECORDS_DIR:
        problems.append(("foreign_object", rel))
        return None
    name = parts[3]
    if not _RECORD_FILE_NAME.fullmatch(name):
        problems.append(
            ("foreign_object", f"{rel} (file name is not <sha256>.json)")
        )
        return None
    family = f"{parts[1]}/{parts[2]}"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        problems.append(("store_unreadable", f"{rel}: cannot read: {exc}"))
        return None
    try:
        record = load_record(raw, schema_root=schema_root)
    except CoreError as exc:
        problems.append(("record_invalid", f"{rel}: {exc}"))
        return None
    if record.schema_id != family:
        problems.append(
            (
                "record_identity_mismatch",
                f"{rel}: directory family is {family!r} but the record "
                f"declares {record.schema_id!r}",
            )
        )
        return None
    if record.sha256 != name[: -len(".json")]:
        problems.append(
            (
                "record_identity_mismatch",
                f"{rel}: file name does not match the content hash "
                f"{record.sha256}",
            )
        )
        return None
    if raw != record.canonical_bytes:
        problems.append(
            (
                "record_not_canonical",
                f"{rel}: stored bytes differ from the canonical form",
            )
        )
        return None
    return record


def reconcile_store(
    root: Path, *, schema_root: Any = None
) -> tuple[
    list[tuple[str, str]],
    dict[str, dict[str, Record]],
    str | None,
    list[dict[str, str]] | None,
]:
    """Reconcile the manifest against the disk and load clean records.

    Returns ``(problems, records, manifest_sha256, entries)`` where
    *problems* is a deterministic list of ``(kind, detail)`` integrity
    findings, *records* maps ``family -> id -> Record`` for cleanly
    identified records only, and *entries* is the parsed manifest entry list
    (``None`` when no usable manifest exists). Corruption is reported,
    never raised. The store root is first absolutized lexically (never
    resolved) and every existing component must be reparse-free and
    stat-able; a reparse component is ``reparse_point``, an undeterminable
    one ``store_unreadable``. Reserved nodes (``manifest.json``,
    ``records/``, ``.tmp/``) must be regular files/directories free of
    reparse points; anything else is a violation, and the records walk
    never follows links.
    """
    problems: list[tuple[str, str]] = []
    records: dict[str, dict[str, Record]] = {}
    try:
        offender = _find_reparse_component(root)
    except StoreIntegrityError as exc:
        # The root path itself could not be classified — never treat an
        # undeterminable boundary as safe.
        problems.append(("store_unreadable", str(exc)))
        return problems, records, None, None
    if offender is not None:
        # The caller-provided lexical root — including every existing
        # ancestor component — is the containment boundary; a reparse point
        # anywhere on it would silently relocate every store byte.
        problems.append(
            (
                "reparse_point",
                f"store root path component is a symlink, junction, or other "
                f"reparse point: {str(offender)!r}",
            )
        )
        return problems, records, None, None
    if not root.is_dir():
        problems.append(
            ("store_root_missing", f"store root is not a directory: {str(root)!r}")
        )
        return problems, records, None, None
    manifest_path = root / MANIFEST_NAME
    records_dir = root / RECORDS_DIR
    tmp_dir = root / TMP_DIR
    entries: list[dict[str, str]] | None = None
    manifest_raw: bytes | None = None
    manifest_sha256: str | None = None

    manifest_state, manifest_err = _node_state(manifest_path)
    if manifest_state == "reparse":
        problems.append(("reparse_point", MANIFEST_NAME))
    elif manifest_state == "file":
        try:
            manifest_raw = manifest_path.read_bytes()
        except OSError as exc:
            problems.append(
                ("store_unreadable", f"{MANIFEST_NAME}: cannot read: {exc}")
            )
        else:
            manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
            try:
                entries = parse_manifest(manifest_raw)
            except StoreIntegrityError as exc:
                problems.append(("manifest_malformed", str(exc)))
    elif manifest_state == "unreadable":
        problems.append(
            ("store_unreadable", f"{MANIFEST_NAME}: cannot stat: {manifest_err}")
        )
    elif manifest_state != "absent":
        problems.append(
            (
                "unexpected_node_type",
                f"{MANIFEST_NAME} exists but is not a regular file",
            )
        )

    records_state, records_err = _node_state(records_dir)
    if records_state == "reparse":
        problems.append(("reparse_point", RECORDS_DIR))
    elif records_state == "unreadable":
        problems.append(
            ("store_unreadable", f"{RECORDS_DIR}/: cannot stat: {records_err}")
        )
    elif records_state not in ("dir", "absent"):
        problems.append(
            ("unexpected_node_type", f"{RECORDS_DIR}/ exists but is not a directory")
        )

    tmp_state, tmp_err = _node_state(tmp_dir)
    if tmp_state == "reparse":
        problems.append(("reparse_point", TMP_DIR))
    elif tmp_state == "unreadable":
        problems.append(
            ("store_unreadable", f"{TMP_DIR}/: cannot stat: {tmp_err}")
        )
    elif tmp_state not in ("dir", "absent"):
        problems.append(
            ("unexpected_node_type", f"{TMP_DIR}/ exists but is not a directory")
        )

    if manifest_state == "absent" and records_state == "dir":
        problems.append(
            ("manifest_missing", "records/ exists but manifest.json is absent")
        )

    disk: dict[str, Record] = {}
    seen_ids: dict[tuple[str, str], str] = {}
    if records_state == "dir":
        for path, rel in _scan_record_files(root, problems):
            record = _load_disk_record(path, rel, problems, schema_root)
            if record is None:
                continue
            try:
                rid = identity_of(record)
            except PublicationError as exc:
                problems.append(("record_invalid", f"{rel}: {exc}"))
                continue
            key = (record.schema_id, rid)
            if key in seen_ids:
                problems.append(
                    (
                        "duplicate_record",
                        f"{rel}: id {rid!r} is also stored at {seen_ids[key]}",
                    )
                )
                continue
            seen_ids[key] = rel
            records.setdefault(record.schema_id, {})[rid] = record
            disk[rel] = record

    if entries is not None:
        entry_paths = {entry["path"] for entry in entries}
        for entry in entries:
            record = disk.get(entry["path"])
            if record is None:
                if not (root / Path(entry["path"])).is_file():
                    problems.append(
                        (
                            "missing_record",
                            f"{entry['path']} ({entry['family']} id "
                            f"{entry['id']!r})",
                        )
                    )
                continue
            rid = identity_of(record)
            if record.schema_id != entry["family"] or rid != entry["id"]:
                problems.append(
                    (
                        "record_identity_mismatch",
                        f"{entry['path']}: manifest says {entry['family']} id "
                        f"{entry['id']!r} but the record is "
                        f"{record.schema_id} id {rid!r}",
                    )
                )
        for rel in disk:
            if rel not in entry_paths:
                problems.append(("extra_record", rel))
        # Determinism is checked independently of other findings: an
        # allowed finding (e.g. a publishable crash-window orphan) must
        # never mask a tampered or non-canonically encoded manifest.
        if manifest_bytes(entries) != manifest_raw:
            problems.append(
                (
                    "manifest_not_deterministic",
                    "stored manifest differs from the deterministic rebuild of "
                    "the record set",
                )
            )
    return problems, records, manifest_sha256, entries
