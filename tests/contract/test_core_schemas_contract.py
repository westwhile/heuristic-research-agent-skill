"""Contract tests: fixtures, schema integrity, and domain neutrality.

These tests pin the public contract of the Phase 1A core kernel:

- the fixture tree on disk and FIXTURE_MANIFEST are compared
  bidirectionally, so an unlisted family/version directory or stray file is a
  test failure;
- every ``valid`` fixture loads; every ``invalid`` fixture raises the
  expected error class with the expected reason substring;
- the canonical hash of the minimal task fixture is golden-pinned;
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
}

# Golden pin: canonical SHA-256 of research-task/v1 valid/minimal.json.
MINIMAL_TASK_SHA256 = (
    "7a73b657e4b3e8ae6250e0a56b0dee7a73b3838ca4bdd637fe58b7d044e7519a"
)

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

    def test_minimal_task_hash_is_golden_pinned(self) -> None:
        path = _fixture_dir("research-task/v1", "valid") / "minimal.json"
        record = load_record(path.read_bytes())
        self.assertEqual(record.sha256, MINIMAL_TASK_SHA256)

    def test_reloading_is_deterministic(self) -> None:
        for schema_id, groups in FIXTURE_MANIFEST.items():
            for name in groups["valid"]:
                path = _fixture_dir(schema_id, "valid") / name
                first = load_record(path.read_bytes()).sha256
                second = load_record(path.read_bytes()).sha256
                self.assertEqual(first, second, f"nondeterministic hash for {path}")


class SchemaIntegrityTest(unittest.TestCase):
    def test_registry_loads_exactly_the_three_v1_schemas(self) -> None:
        registry = SchemaRegistry(SCHEMA_ROOT)
        self.assertEqual(
            registry.schema_ids,
            ("research-claim/v1", "research-evidence/v1", "research-task/v1"),
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
