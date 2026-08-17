"""Benchmark registries, runners, scorers, statistics, and reports.

Phase 3 surface, built layer by layer (ADR-0006 decision 12): E3 added
the replay envelope and the deterministic offline replay runner; E4 adds
the four-level scorer discipline and score-vector construction; E5 adds
the three traced comparison statistics; E6 adds the six hard gates,
verdict assembly, and the evaluator meta-tests. The three report forms
(E7) extend this package additively; the surface freezes at the Phase 3
integration PR. This package is a public face PARALLEL to
``research_evolution.core`` — it never extends the core export surface.
"""

from .envelope import ERROR_CLASSES, Envelope
from .gates import (
    GATE_RESULTS,
    GATES,
    VERDICTS,
    GateConfig,
    GateResult,
    assemble_verdict,
    evaluate_gates,
    gate_results_payload,
)
from .metatests import (
    MUTATION_CLASSES,
    MetaTestReport,
    known_pair_check,
    mutate_drop_condition,
    mutate_invert_verdict,
    mutate_relax_resource_limit,
    mutation_check,
)
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
from .statistics import (
    STATISTICAL_METHODS,
    StatisticResult,
    mcnemar_exact,
    paired_bootstrap,
    rare_event_upper_bound,
    small_sample_limitation,
)

__all__ = [
    "ERROR_CLASSES",
    "GATE_RESULTS",
    "GATES",
    "MUTATION_CLASSES",
    "SCORER_LEVELS",
    "STATISTICAL_METHODS",
    "VERDICTS",
    "Envelope",
    "GateConfig",
    "GateResult",
    "MetaTestReport",
    "ReplayResult",
    "ScoreEntry",
    "StatisticResult",
    "assemble_verdict",
    "evaluate_gates",
    "gate_results_payload",
    "known_pair_check",
    "mcnemar_exact",
    "mutate_drop_condition",
    "mutate_invert_verdict",
    "mutate_relax_resource_limit",
    "mutation_check",
    "package_judge_scores",
    "package_rubric_scores",
    "paired_bootstrap",
    "rare_event_upper_bound",
    "run_replay",
    "runner_identity",
    "score_vector_payload",
    "score_with_checker",
    "score_with_oracle",
    "scorer_identity",
    "small_sample_limitation",
    "validate_score_vector",
]
