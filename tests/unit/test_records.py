"""Unit tests for the record facade: dispatch, validation, and hash binding."""

import json
import tempfile
import unittest
from pathlib import Path

from research_evolution.core import (
    CoreError,
    Record,
    RecordValidationError,
    SchemaDefinitionError,
    StrictJsonError,
    UnknownSchemaError,
    canonical_sha256,
    load_record,
)

MINIMAL_TASK = {
    "schema": "research-task/v1",
    "task_id": "task-unit-001",
    "title": "Unit test task",
    "problem_statement": "Exercise the record facade.",
    "domain": "engineering",
    "scope": {},
    "resources": {},
    "completion_criteria": ["Loads."],
    "permissions": [],
    "allowed_external_effects": [],
    "created_at": "2026-08-14T07:00:00Z",
}


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


class LoadRecordTest(unittest.TestCase):
    def test_valid_task_loads(self) -> None:
        record = load_record(json.dumps(MINIMAL_TASK))
        self.assertIsInstance(record, Record)
        self.assertEqual(record.schema_id, "research-task/v1")
        self.assertEqual(record.data["task_id"], "task-unit-001")

    def test_hash_binds_canonical_form(self) -> None:
        record = load_record(json.dumps(MINIMAL_TASK))
        self.assertEqual(record.sha256, canonical_sha256(MINIMAL_TASK))
        self.assertEqual(len(record.sha256), 64)

    def test_data_returns_isolated_deep_copy(self) -> None:
        record = load_record(json.dumps(MINIMAL_TASK))
        frozen = record.sha256
        record.data["title"] = "mutated through the accessor"
        record.data["completion_criteria"].append("mutated nested")
        self.assertEqual(record.data["title"], "Unit test task")
        self.assertEqual(record.data["completion_criteria"], ["Loads."])
        self.assertEqual(record.sha256, frozen)

    def test_hash_invariant_always_holds(self) -> None:
        record = load_record(json.dumps(MINIMAL_TASK))
        self.assertEqual(record.sha256, canonical_sha256(record.data))

    def test_direct_construction_rejected(self) -> None:
        with self.assertRaises(CoreError):
            Record("research-task/v1", dict(MINIMAL_TASK))
        with self.assertRaises(CoreError):
            Record("research-task/v1", dict(MINIMAL_TASK), _token=None)

    def test_caller_payload_mutation_does_not_reach_record(self) -> None:
        payload = json.loads(json.dumps(MINIMAL_TASK))
        record = load_record(json.dumps(payload))
        payload["title"] = "mutated caller object"
        self.assertEqual(record.data["title"], "Unit test task")

    def test_key_order_does_not_change_hash(self) -> None:
        reordered = dict(reversed(list(MINIMAL_TASK.items())))
        self.assertEqual(
            load_record(json.dumps(MINIMAL_TASK)).sha256,
            load_record(json.dumps(reordered)).sha256,
        )

    def test_missing_schema_field_rejected(self) -> None:
        payload = {k: v for k, v in MINIMAL_TASK.items() if k != "schema"}
        with self.assertRaises(UnknownSchemaError):
            load_record(json.dumps(payload))

    def test_non_string_schema_field_rejected(self) -> None:
        payload = dict(MINIMAL_TASK, schema=1)
        with self.assertRaises(UnknownSchemaError):
            load_record(json.dumps(payload))

    def test_unknown_schema_id_rejected(self) -> None:
        payload = dict(MINIMAL_TASK, schema="research-run/v9")
        with self.assertRaises(UnknownSchemaError):
            load_record(json.dumps(payload))

    def test_missing_required_field_rejected_with_path(self) -> None:
        payload = {k: v for k, v in MINIMAL_TASK.items() if k != "task_id"}
        with self.assertRaises(RecordValidationError) as ctx:
            load_record(json.dumps(payload))
        self.assertEqual(ctx.exception.schema_id, "research-task/v1")
        self.assertTrue(any("task_id" in v for v in ctx.exception.violations))

    def test_additional_property_rejected(self) -> None:
        payload = dict(MINIMAL_TASK, unexpected=1)
        with self.assertRaises(RecordValidationError):
            load_record(json.dumps(payload))

    def test_enum_violation_rejected(self) -> None:
        claim = {
            "schema": "research-claim/v1",
            "claim_id": "claim-unit-001",
            "claim_type": "research_claim",
            "statement": "x",
            "scope": "x",
            "disposition": "proposed",
            "evidence_maturity": "draft",
            "supporting_evidence": [],
            "limitations": [],
            "non_entailments": [],
            "created_at": "2026-08-14T07:00:00Z",
        }
        with self.assertRaises(RecordValidationError) as ctx:
            load_record(json.dumps(claim))
        self.assertTrue(any("claim_type" in v for v in ctx.exception.violations))

    def _minimal_claim(self, **overrides) -> dict:
        claim = {
            "schema": "research-claim/v1",
            "claim_id": "claim-unit-001",
            "claim_type": "engineering_claim",
            "statement": "x",
            "scope": "x",
            "disposition": "proposed",
            "evidence_maturity": "draft",
            "supporting_evidence": [],
            "limitations": [],
            "non_entailments": [],
            "created_at": "2026-08-14T07:00:00Z",
        }
        claim.update(overrides)
        return claim

    def test_supported_without_evidence_rejected(self) -> None:
        with self.assertRaises(RecordValidationError) as ctx:
            load_record(json.dumps(self._minimal_claim(disposition="supported")))
        self.assertTrue(
            any("supporting_evidence" in v for v in ctx.exception.violations)
        )

    def test_refuted_without_evidence_rejected(self) -> None:
        with self.assertRaises(RecordValidationError):
            load_record(json.dumps(self._minimal_claim(disposition="refuted")))

    def test_terminal_dispositions_without_evidence_rejected(self) -> None:
        # superseded/withdrawn are terminal dispositions: only
        # proposed/inconclusive at draft maturity may have empty evidence.
        for disposition in ("superseded", "withdrawn"):
            with self.subTest(disposition=disposition):
                with self.assertRaises(RecordValidationError) as ctx:
                    load_record(json.dumps(self._minimal_claim(disposition=disposition)))
                self.assertTrue(
                    any("supporting_evidence" in v for v in ctx.exception.violations)
                )

    def test_maturity_above_draft_without_evidence_rejected(self) -> None:
        with self.assertRaises(RecordValidationError):
            load_record(
                json.dumps(self._minimal_claim(evidence_maturity="engineering_verified"))
            )

    def test_proposed_and_inconclusive_may_have_empty_evidence(self) -> None:
        for disposition in ("proposed", "inconclusive"):
            with self.subTest(disposition=disposition):
                record = load_record(
                    json.dumps(self._minimal_claim(disposition=disposition))
                )
                self.assertEqual(record.schema_id, "research-claim/v1")

    def test_supported_with_evidence_accepted(self) -> None:
        record = load_record(
            json.dumps(
                self._minimal_claim(
                    disposition="supported",
                    evidence_maturity="engineering_verified",
                    supporting_evidence=[{"evidence_id": "evidence-unit-1"}],
                )
            )
        )
        self.assertEqual(record.schema_id, "research-claim/v1")

    def test_whitespace_only_semantic_strings_rejected(self) -> None:
        with self.assertRaises(RecordValidationError):
            load_record(json.dumps(dict(MINIMAL_TASK, title="   ")))
        with self.assertRaises(RecordValidationError):
            load_record(json.dumps(self._minimal_claim(statement="   ")))
        evidence = self._minimal_evidence()
        evidence["evidence_level"] = "   "
        with self.assertRaises(RecordValidationError):
            load_record(json.dumps(evidence))

    def test_unsafe_locator_rejected_via_schema_extension(self) -> None:
        evidence = {
            "schema": "research-evidence/v1",
            "evidence_id": "evidence-unit-001",
            "claim_ids": ["claim-unit-001"],
            "producer": {"tool": "t", "version": "1"},
            "inputs": [{"name": "n", "kind": "data", "locator": "../escape"}],
            "generated_at": "2026-08-14T07:00:00Z",
            "content_sha256": "0" * 64,
            "applicability": "unit test",
            "evidence_level": "engineering",
            "limitations": [],
        }
        with self.assertRaises(RecordValidationError) as ctx:
            load_record(json.dumps(evidence))
        self.assertTrue(any(".." in v for v in ctx.exception.violations))

    def test_multiple_violations_are_all_reported(self) -> None:
        payload = dict(MINIMAL_TASK, task_id="has space", created_at="not-a-date")
        with self.assertRaises(RecordValidationError) as ctx:
            load_record(json.dumps(payload))
        self.assertGreaterEqual(len(ctx.exception.violations), 2)

    def _minimal_evidence(self) -> dict:
        return {
            "schema": "research-evidence/v1",
            "evidence_id": "evidence-unit-001",
            "claim_ids": ["claim-unit-001"],
            "producer": {"tool": "t", "version": "1"},
            "inputs": [{"name": "n", "kind": "data", "locator": "in/x.json"}],
            "generated_at": "2026-08-14T07:00:00Z",
            "content_sha256": "0" * 64,
            "applicability": "unit test",
            "evidence_level": "engineering",
            "limitations": [],
        }

    def test_hash_with_trailing_newline_rejected(self) -> None:
        payload = self._minimal_evidence()
        payload["content_sha256"] = "0" * 64 + "\n"
        with self.assertRaises(RecordValidationError) as ctx:
            load_record(json.dumps(payload))
        self.assertTrue(any("content_sha256" in v for v in ctx.exception.violations))

    def test_impossible_timestamp_rejected(self) -> None:
        payload = dict(MINIMAL_TASK, created_at="2026-99-99T99:99:99+99:99")
        with self.assertRaises(RecordValidationError) as ctx:
            load_record(json.dumps(payload))
        self.assertTrue(any("created_at" in v for v in ctx.exception.violations))

    def test_unbound_evidence_input_rejected(self) -> None:
        payload = self._minimal_evidence()
        payload["inputs"] = [{"name": "n", "kind": "data"}]
        with self.assertRaises(RecordValidationError) as ctx:
            load_record(json.dumps(payload))
        self.assertTrue(any("at least one" in v for v in ctx.exception.violations))

    def test_lone_surrogate_fails_as_core_error(self) -> None:
        payload = dict(MINIMAL_TASK, title="lone surrogate: \ud800")
        with self.assertRaises(CoreError):
            load_record(json.dumps(payload))

    def test_deep_legal_record_via_public_api(self) -> None:
        # 498 nested levels pass parsing and validation; canonicalization of
        # a legal record must succeed without leaking a RecursionError.
        record = load_record(_nested_task_text(498))
        self.assertEqual(len(record.sha256), 64)
        self.assertEqual(record.sha256, canonical_sha256(record.data))

    def test_excessive_nesting_via_public_api_rejected(self) -> None:
        with self.assertRaises(StrictJsonError):
            load_record(_nested_task_text(600))


