"""Unit tests for publish_record: append-only identity, atomicity, receipts."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import research_evolution.core._store as store_module
import research_evolution.core.publication as publication_module
from research_evolution.core import (
    PublicationError,
    RecordValidationError,
    StoreIntegrityError,
    canonical_bytes,
    canonical_sha256,
    load_record,
    publish_record,
    verify_record_graph,
)


def _task(task_id: str, title: str = "Unit test task") -> dict:
    return {
        "schema": "research-task/v1",
        "task_id": task_id,
        "title": title,
        "problem_statement": "Exercise the publication path.",
        "domain": "engineering",
        "scope": {},
        "resources": {},
        "completion_criteria": ["Publishes."],
        "permissions": [],
        "allowed_external_effects": [],
        "created_at": "2026-08-14T07:00:00Z",
    }


def _claim(claim_id: str, supersedes: str | None = None) -> dict:
    payload = {
        "schema": "research-claim/v1",
        "claim_id": claim_id,
        "claim_type": "engineering_claim",
        "statement": "The store test harness works.",
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
    return payload


def _run(run_id: str, task_id: str = "t-1", task_sha256: str = "0" * 64) -> dict:
    return {
        "schema": "research-run/v1",
        "run_id": run_id,
        "task": {
            "task_id": task_id,
            "sha256": task_sha256,
        },
        "executor": {"tool": "unit-test", "version": "1.0.0"},
        "environment": [{"name": "local interpreter", "version": "3.14.5"}],
        "inputs": [
            {"name": "fixture set", "kind": "case", "sha256": "1" * 64}
        ],
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
        "observer": {"tool": "unit-test", "version": "1.0.0"},
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


def _case(
    case_id: str,
    task_id: str = "t-1",
    task_sha256: str = "0" * 64,
    runs: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "schema": "research-case-package/v1",
        "case_id": case_id,
        "title": "Unit test case package",
        "task": {"task_id": task_id, "sha256": task_sha256},
        "runs": runs
        if runs is not None
        else [{"run_id": "r-1", "sha256": "4" * 64}],
        "claims": [],
        "evidence": [],
        "observations": [],
        "analyses": [],
        "privacy_review_status": "pending",
        "created_at": "2026-08-14T08:20:00Z",
    }


def _tree_snapshot(root: Path) -> dict[str, str]:
    """{relative path: sha256} for every file under root, including .tmp."""
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


class PublishTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "store"

    def _publish(self, payload: dict):
        return publish_record(json.dumps(payload), root=self.root)

    def test_publish_creates_content_addressed_record(self) -> None:
        payload = _task("t-1")
        receipt = self._publish(payload)
        record = load_record(json.dumps(payload))
        self.assertFalse(receipt.already_present)
        self.assertEqual(receipt.record_id, "t-1")
        self.assertEqual(receipt.schema_id, "research-task/v1")
        self.assertEqual(receipt.sha256, record.sha256)
        self.assertEqual(
            receipt.path, f"records/research-task/v1/{record.sha256}.json"
        )
        stored = self.root / receipt.path
        self.assertTrue(stored.is_file())
        self.assertEqual(stored.read_bytes(), record.canonical_bytes)
        self.assertTrue((self.root / "manifest.json").is_file())
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 1)

    def test_receipt_binds_manifest_hash(self) -> None:
        receipt = self._publish(_task("t-1"))
        manifest_raw = (self.root / "manifest.json").read_bytes()
        self.assertEqual(
            receipt.manifest_sha256, hashlib.sha256(manifest_raw).hexdigest()
        )
        keys = set(receipt.to_dict())
        self.assertEqual(
            keys,
            {"schema", "id", "sha256", "path", "already_present", "manifest_sha256"},
        )

    def test_exact_replay_changes_nothing_on_disk(self) -> None:
        payload = _task("t-1")
        first = self._publish(payload)
        before = _tree_snapshot(self.root)
        second = self._publish(payload)
        after = _tree_snapshot(self.root)
        self.assertFalse(first.already_present)
        self.assertTrue(second.already_present)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.path, second.path)
        self.assertEqual(first.manifest_sha256, second.manifest_sha256)
        self.assertEqual(before, after)

    def test_same_id_different_content_fails_closed(self) -> None:
        self._publish(_task("t-1", title="original"))
        before = _tree_snapshot(self.root)
        with self.assertRaises(PublicationError) as caught:
            self._publish(_task("t-1", title="mutated"))
        self.assertIn("supersedes", str(caught.exception))
        self.assertEqual(before, _tree_snapshot(self.root))
        self.assertTrue(verify_record_graph(self.root).ok)

    def test_revision_is_new_id_plus_supersedes(self) -> None:
        self._publish(_claim("c-1"))
        receipt = self._publish(_claim("c-2", supersedes="c-1"))
        self.assertFalse(receipt.already_present)
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.families, {"research-claim/v1": 2})

    def test_interrupted_publish_leaves_no_visible_half_record(self) -> None:
        # Simulate a crash between the atomic record link and the manifest
        # replace on the second publish: the record file exists but the
        # manifest still lists only the first record.
        self._publish(_task("t-0"))
        payload = _task("t-1")
        with mock.patch.object(
            publication_module, "replace_manifest", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                self._publish(payload)
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("extra_record", {v.kind for v in report.violations})
        # Republishing the identical record heals the store without rewriting
        # the existing bytes (the file is adopted, not recreated).
        receipt = self._publish(payload)
        self.assertFalse(receipt.already_present)
        self.assertTrue(verify_record_graph(self.root).ok)

    def test_first_publish_crash_window_fails_closed(self) -> None:
        # Crash before the manifest ever exists: records/ without
        # manifest.json. Verification flags it, and publish refuses to write
        # into the inconsistent store until an operator removes the residue.
        with mock.patch.object(
            publication_module, "replace_manifest", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                self._publish(_task("t-1"))
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("manifest_missing", {v.kind for v in report.violations})
        with self.assertRaises(StoreIntegrityError):
            self._publish(_task("t-1"))

    def test_tmp_residue_is_invisible_to_verification(self) -> None:
        self._publish(_task("t-1"))
        tmp_dir = self.root / ".tmp"
        tmp_dir.mkdir(exist_ok=True)
        (tmp_dir / ".rc-orphan.tmp").write_bytes(b"partial write residue")
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())

    def test_tampered_manifest_refuses_further_publish(self) -> None:
        self._publish(_task("t-1"))
        before = _tree_snapshot(self.root)
        manifest = self.root / "manifest.json"
        # Valid JSON, same content, but pretty-printed: not canonical bytes.
        obj = json.loads(manifest.read_text(encoding="utf-8"))
        manifest.write_text(json.dumps(obj, indent=2), encoding="utf-8")
        with self.assertRaises(StoreIntegrityError):
            self._publish(_task("t-2"))
        after = _tree_snapshot(self.root)
        self.assertEqual(set(before) | {"manifest.json"}, set(after))
        self.assertNotIn("t-2", json.dumps(after))

    def test_garbage_manifest_refuses_publish(self) -> None:
        self._publish(_task("t-1"))
        (self.root / "manifest.json").write_bytes(b"not json at all")
        with self.assertRaises(StoreIntegrityError):
            self._publish(_task("t-2"))

    def test_already_present_verifies_bytes_before_claiming(self) -> None:
        payload = _task("t-1")
        receipt = self._publish(payload)
        (self.root / receipt.path).unlink()
        with self.assertRaises(StoreIntegrityError):
            self._publish(payload)

    def test_concurrent_publish_same_record_is_serialized(self) -> None:
        payload = json.dumps(_task("t-1"))
        barrier = threading.Barrier(2)
        receipts: list = []
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                barrier.wait(timeout=10)
                receipts.append(publish_record(payload, root=self.root))
            except BaseException as exc:  # pragma: no cover - failure surface
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(len(receipts), 2)
        created = [r for r in receipts if not r.already_present]
        self.assertEqual(len(created), 1)
        self.assertTrue(verify_record_graph(self.root).ok)

    def test_concurrent_publish_distinct_records_keeps_both(self) -> None:
        barrier = threading.Barrier(2)
        receipts: list = []
        errors: list[BaseException] = []

        def worker(payload: dict) -> None:
            try:
                barrier.wait(timeout=10)
                receipts.append(publish_record(json.dumps(payload), root=self.root))
            except BaseException as exc:  # pragma: no cover - failure surface
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(_task("t-1"),)),
            threading.Thread(target=worker, args=(_task("t-2"),)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(len(receipts), 2)
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 2)

    def test_family_without_identity_field_fails_closed(self) -> None:
        # A schema the kernel validates but the store has no identity field
        # for must not be publishable.
        schema_root = Path(self._tmp.name) / "schemas"
        shutil.copytree(
            Path(__file__).resolve().parents[2] / "schemas" / "core", schema_root
        )
        (schema_root / "research-extra-v1.schema.json").write_text(
            json.dumps(
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "research-extra/v1",
                    "title": "Extra v1",
                    "type": "object",
                    "required": ["schema"],
                    "properties": {"schema": {"const": "research-extra/v1"}},
                    "additionalProperties": False,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(PublicationError):
            publish_record(
                '{"schema": "research-extra/v1"}',
                root=self.root,
                schema_root=schema_root,
            )
        self.assertEqual(_tree_snapshot(self.root), {})

    def test_phase_1c_chain_publishes_and_verifies(self) -> None:
        # C3 unlocks the three hierarchical families; a fully pinned
        # task -> run -> observation -> analysis chain must verify clean.
        task = _task("t-1")
        self._publish(task)
        task_sha = load_record(json.dumps(task)).sha256
        run_receipt = self._publish(_run("r-1", task_sha256=task_sha))
        self.assertEqual(run_receipt.record_id, "r-1")
        self.assertEqual(run_receipt.schema_id, "research-run/v1")
        self.assertTrue(
            run_receipt.path.startswith("records/research-run/v1/")
        )
        observation_receipt = self._publish(
            _observation("o-1", run_sha256=run_receipt.sha256)
        )
        analysis_receipt = self._publish(
            _analysis(
                "a-1",
                observation_sha256=observation_receipt.sha256,
            )
        )
        self.assertEqual(analysis_receipt.record_id, "a-1")
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 4)
        self.assertEqual(report.families["research-run/v1"], 1)

    def test_case_package_publishes_and_verifies(self) -> None:
        # C4 closes the window: the case package is publishable and the
        # graph fully understands it (pins, closure, membership).
        task = _task("t-1")
        self._publish(task)
        task_sha = load_record(json.dumps(task)).sha256
        run_receipt = self._publish(_run("r-1", task_sha256=task_sha))
        case_receipt = self._publish(
            _case(
                "case-1",
                task_sha256=task_sha,
                runs=[{"run_id": "r-1", "sha256": run_receipt.sha256}],
            )
        )
        self.assertEqual(case_receipt.record_id, "case-1")
        self.assertEqual(case_receipt.schema_id, "research-case-package/v1")
        self.assertTrue(
            case_receipt.path.startswith("records/research-case-package/v1/")
        )
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 3)


def _make_junction(link: Path, target: Path) -> None:
    """Create a Windows directory junction (requires no admin rights)."""
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
    )


class PublishGuardTest(unittest.TestCase):
    """Fail-closed publish guards: dirty stores and hostile filesystem nodes."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "store"

    def _publish(self, payload: dict):
        return publish_record(json.dumps(payload), root=self.root)

    def _assert_blocked_without_writes(self, corrupt) -> None:
        """A dirty store rejects the next publish before writing anything."""
        first = self._publish(_task("t-1"))
        corrupt(first)
        before = _tree_snapshot(self.root)
        with self.assertRaises(StoreIntegrityError):
            self._publish(_task("t-2"))
        self.assertEqual(_tree_snapshot(self.root), before)

    # -- publish requires a clean store -------------------------------------

    def test_publish_blocked_when_existing_record_deleted(self) -> None:
        def corrupt(receipt) -> None:
            (self.root / receipt.path).unlink()

        self._assert_blocked_without_writes(corrupt)
        report = verify_record_graph(self.root)
        self.assertIn("missing_record", {v.kind for v in report.violations})

    def test_publish_blocked_when_existing_record_corrupted(self) -> None:
        def corrupt(receipt) -> None:
            (self.root / receipt.path).write_bytes(b"garbage")

        self._assert_blocked_without_writes(corrupt)
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)

    def test_publish_blocked_when_manifest_entry_tampered(self) -> None:
        def corrupt(receipt) -> None:
            manifest = self.root / "manifest.json"
            obj = json.loads(manifest.read_text(encoding="utf-8"))
            obj["records"][0]["id"] = "t-1-tampered"
            manifest.write_bytes(canonical_bytes(obj))

        self._assert_blocked_without_writes(corrupt)
        report = verify_record_graph(self.root)
        self.assertIn(
            "record_identity_mismatch", {v.kind for v in report.violations}
        )

    def test_publish_blocked_when_unregistered_record_present(self) -> None:
        def corrupt(receipt) -> None:
            orphan = load_record(json.dumps(_task("t-9")))
            target = (
                self.root
                / "records"
                / "research-task"
                / "v1"
                / f"{orphan.sha256}.json"
            )
            target.write_bytes(orphan.canonical_bytes)

        self._assert_blocked_without_writes(corrupt)
        report = verify_record_graph(self.root)
        self.assertIn("extra_record", {v.kind for v in report.violations})

    def test_crash_orphan_of_pending_record_is_adopted(self) -> None:
        # The narrow exception: a publish that crashed after the record link
        # but before the manifest replace leaves the record file as an
        # unregistered extra; republishing that very record adopts the
        # byte-identical orphan without a rewrite.
        self._publish(_task("t-0"))
        payload = _task("t-1")
        record = load_record(json.dumps(payload))
        orphan = (
            self.root
            / "records"
            / "research-task"
            / "v1"
            / f"{record.sha256}.json"
        )
        orphan.write_bytes(record.canonical_bytes)
        receipt = self._publish(payload)
        self.assertFalse(receipt.already_present)
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 2)

    def _place_orphan(self, payload: dict) -> None:
        """Simulate a crash-window orphan: the record file linked into the
        store without its manifest entry."""
        record = load_record(json.dumps(payload))
        orphan = (
            self.root
            / "records"
            / "research-task"
            / "v1"
            / f"{record.sha256}.json"
        )
        orphan.write_bytes(record.canonical_bytes)

    def test_orphan_does_not_mask_noncanonical_manifest(self) -> None:
        # The tolerated finding must be the *sole* finding: a non-canonical
        # manifest hiding behind the target orphan blocks the publish.
        self._publish(_task("t-0"))
        manifest = self.root / "manifest.json"
        obj = json.loads(manifest.read_text(encoding="utf-8"))
        manifest.write_bytes(json.dumps(obj, indent=2).encode("utf-8"))
        payload = _task("t-1")
        self._place_orphan(payload)
        before = _tree_snapshot(self.root)
        with self.assertRaises(StoreIntegrityError):
            self._publish(payload)
        self.assertEqual(_tree_snapshot(self.root), before)
        kinds = {v.kind for v in verify_record_graph(self.root).violations}
        self.assertIn("extra_record", kinds)
        self.assertIn("manifest_not_deterministic", kinds)

    def test_orphan_does_not_mask_reordered_manifest(self) -> None:
        # Same content but wrong entry order: canonically encoded, yet not
        # the deterministic rebuild — still must not be masked by the orphan.
        self._publish(_task("t-0a"))
        self._publish(_task("t-0b"))
        manifest = self.root / "manifest.json"
        obj = json.loads(manifest.read_text(encoding="utf-8"))
        obj["records"] = list(reversed(obj["records"]))
        manifest.write_bytes(canonical_bytes(obj))
        payload = _task("t-1")
        self._place_orphan(payload)
        before = _tree_snapshot(self.root)
        with self.assertRaises(StoreIntegrityError):
            self._publish(payload)
        self.assertEqual(_tree_snapshot(self.root), before)
        kinds = {v.kind for v in verify_record_graph(self.root).violations}
        self.assertIn("extra_record", kinds)
        self.assertIn("manifest_not_deterministic", kinds)

    # -- reparse points never let writes escape the root ---------------------

    @unittest.skipUnless(os.name == "nt", "directory junctions are Windows-only")
    def test_family_version_junction_rejected(self) -> None:
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        family = self.root / "records" / "research-task"
        family.mkdir(parents=True)
        _make_junction(family / "v1", outside)
        with self.assertRaises(StoreIntegrityError):
            self._publish(_task("t-1"))
        self.assertEqual(list(outside.iterdir()), [])
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("reparse_point", {v.kind for v in report.violations})

    @unittest.skipUnless(os.name == "nt", "directory junctions are Windows-only")
    def test_records_root_junction_rejected(self) -> None:
        outside = Path(self._tmp.name) / "outside-records"
        outside.mkdir()
        self.root.mkdir()
        _make_junction(self.root / "records", outside)
        with self.assertRaises(StoreIntegrityError):
            self._publish(_task("t-1"))
        self.assertEqual(list(outside.iterdir()), [])
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("reparse_point", {v.kind for v in report.violations})

    @unittest.skipUnless(os.name == "nt", "directory junctions are Windows-only")
    def test_store_root_junction_rejected(self) -> None:
        # The caller-provided root itself is the containment boundary: a
        # junction here would silently relocate every store byte.
        outside = Path(self._tmp.name) / "real-store"
        outside.mkdir()
        linked = Path(self._tmp.name) / "store-link"
        _make_junction(linked, outside)
        with self.assertRaises(StoreIntegrityError):
            publish_record(json.dumps(_task("t-1")), root=linked)
        self.assertEqual(list(outside.iterdir()), [])
        report = verify_record_graph(linked)
        self.assertFalse(report.ok)
        self.assertIn("reparse_point", {v.kind for v in report.violations})

    @unittest.skipUnless(os.name == "nt", "directory junctions are Windows-only")
    def test_nested_root_through_junction_rejected_pending(self) -> None:
        # Lexical root *below* a junction, store not yet created: publishing
        # must not pass through the ancestor junction.
        outside = Path(self._tmp.name) / "real-target"
        outside.mkdir()
        junction = Path(self._tmp.name) / "link-dir"
        _make_junction(junction, outside)
        nested = junction / "nested-store"
        with self.assertRaises(StoreIntegrityError):
            publish_record(json.dumps(_task("t-1")), root=nested)
        self.assertEqual(list(outside.iterdir()), [])
        report = verify_record_graph(nested)
        self.assertFalse(report.ok)
        self.assertIn("reparse_point", {v.kind for v in report.violations})

    @unittest.skipUnless(os.name == "nt", "directory junctions are Windows-only")
    def test_nested_root_through_junction_rejected_existing(self) -> None:
        # The underlying store may be perfectly healthy; the lexical path
        # through a junction is still rejected, with zero writes.
        outside = Path(self._tmp.name) / "real-target"
        real_store = outside / "nested-store"
        publish_record(json.dumps(_task("t-0")), root=real_store)
        junction = Path(self._tmp.name) / "link-dir"
        _make_junction(junction, outside)
        nested = junction / "nested-store"
        before = _tree_snapshot(real_store)
        with self.assertRaises(StoreIntegrityError):
            publish_record(json.dumps(_task("t-1")), root=nested)
        self.assertEqual(_tree_snapshot(real_store), before)
        report = verify_record_graph(nested)
        self.assertFalse(report.ok)
        self.assertIn("reparse_point", {v.kind for v in report.violations})
        # The underlying store, addressed by its real path, stays healthy.
        self.assertTrue(verify_record_graph(real_store).ok)

    @unittest.skipUnless(os.name == "nt", "directory junctions are Windows-only")
    def test_relative_root_under_junction_cwd_rejected(self) -> None:
        # A relative root is interpreted against the process cwd; when the
        # cwd itself sits under a junction, the lexical check must see it.
        outside = Path(self._tmp.name) / "real-target"
        outside.mkdir()
        junction = Path(self._tmp.name) / "link-dir"
        _make_junction(junction, outside)
        cwd = Path(os.getcwd())
        try:
            os.chdir(junction)
            with self.assertRaises(StoreIntegrityError):
                publish_record(json.dumps(_task("t-1")), root=Path("nested-store"))
            report = verify_record_graph(Path("nested-store"))
            self.assertFalse(report.ok)
            self.assertIn("reparse_point", {v.kind for v in report.violations})
        finally:
            os.chdir(cwd)
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "directory junctions are Windows-only")
    def test_verify_preflight_never_resolves(self) -> None:
        # Even if path resolution fails *on the store path*, verification
        # reports a violation instead of leaking the error — preflight is
        # lexical and precedes locking, and the lock key never resolves.
        # (The schema registry resolves its own trusted schema_root, so the
        # denial is scoped to the store sandbox.)
        self._publish(_task("t-1"))
        outside = Path(self._tmp.name) / "real-target"
        outside.mkdir()
        linked = Path(self._tmp.name) / "store-link"
        _make_junction(linked, outside)
        sandbox = str(Path(self._tmp.name))
        real_resolve = Path.resolve

        def flaky_resolve(path_self, *args, **kwargs):
            if str(path_self).startswith(sandbox):
                raise OSError("simulated resolve failure")
            return real_resolve(path_self, *args, **kwargs)

        with mock.patch.object(Path, "resolve", flaky_resolve):
            healthy = verify_record_graph(self.root)
            self.assertTrue(healthy.ok, healthy.to_dict())
            report = verify_record_graph(linked)
            self.assertFalse(report.ok)
            self.assertIn("reparse_point", {v.kind for v in report.violations})

    def test_relative_root_pinned_against_midcall_cwd_change(self) -> None:
        # The checked object and the written/verified object must be the
        # same: the root is pinned to its lexical absolute form at entry, so
        # switching the process cwd *mid-call* cannot redirect reconciliation
        # or writes to a different, unchecked location. Pre-pinning this
        # deterministically failed (the mid-call cwd made reconcile see a
        # nonexistent root and the publish raised StoreIntegrityError).
        dir_a = Path(self._tmp.name) / "dir-a"
        dir_b = Path(self._tmp.name) / "dir-b"
        dir_a.mkdir()
        dir_b.mkdir()
        publish_record(json.dumps(_task("t-0")), root=dir_a / "store")
        cwd = Path(os.getcwd())
        real_reconcile = publication_module.reconcile_store
        switches = 0

        def chdir_reconcile(root, **kwargs):
            nonlocal switches
            switches += 1
            os.chdir(dir_b)  # in-process mid-call cwd switch
            return real_reconcile(root, **kwargs)

        try:
            os.chdir(dir_a)
            with mock.patch.object(
                publication_module, "reconcile_store", chdir_reconcile
            ):
                receipt = publish_record(json.dumps(_task("t-1")), root=Path("store"))
            self.assertEqual(switches, 1)
            # Reset the entry cwd for the verify call; its own mid-call
            # switch must not change what gets verified either.
            os.chdir(dir_a)
            with mock.patch.object(
                publication_module, "reconcile_store", chdir_reconcile
            ):
                report = verify_record_graph(Path("store"))
        finally:
            os.chdir(cwd)
        self.assertEqual(switches, 2)
        self.assertFalse(receipt.already_present)
        self.assertEqual(receipt.record_id, "t-1")
        # Everything landed in the checked store; dir-b was never touched.
        self.assertEqual(list(dir_b.iterdir()), [])
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 2)
        self.assertTrue(verify_record_graph(dir_a / "store").ok)

    def test_publish_pins_root_before_load_record(self) -> None:
        # Regression: pinning is the *first* step, before load_record or any
        # other callback-capable work. The wrapper switches cwd during
        # load_record; pre-fix the entire store was created under dir-b.
        dir_a = Path(self._tmp.name) / "dir-a"
        dir_b = Path(self._tmp.name) / "dir-b"
        dir_a.mkdir()
        dir_b.mkdir()
        cwd = Path(os.getcwd())
        real_load = publication_module.load_record
        switched = False

        def chdir_load(source, **kwargs):
            nonlocal switched
            switched = True
            os.chdir(dir_b)
            return real_load(source, **kwargs)

        try:
            os.chdir(dir_a)
            with mock.patch.object(publication_module, "load_record", chdir_load):
                receipt = publish_record(
                    json.dumps(_task("t-1")), root=Path("store")
                )
        finally:
            os.chdir(cwd)
        self.assertTrue(switched)
        self.assertFalse(receipt.already_present)
        self.assertEqual(receipt.record_id, "t-1")
        self.assertEqual(list(dir_b.iterdir()), [])
        self.assertTrue(verify_record_graph(dir_a / "store").ok)

    def test_verify_pins_relative_schema_root(self) -> None:
        # Regression: a relative schema_root is pinned at entry, so a
        # mid-call cwd switch cannot change which schema registry validates
        # the records. Pre-fix this probe turned a strict record_invalid
        # into a false ok=True under the weak schema.
        dir_a = Path(self._tmp.name) / "dir-a"
        dir_b = Path(self._tmp.name) / "dir-b"
        dir_a.mkdir()
        dir_b.mkdir()
        repo_schemas = Path(__file__).resolve().parents[2] / "schemas" / "core"
        shutil.copytree(repo_schemas, dir_a / "schemas")
        shutil.copytree(repo_schemas, dir_b / "schemas")
        # Weaken dir-b's task schema: "title" is no longer required.
        weak_task = dir_b / "schemas" / "research-task-v1.schema.json"
        weak = json.loads(weak_task.read_text(encoding="utf-8"))
        weak["required"] = [name for name in weak["required"] if name != "title"]
        weak_task.write_bytes(canonical_bytes(weak))

        # A record valid only under the weakened schema (no title).
        payload = _task("t-1")
        del payload["title"]
        sha = canonical_sha256(payload)
        store = Path(self._tmp.name) / "store"
        record_file = store / "records" / "research-task" / "v1" / f"{sha}.json"
        record_file.parent.mkdir(parents=True)
        record_file.write_bytes(canonical_bytes(payload))
        manifest_obj = {
            "manifest": "core-manifest/v1",
            "records": [
                {
                    "family": "research-task/v1",
                    "id": "t-1",
                    "sha256": sha,
                    "path": f"records/research-task/v1/{sha}.json",
                }
            ],
        }
        (store / "manifest.json").write_bytes(canonical_bytes(manifest_obj))

        real_load = store_module.load_record
        switched = False
        cwd = Path(os.getcwd())

        def chdir_load(source, **kwargs):
            nonlocal switched
            switched = True
            os.chdir(dir_b)
            return real_load(source, **kwargs)

        try:
            os.chdir(dir_a)
            with mock.patch.object(store_module, "load_record", chdir_load):
                report = verify_record_graph(store, schema_root=Path("schemas"))
        finally:
            os.chdir(cwd)
        self.assertTrue(switched)
        # The pinned strict schema governs: the title-less record is invalid.
        self.assertFalse(report.ok)
        self.assertIn("record_invalid", {v.kind for v in report.violations})

    def test_publish_single_cwd_snapshot_for_root_and_schema(self) -> None:
        # Regression: both pins derive from ONE entry cwd snapshot. The hook
        # fires only on a per-argument abspath of "schemas" (the two-call
        # mutation shape); the fixed code never re-reads cwd after the
        # snapshot, so the switch is inert and the strict schema still
        # rejects the record.
        dir_a = Path(self._tmp.name) / "dir-a"
        dir_b = Path(self._tmp.name) / "dir-b"
        dir_a.mkdir()
        dir_b.mkdir()
        repo_schemas = Path(__file__).resolve().parents[2] / "schemas" / "core"
        shutil.copytree(repo_schemas, dir_a / "schemas")
        shutil.copytree(repo_schemas, dir_b / "schemas")
        # Weaken dir-b's task schema: "title" is no longer required.
        weak_task = dir_b / "schemas" / "research-task-v1.schema.json"
        weak = json.loads(weak_task.read_text(encoding="utf-8"))
        weak["required"] = [name for name in weak["required"] if name != "title"]
        weak_task.write_bytes(canonical_bytes(weak))
        # A record valid only under the weakened schema (no title).
        payload = _task("t-1")
        del payload["title"]
        cwd = Path(os.getcwd())
        real_abspath = os.path.abspath

        def chdir_abspath(path, *args, **kwargs):
            if os.path.basename(os.fspath(path).rstrip("\\/")) == "schemas":
                os.chdir(dir_b)
            return real_abspath(path, *args, **kwargs)

        try:
            os.chdir(dir_a)
            with mock.patch("os.path.abspath", side_effect=chdir_abspath):
                with self.assertRaises(RecordValidationError):
                    publish_record(
                        json.dumps(payload),
                        root=Path("store"),
                        schema_root=Path("schemas"),
                    )
        finally:
            os.chdir(cwd)
        # The publish died at validation: nothing was written anywhere.
        self.assertFalse((dir_a / "store").exists())
        self.assertEqual(sorted(p.name for p in dir_b.iterdir()), ["schemas"])

    # -- write-path I/O failures fail closed with StoreIntegrityError ---------

    def test_root_ancestor_plain_file_fails_closed(self) -> None:
        # A plain-file ancestor is not a reparse point, so the preflight
        # passes it; the failure surfaces at directory creation (Windows
        # lstat even reports the child as simply absent). It must raise
        # StoreIntegrityError — never a bare OSError — and write nothing.
        blocker = Path(self._tmp.name) / "blocker"
        blocker.write_bytes(b"plain file")
        root = blocker / "store"
        with self.assertRaises(StoreIntegrityError):
            publish_record(json.dumps(_task("t-1")), root=root)
        self.assertEqual(blocker.read_bytes(), b"plain file")
        self.assertEqual(list(Path(self._tmp.name).iterdir()), [blocker])

    def test_directory_creation_failure_is_wrapped(self) -> None:
        # A denied mkdir (e.g. a read-only parent) is wrapped, not leaked.
        def denied_mkdir(self, *args, **kwargs):
            raise PermissionError("simulated denial")

        with mock.patch.object(Path, "mkdir", denied_mkdir):
            with self.assertRaises(StoreIntegrityError):
                self._publish(_task("t-1"))
        self.assertFalse(self.root.exists())

    def test_temp_staging_failure_is_wrapped(self) -> None:
        # A denied mkstemp (e.g. an unwritable .tmp) is wrapped, not leaked,
        # and leaves neither a record nor a manifest behind.
        def denied_mkstemp(*args, **kwargs):
            raise PermissionError("simulated denial")

        with mock.patch.object(store_module.tempfile, "mkstemp", denied_mkstemp):
            with self.assertRaises(StoreIntegrityError):
                self._publish(_task("t-1"))
        self.assertFalse((self.root / "manifest.json").exists())
        leftovers = [p for p in self.root.rglob("*") if p.is_file()]
        self.assertEqual(leftovers, [])

    def test_staged_write_failure_is_wrapped(self) -> None:
        # write/flush/fsync failures (disk full, quota) are wrapped, not
        # leaked, and the staged temp file is cleaned up.
        with mock.patch(
            "os.fsync", side_effect=OSError(28, "No space left on device")
        ):
            with self.assertRaises(StoreIntegrityError):
                self._publish(_task("t-1"))
        self.assertFalse((self.root / "manifest.json").exists())
        leftovers = [p for p in self.root.rglob("*") if p.is_file()]
        self.assertEqual(leftovers, [])

    def test_record_link_failure_is_wrapped(self) -> None:
        # os.link failures other than FileExistsError (e.g. permission
        # denied) are wrapped, not leaked; no record or manifest remains.
        with mock.patch("os.link", side_effect=PermissionError("denied")):
            with self.assertRaises(StoreIntegrityError):
                self._publish(_task("t-1"))
        self.assertFalse((self.root / "manifest.json").exists())
        leftovers = [p for p in self.root.rglob("*") if p.is_file()]
        self.assertEqual(leftovers, [])

    def test_manifest_replace_failure_is_wrapped(self) -> None:
        # os.replace failure (e.g. a read-only manifest) is wrapped, not
        # leaked. The already-linked record stays as a documented
        # crash-window orphan; the manifest keeps its prior bytes.
        self._publish(_task("t-1"))
        manifest = self.root / "manifest.json"
        before = manifest.read_bytes()
        with mock.patch("os.replace", side_effect=PermissionError("denied")):
            with self.assertRaises(StoreIntegrityError):
                self._publish(_task("t-2"))
        self.assertEqual(manifest.read_bytes(), before)
        self.assertEqual(list((self.root / ".tmp").iterdir()), [])
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("extra_record", {v.kind for v in report.violations})

    def test_unlink_cleanup_failure_does_not_mask_primary_error(self) -> None:
        # A failing cleanup unlink (e.g. a transient antivirus lock on the
        # staged file) must neither leak nor mask the wrapped primary
        # error: the caller still sees the StoreIntegrityError.
        real_unlink = Path.unlink

        def av_locked(self, *args, **kwargs):
            if self.name.startswith((".rc-", ".mf-")):
                raise PermissionError("cleanup denied (AV lock)")
            return real_unlink(self, *args, **kwargs)

        with mock.patch(
            "os.fsync", side_effect=OSError(28, "No space left on device")
        ):
            with mock.patch.object(Path, "unlink", av_locked):
                with self.assertRaises(StoreIntegrityError) as caught:
                    self._publish(_task("t-1"))
        self.assertIn("staged bytes", str(caught.exception))
        # The leftover staged file is verification-invisible; the store
        # shows the documented first-publish crash-window state.
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("manifest_missing", {v.kind for v in report.violations})

    def test_unlink_cleanup_failure_does_not_break_commit(self) -> None:
        # Cleanup failure alone leaves only an invisible .tmp orphan: the
        # publish commits normally and verification stays green.
        real_unlink = Path.unlink

        def av_locked(self, *args, **kwargs):
            if self.name.startswith((".rc-", ".mf-")):
                raise PermissionError("cleanup denied (AV lock)")
            return real_unlink(self, *args, **kwargs)

        with mock.patch.object(Path, "unlink", av_locked):
            receipt = self._publish(_task("t-1"))
        self.assertFalse(receipt.already_present)
        self.assertTrue((self.root / receipt.path).is_file())
        report = verify_record_graph(self.root)
        self.assertTrue(report.ok, report.to_dict())

    # -- reserved nodes must have their expected types ------------------------

    def test_manifest_as_directory_fails_closed(self) -> None:
        self.root.mkdir(parents=True)
        (self.root / "manifest.json").mkdir()
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("unexpected_node_type", {v.kind for v in report.violations})
        # Publishing must fail as StoreIntegrityError, never a bare OSError.
        with self.assertRaises(StoreIntegrityError):
            self._publish(_task("t-1"))

    def test_records_as_plain_file_fails_closed(self) -> None:
        self.root.mkdir(parents=True)
        (self.root / "records").write_bytes(b"not a directory")
        report = verify_record_graph(self.root)
        self.assertFalse(report.ok)
        self.assertIn("unexpected_node_type", {v.kind for v in report.violations})
        with self.assertRaises(StoreIntegrityError):
            self._publish(_task("t-1"))


class PublicInterfaceTest(unittest.TestCase):
    def test_public_export_set_matches_phase_1b(self) -> None:
        # Phase 1C adds no public names: the export list stays identical to
        # the Phase 1B contract, item for item.
        import research_evolution.core as core

        self.assertEqual(
            core.__all__,
            [
                "CoreError",
                "GraphVerificationReport",
                "PublicationError",
                "PublicationReceipt",
                "Record",
                "RecordValidationError",
                "SchemaDefinitionError",
                "StoreIntegrityError",
                "StrictJsonError",
                "UnknownSchemaError",
                "UnsafePathError",
                "canonical_bytes",
                "canonical_sha256",
                "load_record",
                "load_strict_json",
                "publish_record",
                "validate_safe_relative_path",
                "verify_record_graph",
            ],
        )


if __name__ == "__main__":
    unittest.main()
