"""Cross-platform process-tree and fail-closed cleanup contracts."""

from __future__ import annotations

import ctypes
import io
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from research_evolution.evolution._process_containment import (
    _terminate_windows_process_tree,
    process_facts_are_valid,
    read_output_bounded,
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


def _stop_fixture_pid(pid: int) -> None:
    if not _pid_is_running(pid):
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        os.kill(pid, signal.SIGKILL)


class ProcessContainmentTest(unittest.TestCase):
    def test_output_flood_is_bounded_during_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            started = time.monotonic()
            result = run_process_contained(
                [PYTHON_EXECUTABLE, "-c",
                 'import sys; sys.stdout.buffer.write(b"x"*(5<<20)); '
                 'sys.stderr.buffer.write(b"y"*(5<<20))'],
                cwd=Path(tmp), env=dict(os.environ), input_bytes=b"", timeout_seconds=10,
            )
        self.assertLessEqual(len(result.stdout), 4 << 20)
        self.assertLessEqual(len(result.stderr), 4 << 20)
        self.assertTrue(result.process_tree_cleanup_verified)
        self.assertLess(time.monotonic() - started, 15)
        self.assertIn(result.failure_code, {"stdout_limit_exceeded", "stderr_limit_exceeded"})

    def test_execution_cleanup_fact_mutations_fail_closed(self) -> None:
        self.assertTrue(process_facts_are_valid("executor_failed", "verified", True))
        self.assertTrue(process_facts_are_valid("timeout", "verified", True))
        self.assertTrue(process_facts_are_valid("completed", "verified", True))
        self.assertTrue(process_facts_are_valid("completed", "failed", False))
        self.assertTrue(process_facts_are_valid("cleanup_failed", "failed", False))
        for mutated in (
            ("timeout", "failed", False),
            ("cleanup_failed", "verified", True),
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

    def test_completed_parent_reaps_orphaned_descendant_before_return(self) -> None:
        for mode in ("orphan-parent", "orphan-inherited"):
            with self.subTest(mode=mode):
                self._assert_orphan_cleanup(mode)

    def _assert_orphan_cleanup(self, mode: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker_root = root / "pids"
            child_pid = None
            try:
                result = run_process_contained(
                    [
                        PYTHON_EXECUTABLE,
                        str(FIXTURE),
                        str(marker_root),
                        "1",
                        mode,
                    ],
                    cwd=root,
                    env=dict(os.environ),
                    input_bytes=b"",
                    timeout_seconds=5.0,
                    cleanup_grace_seconds=3.0,
                )
                child_pid = int((marker_root / "depth-0.pid").read_text(encoding="ascii"))

                self.assertEqual(result.execution_status, "completed")
                self.assertEqual(result.process_cleanup_status, "verified")
                self.assertTrue(result.process_tree_cleanup_verified)
                self.assertFalse(_pid_is_running(child_pid))
            finally:
                if child_pid is not None:
                    _stop_fixture_pid(child_pid)

    def test_completed_parent_cleanup_failure_preserves_execution_fact(self) -> None:
        process = Mock()
        process.pid = 12345
        process.returncode = 17
        process.poll.return_value = 17
        process.stdout = io.BytesIO(b"trace")
        process.stderr = io.BytesIO(b"private")
        process.stdin = io.BytesIO()
        with (
            patch(
                "research_evolution.evolution._process_containment.subprocess.Popen",
                return_value=process,
            ),
            patch(
                "research_evolution.evolution._process_containment._cleanup_after_completed_parent",
                return_value=("failed", False),
            ),
        ):
            result = run_process_contained(
                ["fixture"],
                cwd=Path.cwd(),
                env={},
                input_bytes=b"input",
                timeout_seconds=1.0,
                cleanup_grace_seconds=0.01,
            )

        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.execution_status, "completed")
        self.assertEqual(result.process_cleanup_status, "failed")
        self.assertFalse(result.process_tree_cleanup_verified)

    def test_cleanup_failure_is_distinct_from_timeout(self) -> None:
        process = Mock()
        process.pid = 12345
        process.returncode = None
        process.poll.return_value = None
        process.stdout = io.BytesIO(b"partial trace")
        process.stderr = io.BytesIO(b"private")
        process.stdin = io.BytesIO()
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
        self.assertEqual(result.failure_code, "timeout")
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

    def test_each_stream_has_its_own_hard_cap(self) -> None:
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream), tempfile.TemporaryDirectory() as tmp:
                result = run_process_contained(
                    [PYTHON_EXECUTABLE, "-c", f'import sys,time; '
                     f'sys.{stream}.buffer.write(b"x"*256); sys.{stream}.flush(); time.sleep(60)'],
                    cwd=Path(tmp), env=dict(os.environ), input_bytes=b"", timeout_seconds=10,
                    stdout_max_bytes=128, stderr_max_bytes=128,
                )
                self.assertEqual(result.failure_code, f"{stream}_limit_exceeded")
                self.assertEqual(len(getattr(result, stream)), 128)
                self.assertEqual(result.execution_status, "executor_failed")
                self.assertTrue(result.process_tree_cleanup_verified)

    def test_exact_caps_and_closed_stdin_do_not_trigger_false_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_process_contained(
                [PYTHON_EXECUTABLE, "-c", 'import sys; '
                 'assert sys.stdin.buffer.read()==b"input"; '
                 'sys.stdout.buffer.write(b"x"*128); sys.stderr.buffer.write(b"y"*128)'],
                cwd=Path(tmp), env=dict(os.environ), input_bytes=b"input", timeout_seconds=10,
                stdout_max_bytes=128, stderr_max_bytes=128,
            )
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(result.failure_code)
        self.assertEqual(result.stdout, b"x" * 128)
        self.assertEqual(result.stderr, b"y" * 128)
        self.assertTrue(result.process_tree_cleanup_verified)

    def test_nonfinite_budgets_and_invalid_caps_fail_before_launch(self) -> None:
        for kwargs in ({"timeout_seconds": float("nan")}, {"timeout_seconds": float("inf")},
                       {"timeout_seconds": True}, {"cleanup_grace_seconds": 0},
                       {"stdout_max_bytes": 0}, {"stderr_max_bytes": True}):
            with self.subTest(kwargs=kwargs), patch(
                "research_evolution.evolution._process_containment.subprocess.Popen"
            ) as launch, self.assertRaises(ValueError):
                run_process_contained(["fixture"], cwd=Path.cwd(), env={}, input_bytes=b"",
                                      **{"timeout_seconds": 1, **kwargs})
            launch.assert_not_called()

    def test_final_file_boundaries_never_hash_a_prefix_as_full_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "final.json"
            self.assertEqual(read_output_bounded(path, 128).error_code, "output_missing")
            path.write_bytes(b"x" * 128)
            self.assertEqual(read_output_bounded(path, 128).data, b"x" * 128)
            path.write_bytes(b"x" * 129)
            oversized = read_output_bounded(path, 128)
            self.assertEqual(oversized.error_code, "output_limit")
            self.assertEqual(oversized.size_bytes, 129)
            self.assertEqual(oversized.data, b"")
            self.assertIsNotNone(read_output_bounded(Path(tmp), 128).error_code)

    @unittest.skipIf(os.name == "nt", "POSIX FIFO contract")
    def test_fifo_final_output_cannot_block_or_be_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "final.fifo"
            os.mkfifo(path)
            self.assertEqual(read_output_bounded(path, 128).error_code, "output_not_regular")


if __name__ == "__main__":
    unittest.main()
