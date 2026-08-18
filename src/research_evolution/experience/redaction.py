"""Default-deny restricted-content scan for experience case free text.

Architecture section 7: absolute paths, identities, and restricted
content are refused by default in anything that may become shareable
research memory. This module is the scanner half of that discipline. It
reports findings; it never rewrites — there is deliberately no executor
here (ADR-0004 decision 9 defers automated rewriting).

Every finding names the field and the pattern class; the matched text
itself is never echoed back, so a finding cannot leak the very secret it
reports. The scan is conservative by contract: a false positive costs the
author a rephrasing, a false negative lands in an append-only store.
"""

import re

# One (label, pattern) entry per refused content class, in scan order;
# the order is part of the finding output and therefore frozen.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "drive-letter path",
        # The letter must not follow another letter, otherwise a URL
        # scheme suffix (the "s:/" inside "https://...") would misreport
        # as a drive letter.
        re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]"),
    ),
    ("UNC path", re.compile(r"\\\\")),
    (
        "absolute POSIX path",
        # A leading slash in a token-initial position, followed by path
        # segments. "and/or", "1/2", and relative paths such as
        # "artifacts/input.bin" do not match: their slashes never sit
        # right after a string start, whitespace, quote, or open paren.
        re.compile(r"(?:^|[\s\"'`(])/(?:[\w.-]+/)*[\w.-]+"),
    ),
    ("home-relative path", re.compile(r"(?:^|[\s\"'`(])~/")),
    ("email address", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("PEM block marker", re.compile(r"-----BEGIN")),
    ("AWS-style access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("API token fragment", re.compile(r"sk-[A-Za-z0-9]{20,}")),
)


def scan_for_restricted(text: str, field: str) -> tuple[str, ...]:
    """Return one finding per restricted pattern that matches *text*.

    *field* names the payload field being scanned and becomes part of each
    finding, so a caller aggregating findings across fields keeps the
    provenance. An empty tuple means the text is clean under every
    pattern. Findings contain the label, never the matched text.
    """
    if not isinstance(text, str):
        raise ValueError(f"{field}: scanned text must be a string, got {type(text).__name__}")
    return tuple(
        f"{field}: {label}"
        for label, pattern in _PATTERNS
        if pattern.search(text) is not None
    )
