"""Frozen seam exchange types (ADR-0005 decisions 1-5).

``DomainTask``, ``ClaimAssessment``, and ``EvaluationContract`` are
adapter-layer v1 exchange types — translation contracts between domain
semantics and the core kernel. They are NOT core record families: they
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


@dataclass(frozen=True)
class DomainTask:
    """Normalized result of one domain task (ADR-0005 decision 3).

    Construction is via :meth:`from_payload` / :meth:`from_json`, which
    validate against ``domain-task/v1``. ``to_core_task_payload`` is the
    single Adapter -> Core direction: domain detail travels only inside the
    core task's ``domain`` label and ``domain_context``.
    """

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != "domain-task/v1":
            raise AdapterError(
                f"DomainTask wraps domain-task/v1 payloads, "
                f"got {self._record.schema_id!r}"
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DomainTask":
        """Build from a programmatic JSON tree (validated, hash-bound)."""
        return cls(_load_seam_record("domain-task/v1", payload))

    @classmethod
    def from_json(cls, source: "str | bytes | bytearray") -> "DomainTask":
        """Build from strict JSON text/bytes (validated, hash-bound)."""
        return cls(_load_seam_record("domain-task/v1", source))

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


@dataclass(frozen=True)
class EvaluationContract:
    """Evaluation contract derived from one case payload (ADR-0005 decision 5).

    ``case_sha256`` binds the exact case payload. The contract's own
    canonical hash can be pinned into core evidence inputs
    (``kind="config"``) so the judging contract stays auditable; the
    contract itself never enters the store.
    """

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != "evaluation-contract/v1":
            raise AdapterError(
                f"EvaluationContract wraps evaluation-contract/v1 payloads, "
                f"got {self._record.schema_id!r}"
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "EvaluationContract":
        return cls(_load_seam_record("evaluation-contract/v1", payload))

    @classmethod
    def from_json(cls, source: "str | bytes | bytearray") -> "EvaluationContract":
        return cls(_load_seam_record("evaluation-contract/v1", source))

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
