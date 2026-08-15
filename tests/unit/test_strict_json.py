"""Unit tests for the strict JSON loader (no schema dispatch involved)."""

import os
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

from research_evolution.core import StrictJsonError, load_strict_json


class LoadStrictJsonTest(unittest.TestCase):
    def test_str_and_bytes_inputs_are_equivalent(self) -> None:
        text = '{"a": 1, "b": "x"}'
        self.assertEqual(load_strict_json(text), load_strict_json(text.encode("utf-8")))

    def test_utf8_bytes_with_non_ascii(self) -> None:
        data = load_strict_json('{"note": "héllo"}'.encode("utf-8"))
        self.assertEqual(data["note"], "héllo")

    def test_bom_bytes_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_strict_json(b'\xef\xbb\xbf{"a": 1}')

    def test_bom_str_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_strict_json("\ufeff" + '{"a": 1}')

    def test_invalid_utf8_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_strict_json(b'{"a": "\xff\xfe"}')

    def test_empty_and_whitespace_rejected(self) -> None:
        for source in ("", "   ", b""):
            with self.subTest(source=source), self.assertRaises(StrictJsonError):
                load_strict_json(source)

    def test_trailing_garbage_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_strict_json('{"a": 1} trailing')

    def test_top_level_must_be_object(self) -> None:
        for source in ("[1, 2]", '"text"', "42", "true", "null"):
            with self.subTest(source=source), self.assertRaises(StrictJsonError):
                load_strict_json(source)

    def test_duplicate_key_top_level_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_strict_json('{"a": 1, "a": 2}')

    def test_duplicate_key_same_value_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_strict_json('{"a": 1, "a": 1}')

    def test_duplicate_key_nested_object_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_strict_json('{"outer": {"b": 1, "b": 2}}')

    def test_duplicate_key_inside_array_object_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_strict_json('{"items": [{"c": 1, "c": 2}]}')

    def test_non_finite_literals_rejected(self) -> None:
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token), self.assertRaises(StrictJsonError):
                load_strict_json('{"x": %s}' % token)

    def test_large_exponent_literals_are_exact_decimals(self) -> None:
        # Arbitrary-precision decimal model: 1e999 is a finite exact value,
        # not an overflow to infinity.
        for literal in ("1e999", "-1e999"):
            with self.subTest(literal=literal):
                data = load_strict_json('{"x": %s}' % literal)
                self.assertIsInstance(data["x"], Decimal)

    def test_decimal_scale_limit_rejected(self) -> None:
        # Past the CPython-int-derived scale cap, canonicalization would
        # amplify into gigantic strings, so the literal fails closed.
        for literal in ("1e4300", "1e-4300", "1e9999"):
            with self.subTest(literal=literal), self.assertRaises(StrictJsonError):
                load_strict_json('{"x": %s}' % literal)

    def test_tiny_literal_does_not_underflow_to_zero(self) -> None:
        data = load_strict_json('{"x": 1e-999}')
        self.assertNotEqual(data["x"], 0)
        self.assertEqual(data["x"], Decimal("1e-999"))

    def test_large_exponent_nested_in_array(self) -> None:
        data = load_strict_json('{"x": [1, [2, [1e999]]]}')
        self.assertIsInstance(data["x"][1][1][0], Decimal)
        with self.assertRaises(StrictJsonError):
            load_strict_json('{"x": [1e9999]}')

    def test_unicode_digits_rejected_in_number_positions(self) -> None:
        # RFC 8259 digits are ASCII 0-9 only; Python's \d also matches
        # Unicode decimal digits, so each number position gets an explicit
        # regression (Arabic-Indic and full-width forms).
        for text in (
            '{"x": 1٢}',  # integer tail
            '{"x": 0.١}',  # fraction part
            '{"x": 1e٢}',  # exponent part
            '{"x": ١٢}',  # leading digits
            '{"x": 1２}',  # integer tail (full-width)
            '{"x": 0.１}',  # fraction part (full-width)
            '{"x": 1e２}',  # exponent part (full-width)
        ):
            with self.subTest(text=text), self.assertRaises(StrictJsonError):
                load_strict_json(text)

    def test_unicode_digits_in_strings_accepted(self) -> None:
        # Only the number grammar is ASCII-restricted; string content keeps
        # the full Unicode range.
        data = load_strict_json('{"s": "١٢٣４５"}')
        self.assertEqual(data["s"], "١٢٣４５")

    def test_control_character_in_string_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_strict_json('{"a": "b\x01c"}')

    def test_deep_nesting_fails_closed(self) -> None:
        # 2000 levels exceed the parser's own frozen container budget; the
        # failure is StrictJsonError, never a bare RecursionError, and no
        # process-global recursion limit is touched.
        with self.assertRaises(StrictJsonError):
            load_strict_json("[" * 2000 + "]" * 2000)

    def test_moderate_nesting_above_walk_limit_rejected(self) -> None:
        # 600 levels exceed the frozen container budget of 500.
        with self.assertRaises(StrictJsonError):
            load_strict_json('{"x": ' + "[" * 600 + "1" + "]" * 600 + "}")

    def test_unsupported_source_type_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_strict_json(123)  # type: ignore[arg-type]

    def test_valid_document_returns_dict(self) -> None:
        data = load_strict_json('{"a": [1, 2.5, "x", true, null], "b": {}}')
        self.assertEqual(data, {"a": [1, 2.5, "x", True, None], "b": {}})
        self.assertIsInstance(data["a"][0], int)
        self.assertIsInstance(data["a"][1], Decimal)

    def test_lone_surrogate_in_string_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_strict_json('{"a": "\\ud800"}')

    def test_lone_surrogate_in_key_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_strict_json('{"\\udfff": 1}')

    def test_valid_surrogate_pair_accepted(self) -> None:
        data = load_strict_json('{"a": "\\ud83d\\ude00"}')
        self.assertEqual(data["a"], "\U0001f600")

    def test_huge_integer_digit_limit_fails_closed(self) -> None:
        # The frozen protocol limit (4300 digits) applies regardless of the
        # runtime digit configuration; see FrozenNumericProtocolTest.
        digits = 4300 + 100
        with self.assertRaises(StrictJsonError):
            load_strict_json('{"x": ' + "1" * digits + "}")


