"""JSON-Schema subset validator and schema registry.

Schemas are data: versioned ``*.schema.json`` files, not Python code. This
module supports exactly the keywords in ``_SUPPORTED_KEYWORDS`` and fails
closed on anything else, so a schema author cannot silently declare a
constraint that is never enforced. Every keyword's value type and its
combination with the declared ``type`` is validated at registry load;
malformed schemas raise :class:`SchemaDefinitionError`, never fail open.

Extension keywords (all enforced, none silently ignored):

- ``"x-safe-relative-path": true`` on a string schema enforces
  :func:`research_evolution.core.validate_safe_relative_path`;
- ``"x-rfc3339-datetime": true`` on a string schema is self-contained: it
  enforces the full RFC 3339 shape (date, ``T``, time with seconds, and an
  explicit ``Z``/offset) plus real calendar/clock/offset semantics;
- ``"x-at-least-one-of": [...]`` on an object schema requires at least one of
  the listed properties to be present;
- ``"x-conditional-min-items": [...]`` on an object schema requires a target
  array property to hold at least N items whenever a discriminator property
  equals one of the listed values (used for evidence-backed claim rules).

The standard ``pattern`` and ``minimum`` keywords keep stock JSON Schema Draft
2020-12 semantics (unanchored :func:`re.search` and exact numeric comparison).
Fields needing exact length combine ``pattern`` with
``minLength``/``maxLength``. Boundary keywords
(``minLength``/``maxLength``/``minItems``/``maxItems`` and rule
``min_items``) follow the Draft 2020-12 ``integer`` definition: any number
with a zero fractional part is accepted (``1.0`` is a legal bound) and
normalized to plain ``int`` at load; non-integral numbers, negatives, and
booleans fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ._errors import RecordValidationError, SchemaDefinitionError, UnsafePathError
from ._paths import validate_safe_relative_path
from ._strict_json import load_strict_json

_META_KEYWORDS = frozenset({"$schema", "$id", "title", "description"})
_SUPPORTED_KEYWORDS = _META_KEYWORDS | frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "x-safe-relative-path",
        "x-rfc3339-datetime",
        "x-at-least-one-of",
        "x-conditional-min-items",
    }
)
_TYPES = frozenset({"object", "array", "string", "boolean", "integer", "number", "null"})
# Which declared "type" a keyword is allowed to combine with. const/enum and
# the metadata keywords are type-agnostic.
_OBJECT_ONLY = frozenset(
    {
        "properties",
        "required",
        "additionalProperties",
        "x-at-least-one-of",
        "x-conditional-min-items",
    }
)
_ARRAY_ONLY = frozenset({"items", "minItems", "maxItems"})
_STRING_ONLY = frozenset(
    {"minLength", "maxLength", "pattern", "x-safe-relative-path", "x-rfc3339-datetime"}
)
_NON_NEGATIVE_INT = frozenset({"minItems", "maxItems", "minLength", "maxLength"})
_TRUE_ONLY = frozenset({"x-safe-relative-path", "x-rfc3339-datetime"})


@dataclass(frozen=True)
class Schema:
    """One parsed, integrity-checked schema document."""

    schema_id: str
    document: dict[str, Any]
    source_path: Path


class SchemaRegistry:
    """All schema documents found under one directory, keyed by ``$id``."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._schemas: dict[str, Schema] = {}
        self._load_all()

    @property
    def schema_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._schemas))

    def has(self, schema_id: str) -> bool:
        return schema_id in self._schemas

    def validate(self, schema_id: str, data: dict[str, Any]) -> None:
        """Validate *data* against *schema_id*, raising RecordValidationError."""
        schema = self._schemas[schema_id]
        violations: list[str] = []
        _validate_node(schema.document, data, "$", violations)
        if violations:
            raise RecordValidationError(schema_id, violations)

    def _load_all(self) -> None:
        if not self._root.is_dir():
            raise SchemaDefinitionError(f"schema root does not exist: {self._root}")
        files = sorted(self._root.glob("*.schema.json"))
        if not files:
            raise SchemaDefinitionError(f"no *.schema.json files under {self._root}")
        for path in files:
            schema = self._load_one(path)
            if schema.schema_id in self._schemas:
                raise SchemaDefinitionError(
                    f"duplicate schema id {schema.schema_id!r} in "
                    f"{path.name} and {self._schemas[schema.schema_id].source_path.name}"
                )
            self._schemas[schema.schema_id] = schema

    def _load_one(self, path: Path) -> Schema:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise SchemaDefinitionError(f"cannot read schema file {path}: {exc}") from exc
        try:
            document = load_strict_json(raw)
        except Exception as exc:
            raise SchemaDefinitionError(
                f"schema file {path.name} is not strict JSON: {exc}"
            ) from exc
        try:
            _check_schema_node(document, "$", path.name)
        except RecursionError as exc:
            # Defensive: meta-validation recurses over the schema structure,
            # so a maximally deep schema under a low caller recursion limit
            # must fail closed, not leak.
            raise SchemaDefinitionError(
                f"{path.name}: schema nesting too deep to meta-validate"
            ) from exc
        schema_id = document.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise SchemaDefinitionError(f"{path.name}: missing string $id")
        expected_name = schema_id.replace("/", "-") + ".schema.json"
        if path.name != expected_name:
            raise SchemaDefinitionError(
                f"{path.name}: filename must be {expected_name!r} for $id {schema_id!r}"
            )
        const = document.get("properties", {}).get("schema", {}).get("const")
        if const != schema_id:
            raise SchemaDefinitionError(
                f"{path.name}: properties.schema.const must equal $id {schema_id!r}"
            )
        return Schema(schema_id=schema_id, document=document, source_path=path)


