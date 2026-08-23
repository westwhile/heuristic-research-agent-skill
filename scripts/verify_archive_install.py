"""Install and smoke-test the exact ``git archive`` for the current commit.

The gate creates an isolated virtual environment, installs only from the
exported source tree, and runs the packaged console entry point outside both
the repository and archive roots. It therefore cannot borrow source imports,
ignored files, or repository-local schemas.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPORT_MATRIX = Path("docs/governance/SUPPORT_MATRIX.json")


class GateError(Exception):
    """A deterministic archive-install Gate failure."""


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    expected: int = 0,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != expected:
        detail = "\n".join(
            part for part in (result.stdout.strip(), result.stderr.strip()) if part
        )
        raise GateError(
            f"command exited {result.returncode}, expected {expected}: "
            f"{command!r}\n{detail}"
        )
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{path} must contain a JSON object")
    return value


def _json_stdout(result: subprocess.CompletedProcess[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateError(f"{label} did not emit valid JSON: {result.stdout!r}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{label} must emit a JSON object")
    return value


def _platform_label() -> str:
    labels = {"Linux": "ubuntu-latest", "Windows": "windows-latest"}
    try:
        return labels[platform.system()]
    except KeyError as exc:
        raise GateError(f"unsupported Gate platform: {platform.system()!r}") from exc


def _venv_paths(root: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        return root / "Scripts" / "python.exe", root / "Scripts" / "research-evolution.exe"
    return root / "bin" / "python", root / "bin" / "research-evolution"


def _clean_environment() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _validate_policy(tree: Path) -> tuple[dict[str, Any], str, str]:
    policy = _load_json(tree / SUPPORT_MATRIX)
    if policy.get("schema") != "research-evolution-support-matrix/v1":
        raise GateError("unsupported support matrix schema")
    with (tree / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    package_version = str(project["version"])
    requires_python = str(project["requires-python"])
    if policy.get("package_version") != package_version:
        raise GateError("support matrix package_version does not match pyproject.toml")
    if policy.get("requires_python") != requires_python:
        raise GateError("support matrix requires_python does not match pyproject.toml")
    current = {
        "os": _platform_label(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }
    if current not in policy.get("required_jobs", []):
        raise GateError(f"current interpreter is not a required support job: {current}")
    return policy, package_version, requires_python


def _verify_installed(
    tree: Path,
    run_root: Path,
    venv_python: Path,
    console: Path,
    package_version: str,
    policy: dict[str, Any],
    env: dict[str, str],
) -> None:
    probe_code = (
        "import importlib.metadata as m, json, pathlib, research_evolution as r;"
        "print(json.dumps({'distribution': m.version('heuristic-research-agent-skill'),"
        "'runtime': r.__version__, 'module': str(pathlib.Path(r.__file__).resolve())}))"
    )
    probe = _json_stdout(
        _run([str(venv_python), "-I", "-c", probe_code], cwd=run_root, env=env),
        "installed package probe",
    )
    if probe["distribution"] != package_version or probe["runtime"] != package_version:
        raise GateError(f"installed version mismatch: {probe}")
    module_path = Path(probe["module"])
    if module_path.is_relative_to(tree.resolve()):
        raise GateError(f"installed import leaked from archive source tree: {module_path}")
    if not module_path.is_relative_to(venv_python.parent.parent.resolve()):
        raise GateError(f"installed import is outside the isolated venv: {module_path}")

    help_result = _run([str(console), "--help"], cwd=run_root, env=env)
    if "demo" not in help_result.stdout:
        raise GateError("installed console help does not expose demo")

    gate = policy["archive_install_gate"]
    success_args = gate["success_args"]
    rejection_args = gate["rejection_args"]
    rejection_exit = gate["rejection_exit_code"]
    if not isinstance(success_args, list) or not isinstance(rejection_args, list):
        raise GateError("archive install command arguments must be lists")
    if not all(isinstance(item, str) for item in success_args + rejection_args):
        raise GateError("archive install command arguments must all be strings")
    if not isinstance(rejection_exit, int):
        raise GateError("archive install rejection exit code must be an integer")
    success = _json_stdout(
        _run([str(console), *success_args], cwd=run_root, env=env),
        "installed success demo",
    )
    validation = success.get("engineering_validation", {})
    if not validation.get("ok") or validation.get("expected_rejection"):
        raise GateError(f"installed success demo returned an invalid report: {success}")
    if validation.get("record", {}).get("schema_id") != "research-task/v1":
        raise GateError("installed success demo did not validate research-task/v1")
    if success.get("evidence_scope", {}).get("external_adoption") != "not_evaluated":
        raise GateError("installed demo lost its external-adoption boundary")

    rejection = _json_stdout(
        _run(
            [str(console), *rejection_args],
            cwd=run_root,
            env=env,
            expected=rejection_exit,
        ),
        "installed rejection demo",
    )
    rejected = rejection.get("engineering_validation", {})
    if rejected.get("ok") or not rejected.get("expected_rejection"):
        raise GateError(f"installed tamper demo was not rejected as expected: {rejection}")


def main() -> int:
    if sys.argv[1:]:
        print("usage: python -B scripts/verify_archive_install.py", file=sys.stderr)
        return 2
    env = _clean_environment()
    try:
        commit = _run(
            ["git", "rev-parse", "--verify", "HEAD^{commit}"],
            cwd=REPO_ROOT,
            env=env,
        ).stdout.strip()
        with tempfile.TemporaryDirectory(prefix="archive-install-gate-") as tmp:
            temp_root = Path(tmp)
            archive_path = temp_root / "tree.tar"
            with archive_path.open("wb") as handle:
                archived = subprocess.run(
                    ["git", "archive", "--format=tar", commit],
                    cwd=REPO_ROOT,
                    env=env,
                    stdout=handle,
                )
            if archived.returncode != 0:
                raise GateError(f"git archive failed with exit {archived.returncode}")
            tree = temp_root / "tree"
            tree.mkdir()
            with tarfile.open(archive_path) as archive:
                archive.extractall(tree, filter="data")

            policy, package_version, requires_python = _validate_policy(tree)
            venv = temp_root / "venv"
            _run([sys.executable, "-I", "-m", "venv", str(venv)], cwd=temp_root, env=env)
            venv_python, console = _venv_paths(venv)
            _run(
                [str(venv_python), "-I", "-m", "pip", "install", str(tree)],
                cwd=temp_root,
                env=env,
            )
            if not console.is_file():
                raise GateError(f"installed console entry point is missing: {console}")
            run_root = temp_root / "outside-source"
            run_root.mkdir()
            _verify_installed(
                tree,
                run_root,
                venv_python,
                console,
                package_version,
                policy,
                env,
            )
        print(
            "ARCHIVE INSTALL GATE: PASS "
            f"commit={commit} os={_platform_label()} "
            f"python={sys.version_info.major}.{sys.version_info.minor} "
            f"requires_python={requires_python} package={package_version}"
        )
        return 0
    except (GateError, OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        print(f"ARCHIVE INSTALL GATE: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
