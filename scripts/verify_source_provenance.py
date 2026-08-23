"""Verify the repository source-provenance and licensing gate.

The working-tree mode inventories tracked files plus non-ignored proposed files.
The archive mode inventories the extracted tree directly, so the same check can
run after ``git archive`` without Git metadata.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("docs/governance/SOURCE_PROVENANCE.json")
REQUIRED_EXTERNAL_FIELDS = {
    "id",
    "source_name",
    "source_url",
    "versions",
    "visible_license",
    "tracked_expression_reused",
    "tracked_use",
    "disposition",
    "notice_action",
    "evidence_sufficient_for_reuse",
}


def _inventory(root: Path) -> list[str]:
    if (root / ".git").exists():
        result = subprocess.run(
            [
                "git",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            cwd=root,
            capture_output=True,
            check=True,
        )
        return sorted(
            item.decode("utf-8").replace("\\", "/")
            for item in result.stdout.split(b"\0")
            if item
        )

    excluded_parts = {".git", ".pytest_cache", "__pycache__"}
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and not excluded_parts.intersection(path.relative_to(root).parts)
        and path.suffix not in {".pyc", ".pyo"}
    )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _classify(
    files: list[str], rules: list[dict[str, Any]]
) -> tuple[dict[str, str], dict[str, int]]:
    assignments: dict[str, str] = {}
    rule_hits: Counter[str] = Counter()
    for file_name in files:
        for rule in rules:
            if any(
                fnmatch.fnmatchcase(file_name, pattern)
                for pattern in rule.get("patterns", [])
            ):
                assignments[file_name] = str(rule.get("class", ""))
                rule_hits[str(rule.get("id", ""))] += 1
                break
    return assignments, dict(rule_hits)


def verify(root: Path = REPO_ROOT) -> dict[str, Any]:
    errors: list[str] = []
    manifest_file = root / MANIFEST_PATH
    try:
        manifest = _load_json(manifest_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"cannot load provenance manifest: {exc}"]}

    classification = manifest.get("classification", {})
    allowed = set(classification.get("allowed", []))
    rules = classification.get("rules", [])
    expected = classification.get("expected_counts", {})
    if not classification.get("first_match_wins"):
        errors.append("classification.first_match_wins must be true")
    if not isinstance(rules, list) or not rules:
        errors.append("classification.rules must be a non-empty list")
        rules = []

    files = _inventory(root)
    assignments, rule_hits = _classify(files, rules)
    unclassified = sorted(set(files) - set(assignments))
    if unclassified:
        errors.append("unclassified files: " + ", ".join(unclassified))

    counts = Counter(assignments.values())
    invalid_classes = sorted(set(counts) - allowed)
    if invalid_classes:
        errors.append("invalid provenance classes: " + ", ".join(invalid_classes))
    for category in allowed:
        counts.setdefault(category, 0)

    actual_counts = {category: counts[category] for category in sorted(allowed)}
    actual_counts["total"] = len(files)
    for category, expected_count in expected.items():
        actual_count = actual_counts.get(category)
        if actual_count != expected_count:
            errors.append(
                f"count mismatch for {category}: expected {expected_count}, "
                f"found {actual_count}"
            )
    for rule in rules:
        rule_id = str(rule.get("id", ""))
        if not rule_id:
            errors.append("every classification rule must have an id")
        elif rule_hits.get(rule_id, 0) == 0:
            errors.append(f"classification rule matched no files: {rule_id}")

    unknown_limit = manifest.get("gates", {}).get("unknown_must_equal")
    if counts["unknown"] != unknown_limit:
        errors.append(
            f"unknown gate failed: expected {unknown_limit}, found {counts['unknown']}"
        )

    project_license = manifest.get("project_license", {})
    license_file = root / str(project_license.get("license_file", ""))
    notice_file = root / str(project_license.get("notice_file", ""))
    if not license_file.is_file():
        errors.append("LICENSE file declared by the manifest is missing")
    else:
        license_text = license_file.read_text(encoding="utf-8")
        required_license_anchors = (
            "Apache License\n                           Version 2.0, January 2004",
            "http://www.apache.org/licenses/",
            "3. Grant of Patent License.",
            "END OF TERMS AND CONDITIONS",
        )
        for anchor in required_license_anchors:
            if anchor not in license_text:
                errors.append(f"LICENSE is missing canonical anchor: {anchor!r}")
    if not notice_file.is_file() or not notice_file.read_text(encoding="utf-8").strip():
        errors.append("NOTICE file declared by the manifest is missing or empty")

    try:
        with (root / "pyproject.toml").open("rb") as handle:
            package_license = tomllib.load(handle)["project"]["license"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"cannot read project license metadata: {exc}")
    else:
        required_license = manifest.get("gates", {}).get("package_license_must_equal")
        if package_license != required_license:
            errors.append(
                f"pyproject license mismatch: expected {required_license!r}, "
                f"found {package_license!r}"
            )

    rights_status = manifest.get("rights_confirmation", {}).get("status")
    if rights_status != "confirmed":
        errors.append("rights_confirmation.status must be confirmed")

    external_sources = manifest.get("external_sources", [])
    if not isinstance(external_sources, list):
        errors.append("external_sources must be a list")
        external_sources = []
    for source in external_sources:
        missing = sorted(REQUIRED_EXTERNAL_FIELDS - set(source))
        source_id = source.get("id", "<missing-id>")
        if missing:
            errors.append(f"external source {source_id} missing fields: {', '.join(missing)}")
        if source.get("tracked_expression_reused") is True:
            license_value = str(source.get("visible_license", "")).lower()
            if not license_value or "not " in license_value or "unknown" in license_value:
                errors.append(
                    f"external source {source_id} reuses expression without a clear license"
                )

    return {
        "ok": not errors,
        "mode": "working-tree" if (root / ".git").exists() else "archive",
        "manifest": MANIFEST_PATH.as_posix(),
        "files": len(files),
        "counts": actual_counts,
        "rule_hits": rule_hits,
        "unclassified": unclassified,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()
    result = verify()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        verdict = "PASS" if result["ok"] else "FAIL"
        print(f"SOURCE PROVENANCE GATE: {verdict}")
        print(f"mode={result.get('mode')} files={result.get('files')}")
        print(f"counts={json.dumps(result.get('counts'), sort_keys=True)}")
        for error in result.get("errors", []):
            print(f"ERROR: {error}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
