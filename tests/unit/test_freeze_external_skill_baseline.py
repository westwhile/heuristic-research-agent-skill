"""Tests for the external Skill baseline freezer."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FreezeExternalSkillBaselineTest(unittest.TestCase):
    def test_equal_portable_and_installed_trees_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installed = root / "installed"
            installed.mkdir()
            skill_bytes = b"---\nname: demo\ndescription: demo\n---\n"
            (installed / "SKILL.md").write_bytes(skill_bytes)

            package = {
                "artifact": {"name": "demo", "version": "1.0.0", "type": "portable-skill"},
                "build": {"source_tree_sha256": "0" * 64},
                "payload_root": "payload/demo",
            }
            package_bytes = (json.dumps(package, sort_keys=True) + "\n").encode()
            checksum_lines = (
                f"{digest(package_bytes)}  package-manifest.json\n"
                f"{digest(skill_bytes)}  payload/demo/SKILL.md\n"
            ).encode()
            archive = root / "demo.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("package-manifest.json", package_bytes)
                output.writestr("payload/demo/SKILL.md", skill_bytes)
                output.writestr("checksums.sha256", checksum_lines)

            destination = root / "result"
            script = Path(__file__).parents[2] / "scripts" / "freeze_external_skill_baseline.py"
            run = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(script),
                    "--portable-zip",
                    str(archive),
                    "--installed-root",
                    str(installed),
                    "--output-dir",
                    str(destination),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(run.returncode, 0, run.stderr or run.stdout)
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            comparison = json.loads((destination / "comparison.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["comparison"]["status"], "pass")
            self.assertEqual(comparison["status"], "pass")
            self.assertEqual(manifest["payload"]["tree_sha256"], manifest["installed_snapshot"]["tree_sha256"])
            self.assertNotIn(str(root), (destination / "manifest.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
