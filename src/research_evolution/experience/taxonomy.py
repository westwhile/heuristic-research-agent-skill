"""Versioned taxonomy data: loading, content-hash pinning, composition.

ADR-0007 decision 4: taxonomy is versioned DATA, not code — a generic
level-1 taxonomy plus domain level-2 overlays, each pinned by content
hash into the registry. The data files live at the repository root under
``taxonomies/``; this module performs no I/O — the caller reads the files
and passes the parsed mapping in.

An overlay binds its parent by content hash (``parent_sha256``), so a
composed taxonomy is a hash-chained data stack: change any byte upstream
and every downstream pin breaks loudly.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from ..core import canonical_sha256


@dataclass(frozen=True)
class Taxonomy:
    """A validated, content-hash-pinned taxonomy (or composed stack)."""

    version: str
    sha256: str
    paths: frozenset[tuple[str, ...]]
    parent_sha256: str | None


def _walk(nodes: Mapping[str, Any], prefix: tuple[str, ...], out: set) -> None:
    for label, children in nodes.items():
        if not isinstance(label, str) or not label.strip():
            raise ValueError("taxonomy node labels must be non-blank strings")
        if not isinstance(children, Mapping):
            raise ValueError(f"taxonomy node {label!r} children must be a mapping")
        path = prefix + (label,)
        out.add(path)
        _walk(children, path, out)


def load_taxonomy(data: Mapping[str, Any]) -> Taxonomy:
    """Validate one taxonomy data mapping and return it hash-pinned.

    Shape: ``{"version": str, "nodes": {label: {child: ...}}}`` with an
    optional ``parent_sha256`` for overlays. Paths are the full label
    tuples from the root, e.g. ``("algorithm-design",)``.
    """
    if not isinstance(data, Mapping):
        raise ValueError("taxonomy data must be a mapping")
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("taxonomy version must be a non-blank string")
    nodes = data.get("nodes")
    if not isinstance(nodes, Mapping):
        raise ValueError("taxonomy nodes must be a mapping")
    parent = data.get("parent_sha256")
    if parent is not None and not (
        isinstance(parent, str) and len(parent) == 64
    ):
        raise ValueError("taxonomy parent_sha256 must be a 64-hex string or absent")
    paths: set[tuple[str, ...]] = set()
    _walk(nodes, (), paths)
    return Taxonomy(
        version=version,
        sha256=canonical_sha256(data),
        paths=frozenset(paths),
        parent_sha256=parent,
    )


def compose_taxonomy(general: Taxonomy, *overlays: Taxonomy) -> Taxonomy:
    """Compose a level-1 taxonomy with level-2 overlays, hash-chained.

    Each overlay's ``parent_sha256`` must equal the level-1 taxonomy's
    hash (a star, not a chain: overlays extend the same base
    independently), and every overlay path must attach below an existing
    path. The composed hash binds the exact stack:
    ``{general, overlays[]}``.
    """
    if not isinstance(general, Taxonomy):
        raise ValueError("general must be a Taxonomy")
    paths: set[tuple[str, ...]] = set(general.paths)
    overlay_shas: list[str] = []
    versions = [general.version]
    for overlay in overlays:
        if not isinstance(overlay, Taxonomy):
            raise ValueError("overlays must be Taxonomy instances")
        if overlay.parent_sha256 != general.sha256:
            raise ValueError(
                f"overlay {overlay.version!r} pins parent {overlay.parent_sha256!r} "
                f"but the level-1 taxonomy hashes to {general.sha256!r}"
            )
        for path in overlay.paths:
            if len(path) > 1 and path[:-1] not in paths:
                raise ValueError(
                    f"overlay {overlay.version!r} path {path} does not attach "
                    "below an existing path"
                )
        paths |= overlay.paths
        overlay_shas.append(overlay.sha256)
        versions.append(overlay.version)
    composed_sha = canonical_sha256(
        {"general": general.sha256, "overlays": overlay_shas}
    )
    return Taxonomy(
        version="+".join(versions),
        sha256=composed_sha,
        paths=frozenset(paths),
        parent_sha256=None,
    )
