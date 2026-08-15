"""Unit tests for canonical serialization and SHA-256 hashing."""

import unittest
from decimal import Decimal

from research_evolution.core import StrictJsonError, canonical_bytes, canonical_sha256

# Golden vectors, computed once and pinned to detect any algorithm drift.
GOLDEN_VALUE = {"b": 1, "a": [True, None, "é"]}
GOLDEN_BYTES = b'{"a":[true,null,"\xc3\xa9"],"b":1}'
GOLDEN_SHA256 = "17c8c6f7f948ee1c9b93b1bc35f6edc29cbaf3022bff7d076d1c4831dd8a44a2"


class CanonicalBytesTest(unittest.TestCase):
    def test_golden_bytes(self) -> None:
        self.assertEqual(canonical_bytes(GOLDEN_VALUE), GOLDEN_BYTES)

    def test_golden_sha256(self) -> None:
        self.assertEqual(canonical_sha256(GOLDEN_VALUE), GOLDEN_SHA256)

    def test_key_order_invariant(self) -> None:
        left = {"a": 1, "b": {"x": 1, "y": 2}, "c": [1, 2]}
        right = {"c": [1, 2], "b": {"y": 2, "x": 1}, "a": 1}
        self.assertEqual(canonical_bytes(left), canonical_bytes(right))
        self.assertEqual(canonical_sha256(left), canonical_sha256(right))

    def test_array_order_is_significant(self) -> None:
        self.assertNotEqual(canonical_bytes([1, 2]), canonical_bytes([2, 1]))

    def test_no_insignificant_whitespace(self) -> None:
        output = canonical_bytes({"a": 1, "b": [1, 2]})
        self.assertNotIn(b" ", output)
        self.assertEqual(output, b'{"a":1,"b":[1,2]}')

    def test_non_ascii_is_utf8_not_escaped(self) -> None:
        output = canonical_bytes({"k": "é中"})
        self.assertIn("é中".encode("utf-8"), output)
        self.assertNotIn(b"\\u", output)

    def test_no_trailing_newline(self) -> None:
        self.assertFalse(canonical_bytes({"a": 1}).endswith(b"\n"))

    def test_boolean_and_null_lowercase(self) -> None:
        self.assertEqual(canonical_bytes({"t": True, "n": None}), b'{"n":null,"t":true}')

    def test_non_finite_rejected(self) -> None:
        for bad in (float("inf"), float("-inf"), float("nan")):
            with self.subTest(bad=bad), self.assertRaises(StrictJsonError):
                canonical_bytes({"x": bad})

    def test_unserializable_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            canonical_bytes({"x": object()})

    def test_non_string_object_keys_rejected(self) -> None:
        # json.dumps would silently coerce these keys to strings, folding
        # distinct inputs into identical canonical bytes; the kernel refuses.
        for bad in ({1: "x"}, {True: "x"}, {1.5: "x"}, {None: "x"}, {"a": {2: "x"}}):
            with self.subTest(bad=bad), self.assertRaises(StrictJsonError):
                canonical_bytes(bad)

    def test_non_list_sequences_rejected(self) -> None:
        # json.dumps would silently coerce tuples to arrays.
        for bad in ((1, 2), {"a": (1,)}, [{"b": (2, 3)}]):
            with self.subTest(bad=bad), self.assertRaises(StrictJsonError):
                canonical_bytes(bad)

    def test_other_non_json_types_rejected(self) -> None:
        for bad in ({"x": {1, 2}}, {"x": b"bytes"}, {"x": range(3)}):
            with self.subTest(bad=bad), self.assertRaises(StrictJsonError):
                canonical_bytes(bad)

    def test_lone_surrogate_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            canonical_bytes({"x": "\ud800"})

    def test_hash_is_stable_across_calls(self) -> None:
        value = {"schema": "x", "items": [1, 2, 3], "nested": {"z": 0, "a": 1}}
        self.assertEqual(canonical_sha256(value), canonical_sha256(value))
        self.assertEqual(len(canonical_sha256(value)), 64)

    def test_decimal_canonical_form(self) -> None:
        cases = {
            Decimal("0.10"): "0.1",
            Decimal("1.0"): "1",
            Decimal("1E+2"): "100",
            Decimal("-0.0"): "0",
            Decimal("1E-7"): "0.0000001",
            Decimal("9007199254740993.0"): "9007199254740993",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(
                    canonical_bytes({"x": value}),
                    ('{"x":' + expected + "}").encode("utf-8"),
                )

    def test_float_and_decimal_agree_on_canonical_text(self) -> None:
        self.assertEqual(
            canonical_bytes({"x": 0.1}), canonical_bytes({"x": Decimal("0.1")})
        )

    def test_integral_decimal_canonicalizes_like_integer(self) -> None:
        self.assertEqual(
            canonical_bytes({"x": Decimal("1.0")}), canonical_bytes({"x": 1})
        )

    def test_non_finite_decimal_rejected(self) -> None:
        for bad in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with self.subTest(bad=bad), self.assertRaises(StrictJsonError):
                canonical_bytes({"x": bad})

    def test_adjacent_large_decimals_do_not_collide(self) -> None:
        # A binary-float pipeline folds these two distinct values into one;
        # the exact-decimal pipeline must keep their hashes distinct.
        self.assertNotEqual(
            canonical_sha256({"x": Decimal("9007199254740992.0")}),
            canonical_sha256({"x": Decimal("9007199254740993.0")}),
        )

    def test_deep_nesting_uses_iterative_serializer(self) -> None:
        # 498 nested levels: within the data budget (500), and far beyond
        # what a recursive serializer with generator frames would survive.
        value: list = [1]
        for _ in range(497):
            value = [value]
        self.assertTrue(canonical_bytes(value).startswith(b"[["))

    def test_huge_programmatic_int_rejected(self) -> None:
        # Frozen protocol digit limit, independent of the runtime int<->str
        # conversion cap; must not leak a bare ValueError either.
        with self.assertRaises(StrictJsonError):
            canonical_bytes({"x": 10**5000})

    def test_huge_programmatic_decimal_scale_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            canonical_bytes({"x": Decimal("1e9999")})


if __name__ == "__main__":
    unittest.main()
