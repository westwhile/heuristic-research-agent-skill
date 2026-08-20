"""Frozen seam exchange types (ADR-0005 decisions 1-5).

``DomainTask``, ``ClaimAssessment``, and ``EvaluationContract`` are
adapter-layer exchange types — translation contracts between domain
semantics and the core kernel. ``DomainTask`` has two live pinned versions
(v1, frozen for the math/quant producers, and v2, which adds the ``ml``
domain label — ADR-0008 addendum A1); ``EvaluationContract`` likewise has
two live pinned versions (v1, frozen for the math/quant producers, and v2,
which adds the ``study_id``/``assessment_declaration`` binding surface the
ML adapter requires — ADR-0008 addendum A3); ``ClaimAssessment`` remains at
v1. They are NOT core record families: they
are absent from the core family registry, cannot be published to a core
store, and do not extend ``research_evolution.core.__all__``.

Every instance wraps a validated, hash-bound payload obtained through the
public core entry point ``load_record(..., schema_root=<schemas/adapters>)``,
so strict-JSON parsing, schema validation, copy discipline, and canonical
hashing all come from the one kernel engine — no parallel implementation
lives here. Kernel validation failures are re-raised as
:class:`AdapterError`: the adapter error surface is listed separately from
the core error surface and never masquerades as it (ADR-0005 decision 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_evolution.core import CoreError, Record, canonical_bytes, load_record

# Repository-local adapter schema root, mirroring the core default in
# core/records.py (same package depth). Not configurable in v1: the frozen
# seam schemas ship with the repository.
_ADAPTER_SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schemas" / "adapters"


class AdapterError(Exception):
    """Structured failure raised by seam payload loading and domain adapters.

    Not a ``CoreError`` subclass: adapter-layer failures never masquerade
    as kernel failures. ``details`` carries the underlying violation list
    when the failure came from schema validation.
    """

    def __init__(self, message: str, *, details: tuple[str, ...] = ()) -> None:
        self.details = tuple(details)
        super().__init__(message)


def _load_seam_record(expected_schema_id: str, source: Any) -> Record:
    """Validate *source* against the adapter schema root, failing as AdapterError.

    Programmatic ``dict`` payloads re-enter through ``canonical_bytes`` so
    the strict-JSON budgets and parser apply to them exactly as they do to
    wire input.
    """
    try:
        if isinstance(source, dict):
            source = canonical_bytes(source)
        record = load_record(source, schema_root=_ADAPTER_SCHEMA_ROOT)
    except CoreError as exc:
        details = tuple(getattr(exc, "violations", ()))
        raise AdapterError(
            f"invalid {expected_schema_id} payload: {exc}", details=details
        ) from exc
    if record.schema_id != expected_schema_id:
        raise AdapterError(
            f"expected a {expected_schema_id} payload, got {record.schema_id!r}"
        )
    return record


def _load_seam_record_one_of(expected_schema_ids: tuple[str, ...], source: Any) -> Record:
    """Multi-version variant of :func:`_load_seam_record` (ADR-0008 L2 addendum).

    Used for the two seam types with two live versions: ``DomainTask``
    (the ML adapter emits ``domain-task/v2`` while the math/quant
    producers keep emitting the frozen v1 shape — addendum A1) and
    ``EvaluationContract`` (the ML adapter requires the v2 binding
    surface; v1 stays frozen for the math/quant producers — addendum A3).
    Each exchange type accepts exactly the listed live versions — never
    more.
    """
    try:
        if isinstance(source, dict):
            source = canonical_bytes(source)
        record = load_record(source, schema_root=_ADAPTER_SCHEMA_ROOT)
    except CoreError as exc:
        details = tuple(getattr(exc, "violations", ()))
        raise AdapterError(
            f"invalid {', '.join(expected_schema_ids)} payload: {exc}",
            details=details,
        ) from exc
    if record.schema_id not in expected_schema_ids:
        raise AdapterError(
            f"expected one of {expected_schema_ids}, got {record.schema_id!r}"
        )
    return record


# Live domain-task versions the DomainTask exchange type accepts (ADR-0008
# L2 addendum): v1 stays frozen for the math/quant producers; v2 adds the
# ml domain label. A further domain requires the next schema version.
_DOMAIN_TASK_SCHEMA_IDS = ("domain-task/v1", "domain-task/v2")


@dataclass(frozen=True)
class DomainTask:
    """Normalized result of one domain task (ADR-0005 decision 3).

    Construction is via :meth:`from_payload` / :meth:`from_json`, which
    validate against the live ``domain-task`` versions (v1 and, since the
    ADR-0008 L2 addendum, v2 — the version carrying the three-domain
    vocabulary). ``to_core_task_payload`` is the single Adapter -> Core
    direction: domain detail travels only inside the core task's ``domain``
    label and ``domain_context``.
    """

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id not in _DOMAIN_TASK_SCHEMA_IDS:
            raise AdapterError(
                f"DomainTask wraps {_DOMAIN_TASK_SCHEMA_IDS} payloads, "
                f"got {self._record.schema_id!r}"
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DomainTask":
        """Build from a programmatic JSON tree (validated, hash-bound)."""
        return cls(_load_seam_record_one_of(_DOMAIN_TASK_SCHEMA_IDS, payload))

    @classmethod
    def from_json(cls, source: "str | bytes | bytearray") -> "DomainTask":
        """Build from strict JSON text/bytes (validated, hash-bound)."""
        return cls(_load_seam_record_one_of(_DOMAIN_TASK_SCHEMA_IDS, source))

    @property
    def sha256(self) -> str:
        """Canonical SHA-256 of the exchange payload."""
        return self._record.sha256

    @property
    def payload(self) -> dict[str, Any]:
        """A fresh copy of the validated payload; mutating it affects nothing."""
        return self._record.data

    @property
    def domain(self) -> str:
        return self._record.data["domain"]

    @property
    def domain_schema_id(self) -> str:
        return self._record.data["domain_schema_id"]

    @property
    def domain_payload(self) -> dict[str, Any]:
        return self._record.data["domain_payload"]

    @property
    def core_task_draft(self) -> dict[str, Any]:
        return self._record.data["core_task_draft"]

    def to_core_task_payload(self) -> dict[str, Any]:
        """The mapped ``research-task/v1`` draft, ready for core load/publish."""
        return self._record.data["core_task_draft"]


@dataclass(frozen=True)
class ClaimAssessment:
    """A domain assessment SUGGESTION for one claim (ADR-0005 decision 4).

    The maturity field is a CEILING, never a granted rank: promotion is
    decided by core evidence binding and the governance ladder, and
    adapters never write core records.
    """

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != "claim-assessment/v1":
            raise AdapterError(
                f"ClaimAssessment wraps claim-assessment/v1 payloads, "
                f"got {self._record.schema_id!r}"
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ClaimAssessment":
        return cls(_load_seam_record("claim-assessment/v1", payload))

    @classmethod
    def from_json(cls, source: "str | bytes | bytearray") -> "ClaimAssessment":
        return cls(_load_seam_record("claim-assessment/v1", source))

    @property
    def sha256(self) -> str:
        return self._record.sha256

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def suggested_claim_type(self) -> str:
        return self._record.data["suggested_claim_type"]

    @property
    def suggested_disposition(self) -> str:
        return self._record.data["suggested_disposition"]

    @property
    def evidence_maturity_ceiling(self) -> str:
        """Upper bound on the governance ladder — never a granted maturity."""
        return self._record.data["evidence_maturity_ceiling"]

    @property
    def reasons(self) -> list[str]:
        return self._record.data["reasons"]

    @property
    def triggered_rules(self) -> list[str]:
        return self._record.data["triggered_rules"]


# Live evaluation-contract versions the exchange type accepts: v1 stays
# frozen for the math/quant producers; v2 (ADR-0008 addendum A3) adds the
# study/assessment-declaration binding surface the ML adapter requires.
_EVALUATION_CONTRACT_SCHEMA_IDS = (
    "evaluation-contract/v1",
    "evaluation-contract/v2",
)


@dataclass(frozen=True)
class EvaluationContract:
    """Evaluation contract derived from one case payload (ADR-0005 decision 5).

    ``case_sha256`` binds the exact case payload. Two live pinned versions:
    v1 (frozen, math/quant producers) and v2 (ADR-0008 addendum A3: adds
    ``study_id`` and ``assessment_declaration`` so a consuming adapter can
    bind claim/evidence to the contract's study and compare declared
    evaluation dimensions against supplied evidence). The contract's own
    canonical hash can be pinned into core evidence inputs
    (``kind="config"``) so the judging contract stays auditable; the
    contract itself never enters the store.
    """

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id not in _EVALUATION_CONTRACT_SCHEMA_IDS:
            raise AdapterError(
                f"EvaluationContract wraps "
                f"{_EVALUATION_CONTRACT_SCHEMA_IDS} payloads, "
                f"got {self._record.schema_id!r}"
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "EvaluationContract":
        return cls(_load_seam_record_one_of(_EVALUATION_CONTRACT_SCHEMA_IDS, payload))

    @classmethod
    def from_json(cls, source: "str | bytes | bytearray") -> "EvaluationContract":
        return cls(_load_seam_record_one_of(_EVALUATION_CONTRACT_SCHEMA_IDS, source))

    @property
    def sha256(self) -> str:
        return self._record.sha256

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def case_sha256(self) -> str:
        return self._record.data["case_sha256"]

    @property
    def required_evidence(self) -> list[dict[str, Any]]:
        return self._record.data["required_evidence"]

    @property
    def forbidden_channels(self) -> list[str]:
        return self._record.data["forbidden_channels"]

    @property
    def checkpoints(self) -> list[str]:
        return self._record.data["checkpoints"]