def _check_schema_node(node: Any, path: str, filename: str) -> None:
    """Fail closed on any schema construct outside the supported subset."""
    if not isinstance(node, dict):
        raise SchemaDefinitionError(
            f"{filename}: schema node at {path} must be an object, "
            f"got {_json_type(node)}"
        )
    unknown = set(node) - _SUPPORTED_KEYWORDS
    if unknown:
        raise SchemaDefinitionError(
            f"{filename}: unsupported keyword(s) at {path}: {sorted(unknown)}"
        )
    declared_type = node.get("type")
    if declared_type is not None and declared_type not in _TYPES:
        raise SchemaDefinitionError(
            f"{filename}: unsupported type at {path}: {declared_type!r}"
        )
    for meta in ("$schema", "$id", "title", "description"):
        if meta in node and not isinstance(node[meta], str):
            raise SchemaDefinitionError(
                f"{filename}: {meta} at {path} must be a string"
            )
    for keyword in node:
        if keyword in _OBJECT_ONLY and declared_type != "object":
            raise SchemaDefinitionError(
                f"{filename}: {keyword} at {path} requires type object"
            )
        if keyword in _ARRAY_ONLY and declared_type != "array":
            raise SchemaDefinitionError(
                f"{filename}: {keyword} at {path} requires type array"
            )
        if keyword in _STRING_ONLY and declared_type != "string":
            raise SchemaDefinitionError(
                f"{filename}: {keyword} at {path} requires type string"
            )
        if keyword == "minimum" and declared_type not in {"integer", "number"}:
            raise SchemaDefinitionError(
                f"{filename}: minimum at {path} requires type integer or number"
            )
    for keyword in _NON_NEGATIVE_INT:
        if keyword in node:
            bound = _as_mathematical_integer(node[keyword])
            if bound is None or bound < 0:
                raise SchemaDefinitionError(
                    f"{filename}: {keyword} at {path} must be a non-negative integer"
                )
            node[keyword] = bound  # normalize 1.0 -> 1 for comparisons/messages
    for keyword in _TRUE_ONLY:
        if keyword in node and node[keyword] is not True:
            raise SchemaDefinitionError(
                f"{filename}: {keyword} at {path} must be exactly true"
            )
    if "minimum" in node:
        minimum = node["minimum"]
        if (
            isinstance(minimum, bool)
            or not isinstance(minimum, (int, float, Decimal))
            or not _as_decimal(minimum).is_finite()
        ):
            raise SchemaDefinitionError(
                f"{filename}: minimum at {path} must be a finite number"
            )
    if "minItems" in node and "maxItems" in node and node["minItems"] > node["maxItems"]:
        raise SchemaDefinitionError(f"{filename}: minItems > maxItems at {path}")
    if (
        "minLength" in node
        and "maxLength" in node
        and node["minLength"] > node["maxLength"]
    ):
        raise SchemaDefinitionError(f"{filename}: minLength > maxLength at {path}")
    if "required" in node:
        required = node["required"]
        if not isinstance(required, list) or not all(
            isinstance(item, str) for item in required
        ):
            raise SchemaDefinitionError(
                f"{filename}: required at {path} must be a list of strings"
            )
        if len(set(required)) != len(required):
            raise SchemaDefinitionError(f"{filename}: required at {path} has duplicates")
    if "enum" in node:
        enum = node["enum"]
        if not isinstance(enum, list) or not enum:
            raise SchemaDefinitionError(
                f"{filename}: enum at {path} must be a non-empty list"
            )
    if "additionalProperties" in node and not isinstance(
        node["additionalProperties"], bool
    ):
        raise SchemaDefinitionError(
            f"{filename}: additionalProperties at {path} must be a boolean"
        )
    if "pattern" in node:
        pattern = node["pattern"]
        if not isinstance(pattern, str):
            raise SchemaDefinitionError(f"{filename}: pattern at {path} must be a string")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise SchemaDefinitionError(
                f"{filename}: pattern at {path} does not compile: {exc}"
            ) from exc
    if "x-at-least-one-of" in node:
        group = node["x-at-least-one-of"]
        if (
            not isinstance(group, list)
            or not group
            or not all(isinstance(item, str) for item in group)
        ):
            raise SchemaDefinitionError(
                f"{filename}: x-at-least-one-of at {path} must be a non-empty "
                f"list of property names"
            )
        properties = node.get("properties", {})
        missing = [item for item in group if item not in properties]
        if missing:
            raise SchemaDefinitionError(
                f"{filename}: x-at-least-one-of at {path} references undeclared "
                f"properties: {missing}"
            )
    if "x-conditional-min-items" in node:
        _check_conditional_min_items(node["x-conditional-min-items"], node, path, filename)
    if "properties" in node:
        properties = node["properties"]
        if not isinstance(properties, dict):
            raise SchemaDefinitionError(
                f"{filename}: properties at {path} must be an object"
            )
        for key, subschema in properties.items():
            _check_schema_node(subschema, f"{path}.properties.{key}", filename)
    if "items" in node:
        _check_schema_node(node["items"], f"{path}.items", filename)