class FrozenNumericProtocolTest(unittest.TestCase):
    """The numeric wire-format contract must not depend on the runtime
    PYTHONINTMAXSTRDIGITS setting; verified in a fresh subprocess."""

    _PROBE = Path(__file__).with_name("_frozen_protocol_probe.py")
    _SRC = Path(__file__).resolve().parents[2] / "src"

    def _run_probe(self, digit_setting: str) -> str:
        env = dict(os.environ)
        env["PYTHONINTMAXSTRDIGITS"] = digit_setting
        env["PYTHONPATH"] = str(self._SRC)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", str(self._PROBE)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"probe failed (cap={digit_setting}): {result.stdout} {result.stderr}",
        )
        return result.stdout

    def test_protocol_stable_with_digit_cap_disabled(self) -> None:
        self.assertIn("FROZEN-OK", self._run_probe("0"))

    def test_protocol_stable_with_low_digit_cap(self) -> None:
        # 640 is the smallest non-zero value CPython accepts for the knob;
        # the 700-digit probe case exceeds it and must still parse exactly.
        self.assertIn("FROZEN-OK", self._run_probe("640"))


class RecursionLimitStressTest(unittest.TestCase):
    """Concurrency stress at low/high caller recursion limits: in-budget
    deep inputs are accepted, over-budget inputs fail closed, solo and
    under a two-thread barrier bracket, with zero recursion-limit drift.

    This is a stress harness — the barriers cannot deterministically force
    overlapped parsing. The deterministic root-cause regression is
    NoGlobalRecursionStateTest below. Verified in fresh subprocesses."""

    _PROBE = Path(__file__).with_name("_frozen_protocol_probe.py")
    _SRC = Path(__file__).resolve().parents[2] / "src"

    def _run_probe(self, limit: int) -> str:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self._SRC)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", str(self._PROBE), "stress", str(limit)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"probe failed (limit={limit}): {result.stdout} {result.stderr}",
        )
        return result.stdout

    def test_stress_at_low_recursion_limit(self) -> None:
        # 300 is below the protocol walk budget of 500: the kernel's own
        # iterative parser must accept in-budget records here exactly as at
        # higher limits, without touching the process recursion limit.
        self.assertIn("STRESS-OK", self._run_probe(300))

    def test_stress_at_high_recursion_limit(self) -> None:
        self.assertIn("STRESS-OK", self._run_probe(2000))


class NoGlobalRecursionStateTest(unittest.TestCase):
    """Deterministic root-cause regression: sys.getrecursionlimit and
    sys.setrecursionlimit are replaced with fail-on-call probes before the
    kernel is imported, with the real limit pinned at 100. Any kernel read
    or modification of the process-global recursion limit fails the probe.
    A bump/restore implementation would be killed deterministically."""

    _PROBE = Path(__file__).with_name("_frozen_protocol_probe.py")
    _SRC = Path(__file__).resolve().parents[2] / "src"

    def test_kernel_never_touches_process_recursion_limit(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self._SRC)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", str(self._PROBE), "noglobal"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"noglobal probe failed: {result.stdout} {result.stderr}",
        )
        self.assertIn("NOGLOBAL-OK", result.stdout)


class StdlibScannerParityTest(unittest.TestCase):
    """The kernel parser no longer consumes stdlib json; prove behavioral
    parity against reference semantics under both the C scanner and the
    pure-Python scanner, so scanner choice cannot change verdicts."""

    _PROBE = Path(__file__).with_name("_frozen_protocol_probe.py")
    _SRC = Path(__file__).resolve().parents[2] / "src"

    def test_parity_with_stdlib_scanners(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self._SRC)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", str(self._PROBE), "parity"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"parity probe failed: {result.stdout} {result.stderr}",
        )
        self.assertIn("PARITY-OK", result.stdout)
        # Both stdlib scanners must actually be exercised on this runtime.
        self.assertIn("scanners=python,c", result.stdout)


if __name__ == "__main__":
    unittest.main()
