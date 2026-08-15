"""Canonical JSON serialization and content hashing for core records.

Canonical form (v1):

- input must belong to the strict JSON data model: ``None``, ``bool``,
  ``int`` (bounded by the frozen ``MAX_INT_DIGITS`` protocol limit), finite
  ``decimal.Decimal`` (bounded by ``MAX_DECIMAL_SCALE``), finite ``float``
  (normalized through ``Decimal(repr(...))`` so it cannot diverge from the
  exact-decimal path), ``str`` (no unpaired surrogates), ``list``, and
  ``dict`` with ``str`` keys; anything else (tuples, sets, bytes,
  non-string keys, ...) is rejected with :class:`StrictJsonError` instead
  of being silently coerced, so two different accepted inputs can never
  fold into the same canonical bytes;
- numbers serialize by exact mathematical value: an integral value becomes
  an integer literal (``1.0`` -> ``1``, ``1E+2`` -> ``100``, ``-0.0`` ->
  ``0``), otherwise the plain decimal form with trailing zeros stripped
  (``0.10`` -> ``0.1``, ``1E-7`` -> ``0.0000001``);
- UTF-8 bytes, no BOM, no trailing newline;
- object keys sorted lexicographically (code-point order);
- no insignificant whitespace (``,`` and ``:`` separators);
- non-ASCII characters emitted as UTF-8, not ``\\uXXXX`` escapes.

The serializer is iterative: the nesting budget (``MAX_WALK_DEPTH``) is a
data property, never a function of the interpreter recursion limit, and
deep-but-legal values cannot leak a bare :class:`RecursionError`. The
input-domain check shares the iterative walker in ``_walk.py``, and the
public entry additionally converts any residual :class:`RecursionError`
into :class:`StrictJsonError`. Integer output is formatted through
:class:`Decimal`, so the runtime-configurable ``int``/``str`` conversion
cap cannot change serialization outcomes.

Determinism caveat: number formatting is exact decimal normalized as above.
Cross-language canonical interop is a documented open point for a future
schema version, not part of this contract.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

from ._errors import StrictJsonError
from ._limits import INT_LIMIT, MAX_DECIMAL_SCALE, MAX_INT_DIGITS
from ._walk import walk_json_tree


class _Marker:
    """Structural token for the iterative serializer: closing brackets,
    separators, and pre-serialized ``"key":`` prefixes."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


def canonical_bytes(value: Any) -> bytes:
    """Serialize *value* to its canonical UTF-8 JSON byte form.

    Raises :class:`StrictJsonError` if *value* is outside the strict JSON
    data model (no coercion) or cannot be encoded as UTF-8.
    """
    try:
        _assert_json_data_model(value)
        text = _dump(value)
        return text.encode("utf-8")
    except StrictJsonError:
        raise
    except UnicodeEncodeError as exc:
        raise StrictJsonError(
            f"value contains characters that are not valid UTF-8: {exc}"
        ) from exc
    except RecursionError as exc:
        # Defensive: the walkers and the serializer are iterative, so this
        # should never fire; the contract still forbids leaking it.
        raise StrictJsonError("value nesting exceeds the safety limit") from exc


def canonical_sha256(value: Any) -> str:
    """Return the SHA-256 hex digest of the canonical byte form of *value*."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _dump(value: Any) -> str:
    """Iterative serializer: nesting depth never consumes the call stack."""
    out: list[str] = []
    stack: list[Any] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, _Marker):
            out.append(item.text)
        elif item is None:
            out.append("null")
        elif item is True:
            out.append("true")
        elif item is False:
            out.append("false")
        elif isinstance(item, int):
            out.append(_dump_int(item))
        elif isinstance(item, Decimal):
            out.append(_dump_decimal(item))
        elif isinstance(item, float):
            # repr is the shortest round-trip form; routing through Decimal
            # keeps direct float callers on the parsed-Decimal canonical text.
            out.append(_dump_decimal(Decimal(repr(item))))
        elif isinstance(item, str):
            out.append(json.dumps(item, ensure_ascii=False))
        elif isinstance(item, list):
            if not item:
                out.append("[]")
                continue
            out.append("[")
            stack.append(_Marker("]"))
            for child in reversed(item[1:]):
                stack.append(child)
                stack.append(_Marker(","))
            stack.append(item[0])
        else:
            # dict; keys are verified as str by _assert_json_data_model.
            items = sorted(item.items())
            if not items:
                out.append("{}")
                continue
            out.append("{")
            stack.append(_Marker("}"))
            for key, child in reversed(items[1:]):
                stack.append(child)
                stack.append(
                    _Marker("," + json.dumps(key, ensure_ascii=False) + ":")
                )
            first_key, first_child = items[0]
            stack.append(first_child)
            stack.append(_Marker(json.dumps(first_key, ensure_ascii=False) + ":"))
    return "".join(out)


def _dump_int(value: int) -> str:
    # Decimal formatting, not str(): the int<->str conversion cap is
    # runtime-configurable and must not leak into the frozen protocol.
    return format(Decimal(value), "f")


def _dump_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"  # normalizes -0.0 as well
    # format(..., "f") emits plain decimal without exponent and never
    # touches the runtime int<->str conversion cap.
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _assert_json_data_model(root: Any) -> None:
    """Reject anything outside the strict JSON data model (iterative walk)."""

    def visit(node: Any, path: str, _depth: int) -> None:
        if node is None or isinstance(node, bool):
            return
        if isinstance(node, int):
            if abs(node) >= INT_LIMIT:
                raise StrictJsonError(
                    f"integer at {path} exceeds the {MAX_INT_DIGITS}-digit "
                    f"protocol limit"
                )
            return
        if isinstance(node, float):
            if not math.isfinite(node):
                raise StrictJsonError(f"non-finite number at {path}")
            return
        if isinstance(node, Decimal):
            if not node.is_finite():
                raise StrictJsonError(f"non-finite number at {path}")
            if abs(node.adjusted()) >= MAX_DECIMAL_SCALE:
                raise StrictJsonError(
                    f"number at {path} exceeds the decimal scale limit"
                )
            return
        if isinstance(node, str):
            return
        if isinstance(node, list):
            return
        if isinstance(node, dict):
            for key in node:
                if not isinstance(key, str):
                    raise StrictJsonError(
                        f"object key at {path} must be a string, "
                        f"got {type(key).__name__}"
                    )
            return
        raise StrictJsonError(
            f"value at {path} is not part of the JSON data model: "
            f"{type(node).__name__}"
        )

    walk_json_tree(root, visit)