_CONDITIONAL_RULE_KEYS = frozenset(
    {"when_property", "when_equals", "then_property", "min_items"}
)


def _check_conditional_min_items(
    rules: Any, node: dict[str, Any], path: str, filename: str
) -> None:
    if not isinstance(rules, list) or not rules:
        raise SchemaDefinitionError(
            f"{filename}: x-conditional-min-items at {path} must be a "
            f"non-empty list of rules"
        )
    properties = node.get("properties", {})
    for index, rule in enumerate(rules):
        rule_path = f"{path}.x-conditional-min-items[{index}]"
        if not isinstance(rule, dict):
            raise SchemaDefinitionError(
                f"{filename}: rule at {rule_path} must be an object"
            )
        unknown = set(rule) - _CONDITIONAL_RULE_KEYS
        if unknown or set(rule) != set(_CONDITIONAL_RULE_KEYS):
            raise SchemaDefinitionError(
                f"{filename}: rule at {rule_path} must have exactly the keys "
                f"{sorted(_CONDITIONAL_RULE_KEYS)}; unknown/missing: "
                f"{sorted(unknown) or 'none'}"
            )
        when_property = rule["when_property"]
        when_equals = rule["when_equals"]
        then_property = rule["then_property"]
        min_items = rule["min_items"]
        if not isinstance(when_property, str) or when_property not in properties:
            raise SchemaDefinitionError(
                f"{filename}: rule at {rule_path} references undeclared "
                f"when_property {when_property!r}"
            )
        if not isinstance(when_equals, list) or not when_equals:
            raise SchemaDefinitionError(
                f"{filename}: rule at {rule_path} when_equals must be a "
                f"non-empty list"
            )
        then_schema = properties.get(then_property)
        if not isinstance(then_property, str) or not isinstance(then_schema, dict):
            raise SchemaDefinitionError(
                f"{filename}: rule at {rule_path} references undeclared "
                f"then_property {then_property!r}"
            )
        if then_schema.get("type") != "array":
            raise SchemaDefinitionError(
                f"{filename}: rule at {rule_path} then_property "
                f"{then_property!r} must be declared with type array"
            )
        min_items_value = _as_mathematical_integer(min_items)
        if min_items_value is None or min_items_value < 1:
            raise SchemaDefinitionError(
                f"{filename}: rule at {rule_path} min_items must be a "
                f"positive integer"
            )
        rule["min_items"] = min_items_value


