"""Benchmark registries, runners, scorers, statistics, and reports.

Phase 3 surface, built layer by layer (ADR-0006 decision 12): E3 added
the replay envelope and the deterministic offline replay runner; E4 adds
the four-level scorer discipline and score-vector construction.
Statistics (E5), gates and meta-tests (E6), and the three report forms
(E7) extend this package additively; the surface freezes at the Phase 3
integration PR. This package is a public face PARALLEL to
``research_evolution.core`` — it never extends the core export surface.
"""

from .envelope import ERROR_CLASSES, Envelope
from .runner import ReplayResult, run_replay, runner_identity
from .scorers import (
    SCORER_LEVELS,
    ScoreEntry,
    package_judge_scores,
    package_rubric_scores,
    score_vector_payload,
    score_with_checker,
    score_with_oracle,
    scorer_identity,
    validate_score_vector,
)

__all__ = [
    "ERROR_CLASSES",
    "SCORER_LEVELS",
    "Envelope",
    "ReplayResult",
    "ScoreEntry",
    "package_judge_scores",
    "package_rubric_scores",
    "run_replay",
    "runner_identity",
    "score_vector_payload",
    "score_with_checker",
    "score_with_oracle",
    "scorer_identity",
    "validate_score_vector",
]
