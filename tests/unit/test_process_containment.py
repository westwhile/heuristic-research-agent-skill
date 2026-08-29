"""Cross-platform process-tree and fail-closed cleanup contracts."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from research_evolution.evolution._process_containment import (
    _terminate_windows_process_tree,
    process_facts_are_valid,
    run_process_contained,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "process-tree" / "spawn_tree.py"
PYTHON_EXECUTABLE = getattr(sys, "_base_executable", sys.executable)


def _pid_is_running(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


class ProcessContainmentTest(unittest.TestCase):
    def test_execution_cleanup_fact_mutations_fail_closed(self) -> None:
        self.assertTrue(process_facts_are_valid("timeout", "verified", True))
        self.assertTrue(process_facts_are_valid("cleanup_failed", "failed", False))
        for mutated in (
            ("timeout", "failed", False),
            ("cleanup_failed", "verified", True),
            ("completed", "failed", False),
            ("launch_failed", "not_required", True),
            ("unknown", "unverified", False),
        ):
            with self.subTest(mutated=mutated):
                self.assertFalse(process_facts_are_valid(*mutated))

    def test_timeout_reaps_parent_child_and_grandchild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker_root = root / "pids"
            result = run_process_contained(
                [PYTHON_EXECUTABLE, str(FIXTURE), str(marker_root), "2"],
                cwd=root,
                env=dict(os.environ),
                input_bytes=b"",
                timeout_seconds=1.5,
                cleanup_grace_seconds=3.0,
            )

            self.assertEqual(result.execution_status, "timeout")
            self.assertEqual(result.process_cleanup_status, "verified")
            self.assertTrue(result.process_tree_cleanup_verified)
            pid_files = sorted(marker_root.glob("*.pid"))
            self.assertEqual(len(pid_files), 3)
            pids = [int(path.read_text(encoding="ascii")) for path in pid_files]
            self.assertTrue(all(not _pid_is_running(pid) for pid in pids))

    def test_cleanup_failure_is_distinct_from_timeout(self) -> None:
        process = Mock()
        process.pid = 12345
        process.returncode = None
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(
                cmd=["fixture"], timeout=0.01, output=b"partial trace", stderr=b"private"
            ),
            (b"partial trace", b"private"),
        ]
        with (
            patch(
                "research_evolution.evolution._process_containment.subprocess.Popen",
                return_value=process,
            ),
            patch(
                "research_evolution.evolution._process_containment._terminate_process_tree",
                return_value=False,
            ),
        ):
            result = run_process_contained(
                ["fixture"],
                cwd=Path.cwd(),
                env={},
                input_bytes=b"input",
                timeout_seconds=0.01,
                cleanup_grace_seconds=0.01,
            )

        self.assertEqual(result.execution_status, "cleanup_failed")
        self.assertEqual(result.process_cleanup_status, "failed")
        self.assertFalse(result.process_tree_cleanup_verified)
        self.assertTrue(result.process_started)
        process.kill.assert_called_once_with()

    def test_windows_snapshot_failure_cannot_verify_cleanup(self) -> None:
        process = Mock()
        process.pid = 12345
        with patch(
            "research_evolution.evolution._process_containment._windows_descendant_pids",
            return_value=None,
        ):
            self.assertFalse(_terminate_windows_process_tree(process, 0.01))
        process.wait.assert_not_called()


if __name__ == "__main__":
    unittest.main()
