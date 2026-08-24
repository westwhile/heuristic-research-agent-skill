from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class ExternalTrialScriptTests(unittest.TestCase):
    def test_submission_and_review_help_need_no_pytorch(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPO_ROOT / "src")
        cases = (
            (
                "prepare_dl_external_trial_submission.py",
                ("--receipt", "--attestation", "--submission-output"),
            ),
            (
                "review_dl_external_trial_cohort.py",
                ("--submission", "--review-plan", "--review-output"),
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

    def test_prepare_then_review_is_local_public_safe_and_engineering_only(
        self,
    ) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPO_ROOT / "src")
        fixture_root = REPO_ROOT / "tests" / "fixtures" / "adapters"
        receipt_root = fixture_root / "dl-portability-trial-receipt" / "v1" / "valid"
        attestation_root = (
            fixture_root / "dl-external-trial-attestation" / "v1" / "valid"
        )
        review_plan = (
            fixture_root
            / "dl-external-trial-cohort-review-plan"
            / "v1"
            / "valid"
            / "minimal.json"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory)
            first_output = output_root / "first-submission.json"
            second_output = output_root / "second-submission.json"
            preparations = (
                ("full.json", "minimal.json", first_output),
                ("minimal.json", "full.json", second_output),
            )
            for receipt_name, attestation_name, output in preparations:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(
                            REPO_ROOT
                            / "scripts"
                            / "prepare_dl_external_trial_submission.py"
                        ),
                        "--receipt",
                        str(receipt_root / receipt_name),
                        "--attestation",
                        str(attestation_root / attestation_name),
                        "--submission-output",
                        str(output),
                    ],
                    cwd=REPO_ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout)
                self.assertIn("DL EXTERNAL TRIAL SUBMISSION: PASS", completed.stdout)
                self.assertIn("external_adoption_verified=false", completed.stdout)
                self.assertTrue(output.is_file())

            review_output = output_root / "cohort-review.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "review_dl_external_trial_cohort.py"),
                    "--submission",
                    str(first_output),
                    "--submission",
                    str(second_output),
                    "--review-plan",
                    str(review_plan),
                    "--review-output",
                    str(review_output),
                ],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn("DL EXTERNAL TRIAL COHORT REVIEW: PASS", completed.stdout)
            self.assertIn(
                "status=eligible_for_separate_technical_comparison",
                completed.stdout,
            )
            self.assertIn("r5_technical_comparison_required=true", completed.stdout)
            payload = json.loads(review_output.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["accepted_submissions"], 2)
            self.assertFalse(payload["claims"]["external_adoption_verified"])
            self.assertFalse(payload["claims"]["production_reliability_verified"])
            self.assertFalse(payload["privacy"]["automatic_upload_performed"])


if __name__ == "__main__":
    unittest.main()
