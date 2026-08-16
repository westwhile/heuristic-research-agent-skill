"""Contract tests: fixtures, schema integrity, and domain neutrality.

These tests pin the public contract of the core kernel (Phase 1A–1C):

- the fixture tree on disk and FIXTURE_MANIFEST are compared
  bidirectionally, so an unlisted family/version directory or stray file is a
  test failure;
- every ``valid`` fixture loads; every ``invalid`` fixture raises the
  expected error class with the expected reason substring;
- the canonical hash of every family's minimal fixture is golden-pinned;
- schema files are strict JSON, self-consistent, and free of domain vocabulary.
"""

import re
import unittest
from pathlib import Path

from research_evolution.core import (
    CoreError,
    RecordValidationError,
    SchemaDefinitionError,
    StrictJsonError,
    UnknownSchemaError,
    load_record,
)
from research_evolution.core._schema import SchemaRegistry

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "core"
SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "core"

_ERROR_CLASSES = {
    "StrictJsonError": StrictJsonError,
    "UnknownSchemaError": UnknownSchemaError,
    "RecordValidationError": RecordValidationError,
    "SchemaDefinitionError": SchemaDefinitionError,
}

# invalid fixture name -> (expected error class, expected reason substring).
FIXTURE_MANIFEST = {
    "research-task/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-created-at-month.json": ("RecordValidationError", "created_at"),
            "bad-created-at.json": ("RecordValidationError", "created_at"),
            "bad-id-pattern.json": ("RecordValidationError", "task_id"),
            "duplicate-nested-key.json": ("StrictJsonError", "duplicate"),
            "duplicate-top-level-key.json": ("StrictJsonError", "duplicate"),
            "empty-completion-criteria.json": (
                "RecordValidationError",
                "completion_criteria",
            ),
            "missing-task-id.json": ("RecordValidationError", "task_id"),
            "nan-literal.json": ("StrictJsonError", "non-finite"),
            "number-scale-overflow.json": ("StrictJsonError", "decimal scale"),
            "top-level-array.json": ("StrictJsonError", "top-level"),
            "unicode-digit-exponent.json": ("StrictJsonError", "invalid number"),
            "unicode-digit-fraction.json": ("StrictJsonError", "invalid number"),
            "unicode-digit-integer.json": ("StrictJsonError", "invalid number"),
            "whitespace-title.json": ("RecordValidationError", "title"),
            "wrong-schema-field.json": ("RecordValidationError", "claim_id"),
        },
    },
    "research-claim/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-claim-type.json": ("RecordValidationError", "claim_type"),
            "bad-disposition.json": ("RecordValidationError", "disposition"),
            "bad-evidence-maturity.json": (
                "RecordValidationError",
                "evidence_maturity",
            ),
            "bad-evidence-sha256.json": ("RecordValidationError", "sha256"),
            "duplicate-key-nested.json": ("StrictJsonError", "duplicate"),
            "empty-statement.json": ("RecordValidationError", "statement"),
            "maturity-without-evidence.json": (
                "RecordValidationError",
                "supporting_evidence",
            ),
            "missing-non-entailments.json": ("RecordValidationError", "non_entailments"),
            "supported-no-evidence.json": (
                "RecordValidationError",
                "supporting_evidence",
            ),
            "superseded-no-evidence.json": (
                "RecordValidationError",
                "supporting_evidence",
            ),
            "whitespace-statement.json": ("RecordValidationError", "statement"),
            "withdrawn-no-evidence.json": (
                "RecordValidationError",
                "supporting_evidence",
            ),
        },
    },
    "research-evidence/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-content-sha256-newline.json": (
                "RecordValidationError",
                "content_sha256",
            ),
            "bad-content-sha256.json": ("RecordValidationError", "content_sha256"),
            "bad-input-kind.json": ("RecordValidationError", "kind"),
            "duplicate-key.json": ("StrictJsonError", "duplicate"),
            "empty-claim-ids.json": ("RecordValidationError", "claim_ids"),
            "input-unbound.json": ("RecordValidationError", "at least one"),
            "locator-backslash.json": ("RecordValidationError", "backslash"),
            "locator-device-name.json": ("RecordValidationError", "device name"),
            "locator-dotdot-escape.json": ("RecordValidationError", "'..'"),
            "locator-drive-absolute.json": ("RecordValidationError", "drive-letter"),
            "locator-drive-relative.json": ("RecordValidationError", "drive-letter"),
            "locator-root-absolute.json": ("RecordValidationError", "not allowed"),
            "locator-trailing-dot.json": ("RecordValidationError", "trailing"),
            "locator-unc.json": ("RecordValidationError", "backslash"),
            "missing-content-sha256.json": ("RecordValidationError", "content_sha256"),
            "missing-producer-version.json": ("RecordValidationError", "version"),
            "whitespace-applicability.json": ("RecordValidationError", "applicability"),
        },
    },
    "research-run/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-randomness-mode.json": ("RecordValidationError", "randomness"),
            "bad-task-sha256.json": ("RecordValidationError", "sha256"),
            "empty-environment.json": ("RecordValidationError", "environment"),
            "input-missing-sha256.json": ("RecordValidationError", "sha256"),
            "missing-task-pin.json": ("RecordValidationError", "sha256"),
            "missing-task.json": ("RecordValidationError", "task"),
        },
    },
    "research-failure-observation/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "bad-observed-at.json": ("RecordValidationError", "observed_at"),
            "empty-facts.json": ("RecordValidationError", "facts"),
            "missing-observer-version.json": ("RecordValidationError", "version"),
            "missing-run-pin.json": ("RecordValidationError", "sha256"),
            "root-cause-field.json": ("RecordValidationError", "additional property"),
            "run-ref-not-object.json": ("RecordValidationError", "run"),
        },
    },
    "research-failure-analysis/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-supersedes-pattern.json": ("RecordValidationError", "supersedes"),
            "empty-hypotheses.json": ("RecordValidationError", "hypotheses"),
            "missing-observation-pin.json": ("RecordValidationError", "sha256"),
            "missing-observation.json": ("RecordValidationError", "observation"),
            "whitespace-hypothesis.json": ("RecordValidationError", "hypotheses"),
        },
    },
    "research-case-package/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "empty-runs.json": ("RecordValidationError", "runs"),
            "member-bad-pin.json": ("RecordValidationError", "sha256"),
            "member-missing-pin.json": ("RecordValidationError", "sha256"),
            "missing-privacy-status.json": (
                "RecordValidationError",
                "privacy_review_status",
            ),
            "privacy-not-pending.json": (
                "RecordValidationError",
                "privacy_review_status",
            ),
            "task-as-array.json": ("RecordValidationError", "task"),
        },
    },
}

