"""Unit tests for the E3 replay envelope and deterministic replay runner
(ADR-0006 decisions 3-4)."""

import hashlib
import json
import re
import unittest
from pathlib import Path

from research_evolution.core import canonical_bytes, canonical_sha256
from research_evolution.evaluation import (
    ERROR_CLASSES,
    Envelope,
    ReplayResult,
    run_replay,
    runner_identity,
)
from tests.contract.test_core_schemas_contract import _BANNED_TERMS

EVALUATION_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "research_evolution"
    / "evaluation"
)
RUN_SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "schemas"
    / "core"
    / "evaluation-run-v1.schema.json"
)

# Imports the offline runner must never make (ADR-0006 decision 4: no
# network, no subprocess, no process-environment access).
_BANNED_IMPORTS = re.compile(
    r"^\s*(?:import|from)\s+"
    r"(?:socket|urllib|requests|httpx|http|ssl|subprocess|ctypes|asyncio)\b",
    re.MULTILINE,
)

ARTIFACT_OBJ = {"answer": 42, "trace": ["step-1", "step-2"]}


def _artifact() -> bytes:
    return canonical_bytes(ARTIFACT_OBJ)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _envelope(**overrides) -> Envelope:
    params = {"timeout_ms": 1000, "max_output_bytes": 1 << 20}
    params.update(overrides)
    return Envelope(**params)


class EnvelopeTest(unittest.TestCase):
    def test_defaults_and_normalization(self) -> None:
        envelope = _envelope(retry_on=("runner_error", "parse_error", "runner_error"))
        self.assertEqual(envelope.retry_attempts, 0)
        self.assertIsNone(envelope.seed)
        # retry_on is deduplicated and sorted: the same policy hashes the same
        self.assertEqual(envelope.retry_on, ("parse_error", "runner_error"))

    def test_to_dict_omits_unset_optional_fields(self) -> None:
        payload = _envelope().to_dict()
        self.assertNotIn("seed", payload)
        self.assertNotIn("notes", payload)
        full = _envelope(seed=7, notes="smoke").to_dict()
        self.assertEqual(full["seed"], 7)
        self.assertEqual(full["notes"], "smoke")

    def test_canonical_hash_is_stable_and_order_insensitive(self) -> None:
        first = _envelope(retry_on=("runner_error", "parse_error"))
        second = _envelope(retry_on=("parse_error", "runner_error"))
        self.assertEqual(first.canonical_sha256, second.canonical_sha256)
        self.assertNotEqual(
            first.canonical_sha256, _envelope(timeout_ms=2000).canonical_sha256
        )

    def test_field_validation(self) -> None:
        with self.assertRaises(ValueError):
            _envelope(timeout_ms=0)
        with self.assertRaises(ValueError):
            _envelope(timeout_ms=True)
        with self.assertRaises(ValueError):
            _envelope(max_output_bytes=-1)
        with self.assertRaises(ValueError):
            _envelope(retry_attempts=-1)
        with self.assertRaises(ValueError):
            _envelope(retry_on=("unknown_class",))
        with self.assertRaises(ValueError):
            _envelope(seed=True)
        self.assertEqual(_envelope(seed=7).seed, 7)


