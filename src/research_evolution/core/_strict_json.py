"""Strict UTF-8 JSON parsing for core records.

The parser is a purpose-built iterative descent parser with an explicit
container stack. It never reads or modifies process-global interpreter
state (the recursion limit is untouched), so the same in-budget document
parses identically under any caller recursion limit and under concurrent
calls; the stdlib ``json`` scanner is not used at all.

Fail-closed rules, applied before any schema work:

- input must be UTF-8 (``str`` or UTF-8 ``bytes``); a BOM is rejected;
- duplicate object keys are rejected at every nesting level (keys are
  compared after escape decoding, so ``"a"`` and ``"\\u0061"`` collide);
- ``NaN``/``Infinity``/``-Infinity`` literals are rejected (they are not
  valid JSON tokens);
- the numeric model is arbitrary-precision decimal: JSON fractions are
  parsed as :class:`decimal.Decimal`, never as binary floats, so two
  distinct literals (for example ``9007199254740992.0`` and
  ``9007199254740993.0``) can never collapse into one value, and a tiny
  literal can never silently underflow to ``0.0``; digits are ASCII
  ``0-9`` only (RFC 8259) — Unicode decimal digits (Arabic-Indic,
  full-width, ...) are rejected in every number position;
- numeric limits are frozen protocol constants (see ``_limits.py``), not
  the runtime-adjustable ``sys.get_int_max_str_digits()``: integers beyond
  ``MAX_INT_DIGITS`` digits and decimals whose absolute adjusted exponent
  reaches ``MAX_DECIMAL_SCALE`` are rejected on every machine alike;
- strings containing unpaired surrogates are rejected (they cannot be
  encoded as UTF-8 during canonical serialization); valid ``\\uXXXX``
  surrogate pairs are combined into the intended astral character;
- the top-level value must be an object;
- the nesting budget ``MAX_WALK_DEPTH`` is enforced per call as data
  (explicit stack, shared with the canonicalizer via ``_walk.py``);
  over-budget documents fail with :class:`StrictJsonError`, never a bare
  :class:`RecursionError`.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from ._errors import StrictJsonError
from ._limits import MAX_DECIMAL_SCALE, MAX_INT_DIGITS, MAX_WALK_DEPTH
from ._walk import walk_json_tree

_UTF8_BOM = b"\xef\xbb\xbf"
_WHITESPACE = " \t\n\r"
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
# RFC 8259 digits are ASCII 0-9 only; ``\d`` would also match Unicode
# decimal digits (Arabic-Indic, full-width, ...), so the class is explicit.
_NUMBER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_NUMBER_DELIMITERS = frozenset(" \t\n\r,]}")
_KEYWORDS = (("true", True), ("false", False), ("null", None))


def load_strict_json(source: str | bytes | bytearray) -> dict[str, Any]:
    """Parse *source* into a Python object under the strict rules above.

    Returns the parsed top-level object; JSON fractions are returned as
    :class:`decimal.Decimal`, integers as arbitrary-precision ``int``.
    Raises :class:`StrictJsonError` on any violation; never returns
    partially parsed data.
    """
    text = _to_text(source)
    if not text.strip():
        raise StrictJsonError("input is empty")
    try:
        data = _parse_document(text)
        _check_value(data)
    except StrictJsonError:
        raise
    except RecursionError as exc:
        # Defensive: the parser and the walkers are iterative, so this
        # should never fire; the contract still forbids leaking it.
        raise StrictJsonError("document nesting exceeds the safety limit") from exc
    except (ValueError, ArithmeticError) as exc:
        raise StrictJsonError(f"number literal cannot be represented: {exc}") from exc
    if not isinstance(data, dict):
        raise StrictJsonError(
            f"top-level JSON value must be an object, got {_type_name(data)}"
        )
    return data


def _to_text(source: str | bytes | bytearray) -> str:
    if isinstance(source, str):
        if source.startswith("\ufeff"):
            raise StrictJsonError("a BOM marker is not allowed in JSON records")
        return source
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
        if raw.startswith(_UTF8_BOM):
            raise StrictJsonError("a UTF-8 BOM is not allowed in JSON records")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StrictJsonError(f"record is not valid UTF-8: {exc}") from exc
    raise StrictJsonError(
        f"unsupported source type: {type(source).__name__}; expected str or UTF-8 bytes"
    )


def _skip_ws(text: str, pos: int, n: int) -> int:
    while pos < n and text[pos] in _WHITESPACE:
        pos += 1
    return pos


def _parse_document(text: str) -> Any:
    """Iterative descent parse of one JSON document; explicit container stack.

    Frames are ``["object", dict, pending_key]`` or ``["array", list]``.
    Container depth is bounded per call by ``MAX_WALK_DEPTH``; scalars one
    level deeper are still caught by the post-parse walk.
    """
    n = len(text)
    pos = _skip_ws(text, 0, n)
    stack: list[list] = []
    root: Any = None
    have_root = False

    while True:
        # Parse one value; containers push a frame and loop for their
        # first element/key.
        if pos >= n:
            raise StrictJsonError("unexpected end of JSON input")
        ch = text[pos]
        if ch == "{":
            _check_container_depth(stack)
            stack.append(["object", {}, None])
            pos = _skip_ws(text, pos + 1, n)
            if pos < n and text[pos] == "}":
                pos += 1
                completed: Any = stack.pop()[1]
            else:
                key, pos = _parse_object_key(text, pos, n)
                stack[-1][2] = key
                continue
        elif ch == "[":
            _check_container_depth(stack)
            stack.append(["array", []])
            pos = _skip_ws(text, pos + 1, n)
            if pos < n and text[pos] == "]":
                pos += 1
                completed = stack.pop()[1]
            else:
                continue
        elif ch == '"':
            completed, pos = _parse_string(text, pos)
        elif ch == "-" or "0" <= ch <= "9":
            if text.startswith("-Infinity", pos):
                raise StrictJsonError(
                    "non-finite number literal is not allowed: -Infinity"
                )
            completed, pos = _parse_number(text, pos)
        else:
            completed, pos = _parse_keyword(text, pos)

        # Attach the completed value; cascades while containers close.
        while True:
            if not stack:
                root = completed
                have_root = True
                break
            frame = stack[-1]
            if frame[0] == "array":
                frame[1].append(completed)
                pos = _skip_ws(text, pos, n)
                if pos < n and text[pos] == ",":
                    pos = _skip_ws(text, pos + 1, n)
                    break  # parse the next element
                if pos < n and text[pos] == "]":
                    pos += 1
                    completed = stack.pop()[1]
                    continue
                raise StrictJsonError("expected ',' or ']' in array")
            key = frame[2]
            mapping = frame[1]
            if key in mapping:
                raise StrictJsonError(f"duplicate object key: {key!r}")
            mapping[key] = completed
            frame[2] = None
            pos = _skip_ws(text, pos, n)
            if pos < n and text[pos] == ",":
                pos = _skip_ws(text, pos + 1, n)
                key, pos = _parse_object_key(text, pos, n)
                frame[2] = key
                break  # parse the value for the new key
            if pos < n and text[pos] == "}":
                pos += 1
                completed = stack.pop()[1]
                continue
            raise StrictJsonError("expected ',' or '}' in object")
        if have_root:
            break

    pos = _skip_ws(text, pos, n)
    if pos != n:
        raise StrictJsonError(f"trailing data after JSON document at offset {pos}")
    return root


def _check_container_depth(stack: list) -> None:
    if len(stack) > MAX_WALK_DEPTH:
        raise StrictJsonError("value nesting exceeds the safety limit")


def _parse_object_key(text: str, pos: int, n: int) -> tuple[str, int]:
    if pos >= n or text[pos] != '"':
        raise StrictJsonError("expected an object key string")
    key, pos = _parse_string(text, pos)
    pos = _skip_ws(text, pos, n)
    if pos >= n or text[pos] != ":":
        raise StrictJsonError("expected ':' after object key")
    return key, _skip_ws(text, pos + 1, n)


def _parse_string(text: str, pos: int) -> tuple[str, int]:
    """Parse a JSON string; *pos* is at the opening quote."""
    n = len(text)
    pos += 1
    out: list[str] = []
    while True:
        if pos >= n:
            raise StrictJsonError("unterminated string")
        ch = text[pos]
        if ch == '"':
            return "".join(out), pos + 1
        if ch == "\\":
            if pos + 1 >= n:
                raise StrictJsonError("unterminated escape sequence")
            esc = text[pos + 1]
            if esc in _SIMPLE_ESCAPES:
                out.append(_SIMPLE_ESCAPES[esc])
                pos += 2
                continue
            if esc == "u":
                code, pos = _parse_unicode_escape(text, pos + 2, n)
                if 0xD800 <= code <= 0xDBFF and text[pos : pos + 2] == "\\u":
                    low, new_pos = _parse_unicode_escape(text, pos + 2, n)
                    if 0xDC00 <= low <= 0xDFFF:
                        out.append(
                            chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00))
                        )
                    else:
                        out.append(chr(code))  # lone surrogate; walker rejects
                        out.append(chr(low))
                    pos = new_pos
                    continue
                out.append(chr(code))  # BMP escape or lone surrogate
                continue
            raise StrictJsonError(f"invalid escape sequence: \\{esc}")
        if ord(ch) < 0x20:
            raise StrictJsonError("unescaped control character in string")
        out.append(ch)
        pos += 1


def _parse_unicode_escape(text: str, pos: int, n: int) -> tuple[int, int]:
    """Read four hex digits at *pos*; return (code point, position after)."""
    digits = text[pos : pos + 4]
    if len(digits) < 4 or any(char not in _HEX_DIGITS for char in digits):
        raise StrictJsonError("invalid \\u escape sequence")
    return int(digits, 16), pos + 4


def _parse_number(text: str, pos: int) -> tuple[Any, int]:
    """Parse a JSON number literal (strict grammar: ASCII digits only, no
    leading zeros, no leading ``.``, no ``+``). Fractions/exponents become
    exact :class:`Decimal`; plain integers become arbitrary-precision
    ``int``. A non-delimiter immediately after the literal (for example a
    Unicode digit) is a number error, not a structural one."""
    match = _NUMBER_RE.match(text, pos)
    if match is None:
        raise StrictJsonError(f"invalid number literal at offset {pos}")
    token = match.group(0)
    end = match.end()
    if end < len(text) and text[end] not in _NUMBER_DELIMITERS:
        raise StrictJsonError(f"invalid number literal at offset {pos}")
    if "." in token or "e" in token or "E" in token:
        return _parse_decimal(token), end
    return _parse_int(token), end


def _parse_keyword(text: str, pos: int) -> tuple[Any, int]:
    for literal, value in _KEYWORDS:
        if text.startswith(literal, pos):
            return value, pos + len(literal)
    for token in ("NaN", "Infinity"):
        if text.startswith(token, pos):
            raise StrictJsonError(
                f"non-finite number literal is not allowed: {token}"
            )
    raise StrictJsonError(f"invalid JSON value at offset {pos}")


def _parse_int(text: str) -> int:
    """Parse a JSON integer literal under the frozen digit limit.

    Routing through :class:`Decimal` keeps the result independent of the
    runtime ``int``/``str`` conversion cap (``PYTHONINTMAXSTRDIGITS``):
    the protocol limit is ``MAX_INT_DIGITS`` on every machine.
    """
    if len(text.lstrip("-")) > MAX_INT_DIGITS:
        raise StrictJsonError(
            f"integer literal exceeds the {MAX_INT_DIGITS}-digit protocol limit"
        )
    return int(Decimal(text))


def _parse_decimal(text: str) -> Decimal:
    """Parse a JSON fraction literal as an exact decimal, with a scale cap."""
    value = Decimal(text)
    if not value.is_finite():
        raise StrictJsonError(f"non-finite number literal is not allowed: {text}")
    if abs(value.adjusted()) >= MAX_DECIMAL_SCALE:
        raise StrictJsonError(
            f"number literal exceeds the decimal scale limit: {text[:32]}"
        )
    return value


def _has_lone_surrogate(text: str) -> bool:
    return any(0xD800 <= ord(char) <= 0xDFFF for char in text)


def _check_value(root: Any) -> None:
    """Post-parse checks via the shared iterative walker (no call-stack use)."""

    def visit(node: Any, path: str, _depth: int) -> None:
        if isinstance(node, Decimal):
            if not node.is_finite():  # defensive; _parse_decimal already enforces
                raise StrictJsonError(f"non-finite number at {path}")
        elif isinstance(node, str):
            if _has_lone_surrogate(node):
                raise StrictJsonError(f"unpaired surrogate in string at {path}")
        elif isinstance(node, dict):
            for key in node:
                if _has_lone_surrogate(key):
                    raise StrictJsonError(f"unpaired surrogate in object key at {path}")

    walk_json_tree(root, visit)


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float, Decimal)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"
