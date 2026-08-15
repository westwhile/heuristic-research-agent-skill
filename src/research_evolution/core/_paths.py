"""Safe relative-path validation for record locators.

Records stored in the public repository must never carry absolute,
machine-specific, or aliasable paths. Stored locators are POSIX-form only;
validation never normalizes, so the stored value *is* the canonical form and
two spellings of the same path cannot hash differently.

Rules:

- separators: only ``/``; backslashes are rejected outright (this also
  eliminates UNC ``\\\\server\\share`` forms);
- rejected: POSIX-root paths (``/etc``), drive-letter paths (``C:/x``),
  drive-relative paths (``C:x``), ``..`` and ``.`` components, empty
  components (``a//b``), components with leading/trailing whitespace or a
  trailing dot, Windows reserved device names (``CON``, ``PRN``, ``AUX``,
  ``NUL``, ``COM1``-``COM9``, ``LPT1``-``LPT9``, with or without extension),
  Windows-forbidden characters (``<>:"|?*``), control characters
  (``0x00``-``0x1F``, ``0x7F``), and leading/trailing whitespace;
- accepted: clean relative POSIX paths such as ``artifacts/run-001/out.json``.
"""

from __future__ import annotations

import re

from ._errors import UnsafePathError

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_CONTROL_CHAR = re.compile(r"[\x00-\x1f\x7f]")
_FORBIDDEN_CHARS = frozenset('<>:"|?*')
_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def validate_safe_relative_path(raw: str) -> str:
    """Validate *raw* and return it unchanged once accepted.

    Raises :class:`UnsafePathError` on any rule violation. The return value
    equals the input: accepted paths are already in canonical POSIX form.
    """
    if not isinstance(raw, str):
        raise UnsafePathError(f"path must be a string, got {type(raw).__name__}")
    if not raw:
        raise UnsafePathError("path is empty")
    if raw != raw.strip():
        raise UnsafePathError(f"path has leading or trailing whitespace: {raw!r}")
    if _CONTROL_CHAR.search(raw):
        raise UnsafePathError(f"path contains a control character: {raw!r}")
    if _DRIVE_PREFIX.match(raw):
        raise UnsafePathError(f"drive-letter paths are not allowed: {raw!r}")
    if "\\" in raw:
        raise UnsafePathError(
            f"backslash separators are not allowed in record locators; "
            f"use '/': {raw!r}"
        )
    if raw.startswith("/"):
        raise UnsafePathError(
            f"absolute, root-anchored, or UNC paths are not allowed: {raw!r}"
        )
    for component in raw.split("/"):
        if component == "":
            raise UnsafePathError(f"path contains an empty component: {raw!r}")
        if component in (".", ".."):
            raise UnsafePathError(
                f"path component {component!r} is not allowed: {raw!r}"
            )
        if component != component.strip() or component != component.rstrip("."):
            raise UnsafePathError(
                f"path component {component!r} has leading/trailing whitespace "
                f"or a trailing dot: {raw!r}"
            )
        stem = component.split(".", 1)[0].upper()
        if stem in _WINDOWS_DEVICE_NAMES:
            raise UnsafePathError(
                f"path component {component!r} is a reserved Windows device "
                f"name: {raw!r}"
            )
        bad = sorted(_FORBIDDEN_CHARS.intersection(component))
        if bad:
            raise UnsafePathError(
                f"path component {component!r} contains forbidden character "
                f"{bad[0]!r}: {raw!r}"
            )
    return raw
