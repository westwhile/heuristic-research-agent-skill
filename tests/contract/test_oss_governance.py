from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class OSSGovernanceContractTest(unittest.TestCase):
    def test_required_public_entrypoints_exist(self) -> None:
        for relative in (
            "CHANGELOG.md",
            "CITATION.cff",
            "CODE_OF_CONDUCT.md",
            "CONTRIBUTING.md",
            "GOVERNANCE.md",
            "SECURITY.md",
        ):
            path = REPO_ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertTrue(path.read_text(encoding="utf-8").strip(), relative)

    def test_citation_uses_confirmed_public_metadata_without_fake_release(self) -> None:
        citation = (REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8")
        self.assertIn("cff-version: 1.2.0", citation)
        self.assertIn('name: "westwhile"', citation)
        self.assertIn("license: Apache-2.0", citation)
        self.assertIn(
            'repository-code: "https://github.com/westwhile/'
            'heuristic-research-agent-skill"',
            citation,
        )
        self.assertNotIn("date-released:", citation)
        self.assertNotRegex(citation, r"(?m)^version:")

    def test_changelog_covers_every_tag_without_pypi_overclaim(self) -> None:
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        for version in (
            "0.1.0",
            "0.2.0",
            "0.3.0",
            "0.4.0",
            "0.5.0",
            "0.5.1",
            "0.6.0",
        ):
            self.assertIn(f"## {version} ", changelog)
        self.assertIn("## Unreleased", changelog)
        self.assertIn("has not been tagged, published to PyPI", changelog)

    def test_conduct_template_is_attributed_and_fully_adapted(self) -> None:
        conduct = (REPO_ROOT / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
        self.assertIn("Contributor Covenant, version 3.0", conduct)
        self.assertIn("CC BY-SA 4.0", conduct)
        self.assertNotIn("[NOTE:", conduct)
        self.assertIn("Reporting an Issue", conduct)

    def test_security_policy_has_private_route_and_no_placeholder(self) -> None:
        security = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("Supported versions", security)
        self.assertIn("Do not open a public issue", security)
        self.assertIn("private", security.lower())
        for placeholder in ("TODO", "TBD", "INSERT", "example.com"):
            self.assertNotIn(placeholder, security)

    def test_issue_forms_cover_public_intake_without_security_details(self) -> None:
        forms = {
            "bug_report.yml",
            "documentation.yml",
            "research_boundary.yml",
            "schema_contract_proposal.yml",
        }
        issue_root = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
        for name in forms:
            text = (issue_root / name).read_text(encoding="utf-8")
            self.assertIn("name:", text, name)
            self.assertIn("description:", text, name)
            self.assertIn("body:", text, name)
            self.assertIn("required: true", text, name)
        bug = (issue_root / "bug_report.yml").read_text(encoding="utf-8")
        self.assertIn("Security reports follow SECURITY.md", bug)
        config = (issue_root / "config.yml").read_text(encoding="utf-8")
        self.assertIn("/security/policy", config)

    def test_pull_request_template_carries_provenance_and_claim_gates(self) -> None:
        template = (REPO_ROOT / ".github" / "pull_request_template.md").read_text(
            encoding="utf-8"
        )
        for heading in (
            "## 科研结论边界",
            "## 来源、许可证与第三方内容",
            "## 数据、隐私与污染检查",
            "## 兼容性与治理",
            "## 回滚",
        ):
            self.assertIn(heading, template)
        self.assertIn("unknown=0", template)


if __name__ == "__main__":
    unittest.main()
