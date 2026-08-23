"""Read-only command line interface (ADR-0004, decision 8).

Four subcommands over the kernel's read operations: ``validate`` and
``hash`` a record file, ``verify-graph`` a store root, and ``demo`` a
bundled synthetic ResearchTask. The CLI never
creates, modifies, or deletes files, never touches the network, and does
not expose publish — the write path stays library-only, a deliberate
misuse-surface shrink for Phase 1D.

Output: ``--json`` writes the machine-readable report as canonical bytes
exactly as the kernel would hash them, so the report can be re-parsed by
:func:`load_strict_json` and re-hashed stably (ADR-0004, decision 10);
the default is human-readable lines. Reports go to stdout, errors to
stderr; both are written byte-exactly (UTF-8, LF newlines) on every
platform.

Exit codes: 0 = ok; 1 = validation failure or violations (the structured
report is still printed); 2 = usage errors (argparse) and input errors —
the CLI's own failure to read an input file (missing / unreadable / not
a regular file) happens before any kernel call and is reported as a
structured input error. ``CoreError`` subclasses become structured error
output with exit 1; a non-CoreError escaping a kernel call is a kernel
bug and crashes (the kernel contract says it cannot happen).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import CoreError, canonical_bytes, load_record, verify_record_graph
from .core._store import identity_of


_DEMO_TASK = {
    "schema": "research-task/v1",
    "task_id": "task-oss-quickstart-001",
    "title": "Validate a synthetic research task",
    "problem_statement": (
        "Demonstrate deterministic record validation without real research data."
    ),
    "domain": "engineering",
    "scope": {
        "time_range": "synthetic",
        "data": "bundled synthetic input only",
    },
    "resources": {"compute": "local-cpu", "budget_minutes": 1},
    "completion_criteria": [
        "The synthetic record validates and produces a canonical SHA-256."
    ],
    "permissions": ["read:bundled-demo"],
    "allowed_external_effects": [],
    "created_at": "2026-08-23T00:00:00Z",
}

_DEMO_EVIDENCE_SCOPE = {
    "data_acceptance": "not_performed",
    "external_adoption": "not_evaluated",
    "input": "bundled synthetic ResearchTask",
    "scientific_or_market_validation": "not_performed",
    "skill_installation_or_activation": "not_performed",
}

_DEMO_NON_ENTAILMENTS = [
    "No real ML training or data acceptance was performed.",
    "No mathematical, scientific, or market claim was validated.",
    "No external adoption, Skill installation, or production readiness was shown.",
]


class _InputError(Exception):
    """A CLI-side input failure (exit 2), raised before any kernel call."""


def _read_input(path_str: str) -> bytes:
    """Read a record input file; failures are input errors (exit 2)."""
    path = Path(path_str)
    if not path.exists():
        raise _InputError(f"input file does not exist: {path_str}")
    if not path.is_file():
        raise _InputError(f"input path is not a regular file: {path_str}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _InputError(f"cannot read input file {path_str!r}: {exc}") from exc


def _emit_json(payload: dict) -> None:
    # The canonical bytes of the payload, byte-exactly: hashing the raw
    # output reproduces the report's canonical hash (dogfooding the
    # kernel contract, ADR-0004 decision 10).
    sys.stdout.buffer.write(canonical_bytes(payload))


def _emit_error(error_type: str, message: str, as_json: bool) -> None:
    if as_json:
        sys.stderr.buffer.write(
            canonical_bytes({"error": {"type": error_type, "message": message}})
        )
    else:
        sys.stderr.buffer.write(
            f"error: {error_type}: {message}\n".encode("utf-8")
        )


def _cmd_validate(args: argparse.Namespace) -> int:
    record = load_record(_read_input(args.record_file))
    payload = {
        "schema_id": record.schema_id,
        # identity_of is the registry's single source for the identity
        # field; an unregistered family fails closed here exactly as it
        # would at publish time.
        "record_id": identity_of(record),
        "sha256": record.sha256,
    }
    if args.json:
        _emit_json(payload)
    else:
        sys.stdout.buffer.write(
            f"schema_id: {payload['schema_id']}\n"
            f"record_id: {payload['record_id']}\n"
            f"sha256: {payload['sha256']}\n".encode("utf-8")
        )
    return 0


def _cmd_hash(args: argparse.Namespace) -> int:
    record = load_record(_read_input(args.record_file))
    if args.json:
        _emit_json({"sha256": record.sha256})
    else:
        sys.stdout.buffer.write((record.sha256 + "\n").encode("utf-8"))
    return 0


def _cmd_verify_graph(args: argparse.Namespace) -> int:
    # The store root is the kernel's input, not a CLI input file: a
    # missing or corrupted store is a verification finding
    # (store_root_missing & co), reported fail-closed with exit 1, not a
    # usage error.
    report = verify_record_graph(args.store_root)
    if args.json:
        _emit_json(report.to_dict())
    else:
        lines = [
            f"ok: {'true' if report.ok else 'false'}",
            f"records_total: {report.records_total}",
        ]
        for family, count in sorted(report.families.items()):
            lines.append(f"family {family}: {count}")
        if report.manifest_sha256 is not None:
            lines.append(f"manifest_sha256: {report.manifest_sha256}")
        for violation in report.violations:
            lines.append(f"violation {violation.kind}: {violation.detail}")
        for parent, children in report.forks:
            lines.append(f"fork {parent}: {', '.join(children)}")
        sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))
    return 0 if report.ok else 1


def _demo_report(tamper: bool) -> tuple[dict, int]:
    task = dict(_DEMO_TASK)
    if tamper:
        # A whitespace-only title violates the frozen ResearchTask schema.
        task["title"] = "   "
    try:
        record = load_record(canonical_bytes(task))
    except CoreError as exc:
        report = {
            "demo_id": "synthetic-research-task-validation/v1",
            "engineering_validation": {
                "error": {"message": str(exc), "type": type(exc).__name__},
                "expected_rejection": tamper,
                "ok": False,
                "record": None,
            },
            "evidence_scope": _DEMO_EVIDENCE_SCOPE,
            "non_entailments": _DEMO_NON_ENTAILMENTS,
        }
        return report, 1
    report = {
        "demo_id": "synthetic-research-task-validation/v1",
        "engineering_validation": {
            "error": None,
            "expected_rejection": tamper,
            "ok": True,
            "record": {
                "record_id": identity_of(record),
                "schema_id": record.schema_id,
                "sha256": record.sha256,
            },
        },
        "evidence_scope": _DEMO_EVIDENCE_SCOPE,
        "non_entailments": _DEMO_NON_ENTAILMENTS,
    }
    return report, 0


def _cmd_demo(args: argparse.Namespace) -> int:
    report, exit_code = _demo_report(args.tamper)
    if args.json:
        _emit_json(report)
        return exit_code
    validation = report["engineering_validation"]
    status = "pass" if validation["ok"] else "rejected"
    lines = [
        "[engineering validation]",
        f"status: {status}",
        f"expected_rejection: {'true' if validation['expected_rejection'] else 'false'}",
    ]
    record = validation["record"]
    if record is not None:
        lines.extend(
            [
                f"schema_id: {record['schema_id']}",
                f"record_id: {record['record_id']}",
                f"sha256: {record['sha256']}",
            ]
        )
    else:
        error = validation["error"]
        lines.extend([f"error_type: {error['type']}", f"error: {error['message']}"])
    lines.extend(
        [
            "",
            "[evidence scope]",
            *(f"{key}: {value}" for key, value in sorted(_DEMO_EVIDENCE_SCOPE.items())),
            "",
            "[non-entailments]",
            *(f"- {item}" for item in _DEMO_NON_ENTAILMENTS),
        ]
    )
    sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-evolution",
        description="Read-only inspection of core records and stores.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text, argument in (
        ("validate", "validate a record file against its schema", "record_file"),
        ("hash", "print a record file's canonical SHA-256", "record_file"),
        ("verify-graph", "verify a store root's integrity and graph", "store_root"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument(argument)
        sub.add_argument(
            "--json",
            action="store_true",
            help="write the machine-readable report as canonical JSON bytes",
        )
    demo = subparsers.add_parser(
        "demo", help="validate a bundled synthetic ResearchTask"
    )
    demo.add_argument(
        "--tamper",
        action="store_true",
        help="run the expected rejection path with an invalid synthetic record",
    )
    demo.add_argument(
        "--json",
        action="store_true",
        help="write the machine-readable report as canonical JSON bytes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            return _cmd_validate(args)
        if args.command == "hash":
            return _cmd_hash(args)
        if args.command == "verify-graph":
            return _cmd_verify_graph(args)
        return _cmd_demo(args)
    except _InputError as exc:
        _emit_error("InputError", str(exc), args.json)
        return 2
    except CoreError as exc:
        _emit_error(type(exc).__name__, str(exc), args.json)
        return 1
