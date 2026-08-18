"""Tracked-content guard: files on disk under content trees must be tracked.

v0.5.0 lesson: a non-anchored ``runs/`` rule in ``.gitignore`` silently
excluded two files under ``tests/fixtures/math-archives/``; the working
tree stayed green while ``git archive`` and fresh clones failed. Working-
tree tests cannot kill ignored-file gaps, so this contract test compares
the on-disk content trees against ``git ls-files``.

The check skips cleanly when the suite runs from a ``git archive`` export
(no ``.git`` directory): there the export itself is the source of truth.
"""

import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Content trees whose files must all be tracked: fixtures, public
# benchmark data, and the Phase 4 staging evidence pack.
CONTENT_TREES = ("tests/fixtures", "benchmarks", "staging")

# Governance-protected local-only prefixes (.gitignore): these may exist
# locally and must never be committed, so they are excluded from the
# comparison. The rest of benchmarks/ keeps being scanned — narrowing the
# scan to benchmarks/public/ would miss future public subtrees.
EXCLUDED_PREFIXES = ("benchmarks/private/", "benchmarks/hidden/")


class TrackedContentTest(unittest.TestCase):
    def test_no_untracked_or_ignored_files_in_content_trees(self) -> None:
        if not (REPO_ROOT / ".git").exists():
            self.skipTest("not a git checkout (archive export); nothing to compare")
        if shutil.which("git") is None:
            self.fail(".git is present but the git executable is not on PATH")
        result = subprocess.run(
            ["git", "ls-files", "-z", "--", *CONTENT_TREES],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
        tracked = {
            entry.decode("utf-8")
            for entry in result.stdout.split(b"\0")
            if entry
        }
        on_disk = set()
        for tree in CONTENT_TREES:
            root = REPO_ROOT / tree
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    on_disk.add(path.relative_to(REPO_ROOT).as_posix())
        on_disk -= {
            path
            for path in on_disk
            if path.startswith(EXCLUDED_PREFIXES)
        }
        untracked = sorted(on_disk - tracked)
        self.assertEqual(
            untracked,
            [],
            "content files present on disk but not tracked by git "
            "(ignored or never added): " + ", ".join(untracked),
        )


if __name__ == "__main__":
    unittest.main()
