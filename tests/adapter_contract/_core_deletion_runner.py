"""Subprocess runner for the core deletion probe (ADR-0005 decision 8b).

Invoked by ``CoreDeletionTest`` as::

    python -B tests/adapter_contract/_core_deletion_runner.py <test modules...>

The runner installs a meta-path blocker that makes every
``research_evolution.adapters`` import attempt raise ``ImportError``, prints
``BLOCKER-ACTIVE`` after proving the blocker bites, then runs the given core
test modules. Exit code 0 iff the blocker bit AND all core tests pass.
"""

from __future__ import annotations

import sys
import unittest


class _AdaptersBlocker:
    """Fail-closed import blocker for the whole adapters package tree."""

    def find_spec(self, name, path=None, target=None):  # noqa: ANN001
        if name == "research_evolution.adapters" or name.startswith(
            "research_evolution.adapters."
        ):
            raise ImportError(
                f"deletion probe: {name} is not importable in this subprocess"
            )
        return None


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: _core_deletion_runner.py <test module> [<test module>...]")
        return 2
    sys.meta_path.insert(0, _AdaptersBlocker())
    try:
        import research_evolution.adapters  # noqa: F401
    except ImportError:
        print("BLOCKER-ACTIVE")
    else:
        print("BLOCKER-FAILED: research_evolution.adapters imported")
        return 2
    suite = unittest.defaultTestLoader.loadTestsFromNames(argv)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