def _validate_node(
    schema: dict[str, Any], value: Any, path: str, violations: list[str]
) -> None:
    declared_type = schema.get("type")
    if declared_type is not None and not _type_matches(declared_type, value):
        violations.append(
            f"{path}: expected type {declared_type}, got {_json_type(value)}"
        )
        return
    if "const" in schema and not _json_equal(value, schema["const"]):
        violations.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and not any(
        _json_equal(value, option) for option in schema["enum"]
    ):
        violations.append(f"{path}: must be one of {schema['enum']!r}")
    if "minimum" in schema and _as_decimal(value) < _as_decimal(schema["minimum"]):
        violations.append(f"{path}: must be >= {schema['minimum']!r}")
    if declared_type == "object":
        for key in schema.get("required", []):
            if key not in value:
                violations.append(f"{path}: missing required property {key!r}")
        group = schema.get("x-at-least-one-of")
        if group is not None and not any(key in value for key in group):
            violations.append(f"{path}: at least one of {group} is required")
        for rule in schema.get("x-conditional-min-items", []):
            when_property = rule["when_property"]
            if when_property in value and any(
                _json_equal(value[when_property], option)
                for option in rule["when_equals"]
            ):
                target = value.get(rule["then_property"])
                if not isinstance(target, list) or len(target) < rule["min_items"]:
                    violations.append(
                        f"{path}.{rule['then_property']}: must contain at "
                        f"least {rule['min_items']} item(s) when "
                        f"{when_property} is one of {rule['when_equals']}"
                    )
        properties = schema.get("properties", {})
        additional_forbidden = schema.get("additionalProperties") is False
        for key, item in value.items():
            if key in properties:
                _validate_node(properties[key], item, f"{path}.{key}", violations)
            elif additional_forbidden:
                violations.append(f"{path}: additional property {key!r} is not allowed")
    elif declared_type == "array":
        if "minItems" in schema and len(value) < schema["minItems"]:
            violations.append(
                f"{path}: expected at least {schema['minItems']} item(s), got {len(value)}"
            )
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            violations.append(
                f"{path}: expected at most {schema['maxItems']} item(s), got {len(value)}"
            )
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _validate_node(item_schema, item, f"{path}[{index}]", violations)
    elif declared_type == "string":
        if "minLength" in schema and len(value) < schema["minLength"]:
            violations.append(
                f"{path}: expected length >= {schema['minLength']}, got {len(value)}"
            )
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            violations.append(
                f"{path}: expected length <= {schema['maxLength']}, got {len(value)}"
            )
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            violations.append(f"{path}: does not match pattern {schema['pattern']!r}")
        if schema.get("x-rfc3339-datetime") is True and not _is_rfc3339_datetime(value):
            violations.append(f"{path}: is not a valid RFC 3339 timestamp")
        if schema.get("x-safe-relative-path") is True:
            try:
                validate_safe_relative_path(value)
            except UnsafePathError as exc:
                violations.append(f"{path}: {exc}")


_RFC3339_SHAPE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def _is_rfc3339_datetime(value: str) -> bool:
    """Self-contained RFC 3339 check: full shape plus real semantics.

    Seconds and an explicit ``Z``/offset are mandatory (a bare date like
    ``2026-08-14`` fails); impossible values such as
    ``2026-99-99T99:99:99+99:99`` and leap seconds are rejected.
    """
    if _RFC3339_SHAPE.fullmatch(value) is None:
        return False
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return False
    return True


def _type_matches(declared_type: str, value: Any) -> bool:
    if declared_type == "object":
        return isinstance(value, dict)
    if declared_type == "array":
        return isinstance(value, list)
    if declared_type == "string":
        return isinstance(value, str)
    if declared_type == "boolean":
        return isinstance(value, bool)
    if declared_type == "integer":
        # Draft 2020-12: any number with a zero fractional part matches.
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        if isinstance(value, Decimal):
            return value == value.to_integral_value()
        if isinstance(value, float):
            return value.is_integer()
        return False
    if declared_type == "number":
        return isinstance(value, (int, float, Decimal)) and not isinstance(
            value, bool
        )
    if declared_type == "null":
        return value is None
    return False


def _as_decimal(value: int | float | Decimal) -> Decimal:
    """Exact-decimal view of a JSON number (booleans excluded by callers)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def _as_mathematical_integer(value: Any) -> int | None:
    """Draft 2020-12 ``integer`` view of a parsed JSON number.

    Any number with a zero fractional part is an integer (``1.0`` and
    ``1e2`` qualify); booleans, non-integral numbers, and non-numbers do
    not. Returns the plain ``int`` form, or ``None`` when not an integer.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if value.is_finite() and value == value.to_integral_value():
            return int(value)
        return None
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    return None


def _json_equal(left: Any, right: Any) -> bool:
    """Recursive JSON equality (Draft 2020-12 const/enum semantics).

    Booleans and numbers are strictly distinct (``true`` is not ``1``);
    numbers compare by exact decimal value (``1``, ``1.0`` and ``1e0`` are
    equal, and ``10**24`` equals ``1e24``); arrays and objects compare
    recursively, element by element.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float, Decimal)) and isinstance(
        right, (int, float, Decimal)
    ):
        return _as_decimal(left) == _as_decimal(right)
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(item_left, item_right)
            for item_left, item_right in zip(left, right, strict=True)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            return False
        return all(_json_equal(left[key], right[key]) for key in left)
    return False


def _json_type(value: Any) -> str:
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