class ReplayRunnerTest(unittest.TestCase):
    def test_runner_identity_shape(self) -> None:
        self.assertEqual(
            runner_identity(), {"tool": "replay-runner", "version": "0.1.0"}
        )

    def test_happy_path_replay(self) -> None:
        artifact = _artifact()
        result = run_replay(artifact, _sha(artifact), _envelope())
        self.assertTrue(result.ok, result)
        self.assertEqual(result.attempts, 1)
        self.assertIsNone(result.error_class)
        self.assertEqual(result.output_bytes, artifact)
        self.assertEqual(result.output_sha256, canonical_sha256(ARTIFACT_OBJ))

    def test_integrity_mismatch_is_runner_error(self) -> None:
        artifact = _artifact()
        result = run_replay(artifact, "0" * 64, _envelope())
        self.assertFalse(result.ok)
        self.assertEqual(result.error_class, "runner_error")
        self.assertIn("0" * 64, result.error_detail)
        self.assertIn(_sha(artifact), result.error_detail)

    def test_oversize_artifact_is_output_limit(self) -> None:
        artifact = b"x" * 100
        result = run_replay(artifact, _sha(artifact), _envelope(max_output_bytes=10))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_class, "output_limit")
        self.assertIn("100", result.error_detail)
        self.assertIn("10", result.error_detail)

    def test_invalid_json_is_parse_error(self) -> None:
        artifact = b"{not json"
        result = run_replay(artifact, _sha(artifact), _envelope())
        self.assertFalse(result.ok)
        self.assertEqual(result.error_class, "parse_error")

    def test_top_level_array_is_parse_error(self) -> None:
        artifact = b"[1, 2]"
        result = run_replay(artifact, _sha(artifact), _envelope())
        self.assertFalse(result.ok)
        self.assertEqual(result.error_class, "parse_error")

    def test_timeout_via_injected_clock(self) -> None:
        artifact = _artifact()
        ticks = iter([0.0, 2000.0])
        result = run_replay(
            artifact,
            _sha(artifact),
            _envelope(timeout_ms=1000),
            clock=lambda: next(ticks),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error_class, "timeout")
        self.assertEqual(result.attempts, 1)

    def test_retry_respects_policy(self) -> None:
        artifact = _artifact()
        # retryable class: retried exactly retry_attempts extra times
        result = run_replay(
            artifact,
            "0" * 64,
            _envelope(retry_attempts=2, retry_on=("runner_error",)),
        )
        self.assertEqual(result.attempts, 3)
        self.assertEqual(result.error_class, "runner_error")
        # non-retryable class: single attempt despite retry_attempts > 0
        result = run_replay(
            artifact, "0" * 64, _envelope(retry_attempts=2, retry_on=("timeout",))
        )
        self.assertEqual(result.attempts, 1)
        # retry_attempts=0: single attempt even when the class is retryable
        result = run_replay(
            artifact,
            "0" * 64,
            _envelope(retry_attempts=0, retry_on=("runner_error",)),
        )
        self.assertEqual(result.attempts, 1)

    def test_replay_is_deterministic(self) -> None:
        artifact = _artifact()
        first = run_replay(artifact, _sha(artifact), _envelope(seed=7))
        second = run_replay(artifact, _sha(artifact), _envelope(seed=7))
        self.assertEqual(first, second)
        failure_first = run_replay(artifact, "0" * 64, _envelope())
        failure_second = run_replay(artifact, "0" * 64, _envelope())
        self.assertEqual(failure_first, failure_second)


class EvaluationStaticDisciplineTest(unittest.TestCase):
    def test_error_taxonomy_matches_run_schema(self) -> None:
        schema = json.loads(RUN_SCHEMA.read_text(encoding="utf-8"))
        enum = set(schema["properties"]["error_class"]["enum"])
        self.assertEqual(enum, set(ERROR_CLASSES))

    def test_evaluation_package_makes_no_banned_imports(self) -> None:
        for path in sorted(EVALUATION_ROOT.glob("*.py")):
            with self.subTest(module=path.name):
                match = _BANNED_IMPORTS.search(path.read_text(encoding="utf-8"))
                self.assertIsNone(match)

    def test_evaluation_package_is_domain_neutral(self) -> None:
        # The evaluator is generic infrastructure, not an adapter: the core
        # domain-neutrality discipline (tests/contract _BANNED_TERMS) applies.
        for path in sorted(EVALUATION_ROOT.glob("*.py")):
            with self.subTest(module=path.name):
                match = _BANNED_TERMS.search(path.read_text(encoding="utf-8"))
                self.assertIsNone(match)


if __name__ == "__main__":
    unittest.main()
