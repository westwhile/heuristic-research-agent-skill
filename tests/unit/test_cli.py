"""Unit tests for the read-only CLI (ADR-0004, decisions 8 and 10).

Every invocation runs as a subprocess (``python -m research_evolution``)
with its working directory inside the test's temporary tree, so any
accidental write would land inside the snapshotted surface. The CLI must
never create, modify, or delete files; ``test_cli_is_read_only`` pins
that with before/after tree snapshots.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from research_evolution.core import (
    canonical_bytes,
    canonical_sha256,
    load_record,
    load_strict_json,
    publish_record,
    verify_record_graph,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "core"
TASK_MINIMAL = FIXTURES / "research-task" / "v1" / "valid" / "minimal.json"
TASK_WHITESPACE_TITLE = (
    FIXTURES / "research-task" / "v1" / "invalid" / "whitespace-title.json"
)


def _tree_snapshot(root: Path) -> dict[str, str]:
    """{relative path: sha256} for every file under root."""
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.work = Path(self._tmp.name)
        self._env = dict(os.environ)
        self._env["PYTHONPATH"] = str(REPO_ROOT / "src")
        self._env["PYTHONDONTWRITEBYTECODE"] = "1"

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", "-m", "research_evolution", *args],
            capture_output=True,
            cwd=self.work,
            env=self._env,
        )

    def _expected_validate_payload(self) -> dict[str, str]:
        record = load_record(TASK_MINIMAL.read_bytes())
        return {
            "schema_id": record.schema_id,
            "record_id": record.data["task_id"],
            "sha256": record.sha256,
        }

    def _publish_store(self) -> Path:
        store = self.work / "store"
        publish_record(
            TASK_MINIMAL.read_text(encoding="utf-8"), root=store
        )
        return store

    # -- validate ----------------------------------------------------------

    def test_validate_human_readable(self) -> None:
        payload = self._expected_validate_payload()
        proc = self._run("validate", str(TASK_MINIMAL))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stdout = proc.stdout.decode("utf-8")
        self.assertIn(f"schema_id: {payload['schema_id']}\n", stdout)
        self.assertIn(f"record_id: {payload['record_id']}\n", stdout)
        self.assertIn(f"sha256: {payload['sha256']}\n", stdout)
        self.assertEqual(proc.stderr, b"")

    def test_validate_json_is_canonical_and_reparseable(self) -> None:
        payload = self._expected_validate_payload()
        proc = self._run("validate", "--json", str(TASK_MINIMAL))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Byte-exact canonical output: hashing the raw report reproduces
        # the payload's canonical hash (dogfood, ADR-0004 decision 10).
        self.assertEqual(proc.stdout, canonical_bytes(payload))
        reparsed = load_strict_json(proc.stdout)
        self.assertEqual(reparsed, payload)
        self.assertEqual(
            hashlib.sha256(proc.stdout).hexdigest(), canonical_sha256(reparsed)
        )

    def test_validate_invalid_record_exit_1(self) -> None:
        proc = self._run("validate", str(TASK_WHITESPACE_TITLE))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, b"")
        self.assertIn(b"RecordValidationError", proc.stderr)

    def test_validate_invalid_record_json_error_envelope(self) -> None:
        proc = self._run("validate", "--json", str(TASK_WHITESPACE_TITLE))
        self.assertEqual(proc.returncode, 1)
        envelope = load_strict_json(proc.stderr)
        self.assertEqual(envelope["error"]["type"], "RecordValidationError")
        self.assertEqual(proc.stderr, canonical_bytes(envelope))

    def test_validate_garbage_bytes_exit_1(self) -> None:
        garbage = self.work / "garbage.json"
        garbage.write_bytes(b"not json {")
        proc = self._run("validate", str(garbage))
        self.assertEqual(proc.returncode, 1)
        self.assertIn(b"StrictJsonError", proc.stderr)

    def test_validate_missing_file_exit_2(self) -> None:
        proc = self._run("validate", str(self.work / "missing.json"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"InputError", proc.stderr)
        self.assertIn(b"does not exist", proc.stderr)

    def test_validate_directory_is_input_error_exit_2(self) -> None:
        proc = self._run("validate", str(self.work))
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"InputError", proc.stderr)
        self.assertIn(b"not a regular file", proc.stderr)

    # -- hash ---------------------------------------------------------------

    def test_hash_human_readable(self) -> None:
        record = load_record(TASK_MINIMAL.read_bytes())
        proc = self._run("hash", str(TASK_MINIMAL))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, (record.sha256 + "\n").encode("utf-8"))

    def test_hash_json(self) -> None:
        record = load_record(TASK_MINIMAL.read_bytes())
        proc = self._run("hash", "--json", str(TASK_MINIMAL))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            proc.stdout, canonical_bytes({"sha256": record.sha256})
        )

    def test_hash_invalid_record_exit_1(self) -> None:
        # The kernel's hash is defined on validated records only.
        proc = self._run("hash", str(TASK_WHITESPACE_TITLE))
        self.assertEqual(proc.returncode, 1)
        self.assertIn(b"RecordValidationError", proc.stderr)

    # -- verify-graph --------------------------------------------------------

    def test_verify_graph_ok_store(self) -> None:
        store = self._publish_store()
        proc = self._run("verify-graph", str(store))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stdout = proc.stdout.decode("utf-8")
        self.assertIn("ok: true\n", stdout)
        self.assertIn("records_total: 1\n", stdout)
        self.assertIn("family research-task/v1: 1\n", stdout)
        self.assertIn("manifest_sha256: ", stdout)

    def test_verify_graph_json_matches_kernel_report(self) -> None:
        store = self._publish_store()
        expected = verify_record_graph(store).to_dict()
        proc = self._run("verify-graph", "--json", str(store))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, canonical_bytes(expected))
        self.assertEqual(load_strict_json(proc.stdout), expected)

    def test_verify_graph_broken_store_reports_not_crashes(self) -> None:
        store = self._publish_store()
        record_file = next((store / "records").rglob("*.json"))
        record_file.write_bytes(b"garbage")
        proc = self._run("verify-graph", "--json", str(store))
        self.assertEqual(proc.returncode, 1)
        report = load_strict_json(proc.stdout)
        self.assertFalse(report["ok"])
        self.assertGreaterEqual(len(report["violations"]), 1)

    def test_verify_graph_missing_store_is_finding_not_usage_error(self) -> None:
        # The store root is the kernel's input: its absence is a
        # fail-closed finding (store_root_missing, exit 1), not a CLI
        # input error (exit 2) — ADR-0004 decision 8's input-error clause
        # covers record files only.
        proc = self._run(
            "verify-graph", "--json", str(self.work / "missing-store")
        )
        self.assertEqual(proc.returncode, 1)
        report = load_strict_json(proc.stdout)
        self.assertEqual(
            [v["kind"] for v in report["violations"]], ["store_root_missing"]
        )

    # -- usage and read-only boundary ----------------------------------------

    def test_usage_errors_exit_2(self) -> None:
        for args in ((), ("publish", "x.json"), ("validate",), ("nonsense",)):
            with self.subTest(args=args):
                proc = self._run(*args)
                self.assertEqual(proc.returncode, 2)
                self.assertIn(b"usage:", proc.stderr)

    def test_cli_is_read_only(self) -> None:
        store = self._publish_store()
        before = _tree_snapshot(self.work)
        for args in (
            ("validate", str(TASK_MINIMAL)),
            ("validate", "--json", str(TASK_MINIMAL)),
            ("hash", str(TASK_MINIMAL)),
            ("verify-graph", str(store)),
            ("verify-graph", "--json", str(store)),
            ("validate", str(TASK_WHITESPACE_TITLE)),
            ("validate", str(self.work / "missing.json")),
        ):
            proc = self._run(*args)
            self.assertNotEqual(proc.returncode, -1)
        self.assertEqual(_tree_snapshot(self.work), before)


if __name__ == "__main__":
    unittest.main()
