"""Subprocess probe for frozen-protocol regression tests.

Modes (argv[1]):

- ``digits`` (default): runs with PYTHONINTMAXSTRDIGITS set by the parent;
  prints FROZEN-OK only if the numeric wire-format contract is identical
  to the default-configuration behavior.
- ``stress LIMIT``: concurrency STRESS test at sys recursion limit LIMIT;
  prints STRESS-OK only if in-budget deep inputs are accepted and
  over-budget inputs are rejected with StrictJsonError on both public
  paths, solo and under a two-thread barrier bracket, with zero
  recursion-limit drift. (A stress test: the barriers bracket the parse
  region but cannot deterministically force thread overlap.)
- ``noglobal``: deterministic root-cause regression for the frozen depth
  protocol. sys.getrecursionlimit / sys.setrecursionlimit are replaced
  with fail-on-call probes BEFORE the kernel is imported; the process
  limit is pinned to 100 (below the 500 walk budget). Any kernel read or
  modification of the process-global recursion limit fails the probe.
  Prints NOGLOBAL-OK.
- ``parity``: differential check against the stdlib ``json`` reference
  semantics under both the C scanner and the pure-Python scanner; prints
  PARITY-OK with the scanner list.

Not a unittest module (the filename does not match the discovery pattern
on purpose). Kernel imports are lazy so ``noglobal`` can patch the sys
recursion-limit functions before the kernel module loads.
"""

import os
import sys
import threading
from decimal import Decimal


def _kernel():
    from research_evolution.core import (
        StrictJsonError,
        canonical_bytes,
        load_record,
        load_strict_json,
    )

    return StrictJsonError, canonical_bytes, load_record, load_strict_json


def _nested_task_text(depth: int) -> str:
    """A valid research-task/v1 document with ``depth`` nested objects under
    the free-form ``domain_context`` extension point."""
    inner = '"v": 1'
    for _ in range(depth):
        inner = '"x": {%s}' % inner
    return (
        '{"schema": "research-task/v1", "task_id": "t-deep", "title": "deep", '
        '"problem_statement": "p", "domain": "engineering", "scope": {}, '
        '"resources": {}, "completion_criteria": ["c"], "permissions": [], '
        '"allowed_external_effects": [], "created_at": "2026-08-14T07:00:00Z", '
        '"domain_context": {%s}}' % inner
    )


def _programmatic_deep_list(depth: int) -> list:
    value = [1]
    for _ in range(depth - 1):
        value = [value]
    return value


def _expect_accept(label: str, failures: list, call) -> None:
    try:
        call()
    except Exception as exc:
        failures.append(f"{label} -> {type(exc).__name__}: {exc}")


def _expect_strict_reject(label: str, failures: list, call) -> None:
    StrictJsonError, _, _, _ = _kernel()
    try:
        call()
    except StrictJsonError:
        pass
    except Exception as exc:
        failures.append(f"{label} leaked {type(exc).__name__}: {exc}")
    else:
        failures.append(f"{label} accepted an over-budget input")


