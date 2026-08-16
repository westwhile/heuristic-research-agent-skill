"""Unit tests for verify_record_graph: store integrity and graph invariants."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_evolution.core import (
    StoreIntegrityError,
    canonical_bytes,
    load_record,
    publish_record,
    verify_record_graph,
)


def _task(task_id: str) -> dict:
    return {
        "schema": "research-task/v1",
        "task_id": task_id,
        "title": "Graph test task",
        "problem_statement": "Exercise graph verification.",
        "domain": "engineering",
        "scope": {},
        "resources": {},
        "completion_criteria": ["Verifies."],
        "permissions": [],
        "allowed_external_effects": [],
        "created_at": "2026-08-14T07:00:00Z",
    }


def _claim(
    claim_id: str,
    evidence_refs: list[tuple[str, str | None]] | None = None,
    supersedes: str | None = None,
) -> dict:
    payload = {
        "schema": "research-claim/v1",
        "claim_id": claim_id,
        "claim_type": "engineering_claim",
        "statement": "Graph test claim.",
        "scope": "unit tests",
        "disposition": "proposed",
        "evidence_maturity": "draft",
        "supporting_evidence": [],
        "limitations": [],
        "non_entailments": [],
        "created_at": "2026-08-14T07:00:00Z",
    }
    if supersedes is not None:
        payload["supersedes"] = supersedes
    for evidence_id, pin in evidence_refs or []:
        ref = {"evidence_id": evidence_id}
        if pin is not None:
            ref["sha256"] = pin
        payload["supporting_evidence"].append(ref)
    return payload


def _evidence(evidence_id: str, claim_ids: list[str]) -> dict:
    return {
        "schema": "research-evidence/v1",
        "evidence_id": evidence_id,
        "claim_ids": claim_ids,
        "producer": {"tool": "unit-test", "version": "1.0"},
        "inputs": [{"name": "code", "kind": "code", "sha256": "0" * 64}],
        "generated_at": "2026-08-14T07:00:00Z",
        "content_sha256": "1" * 64,
        "applicability": "unit tests",
        "evidence_level": "engineering",
        "limitations": [],
    }


class GraphVerifyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "store"

    def _publish(self, payload: dict):
        return publish_record(json.dumps(payload), root=self.root)

    def _kinds(self, report) -> set[str]:
        return {violation.kind for violation in report.violations}

    def _linked_pair(self, pin: bool = True) -> str:
        """Publish evidence e-1 and claim c-1 linked in both directions."""
        evidence = _evidence("e-1", ["c-1"])
        record = load_record(json.dumps(evidence))
        refs = [("e-1", record.sha256 if pin else None)]
        self._publish(evidence)
        self._publish(_claim("c-1", evidence_refs=refs))
        return record.sha256

    # -- baseline ---------------------------------------------------------

    def test_empty_store_verifies_ok(self) -> None:
        self.root.mkdir(parents=True)
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 0)
        self.assertEqual(report.to_dict()["violations"], [])

    def test_missing_root_fails_closed(self) -> None:
        report = verify_record_graph(self.root / "does-not-exist")
        self.assertFalse(report.ok)
        self.assertIn("store_root_missing", self._kinds(report))

    def test_linked_claim_evidence_graph_ok(self) -> None:
        sha = self._linked_pair()
        self._publish(_task("t-1"))
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 3)
        self.assertEqual(
            report.families,
            {
                "research-claim/v1": 1,
                "research-evidence/v1": 1,
                "research-task/v1": 1,
            },
        )
        manifest_raw = (self.root / "manifest.json").read_bytes()
        self.assertEqual(
            report.manifest_sha256, hashlib.sha256(manifest_raw).hexdigest()
        )
        self.assertEqual(sha, load_record(json.dumps(_evidence("e-1", ["c-1"]))).sha256)

    # -- reference checks ---------------------------------------------------

    def test_dangling_evidence_reference(self) -> None:
        self._publish(_claim("c-1", evidence_refs=[("e-missing", None)]))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("dangling_reference", self._kinds(report))

    def test_dangling_claim_reference(self) -> None:
        self._publish(_evidence("e-1", ["c-missing"]))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("dangling_reference", self._kinds(report))

    def test_dangling_supersedes_reference(self) -> None:
        self._publish(_claim("c-2", supersedes="c-missing"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("dangling_reference", self._kinds(report))

    def test_cross_type_reference_from_claim_to_task(self) -> None:
        self._publish(_task("t-1"))
        self._publish(_claim("c-1", evidence_refs=[("t-1", None)]))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("cross_type_reference", self._kinds(report))

    def test_cross_type_reference_from_evidence_to_evidence(self) -> None:
        self._publish(_evidence("e-1", ["e-2"]))
        self._publish(_evidence("e-2", ["e-1"]))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("cross_type_reference", self._kinds(report))

    def test_cross_type_supersedes_reference(self) -> None:
        self._publish(_evidence("e-1", ["c-1"]))
        self._publish(_claim("c-1", supersedes="e-1"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        # supersedes must name a claim; e-1 exists but is an evidence id.
        self.assertIn("cross_type_reference", self._kinds(report))
        # e-1 lists c-1 without a link back; the two findings coexist.
        self.assertIn("one_way_link", self._kinds(report))

    def test_self_reference_detected(self) -> None:
        self._publish(_claim("c-1", supersedes="c-1"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("self_reference", self._kinds(report))

    def test_pin_mismatch_detected(self) -> None:
        self._publish(_evidence("e-1", ["c-1"]))
        self._publish(_claim("c-1", evidence_refs=[("e-1", "f" * 64)]))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("pin_mismatch", self._kinds(report))

    def test_one_way_link_claim_side(self) -> None:
        self._publish(_evidence("e-1", ["c-2"]))  # lists a different claim
        self._publish(_claim("c-1", evidence_refs=[("e-1", None)]))
        self._publish(_claim("c-2", evidence_refs=[("e-1", None)]))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("one_way_link", self._kinds(report))

    def test_one_way_link_evidence_side(self) -> None:
        self._publish(_evidence("e-1", ["c-1"]))
        self._publish(_claim("c-1"))  # does not list e-1 back
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("one_way_link", self._kinds(report))

    def test_unpinned_bidirectional_link_ok(self) -> None:
        self._linked_pair(pin=False)
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())

    # -- lineage ------------------------------------------------------------

    def test_lineage_cycle_of_two_detected(self) -> None:
        self._publish(_claim("c-1", supersedes="c-2"))
        self._publish(_claim("c-2", supersedes="c-1"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("lineage_cycle", self._kinds(report))

    def test_lineage_cycle_of_three_detected(self) -> None:
        self._publish(_claim("c-1", supersedes="c-3"))
        self._publish(_claim("c-2", supersedes="c-1"))
        self._publish(_claim("c-3", supersedes="c-2"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("lineage_cycle", self._kinds(report))

    def test_lineage_chain_ok(self) -> None:
        self._publish(_claim("c-1"))
        self._publish(_claim("c-2", supersedes="c-1"))
        self._publish(_claim("c-3", supersedes="c-2"))
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.forks, ())

    def test_fork_is_informational_not_an_error(self) -> None:
        self._publish(_claim("c-1"))
        self._publish(_claim("c-2", supersedes="c-1"))
        self._publish(_claim("c-3", supersedes="c-1"))
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.forks, (("c-1", ("c-2", "c-3")),))

    # -- identity uniqueness --------------------------------------------------

    def test_duplicate_id_across_two_families_detected(self) -> None:
        # The same logical id as task and claim: exactly one violation, and
        # it is duplicate_id (references are typed, so nothing else fires).
        self._publish(_task("x-1"))
        self._publish(_claim("x-1"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(len(report.violations), 1)
        violation = report.violations[0]
        self.assertEqual(violation.kind, "duplicate_id")
        self.assertIn("'x-1'", violation.detail)
        self.assertIn("research-claim/v1", violation.detail)
        self.assertIn("research-task/v1", violation.detail)

    def test_duplicate_id_across_three_families_single_violation(self) -> None:
        # One violation per colliding id listing every involved family; the
        # records are otherwise fully linked, so nothing else fires.
        self._publish(_task("x-1"))
        evidence = _evidence("x-1", ["x-1"])
        pin = load_record(json.dumps(evidence)).sha256
        self._publish(evidence)
        self._publish(_claim("x-1", evidence_refs=[("x-1", pin)]))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(len(report.violations), 1)
        violation = report.violations[0]
        self.assertEqual(violation.kind, "duplicate_id")
        for family in (
            "research-claim/v1",
            "research-evidence/v1",
            "research-task/v1",
        ):
            self.assertIn(family, violation.detail)

    def test_unique_ids_across_families_ok(self) -> None:
        self._publish(_task("t-1"))
        self._linked_pair()
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertNotIn("duplicate_id", self._kinds(report))

    # -- store integrity tampering -------------------------------------------

    def test_record_rewrite_detected(self) -> None:
        receipt = self._publish(_task("t-1"))
        path = self.root / receipt.path
        # Replace content with a different valid record under the victim's
        # file name: the content hash no longer matches the name.
        other = load_record(json.dumps(_task("t-2")))
        path.write_bytes(other.canonical_bytes)
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("record_identity_mismatch", self._kinds(report))

    def test_record_corruption_detected(self) -> None:
        receipt = self._publish(_task("t-1"))
        (self.root / receipt.path).write_bytes(b"{not json")
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("record_invalid", self._kinds(report))

    def test_record_deletion_detected(self) -> None:
        receipt = self._publish(_task("t-1"))
        (self.root / receipt.path).unlink()
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("missing_record", self._kinds(report))

    def test_extra_record_detected(self) -> None:
        self._publish(_task("t-1"))
        extra = load_record(json.dumps(_task("t-2")))
        target = (
            self.root / "records" / "research-task" / "v1" / f"{extra.sha256}.json"
        )
        target.write_bytes(extra.canonical_bytes)
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("extra_record", self._kinds(report))

    def test_non_canonical_record_bytes_detected(self) -> None:
        payload = _task("t-1")
        receipt = self._publish(payload)
        pretty = json.dumps(payload, indent=2).encode("utf-8")
        (self.root / receipt.path).write_bytes(pretty)
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("record_not_canonical", self._kinds(report))

    def test_manifest_entry_removal_detected(self) -> None:
        self._publish(_task("t-1"))
        self._publish(_task("t-2"))
        manifest = self.root / "manifest.json"
        obj = json.loads(manifest.read_text(encoding="utf-8"))
        obj["records"] = obj["records"][:1]
        manifest.write_bytes(canonical_bytes(obj))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("extra_record", self._kinds(report))

    def test_manifest_hash_tamper_detected(self) -> None:
        receipt = self._publish(_task("t-1"))
        manifest = self.root / "manifest.json"
        obj = json.loads(manifest.read_text(encoding="utf-8"))
        entry = obj["records"][0]
        entry["sha256"] = "0" * 64
        entry["path"] = receipt.path  # keep the path pointing at the file
        manifest.write_bytes(canonical_bytes(obj))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        # The doctored entry is structurally inconsistent (path no longer
        # derives from the hash) and therefore caught at manifest parse time.
        self.assertIn("manifest_malformed", self._kinds(report))

    def test_manifest_duplicate_entries_detected(self) -> None:
        self._publish(_task("t-1"))
        manifest = self.root / "manifest.json"
        obj = json.loads(manifest.read_text(encoding="utf-8"))
        obj["records"] = obj["records"] * 2
        manifest.write_bytes(canonical_bytes(obj))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("manifest_malformed", self._kinds(report))

    def test_manifest_entry_non_string_field_is_malformed(self) -> None:
        # The branch behind the entry-shape cleanup: a non-string field
        # value is a malformed manifest, and it blocks the next publish.
        self._publish(_task("t-1"))
        manifest = self.root / "manifest.json"
        obj = json.loads(manifest.read_text(encoding="utf-8"))
        obj["records"][0]["id"] = 123
        manifest.write_bytes(canonical_bytes(obj))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        detail = next(
            v.detail for v in report.violations if v.kind == "manifest_malformed"
        )
        self.assertIn("must be a string", detail)
        with self.assertRaises(StoreIntegrityError):
            self._publish(_task("t-2"))

    def test_manifest_deletion_detected(self) -> None:
        self._publish(_task("t-1"))
        (self.root / "manifest.json").unlink()
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("manifest_missing", self._kinds(report))

    def test_foreign_object_detected(self) -> None:
        self._publish(_claim("c-1"))
        stray = self.root / "records" / "research-claim" / "v1" / "note.txt"
        stray.write_bytes(b"hello")
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("foreign_object", self._kinds(report))

    def test_misplaced_record_file_is_foreign(self) -> None:
        self._publish(_task("t-1"))
        record = load_record(json.dumps(_task("t-2")))
        stray = self.root / "records" / f"{record.sha256}.json"
        stray.write_bytes(record.canonical_bytes)
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("foreign_object", self._kinds(report))

    def test_duplicate_logical_id_across_files_detected(self) -> None:
        self._publish(_claim("c-1"))
        twin = load_record(
            json.dumps({**_claim("c-1"), "statement": "A different statement."})
        )
        stray = (
            self.root / "records" / "research-claim" / "v1" / f"{twin.sha256}.json"
        )
        stray.write_bytes(twin.canonical_bytes)
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("duplicate_record", self._kinds(report))

    def test_manifest_not_deterministic_detected(self) -> None:
        self._publish(_task("t-1"))
        manifest = self.root / "manifest.json"
        obj = json.loads(manifest.read_text(encoding="utf-8"))
        # Same content, non-canonical encoding: the manifest is a derived
        # index and must be byte-identical to the deterministic rebuild.
        manifest.write_bytes(json.dumps(obj, indent=2).encode("utf-8"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(
            self._kinds(report), {"manifest_not_deterministic"}, report.to_dict()
        )

    def test_all_disjoint_lineage_cycles_reported(self) -> None:
        # supersedes forms a functional graph, so cycles are disjoint;
        # verification must enumerate every one of them.
        self._publish(_claim("c-1", supersedes="c-2"))
        self._publish(_claim("c-2", supersedes="c-1"))
        self._publish(_claim("c-3", supersedes="c-4"))
        self._publish(_claim("c-4", supersedes="c-3"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        cycles = [v for v in report.violations if v.kind == "lineage_cycle"]
        self.assertEqual(len(cycles), 2, report.to_dict())

    def test_unreadable_records_tree_detected(self) -> None:
        # A directory that cannot be listed is a violation, not silence.
        self._publish(_task("t-1"))
        real_scandir = os.scandir

        def denying_scandir(path):
            if str(path).endswith("v1"):
                raise OSError("simulated permission denial")
            return real_scandir(path)

        with mock.patch(
            "research_evolution.core._store.os.scandir",
            side_effect=denying_scandir,
        ):
            report = verify_record_graph(self.root)
            self.assertFalse(report.ok)
            self.assertEqual(
                self._kinds(report), {"store_unreadable"}, report.to_dict()
            )
            # Publishing is blocked by the same finding, with no writes.
            with self.assertRaises(StoreIntegrityError):
                self._publish(_task("t-2"))

    def test_unreadable_manifest_detected(self) -> None:
        # A manifest that cannot be read is a violation, never a bare OSError.
        self._publish(_task("t-1"))
        real_read_bytes = Path.read_bytes

        def denying_read_bytes(path_self, *args, **kwargs):
            if path_self.name == "manifest.json":
                raise PermissionError("simulated denial")
            return real_read_bytes(path_self, *args, **kwargs)

        with mock.patch.object(Path, "read_bytes", denying_read_bytes):
            report = verify_record_graph(self.root)
            self.assertFalse(report.ok)
            self.assertIn("store_unreadable", self._kinds(report))
            with self.assertRaises(StoreIntegrityError):
                self._publish(_task("t-2"))

    def test_unreadable_record_detected(self) -> None:
        # A record file that cannot be read is a violation, never a bare
        # OSError from the public interface.
        receipt = self._publish(_task("t-1"))
        victim = Path(receipt.path).name
        real_read_bytes = Path.read_bytes

        def denying_read_bytes(path_self, *args, **kwargs):
            if path_self.name == victim:
                raise PermissionError("simulated denial")
            return real_read_bytes(path_self, *args, **kwargs)

        with mock.patch.object(Path, "read_bytes", denying_read_bytes):
            report = verify_record_graph(self.root)
            self.assertFalse(report.ok)
            self.assertEqual(
                self._kinds(report), {"store_unreadable"}, report.to_dict()
            )
            with self.assertRaises(StoreIntegrityError):
                self._publish(_task("t-2"))

    def test_other_reparse_tag_on_reserved_node_detected(self) -> None:
        # White-box: a node carrying FILE_ATTRIBUTE_REPARSE_POINT but being
        # neither symlink nor junction must still be rejected — the contract
        # rejects *every* reparse tag, not only the two common ones.
        self._publish(_task("t-1"))
        target = self.root / "records"
        real_lstat = os.lstat

        class _FakeStat:
            def __init__(self, base) -> None:
                self.st_mode = base.st_mode  # still a plain directory mode
                # FILE_ATTRIBUTE_REPARSE_POINT without symlink/junction.
                self.st_file_attributes = 0x400

        def fake_lstat(path, *args, **kwargs):
            result = real_lstat(path, *args, **kwargs)
            if str(path) == str(target):
                return _FakeStat(result)
            return result

        with mock.patch("os.lstat", side_effect=fake_lstat):
            report = verify_record_graph(self.root)
            self.assertFalse(report.ok)
            self.assertEqual(
                self._kinds(report), {"reparse_point"}, report.to_dict()
            )
            with self.assertRaises(StoreIntegrityError):
                self._publish(_task("t-2"))

    def test_undeterminable_reserved_node_fails_closed(self) -> None:
        # An lstat failure other than FileNotFoundError makes the node
        # undeterminable — never "safe". verify reports store_unreadable;
        # publish raises StoreIntegrityError before writing.
        self._publish(_task("t-1"))
        target = self.root / "records"
        real_lstat = os.lstat

        def denying_lstat(path, *args, **kwargs):
            if str(path) == str(target):
                raise PermissionError("simulated lstat denial")
            return real_lstat(path, *args, **kwargs)

        with mock.patch("os.lstat", side_effect=denying_lstat):
            report = verify_record_graph(self.root)
            self.assertFalse(report.ok)
            self.assertIn("store_unreadable", self._kinds(report))
            self.assertNotIn("reparse_point", self._kinds(report))
            with self.assertRaises(StoreIntegrityError):
                self._publish(_task("t-2"))

    def test_undeterminable_root_component_fails_closed(self) -> None:
        # The lexical root walk fails closed too: an unstat-able root
        # component is store_unreadable in verify and StoreIntegrityError
        # in publish — never silently treated as reparse-free.
        self._publish(_task("t-1"))
        target = self.root
        real_lstat = os.lstat

        def denying_lstat(path, *args, **kwargs):
            if str(path) == str(target):
                raise PermissionError("simulated lstat denial")
            return real_lstat(path, *args, **kwargs)

        with mock.patch("os.lstat", side_effect=denying_lstat):
            report = verify_record_graph(self.root)
            self.assertFalse(report.ok)
            self.assertIn("store_unreadable", self._kinds(report))
            with self.assertRaises(StoreIntegrityError):
                self._publish(_task("t-2"))


if __name__ == "__main__":
    unittest.main()
