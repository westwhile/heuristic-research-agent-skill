"""Public facade of the core records kernel.

Pipeline: strict JSON parsing -> schema dispatch by the record's ``schema``
field -> validation -> hash binding. Parsing details, schema loading, path
checks, and hashing stay in the private modules; callers only see
:func:`load_record` and :class:`Record`.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from ._canonical import canonical_bytes
from ._errors import CoreError, StrictJsonError, UnknownSchemaError
from ._schema import SchemaRegistry
from ._strict_json import load_strict_json

# A source checkout keeps the canonical schemas at <repo>/schemas/core. Wheels
# force-include that same tree under the package so an installed CLI has the
# identical frozen contracts without depending on repository layout.
_REPOSITORY_SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schemas" / "core"
_PACKAGED_SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "_schemas" / "core"
_DEFAULT_SCHEMA_ROOT = (
    _PACKAGED_SCHEMA_ROOT
    if _PACKAGED_SCHEMA_ROOT.is_dir()
    else _REPOSITORY_SCHEMA_ROOT
)

_CONSTRUCTION_TOKEN = object()


@lru_cache(maxsize=8)
def _registry_for(root: str) -> SchemaRegistry:
    return SchemaRegistry(root)


def _registry(schema_root: Path | str | None) -> SchemaRegistry:
    root = Path(schema_root) if schema_root is not None else _DEFAULT_SCHEMA_ROOT
    return _registry_for(str(root.resolve()))


def _copy_json_tree(value: Any) -> Any:
    """Deep copy of a strict-JSON tree (acyclic, no shared references).

    Iterative, so the nesting budget never consumes the call stack and deep
    records cannot leak a bare :class:`RecursionError`; scalars (``str``,
    ``int``, ``Decimal``, ``bool``, ``None``) are immutable and are shared
    safely.
    """
    if isinstance(value, dict):
        root: Any = {}
        work = [(child, root, key) for key, child in value.items()]
    elif isinstance(value, list):
        root = [None] * len(value)
        work = [(child, root, index) for index, child in enumerate(value)]
    else:
        return value
    while work:
        node, parent, slot = work.pop()
        if isinstance(node, dict):
            copied: Any = {}
            parent[slot] = copied
            for key, child in node.items():
                work.append((child, copied, key))
        elif isinstance(node, list):
            copied = [None] * len(node)
            parent[slot] = copied
            for index, child in enumerate(node):
                work.append((child, copied, index))
        else:
            parent[slot] = node
    return root


class Record:
    """A validated, hash-bound core record.

    Invariant: ``record.sha256 == canonical_sha256(record.data)`` always
    holds. This is enforced structurally:

    - construction is gated on an internal token, so the only way to obtain a
      Record is :func:`load_record`, which always validates first;
    - the constructor copies the validated payload via :func:`_copy_json_tree`,
      so later mutation of any caller-visible object cannot reach the record;
    - :attr:`data` returns a fresh copy via the same iterative copier, so
      callers cannot mutate the hashed content through the accessor either.
    """

    __slots__ = ("_schema_id", "_data", "_canonical", "_sha256")

    def __init__(
        self, schema_id: str, data: dict[str, Any], *, _token: object | None = None
    ) -> None:
        if _token is not _CONSTRUCTION_TOKEN:
            raise CoreError(
                "Record can only be constructed by load_record(); "
                "direct construction bypasses schema validation"
            )
        self._schema_id = schema_id
        self._data = _copy_json_tree(data)
        self._canonical = canonical_bytes(self._data)
        self._sha256 = hashlib.sha256(self._canonical).hexdigest()

    @property
    def schema_id(self) -> str:
        return self._schema_id

    @property
    def data(self) -> dict[str, Any]:
        """A fresh copy of the validated payload; mutating it affects nothing."""
        return _copy_json_tree(self._data)

    @property
    def canonical_bytes(self) -> bytes:
        return self._canonical

    @property
    def sha256(self) -> str:
        return self._sha256

    def __repr__(self) -> str:
        return f"Record(schema_id={self._schema_id!r}, sha256={self._sha256[:12]}...)"


def load_record(
    source: str | bytes | bytearray, *, schema_root: Path | str | None = None
) -> Record:
    """Parse, dispatch, and validate one core record.

    *source* is strict UTF-8 JSON text (or bytes). The record's ``schema``
    field selects the schema; unknown ids fail closed with
    :class:`UnknownSchemaError`. Validation failures raise
    :class:`RecordValidationError` with the full violation list.
    """
    data = load_strict_json(source)
    declared = data.get("schema")
    if not isinstance(declared, str):
        raise UnknownSchemaError('record must declare a string "schema" field')
    registry = _registry(schema_root)
    if not registry.has(declared):
        supported = ", ".join(registry.schema_ids)
        raise UnknownSchemaError(
            f"unsupported schema id {declared!r}; supported: {supported}"
        )
    try:
        registry.validate(declared, data)
    except RecursionError as exc:
        # Defensive: validation recurses over the schema's own nesting, so
        # only an extreme custom schema under a low caller recursion limit
        # can reach this; the kernel contract forbids leaking it.
        raise StrictJsonError(
            "validation nesting exceeds the safety limit"
        ) from exc
    return Record(declared, data, _token=_CONSTRUCTION_TOKEN)
