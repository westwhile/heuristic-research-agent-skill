"""Close every candidate evaluation dependency without performing I/O.

The public entry point accepts immutable candidate/member data, Core artifact
records, and exact public artifact bytes. Hidden evaluator bytes are never
accepted: their ArtifactRecord must instead carry a principal-separated byte
attestation. The resulting receipt proves only byte/pin closure, not semantic
quality, evaluator independence in the real world, promotion, or installation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from research_evolution.core import (
    CoreError,
    Record,
    canonical_bytes,
    canonical_sha256,
    load_record,
)
from research_evolution.core._restricted import scan_value_for_restricted

from .incubator import (
    CandidateManifestError,
    _topological_order,
    close_candidate_bundle,
)

_ARTIFACT_SCHEMA = "artifact-record/v1"
_RECEIPT_SCHEMA = "evaluation-envelope-closure-receipt/v1"
_CANDIDATE_SCHEMA = "candidate-manifest/v1"
_REQUIRED_ROLES = (
    "authoritative_head_snapshot",
    "budget_configuration",
    "evaluator_configuration",
    "generator_configuration",
    "public_data_manifest",
    "rollback_target",
    "statistical_plan",
    "tool_configuration",
)
_MANIFEST_HASH_BINDINGS = {
    "authoritative_head_snapshot": ("context", "authoritative_head", "sha256"),
    "budget_configuration": ("evaluation_envelope", "budget_sha256"),
    "evaluator_configuration": ("evaluation_envelope", "evaluator_sha256"),
    "public_data_manifest": ("evaluation_envelope", "data_sha256"),
    "tool_configuration": ("evaluation_envelope", "tools_sha256"),
}
_LIMITATIONS = (
    "Artifact closure does not establish semantic correctness or candidate quality.",
    "Hidden evaluator attestors are protocol principals, not cryptographically "
    "verified identities.",
    "No installation, activation, publication, promotion, or external adoption is authorized.",
)


class EvaluationEnvelopeClosureError(ValueError):
    """The complete candidate/evaluation closure could not be established."""


def _nested(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = payload
    for field in path:
        value = value[field]
    return value


def _record_from_source(
    source: Record | Mapping[str, Any] | str | bytes | bytearray,
    *,
    schema_id: str,
    label: str,
) -> Record:
    try:
        record = source if isinstance(source, Record) else load_record(
            canonical_bytes(dict(source)) if isinstance(source, Mapping) else source
        )
    except (CoreError, TypeError, ValueError) as exc:
        raise EvaluationEnvelopeClosureError(f"invalid {label}: {exc}") from exc
    if record.schema_id != schema_id:
        raise EvaluationEnvelopeClosureError(
            f"expected {schema_id} for {label}, got {record.schema_id!r}"
        )
    return record


def _validate_artifact_semantics(record: Record) -> dict[str, Any]:
    payload = record.data
    restricted = scan_value_for_restricted(payload, "artifact_record")
    if restricted:
        raise EvaluationEnvelopeClosureError(
            "restricted content refused: " + "; ".join(restricted)
        )
    size = payload["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise EvaluationEnvelopeClosureError("artifact size_bytes must be non-negative")
    storage = payload["storage_class"]
    locator_present = "locator" in payload
    attestation = payload.get("attestation")
    if storage in {"bundle_member", "core_store"}:
        if not locator_present:
            raise EvaluationEnvelopeClosureError(
                f"storage class {storage!r} requires locator"
            )
        if attestation is not None:
            raise EvaluationEnvelopeClosureError(
                f"storage class {storage!r} forbids hidden attestation"
            )
        if payload["redaction_state"] == "restricted":
            raise EvaluationEnvelopeClosureError(
                f"storage class {storage!r} cannot claim restricted undisclosed bytes"
            )
    else:
        if locator_present:
            raise EvaluationEnvelopeClosureError("hidden_evaluator forbids locator")
        if payload["redaction_state"] != "restricted":
            raise EvaluationEnvelopeClosureError(
                "hidden_evaluator requires redaction_state='restricted'"
            )
        if attestation is None:
            raise EvaluationEnvelopeClosureError(
                "hidden_evaluator requires a byte attestation"
            )
        if (
            attestation["observed_content_sha256"] != payload["content_sha256"]
            or attestation["observed_size_bytes"] != size
        ):
            raise EvaluationEnvelopeClosureError(
                "hidden evaluator attestation does not match content hash or size"
            )
    return payload


@dataclass(frozen=True)
class ArtifactRecord:
    """Immutable Core record describing one closure-addressable artifact."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _ARTIFACT_SCHEMA:
            raise EvaluationEnvelopeClosureError(
                f"expected {_ARTIFACT_SCHEMA}, got {self._record.schema_id!r}"
            )
        _validate_artifact_semantics(self._record)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ArtifactRecord:
        record = _record_from_source(
            payload, schema_id=_ARTIFACT_SCHEMA, label="artifact record"
        )
        return cls(record)

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def sha256(self) -> str:
        return self._record.sha256

    @property
    def content_sha256(self) -> str:
        return self._record.data["content_sha256"]

    @property
    def storage_class(self) -> str:
        return self._record.data["storage_class"]


