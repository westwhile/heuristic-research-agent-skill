"""Contract tests for the adapter seam schemas (ADR-0005 decision 1).

Mirrors tests/contract/test_core_schemas_contract.py with two deliberate
differences:

- no domain-neutrality scan — domain vocabulary is ALLOWED under
  schemas/adapters/ (the freeze is the other direction: domain fields must
  never flow back into schemas/core/, and the core contract test pins that);
- SeamBoundaryTest pins the ADR-0005 decision 1 boundary: seam schema ids
  are rejected by the core default schema root, so seam payloads can never
  enter the core record pipeline (never publishable to a core store).

The fixture tree under tests/fixtures/adapters/ and ADAPTER_FIXTURE_MANIFEST
are compared bidirectionally; every family's minimal fixture and every
schema file's raw bytes are golden-pinned (ADR-0004 decision 7 applies to
adapter schemas from birth).
"""

import hashlib
import unittest
from pathlib import Path

from research_evolution.core import (
    CoreError,
    RecordValidationError,
    UnknownSchemaError,
    load_record,
)
from research_evolution.core._schema import SchemaRegistry

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"
SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "adapters"
CORE_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "core"

_ERROR_CLASSES = {
    "RecordValidationError": RecordValidationError,
}

# invalid fixture name -> (expected error class, expected reason substring).
ADAPTER_FIXTURE_MANIFEST = {
    "domain-task/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-domain-schema-id.json": ("RecordValidationError", "domain_schema_id"),
            "bad-domain.json": ("RecordValidationError", "$.domain"),
            "draft-missing-schema.json": ("RecordValidationError", "core_task_draft"),
            "draft-wrong-schema-tag.json": ("RecordValidationError", "research-task/v1"),
            "missing-domain-payload.json": ("RecordValidationError", "domain_payload"),
            "payload-not-object.json": ("RecordValidationError", "domain_payload"),
        },
    },
    "claim-assessment/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-claim-type.json": ("RecordValidationError", "suggested_claim_type"),
            "bad-disposition.json": ("RecordValidationError", "suggested_disposition"),
            "bad-maturity-ceiling.json": (
                "RecordValidationError",
                "evidence_maturity_ceiling",
            ),
            "empty-reasons.json": ("RecordValidationError", "reasons"),
            "missing-triggered-rules.json": (
                "RecordValidationError",
                "triggered_rules",
            ),
            "whitespace-reason.json": ("RecordValidationError", "reasons"),
        },
    },
    "evaluation-contract/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-case-sha256.json": ("RecordValidationError", "case_sha256"),
            "bad-requirement-claim-type.json": ("RecordValidationError", "claim_type"),
            "bad-requirement-min-maturity.json": (
                "RecordValidationError",
                "min_maturity",
            ),
            "empty-required-evidence.json": (
                "RecordValidationError",
                "required_evidence",
            ),
            "requirement-missing-maturity.json": (
                "RecordValidationError",
                "min_maturity",
            ),
            "whitespace-forbidden-channel.json": (
                "RecordValidationError",
                "forbidden_channels",
            ),
        },
    },
}

# Golden pins: canonical SHA-256 of each family's valid/minimal.json fixture.
MINIMAL_FIXTURE_SHA256 = {
    "claim-assessment/v1": (
        "fc5761d819cafe98d3ab08110311eb72e3aab8cb8067882ed7402917ba88a805"
    ),
    "domain-task/v1": (
        "d4220f70af2cc8df6bfe4790d914d8bae25f3f8bfd7987290f7e90e1320890cd"
    ),
    "evaluation-contract/v1": (
        "8d28c5756a2ec8f90341562bbfbdd605350c3bc52cb3a6b03bfd6eac4b02d1ab"
    ),
}

# Golden pins (ADR-0004 decision 7): SHA-256 of each schema file's raw
# on-disk bytes. Newline stability is carried by .gitattributes.
ADAPTER_SCHEMA_TEXT_SHA256 = {
    "claim-assessment-v1.schema.json": (
        "c172cf54e70f1a3f6f01330e9b61a87e6e992ca05e20d8fe74e9182bd6ebc42e"
    ),
    "domain-task-v1.schema.json": (
        "3e49118d4d3b17b68fafc95a2f5dd7389eefe0a200acd0c5194bc5127d8faf61"
    ),
    "evaluation-contract-v1.schema.json": (
        "ab8294815264af74b19d325c7e1bd9e70bf938d4a39192736aee6a5d3e65be27"
    ),
}


def _fixture_dir(schema_id: str, kind: str) -> Path:
    family, version = schema_id.split("/")
    return FIXTURES_ROOT / family / version / kind