# Golden pins: canonical SHA-256 of each family's valid/minimal.json fixture.
MINIMAL_FIXTURE_SHA256 = {
    "research-case-package/v1": (
        "d83202cfeafc280b98df1b7d9e0c69be70e1d8681c3c6fbc0e5b252c7a5f2ae5"
    ),
    "research-claim/v1": (
        "a496686fd72c63ee8cba7c3e59281a7575f8ee499798072457e2bcce6796c769"
    ),
    "research-evidence/v1": (
        "a77ec6c1bb747e00d95d5a0d227f6bc0f6f8e9592bd93ca6911978810f09b3a4"
    ),
    "research-failure-analysis/v1": (
        "97143007a8f05ca7e243228f490f8bee23c06323155b3ad68710ae34b4fddeed"
    ),
    "research-failure-observation/v1": (
        "946bd26918fe3ec254be0fa375c0a2090ddde0dffee5d4fb6de9c3d546300ece"
    ),
    "research-run/v1": (
        "f6a3a6273e87f9ac38efc332b98b14b5c9b95ec3f5652567502d7063df8e4c9e"
    ),
    "research-task/v1": (
        "7a73b657e4b3e8ae6250e0a56b0dee7a73b3838ca4bdd637fe58b7d044e7519a"
    ),
}

# Domain vocabulary that must never leak into the domain-neutral core schemas.
_BANNED_TERMS = re.compile(
    r"\b(theorem|proof|factor|backtest|signal|sharpe|drawdown|ohlcv|"
    r"neural|neuron|cuda|gpu|alpha)\b",
    re.IGNORECASE,
)


