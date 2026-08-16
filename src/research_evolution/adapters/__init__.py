"""Domain adapters translating research semantics into core records.

Public seam surface (ADR-0005): the three frozen exchange types, the
adapter error, and the DomainAdapter seam contract. This package is a
public face PARALLEL to ``research_evolution.core`` — it does not extend
the core export surface (still 18 items), and seam payloads can never be
published to a core store.
"""

from .base import DomainAdapter
from .types import (
    AdapterError,
    ClaimAssessment,
    DomainTask,
    EvaluationContract,
)

__all__ = [
    "AdapterError",
    "ClaimAssessment",
    "DomainAdapter",
    "DomainTask",
    "EvaluationContract",
]
