from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SUPPORT_MATRIX = REPO_ROOT / "docs" / "governance" / "SUPPORT_MATRIX.json"


class CIWorkflowContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.support = json.loads(SUPPORT_MATRIX.read_text(encoding="utf-8"))
        with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
            cls.pyproject = tomllib.load(handle)
        cls.project = cls.pyproject["project"]

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
        self.assertIn("fetch-depth: 0", self.workflow)
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            self.workflow,
        )

    def test_matrix_covers_supported_minimum_and_current_validation(self) -> None:
        self.assertIn("os: [ubuntu-latest, windows-latest]", self.workflow)
        self.assertIn('python-version: ["3.12", "3.14"]', self.workflow)
        self.assertIn("fail-fast: false", self.workflow)
        expected = {
            (job["os"], job["python"]) for job in self.support["required_jobs"]
        }
        actual = {
            (operating_system, python)
            for operating_system in ("ubuntu-latest", "windows-latest")
            for python in ("3.12", "3.14")
        }
        self.assertEqual(expected, actual)
        self.assertEqual(self.support["package_version"], self.project["version"])
        self.assertEqual(self.support["requires_python"], self.project["requires-python"])

    def test_installs_pinned_non_runtime_quality_dependencies(self) -> None:
        expected = ["coverage==7.15.4", "mypy==2.3.1", "ruff==0.16.3"]
        self.assertEqual(
            self.project["optional-dependencies"]["quality"],
            expected,
        )
        self.assertIn(
            'python -m pip install --disable-pip-version-check ".[quality]"',
            self.workflow,
        )

    def test_runs_ratcheted_ruff_and_mypy_gates(self) -> None:
        quality = self.support["quality_gates"]
        for command in quality["ruff"]["commands"]:
            self.assertIn(command, self.workflow)
        self.assertEqual(
            quality["ruff"]["strict_paths"],
            [
                "src/research_evolution/core",
                "src/research_evolution/evaluation",
                "src/research_evolution/evolution",
            ],
        )
        self.assertIn(quality["mypy"]["command"], self.workflow)
        self.assertEqual(self.pyproject["tool"]["mypy"]["python_version"], "3.12")
        self.assertTrue(self.pyproject["tool"]["mypy"]["check_untyped_defs"])
        self.assertTrue(self.pyproject["tool"]["mypy"]["no_incremental"])

    def test_runs_full_suite_with_branch_coverage_floor(self) -> None:
        self.assertIn("PYTHONPATH: src", self.workflow)
        self.assertIn('PYTHONDONTWRITEBYTECODE: "1"', self.workflow)
        quality = self.support["quality_gates"]["coverage"]
        self.assertIn("COVERAGE_FILE: ${{ runner.temp }}/.coverage", self.workflow)
        self.assertIn(quality["run_command"], self.workflow)
        self.assertIn(quality["report_command"], self.workflow)
        self.assertEqual(quality["branch_floor_percent"], 80)

    def test_checks_changed_bytes_and_clean_archive_install(self) -> None:
        self.assertIn(
            'git diff --check "${{ github.event.pull_request.base.sha }}...HEAD"',
            self.workflow,
        )
        self.assertIn(
            'git diff --check "${{ github.event.before }}..HEAD"',
            self.workflow,
        )
        command = "python -B scripts/verify_archive_install.py"
        self.assertEqual(self.support["archive_install_gate"]["command"], command)
        self.assertIn(command, self.workflow)
        self.assertEqual(
            self.support["archive_install_gate"]["success_args"],
            ["demo", "--json"],
        )
        self.assertEqual(
            self.support["archive_install_gate"]["rejection_args"],
            ["demo", "--tamper", "--json"],
        )
        self.assertEqual(
            self.support["archive_install_gate"]["rejection_exit_code"], 1
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