def _fixture_dir(schema_id: str, kind: str) -> Path:
    family, version = schema_id.split("/")
    return FIXTURES_ROOT / family / version / kind


def _manifest_files() -> set[str]:
    expected: set[str] = set()
    for schema_id, groups in FIXTURE_MANIFEST.items():
        family, version = schema_id.split("/")
        for name in groups["valid"]:
            expected.add(f"{family}/{version}/valid/{name}")
        for name in groups["invalid"]:
            expected.add(f"{family}/{version}/invalid/{name}")
    return expected


class FixtureManifestTest(unittest.TestCase):
    def test_fixture_tree_matches_manifest_bidirectionally(self) -> None:
        on_disk = {
            path.relative_to(FIXTURES_ROOT).as_posix()
            for path in FIXTURES_ROOT.rglob("*")
            if path.is_file()
        }
        self.assertEqual(_manifest_files(), on_disk)

    def test_every_schema_has_valid_and_invalid_fixtures(self) -> None:
        for groups in FIXTURE_MANIFEST.values():
            self.assertGreaterEqual(len(groups["valid"]), 2)
            self.assertGreaterEqual(len(groups["invalid"]), 5)


class FixtureBehaviorTest(unittest.TestCase):
    def test_valid_fixtures_load(self) -> None:
        for schema_id, groups in FIXTURE_MANIFEST.items():
            for name in groups["valid"]:
                path = _fixture_dir(schema_id, "valid") / name
                with self.subTest(fixture=f"{schema_id}/valid/{name}"):
                    record = load_record(path.read_bytes())
                    self.assertEqual(record.schema_id, schema_id)

    def test_invalid_fixtures_fail_with_expected_error(self) -> None:
        for schema_id, groups in FIXTURE_MANIFEST.items():
            for name, (error_name, reason) in groups["invalid"].items():
                path = _fixture_dir(schema_id, "invalid") / name
                with self.subTest(fixture=f"{schema_id}/invalid/{name}"):
                    with self.assertRaises(CoreError) as ctx:
                        load_record(path.read_bytes())
                    self.assertEqual(
                        type(ctx.exception).__name__,
                        error_name,
                        f"wrong error class: {ctx.exception}",
                    )
                    self.assertIn(
                        reason,
                        str(ctx.exception),
                        f"reason substring missing: {ctx.exception}",
                    )

    def test_minimal_fixture_hashes_are_golden_pinned(self) -> None:
        for schema_id, expected in MINIMAL_FIXTURE_SHA256.items():
            path = _fixture_dir(schema_id, "valid") / "minimal.json"
            with self.subTest(fixture=f"{schema_id}/valid/minimal.json"):
                record = load_record(path.read_bytes())
                self.assertEqual(record.sha256, expected)

    def test_reloading_is_deterministic(self) -> None:
        for schema_id, groups in FIXTURE_MANIFEST.items():
            for name in groups["valid"]:
                path = _fixture_dir(schema_id, "valid") / name
                first = load_record(path.read_bytes()).sha256
                second = load_record(path.read_bytes()).sha256
                self.assertEqual(first, second, f"nondeterministic hash for {path}")


class SchemaIntegrityTest(unittest.TestCase):
    def test_registry_loads_exactly_the_seven_v1_schemas(self) -> None:
        registry = SchemaRegistry(SCHEMA_ROOT)
        self.assertEqual(
            registry.schema_ids,
            (
                "research-case-package/v1",
                "research-claim/v1",
                "research-evidence/v1",
                "research-failure-analysis/v1",
                "research-failure-observation/v1",
                "research-run/v1",
                "research-task/v1",
            ),
        )

    def test_schema_files_are_domain_neutral(self) -> None:
        for path in sorted(SCHEMA_ROOT.glob("*.schema.json")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(schema=path.name):
                match = _BANNED_TERMS.search(text)
                self.assertIsNone(
                    match,
                    f"domain term {match.group(0)!r} leaked into {path.name}"
                    if match
                    else "",
                )


if __name__ == "__main__":
    unittest.main()
