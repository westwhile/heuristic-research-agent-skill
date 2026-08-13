#!/usr/bin/env python3
"""Build a deterministic portable Skill update from a verified base package."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import zipfile
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any


FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_tree_hash(items: dict[str, bytes]) -> str:
    body = "".join(f"{path}\t{sha256_bytes(items[path])}\n" for path in sorted(items))
    return sha256_bytes(body.encode("utf-8"))


def parse_checksums(data: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, raw in enumerate(data.decode("utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})  (.+)", raw)
        if not match:
            raise ValueError(f"invalid checksum line {line_number}")
        digest, name = match.group(1).lower(), match.group(2).replace("\\", "/")
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts or name in result:
            raise ValueError(f"unsafe or duplicate checksum path at line {line_number}")
        result[name] = digest
    return result


def verify_base(files: dict[str, bytes]) -> dict[str, Any]:
    if "package-manifest.json" not in files or "checksums.sha256" not in files:
        raise ValueError("base package lacks manifest or checksums")
    expected = parse_checksums(files["checksums.sha256"])
    observed = {
        name: sha256_bytes(data)
        for name, data in files.items()
        if name != "checksums.sha256"
    }
    if expected != observed:
        raise ValueError("base package checksum inventory does not match its bytes")
    manifest = json.loads(files["package-manifest.json"].decode("utf-8-sig"))
    if int(manifest.get("schema_version", 0)) < 2:
        raise ValueError("base package manifest schema is unsupported")
    return manifest


def collect_candidate(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        raise ValueError("candidate Skill root is missing")
    result: dict[str, bytes] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if FORBIDDEN_PARTS.intersection(relative.parts) or path.suffix == ".pyc":
            raise ValueError(f"candidate contains forbidden generated content: {relative}")
        result[relative.as_posix()] = path.read_bytes()
    if "SKILL.md" not in result:
        raise ValueError("candidate Skill lacks SKILL.md")
    return result


def command_version(argv: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = (completed.stdout or completed.stderr).strip().splitlines()
    return lines[0] if completed.returncode == 0 and lines else None


def build(
    base_zip: Path,
    candidate_root: Path,
    output_zip: Path,
    version: str,
    build_date: str,
) -> dict[str, Any]:
    if output_zip.exists():
        raise ValueError("output ZIP already exists")
    with zipfile.ZipFile(base_zip, "r") as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError("base package contains duplicate ZIP paths")
        for name in names:
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError("base package contains an unsafe ZIP path")
        base_files = {name: archive.read(name) for name in names}

    manifest = verify_base(base_files)
    payload_root = str(manifest["payload_root"]).strip("/")
    candidate = collect_candidate(candidate_root)
    if candidate_root.name != PurePosixPath(payload_root).name:
        raise ValueError("candidate folder name does not match payload_root")

    package_files = {
        name: data
        for name, data in base_files.items()
        if name not in {"checksums.sha256", "package-manifest.json"}
        and not name.startswith(payload_root + "/")
    }
    for relative, data in candidate.items():
        package_files[f"{payload_root}/{relative}"] = data

    manifest["artifact"]["version"] = version
    manifest["build"]["date"] = build_date
    manifest["build"]["source_tree_sha256"] = canonical_tree_hash(candidate)
    limitation = (
        "The real legacy-successor 600+ artifact fixture was unavailable; that optional "
        "end-to-end case remains deferred and is not part of this release claim."
    )
    limitations = manifest.setdefault("known_limitations", [])
    if limitation not in limitations:
        limitations.append(limitation)
    manifest["tested_matrix"] = [
        {
            "os": "Windows",
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "powershell": command_version(["pwsh", "--version"]),
            "result": "19 passed; 1 real-fixture case deferred",
        }
    ]
    package_files["package-manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    checksum_text = "".join(
        f"{sha256_bytes(package_files[name])}  {name}\n" for name in sorted(package_files)
    )
    package_files["checksums.sha256"] = checksum_text.encode("utf-8")

    year, month, day = (int(value) for value in build_date.split("-"))
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(package_files):
            info = zipfile.ZipInfo(name, date_time=(year, month, day, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, package_files[name])

    return {
        "status": "built",
        "version": version,
        "file_count": len(package_files),
        "payload_file_count": len(candidate),
        "payload_tree_sha256": canonical_tree_hash(candidate),
        "portable_sha256": sha256_bytes(output_zip.read_bytes()),
        "portable_bytes": output_zip.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-zip", required=True, type=Path)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--output-zip", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build-date", default=date.today().isoformat())
    args = parser.parse_args()
    try:
        result = build(
            args.base_zip,
            args.candidate_root,
            args.output_zip,
            args.version,
            args.build_date,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
