from __future__ import annotations

import json
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

    def test_citation_uses_confirmed_public_release_metadata(self) -> None:
        citation = (REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8")
        self.assertIn("cff-version: 1.2.0", citation)
        self.assertIn('name: "westwhile"', citation)
        self.assertIn("license: Apache-2.0", citation)
        self.assertIn(
            'repository-code: "https://github.com/westwhile/'
            'heuristic-research-agent-skill"',
            citation,
        )
        self.assertIn('version: "0.6.1"', citation)
        self.assertIn('date-released: "2026-08-23"', citation)

    def test_changelog_covers_release_history_without_pypi_overclaim(self) -> None:
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
        self.assertIn("## 0.6.1", changelog)
        self.assertIn("has not been published to PyPI", changelog)

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
        self.assertIn("Latest GitHub Release (`v0.6.1`", security)
        for placeholder in ("TODO", "TBD", "INSERT", "example.com"):
            self.assertNotIn(placeholder, security)

    def test_issue_forms_cover_public_intake_without_security_details(self) -> None:
        forms = {
            "bug_report.yml",
            "documentation.yml",
            "quick_start_trial.yml",
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
        trial = (issue_root / "quick_start_trial.yml").read_text(encoding="utf-8")
        for evidence_field in (
            "id: relationship",
            "id: version",
            "id: operating_system",
            "id: python",
            "id: elapsed",
            "id: outcome",
            "id: interpretation",
            "id: public_confirmation",
        ):
            self.assertIn(evidence_field, trial)
        self.assertIn("This describes my own real attempt", trial)
        self.assertIn("Security reports follow SECURITY.md", trial)
        config = (issue_root / "config.yml").read_text(encoding="utf-8")
        self.assertIn("/security/policy", config)

        protocol = (
            REPO_ROOT / "docs" / "governance" / "EXTERNAL_TRIAL_PROTOCOL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("NO_EXTERNAL_RESULTS_YET", protocol)
        self.assertIn("WAITING_FOR_EXTERNAL_PARTICIPANTS", protocol)
        self.assertIn("at least two independent external users", protocol)
        self.assertIn("do **not** count as external adoption", protocol)

    def test_application_evidence_is_public_safe_and_not_submission_ready(self) -> None:
        evidence_root = REPO_ROOT / "docs" / "governance" / "codex-for-oss"
        evidence = json.loads(
            (evidence_root / "application-evidence.json").read_text(
                encoding="utf-8"
            )
        )
        claims = (evidence_root / "application-claims.md").read_text(
            encoding="utf-8"
        )

        self.assertEqual(
            evidence["status"], "preparation_only_external_trial_pending"
        )
        self.assertFalse(evidence["external_trial"]["o5_exit_gate_met"])
        for field in (
            "independent_participants",
            "qualifying_attempts",
            "genuine_findings",
            "feedback_driven_changes",
        ):
            self.assertEqual(evidence["external_trial"][field], 0, field)
        self.assertFalse(evidence["private_fields"]["stored_in_repository"])
        self.assertFalse(evidence["submission_gate"]["ready"])
        self.assertFalse(
            evidence["submission_gate"]["user_submission_authorization"]
        )

        for name, draft in evidence["application_drafts"].items():
            self.assertEqual(draft["character_limit"], 500, name)
            self.assertEqual(draft["character_count"], len(draft["text"]), name)
            self.assertLessEqual(draft["character_count"], 500, name)

        for marker in (
            "PREPARATION_ONLY",
            "WAITING_FOR_EXTERNAL_PARTICIPANTS",
            "NO_EXTERNAL_RESULTS_YET",
            "DO_NOT_SUBMIT",
            "https://developers.openai.com/community/codex-for-oss",
            "https://learn.chatgpt.com/docs/codex-for-oss-terms",
        ):
            self.assertIn(marker, claims)

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