def run_digit_checks() -> list:
    StrictJsonError, canonical_bytes, _, load_strict_json = _kernel()
    failures = []

    # The runtime knob must actually be in effect, otherwise this probe
    # proves nothing.
    setting = os.environ.get("PYTHONINTMAXSTRDIGITS", "")
    actual = sys.get_int_max_str_digits()
    if setting == "0" and actual != 0:
        failures.append(f"knob ineffective: expected 0, got {actual}")
    if setting == "640" and actual != 640:
        failures.append(f"knob ineffective: expected 640, got {actual}")

    # Fractions stay exact regardless of the runtime digit configuration.
    if load_strict_json('{"x": 0.1}')["x"] != Decimal("0.1"):
        failures.append("0.1 rejected or inexact")
    if load_strict_json('{"x": 1e0}')["x"] != Decimal("1e0"):
        failures.append("1e0 rejected or inexact")
    if load_strict_json('{"x": 1e999}')["x"] != Decimal("1e999"):
        failures.append("1e999 rejected or inexact")

    # Integers inside the frozen 4300-digit protocol limit parse exactly,
    # even past a lower runtime cap (700 digits with the cap at 640).
    for digits, low, high in ((150, 149, 150), (700, 699, 700)):
        value = load_strict_json('{"x": ' + "1" * digits + '}')["x"]
        if not (10**low < value < 10**high):
            failures.append(f"{digits}-digit integer not parsed exactly")

    # Beyond the frozen limit: rejected on every machine, no bare ValueError.
    try:
        load_strict_json('{"x": ' + "1" * 5000 + '}')
    except StrictJsonError:
        pass
    else:
        failures.append("5000-digit integer accepted")

    # Programmatic huge int at the canonical entry: StrictJsonError only.
    try:
        canonical_bytes({"x": 10**5000})
    except StrictJsonError:
        pass
    else:
        failures.append("huge programmatic int canonicalized")

    # The decimal scale limit is frozen as well.
    try:
        load_strict_json('{"x": 1e9999}')
    except StrictJsonError:
        pass
    else:
        failures.append("1e9999 accepted")

    return failures


