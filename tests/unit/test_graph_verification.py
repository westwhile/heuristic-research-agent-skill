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


def _run(run_id: str, task_id: str = "t-1", task_sha256: str = "0" * 64) -> dict:
    return {
        "schema": "research-run/v1",
        "run_id": run_id,
        "task": {"task_id": task_id, "sha256": task_sha256},
        "executor": {"tool": "unit-test", "version": "1.0"},
        "environment": [{"name": "interpreter", "version": "3.14.5"}],
        "inputs": [{"name": "code", "kind": "code", "sha256": "2" * 64}],
        "randomness": {"mode": "uncontrolled"},
        "started_at": "2026-08-14T08:00:00Z",
        "completed_at": "2026-08-14T08:01:00Z",
    }


def _observation(
    observation_id: str, run_id: str = "r-1", run_sha256: str = "2" * 64
) -> dict:
    return {
        "schema": "research-failure-observation/v1",
        "observation_id": observation_id,
        "run": {"run_id": run_id, "sha256": run_sha256},
        "observer": {"tool": "unit-test", "version": "1.0"},
        "facts": ["The run log ends with exit code 1."],
        "observed_at": "2026-08-14T08:05:00Z",
    }


def _analysis(
    analysis_id: str,
    observation_id: str = "o-1",
    observation_sha256: str = "3" * 64,
    supersedes: str | None = None,
) -> dict:
    payload = {
        "schema": "research-failure-analysis/v1",
        "analysis_id": analysis_id,
        "observation": {
            "observation_id": observation_id,
            "sha256": observation_sha256,
        },
        "hypotheses": ["The input fixture may be missing."],
        "created_at": "2026-08-14T08:10:00Z",
    }
    if supersedes is not None:
        payload["supersedes"] = supersedes
    return payload


