"""Contract tests for the adapter seam and domain schemas (ADR-0005).

Mirrors tests/contract/test_core_schemas_contract.py with two deliberate
differences:

- no domain-neutrality scan — domain vocabulary is ALLOWED under
  schemas/adapters/ (the freeze is the other direction: domain fields must
  never flow back into schemas/core/, and the core contract test pins that);
- SeamBoundaryTest pins the ADR-0005 decision 1 boundary: adapter schema
  ids are rejected by the core default schema root, so seam and domain
  payloads can never enter the core record pipeline (never publishable to
  a core store).

The fixture tree under tests/fixtures/adapters/ and
ADAPTER_FIXTURE_MANIFEST are compared bidirectionally; every family's
minimal fixture and every schema file's raw bytes are golden-pinned
(ADR-0004 decision 7 applies to adapter schemas from birth).
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
    "math-task/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-sought.json": ("RecordValidationError", "sought"),
            "empty-completion-criteria.json": (
                "RecordValidationError",
                "completion_criteria",
            ),
            "missing-created-at.json": ("RecordValidationError", "created_at"),
            "missing-quantifiers.json": ("RecordValidationError", "quantifiers"),
            "whitespace-statement.json": ("RecordValidationError", "statement"),
        },
    },
    "math-claim/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-result.json": ("RecordValidationError", "$.result"),
            "missing-non-entailments.json": (
                "RecordValidationError",
                "non_entailments",
            ),
            "missing-quantifiers.json": ("RecordValidationError", "quantifiers"),
            "whitespace-statement.json": ("RecordValidationError", "statement"),
        },
    },
    "math-evidence/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-content-sha256.json": ("RecordValidationError", "content_sha256"),
            "bad-kind.json": ("RecordValidationError", "$.kind"),
            "missing-content-sha256.json": (
                "RecordValidationError",
                "content_sha256",
            ),
            "whitespace-summary.json": ("RecordValidationError", "summary"),
        },
    },
    "math-case/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-sought.json": ("RecordValidationError", "sought"),
            "missing-case-id.json": ("RecordValidationError", "case_id"),
            "missing-problem-id.json": ("RecordValidationError", "problem_id"),
            "whitespace-case-id.json": ("RecordValidationError", "case_id"),
        },
    },
    "quant-task/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "empty-completion-criteria.json": (
                "RecordValidationError",
                "completion_criteria",
            ),
            "missing-created-at.json": ("RecordValidationError", "created_at"),
            "missing-pit-policy.json": ("RecordValidationError", "pit_policy"),
            "whitespace-universe.json": ("RecordValidationError", "$.universe"),
        },
    },
    "quant-claim/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-claim-class.json": ("RecordValidationError", "claim_class"),
            "bad-outcome.json": ("RecordValidationError", "$.outcome"),
            "missing-non-entailments.json": (
                "RecordValidationError",
                "non_entailments",
            ),
            "whitespace-statement.json": ("RecordValidationError", "statement"),
        },
    },
    "quant-evidence/v1": {
        "valid": ["full.json", "minimal.json", "production-log.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-content-sha256.json": ("RecordValidationError", "content_sha256"),
            "bad-kind.json": ("RecordValidationError", "$.kind"),
            "bad-provenance.json": ("RecordValidationError", "data_provenance"),
            "whitespace-summary.json": ("RecordValidationError", "summary"),
        },
    },
    "quant-case/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-gate.json": ("RecordValidationError", "$.gates"),
            "empty-gates.json": ("RecordValidationError", "$.gates"),
            "missing-case-id.json": ("RecordValidationError", "case_id"),
            "missing-study-id.json": ("RecordValidationError", "study_id"),
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
    "math-case/v1": (
        "9836f8c7af72b063942e002acf63cf57255886c23e7981fa6495c704ac9ddac0"
    ),
    "math-claim/v1": (
        "a2d27809a0dedf7486f2f9136e433005c8c67e9ce7a290c236c974089166a0ab"
    ),
    "math-evidence/v1": (
        "12d43f360b06ea18ee44407313d89befb72a137d3cb99de13e2a67f8292754f8"
    ),
    "math-task/v1": (
        "ebde1b55848120a664ba912dcf8ac2a34e23759ea9209207a9f30e491be5e464"
    ),
    "quant-case/v1": (
        "7a52cba8b1cd40c84249be15b3c6ad4625d204c2b549333fd7ab32c1c57843d7"
    ),
    "quant-claim/v1": (
        "78ef0f843afa098f2cbd49ffb497f6f6e353d3eb182be442260cb3f8d1f426e4"
    ),
    "quant-evidence/v1": (
        "06a6c54fd30eb83e3b7eea64c3afd92244ceae4447c01f5bac6272d4c2253b46"
    ),
    "quant-task/v1": (
        "26d71ed439531b946676f7e192ccdaaca1fcde003fe5fc381521a1705971e410"
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
    "math-case-v1.schema.json": (
        "6c17344f768b6294468cd2d869b2820aa2f85ff33ccb8e9ba62e1071f38b4faa"
    ),
    "math-claim-v1.schema.json": (
        "9823d6b3dc2a55683e007fe1b2ca2171f4e9284ae6e4626d990f0b4c7facb448"
    ),
    "math-evidence-v1.schema.json": (
        "ff88b52782b66c5160afe1d9b2cb004ee09692be0d4af1cd5c48701d89cf1179"
    ),
    "math-task-v1.schema.json": (
        "2794bee04967dc9c784e523de36bb926d68e0e2057f15ed82cd969981e74984a"
    ),
    "quant-case-v1.schema.json": (
        "e7c6e8bb0e0cbb258be65a0bd9629e916dd89f0264312494dc86d827c6aa26ac"
    ),
    "quant-claim-v1.schema.json": (
        "a154a8b805ca2f6716927826acd0db4a44c2a8c69a098176f0ea1c902f86e940"
    ),
    "quant-evidence-v1.schema.json": (
        "c6de86dc72403c1de8d50ab493d092ece7d82222582d14b0f80bd53a0dec31ef"
    ),
    "quant-task-v1.schema.json": (
        "80a0c41c517a28f91154b3400ebc58566eecf8ce892fe958f1647de217793f33"
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
    def test_registry_loads_exactly_the_eleven_v1_adapter_schemas(self) -> None:
        registry = SchemaRegistry(SCHEMA_ROOT)
        self.assertEqual(
            registry.schema_ids,
            (
                "claim-assessment/v1",
                "domain-task/v1",
                "evaluation-contract/v1",
                "math-case/v1",
                "math-claim/v1",
                "math-evidence/v1",
                "math-task/v1",
                "quant-case/v1",
                "quant-claim/v1",
                "quant-evidence/v1",
                "quant-task/v1",
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
    """ADR-0005 decision 1: adapter schemas are not core record families."""

    def test_adapter_schema_ids_are_unknown_to_the_core_default_root(self) -> None:
        for schema_id in ADAPTER_FIXTURE_MANIFEST:
            path = _fixture_dir(schema_id, "valid") / "minimal.json"
            with self.subTest(schema=schema_id):
                with self.assertRaises(UnknownSchemaError):
                    load_record(path.read_bytes())

    def test_core_registry_does_not_register_adapter_schemas(self) -> None:
        core_registry = SchemaRegistry(CORE_SCHEMA_ROOT)
        for schema_id in ADAPTER_FIXTURE_MANIFEST:
            with self.subTest(schema=schema_id):
                self.assertFalse(core_registry.has(schema_id))


if __name__ == "__main__":
    unittest.main()
