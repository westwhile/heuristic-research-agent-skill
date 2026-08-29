from __future__ import annotations

import json
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class SourceProvenanceTests(unittest.TestCase):
    def test_repository_provenance_gate(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "scripts/verify_source_provenance.py", "--json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"]["unknown"], 0)
        self.assertEqual(report["counts"]["third_party_reused"], 2)
        self.assertEqual(report["counts"]["independently_authored"], 993)
        self.assertEqual(report["counts"]["design_inspired"], 35)
        self.assertEqual(report["counts"]["total"], 1148)

    def test_apache_license_metadata_and_rights_confirmation(self) -> None:
        manifest = json.loads(
            (REPO_ROOT / "docs/governance/SOURCE_PROVENANCE.json").read_text(
                encoding="utf-8"
            )
        )
        with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
            package = tomllib.load(handle)["project"]

        self.assertEqual(manifest["project_license"]["spdx"], "Apache-2.0")
        self.assertEqual(manifest["rights_confirmation"]["status"], "confirmed")
        self.assertEqual(package["license"], "Apache-2.0")
        self.assertTrue((REPO_ROOT / "LICENSE").is_file())
        self.assertTrue((REPO_ROOT / "NOTICE").is_file())

        openai_reference = next(
            source
            for source in manifest["external_sources"]
            if source["id"] == "openai-codex-for-oss-official-pages"
        )
        self.assertFalse(openai_reference["tracked_expression_reused"])
        self.assertTrue(openai_reference["evidence_sufficient_for_reuse"])

        pytorch_reference = next(
            source
            for source in manifest["external_sources"]
            if source["id"] == "pytorch"
        )
        self.assertFalse(pytorch_reference["tracked_expression_reused"])
        self.assertIn("not bundled", pytorch_reference["versions"][0])

        sources = {source["id"]: source for source in manifest["external_sources"]}
        expected_quality_sources = {
            "ruff": ("0.16.3", "MIT"),
            "mypy": ("2.3.1", "MIT"),
            "coverage-py": ("7.15.4", "Apache-2.0"),
        }
        for source_id, (version, license_id) in expected_quality_sources.items():
            source = sources[source_id]
            self.assertEqual(source["versions"], [version])
            self.assertEqual(source["visible_license"], license_id)
            self.assertFalse(source["tracked_expression_reused"])
            self.assertIn("non-vendored", source["notice_action"])

    def test_v13_external_expression_remains_excluded(self) -> None:
        manifest = json.loads(
            (REPO_ROOT / "docs/governance/SOURCE_PROVENANCE.json").read_text(
                encoding="utf-8"
            )
        )
        pika = next(
            source
            for source in manifest["external_sources"]
            if source["id"] == "pika-toolkit-v13"
        )
        plan = (
            REPO_ROOT
            / "docs/plans/MATH_RESEARCH_SOLVE_V13_CROSS_DOMAIN_ADOPTION_PLAN.md"
        ).read_text(encoding="utf-8")

        self.assertFalse(pika["tracked_expression_reused"])
        self.assertFalse(pika["evidence_sufficient_for_reuse"])
        self.assertIn("SOURCE_EXCLUDED", plan)
        self.assertIn("本轮无法重新核验原始 artifact", plan)
        self.assertLess(len(plan.splitlines()), 100)
        for stale_count in ("493", "249", "170", "18 个"):
            self.assertNotIn(stale_count, plan)


if __name__ == "__main__":
    unittest.main()
