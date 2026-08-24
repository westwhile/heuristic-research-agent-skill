"""Benchmark registries, runners, scorers, statistics, and reports.

Phase 3 surface, built layer by layer (ADR-0006 decision 12): E3 added
the replay envelope and the deterministic offline replay runner; E4 adds
the four-level scorer discipline and score-vector construction; E5 adds
the three traced comparison statistics; E6 adds the six hard gates,
verdict assembly, and the evaluator meta-tests; E7 adds the record
assembly (`evaluate_case`/`compare`) and the three report forms. The
Correctness Reset CR4 additively exposes attempt-always/result-optional
payloads through the existing ``PipelineOutcome`` interface while retaining
the legacy pass/fail run projection. This package is a public
face PARALLEL to ``research_evolution.core`` — it never extends the core
export surface.
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
from .pipeline import (
    LEVELS,
    ComparePolicy,
    PipelineOutcome,
    compare,
    evaluate_case,
    interpreter_environment,
)
from .reports import render_html, render_json, render_markdown
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
    "LEVELS",
    "MUTATION_CLASSES",
    "SCORER_LEVELS",
    "STATISTICAL_METHODS",
    "VERDICTS",
    "ComparePolicy",
    "Envelope",
    "GateConfig",
    "GateResult",
    "MetaTestReport",
    "PipelineOutcome",
    "ReplayResult",
    "ScoreEntry",
    "StatisticResult",
    "assemble_verdict",
    "compare",
    "evaluate_case",
    "evaluate_gates",
    "gate_results_payload",
    "interpreter_environment",
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
    "render_html",
    "render_json",
    "render_markdown",
    "run_replay",
    "runner_identity",
    "score_vector_payload",
    "score_with_checker",
    "score_with_oracle",
    "scorer_identity",
    "small_sample_limitation",
    "validate_score_vector",
]
