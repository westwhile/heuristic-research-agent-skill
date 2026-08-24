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

from research_evolution.core._restricted import scan_for_restricted

__all__ = ["scan_for_restricted"]
