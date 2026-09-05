"""Fail-closed subprocess containment for external Agent execution.

The caller gets one bounded semantic result: normal completion, launch failure,
timeout with a verified process-tree cleanup, or cleanup failure.  The module
does not interpret model output and is intentionally private to ``evolution``.
"""

from __future__ import annotations

import ctypes
import math
import os
import signal
import stat
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

_STATUS_PAIRS = frozenset(
    {
        ("not_applicable", "not_applicable"),
        ("completed", "not_required"),
        ("completed", "verified"),
        ("completed", "failed"),
        ("timeout", "verified"),
        ("launch_failed", "not_started"),
        ("cleanup_failed", "failed"),
        ("executor_failed", "unverified"),
        ("executor_failed", "verified"),
    }
)
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
    # Primary execution failure survives a later cleanup failure. Hashes in
    # consumers refer to captured bytes, never to an unobserved complete stream.
    failure_code: str | None = None


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
        and (execution_status, process_cleanup_status) in _STATUS_PAIRS
        and process_tree_cleanup_verified is (process_cleanup_status in _VERIFIED_CLEANUP_STATUSES)
    )


@dataclass(frozen=True)
class BoundedOutput:
    data: bytes
    size_bytes: int
    error_code: str | None = None


def read_output_bounded(path: Path, max_bytes: int) -> BoundedOutput:
    """Read only a regular, stable final file, with at most limit + 1 bytes.

    Oversized files have an observed size but no payload or purported full hash.
    Nonblocking open prevents a substituted POSIX FIFO from hanging the caller.
    This is bounded I/O, not a filesystem isolation or adversarial snapshot claim.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    try:
        if path.is_symlink() or path.is_junction():
            return BoundedOutput(b"", 0, "output_not_regular")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                return BoundedOutput(b"", 0, "output_not_regular")
            if before.st_size > max_bytes:
                return BoundedOutput(b"", before.st_size, "output_limit")
            data = handle.read(max_bytes + 1)
            after = os.fstat(handle.fileno())
            if len(data) > max_bytes:
                return BoundedOutput(b"", max(after.st_size, len(data)), "output_limit")
            if (before.st_size != after.st_size or len(data) != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns):
                return BoundedOutput(b"", after.st_size, "output_changed")
            return BoundedOutput(data, len(data))
    except FileNotFoundError:
        return BoundedOutput(b"", 0, "output_missing")
    except OSError:
        return BoundedOutput(b"", 0, "output_unreadable")


def _windows_kernel32() -> Any | None:
    """Load kernel32 when the runtime exposes Windows ctypes support."""

    win_dll = getattr(ctypes, "WinDLL", None)
    if win_dll is None:
        return None
    return win_dll("kernel32", use_last_error=True)


def _windows_last_error() -> int | None:
    """Return the thread-local Windows error without assuming a Windows host."""

    get_last_error = getattr(ctypes, "get_last_error", None)
    if get_last_error is None:
        return None
    return int(get_last_error())


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
    deadline = time.monotonic() + cleanup_grace_seconds
    descendants = _windows_descendant_pids(process.pid)
    if descendants is None:
        return False
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=max(0.001, deadline - time.monotonic()),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    for pid in reversed(descendants):
        running = _windows_pid_running(pid)
        if running is False:
            continue
        if time.monotonic() >= deadline:
            return False
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(0.001, deadline - time.monotonic()),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if _windows_pid_running(pid) is not False and not _windows_terminate_pid(
            pid, max(0, int((deadline - time.monotonic()) * 1000))
        ):
            return False
    try:
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except (OSError, subprocess.TimeoutExpired):
            return False
    return process.poll() is not None and all(
        _windows_pid_running(pid) is False for pid in descendants
    )


def _windows_pid_running(pid: int) -> bool | None:
    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = _windows_kernel32()
    if kernel32 is None:
        return None
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
        return False if _windows_last_error() == 87 else None
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _windows_terminate_pid(pid: int, wait_ms: int = 2000) -> bool:
    process_terminate = 0x0001
    synchronize = 0x00100000
    wait_object_0 = 0
    kernel32 = _windows_kernel32()
    if kernel32 is None:
        return False
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
        return kernel32.WaitForSingleObject(handle, min(2000, wait_ms)) == wait_object_0
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

    kernel32 = _windows_kernel32()
    if kernel32 is None:
        return None
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


def _terminate_process_tree(process: subprocess.Popen[bytes], cleanup_grace_seconds: float) -> bool:
    if os.name == "nt":
        return _terminate_windows_process_tree(process, cleanup_grace_seconds)
    return _terminate_posix_process_tree(process, cleanup_grace_seconds)


def _cleanup_after_completed_parent(
    process: subprocess.Popen[bytes], cleanup_grace_seconds: float
) -> tuple[str, bool]:
    """Verify that a completed parent left no descendant or process-group member."""

    if os.name == "nt":
        descendants = _windows_descendant_pids(process.pid)
        if descendants is None:
            return "failed", False
        cleanup_required = bool(descendants)
    else:
        cleanup_required = _process_group_exists(process.pid)
    if not cleanup_required:
        return "not_required", True
    if _terminate_process_tree(process, cleanup_grace_seconds):
        return "verified", True
    return "failed", False


def run_process_contained(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    input_bytes: bytes,
    timeout_seconds: float,
    cleanup_grace_seconds: float = 5.0,
    stdout_max_bytes: int = 4 << 20,
    stderr_max_bytes: int = 4 << 20,
) -> ContainedProcessResult:
    """Bound pipe capture while running; preserve primary cause and cleanup facts.

    Readers retain at most their cap and one probe byte, not unbounded communicate
    buffers. Owned tree cleanup precedes bounded joins; unresolved pipe workers
    also invalidate cleanup. This does not constrain files, network or escaped
    processes: the caller's sandbox remains a separate policy.
    """

    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ValueError("command must contain non-empty strings")
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value <= 0
           for value in (timeout_seconds, cleanup_grace_seconds)):
        raise ValueError("execution and cleanup timeouts must be positive")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
           for value in (stdout_max_bytes, stderr_max_bytes)):
        raise ValueError("pipe byte limits must be positive integers")
    if not isinstance(input_bytes, bytes):
        raise TypeError("input_bytes must be bytes")
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

    stdout = bytearray()
    stderr = bytearray()
    lock = threading.Lock()
    failed = threading.Event()
    causes: list[str] = []

    def reject(code: str) -> None:
        with lock:
            if not causes:
                causes.append(code)
        failed.set()

    def drain(stream: BinaryIO, buffer: bytearray, limit: int, name: str) -> None:
        try:
            while True:
                chunk = stream.read1(min(65536, limit + 1 - len(buffer)))  # type: ignore[attr-defined]
                if not chunk:
                    break
                with lock:
                    remaining = limit - len(buffer)
                    buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    reject(f"{name}_limit_exceeded")
                    break
        except (OSError, ValueError):
            reject(f"{name}_read_failed")
        finally:
            try:
                stream.close()
            except OSError:
                reject(f"{name}_close_failed")

    def feed(stream: BinaryIO) -> None:
        try:
            stream.write(input_bytes)
            stream.flush()
        except BrokenPipeError:
            # A launcher may exit without consuming stdin; preserve its exit.
            pass
        except OSError:
            reject("stdin_write_failed")
        finally:
            try:
                stream.close()
            except OSError:
                pass

    assert process.stdout is not None and process.stderr is not None and process.stdin is not None
    workers = [
        threading.Thread(target=drain, args=(process.stdout, stdout, stdout_max_bytes, "stdout"),
                         daemon=True, name="contained-stdout"),
        threading.Thread(target=drain, args=(process.stderr, stderr, stderr_max_bytes, "stderr"),
                         daemon=True, name="contained-stderr"),
        threading.Thread(target=feed, args=(process.stdin,), daemon=True, name="contained-stdin"),
    ]
    deadline = time.monotonic() + timeout_seconds
    cleanup_status, cleanup_verified = "failed", False
    try:
        for worker in workers:
            worker.start()
        while not failed.is_set() and process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reject("timeout")
                break
            failed.wait(min(0.01, remaining))
    finally:
        # Also executed for cancellation or an unexpected caller-side exception.
        if process.poll() is None:
            cleanup_verified = _terminate_process_tree(process, cleanup_grace_seconds)
            cleanup_status = "verified" if cleanup_verified else "failed"
            if not cleanup_verified:
                try:
                    process.kill()
                    process.wait(timeout=cleanup_grace_seconds)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        else:
            cleanup_status, cleanup_verified = _cleanup_after_completed_parent(
                process, cleanup_grace_seconds
            )
        join_deadline = time.monotonic() + cleanup_grace_seconds
        for worker in workers:
            if worker.ident is not None:
                worker.join(timeout=max(0, join_deadline - time.monotonic()))
        if any(worker.is_alive() for worker in workers):
            reject("pipe_cleanup_failed")
            cleanup_status, cleanup_verified = "failed", False
    with lock:
        cause = causes[0] if causes else None
        captured_stdout, captured_stderr = bytes(stdout), bytes(stderr)
    status = "completed"
    if cause is not None:
        status = (
            ("timeout" if cause == "timeout" else "executor_failed")
            if cleanup_verified else "cleanup_failed"
        )
        if cleanup_verified:
            cleanup_status = "verified"
    return ContainedProcessResult(
        returncode=process.returncode,
        stdout=captured_stdout,
        stderr=captured_stderr,
        process_started=True,
        execution_status=status,
        process_cleanup_status=cleanup_status,
        process_tree_cleanup_verified=cleanup_verified,
        failure_code=cause,
    )


__all__ = ["ContainedProcessResult", "process_facts_are_valid", "run_process_contained"]