def _concurrent_rounds(label, failures, rounds, body) -> None:
    """Run ``body(worker_id, round_no)`` in two threads whose rounds are
    bracketed by barriers. This is a stress harness: the barriers bound
    the region but cannot deterministically force overlapped parsing."""
    barrier = threading.Barrier(2)
    errors = []

    def worker(worker_id: int) -> None:
        for round_no in range(rounds):
            try:
                barrier.wait(timeout=30)
                body(worker_id, round_no)
                barrier.wait(timeout=30)
            except Exception as exc:
                errors.append(
                    f"{label} w{worker_id} r{round_no}: "
                    f"{type(exc).__name__}: {exc}"
                )
                break

    threads = [threading.Thread(target=worker, args=(k,)) for k in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    if any(thread.is_alive() for thread in threads):
        failures.append(f"{label}: workers deadlocked")
    failures.extend(errors)


def run_stress_checks(limit: int) -> list:
    StrictJsonError, canonical_bytes, load_record, _ = _kernel()
    failures = []
    sys.setrecursionlimit(limit)
    if sys.getrecursionlimit() != limit:
        return [f"recursion knob ineffective: wanted {limit}"]

    text400 = _nested_task_text(400)
    text600 = _nested_task_text(600)
    list400 = _programmatic_deep_list(400)
    list600 = _programmatic_deep_list(600)

    # Solo verdicts on both public paths.
    try:
        solo_sha = load_record(text400).sha256
    except Exception as exc:
        return [f"solo load_record(400) -> {type(exc).__name__}: {exc}"]
    _expect_accept(f"canonical_bytes(400)@limit={limit}", failures,
                   lambda: canonical_bytes(list400))
    _expect_strict_reject(f"load_record(600)@limit={limit}", failures,
                          lambda: load_record(text600))
    _expect_strict_reject(f"canonical_bytes(600)@limit={limit}", failures,
                          lambda: canonical_bytes(list600))

    # Concurrency stress: every round must reproduce the solo verdicts.
    def body(worker_id: int, round_no: int) -> None:
        record = load_record(text400)
        if record.sha256 != solo_sha:
            raise AssertionError("hash mismatch under concurrency")
        try:
            load_record(text600)
        except StrictJsonError:
            pass
        else:
            raise AssertionError("600 accepted")
        canonical_bytes(list400)

    _concurrent_rounds(f"stress@{limit}", failures, 25, body)

    # The kernel must not drift the process recursion limit either.
    drifted = sys.getrecursionlimit()
    if drifted != limit:
        failures.append(f"recursion limit drifted: {limit} -> {drifted}")
    return failures


def run_noglobal_checks() -> list:
    """Deterministic regression: the kernel must not read or modify the
    process-global recursion limit at all. Both sys functions are replaced
    with fail-on-call probes before the kernel is imported, and the real
    limit is pinned to 100 (below the 500 walk budget) so a secret raise
    would be needed by any implementation that still relied on it."""
    real_get = sys.getrecursionlimit
    real_set = sys.setrecursionlimit
    real_set(100)
    calls = []

    def boom_get():
        calls.append("getrecursionlimit")
        raise AssertionError("kernel read the process recursion limit")

    def boom_set(value):
        calls.append(f"setrecursionlimit({value})")
        raise AssertionError("kernel modified the process recursion limit")

    sys.getrecursionlimit = boom_get
    sys.setrecursionlimit = boom_set
    failures = []
    try:
        StrictJsonError, canonical_bytes, load_record, _ = _kernel()

        text400 = _nested_task_text(400)
        text600 = _nested_task_text(600)
        solo = load_record(text400)
        _expect_accept("noglobal canonical_bytes(400)", failures,
                       lambda: canonical_bytes(_programmatic_deep_list(400)))
        _expect_strict_reject("noglobal load_record(600)", failures,
                              lambda: load_record(text600))
        _expect_strict_reject("noglobal canonical_bytes(600)", failures,
                              lambda: canonical_bytes(_programmatic_deep_list(600)))

        def body(worker_id: int, round_no: int) -> None:
            record = load_record(text400)
            if record.sha256 != solo.sha256:
                raise AssertionError("hash mismatch")

        _concurrent_rounds("noglobal", failures, 15, body)
    except AssertionError as exc:
        failures.append(str(exc))
    finally:
        sys.getrecursionlimit = real_get
        sys.setrecursionlimit = real_set
    if calls:
        failures.append(f"recursion-limit probes fired: {calls}")
    if real_get() != 100:
        failures.append(f"limit drifted: 100 -> {real_get()}")
    real_set(1000)
    return failures


def run_parity_checks() -> tuple:
    """Differential parity against stdlib json under both scanners.

    The kernel parser no longer consumes stdlib json; this corpus proves
    its accept/reject verdicts and produced values match reference
    semantics regardless of which stdlib scanner is in effect.
    """
    import json as stdlib_json
    from json import scanner as stdlib_scanner

    _, _, _, load_strict_json = _kernel()
    from research_evolution.core import StrictJsonError
    failures = []

    def dup_hook(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate key")
            out[key] = value
        return out

    def const_hook(token):
        raise ValueError(f"constant {token}")

    def reference_loads(text, force_python_scanner):
        decoder = stdlib_json.JSONDecoder(
            object_pairs_hook=dup_hook, parse_constant=const_hook
        )
        if force_python_scanner:
            decoder.scan_once = stdlib_scanner.py_make_scanner(decoder)
        return decoder.decode(text)

    def as_decimal(value):
        if isinstance(value, Decimal):
            return value
        if isinstance(value, float):
            return Decimal(repr(value))
        return Decimal(value)

    def same(left, right):
        if isinstance(left, bool) or isinstance(right, bool):
            return isinstance(left, bool) and isinstance(right, bool) and left == right
        if isinstance(left, (int, float, Decimal)) and isinstance(
            right, (int, float, Decimal)
        ):
            return as_decimal(left) == as_decimal(right)
        if isinstance(left, str) and isinstance(right, str):
            return left == right
        if left is None or right is None:
            return left is None and right is None
        if isinstance(left, list) and isinstance(right, list):
            return len(left) == len(right) and all(
                same(item_l, item_r) for item_l, item_r in zip(left, right)
            )
        if isinstance(left, dict) and isinstance(right, dict):
            return set(left) == set(right) and all(
                same(left[key], right[key]) for key in left
            )
        return False

    valid_corpus = [
        '{"a": 1, "b": [0.5, "x", true, null], "c": {}}',
        '{"x": 1e2}',
        '{"x": -0.5}',
        '{"x": 0}',
        '{"x": -0}',
        '{"pair": "\\ud83d\\ude00"}',
        '{"big": 123456789012345678901234567890}',
        '{"esc": "a\\nb\\t\\u0041\\u00e9"}',
        '{"s": "١٢٣"}',
        '{"nested": ' + "[" * 60 + "1" + "]" * 60 + "}",
        '{"empty_arr": [], "empty_obj": {}}',
        '{"key with space": "v", "\\u0061": "decoded-key"}',
    ]
    # Cases where the kernel is intentionally stricter than stdlib
    # (unpaired surrogates, frozen numeric limits) are NOT in this corpus;
    # they are covered by dedicated fail-closed tests instead. Unicode
    # digits ARE included: modern stdlib rejects them too (the \d quirk
    # was fixed in CPython), so parity must hold.
    invalid_corpus = [
        '{"a": 1, "a": 2}',
        '{"a": 1, "\\u0061": 2}',
        '{"x": NaN}',
        '{"x": Infinity}',
        '{"x": -Infinity}',
        '{"x": 01}',
        '{"x": 1٢}',
        '{"x": 0.١}',
        '{"x": 1e٢}',
        '{"x": ١٢}',
        '{"x": 1２}',
        '{"x": 0.１}',
        '{"x": 1e２}',
        '{"a": "b\x01c"}',
        '{"a": 1,}',
        "[1, 2",
        '{"a": 1} trailing',
        "\ufeff" + '{"a": 1}',
        '{"a": "\\x"}',
        '{"a": 1',
        '{"a" 1}',
        '{"a": tru}',
        '[1,]',
    ]

    scanners = ["python"]
    if stdlib_scanner.c_make_scanner is not None:
        scanners.append("c")

    for name in scanners:
        force_py = name == "python"
        for text in valid_corpus:
            try:
                ours = load_strict_json(text)
            except Exception as exc:
                failures.append(f"[{name}] valid rejected by kernel: {exc}")
                continue
            try:
                ref = reference_loads(text, force_py)
            except Exception as exc:
                failures.append(f"[{name}] valid rejected by reference: {exc}")
                continue
            if not same(ours, ref):
                failures.append(f"[{name}] value mismatch: {text[:40]!r}")
        for text in invalid_corpus:
            try:
                load_strict_json(text)
            except StrictJsonError:
                ours_ok = False
            except Exception as exc:
                failures.append(
                    f"[{name}] invalid leaked {type(exc).__name__}: {text[:40]!r}"
                )
                continue
            else:
                ours_ok = True
            try:
                reference_loads(text, force_py)
            except Exception:
                ref_ok = False
            else:
                ref_ok = True
            if ours_ok != ref_ok:
                failures.append(
                    f"[{name}] verdict mismatch: {text[:40]!r} "
                    f"kernel_ok={ours_ok} ref_ok={ref_ok}"
                )

    return failures, scanners


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "digits"
    if mode == "stress":
        limit = int(sys.argv[2])
        failures = run_stress_checks(limit)
        if failures:
            print("PROBE-FAIL:", "; ".join(failures))
            return 1
        print("STRESS-OK")
        return 0
    if mode == "noglobal":
        failures = run_noglobal_checks()
        if failures:
            print("PROBE-FAIL:", "; ".join(failures))
            return 1
        print("NOGLOBAL-OK")
        return 0
    if mode == "parity":
        failures, scanners = run_parity_checks()
        if failures:
            print("PROBE-FAIL:", "; ".join(failures))
            return 1
        print("PARITY-OK scanners=" + ",".join(scanners))
        return 0

    failures = run_digit_checks()
    if failures:
        print("PROBE-FAIL:", "; ".join(failures))
        return 1
    print("FROZEN-OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
