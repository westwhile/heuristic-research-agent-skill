"""Minimal repository-bootstrap checks with no third-party dependencies."""

import tomllib
import unittest
from pathlib import Path

import research_evolution


REPO_ROOT = Path(__file__).resolve().parents[2]


class BootstrapTest(unittest.TestCase):
    def test_package_exposes_bootstrap_version(self) -> None:
        self.assertEqual(research_evolution.__version__, "0.6.1")

    def test_wheel_force_includes_frozen_schema_trees(self) -> None:
        with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
            config = tomllib.load(handle)
        force_include = config["tool"]["hatch"]["build"]["targets"]["wheel"][
            "force-include"
        ]
        self.assertEqual(
            force_include,
            {
                "schemas/core": "research_evolution/_schemas/core",
                "schemas/adapters": "research_evolution/_schemas/adapters",
            },
        )
        for source in force_include:
            schema_root = REPO_ROOT / source
            self.assertTrue(schema_root.is_dir(), source)
            self.assertTrue(any(schema_root.glob("*.schema.json")), source)


if __name__ == "__main__":
    unittest.main()
