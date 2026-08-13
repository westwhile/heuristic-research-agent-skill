from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "build_external_skill_portable.py"
SPEC = importlib.util.spec_from_file_location("build_external_skill_portable", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PortableBuilderTest(unittest.TestCase):
    def test_replaces_payload_and_regenerates_verified_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "demo-skill"
            candidate.mkdir()
            (candidate / "SKILL.md").write_text("---\nname: demo-skill\n---\n", encoding="utf-8")
            base = root / "base.zip"
            manifest = {
                "schema_version": 2,
                "artifact": {"name": "demo-skill", "version": "1.0.0"},
                "build": {"date": "2026-01-01", "source_tree_sha256": "0" * 64},
                "payload_root": "payload/demo-skill",
                "known_limitations": [],
            }
            files = {
                "package-manifest.json": (json.dumps(manifest) + "\n").encode(),
                "payload/demo-skill/SKILL.md": b"old",
                "install.py": b"print('ok')\n",
            }
            checksums = "".join(
                f"{MODULE.sha256_bytes(files[name])}  {name}\n" for name in sorted(files)
            ).encode()
            with zipfile.ZipFile(base, "w") as archive:
                for name, data in {**files, "checksums.sha256": checksums}.items():
                    archive.writestr(name, data)

            output = root / "updated.zip"
            result = MODULE.build(base, candidate, output, "1.0.1", "2026-08-13")
            self.assertEqual(result["status"], "built")
            with zipfile.ZipFile(output) as archive:
                packaged = {
                    item.filename: archive.read(item.filename)
                    for item in archive.infolist()
                    if not item.is_dir()
                }
            updated_manifest = MODULE.verify_base(packaged)
            self.assertEqual(updated_manifest["artifact"]["version"], "1.0.1")
            self.assertEqual(
                packaged["payload/demo-skill/SKILL.md"],
                (candidate / "SKILL.md").read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