class HierarchicalGraphTest(unittest.TestCase):
    """Phase 1C graph checks: the pinned one-directional hierarchy
    (run -> task, observation -> run, analysis -> observation) and the
    anchored analysis lineage (ADR-0003 decisions 2, 3, 5, and 6)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "store"

    def _publish(self, payload: dict):
        return publish_record(json.dumps(payload), root=self.root)

    def _kinds(self, report) -> set[str]:
        return {violation.kind for violation in report.violations}

    def _publish_chain(self) -> tuple[str, str, str]:
        """Publish task t-1 <- run r-1 <- observation o-1 <- analysis a-1,
        every hierarchical reference pinned to the stored record's hash."""
        task = _task("t-1")
        self._publish(task)
        task_sha = load_record(json.dumps(task)).sha256
        run = _run("r-1", task_sha256=task_sha)
        self._publish(run)
        run_sha = load_record(json.dumps(run)).sha256
        observation = _observation("o-1", run_sha256=run_sha)
        self._publish(observation)
        observation_sha = load_record(json.dumps(observation)).sha256
        self._publish(_analysis("a-1", observation_sha256=observation_sha))
        return task_sha, run_sha, observation_sha

    def test_full_chain_verifies_ok(self) -> None:
        # Correctly pinned one-directional references raise nothing — in
        # particular no one_way_link and no duplicate_id false positives.
        self._publish_chain()
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 4)
        self.assertEqual(
            report.families,
            {
                "research-failure-analysis/v1": 1,
                "research-failure-observation/v1": 1,
                "research-run/v1": 1,
                "research-task/v1": 1,
            },
        )

    def test_run_with_dangling_task(self) -> None:
        self._publish(_run("r-1", task_id="t-absent"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("dangling_reference", self._kinds(report))

    def test_run_with_wrong_task_pin(self) -> None:
        self._publish(_task("t-1"))
        self._publish(_run("r-1", task_sha256="9" * 64))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("pin_mismatch", self._kinds(report))

    def test_run_task_cross_type(self) -> None:
        self._publish(_claim("c-1"))
        self._publish(_run("r-1", task_id="c-1"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("cross_type_reference", self._kinds(report))

    def test_observation_with_dangling_run(self) -> None:
        self._publish(_observation("o-1", run_id="r-absent"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("dangling_reference", self._kinds(report))

    def test_observation_with_wrong_run_pin(self) -> None:
        self._publish_chain_observationless()
        self._publish(_observation("o-1", run_sha256="9" * 64))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("pin_mismatch", self._kinds(report))

    def _publish_chain_observationless(self) -> tuple[str, str]:
        task = _task("t-1")
        self._publish(task)
        task_sha = load_record(json.dumps(task)).sha256
        run = _run("r-1", task_sha256=task_sha)
        self._publish(run)
        run_sha = load_record(json.dumps(run)).sha256
        return task_sha, run_sha

    def test_observation_run_cross_type(self) -> None:
        self._publish(_task("t-1"))
        self._publish(_observation("o-1", run_id="t-1"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("cross_type_reference", self._kinds(report))

    def test_analysis_with_dangling_observation(self) -> None:
        self._publish(_analysis("a-1", observation_id="o-absent"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("dangling_reference", self._kinds(report))

    def test_analysis_with_wrong_observation_pin(self) -> None:
        _t, _r, observation_sha = self._publish_chain()
        self._publish(
            _analysis("a-2", observation_sha256="9" * 64)
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("pin_mismatch", self._kinds(report))

    def test_analysis_observation_cross_type(self) -> None:
        _t, run_sha = self._publish_chain_observationless()
        self._publish(_analysis("a-1", observation_id="r-1"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("cross_type_reference", self._kinds(report))

    def test_analysis_supersedes_chain_ok(self) -> None:
        _t, _r, observation_sha = self._publish_chain()
        self._publish(
            _analysis(
                "a-2", observation_sha256=observation_sha, supersedes="a-1"
            )
        )
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 5)

    def test_analysis_supersedes_self(self) -> None:
        _t, _r, observation_sha = self._publish_chain()
        self._publish(
            _analysis(
                "a-2", observation_sha256=observation_sha, supersedes="a-2"
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("self_reference", self._kinds(report))

    def test_analysis_supersedes_dangling(self) -> None:
        _t, _r, observation_sha = self._publish_chain()
        self._publish(
            _analysis(
                "a-2", observation_sha256=observation_sha, supersedes="a-absent"
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("dangling_reference", self._kinds(report))

    def test_analysis_supersedes_cross_type(self) -> None:
        _t, _r, observation_sha = self._publish_chain()
        self._publish(_claim("c-9"))
        self._publish(
            _analysis("a-2", observation_sha256=observation_sha, supersedes="c-9")
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("cross_type_reference", self._kinds(report))

    def test_analysis_supersedes_cycle(self) -> None:
        _t, run_sha = self._publish_chain_observationless()
        observation = _observation("o-1", run_sha256=run_sha)
        self._publish(observation)
        observation_sha = load_record(json.dumps(observation)).sha256
        # Supersedes is resolved at verify time, so the two records may be
        # published in either order.
        self._publish(
            _analysis("a-1", observation_sha256=observation_sha, supersedes="a-2")
        )
        self._publish(
            _analysis("a-2", observation_sha256=observation_sha, supersedes="a-1")
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("lineage_cycle", self._kinds(report))

    def test_analysis_lineage_scope_mismatch(self) -> None:
        _t, run_sha, observation_sha = self._publish_chain()
        second = _observation("o-2", run_sha256=run_sha)
        self._publish(second)
        second_sha = load_record(json.dumps(second)).sha256
        self._publish(
            _analysis(
                "a-2",
                observation_id="o-2",
                observation_sha256=second_sha,
                supersedes="a-1",
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("lineage_scope_mismatch", self._kinds(report))
        violation = next(
            v for v in report.violations if v.kind == "lineage_scope_mismatch"
        )
        self.assertIn("'o-2'", violation.detail)
        self.assertIn("'o-1'", violation.detail)

    def test_analysis_fork_is_informational(self) -> None:
        _t, _r, observation_sha = self._publish_chain()
        self._publish(
            _analysis("a-2", observation_sha256=observation_sha, supersedes="a-1")
        )
        self._publish(
            _analysis("a-3", observation_sha256=observation_sha, supersedes="a-1")
        )
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertIn(("a-1", ("a-2", "a-3")), report.forks)

    def test_duplicate_id_across_hierarchical_and_claim(self) -> None:
        self._publish(_task("t-1"))
        task_sha = load_record(json.dumps(_task("t-1"))).sha256
        self._publish(_claim("shared-1"))
        self._publish(_run("shared-1", task_sha256=task_sha))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"duplicate_id"})
        violation = report.violations[0]
        self.assertIn("'shared-1'", violation.detail)
        self.assertIn("research-claim/v1", violation.detail)
        self.assertIn("research-run/v1", violation.detail)


def _case_ref(pairs: list[tuple[str, str]], key: str) -> list[dict[str, str]]:
    return [{key: rid, "sha256": sha} for rid, sha in pairs]


def _case_package(
    case_id: str,
    task: tuple[str, str],
    runs: list[tuple[str, str]],
    claims: list[tuple[str, str]] | None = None,
    evidence: list[tuple[str, str]] | None = None,
    observations: list[tuple[str, str]] | None = None,
    analyses: list[tuple[str, str]] | None = None,
) -> dict:
    return {
        "schema": "research-case-package/v1",
        "case_id": case_id,
        "title": "Graph test case package",
        "task": {"task_id": task[0], "sha256": task[1]},
        "runs": _case_ref(runs, "run_id"),
        "claims": _case_ref(claims or [], "claim_id"),
        "evidence": _case_ref(evidence or [], "evidence_id"),
        "observations": _case_ref(observations or [], "observation_id"),
        "analyses": _case_ref(analyses or [], "analysis_id"),
        "privacy_review_status": "pending",
        "created_at": "2026-08-14T08:20:00Z",
    }


def _export_decision(
    decision_id: str,
    case_id: str = "case-1",
    case_sha256: str = "5" * 64,
    outcome: str = "allow",
    export_mode: str = "metrics_only",
    supersedes: str | None = None,
) -> dict:
    payload = {
        "schema": "export-decision/v1",
        "decision_id": decision_id,
        "case": {"case_id": case_id, "sha256": case_sha256},
        "outcome": outcome,
        "export_mode": export_mode,
        "decided_by": {"tool": "unit-test", "version": "1.0.0"},
        "rationale": "Synthetic graph-test case; nothing real to export.",
        "constraints": [],
        "decided_at": "2026-08-14T09:00:00Z",
    }
    if supersedes is not None:
        payload["supersedes"] = supersedes
    return payload


def _export_receipt(
    receipt_id: str,
    decision_id: str = "d-1",
    decision_sha256: str = "6" * 64,
    export_mode: str = "metrics_only",
) -> dict:
    return {
        "schema": "export-receipt/v1",
        "receipt_id": receipt_id,
        "decision": {"decision_id": decision_id, "sha256": decision_sha256},
        "export_mode": export_mode,
        "artifacts": [{"name": "metrics.json", "sha256": "7" * 64}],
        "destination": "graph test inbox",
        "exported_at": "2026-08-14T09:05:00Z",
    }


class CaseGraphTest(unittest.TestCase):
    """Phase 1C C4: case membership closure and generic
    ``duplicate_reference`` (ADR-0003 decisions 7 and 11)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "store"

    def _publish(self, payload: dict):
        return publish_record(json.dumps(payload), root=self.root)

    def _kinds(self, report) -> set[str]:
        return {violation.kind for violation in report.violations}

    def _sha(self, payload: dict) -> str:
        return load_record(json.dumps(payload)).sha256

    def _publish_failure_chain(self) -> tuple[str, str, str, str]:
        """Publish task t-1 <- run r-1 <- observation o-1 <- analysis a-1,
        every reference pinned; return the four hashes."""
        task = _task("t-1")
        self._publish(task)
        task_sha = self._sha(task)
        run = _run("r-1", task_sha256=task_sha)
        self._publish(run)
        run_sha = self._sha(run)
        observation = _observation("o-1", run_sha256=run_sha)
        self._publish(observation)
        observation_sha = self._sha(observation)
        analysis = _analysis("a-1", observation_sha256=observation_sha)
        self._publish(analysis)
        analysis_sha = self._sha(analysis)
        return task_sha, run_sha, observation_sha, analysis_sha

    def _publish_linked_pair(self) -> tuple[str, str]:
        """Publish evidence e-1 and claim c-1 linked in both directions."""
        evidence = _evidence("e-1", ["c-1"])
        self._publish(evidence)
        evidence_sha = self._sha(evidence)
        claim = _claim("c-1", evidence_refs=[("e-1", evidence_sha)])
        self._publish(claim)
        return self._sha(claim), evidence_sha

    def test_case_minimal_ok(self) -> None:
        task = _task("t-1")
        self._publish(task)
        task_sha = self._sha(task)
        run = _run("r-1", task_sha256=task_sha)
        self._publish(run)
        self._publish(
            _case_package("case-1", ("t-1", task_sha), [("r-1", self._sha(run))])
        )
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 3)

    def test_case_full_closure_ok(self) -> None:
        task_sha, run_sha, observation_sha, analysis_sha = (
            self._publish_failure_chain()
        )
        claim_sha, evidence_sha = self._publish_linked_pair()
        self._publish(
            _case_package(
                "case-1",
                ("t-1", task_sha),
                [("r-1", run_sha)],
                claims=[("c-1", claim_sha)],
                evidence=[("e-1", evidence_sha)],
                observations=[("o-1", observation_sha)],
                analyses=[("a-1", analysis_sha)],
            )
        )
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 7)

    def test_case_dangling_run_member(self) -> None:
        self._publish(_task("t-1"))
        task_sha = self._sha(_task("t-1"))
        self._publish(
            _case_package("case-1", ("t-1", task_sha), [("r-9", "9" * 64)])
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("dangling_reference", self._kinds(report))

    def test_case_member_pin_mismatch(self) -> None:
        task_sha, run_sha, _o, _a = self._publish_failure_chain()
        self._publish(
            _case_package("case-1", ("t-1", task_sha), [("r-1", "9" * 64)])
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("pin_mismatch", self._kinds(report))

    def test_case_member_cross_type(self) -> None:
        task_sha, run_sha, _o, _a = self._publish_failure_chain()
        self._publish(
            _case_package(
                "case-1",
                ("t-1", task_sha),
                [("r-1", run_sha)],
                claims=[("r-1", run_sha)],
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("cross_type_reference", self._kinds(report))

    def test_case_incomplete_missing_observation(self) -> None:
        task_sha, run_sha, _o, analysis_sha = self._publish_failure_chain()
        self._publish(
            _case_package(
                "case-1",
                ("t-1", task_sha),
                [("r-1", run_sha)],
                analyses=[("a-1", analysis_sha)],
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"case_incomplete"})
        self.assertIn("'o-1'", report.violations[0].detail)

    def test_case_incomplete_missing_run(self) -> None:
        task_sha, run_sha, observation_sha, analysis_sha = (
            self._publish_failure_chain()
        )
        # The package's run member is a *different* run of the same task,
        # so the chain's run r-1 is outside the package.
        other_run = _run("r-other", task_sha256=task_sha)
        self._publish(other_run)
        self._publish(
            _case_package(
                "case-1",
                ("t-1", task_sha),
                [("r-other", self._sha(other_run))],
                observations=[("o-1", observation_sha)],
                analyses=[("a-1", analysis_sha)],
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"case_incomplete"})
        self.assertIn("'r-1'", report.violations[0].detail)

    def test_case_incomplete_wrong_task(self) -> None:
        task_sha, run_sha, observation_sha, analysis_sha = (
            self._publish_failure_chain()
        )
        other_task = _task("t-other")
        self._publish(other_task)
        self._publish(
            _case_package(
                "case-1",
                ("t-other", self._sha(other_task)),
                [("r-1", run_sha)],
                observations=[("o-1", observation_sha)],
                analyses=[("a-1", analysis_sha)],
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"case_incomplete"})
        self.assertIn("'t-1'", report.violations[0].detail)
        self.assertIn("'t-other'", report.violations[0].detail)

    def test_case_incomplete_claim_evidence(self) -> None:
        task_sha, run_sha, _o, _a = self._publish_failure_chain()
        claim_sha, _e = self._publish_linked_pair()
        self._publish(
            _case_package(
                "case-1",
                ("t-1", task_sha),
                [("r-1", run_sha)],
                claims=[("c-1", claim_sha)],
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"case_incomplete"})
        self.assertIn("'e-1'", report.violations[0].detail)

    def test_case_incomplete_evidence_claim(self) -> None:
        task_sha, run_sha, _o, _a = self._publish_failure_chain()
        _c, evidence_sha = self._publish_linked_pair()
        self._publish(
            _case_package(
                "case-1",
                ("t-1", task_sha),
                [("r-1", run_sha)],
                evidence=[("e-1", evidence_sha)],
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"case_incomplete"})
        self.assertIn("'c-1'", report.violations[0].detail)

    def test_case_duplicate_member(self) -> None:
        task_sha, run_sha, _o, _a = self._publish_failure_chain()
        self._publish(
            _case_package(
                "case-1",
                ("t-1", task_sha),
                [("r-1", run_sha), ("r-1", run_sha)],
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"duplicate_reference"})

    def test_claim_duplicate_supporting_evidence(self) -> None:
        evidence = _evidence("e-1", ["c-1"])
        self._publish(evidence)
        evidence_sha = self._sha(evidence)
        self._publish(
            _claim(
                "c-1",
                evidence_refs=[("e-1", evidence_sha), ("e-1", evidence_sha)],
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"duplicate_reference"})

    def test_evidence_duplicate_claim_ids(self) -> None:
        # The claim lists the evidence back (correct pin), so only the
        # duplicated claim_ids entry can fire.
        evidence = _evidence("e-1", ["c-1", "c-1"])
        evidence_sha = self._sha(evidence)
        self._publish(_claim("c-1", evidence_refs=[("e-1", evidence_sha)]))
        self._publish(evidence)
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"duplicate_reference"})

    def test_duplicate_reference_coexists_with_dangling(self) -> None:
        task_sha, run_sha, _o, _a = self._publish_failure_chain()
        self._publish(
            _case_package(
                "case-1",
                ("t-1", task_sha),
                [("r-9", "9" * 64), ("r-9", "9" * 64)],
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("duplicate_reference", self._kinds(report))
        self.assertIn("dangling_reference", self._kinds(report))


class ExportGraphTest(unittest.TestCase):
    """Phase 1D D3: export-decision lineage (anchor-scoped to its case) and
    the ``unauthorized_export`` gate (ADR-0004 decisions 3 and 5)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "store"

    def _publish(self, payload: dict):
        return publish_record(json.dumps(payload), root=self.root)

    def _kinds(self, report) -> set[str]:
        return {violation.kind for violation in report.violations}

    def _sha(self, payload: dict) -> str:
        return load_record(json.dumps(payload)).sha256

    def _publish_case(self, case_id: str = "case-1") -> str:
        """Publish task t-1 <- run r-1 and a case packaging them; return
        the case record hash. Re-publishing the same task/run records is
        harmless (content-addressed), so two cases can share the chain."""
        task = _task("t-1")
        self._publish(task)
        task_sha = self._sha(task)
        run = _run("r-1", task_sha256=task_sha)
        self._publish(run)
        case = _case_package(
            case_id, ("t-1", task_sha), [("r-1", self._sha(run))]
        )
        self._publish(case)
        return self._sha(case)

    def _publish_decision(self, decision_id: str, case_id: str, **kwargs) -> str:
        case_sha = self._publish_case(case_id)
        decision = _export_decision(
            decision_id, case_id=case_id, case_sha256=case_sha, **kwargs
        )
        self._publish(decision)
        return self._sha(decision)

    # -- decision lineage (anchor-scoped supersedes) ----------------------

    def test_decision_chain_same_case_ok(self) -> None:
        case_sha = self._publish_case("case-1")
        self._publish(_export_decision("d-1", case_sha256=case_sha))
        self._publish(
            _export_decision("d-2", case_sha256=case_sha, supersedes="d-1")
        )
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())

    def test_decision_cross_case_supersedes_scope_mismatch(self) -> None:
        self._publish_decision("d-1", "case-1")
        self._publish_decision("d-2", "case-2", supersedes="d-1")
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        mismatches = [
            v for v in report.violations if v.kind == "lineage_scope_mismatch"
        ]
        self.assertEqual(len(mismatches), 1)
        self.assertIn("case", mismatches[0].detail)
        self.assertIn("case-1", mismatches[0].detail)
        self.assertIn("case-2", mismatches[0].detail)

    def test_decision_fork_is_informational(self) -> None:
        case_sha = self._publish_case("case-1")
        self._publish(_export_decision("d-1", case_sha256=case_sha))
        self._publish(
            _export_decision("d-2", case_sha256=case_sha, supersedes="d-1")
        )
        self._publish(
            _export_decision("d-3", case_sha256=case_sha, supersedes="d-1")
        )
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertIn(("d-1", ("d-2", "d-3")), report.forks)

    def test_decision_self_reference(self) -> None:
        case_sha = self._publish_case("case-1")
        self._publish(
            _export_decision("d-1", case_sha256=case_sha, supersedes="d-1")
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"self_reference"})

    def test_decision_lineage_cycle(self) -> None:
        case_sha = self._publish_case("case-1")
        self._publish(
            _export_decision("d-1", case_sha256=case_sha, supersedes="d-2")
        )
        self._publish(
            _export_decision("d-2", case_sha256=case_sha, supersedes="d-1")
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("lineage_cycle", self._kinds(report))

    # -- the unauthorized_export gate --------------------------------------

    def test_allow_matching_receipt_ok(self) -> None:
        decision_sha = self._publish_decision("d-1", "case-1")
        self._publish(_export_receipt("x-1", decision_sha256=decision_sha))
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())

    def test_deny_decision_receipt_unauthorized(self) -> None:
        decision_sha = self._publish_decision(
            "d-1", "case-1", outcome="deny", export_mode="local_full"
        )
        self._publish(
            _export_receipt(
                "x-1", decision_sha256=decision_sha, export_mode="local_full"
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"unauthorized_export"})
        gate = [v for v in report.violations if v.kind == "unauthorized_export"]
        self.assertEqual(len(gate), 1)
        self.assertIn("denies", gate[0].detail)

    def test_mode_mismatch_receipt_unauthorized(self) -> None:
        decision_sha = self._publish_decision(
            "d-1", "case-1", outcome="allow", export_mode="local_full"
        )
        self._publish(
            _export_receipt(
                "x-1", decision_sha256=decision_sha, export_mode="metrics_only"
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        gate = [v for v in report.violations if v.kind == "unauthorized_export"]
        self.assertEqual(len(gate), 1)
        self.assertIn("metrics_only", gate[0].detail)
        self.assertIn("local_full", gate[0].detail)
        self.assertNotIn("denies", gate[0].detail)

    def test_deny_and_mode_mismatch_raise_single_violation(self) -> None:
        # Both conditions trigger, but the contract is exactly one
        # violation per offending receipt, its detail enumerating both.
        decision_sha = self._publish_decision(
            "d-1", "case-1", outcome="deny", export_mode="local_full"
        )
        self._publish(
            _export_receipt(
                "x-1", decision_sha256=decision_sha, export_mode="metrics_only"
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"unauthorized_export"})
        gate = [v for v in report.violations if v.kind == "unauthorized_export"]
        self.assertEqual(len(gate), 1)
        self.assertIn("denies", gate[0].detail)
        self.assertIn("metrics_only", gate[0].detail)
        self.assertIn("local_full", gate[0].detail)

    def test_receipt_on_superseded_decision_is_not_a_violation(self) -> None:
        # Temporal-ordering boundary (ADR-0004 decision 3): the store
        # carries no clock, so anchoring a receipt to a decision that was
        # later superseded is not per se a violation.
        case_sha = self._publish_case("case-1")
        d1 = _export_decision("d-1", case_sha256=case_sha)
        self._publish(d1)
        self._publish(
            _export_decision("d-2", case_sha256=case_sha, supersedes="d-1")
        )
        self._publish(_export_receipt("x-1", decision_sha256=self._sha(d1)))
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())

    def test_receipt_with_dangling_decision_skips_gate(self) -> None:
        # The broken anchor is reported once, as dangling_reference; the
        # gate stays silent rather than double-counting it.
        self._publish(_export_receipt("x-1", decision_id="d-absent"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"dangling_reference"})

    def test_receipt_with_cross_type_decision_skips_gate(self) -> None:
        case_sha = self._publish_case("case-1")
        self._publish(
            _export_receipt(
                "x-1", decision_id="case-1", decision_sha256=case_sha
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"cross_type_reference"})

    def test_receipt_with_wrong_decision_pin(self) -> None:
        self._publish_decision("d-1", "case-1")
        self._publish(_export_receipt("x-1", decision_sha256="9" * 64))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"pin_mismatch"})

    # -- cross-family identity ---------------------------------------------

    def test_duplicate_id_across_export_families(self) -> None:
        case_sha = self._publish_case("case-1")
        d1 = _export_decision("dup-1", case_sha256=case_sha)
        self._publish(d1)
        self._publish(
            _export_receipt(
                "dup-1", decision_id="dup-1", decision_sha256=self._sha(d1)
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"duplicate_id"})


class VerticalSampleTest(unittest.TestCase):
    """Two hand-built end-to-end samples (ADR-0003 C4 acceptance): a
    desensitized math failure and a synthetic quant leakage case, each
    constructing its store through the public interface and asserting
    claim discipline."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "store"

    def _publish(self, payload: dict):
        return publish_record(json.dumps(payload), root=self.root)

    def _sha(self, payload: dict) -> str:
        return load_record(json.dumps(payload)).sha256

    def test_vertical_math_failure_case(self) -> None:
        task = {
            "schema": "research-task/v1",
            "task_id": "t-math-1",
            "title": "Proof search budget probe",
            "problem_statement": "Search for a short proof of the bracket "
            "identity in the given ring.",
            "domain": "math",
            "scope": {"goal": "bracket-identity", "max_depth": 12},
            "resources": {"budget_minutes": 20},
            "completion_criteria": [
                "Produce a proof term or exhaust the budget."
            ],
            "permissions": [],
            "allowed_external_effects": [],
            "created_at": "2026-08-15T09:00:00Z",
        }
        self._publish(task)
        task_sha = self._sha(task)
        run = {
            "schema": "research-run/v1",
            "run_id": "r-math-1",
            "task": {"task_id": "t-math-1", "sha256": task_sha},
            "executor": {"tool": "proof-search-driver", "version": "0.4.2"},
            "environment": [{"name": "local interpreter", "version": "3.14.5"}],
            "inputs": [
                {"name": "goal file", "kind": "data", "sha256": "5" * 64}
            ],
            "randomness": {"mode": "fixed_seed", "seed": 7},
            "started_at": "2026-08-15T09:05:00Z",
            "completed_at": "2026-08-15T09:25:00Z",
        }
        self._publish(run)
        run_sha = self._sha(run)
        observation = {
            "schema": "research-failure-observation/v1",
            "observation_id": "o-math-1",
            "run": {"run_id": "r-math-1", "sha256": run_sha},
            "observer": {"tool": "run-log-review", "version": "1.0.0"},
            "facts": [
                "The search exhausted the budget at depth 12.",
                "No proof term was produced.",
                "Three branches were abandoned after the budget split.",
            ],
            "observed_at": "2026-08-15T09:30:00Z",
        }
        self._publish(observation)
        observation_sha = self._sha(observation)
        first_analysis = {
            "schema": "research-failure-analysis/v1",
            "analysis_id": "a-math-1",
            "observation": {
                "observation_id": "o-math-1",
                "sha256": observation_sha,
            },
            "hypotheses": [
                "The heuristic may be mis-tuned for this goal shape."
            ],
            "created_at": "2026-08-15T09:40:00Z",
        }
        self._publish(first_analysis)
        first_analysis_sha = self._sha(first_analysis)
        second_analysis = {
            "schema": "research-failure-analysis/v1",
            "analysis_id": "a-math-2",
            "observation": {
                "observation_id": "o-math-1",
                "sha256": observation_sha,
            },
            "hypotheses": [
                "The budget split starved the promising branch."
            ],
            "supersedes": "a-math-1",
            "created_at": "2026-08-15T10:00:00Z",
        }
        self._publish(second_analysis)
        second_analysis_sha = self._sha(second_analysis)
        claim = {
            "schema": "research-claim/v1",
            "claim_id": "c-math-1",
            "claim_type": "mathematical_claim",
            "statement": "The proof search did not close the goal within "
            "the allocated budget.",
            "scope": "The single tested goal, budget, and heuristic settings.",
            "disposition": "inconclusive",
            "evidence_maturity": "draft",
            "supporting_evidence": [],
            "limitations": [
                "Covers only the tested budget and heuristic settings."
            ],
            "non_entailments": [
                "Does not establish that no short proof exists."
            ],
            "created_at": "2026-08-15T10:10:00Z",
        }
        self._publish(claim)
        claim_sha = self._sha(claim)
        case = {
            "schema": "research-case-package/v1",
            "case_id": "case-math-1",
            "title": "Budget-exhausted proof search",
            "task": {"task_id": "t-math-1", "sha256": task_sha},
            "runs": [{"run_id": "r-math-1", "sha256": run_sha}],
            "claims": [{"claim_id": "c-math-1", "sha256": claim_sha}],
            "evidence": [],
            "observations": [
                {"observation_id": "o-math-1", "sha256": observation_sha}
            ],
            "analyses": [
                {"analysis_id": "a-math-1", "sha256": first_analysis_sha},
                {"analysis_id": "a-math-2", "sha256": second_analysis_sha},
            ],
            "privacy_review_status": "pending",
            "created_at": "2026-08-15T10:20:00Z",
        }
        self._publish(case)
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 7)
        # Claim discipline: an inconclusive, draft claim carries no
        # evidence, and its limits and non-entailments are explicit.
        self.assertEqual(claim["disposition"], "inconclusive")
        self.assertEqual(claim["supporting_evidence"], [])
        self.assertTrue(claim["limitations"])
        self.assertTrue(claim["non_entailments"])
        self.assertEqual(case["privacy_review_status"], "pending")

    def test_vertical_quant_leakage_case(self) -> None:
        task = {
            "schema": "research-task/v1",
            "task_id": "t-quant-1",
            "title": "Ranking rule held-back evaluation",
            "problem_statement": "Evaluate whether the candidate ranking "
            "rule adds value on held-back data.",
            "domain": "quant",
            "scope": {"universe": "synthetic instruments", "window": "T1"},
            "resources": {"budget_minutes": 45},
            "completion_criteria": [
                "Produce held-back metrics with a frozen config."
            ],
            "permissions": [],
            "allowed_external_effects": [],
            "created_at": "2026-08-15T11:00:00Z",
        }
        self._publish(task)
        task_sha = self._sha(task)
        run = {
            "schema": "research-run/v1",
            "run_id": "r-quant-1",
            "task": {"task_id": "t-quant-1", "sha256": task_sha},
            "executor": {"tool": "evaluation-runner", "version": "1.2.0"},
            "environment": [{"name": "local interpreter", "version": "3.14.5"}],
            "inputs": [
                {
                    "name": "evaluation config",
                    "kind": "config",
                    "sha256": "6" * 64,
                }
            ],
            "randomness": {"mode": "uncontrolled"},
            "started_at": "2026-08-15T11:05:00Z",
            "completed_at": "2026-08-15T11:50:00Z",
        }
        self._publish(run)
        run_sha = self._sha(run)
        observation = {
            "schema": "research-failure-observation/v1",
            "observation_id": "o-quant-1",
            "run": {"run_id": "r-quant-1", "sha256": run_sha},
            "observer": {"tool": "window-audit", "version": "0.1.0"},
            "facts": [
                "The evaluation window overlaps the training window by "
                "six months.",
                "The reported held-back metrics were computed on the "
                "overlapped slice.",
            ],
            "observed_at": "2026-08-15T12:00:00Z",
        }
        self._publish(observation)
        observation_sha = self._sha(observation)
        analysis = {
            "schema": "research-failure-analysis/v1",
            "analysis_id": "a-quant-1",
            "observation": {
                "observation_id": "o-quant-1",
                "sha256": observation_sha,
            },
            "hypotheses": [
                "The reported uplift may be an artifact of the window "
                "overlap."
            ],
            "created_at": "2026-08-15T12:10:00Z",
        }
        self._publish(analysis)
        analysis_sha = self._sha(analysis)
        evidence = {
            "schema": "research-evidence/v1",
            "evidence_id": "e-quant-1",
            "claim_ids": ["c-quant-1"],
            "producer": {"tool": "window-audit", "version": "0.1.0"},
            "inputs": [
                {
                    "name": "evaluation config",
                    "kind": "config",
                    "sha256": "6" * 64,
                }
            ],
            "generated_at": "2026-08-15T12:20:00Z",
            "content_sha256": "7" * 64,
            "applicability": "Engineering check of the window boundaries.",
            "evidence_level": "engineering",
            "limitations": ["Does not re-run the evaluation."],
        }
        self._publish(evidence)
        evidence_sha = self._sha(evidence)
        claim = {
            "schema": "research-claim/v1",
            "claim_id": "c-quant-1",
            "claim_type": "empirical_claim",
            "statement": "The candidate rule's reported held-back uplift is "
            "an artifact of the window overlap.",
            "scope": "The synthetic evaluation setup of run r-quant-1.",
            "disposition": "refuted",
            "evidence_maturity": "data_accepted",
            "supporting_evidence": [
                {"evidence_id": "e-quant-1", "sha256": evidence_sha}
            ],
            "limitations": [
                "Synthetic data only; no live-market conclusion."
            ],
            "non_entailments": [
                "Does not establish that the rule has no genuine value."
            ],
            "created_at": "2026-08-15T12:30:00Z",
        }
        self._publish(claim)
        claim_sha = self._sha(claim)
        case = {
            "schema": "research-case-package/v1",
            "case_id": "case-quant-1",
            "title": "Window overlap invalidates reported uplift",
            "task": {"task_id": "t-quant-1", "sha256": task_sha},
            "runs": [{"run_id": "r-quant-1", "sha256": run_sha}],
            "claims": [{"claim_id": "c-quant-1", "sha256": claim_sha}],
            "evidence": [{"evidence_id": "e-quant-1", "sha256": evidence_sha}],
            "observations": [
                {"observation_id": "o-quant-1", "sha256": observation_sha}
            ],
            "analyses": [
                {"analysis_id": "a-quant-1", "sha256": analysis_sha}
            ],
            "privacy_review_status": "pending",
            "created_at": "2026-08-15T12:40:00Z",
        }
        self._publish(case)
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 7)
        # Claim discipline: a refuted, data-accepted claim is backed by
        # pinned evidence that lists it back, with explicit limits.
        self.assertTrue(claim["supporting_evidence"])
        self.assertEqual(
            claim["supporting_evidence"][0]["sha256"], evidence_sha
        )
        self.assertIn("c-quant-1", evidence["claim_ids"])
        self.assertTrue(claim["limitations"])
        self.assertTrue(claim["non_entailments"])


def _evaluation_case(case_id: str) -> dict:
    return {
        "schema": "evaluation-case/v1",
        "evaluation_case_id": case_id,
        "title": "Graph test evaluation case",
        "domain": "engineering",
        "claim_type": "engineering_claim",
        "split": "smoke",
        "input": {"content_sha256": "0" * 64},
        "evaluation_contract": {
            "scorer_level": "oracle",
            "contract_sha256": "1" * 64,
        },
        "resources": {},
        "contamination_status": "clean",
        "created_at": "2026-08-14T10:00:00Z",
    }


def _suite(suite_id: str, case_refs: list[tuple[str, str]]) -> dict:
    return {
        "schema": "suite/v1",
        "suite_id": suite_id,
        "title": "Graph test suite",
        "cases": [
            {"evaluation_case_id": cid, "sha256": sha} for cid, sha in case_refs
        ],
        "frozen_at": "2026-08-14T10:05:00Z",
    }


def _evaluation_run(
    run_id: str,
    case_id: str = "ec-1",
    case_sha256: str = "2" * 64,
    suite_id: str = "s-1",
    suite_sha256: str = "3" * 64,
) -> dict:
    return {
        "schema": "evaluation-run/v1",
        "evaluation_run_id": run_id,
        "case": {"evaluation_case_id": case_id, "sha256": case_sha256},
        "suite": {"suite_id": suite_id, "sha256": suite_sha256},
        "candidate": {"candidate_id": "cand-1", "sha256": "4" * 64},
        "envelope": {"envelope_sha256": "5" * 64},
        "runner": {"tool": "unit-test", "version": "1.0"},
        "environment": {},
        "output": {"output_sha256": "6" * 64},
        "scorer": {"level": "oracle", "tool": "unit-test", "version": "1.0"},
        "score_vector": [{"dimension": "exact_match", "value": 1.0}],
        "gate_results": [{"gate": "integrity", "result": "pass"}],
        "verdict": "pass",
        "levels_covered": ["L0", "L1"],
        "generated_at": "2026-08-14T10:10:00Z",
    }


def _comparison_report(
    report_id: str,
    champion: tuple[str, str] = ("er-1", "7" * 64),
    challenger: tuple[str, str] = ("er-2", "8" * 64),
) -> dict:
    return {
        "schema": "comparison-report/v1",
        "report_id": report_id,
        "title": "Graph test comparison report",
        "champion": {"evaluation_run_id": champion[0], "sha256": champion[1]},
        "challenger": {"evaluation_run_id": challenger[0], "sha256": challenger[1]},
        "methods": {"statistics": ["paired_exact_mcnemar"]},
        "score_deltas": [
            {
                "dimension": "exact_match",
                "champion_value": 1.0,
                "challenger_value": 1.0,
            }
        ],
        "gate_summary": [{"gate": "integrity", "result": "pass"}],
        "levels_covered": ["L0", "L1"],
        "conclusion": "Graph test comparison; no significance claimed.",
        "limitations": ["Synthetic graph-test comparison."],
        "generated_at": "2026-08-14T10:15:00Z",
    }


class EvaluationGraphTest(unittest.TestCase):
    """Phase 3 E2: the evaluation record chain (suite -> cases, run -> case
    and suite, report -> two runs) is served entirely by the generic graph
    machinery — dangling/pin/duplicate/cross-type checks — with no new
    composite validator (ADR-0006 decision 1)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "store"

    def _publish(self, payload: dict):
        return publish_record(json.dumps(payload), root=self.root)

    def _kinds(self, report) -> set[str]:
        return {violation.kind for violation in report.violations}

    def _sha(self, payload: dict) -> str:
        return load_record(json.dumps(payload)).sha256

    def _publish_evaluation_case(self, case_id: str = "ec-1") -> str:
        case = _evaluation_case(case_id)
        self._publish(case)
        return self._sha(case)

    def _publish_suite(
        self, suite_id: str = "s-1", case_id: str = "ec-1"
    ) -> tuple[str, str]:
        """Publish the case and a suite containing it; return both hashes."""
        case_sha = self._publish_evaluation_case(case_id)
        suite = _suite(suite_id, [(case_id, case_sha)])
        self._publish(suite)
        return case_sha, self._sha(suite)

    def _publish_run(
        self, run_id: str, case_sha: str, suite_sha: str
    ) -> str:
        run = _evaluation_run(
            run_id, case_sha256=case_sha, suite_sha256=suite_sha
        )
        self._publish(run)
        return self._sha(run)

    def _publish_chain(self) -> tuple[str, str, str, str]:
        """Publish ec-1 <- s-1 <- er-1/er-2 and report rep-1 comparing the
        two runs; return (case_sha, suite_sha, er-1 sha, er-2 sha)."""
        case_sha, suite_sha = self._publish_suite()
        champion_sha = self._publish_run("er-1", case_sha, suite_sha)
        challenger_sha = self._publish_run("er-2", case_sha, suite_sha)
        report = _comparison_report(
            "rep-1",
            champion=("er-1", champion_sha),
            challenger=("er-2", challenger_sha),
        )
        self._publish(report)
        return case_sha, suite_sha, champion_sha, challenger_sha

    # -- full chain ---------------------------------------------------------

    def test_full_evaluation_chain_verifies_ok(self) -> None:
        self._publish_chain()
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 5)
        self.assertEqual(
            report.families,
            {
                "evaluation-case/v1": 1,
                "suite/v1": 1,
                "evaluation-run/v1": 2,
                "comparison-report/v1": 1,
            },
        )

    # -- reference checks ---------------------------------------------------

    def test_run_with_dangling_case(self) -> None:
        case_sha, suite_sha = self._publish_suite()
        self._publish(
            _evaluation_run(
                "er-1",
                case_id="ec-absent",
                case_sha256=case_sha,
                suite_sha256=suite_sha,
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"dangling_reference"})

    def test_suite_with_dangling_case(self) -> None:
        self._publish(_suite("s-1", [("ec-absent", "9" * 64)]))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"dangling_reference"})

    def test_report_with_wrong_challenger_pin(self) -> None:
        case_sha, suite_sha = self._publish_suite()
        champion_sha = self._publish_run("er-1", case_sha, suite_sha)
        self._publish_run("er-2", case_sha, suite_sha)
        self._publish(
            _comparison_report(
                "rep-1",
                champion=("er-1", champion_sha),
                challenger=("er-2", "9" * 64),
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"pin_mismatch"})

    def test_run_case_cross_type_reference(self) -> None:
        case_sha, suite_sha = self._publish_suite()
        self._publish(
            _evaluation_run(
                "er-1", case_id="s-1", case_sha256=suite_sha,
                suite_sha256=suite_sha,
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"cross_type_reference"})

    def test_run_with_dangling_suite(self) -> None:
        case_sha = self._publish_evaluation_case()
        self._publish(
            _evaluation_run("er-1", case_sha256=case_sha, suite_id="s-absent")
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"dangling_reference"})

    # -- cross-family identity -----------------------------------------------

    def test_duplicate_id_across_evaluation_families(self) -> None:
        self._publish(_evaluation_case("dup-1"))
        self._publish(_task("dup-1"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"duplicate_id"})

    def test_duplicate_id_between_run_and_report(self) -> None:
        case_sha, suite_sha = self._publish_suite()
        run_sha = self._publish_run("dup-2", case_sha, suite_sha)
        self._publish(
            _comparison_report(
                "dup-2",
                champion=("dup-2", run_sha),
                challenger=("dup-2", run_sha),
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"duplicate_id"})


def _case_v2(
    case_id: str,
    task: tuple[str, str] = ("t-1", "0" * 64),
    run_refs: list[tuple[str, str]] | None = None,
    derived_from: list[tuple[str, str]] | None = None,
) -> dict:
    return {
        "schema": "research-case-package/v2",
        "case_id": case_id,
        "title": "Graph test v2 case package",
        "task": {"task_id": task[0], "sha256": task[1]},
        "runs": _case_ref(run_refs if run_refs is not None else [("r-1", "2" * 64)], "run_id"),
        "claims": [],
        "evidence": [],
        "observations": [],
        "analyses": [],
        "problem_signature": {
            "summary": "Graph test signature.",
            "signature_sha256": "3" * 64,
        },
        "io_manifest": {
            "inputs": [{"name": "input.bin", "sha256": "4" * 64}],
            "outputs": [{"name": "output.bin", "sha256": "5" * 64}],
        },
        "intermediate_manifest": [],
        "decision_timeline": [
            {"at": "2026-08-17T09:00:00Z", "entry": "Case captured."}
        ],
        "open_questions": [],
        "environment": {"tool": "unit-test", "version": "1.0"},
        "privacy_review_status": "pending",
        "export_mode": "local_full",
        "eligibility": {"status": "eligible", "reasons": []},
        "source": {"project": "unit-tests"},
        "derived_from": _case_ref(derived_from or [], "case_id"),
        "created_at": "2026-08-17T09:05:00Z",
    }


def _pattern(
    pattern_id: str,
    case_refs: list[tuple[str, str]] | None = None,
    supersedes: str | None = None,
) -> dict:
    payload = {
        "schema": "research-pattern/v1",
        "pattern_id": pattern_id,
        "problem_signature": {
            "summary": "Graph test signature.",
            "signature_sha256": "3" * 64,
        },
        "scope": "unit tests",
        "preconditions": [],
        "contraindications": [],
        "successful_tactics": ["Freeze the signature before retrieval."],
        "failed_tactics": [],
        "evidence": {
            "grade": "engineering",
            "rationale": "Synthetic graph-test pattern.",
        },
        "confidence": "medium",
        "source_cases": _case_ref(
            case_refs if case_refs is not None else [("cv-1", "6" * 64)],
            "case_id",
        ),
        "last_validated": "2026-08-17T09:10:00Z",
        "status": "candidate_pattern",
        "transition_rationale": "Initial capture for graph tests.",
        "created_at": "2026-08-17T09:10:00Z",
    }
    if supersedes is not None:
        payload["supersedes"] = supersedes
    return payload


def _heuristic(
    heuristic_id: str,
    case_refs: list[tuple[str, str]] | None = None,
    supersedes: str | None = None,
) -> dict:
    payload = {
        "schema": "heuristic/v1",
        "heuristic_id": heuristic_id,
        "statement": "Record the envelope with every replay.",
        "scope": "unit tests",
        "mode": "advisory",
        "evidence": ["Synthetic graph-test evidence summary."],
        "exception": [],
        "risk": "The rule may not generalize beyond tests.",
        "rollback": "Remove the annotation from the run notes.",
        "status": "candidate",
        "transition_rationale": "Initial capture for graph tests.",
        "regression_cases": _case_ref(
            case_refs if case_refs is not None else [("cv-1", "6" * 64)],
            "case_id",
        ),
        "created_at": "2026-08-17T09:15:00Z",
    }
    if supersedes is not None:
        payload["supersedes"] = supersedes
    return payload


def _reuse_event(
    reuse_event_id: str,
    run: tuple[str, str] = ("r-1", "2" * 64),
    pattern: tuple[str, str] = ("p-1", "6" * 64),
) -> dict:
    return {
        "schema": "reuse-event/v1",
        "reuse_event_id": reuse_event_id,
        "run": {"run_id": run[0], "sha256": run[1]},
        "pattern": {"pattern_id": pattern[0], "sha256": pattern[1]},
        "outcome": "helped",
        "recorded_at": "2026-08-17T09:20:00Z",
    }


class ResearchMemoryGraphTest(unittest.TestCase):
    """Phase 4 M2: the research memory record chain — case-package v2 with
    backward ``derived_from`` lineage, pattern -> source cases, heuristic ->
    regression cases, reuse event -> run and pinned pattern snapshot — is
    served entirely by the generic graph machinery
    (dangling/pin/duplicate/self/cycle) with no new composite validator and
    no new violation kind (ADR-0007 decisions 2, 3, 6, 7)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "store"

    def _publish(self, payload: dict):
        return publish_record(json.dumps(payload), root=self.root)

    def _kinds(self, report) -> set[str]:
        return {violation.kind for violation in report.violations}

    def _sha(self, payload: dict) -> str:
        return load_record(json.dumps(payload)).sha256

    def _publish_base(self) -> tuple[str, str]:
        """Publish task t-1 and run r-1 pinned to it; return both hashes."""
        task = _task("t-1")
        self._publish(task)
        task_sha = self._sha(task)
        run = _run("r-1", task_sha256=task_sha)
        self._publish(run)
        return task_sha, self._sha(run)

    def _publish_case_v2(
        self,
        case_id: str,
        task_sha: str,
        run_sha: str,
        derived_from: list[tuple[str, str]] | None = None,
    ) -> str:
        case = _case_v2(
            case_id,
            task=("t-1", task_sha),
            run_refs=[("r-1", run_sha)],
            derived_from=derived_from,
        )
        self._publish(case)
        return self._sha(case)

    # -- full chain ---------------------------------------------------------

    def test_full_memory_chain_verifies_ok(self) -> None:
        task_sha, run_sha = self._publish_base()
        case_sha = self._publish_case_v2("cv-1", task_sha, run_sha)
        pattern = _pattern("p-1", case_refs=[("cv-1", case_sha)])
        self._publish(pattern)
        pattern_sha = self._sha(pattern)
        self._publish(_heuristic("h-1", case_refs=[("cv-1", case_sha)]))
        self._publish(
            _reuse_event("rev-1", run=("r-1", run_sha), pattern=("p-1", pattern_sha))
        )
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 6)
        self.assertEqual(
            report.families,
            {
                "research-task/v1": 1,
                "research-run/v1": 1,
                "research-case-package/v2": 1,
                "research-pattern/v1": 1,
                "heuristic/v1": 1,
                "reuse-event/v1": 1,
            },
        )

    # -- case v2 derived_from lineage ----------------------------------------

    def test_case_v2_derived_from_chain_ok(self) -> None:
        task_sha, run_sha = self._publish_base()
        first_sha = self._publish_case_v2("cv-1", task_sha, run_sha)
        self._publish_case_v2("cv-2", task_sha, run_sha, derived_from=[("cv-1", first_sha)])
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 4)

    def test_case_v2_derived_from_dangling(self) -> None:
        task_sha, run_sha = self._publish_base()
        self._publish_case_v2("cv-2", task_sha, run_sha, derived_from=[("cv-absent", "9" * 64)])
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"dangling_reference"})

    def test_case_v2_derived_from_wrong_pin(self) -> None:
        task_sha, run_sha = self._publish_base()
        self._publish_case_v2("cv-1", task_sha, run_sha)
        self._publish_case_v2("cv-2", task_sha, run_sha, derived_from=[("cv-1", "9" * 64)])
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"pin_mismatch"})

    def test_case_v2_derived_from_v1_is_cross_type(self) -> None:
        # R35 ledger item 3: derived_from targets v2 only; a reference that
        # resolves to a v1 record is rejected by the generic cross-type check.
        task_sha, run_sha = self._publish_base()
        v1_case = _case_package("cv-old", ("t-1", task_sha), [("r-1", run_sha)])
        self._publish(v1_case)
        self._publish_case_v2(
            "cv-2", task_sha, run_sha, derived_from=[("cv-old", self._sha(v1_case))]
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"cross_type_reference"})

    def test_case_v1_v2_same_id_is_duplicate(self) -> None:
        # R35 ledger item 2: the global duplicate_id check bites across the
        # v1/v2 successor boundary, so v2 cases must start fresh id chains.
        task_sha, run_sha = self._publish_base()
        self._publish(_case_package("dup-c", ("t-1", task_sha), [("r-1", run_sha)]))
        self._publish_case_v2("dup-c", task_sha, run_sha)
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"duplicate_id"})

    def test_case_v2_dangling_run_member(self) -> None:
        task_sha, run_sha = self._publish_base()
        case = _case_v2(
            "cv-1",
            task=("t-1", task_sha),
            run_refs=[("r-absent", "9" * 64)],
        )
        self._publish(case)
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"dangling_reference"})

    # -- pattern references and lifecycle lineage -----------------------------

    def test_pattern_source_case_dangling(self) -> None:
        self._publish(_pattern("p-1", case_refs=[("cv-absent", "9" * 64)]))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"dangling_reference"})

    def test_pattern_source_case_wrong_pin(self) -> None:
        task_sha, run_sha = self._publish_base()
        self._publish_case_v2("cv-1", task_sha, run_sha)
        self._publish(_pattern("p-1", case_refs=[("cv-1", "9" * 64)]))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"pin_mismatch"})

    def test_pattern_supersedes_chain_ok(self) -> None:
        task_sha, run_sha = self._publish_base()
        case_sha = self._publish_case_v2("cv-1", task_sha, run_sha)
        self._publish(_pattern("p-1", case_refs=[("cv-1", case_sha)]))
        self._publish(_pattern("p-2", case_refs=[("cv-1", case_sha)], supersedes="p-1"))
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 5)

    def test_pattern_supersedes_self(self) -> None:
        task_sha, run_sha = self._publish_base()
        case_sha = self._publish_case_v2("cv-1", task_sha, run_sha)
        self._publish(_pattern("p-1", case_refs=[("cv-1", case_sha)], supersedes="p-1"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"self_reference"})

    def test_pattern_supersedes_dangling(self) -> None:
        task_sha, run_sha = self._publish_base()
        case_sha = self._publish_case_v2("cv-1", task_sha, run_sha)
        self._publish(_pattern("p-2", case_refs=[("cv-1", case_sha)], supersedes="p-absent"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"dangling_reference"})

    def test_pattern_supersedes_cross_type(self) -> None:
        task_sha, run_sha = self._publish_base()
        case_sha = self._publish_case_v2("cv-1", task_sha, run_sha)
        self._publish(_pattern("p-2", case_refs=[("cv-1", case_sha)], supersedes="cv-1"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"cross_type_reference"})

    def test_pattern_supersedes_cycle(self) -> None:
        task_sha, run_sha = self._publish_base()
        case_sha = self._publish_case_v2("cv-1", task_sha, run_sha)
        self._publish(_pattern("p-1", case_refs=[("cv-1", case_sha)], supersedes="p-2"))
        self._publish(_pattern("p-2", case_refs=[("cv-1", case_sha)], supersedes="p-1"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"lineage_cycle"})

    def test_pattern_fork_is_informational(self) -> None:
        task_sha, run_sha = self._publish_base()
        case_sha = self._publish_case_v2("cv-1", task_sha, run_sha)
        self._publish(_pattern("p-1", case_refs=[("cv-1", case_sha)]))
        self._publish(_pattern("p-2", case_refs=[("cv-1", case_sha)], supersedes="p-1"))
        self._publish(_pattern("p-3", case_refs=[("cv-1", case_sha)], supersedes="p-1"))
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())

    # -- heuristic ------------------------------------------------------------

    def test_heuristic_regression_case_dangling(self) -> None:
        self._publish(_heuristic("h-1", case_refs=[("cv-absent", "9" * 64)]))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"dangling_reference"})

    def test_heuristic_supersedes_chain_ok(self) -> None:
        task_sha, run_sha = self._publish_base()
        case_sha = self._publish_case_v2("cv-1", task_sha, run_sha)
        self._publish(_heuristic("h-1", case_refs=[("cv-1", case_sha)]))
        self._publish(_heuristic("h-2", case_refs=[("cv-1", case_sha)], supersedes="h-1"))
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())

    # -- reuse event ------------------------------------------------------------

    def test_reuse_event_dangling_run(self) -> None:
        task_sha, run_sha = self._publish_base()
        case_sha = self._publish_case_v2("cv-1", task_sha, run_sha)
        pattern = _pattern("p-1", case_refs=[("cv-1", case_sha)])
        self._publish(pattern)
        self._publish(
            _reuse_event(
                "rev-1",
                run=("r-absent", "9" * 64),
                pattern=("p-1", self._sha(pattern)),
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"dangling_reference"})

    def test_reuse_event_dangling_pattern(self) -> None:
        _, run_sha = self._publish_base()
        self._publish(
            _reuse_event(
                "rev-1",
                run=("r-1", run_sha),
                pattern=("p-absent", "9" * 64),
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"dangling_reference"})

    def test_reuse_event_pattern_cross_type(self) -> None:
        task_sha, run_sha = self._publish_base()
        case_sha = self._publish_case_v2("cv-1", task_sha, run_sha)
        self._publish(
            _reuse_event(
                "rev-1",
                run=("r-1", run_sha),
                pattern=("cv-1", case_sha),
            )
        )
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"cross_type_reference"})

    # -- cross-family identity --------------------------------------------------

    def test_duplicate_id_between_pattern_and_heuristic(self) -> None:
        task_sha, run_sha = self._publish_base()
        case_sha = self._publish_case_v2("cv-1", task_sha, run_sha)
        self._publish(_pattern("dup-1", case_refs=[("cv-1", case_sha)]))
        self._publish(_heuristic("dup-1", case_refs=[("cv-1", case_sha)]))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertEqual(self._kinds(report), {"duplicate_id"})


if __name__ == "__main__":
    unittest.main()
