#!/usr/bin/env python3
"""Freeze and compare a portable Skill baseline without mutating either input."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "research-evolution-external-skill-baseline/v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_tree_hash(items: dict[str, str]) -> str:
    body = "".join(f"{path}\t{items[path]}\n" for path in sorted(items))
    return sha256_bytes(body.encode("utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def command_version(argv: list[str]) -> str | None:
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if result.returncode == 0 and output else None


def parse_checksums(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})  (.+)", raw)
        if not match:
            raise ValueError(f"invalid checksums.sha256 line {line_number}")
        digest, name = match.group(1).lower(), match.group(2).replace("\\", "/")
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts or name in result:
            raise ValueError(f"unsafe or duplicate checksum path at line {line_number}")
        result[name] = digest
    return result


def collect_installed(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise ValueError("installed Skill root is missing or not a directory")
    result: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        result[relative] = sha256_file(path)
    return result


def freeze(portable_zip: Path, installed_root: Path, output_dir: Path) -> dict[str, Any]:
    if not portable_zip.is_file():
        raise ValueError("portable ZIP is missing")
    if output_dir.resolve() == installed_root.resolve() or installed_root.resolve() in output_dir.resolve().parents:
        raise ValueError("output directory must not be the installed Skill root or its descendant")

    with zipfile.ZipFile(portable_zip, "r") as archive:
        files = [entry for entry in archive.infolist() if not entry.is_dir()]
        names = [entry.filename for entry in files]
        if len(names) != len(set(names)):
            raise ValueError("portable ZIP contains duplicate paths")
        if "package-manifest.json" not in names or "checksums.sha256" not in names:
            raise ValueError("portable ZIP lacks package-manifest.json or checksums.sha256")

        package_manifest = json.loads(archive.read("package-manifest.json"))
        payload_root = str(package_manifest["payload_root"]).strip("/")
        if not payload_root or ".." in PurePosixPath(payload_root).parts:
            raise ValueError("package payload_root is unsafe")
        checksums = parse_checksums(archive.read("checksums.sha256").decode("utf-8-sig"))

        observed_archive: dict[str, str] = {}
        checksum_mismatches: list[dict[str, str]] = []
        for entry in files:
            if entry.filename == "checksums.sha256":
                continue
            digest = sha256_bytes(archive.read(entry.filename))
            observed_archive[entry.filename] = digest
            expected = checksums.get(entry.filename)
            if expected != digest:
                checksum_mismatches.append(
                    {"path": entry.filename, "expected": expected or "missing", "observed": digest}
                )
        checksum_extra = sorted(set(checksums) - set(observed_archive))

        prefix = payload_root + "/"
        payload: dict[str, str] = {}
        for name, digest in observed_archive.items():
            if name.startswith(prefix):
                payload[name[len(prefix) :]] = digest
        if not payload:
            raise ValueError("portable ZIP payload is empty")

    installed = collect_installed(installed_root)
    missing = sorted(set(payload) - set(installed))
    extra = sorted(set(installed) - set(payload))
    mismatched = [
        {"path": path, "portable_sha256": payload[path], "installed_sha256": installed[path]}
        for path in sorted(set(payload) & set(installed))
        if payload[path] != installed[path]
    ]
    comparison_status = "pass" if not (missing or extra or mismatched) else "fail"
    checksum_status = "pass" if not (checksum_mismatches or checksum_extra) else "fail"

    environment = {
        "schema": "research-evolution-environment/v1",
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "powershell": command_version(["pwsh", "--version"]),
        "git": command_version(["git", "--version"]),
        "timezone": list(dict.fromkeys(filter(None, __import__("time").tzname))),
    }
    comparison = {
        "schema": "research-evolution-skill-tree-comparison/v1",
        "status": comparison_status,
        "portable_file_count": len(payload),
        "installed_file_count": len(installed),
        "missing_installed": missing,
        "extra_installed": extra,
        "hash_mismatches": mismatched,
    }
    baseline = {
        "schema": SCHEMA,
        "artifact": package_manifest.get("artifact"),
        "build": package_manifest.get("build"),
        "portable": {
            "file_name": portable_zip.name,
            "byte_size": portable_zip.stat().st_size,
            "sha256": sha256_file(portable_zip),
            "archive_file_count": len(names),
            "checksums_status": checksum_status,
            "checksum_mismatch_count": len(checksum_mismatches),
            "checksum_extra_count": len(checksum_extra),
        },
        "payload": {
            "root": payload_root,
            "file_count": len(payload),
            "tree_sha256": canonical_tree_hash(payload),
        },
        "installed_snapshot": {
            "locator": "local-installed-skill",
            "file_count": len(installed),
            "tree_sha256": canonical_tree_hash(installed),
        },
        "comparison": {
            "status": comparison_status,
            "missing_count": len(missing),
            "extra_count": len(extra),
            "mismatch_count": len(mismatched),
        },
        "claim_boundary": "engineering_integrity_only",
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "manifest.json", baseline)
    write_json(output_dir / "comparison.json", comparison)
    write_json(output_dir / "environment.json", environment)
    (output_dir / "files.sha256").write_text(
        "".join(f"{payload[path]}  {path}\n" for path in sorted(payload)),
        encoding="utf-8",
        newline="\n",
    )
    write_json(
        output_dir / "portable-checksum-verification.json",
        {
            "schema": "research-evolution-portable-checksum-verification/v1",
            "status": checksum_status,
            "mismatches": checksum_mismatches,
            "extra_checksum_entries": checksum_extra,
        },
    )
    (output_dir / "manifest.sha256").write_text(
        f"{sha256_file(output_dir / 'manifest.json')}  manifest.json\n",
        encoding="utf-8",
        newline="\n",
    )
    return baseline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable-zip", required=True, type=Path)
    parser.add_argument("--installed-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = freeze(args.portable_zip, args.installed_root, args.output_dir)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "passed", "manifest": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
