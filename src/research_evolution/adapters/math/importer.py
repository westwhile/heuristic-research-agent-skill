"""Read-only importer for math-research-solve archives (ADR-0005 decision 9).

Minimal v1 projection over the ``math-research-project/v8`` head:

- ``project.json`` must declare schema exactly ``math-research-project/v8``
  (legacy heads are NOT imported as v8 — startup never upgrades identity by
  key presence, and neither do we);
- the documented top-level key set is required exactly; unknown keys fail
  closed;
- every hash pointer (``active_checkpoint``, ``goal_host_state``,
  ``project_event_head``, ``host_binding_head``, and a non-null
  ``legacy_successor``) is verified against the actual file bytes;
- ``active_contract.binding_sha256`` is verified over the contract bytes
  after CRLF-to-LF normalization (the archive's own binding rule);
- ``problem_statement_sha256`` is verified against ``state/problem.md``;
- ``active_run.path`` must be a safe-relative directory containing
  ``run.json``.

Zero-write evidence: :func:`import_archive` snapshots the whole tree before
and after the import and fails closed on any drift (the importer itself
never writes); callers can independently re-snapshot with
:func:`snapshot_tree`. Real legacy archive import remains a conditional
capability (reports/baseline/math-research-solve-1.0.1.md): acceptance
requires a real fixture, never synthetic files.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_evolution.core import CoreError, load_strict_json, validate_safe_relative_path

from ..types import AdapterError

_HEAD_SCHEMA = "math-research-project/v8"
_HEAD_KEYS = frozenset(
    {
        "schema",
        "project_id",
        "project_identity_sha256",
        "problem_statement_sha256",
        "control_generation",
        "active_checkpoint",
        "goal_host_state",
        "project_event_head",
        "host_binding_head",
        "active_contract",
        "active_run",
        "legacy_successor",
    }
)
_POINTER_KEYS = (
    "active_checkpoint",
    "goal_host_state",
    "project_event_head",
    "host_binding_head",
)
_POINTER_SUBKEYS = frozenset({"path", "sha256", "control_generation"})
_HEX64 = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class ArchiveArtifact:
    """One file of the imported archive: safe-relative path + content hash."""

    path: str
    sha256: str


@dataclass(frozen=True)
class MathArchiveImport:
    """Result of a verified read-only archive import."""

    project_id: str
    project_head_sha256: str
    artifacts: tuple[ArchiveArtifact, ...]
    tree_digest: str

    def evidence_inputs(self) -> list[dict[str, Any]]:
        """Artifact bindings ready for core evidence ``inputs`` entries."""
        return [
            {"name": artifact.path, "kind": "data", "sha256": artifact.sha256}
            for artifact in self.artifacts
        ]


def snapshot_tree(root: Path | str) -> dict[str, str]:
    """Hash every file under *root* (safe-relative posix path -> sha256)."""
    root_path = Path(root)
    snapshot: dict[str, str] = {}
    for path in sorted(root_path.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root_path).as_posix()
            snapshot[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX64


def _safe_target(root: Path, rel: Any, label: str) -> Path:
    if not isinstance(rel, str):
        raise AdapterError(f"{label}: path must be a string")
    try:
        validate_safe_relative_path(rel)
    except CoreError as exc:
        raise AdapterError(f"{label}: unsafe path {rel!r}: {exc}") from exc
    target = root / rel
    if not target.is_file():
        raise AdapterError(f"{label}: target file missing: {rel}")
    return target


def _verify_pointer(root: Path, head: dict[str, Any], key: str) -> None:
    pointer = head[key]
    if not isinstance(pointer, dict) or set(pointer) != _POINTER_SUBKEYS:
        raise AdapterError(
            f"{key} must be an object with exactly {sorted(_POINTER_SUBKEYS)}"
        )
    declared = pointer["sha256"]
    if not _is_hex64(declared):
        raise AdapterError(f"{key}: sha256 must be 64 lowercase hex")
    target = _safe_target(root, pointer["path"], key)
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != declared:
        raise AdapterError(
            f"{key}: hash mismatch for {pointer['path']} "
            f"(declared {declared[:12]}..., actual {actual[:12]}...)"
        )


def _verify_head(root: Path, head: dict[str, Any]) -> None:
    keys = set(head)
    if keys != _HEAD_KEYS:
        raise AdapterError(
            f"project.json top-level keys must be exactly {sorted(_HEAD_KEYS)}; "
            f"missing: {sorted(_HEAD_KEYS - keys)}, unknown: {sorted(keys - _HEAD_KEYS)}"
        )
    if not isinstance(head["project_id"], str) or not head["project_id"].strip():
        raise AdapterError("project_id must be a non-empty string")
    if not _is_hex64(head["project_identity_sha256"]):
        raise AdapterError("project_identity_sha256 must be 64 lowercase hex")
    generation = head["control_generation"]
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise AdapterError("control_generation must be a positive integer")

    for key in _POINTER_KEYS:
        _verify_pointer(root, head, key)
    successor = head["legacy_successor"]
    if successor is not None:
        if not isinstance(successor, dict) or set(successor) != _POINTER_SUBKEYS:
            raise AdapterError(
                "legacy_successor must be null or an object with exactly "
                f"{sorted(_POINTER_SUBKEYS)}"
            )
        pointer = {"legacy_successor": successor}
        _verify_pointer(root, pointer, "legacy_successor")

    statement = _safe_target(root, "state/problem.md", "problem_statement_sha256")
    if not _is_hex64(head["problem_statement_sha256"]):
        raise AdapterError("problem_statement_sha256 must be 64 lowercase hex")
    actual = hashlib.sha256(statement.read_bytes()).hexdigest()
    if actual != head["problem_statement_sha256"]:
        raise AdapterError("problem_statement_sha256 does not match state/problem.md")

    contract = head["active_contract"]
    if not isinstance(contract, dict) or set(contract) != {"path", "version", "binding_sha256"}:
        raise AdapterError(
            "active_contract must have exactly ['binding_sha256', 'path', 'version']"
        )
    if contract["version"] != "v8":
        raise AdapterError(f"active_contract version must be 'v8', got {contract['version']!r}")
    contract_file = _safe_target(root, contract["path"], "active_contract")
    normalized = contract_file.read_bytes().replace(b"\r\n", b"\n")
    if not _is_hex64(contract["binding_sha256"]):
        raise AdapterError("active_contract.binding_sha256 must be 64 lowercase hex")
    if hashlib.sha256(normalized).hexdigest() != contract["binding_sha256"]:
        raise AdapterError("active_contract binding hash mismatch (CRLF-normalized)")

    run = head["active_run"]
    if not isinstance(run, dict) or set(run) != {"id", "path", "status"}:
        raise AdapterError("active_run must have exactly ['id', 'path', 'status']")
    if not isinstance(run["status"], str) or not run["status"].strip():
        raise AdapterError("active_run.status must be a non-empty string")
    try:
        validate_safe_relative_path(run["path"])
    except CoreError as exc:
        raise AdapterError(f"active_run: unsafe path {run['path']!r}: {exc}") from exc
    run_dir = root / run["path"]
    if not run_dir.is_dir() or not (run_dir / "run.json").is_file():
        raise AdapterError(f"active_run: {run['path']} must be a directory with run.json")


def import_archive(root: Path | str) -> MathArchiveImport:
    """Import one math-research-solve archive, read-only and hash-verified."""
    root_path = Path(root)
    if not root_path.is_dir():
        raise AdapterError(f"archive root is not a directory: {root_path}")
    head_path = root_path / "project.json"
    if not head_path.is_file():
        raise AdapterError(f"archive has no project.json: {root_path}")

    pre = snapshot_tree(root_path)
    try:
        head = load_strict_json(head_path.read_bytes())
    except CoreError as exc:
        raise AdapterError(f"project.json is not strict JSON: {exc}") from exc
    if head.get("schema") != _HEAD_SCHEMA:
        raise AdapterError(
            f"project.json schema must be exactly {_HEAD_SCHEMA!r}, "
            f"got {head.get('schema')!r}; legacy heads are not imported as v8"
        )
    _verify_head(root_path, head)

    post = snapshot_tree(root_path)
    if post != pre:
        raise AdapterError(
            "archive tree changed during import; the importer must be read-only"
        )

    artifacts = tuple(
        ArchiveArtifact(path=path, sha256=digest)
        for path, digest in sorted(pre.items())
    )
    tree_digest = hashlib.sha256(
        "".join(f"{path}  {digest}\n" for path, digest in sorted(pre.items())).encode(
            "utf-8"
        )
    ).hexdigest()
    return MathArchiveImport(
        project_id=head["project_id"],
        project_head_sha256=hashlib.sha256(head_path.read_bytes()).hexdigest(),
        artifacts=artifacts,
        tree_digest=tree_digest,
    )
