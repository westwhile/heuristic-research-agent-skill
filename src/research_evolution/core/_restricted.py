"""Deterministic restricted-content scanning for publishable records.

Findings identify only the field and pattern class. The matched value is
never included, so rejecting restricted input cannot echo it into logs or
exception reports.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("drive-letter path", re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")),
    ("UNC path", re.compile(r"\\\\")),
    (
        "absolute POSIX path",
        re.compile(r"(?:^|[\s\"'`(])/(?:[\w.-]+/)*[\w.-]+"),
    ),
    ("home-relative path", re.compile(r"(?:^|[\s\"'`(])~/")),
    ("email address", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("PEM block marker", re.compile(r"-----BEGIN")),
    ("AWS-style access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("API token fragment", re.compile(r"sk-[A-Za-z0-9]{20,}")),
)


def scan_for_restricted(text: str, field: str) -> tuple[str, ...]:
    """Return deterministic, non-echoing findings for one text field."""

    if not isinstance(text, str):
        raise ValueError(
            f"{field}: scanned text must be a string, got {type(text).__name__}"
        )
    return tuple(
        f"{field}: {label}"
        for label, pattern in _PATTERNS
        if pattern.search(text) is not None
    )


def scan_value_for_restricted(value: Any, field: str = "$") -> tuple[str, ...]:
    """Recursively scan string leaves without exposing their values."""

    if isinstance(value, str):
        return scan_for_restricted(value, field)
    if isinstance(value, Mapping):
        findings: list[str] = []
        for key in sorted(value, key=str):
            findings.extend(
                scan_value_for_restricted(value[key], f"{field}.{key}")
            )
        return tuple(findings)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        findings = []
        for index, item in enumerate(value):
            findings.extend(scan_value_for_restricted(item, f"{field}[{index}]"))
        return tuple(findings)
    return ()
