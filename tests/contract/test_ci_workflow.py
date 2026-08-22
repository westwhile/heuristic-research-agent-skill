from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


class CIWorkflowContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_triggers_on_pull_requests_and_main_pushes(self) -> None:
        self.assertRegex(self.workflow, r"(?m)^  pull_request:$")
        self.assertRegex(
            self.workflow,
            r"(?ms)^  push:\n    branches: \[main\]$",
        )

    def test_uses_read_only_pinned_official_actions(self) -> None:
        self.assertRegex(
            self.workflow,
            r"(?ms)^permissions:\n  contents: read$",
        )
        self.assertIn(
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1",
            self.workflow,
        )
        self.assertIn(
            "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0",
            self.workflow,
        )
        self.assertIn("persist-credentials: false", self.workflow)

    def test_matrix_covers_supported_minimum_and_current_validation(self) -> None:
        self.assertIn("os: [ubuntu-latest, windows-latest]", self.workflow)
        self.assertIn('python-version: ["3.12", "3.14"]', self.workflow)
        self.assertIn("fail-fast: false", self.workflow)

    def test_runs_full_standard_library_suite_with_explicit_import_path(self) -> None:
        self.assertIn("PYTHONPATH: src", self.workflow)
        self.assertIn('PYTHONDONTWRITEBYTECODE: "1"', self.workflow)
        self.assertIn(
            'python -B -m unittest discover -s tests -p "test_*.py" -v',
            self.workflow,
        )

    def test_runs_powershell_governance_suite_only_on_windows(self) -> None:
        self.assertRegex(
            self.workflow,
            re.compile(
                r"Run PowerShell governance tests.*?"
                r"if: runner\.os == 'Windows'.*?"
                r"tests/unit/test_github_auth_context\.ps1",
                re.DOTALL,
            ),
        )


if __name__ == "__main__":
    unittest.main()
