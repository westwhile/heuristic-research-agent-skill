"""Mutation tests for schema-definition validation.

Every keyword in the supported subset must be validated for value type,
range, and combination with the declared ``type`` at registry load time. Each
test below is a mutation that previously failed open (or could): the registry
must raise SchemaDefinitionError rather than silently ignore the constraint
or leak an unrelated exception.
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from research_evolution.core import (
    RecordValidationError,
    SchemaDefinitionError,
    load_record,
)

BASE_SCHEMA = {
    "$id": "x-probe/v1",
    "title": "Probe schema for mutation tests",
    "type": "object",
    "required": ["schema", "probe_id"],
    "properties": {
        "schema": {"const": "x-probe/v1"},
        "probe_id": {"type": "string", "minLength": 1},
        "tags": {"type": "array", "items": {"type": "string"}},
        "locator": {"type": "string", "x-safe-relative-path": True},
        "meta": {"type": "object"},
    },
    "additionalProperties": False,
}

VALID_RECORD = '{"schema": "x-probe/v1", "probe_id": "p1"}'


def _load_with(document: dict, record: str = VALID_RECORD):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "x-probe-v1.schema.json").write_text(
            json.dumps(document), encoding="utf-8"
        )
        return load_record(record, schema_root=root)


def _set(path: tuple, value):
    def mutator(document: dict) -> None:
        node = document
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return mutator


MUTATIONS = {
    # The three penetrations from adversarial review:
    "additionalProperties-string": _set(("additionalProperties",), "false"),
    "safe-path-string": _set(
        ("properties", "locator", "x-safe-relative-path"), "yes"
    ),
    "items-not-a-schema": _set(("properties", "tags", "items"), "not-a-schema"),
    # Value types:
    "minLength-negative": _set(("properties", "probe_id", "minLength"), -1),
    "minLength-string": _set(("properties", "probe_id", "minLength"), "1"),
    "minLength-float": _set(("properties", "probe_id", "minLength"), 1.5),
    "minLength-bool": _set(("properties", "probe_id", "minLength"), True),
    "minItems-negative": _set(("properties", "tags", "minItems"), -1),
    "minItems-float": _set(("properties", "tags", "minItems"), 1.5),
    "minItems-bool": _set(("properties", "tags", "minItems"), True),
    "maxLength-negative": _set(("properties", "probe_id", "maxLength"), -1),
    "maxLength-float": _set(("properties", "probe_id", "maxLength"), 1.5),
    "maxLength-bool": _set(("properties", "probe_id", "maxLength"), True),
    "maxItems-negative": _set(("properties", "tags", "maxItems"), -1),
    "maxItems-float": _set(("properties", "tags", "maxItems"), 1.5),
    "maxItems-bool": _set(("properties", "tags", "maxItems"), True),
    "required-not-list": _set(("required",), "schema"),
    "required-duplicates": _set(("required",), ["schema", "schema"]),
    "enum-empty": _set(("properties", "probe_id", "enum"), []),
    "enum-not-list": _set(("properties", "probe_id", "enum"), "x"),
    "properties-not-dict": _set(("properties",), ["schema"]),
    "properties-value-not-dict": _set(("properties", "bad"), 5),
    "pattern-not-string": _set(("properties", "probe_id", "pattern"), 64),
    "pattern-uncompilable": _set(("properties", "probe_id", "pattern"), "["),
    "type-unknown": _set(("type",), "str"),
    # Combination constraints:
    "minLength-on-array": _set(("properties", "tags", "minLength"), 1),
    "pattern-on-object": _set(("pattern",), "^x$"),
    "items-on-object": _set(("items",), {"type": "string"}),
    "additionalProperties-on-array": _set(
        ("properties", "tags", "additionalProperties"), False
    ),
    "safe-path-on-array": _set(("properties", "tags", "x-safe-relative-path"), True),
    "rfc3339-not-true": _set(("properties", "probe_id", "x-rfc3339-datetime"), "yes"),
    "at-least-one-of-not-list": _set(("x-at-least-one-of",), "probe_id"),
    "at-least-one-of-undeclared": _set(("x-at-least-one-of",), ["missing"]),
    "at-least-one-of-on-string": _set(
        ("properties", "probe_id", "x-at-least-one-of"), ["x"]
    ),
    "unsupported-keyword-format": _set(("properties", "probe_id", "format"), "date-time"),
}


def _min_gt_max(document: dict) -> None:
    document["properties"]["tags"]["minItems"] = 3
    document["properties"]["tags"]["maxItems"] = 1


def _minlen_gt_maxlen(document: dict) -> None:
    document["properties"]["probe_id"]["minLength"] = 5
    document["properties"]["probe_id"]["maxLength"] = 2


MUTATIONS["minItems-gt-maxItems"] = _min_gt_max
MUTATIONS["minLength-gt-maxLength"] = _minlen_gt_maxlen


def _valid_conditional_rule() -> dict:
    # probe_id (string) is the discriminator; tags (array) is the target.
    return {
        "when_property": "probe_id",
        "when_equals": ["strict"],
        "then_property": "tags",
        "min_items": 1,
    }


def _set_conditional_rules(value):
    return _set(("x-conditional-min-items",), value)


def _mutate_conditional_rule(**overrides):
    def mutator(document: dict) -> None:
        rule = _valid_conditional_rule()
        rule.update(overrides)
        document["x-conditional-min-items"] = [rule]

    return mutator


def _drop_conditional_rule_key(key: str):
    def mutator(document: dict) -> None:
        rule = _valid_conditional_rule()
        del rule[key]
        document["x-conditional-min-items"] = [rule]

    return mutator


MUTATIONS.update(
    {
        "conditional-not-list": _set_conditional_rules("probe_id"),
        "conditional-empty-list": _set_conditional_rules([]),
        "conditional-rule-not-dict": _set_conditional_rules(["strict"]),
        "conditional-rule-missing-key": _drop_conditional_rule_key("min_items"),
        "conditional-rule-extra-key": _mutate_conditional_rule(extra=1),
        "conditional-when-undeclared": _mutate_conditional_rule(
            when_property="missing"
        ),
        "conditional-when-equals-not-list": _mutate_conditional_rule(
            when_equals="strict"
        ),
        "conditional-when-equals-empty": _mutate_conditional_rule(when_equals=[]),
        "conditional-then-undeclared": _mutate_conditional_rule(
            then_property="missing"
        ),
        "conditional-then-not-array": _mutate_conditional_rule(
            then_property="probe_id"
        ),
        "conditional-min-items-zero": _mutate_conditional_rule(min_items=0),
        "conditional-min-items-string": _mutate_conditional_rule(min_items="1"),
        "conditional-min-items-bool": _mutate_conditional_rule(min_items=True),
        "conditional-min-items-float": _mutate_conditional_rule(min_items=1.5),
        "conditional-on-array": _set(
            ("properties", "tags", "x-conditional-min-items"),
            [_valid_conditional_rule()],
        ),
    }
)


class SchemaDefinitionMutationTest(unittest.TestCase):
    def test_base_schema_is_valid(self) -> None:
        record = _load_with(BASE_SCHEMA)
        self.assertEqual(record.schema_id, "x-probe/v1")

    def test_every_mutation_fails_closed(self) -> None:
        for name, mutator in MUTATIONS.items():
            document = copy.deepcopy(BASE_SCHEMA)
            mutator(document)
            with self.subTest(mutation=name):
                try:
                    _load_with(document)
                except SchemaDefinitionError:
                    pass
                except Exception as exc:  # noqa: BLE001 - message is the point
                    self.fail(
                        f"mutation {name} leaked {type(exc).__name__} "
                        f"instead of SchemaDefinitionError: {exc}"
                    )
                else:
                    self.fail(f"mutation {name} was silently accepted")


class BoundaryKeywordIntegerSemanticsTest(unittest.TestCase):
    """Draft 2020-12: integer bounds accept any zero-fraction number.

    ``1.0`` in a schema file parses as ``Decimal("1.0")`` and is a legal
    bound (normalized to plain ``int`` at load); the reject side
    (``1.5``, negatives, booleans) is covered by MUTATIONS above.
    """

    def test_zero_fraction_bounds_accepted(self) -> None:
        # Bounds chosen so the base VALID_RECORD still satisfies them
        # ("p1" has length 2; tags is absent).
        for keyword, owner, bound in (
            ("minLength", "probe_id", 1.0),
            ("maxLength", "probe_id", 2.0),
            ("minItems", "tags", 1.0),
            ("maxItems", "tags", 1.0),
        ):
            document = copy.deepcopy(BASE_SCHEMA)
            document["properties"][owner][keyword] = bound  # -> Decimal
            with self.subTest(keyword=keyword):
                record = _load_with(document)
                self.assertEqual(record.schema_id, "x-probe/v1")

    def test_zero_fraction_bound_is_enforced_after_normalization(self) -> None:
        # minLength: 2.0 must actually constrain as the integer 2.
        document = copy.deepcopy(BASE_SCHEMA)
        document["properties"]["probe_id"]["minLength"] = 2.0
        with self.assertRaises(RecordValidationError):
            _load_with(document, '{"schema": "x-probe/v1", "probe_id": "x"}')

    def test_conditional_min_items_zero_fraction_accepted(self) -> None:
        document = copy.deepcopy(BASE_SCHEMA)
        rule = _valid_conditional_rule()
        rule["min_items"] = 2.0  # -> Decimal("2.0"), normalized to 2
        document["x-conditional-min-items"] = [rule]
        record = _load_with(document)
        self.assertEqual(record.schema_id, "x-probe/v1")
        # And the normalized bound must still gate: discriminator matched,
        # target array too short.
        with self.assertRaises(RecordValidationError):
            _load_with(
                document,
                '{"schema": "x-probe/v1", "probe_id": "strict", "tags": ["only"]}',
            )


class ExtensionKeywordBehaviorTest(unittest.TestCase):
    def test_at_least_one_of_enforced(self) -> None:
        document = copy.deepcopy(BASE_SCHEMA)
        document["properties"]["meta"]["x-at-least-one-of"] = ["a", "b"]
        document["properties"]["meta"]["properties"] = {
            "a": {"type": "string"},
            "b": {"type": "string"},
        }
        with self.assertRaises(RecordValidationError) as ctx:
            _load_with(document, '{"schema": "x-probe/v1", "probe_id": "p1", "meta": {}}')
        self.assertTrue(any("at least one" in v for v in ctx.exception.violations))
        record = _load_with(
            document, '{"schema": "x-probe/v1", "probe_id": "p1", "meta": {"a": "x"}}'
        )
        self.assertEqual(record.schema_id, "x-probe/v1")

    def test_rfc3339_keyword_is_self_contained(self) -> None:
        # No helper pattern: the extension keyword alone must enforce both
        # the full RFC 3339 shape and real calendar/clock semantics.
        document = copy.deepcopy(BASE_SCHEMA)
        document["properties"]["probe_id"] = {
            "type": "string",
            "x-rfc3339-datetime": True,
        }

        def attempt(stamp: str):
            return _load_with(
                document, json.dumps({"schema": "x-probe/v1", "probe_id": stamp})
            )

        for bad in (
            "2026-99-99T99:99:99+99:99",
            "2026-02-30T10:00:00Z",
            "2026-08-14T23:59:60Z",  # leap seconds are not accepted
            "2026-08-14T07:00:00+24:00",
            "2026-08-14",  # bare date: seconds and offset are mandatory
            "2026-08-14 07:00:00Z",  # space separator is not RFC 3339
        ):
            with self.subTest(stamp=bad), self.assertRaises(RecordValidationError):
                attempt(bad)
        for good in ("2026-08-14T07:00:00Z", "2026-08-14T07:00:00.5+08:00"):
            with self.subTest(stamp=good):
                self.assertEqual(attempt(good).schema_id, "x-probe/v1")

    def test_pattern_uses_standard_search_semantics(self) -> None:
        # Draft 2020-12: pattern is an unanchored search, not a fullmatch.
        document = copy.deepcopy(BASE_SCHEMA)
        document["properties"]["probe_id"] = {"type": "string", "pattern": "needle"}
        record = _load_with(
            document, '{"schema": "x-probe/v1", "probe_id": "hay-needle-stack"}'
        )
        self.assertEqual(record.schema_id, "x-probe/v1")
        with self.assertRaises(RecordValidationError):
            _load_with(document, '{"schema": "x-probe/v1", "probe_id": "hay-stack"}')

    def test_exact_length_combines_pattern_with_length_keywords(self) -> None:
        # "$" alone matches just before a trailing newline; the exact-length
        # contract comes from minLength/maxLength, not from pattern.
        document = copy.deepcopy(BASE_SCHEMA)
        document["properties"]["probe_id"] = {
            "type": "string",
            "pattern": "^[0-9a-f]{4}$",
            "minLength": 4,
            "maxLength": 4,
        }
        for bad in ("abcd\n", "abc", "abcde", "ABCD", "abcd "):
            with self.subTest(value=bad), self.assertRaises(RecordValidationError):
                _load_with(document, json.dumps({"schema": "x-probe/v1", "probe_id": bad}))
        record = _load_with(document, '{"schema": "x-probe/v1", "probe_id": "0a9f"}')
        self.assertEqual(record.schema_id, "x-probe/v1")

    def test_conditional_min_items_enforced(self) -> None:
        document = copy.deepcopy(BASE_SCHEMA)
        document["x-conditional-min-items"] = [_valid_conditional_rule()]
        for bad in (
            {"schema": "x-probe/v1", "probe_id": "strict"},
            {"schema": "x-probe/v1", "probe_id": "strict", "tags": []},
        ):
            with self.subTest(record=bad), self.assertRaises(RecordValidationError):
                _load_with(document, json.dumps(bad))
        for good in (
            {"schema": "x-probe/v1", "probe_id": "strict", "tags": ["t1"]},
            {"schema": "x-probe/v1", "probe_id": "relaxed"},
        ):
            with self.subTest(record=good):
                record = _load_with(document, json.dumps(good))
                self.assertEqual(record.schema_id, "x-probe/v1")

    def test_safe_relative_path_enforced(self) -> None:
        good = _load_with(
            BASE_SCHEMA,
            '{"schema": "x-probe/v1", "probe_id": "p1", "locator": "a/b.json"}',
        )
        self.assertEqual(good.schema_id, "x-probe/v1")
        with self.assertRaises(RecordValidationError):
            _load_with(
                BASE_SCHEMA,
                '{"schema": "x-probe/v1", "probe_id": "p1", "locator": "a\\\\b"}',
            )


class JsonEqualityTest(unittest.TestCase):
    """Draft 2020-12 equality over the exact-decimal numeric model:
    bool is not number; numbers compare by exact value (``1 == 1.0 == 1e0``,
    ``10**24 == 1e24``); arrays and objects compare recursively. Probe values
    are raw JSON text so the literal form under test is exact."""

    def _document(self, probe_schema: dict) -> dict:
        document = copy.deepcopy(BASE_SCHEMA)
        document["properties"]["probe_id"] = probe_schema
        return document

    def _attempt(self, document: dict, probe_json: str, extra_fields: str = ""):
        text = '{"schema": "x-probe/v1", "probe_id": %s%s}' % (
            probe_json,
            extra_fields,
        )
        return _load_with(document, text)

    def test_const_integer_matches_float_by_mathematical_value(self) -> None:
        document = self._document({"const": 1})
        for good in ("1", "1.0", "1e0"):
            with self.subTest(value=good):
                self.assertEqual(
                    self._attempt(document, good).schema_id, "x-probe/v1"
                )
        with self.assertRaises(RecordValidationError):
            self._attempt(document, "2")

    def test_const_bool_is_not_a_number(self) -> None:
        document = self._document({"const": True})
        self.assertEqual(self._attempt(document, "true").schema_id, "x-probe/v1")
        for bad in ("1", "1.0"):
            with self.subTest(value=bad), self.assertRaises(RecordValidationError):
                self._attempt(document, bad)

    def test_const_nested_object_bool_not_confused_with_int(self) -> None:
        document = self._document({"const": {"flag": True}})
        record = self._attempt(document, '{"flag": true}')
        self.assertEqual(record.schema_id, "x-probe/v1")
        with self.assertRaises(RecordValidationError):
            self._attempt(document, '{"flag": 1}')

    def test_enum_nested_array_bool_not_confused_with_int(self) -> None:
        document = self._document({"enum": [[True]]})
        self.assertEqual(self._attempt(document, "[true]").schema_id, "x-probe/v1")
        with self.assertRaises(RecordValidationError):
            self._attempt(document, "[1]")

    def test_enum_number_matches_across_int_and_float(self) -> None:
        document = self._document({"enum": [1, "x"]})
        for good in ("1", "1.0", '"x"'):
            with self.subTest(value=good):
                self.assertEqual(
                    self._attempt(document, good).schema_id, "x-probe/v1"
                )
        with self.assertRaises(RecordValidationError):
            self._attempt(document, "true")

    def test_const_large_integer_matches_scientific_literal(self) -> None:
        # const is the integer 10**24; the literal 1e24 parses to the exact
        # same decimal value and must match, while 10**24 + 10**8 must not.
        document = self._document({"const": 10**24})
        for good in ("1e24", "1000000000000000000000000", "1000000000000000000000000.0"):
            with self.subTest(value=good):
                self.assertEqual(
                    self._attempt(document, good).schema_id, "x-probe/v1"
                )
        with self.assertRaises(RecordValidationError):
            self._attempt(document, "1.0000000000000001e24")

    def test_integer_type_accepts_zero_fraction_number(self) -> None:
        # Draft 2020-12: integer matches any number with zero fractional part.
        document = self._document({"type": "integer"})
        for good in ("1", "1.0", "1e2", "-0.0"):
            with self.subTest(value=good):
                self.assertEqual(
                    self._attempt(document, good).schema_id, "x-probe/v1"
                )
        for bad in ("1.5", "true", '"1"'):
            with self.subTest(value=bad), self.assertRaises(RecordValidationError):
                self._attempt(document, bad)

    def test_conditional_rule_fires_on_mathematically_equal_float(self) -> None:
        document = copy.deepcopy(BASE_SCHEMA)
        document["properties"]["mode"] = {"type": "number"}
        document["x-conditional-min-items"] = [
            {
                "when_property": "mode",
                "when_equals": [1],
                "then_property": "tags",
                "min_items": 1,
            }
        ]
        # 1.0 is mathematically equal to the discriminator 1: the gate fires.
        with self.assertRaises(RecordValidationError):
            self._attempt(document, '"p"', ', "mode": 1.0')
        self.assertEqual(
            self._attempt(document, '"p"', ', "mode": 1.0, "tags": ["t"]').schema_id,
            "x-probe/v1",
        )
        # A non-matching value does not fire the gate.
        self.assertEqual(
            self._attempt(document, '"p"', ', "mode": 2.0').schema_id, "x-probe/v1"
        )

    def test_conditional_rule_fires_on_large_equal_number(self) -> None:
        document = copy.deepcopy(BASE_SCHEMA)
        document["properties"]["mode"] = {"type": "number"}
        document["x-conditional-min-items"] = [
            {
                "when_property": "mode",
                "when_equals": [10**24],
                "then_property": "tags",
                "min_items": 1,
            }
        ]
        # 1e24 is exactly 10**24 in the decimal model: the gate fires.
        with self.assertRaises(RecordValidationError):
            self._attempt(document, '"p"', ', "mode": 1e24')
        self.assertEqual(
            self._attempt(document, '"p"', ', "mode": 1e24, "tags": ["t"]').schema_id,
            "x-probe/v1",
        )
        # 10**24 + 10**8 does not fire the gate (a binary float would fold
        # it into the same value as 1e24).
        self.assertEqual(
            self._attempt(
                document, '"p"', ', "mode": 1.0000000000000001e24'
            ).schema_id,
            "x-probe/v1",
        )


if __name__ == "__main__":
    unittest.main()
