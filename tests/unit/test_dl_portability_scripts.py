from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class PortabilityScriptTests(unittest.TestCase):
    def test_trial_and_comparison_help_are_available_without_pytorch(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPO_ROOT / "src")
        cases = (
            (
                "verify_dl_portability_trial.py",
                ("--commit", "--tree", "--archive-sha256", "--receipt-output"),
            ),
            (
                "compare_dl_portability_receipts.py",
                ("--receipt", "--final-loss-absolute-tolerance", "--report-output"),
            ),
        )
        for script, options in cases:
            with self.subTest(script=script):
                completed = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "scripts" / script), "--help"],
                    cwd=REPO_ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                for option in options:
                    self.assertIn(option, completed.stdout)

    def test_comparison_runs_from_an_external_working_directory(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPO_ROOT / "src")
        fixture_root = (
            REPO_ROOT
            / "tests"
            / "fixtures"
            / "adapters"
            / "dl-portability-trial-receipt"
            / "v1"
            / "valid"
        )
        with tempfile.TemporaryDirectory(prefix="dl-portability-script-test-") as cwd:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "compare_dl_portability_receipts.py"),
                    "--receipt",
                    str(fixture_root / "minimal.json"),
                    "--receipt",
                    str(fixture_root / "full.json"),
                ],
                cwd=cwd,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("DL CROSS-ENVIRONMENT RECEIPT COMPARISON: PASS", completed.stdout)
        self.assertIn("verdict=exact", completed.stdout)
        self.assertIn("independent_hosts_verified=false", completed.stdout)
        self.assertIn("external_adoption_verified=false", completed.stdout)


if __name__ == "__main__":
    unittest.main()
