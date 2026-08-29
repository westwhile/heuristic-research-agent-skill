"""Fail-closed subprocess containment for external Agent execution.

The caller gets one bounded semantic result: normal completion, launch failure,
timeout with a verified process-tree cleanup, or cleanup failure.  The module
does not interpret model output and is intentionally private to ``evolution``.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

_STATUS_PAIRS = {
    "not_applicable": "not_applicable",
    "completed": "not_required",
    "timeout": "verified",
    "launch_failed": "not_started",
    "cleanup_failed": "failed",
    "executor_failed": "unverified",
}
_VERIFIED_CLEANUP_STATUSES = frozenset(
    {"not_applicable", "not_required", "not_started", "verified"}
)


@dataclass(frozen=True)
class ContainedProcessResult:
    """Sanitized execution and cleanup facts for one owned process tree."""

    returncode: int | None
    stdout: bytes
    stderr: bytes
    process_started: bool
    execution_status: str
    process_cleanup_status: str
    process_tree_cleanup_verified: bool


def process_facts_are_valid(
    execution_status: object,
    process_cleanup_status: object,
    process_tree_cleanup_verified: object,
) -> bool:
    """Return whether execution and cleanup facts form one exact semantic pair."""

    return (
        isinstance(execution_status, str)
        and isinstance(process_cleanup_status, str)
        and isinstance(process_tree_cleanup_verified, bool)
        and _STATUS_PAIRS.get(execution_status) == process_cleanup_status
        and process_tree_cleanup_verified
        is (process_cleanup_status in _VERIFIED_CLEANUP_STATUSES)
    )


def _as_bytes(value: bytes | str | None) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace")
    return b""


def _process_group_exists(process_group_id: int) -> bool:
    killpg = getattr(os, "killpg", None)
    if killpg is None:
        return False
    try:
        killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_group_exit(process_group_id: int, deadline: float) -> bool:
    while _process_group_exists(process_group_id):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def _terminate_posix_process_tree(
    process: subprocess.Popen[bytes], cleanup_grace_seconds: float
) -> bool:
    killpg = getattr(os, "killpg", None)
    if killpg is None:
        return False
    deadline = time.monotonic() + cleanup_grace_seconds
    try:
        killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        return False

    graceful_deadline = min(deadline, time.monotonic() + cleanup_grace_seconds / 2)
    if not _wait_for_group_exit(process.pid, graceful_deadline):
        try:
            killpg(process.pid, getattr(signal, "SIGKILL", 9))
        except ProcessLookupError:
            pass
        except OSError:
            return False
    remaining = max(0.001, deadline - time.monotonic())
    try:
        process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        return False
    return _wait_for_group_exit(process.pid, deadline)


def _terminate_windows_process_tree(
    process: subprocess.Popen[bytes], cleanup_grace_seconds: float
) -> bool:
    descendants = _windows_descendant_pids(process.pid)
    if descendants is None:
        return False
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=cleanup_grace_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    for pid in reversed(descendants):
        running = _windows_pid_running(pid)
        if running is False:
            continue
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=cleanup_grace_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if _windows_pid_running(pid) is not False and not _windows_terminate_pid(pid):
            return False
    try:
        process.wait(timeout=cleanup_grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=cleanup_grace_seconds)
        except (OSError, subprocess.TimeoutExpired):
            return False
    return process.poll() is not None and all(
        _windows_pid_running(pid) is False for pid in descendants
    )


def _windows_pid_running(pid: int) -> bool | None:
    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        # ERROR_INVALID_PARAMETER is the documented result for a PID that no
        # longer exists.  Access denial or any other error is not evidence of
        # exit and must remain unverified.
        return False if ctypes.get_last_error() == 87 else None
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _windows_terminate_pid(pid: int) -> bool:
    process_terminate = 0x0001
    synchronize = 0x00100000
    wait_object_0 = 0
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.WaitForSingleObject.restype = ctypes.c_ulong
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(process_terminate | synchronize, False, pid)
    if not handle:
        return _windows_pid_running(pid) is False
    try:
        if not kernel32.TerminateProcess(handle, 1):
            return _windows_pid_running(pid) is False
        return kernel32.WaitForSingleObject(handle, 2_000) == wait_object_0
    finally:
        kernel32.CloseHandle(handle)


def _windows_descendant_pids(root_pid: int) -> list[int] | None:
    th32cs_snapprocess = 0x00000002
    max_path = 260

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * max_path),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessEntry32W)]
    kernel32.Process32FirstW.restype = ctypes.c_int
    kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessEntry32W)]
    kernel32.Process32NextW.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    snapshot = kernel32.CreateToolhelp32Snapshot(th32cs_snapprocess, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if not snapshot or snapshot == invalid_handle:
        return None
    children: dict[int, list[int]] = {}
    entry = ProcessEntry32W()
    entry.dwSize = ctypes.sizeof(ProcessEntry32W)
    try:
        available = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while available:
            parent = int(entry.th32ParentProcessID)
            children.setdefault(parent, []).append(int(entry.th32ProcessID))
            entry.dwSize = ctypes.sizeof(ProcessEntry32W)
            available = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)

    descendants: list[int] = []
    pending = list(children.get(root_pid, ()))
    while pending:
        pid = pending.pop()
        descendants.append(pid)
        pending.extend(children.get(pid, ()))
    return descendants


def _terminate_process_tree(
    process: subprocess.Popen[bytes], cleanup_grace_seconds: float
) -> bool:
    if os.name == "nt":
        return _terminate_windows_process_tree(process, cleanup_grace_seconds)
    return _terminate_posix_process_tree(process, cleanup_grace_seconds)


def run_process_contained(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    input_bytes: bytes,
    timeout_seconds: float,
    cleanup_grace_seconds: float = 5.0,
) -> ContainedProcessResult:
    """Run one command and fail closed unless a timed-out tree is fully reaped."""

    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ValueError("command must contain non-empty strings")
    if timeout_seconds <= 0 or cleanup_grace_seconds <= 0:
        raise ValueError("execution and cleanup timeouts must be positive")
    try:
        if os.name == "nt":
            process = subprocess.Popen(
                list(command),
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200),
            )
        else:
            process = subprocess.Popen(
                list(command),
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
    except OSError:
        return ContainedProcessResult(
            returncode=None,
            stdout=b"",
            stderr=b"",
            process_started=False,
            execution_status="launch_failed",
            process_cleanup_status="not_started",
            process_tree_cleanup_verified=True,
        )

    try:
        stdout, stderr = process.communicate(input=input_bytes, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        partial_stdout = _as_bytes(exc.stdout)
        partial_stderr = _as_bytes(exc.stderr)
        cleanup_verified = _terminate_process_tree(process, cleanup_grace_seconds)
        if not cleanup_verified:
            try:
                process.kill()
            except OSError:
                pass
        try:
            stdout, stderr = process.communicate(timeout=cleanup_grace_seconds)
        except (OSError, subprocess.TimeoutExpired):
            stdout, stderr = partial_stdout, partial_stderr
            cleanup_verified = False
        return ContainedProcessResult(
            returncode=process.returncode,
            stdout=_as_bytes(stdout) or partial_stdout,
            stderr=_as_bytes(stderr) or partial_stderr,
            process_started=True,
            execution_status="timeout" if cleanup_verified else "cleanup_failed",
            process_cleanup_status="verified" if cleanup_verified else "failed",
            process_tree_cleanup_verified=cleanup_verified,
        )

    return ContainedProcessResult(
        returncode=process.returncode,
        stdout=_as_bytes(stdout),
        stderr=_as_bytes(stderr),
        process_started=True,
        execution_status="completed",
        process_cleanup_status="not_required",
        process_tree_cleanup_verified=True,
    )


__all__ = ["ContainedProcessResult", "process_facts_are_valid", "run_process_contained"]