def _manifest_files() -> set[str]:
    expected: set[str] = set()
    for schema_id, groups in ADAPTER_FIXTURE_MANIFEST.items():
        family, version = schema_id.split("/")
        for name in groups["valid"]:
            expected.add(f"{family}/{version}/valid/{name}")
        for name in groups["invalid"]:
            expected.add(f"{family}/{version}/invalid/{name}")
    return expected


class AdapterFixtureManifestTest(unittest.TestCase):
    def test_fixture_tree_matches_manifest_bidirectionally(self) -> None:
        on_disk = {
            path.relative_to(FIXTURES_ROOT).as_posix()
            for path in FIXTURES_ROOT.rglob("*")
            if path.is_file()
        }
        self.assertEqual(_manifest_files(), on_disk)

    def test_every_schema_has_valid_and_invalid_fixtures(self) -> None:
        for groups in ADAPTER_FIXTURE_MANIFEST.values():
            self.assertGreaterEqual(len(groups["valid"]), 2)
            self.assertGreaterEqual(len(groups["invalid"]), 5)


class AdapterFixtureBehaviorTest(unittest.TestCase):
    def test_valid_fixtures_load(self) -> None:
        for schema_id, groups in ADAPTER_FIXTURE_MANIFEST.items():
            for name in groups["valid"]:
                path = _fixture_dir(schema_id, "valid") / name
                with self.subTest(fixture=f"{schema_id}/valid/{name}"):
                    record = load_record(path.read_bytes(), schema_root=SCHEMA_ROOT)
                    self.assertEqual(record.schema_id, schema_id)

    def test_invalid_fixtures_fail_with_expected_error(self) -> None:
        for schema_id, groups in ADAPTER_FIXTURE_MANIFEST.items():
            for name, (error_name, reason) in groups["invalid"].items():
                path = _fixture_dir(schema_id, "invalid") / name
                with self.subTest(fixture=f"{schema_id}/invalid/{name}"):
                    with self.assertRaises(CoreError) as ctx:
                        load_record(path.read_bytes(), schema_root=SCHEMA_ROOT)
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
                    # One failure category per invalid fixture.
                    violations = getattr(ctx.exception, "violations", None)
                    if violations is not None:
                        self.assertEqual(
                            len(violations),
                            1,
                            f"fixture should isolate one violation: {ctx.exception}",
                        )

    def test_minimal_fixture_hashes_are_golden_pinned(self) -> None:
        for schema_id, expected in MINIMAL_FIXTURE_SHA256.items():
            path = _fixture_dir(schema_id, "valid") / "minimal.json"
            with self.subTest(fixture=f"{schema_id}/valid/minimal.json"):
                record = load_record(path.read_bytes(), schema_root=SCHEMA_ROOT)
                self.assertEqual(record.sha256, expected)

    def test_reloading_is_deterministic(self) -> None:
        for schema_id, groups in ADAPTER_FIXTURE_MANIFEST.items():
            for name in groups["valid"]:
                path = _fixture_dir(schema_id, "valid") / name
                first = load_record(path.read_bytes(), schema_root=SCHEMA_ROOT).sha256
                second = load_record(path.read_bytes(), schema_root=SCHEMA_ROOT).sha256
                self.assertEqual(first, second, f"nondeterministic hash for {path}")


class AdapterSchemaIntegrityTest(unittest.TestCase):
    def test_registry_loads_exactly_the_three_v1_seam_schemas(self) -> None:
        registry = SchemaRegistry(SCHEMA_ROOT)
        self.assertEqual(
            registry.schema_ids,
            (
                "claim-assessment/v1",
                "domain-task/v1",
                "evaluation-contract/v1",
            ),
        )

    def test_schema_text_bytes_are_golden_pinned(self) -> None:
        on_disk = {path.name for path in SCHEMA_ROOT.glob("*.schema.json")}
        self.assertEqual(set(ADAPTER_SCHEMA_TEXT_SHA256), on_disk)
        for name, expected in sorted(ADAPTER_SCHEMA_TEXT_SHA256.items()):
            with self.subTest(schema=name):
                raw = (SCHEMA_ROOT / name).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)


class SeamBoundaryTest(unittest.TestCase):
    """ADR-0005 decision 1: seam types are not core record families."""

    def test_seam_schema_ids_are_unknown_to_the_core_default_root(self) -> None:
        for schema_id in ADAPTER_FIXTURE_MANIFEST:
            path = _fixture_dir(schema_id, "valid") / "minimal.json"
            with self.subTest(schema=schema_id):
                with self.assertRaises(UnknownSchemaError):
                    load_record(path.read_bytes())

    def test_core_registry_does_not_register_seam_schemas(self) -> None:
        core_registry = SchemaRegistry(CORE_SCHEMA_ROOT)
        for schema_id in ADAPTER_FIXTURE_MANIFEST:
            with self.subTest(schema=schema_id):
                self.assertFalse(core_registry.has(schema_id))


if __name__ == "__main__":
    unittest.main()
