"""Release gate: run the full suite from a ``git archive`` export.

Working-tree test runs cannot kill ignored-file gaps (the v0.5.0 lesson:
two fixtures excluded by a non-anchored ``.gitignore`` rule kept the
working tree green while the tagged archive failed). This script resolves
``HEAD`` to a concrete commit, exports THAT commit via ``git archive``,
extracts it to a temporary directory, and runs the full test suite there
with exactly two interpreters — the invoking one and one other.

Usage:

    python scripts/verify_archive_suite.py <second-python>

The second interpreter is mandatory and must differ from the invoking
one; both paths and versions are printed. The final verdict line carries
the tested commit SHA: a release tag must target exactly that commit.
Exit codes: 0 = pass, 1 = a suite run failed, 2 = usage error.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _same_file(left: str, right: str) -> bool:
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(
        os.path.realpath(right)
    )


def _resolve_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _print_version(python: str) -> None:
    result = subprocess.run(
        [python, "-B", "--version"], capture_output=True, text=True, check=True
    )
    print(f"interpreter: {python} ({result.stdout.strip()})")


def run_suite(tree: Path, python: str) -> bool:
    env = dict(
        os.environ,
        PYTHONPATH=str(tree / "src"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    result = subprocess.run(
        [python, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        cwd=tree,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        print(f"--- {python} (exit 0) ---")
        for line in tail:
            print(line)
    else:
        # A gate that hides the traceback only pretends to be a gate.
        print(f"--- {python} (exit {result.returncode}) FULL OUTPUT ---")
        print(result.stdout)
        print(result.stderr)
    return result.returncode == 0


def main() -> int:
    args = sys.argv[1:]
    if len(args) != 1:
        print(
            "usage: python scripts/verify_archive_suite.py <second-python>\n"
            "exactly one second interpreter is required (dual-interpreter gate)",
            file=sys.stderr,
        )
        return 2
    second = args[0]
    if _same_file(second, sys.executable):
        print(
            "the second interpreter must differ from the invoking one:\n"
            f"  invoking: {sys.executable}\n  given:    {second}",
            file=sys.stderr,
        )
        return 2

    tested_commit = _resolve_head()
    print(f"ARCHIVE_COMMIT={tested_commit}")
    _print_version(sys.executable)
    _print_version(second)

    pythons = [sys.executable, second]
    with tempfile.TemporaryDirectory(prefix="archive-gate-") as tmp:
        tar_path = Path(tmp) / "tree.tar"
        with tar_path.open("wb") as handle:
            subprocess.run(
                ["git", "archive", "--format=tar", tested_commit],
                cwd=REPO_ROOT,
                stdout=handle,
                check=True,
            )
        tree = Path(tmp) / "tree"
        tree.mkdir()
        with tarfile.open(tar_path) as archive:
            archive.extractall(tree, filter="data")
        print(f"exported {tested_commit[:12]} to {tree}")
        ok = True
        for python in pythons:
            ok = run_suite(tree, python) and ok
    verdict = "PASS" if ok else "FAIL"
    print(f"ARCHIVE GATE: {verdict} commit={tested_commit}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