def _receipt_root(payload: Mapping[str, Any]) -> str:
    bound = {
        key: value
        for key, value in payload.items()
        if key not in {"envelope_closure_receipt_id", "closure_root_sha256"}
    }
    return canonical_sha256(bound)


def _receipt_id(payload: Mapping[str, Any]) -> str:
    return "envelope-closure-" + canonical_sha256(
        {
            "candidate": payload["candidate"],
            "closed_at": payload["closed_at"],
            "closure_root_sha256": payload["closure_root_sha256"],
        }
    )[:16]


@dataclass(frozen=True)
class EvaluationEnvelopeClosureReceipt:
    """Immutable receipt for candidate members plus evaluation dependencies."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _RECEIPT_SCHEMA:
            raise EvaluationEnvelopeClosureError(
                f"expected {_RECEIPT_SCHEMA}, got {self._record.schema_id!r}"
            )
        payload = self._record.data
        if payload["closure_root_sha256"] != _receipt_root(payload):
            raise EvaluationEnvelopeClosureError(
                "closure_root_sha256 does not bind the full envelope receipt"
            )
        if payload["envelope_closure_receipt_id"] != _receipt_id(payload):
            raise EvaluationEnvelopeClosureError(
                "envelope closure receipt_id does not bind candidate and root"
            )
        if payload["required_roles"] != list(_REQUIRED_ROLES):
            raise EvaluationEnvelopeClosureError("required_roles are not frozen")
        roles = [row["role"] for row in payload["artifacts"]]
        if roles != list(_REQUIRED_ROLES):
            raise EvaluationEnvelopeClosureError(
                "artifacts must cover required roles exactly once in order"
            )
        artifact_ids = [row["artifact_id"] for row in payload["artifacts"]]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise EvaluationEnvelopeClosureError("artifact identities must be unique")
        members = {row["name"]: row for row in payload["members"]}
        if len(members) != len(payload["members"]):
            raise EvaluationEnvelopeClosureError("candidate member names must be unique")
        try:
            expected_order = _topological_order(members)
        except CandidateManifestError as exc:
            raise EvaluationEnvelopeClosureError(str(exc)) from exc
        if payload["topological_order"] != expected_order:
            raise EvaluationEnvelopeClosureError(
                "topological_order is not the deterministic member order"
            )

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any]
    ) -> EvaluationEnvelopeClosureReceipt:
        record = _record_from_source(
            payload, schema_id=_RECEIPT_SCHEMA, label="envelope closure receipt"
        )
        return cls(record)

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def sha256(self) -> str:
        return self._record.sha256


def _load_artifacts(
    sources: Sequence[Record | Mapping[str, Any] | str | bytes | bytearray],
) -> dict[str, ArtifactRecord]:
    if isinstance(sources, (str, bytes, bytearray)):
        raise EvaluationEnvelopeClosureError("artifacts must be a sequence of records")
    result: dict[str, ArtifactRecord] = {}
    for source in sources:
        record = ArtifactRecord(
            _record_from_source(
                source, schema_id=_ARTIFACT_SCHEMA, label="artifact record"
            )
        )
        artifact_id = record.payload["artifact_id"]
        if artifact_id in result:
            raise EvaluationEnvelopeClosureError(
                f"duplicate artifact identity {artifact_id!r}"
            )
        result[artifact_id] = record
    return result


def _artifact_ref(record: ArtifactRecord) -> dict[str, Any]:
    payload = record.payload
    result = {
        "artifact_id": payload["artifact_id"],
        "sha256": record.sha256,
        "role": payload["role"],
        "media_type": payload["media_type"],
        "content_sha256": payload["content_sha256"],
        "size_bytes": payload["size_bytes"],
        "storage_class": payload["storage_class"],
        "redaction_state": payload["redaction_state"],
    }
    if "locator" in payload:
        result["locator"] = payload["locator"]
    return result


def close_evaluation_envelope(
    manifest: Record | Mapping[str, Any] | str | bytes | bytearray,
    member_bytes: Mapping[str, bytes],
    artifacts: Sequence[Record | Mapping[str, Any] | str | bytes | bytearray],
    artifact_bytes: Mapping[str, bytes],
    *,
    closed_at: str,
) -> EvaluationEnvelopeClosureReceipt:
    """Close candidate members and every frozen evaluation dependency.

    ``bundle_member`` artifacts are verified against candidate member bytes;
    ``core_store`` artifacts require exact bytes keyed by artifact id; and
    ``hidden_evaluator`` accepts no bytes or locator and requires an embedded
    independent byte attestation. The function performs no filesystem, network,
    installation, activation, or publication action.
    """

    try:
        member_receipt = close_candidate_bundle(
            manifest, member_bytes, closed_at=closed_at
        )
    except CandidateManifestError as exc:
        raise EvaluationEnvelopeClosureError(str(exc)) from exc
    candidate_record = _record_from_source(
        manifest, schema_id=_CANDIDATE_SCHEMA, label="candidate manifest"
    )
    candidate = candidate_record.data
    records = _load_artifacts(artifacts)
    by_role: dict[str, ArtifactRecord] = {}
    for record in records.values():
        role = record.payload["role"]
        if role in by_role:
            raise EvaluationEnvelopeClosureError(
                f"artifacts do not cover required roles exactly once: duplicate {role!r}"
            )
        by_role[role] = record
    if tuple(sorted(by_role)) != _REQUIRED_ROLES:
        missing = sorted(set(_REQUIRED_ROLES) - set(by_role))
        extra = sorted(set(by_role) - set(_REQUIRED_ROLES))
        raise EvaluationEnvelopeClosureError(
            f"artifacts must cover required roles exactly; missing={missing!r}, extra={extra!r}"
        )

    for role, path in _MANIFEST_HASH_BINDINGS.items():
        expected = _nested(candidate, path)
        if by_role[role].content_sha256 != expected:
            raise EvaluationEnvelopeClosureError(
                f"{role} artifact does not match candidate manifest hash"
            )
    rollback_hash = hashlib.sha256(candidate["rollback"].encode("utf-8")).hexdigest()
    if by_role["rollback_target"].content_sha256 != rollback_hash:
        raise EvaluationEnvelopeClosureError(
            "rollback_target artifact does not bind the candidate rollback declaration"
        )

    hidden = [
        record
        for record in records.values()
        if record.storage_class == "hidden_evaluator"
    ]
    if any(record.payload["role"] != "evaluator_configuration" for record in hidden):
        raise EvaluationEnvelopeClosureError(
            "only evaluator_configuration can be hidden; public data and rollback cannot be hidden"
        )
    principals = {
        candidate["principals"]["author"],
        candidate["principals"]["reviewer"],
    }
    for record in hidden:
        if record.payload["attestation"]["attestor"] in principals:
            raise EvaluationEnvelopeClosureError(
                "hidden evaluator attestor must be independent of author and reviewer"
            )

    expected_public_ids = {
        artifact_id
        for artifact_id, record in records.items()
        if record.storage_class == "core_store"
    }
    if set(artifact_bytes) != expected_public_ids:
        missing = sorted(expected_public_ids - set(artifact_bytes))
        extra = sorted(set(artifact_bytes) - expected_public_ids)
        raise EvaluationEnvelopeClosureError(
            f"artifact byte set mismatch; missing={missing!r}, extra={extra!r}"
        )
    declared_members = {
        row["name"]: row for row in member_receipt.payload["members"]
    }
    for artifact_id, record in records.items():
        payload = record.payload
        if record.storage_class == "bundle_member":
            locator = payload["locator"]
            if locator not in declared_members or locator not in member_bytes:
                raise EvaluationEnvelopeClosureError(
                    f"bundle artifact {artifact_id!r} locator is not a candidate member"
                )
            content = member_bytes[locator]
        elif record.storage_class == "core_store":
            content = artifact_bytes[artifact_id]
        else:
            continue
        if not isinstance(content, bytes):
            raise EvaluationEnvelopeClosureError("artifact bytes must be exact bytes")
        if hashlib.sha256(content).hexdigest() != payload["content_sha256"] or len(
            content
        ) != payload["size_bytes"]:
            raise EvaluationEnvelopeClosureError(
                f"artifact {artifact_id!r} hash or size mismatch"
            )

    member_payload = member_receipt.payload
    core = {
        "schema": _RECEIPT_SCHEMA,
        "candidate": {
            "candidate_id": candidate["candidate_id"],
            "sha256": candidate_record.sha256,
        },
        "closed_at": closed_at,
        "members": member_payload["members"],
        "topological_order": member_payload["topological_order"],
        "exclusions": member_payload["exclusions"],
        "required_roles": list(_REQUIRED_ROLES),
        "artifacts": [_artifact_ref(by_role[role]) for role in _REQUIRED_ROLES],
        "receipt_last": True,
        "candidate_members_byte_closed": True,
        "evaluation_envelope_closed": True,
        "hidden_bytes_disclosed": False,
        "semantic_review_completed": False,
        "limitations": list(_LIMITATIONS),
    }
    core["closure_root_sha256"] = _receipt_root(core)
    core["envelope_closure_receipt_id"] = _receipt_id(core)
    return EvaluationEnvelopeClosureReceipt.from_payload(core)


__all__ = [
    "ArtifactRecord",
    "EvaluationEnvelopeClosureError",
    "EvaluationEnvelopeClosureReceipt",
    "close_evaluation_envelope",
]
