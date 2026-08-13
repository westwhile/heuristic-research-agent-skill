#!/usr/bin/env python3
"""Run a frozen math-research-solve baseline suite and emit a path-free summary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def safe_counts(stdout: bytes, stderr: bytes) -> dict[str, int]:
    text = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
    result: dict[str, int] = {}
    ran = re.findall(r"Ran\s+(\d+)\s+tests?", text)
    if ran:
        result["unittest_tests"] = int(ran[-1])
    for key in ("assertions", "passed", "failed", "skipped"):
        matches = re.findall(rf'"{key}"\s*:\s*(\d+)', text, flags=re.IGNORECASE)
        if matches:
            result[key] = int(matches[-1])
    return result


def classify_environment_blocker(stderr: bytes) -> str | None:
    text = stderr.decode("utf-8", errors="replace")
    if "requires the installed DPAPI manifest key" in text:
        return "missing_installed_dpapi_manifest_key"
    if "ModuleNotFoundError: No module named 'yaml'" in text:
        return "missing_python_dependency_pyyaml"
    return None


def run_case(
    case_id: str,
    kind: str,
    argv: list[str],
    source: Path | None,
    timeout_seconds: int,
    logs_dir: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    env = os.environ.copy()
    env.update({"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
            env=env,
        )
        status = "passed" if completed.returncode == 0 else "failed"
        return_code: int | None = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
        blocker = classify_environment_blocker(stderr) if completed.returncode else None
        if blocker:
            status = "blocked"
    except subprocess.TimeoutExpired as exc:
        status, return_code = "timed_out", None
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
    duration = round(time.perf_counter() - started, 3)
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / f"{case_id}.stdout.log").write_bytes(stdout)
    (logs_dir / f"{case_id}.stderr.log").write_bytes(stderr)
    result = {
        "id": case_id,
        "kind": kind,
        "status": status,
        "return_code": return_code,
        "duration_seconds": duration,
        "source_sha256": sha256_file(source) if source else None,
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "stdout_sha256": sha256_bytes(stdout),
        "stderr_sha256": sha256_bytes(stderr),
        "observed_counts": safe_counts(stdout, stderr),
    }
    if status == "blocked":
        result["reason"] = blocker
    return result


def not_run(case_id: str, kind: str, source: Path, reason: str) -> dict[str, Any]:
    return {
        "id": case_id,
        "kind": kind,
        "status": "not_run",
        "reason": reason,
        "source_sha256": sha256_file(source),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--logs-dir", required=True, type=Path)
    parser.add_argument("--quick-validate", type=Path)
    parser.add_argument("--legacy-project-fixture", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()
    scripts = args.skill_root / "scripts"
    if not scripts.is_dir():
        print(json.dumps({"status": "failed", "error": "Skill scripts directory is missing"}))
        return 1
    if args.output.resolve().is_relative_to(args.skill_root.resolve()):
        print(json.dumps({"status": "failed", "error": "output must be outside the Skill root"}))
        return 1

    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    results: list[dict[str, Any]] = []

    for source in sorted(scripts.glob("test_*.py")):
        results.append(
            run_case(
                source.stem,
                "python_regression",
                [sys.executable, "-B", str(source)],
                source,
                args.timeout_seconds,
                args.logs_dir,
            )
        )

    for source in sorted(scripts.glob("test_*.ps1")):
        case_id = source.stem
        argv = ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(source)]
        if source.name == "test_math_research_legacy_successor_v8.ps1":
            if args.legacy_project_fixture and args.legacy_project_fixture.is_dir():
                argv.extend(["-RealProjectDirectory", str(args.legacy_project_fixture)])
            else:
                results.append(
                    not_run(
                        case_id,
                        "powershell_regression",
                        source,
                        "missing_required_read_only_legacy_project_fixture",
                    )
                )
                continue
        results.append(
            run_case(
                case_id,
                "powershell_regression",
                argv,
                source,
                args.timeout_seconds,
                args.logs_dir,
            )
        )

    benchmark = scripts / "benchmark_math_research_startup_v9.py"
    if benchmark.is_file():
        results.append(
            run_case(
                benchmark.stem,
                "benchmark",
                [sys.executable, "-B", str(benchmark)],
                benchmark,
                args.timeout_seconds,
                args.logs_dir,
            )
        )

    platform_cli = scripts / "math_research_platform.py"
    state_cli = scripts / "math_research_state_v9.py"
    results.extend(
        [
            run_case(
                "math_research_platform_doctor",
                "entrypoint_smoke",
                [sys.executable, "-B", str(platform_cli), "doctor", "--json"],
                platform_cli,
                60,
                args.logs_dir,
            ),
            run_case(
                "math_research_platform_help",
                "entrypoint_smoke",
                [sys.executable, "-B", str(platform_cli), "--help"],
                platform_cli,
                60,
                args.logs_dir,
            ),
            run_case(
                "math_research_state_v9_help",
                "entrypoint_smoke",
                [sys.executable, "-B", str(state_cli), "--help"],
                state_cli,
                60,
                args.logs_dir,
            ),
        ]
    )
    if args.quick_validate and args.quick_validate.is_file():
        results.append(
            run_case(
                "skill_quick_validate",
                "skill_validation",
                [sys.executable, "-B", str(args.quick_validate), str(args.skill_root)],
                args.quick_validate,
                60,
                args.logs_dir,
            )
        )
    else:
        results.append(
            {
                "id": "skill_quick_validate",
                "kind": "skill_validation",
                "status": "not_run",
                "reason": "quick_validate_script_not_supplied_or_missing",
            }
        )

    counts = {
        status: sum(item["status"] == status for item in results)
        for status in ("passed", "failed", "timed_out", "blocked", "not_run")
    }
    if counts["failed"] or counts["timed_out"]:
        suite_status = "failed"
    elif counts["blocked"] or counts["not_run"]:
        suite_status = "partial"
    else:
        suite_status = "passed"
    summary = {
        "schema": "research-evolution-regression-summary/v1",
        "suite": "math-research-solve-windows-baseline",
        "status": suite_status,
        "claim_boundary": "engineering_regression_only",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "environment": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "counts": counts,
        "cases": results,
        "limitations": [
            "Regression success does not establish mathematical research quality.",
            "A blocked or not_run case prevents a full-suite PASS claim.",
            "Raw logs are intentionally external to the public repository.",
        ],
    }
    write_json(args.output, summary)
    print(json.dumps({"status": suite_status, "counts": counts}, ensure_ascii=False))
    return 1 if suite_status == "failed" else (2 if suite_status == "partial" else 0)


if __name__ == "__main__":
    raise SystemExit(main())
