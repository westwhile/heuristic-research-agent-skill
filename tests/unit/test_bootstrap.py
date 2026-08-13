"""Minimal repository-bootstrap checks with no third-party dependencies."""

import unittest

import research_evolution


class BootstrapTest(unittest.TestCase):
    def test_package_exposes_bootstrap_version(self) -> None:
        self.assertEqual(research_evolution.__version__, "0.0.0")


if __name__ == "__main__":
    unittest.main()
