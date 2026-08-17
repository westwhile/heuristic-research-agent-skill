"""Unit tests for the read-only math-research-solve archive importer.

All tests use the clearly-marked synthetic fixture tree
tests/fixtures/math-archives/minimal-v8. Real legacy archive import is a
conditional capability (reports/baseline/math-research-solve-1.0.1.md) and
is NOT claimed here; no synthetic file is presented as a real archive.
"""

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from research_evolution.adapters import AdapterError
from research_evolution.adapters.math import (
    MathArchiveImport,
    import_archive,
    snapshot_tree,
)

ARCHIVE = Path(__file__).resolve().parents[1] / "fixtures" / "math-archives" / "minimal-v8"


class MathArchiveImportTest(unittest.TestCase):
    def test_import_synthetic_archive(self) -> None:
        result = import_archive(ARCHIVE)
        self.assertIsInstance(result, MathArchiveImport)
        self.assertEqual(result.project_id, "synthetic-project-0001")
        self.assertEqual(len(result.artifacts), 9)
        self.assertEqual(
            result.project_head_sha256,
            hashlib.sha256((ARCHIVE / "project.json").read_bytes()).hexdigest(),
        )
        paths = {artifact.path for artifact in result.artifacts}
        self.assertIn("project.json", paths)
        self.assertIn("contracts/contract-v8.md", paths)
        self.assertIn("runs/run-0001/run.json", paths)
        for artifact in result.artifacts:
            self.assertEqual(len(artifact.sha256), 64)

    def test_import_is_deterministic(self) -> None:
        self.assertEqual(
            import_archive(ARCHIVE).tree_digest, import_archive(ARCHIVE).tree_digest
        )

    def test_zero_write_evidence(self) -> None:
        before = snapshot_tree(ARCHIVE)
        import_archive(ARCHIVE)
        after = snapshot_tree(ARCHIVE)
        self.assertEqual(before, after)

    def test_evidence_inputs_are_core_shaped(self) -> None:
        inputs = import_archive(ARCHIVE).evidence_inputs()
        self.assertEqual(len(inputs), 9)
        for entry in inputs:
            self.assertEqual(set(entry), {"name", "kind", "sha256"})
            self.assertEqual(entry["kind"], "data")
            self.assertEqual(len(entry["sha256"]), 64)

    def _copy(self, tmp: str) -> Path:
        target = Path(tmp) / "archive-copy"
        shutil.copytree(ARCHIVE, target)
        return target

    def test_tampered_pointer_target_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy = self._copy(tmp)
            target = copy / "state" / "generations" / "g0001" / "checkpoint.json"
            target.write_bytes(target.read_bytes() + b" ")
            with self.assertRaises(AdapterError) as ctx:
                import_archive(copy)
            self.assertIn("hash mismatch", str(ctx.exception))

    def test_wrong_head_schema_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy = self._copy(tmp)
            head = copy / "project.json"
            head.write_bytes(
                head.read_bytes().replace(
                    b"math-research-project/v8", b"math-research-project/v7"
                )
            )
            with self.assertRaises(AdapterError) as ctx:
                import_archive(copy)
            self.assertIn("math-research-project/v8", str(ctx.exception))

    def test_unknown_top_level_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy = self._copy(tmp)
            head = copy / "project.json"
            head.write_bytes(
                head.read_bytes().replace(
                    b'"legacy_successor": null',
                    b'"legacy_successor": null, "goal_token": "smuggled"',
                )
            )
            with self.assertRaises(AdapterError) as ctx:
                import_archive(copy)
            self.assertIn("unknown", str(ctx.exception))

    def test_missing_pointer_target_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy = self._copy(tmp)
            (copy / "state" / "generations" / "g0001" / "goal-host-v8.json").unlink()
            with self.assertRaises(AdapterError) as ctx:
                import_archive(copy)
            self.assertIn("target file missing", str(ctx.exception))

    def test_missing_project_json_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AdapterError):
                import_archive(tmp)

    def test_non_directory_root_fails_closed(self) -> None:
        with self.assertRaises(AdapterError):
            import_archive(ARCHIVE / "project.json")


if __name__ == "__main__":
    unittest.main()
