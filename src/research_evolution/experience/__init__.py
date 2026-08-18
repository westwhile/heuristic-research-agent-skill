"""Case capture, redaction scanning, and eligibility gating.

Phase 4 surface, built layer by layer (ADR-0007 decision 13): M3 adds the
case capture builder, the default-deny restricted-content scanner, and
the eligibility gate that keeps ineligible cases out of shareable
patterns. Later layers add clustering, pattern and heuristic
distillation, and export. This package is a public face PARALLEL to
``research_evolution.core`` — it never extends the core export surface.
"""

from .cases import (
    ArtifactInput,
    EligibilityInput,
    assert_case_eligible,
    capture_case,
    evaluate_eligibility,
    validate_case_payload,
)
from .redaction import scan_for_restricted

__all__ = [
    "ArtifactInput",
    "EligibilityInput",
    "assert_case_eligible",
    "capture_case",
    "evaluate_eligibility",
    "scan_for_restricted",
    "validate_case_payload",
]
