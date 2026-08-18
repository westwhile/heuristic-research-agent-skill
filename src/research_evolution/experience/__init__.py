"""Case capture, pattern registry, clustering, taxonomy, and reuse.

Phase 4 surface, built layer by layer (ADR-0007 decision 13): M3 adds the
case capture builder, the default-deny restricted-content scanner, and
the eligibility gate that keeps ineligible cases out of shareable
patterns. M4 adds the pattern registry (distillation, append-only
lifecycle versioning, deterministic chain resolution), the four-tier
layered clustering with its append-only cluster event log, the versioned
taxonomy data machine, and reuse outcome records with rebuildable
aggregates. Later layers add the deterministic retrieval MVP, the
heuristic registry, linter, and shadow runner. This package is a public
face PARALLEL to ``research_evolution.core`` — it never extends the core
export surface.
"""

from .cases import (
    ArtifactInput,
    EligibilityInput,
    assert_case_eligible,
    capture_case,
    evaluate_eligibility,
    validate_case_payload,
)
from .clustering import (
    TIERS,
    Cluster,
    append_cluster_event,
    cluster_cases,
    verify_cluster_log,
)
from .patterns import (
    PatternIndex,
    SingletonAttestation,
    build_pattern_index,
    distill_patterns,
    pattern_chain,
    transition_pattern,
)
from .redaction import scan_for_restricted
from .reuse import record_reuse_outcome, reuse_summary
from .taxonomy import Taxonomy, compose_taxonomy, load_taxonomy

__all__ = [
    "ArtifactInput",
    "Cluster",
    "EligibilityInput",
    "PatternIndex",
    "SingletonAttestation",
    "TIERS",
    "Taxonomy",
    "append_cluster_event",
    "assert_case_eligible",
    "build_pattern_index",
    "capture_case",
    "cluster_cases",
    "compose_taxonomy",
    "distill_patterns",
    "evaluate_eligibility",
    "load_taxonomy",
    "pattern_chain",
    "record_reuse_outcome",
    "reuse_summary",
    "scan_for_restricted",
    "transition_pattern",
    "validate_case_payload",
    "verify_cluster_log",
]