class SchemaRootOverrideTest(unittest.TestCase):
    def _write_schema(self, root: Path, name: str, document: dict) -> None:
        (root / name).write_text(
            json.dumps(document), encoding="utf-8"
        )

    def test_custom_schema_root_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_schema(
                root,
                "x-probe-v1.schema.json",
                {
                    "$id": "x-probe/v1",
                    "type": "object",
                    "required": ["schema", "probe_id"],
                    "properties": {
                        "schema": {"const": "x-probe/v1"},
                        "probe_id": {"type": "string", "minLength": 1},
                    },
                    "additionalProperties": False,
                },
            )
            record = load_record(
                '{"schema": "x-probe/v1", "probe_id": "p1"}', schema_root=root
            )
            self.assertEqual(record.schema_id, "x-probe/v1")

    def test_unsupported_keyword_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_schema(
                root,
                "x-probe-v1.schema.json",
                {
                    "$id": "x-probe/v1",
                    "type": "object",
                    "properties": {
                        "schema": {"const": "x-probe/v1"},
                        "note": {"type": "string", "format": "date-time"},
                    },
                },
            )
            with self.assertRaises(SchemaDefinitionError):
                load_record('{"schema": "x-probe/v1"}', schema_root=root)

    def test_filename_must_match_schema_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_schema(
                root,
                "wrong-name.schema.json",
                {
                    "$id": "x-probe/v1",
                    "type": "object",
                    "properties": {"schema": {"const": "x-probe/v1"}},
                },
            )
            with self.assertRaises(SchemaDefinitionError):
                load_record('{"schema": "x-probe/v1"}', schema_root=root)

    def test_duplicate_schema_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            document = {
                "$id": "x-probe/v1",
                "type": "object",
                "properties": {"schema": {"const": "x-probe/v1"}},
            }
            self._write_schema(root, "x-probe-v1.schema.json", document)
            # A second file cannot reuse the same id under a different name;
            # the name check fires first, which is also a SchemaDefinitionError.
            self._write_schema(root, "x-probe-v1-copy.schema.json", document)
            with self.assertRaises(SchemaDefinitionError):
                load_record('{"schema": "x-probe/v1"}', schema_root=root)

    def test_missing_schema_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            with self.assertRaises(SchemaDefinitionError):
                load_record('{"schema": "x-probe/v1"}', schema_root=missing)


if __name__ == "__main__":
    unittest.main()
