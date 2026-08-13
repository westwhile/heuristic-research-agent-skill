from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "run_math_research_baseline.py"
SPEC = importlib.util.spec_from_file_location("run_math_research_baseline", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BaselineRunnerTest(unittest.TestCase):
    def test_known_prerequisite_failures_are_environment_blockers(self) -> None:
        self.assertEqual(
            MODULE.classify_environment_blocker(
                b"Control-path regression requires the installed DPAPI manifest key."
            ),
            "missing_installed_dpapi_manifest_key",
        )
        self.assertEqual(
            MODULE.classify_environment_blocker(
                b"ModuleNotFoundError: No module named 'yaml'"
            ),
            "missing_python_dependency_pyyaml",
        )

    def test_product_failure_is_not_reclassified(self) -> None:
        self.assertIsNone(
            MODULE.classify_environment_blocker(
                b"full SKILL routes startup expected true."
            )
        )


if __name__ == "__main__":
    unittest.main()
