"""Benchmark registries, runners, scorers, statistics, and reports.

Phase 3 surface, built layer by layer (ADR-0006 decision 12): E3 adds the
replay envelope and the deterministic offline replay runner. Scorers
(E4), statistics (E5), gates and meta-tests (E6), and the three report
forms (E7) extend this package additively; the surface freezes at the
Phase 3 integration PR. This package is a public face PARALLEL to
``research_evolution.core`` — it never extends the core export surface.
"""

from .envelope import ERROR_CLASSES, Envelope
from .runner import ReplayResult, run_replay, runner_identity

__all__ = [
    "ERROR_CLASSES",
    "Envelope",
    "ReplayResult",
    "run_replay",
    "runner_identity",
]
