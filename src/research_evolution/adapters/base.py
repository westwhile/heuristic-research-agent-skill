"""The DomainAdapter seam contract (ADR-0005 decision 2; ARCHITECTURE §4.2)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Sequence

from .types import ClaimAssessment, DomainTask, EvaluationContract


class DomainAdapter(ABC):
    """The three seam operations every domain adapter implements.

    All three operations are pure functions: no file I/O, no network, no
    clock or random-source reads (callers inject timestamps and randomness
    as inputs), and identical inputs give byte-identical outputs. Reading
    archives or data files belongs to the importer/collector layer
    (ADR-0005 decision 9), not to seam operations. Illegal domain input
    fails closed with :class:`~research_evolution.adapters.AdapterError` —
    never a bare exception, never a ``CoreError``.

    ``validate_claim`` returns a SUGGESTION (maturity ceilings, never
    granted ranks — ADR-0005 decision 4). Adapters construct core payloads
    but never read the store and never call ``verify`` to self-check;
    verification is the core's business.
    """

    @property
    @abstractmethod
    def domain(self) -> str:
        """Domain label this adapter serves (for example ``math``)."""

    @abstractmethod
    def normalize_task(self, domain_input: dict[str, Any]) -> DomainTask:
        """Normalize one domain input payload into a :class:`DomainTask`."""

    @abstractmethod
    def validate_claim(
        self,
        claim: dict[str, Any],
        evidence: Sequence[dict[str, Any]],
        contract: EvaluationContract,
    ) -> ClaimAssessment:
        """Assess one claim payload against evidence payloads under *contract*."""

    @abstractmethod
    def build_evaluation_contract(
        self, case: dict[str, Any]
    ) -> EvaluationContract:
        """Derive the evaluation contract for one case payload."""
