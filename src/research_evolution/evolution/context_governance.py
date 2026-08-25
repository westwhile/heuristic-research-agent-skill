"""Prepare privacy-governed, byte- and token-budgeted candidate context.

The single public interface turns one immutable candidate manifest plus an
exact policy row for every material into plaintext-free governance assessments
and one ContextBundle v2.  It performs no I/O and grants no lifecycle authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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
    _RETENTION_BY_MODE,
    CandidateManifestError,
    _load_candidate,
    _validate_candidate_semantics,
)

_ASSESSMENT_SCHEMA = "context-material-assessment/v1"
_BUNDLE_SCHEMA = "context-bundle/v2"
_SAFE_CLASSIFICATIONS = frozenset({"public", "internal_safe"})
_PROTECTED_CLASSIFICATIONS = frozenset({"confidential", "restricted"})
_ESTIMATION_METHOD = "text_utf8_bytes_upper_bound/v1"
_LIMITATIONS = (
    "The token count is a deterministic UTF-8 byte upper-bound estimate, not runtime usage.",
    "Classification and reviewer principal labels are protocol assertions, not identity proof.",
    "Protected artifacts remain external and are bound only by their supplied hashes.",
    "No installation, activation, publication, semantic acceptance, or promotion is authorized.",
)


class ContextPreparationError(ValueError):
    """A governed ContextBundle v2 could not be prepared safely."""


def _record_from_payload(payload: Mapping[str, Any], schema_id: str) -> Record:
    try:
        record = load_record(canonical_bytes(dict(payload)))
    except (CoreError, TypeError, ValueError) as exc:
        raise ContextPreparationError(f"invalid {schema_id}: {exc}") from exc
    if record.schema_id != schema_id:
        raise ContextPreparationError(
            f"expected {schema_id}, got {record.schema_id!r}"
        )
    return record


def _derived_id(prefix: str, payload: Mapping[str, Any], identity: str) -> str:
    bound = {key: value for key, value in payload.items() if key != identity}
    return prefix + canonical_sha256(bound)[:16]


def _timestamp(value: str, label: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ContextPreparationError(f"{label} must be an RFC 3339 timestamp") from exc


def _unique_labels(values: list[str], label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ContextPreparationError(f"{label} must not contain duplicates")
    return tuple(sorted(values))


def _assessment_ref(assessment: ContextMaterialAssessment) -> dict[str, str]:
    return {
        "context_material_assessment_id": assessment.payload[
            "context_material_assessment_id"
        ],
        "sha256": assessment.sha256,
    }


@dataclass(frozen=True)
class ContextMaterialAssessment:
    """Immutable, plaintext-free assessment for one candidate material."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _ASSESSMENT_SCHEMA:
            raise ContextPreparationError(
                f"expected {_ASSESSMENT_SCHEMA}, got {self._record.schema_id!r}"
            )
        payload = self._record.data
        restricted = scan_value_for_restricted(payload, "context_material_assessment")
        if restricted:
            raise ContextPreparationError(
                "restricted content refused: " + "; ".join(restricted)
            )
        expected = _derived_id(
            "context-assessment-", payload, "context_material_assessment_id"
        )
        if payload["context_material_assessment_id"] != expected:
            raise ContextPreparationError("assessment id does not bind the assessment")
        material = payload["material"]
        size = material["size_bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ContextPreparationError("material size_bytes must be non-negative")
        _unique_labels(payload["source_taint_labels"], "source_taint_labels")
        residual = _unique_labels(
            payload["residual_taint_labels"], "residual_taint_labels"
        )
        assessed_at = _timestamp(payload["assessed_at"], "assessed_at")
        retention_until = _timestamp(
            payload["lifecycle"]["retention_until"], "retention_until"
        )
        if retention_until <= assessed_at:
            raise ContextPreparationError("retention_until must be after assessed_at")

        disposition = payload["disposition"]
        classification = payload["classification"]
        taints = payload["source_taint_labels"]
        redaction = payload["redaction"]
        export = payload["export"]
        encryption_required = payload["lifecycle"]["encryption_required"]
        protected = payload.get("protected_artifact")
        redaction_fields = set(redaction) - {"state"}

        if disposition == "include_original":
            if classification not in _SAFE_CLASSIFICATIONS or taints or residual:
                raise ContextPreparationError(
                    "include_original requires a safe, untainted material"
                )
            if redaction["state"] != "not_required" or redaction_fields:
                raise ContextPreparationError(
                    "include_original requires redaction state not_required"
                )
            if export["outcome"] != "allow" or encryption_required or protected:
                raise ContextPreparationError(
                    "include_original requires allow, inline-safe lifecycle metadata"
                )
        elif disposition == "include_redacted":
            required = {"output_classification", "output_sha256", "receipt_sha256"}
            if redaction["state"] != "applied" or redaction_fields != required:
                raise ContextPreparationError(
                    "include_redacted requires a complete redaction receipt"
                )
            if residual or export["outcome"] != "allow" or protected:
                raise ContextPreparationError(
                    "include_redacted requires zero residual taint and export allow"
                )
        elif disposition == "protected_hash_only":
            if classification not in _PROTECTED_CLASSIFICATIONS:
                raise ContextPreparationError(
                    "protected_hash_only requires confidential or restricted classification"
                )
            if export["outcome"] != "deny" or not encryption_required or protected is None:
                raise ContextPreparationError(
                    "protected_hash_only requires deny, encryption, and a protected artifact"
                )
            if (
                protected["content_sha256"] != material["content_sha256"]
                or protected["size_bytes"] != size
            ):
                raise ContextPreparationError(
                    "protected artifact does not bind the source material"
                )
            if redaction["state"] not in {"not_required", "rejected"} or redaction_fields:
                raise ContextPreparationError(
                    "protected_hash_only cannot carry redacted plaintext metadata"
                )
        else:
            if export["outcome"] != "deny" or protected is not None:
                raise ContextPreparationError(
                    "reject requires export deny and no protected artifact"
                )
            if redaction["state"] != "rejected" or redaction_fields:
                raise ContextPreparationError("reject requires redaction state rejected")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ContextMaterialAssessment:
        return cls(_record_from_payload(payload, _ASSESSMENT_SCHEMA))

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def sha256(self) -> str:
        return self._record.sha256


@dataclass(frozen=True)
class ContextBundleV2:
    """Immutable governed context with byte and preflight token budgets."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _BUNDLE_SCHEMA:
            raise ContextPreparationError(
                f"expected {_BUNDLE_SCHEMA}, got {self._record.schema_id!r}"
            )
        payload = self._record.data
        restricted = scan_value_for_restricted(payload, "context_bundle")
        if restricted:
            raise ContextPreparationError(
                "restricted content refused: " + "; ".join(restricted)
            )
        expected = _derived_id("context-", payload, "context_bundle_id")
        if payload["context_bundle_id"] != expected:
            raise ContextPreparationError("context_bundle_id does not bind the bundle")
        max_bytes = payload["max_bytes"]
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ContextPreparationError("max_bytes must be positive")
        if len(self._record.canonical_bytes) > max_bytes:
            raise ContextPreparationError("context bundle exceeds max_bytes")
        token_budget = payload["token_budget"]
        for field in ("estimated_tokens", "max_tokens"):
            value = token_budget[field]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ContextPreparationError(f"{field} must be positive")
        if token_budget["estimated_tokens"] > token_budget["max_tokens"]:
            raise ContextPreparationError("context bundle exceeds max_tokens")

        assessment_refs = payload["assessments"]
        assessment_ids = [row["context_material_assessment_id"] for row in assessment_refs]
        if len(set(assessment_ids)) != len(assessment_ids):
            raise ContextPreparationError("assessment identities must be unique")
        names: list[str] = []
        referenced_assessments: list[str] = []
        for group in ("included_materials", "protected_materials", "omissions"):
            for row in payload[group]:
                names.append(row["name"])
                referenced_assessments.append(
                    row["assessment"]["context_material_assessment_id"]
                )
                if group == "included_materials":
                    actual = hashlib.sha256(row["content"].encode("utf-8")).hexdigest()
                    if actual != row["content_sha256"]:
                        raise ContextPreparationError(
                            f"included material {row['name']!r} does not match its hash"
                        )
        if len(set(names)) != len(names):
            raise ContextPreparationError("context material names must partition cleanly")
        if sorted(referenced_assessments) != sorted(assessment_ids):
            raise ContextPreparationError(
                "bundle material rows must use every assessment exactly once"
            )
        if not any(
            row["retention"] == "minimal_safe"
            for group in ("included_materials", "protected_materials")
            for row in payload[group]
        ):
            raise ContextPreparationError("minimal-safe material was not preserved")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ContextBundleV2:
        return cls(_record_from_payload(payload, _BUNDLE_SCHEMA))

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def sha256(self) -> str:
        return self._record.sha256


@dataclass(frozen=True)
class ContextPreparation:
    """Complete outcome returned by :func:`prepare_context`."""

    assessments: tuple[ContextMaterialAssessment, ...]
    bundle: ContextBundleV2


def _assessment(
    *,
    candidate: Record,
    material: Mapping[str, Any],
    policy: Mapping[str, Any],
    assessed_at: str,
) -> tuple[ContextMaterialAssessment, str | None]:
    redacted_content = policy.get("redacted_content")
    redaction = dict(policy["redaction"])
    if redacted_content is not None:
        if not isinstance(redacted_content, str):
            raise ContextPreparationError("redacted_content must be text")
        findings = scan_value_for_restricted(redacted_content, "redacted_material")
        if findings:
            raise ContextPreparationError(
                "restricted content refused after redaction: " + "; ".join(findings)
            )
        actual = hashlib.sha256(redacted_content.encode("utf-8")).hexdigest()
        if redaction.get("output_sha256") != actual:
            raise ContextPreparationError("redacted output does not match its hash")
    elif policy["disposition"] == "include_redacted":
        raise ContextPreparationError("include_redacted requires redacted_content")

    material_core = {
        "name": material["name"],
        "content_sha256": material["content_sha256"],
        "size_bytes": len(material["content"].encode("utf-8")),
        "retention": material["retention"],
    }
    core: dict[str, Any] = {
        "schema": _ASSESSMENT_SCHEMA,
        "candidate": {
            "candidate_id": candidate.data["candidate_id"],
            "sha256": candidate.sha256,
        },
        "material": material_core,
        "classification": policy["classification"],
        "source_taint_labels": sorted(policy["taint_labels"]),
        "residual_taint_labels": sorted(policy.get("residual_taint_labels", [])),
        "disposition": policy["disposition"],
        "scanner": dict(policy["scanner"]),
        "redaction": redaction,
        "export": dict(policy["export"]),
        "lifecycle": {
            "retention_until": policy["retention_until"],
            "encryption_required": policy["encryption_required"],
        },
        "claims": {
            "sensitive_plaintext_persisted": False,
            "semantic_review_completed": False,
            "publication_authorized": False,
        },
        "assessed_at": assessed_at,
    }
    if "tombstone_ref" in policy:
        core["lifecycle"]["tombstone_ref"] = dict(policy["tombstone_ref"])
    if "protected_artifact" in policy:
        core["protected_artifact"] = dict(policy["protected_artifact"])
    restricted = scan_value_for_restricted(core, "context_material_assessment")
    if restricted:
        raise ContextPreparationError(
            "restricted content refused: " + "; ".join(restricted)
        )
    core["context_material_assessment_id"] = _derived_id(
        "context-assessment-", core, "context_material_assessment_id"
    )
    return ContextMaterialAssessment.from_payload(core), redacted_content


def _estimated_tokens(
    *,
    objective: str,
    obligations: list[str],
    invalidated: list[dict[str, Any]],
    included: list[dict[str, Any]],
) -> int:
    texts = [objective, *obligations]
    texts.extend(row["rationale"] for row in invalidated)
    texts.extend(row["content"] for row in included)
    return max(1, sum(len(text.encode("utf-8")) for text in texts))


def prepare_context(
    manifest: Record | Mapping[str, Any] | str | bytes | bytearray,
    *,
    material_policies: Mapping[str, Mapping[str, Any]],
    mode: str,
    max_bytes: int,
    tokenizer_id: str,
    tokenizer_revision: str,
    max_tokens: int,
    built_at: str,
) -> ContextPreparation:
    """Assess every material and build one ContextBundle v2 or fail closed."""

    if mode not in _RETENTION_BY_MODE:
        raise ContextPreparationError(f"unsupported context mode {mode!r}")
    for label, value in (("max_bytes", max_bytes), ("max_tokens", max_tokens)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ContextPreparationError(f"{label} must be a positive integer")
    if not isinstance(tokenizer_id, str) or not tokenizer_id.strip():
        raise ContextPreparationError("tokenizer_id must be non-blank")
    if not isinstance(tokenizer_revision, str) or not tokenizer_revision.strip():
        raise ContextPreparationError("tokenizer_revision must be non-blank")
    _timestamp(built_at, "built_at")

    try:
        candidate = _load_candidate(manifest)
        payload = _validate_candidate_semantics(candidate)
    except CandidateManifestError as exc:
        raise ContextPreparationError(str(exc)) from exc
    materials = {
        row["name"]: row for row in payload["context"]["materials"]
    }
    if set(material_policies) != set(materials):
        raise ContextPreparationError(
            "material policy set must exactly match candidate materials"
        )

    assessments: list[ContextMaterialAssessment] = []
    redacted: dict[str, str] = {}
    try:
        for name in sorted(materials):
            assessment, redacted_content = _assessment(
                candidate=candidate,
                material=materials[name],
                policy=material_policies[name],
                assessed_at=built_at,
            )
            assessments.append(assessment)
            if redacted_content is not None:
                redacted[name] = redacted_content
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ContextPreparationError):
            raise
        raise ContextPreparationError("material policy is incomplete or malformed") from exc

    selected = _RETENTION_BY_MODE[mode]
    included: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    omissions: list[dict[str, Any]] = []
    for assessment in assessments:
        assessed = assessment.payload
        material = assessed["material"]
        ref = _assessment_ref(assessment)
        if material["retention"] not in selected:
            omissions.append(
                {
                    "name": material["name"],
                    "content_sha256": material["content_sha256"],
                    "retention": material["retention"],
                    "assessment": ref,
                    "reason": "excluded_by_mode",
                }
            )
            continue
        disposition = assessed["disposition"]
        if disposition in {"include_original", "include_redacted"}:
            content = (
                materials[material["name"]]["content"]
                if disposition == "include_original"
                else redacted[material["name"]]
            )
            included.append(
                {
                    "name": material["name"],
                    "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "content": content,
                    "retention": material["retention"],
                    "classification": (
                        assessed["classification"]
                        if disposition == "include_original"
                        else assessed["redaction"]["output_classification"]
                    ),
                    "assessment": ref,
                    "redaction_state": assessed["redaction"]["state"],
                }
            )
        elif disposition == "protected_hash_only":
            protected.append(
                {
                    "name": material["name"],
                    "content_sha256": material["content_sha256"],
                    "size_bytes": material["size_bytes"],
                    "retention": material["retention"],
                    "classification": assessed["classification"],
                    "assessment": ref,
                    "protected_artifact": assessed["protected_artifact"],
                    "encryption_required": True,
                }
            )
        else:
            omissions.append(
                {
                    "name": material["name"],
                    "content_sha256": material["content_sha256"],
                    "retention": material["retention"],
                    "assessment": ref,
                    "reason": "rejected_by_policy",
                }
            )

    invalidated = sorted(
        (
            row
            for row in payload["context"]["source_lifecycle"]
            if row["status"] != "current"
        ),
        key=lambda row: row["source_id"],
    )
    estimated = _estimated_tokens(
        objective=payload["objective"],
        obligations=payload["context"]["unresolved_obligations"],
        invalidated=invalidated,
        included=included,
    )
    if estimated > max_tokens:
        raise ContextPreparationError(
            f"selected {mode!r} context cannot fit max_tokens={max_tokens}"
        )
    core: dict[str, Any] = {
        "schema": _BUNDLE_SCHEMA,
        "candidate": {
            "candidate_id": payload["candidate_id"],
            "sha256": candidate.sha256,
        },
        "assessments": [_assessment_ref(row) for row in assessments],
        "built_at": built_at,
        "mode": mode,
        "max_bytes": max_bytes,
        "token_budget": {
            "tokenizer_id": tokenizer_id,
            "tokenizer_revision": tokenizer_revision,
            "estimation_method": _ESTIMATION_METHOD,
            "estimated_tokens": estimated,
            "max_tokens": max_tokens,
        },
        "objective": payload["objective"],
        "authoritative_head": payload["context"]["authoritative_head"],
        "unresolved_obligations": payload["context"]["unresolved_obligations"],
        "invalidated_sources": invalidated,
        "included_materials": included,
        "protected_materials": protected,
        "omissions": omissions,
        "minimum_safe_preserved": True,
        "claims": {
            "restricted_plaintext_embedded": False,
            "runtime_token_count_verified": False,
            "installation_authorized": False,
            "activation_authorized": False,
            "publication_authorized": False,
            "semantic_review_completed": False,
        },
        "limitations": list(_LIMITATIONS),
    }
    core["context_bundle_id"] = _derived_id(
        "context-", core, "context_bundle_id"
    )
    try:
        bundle = ContextBundleV2.from_payload(core)
    except ContextPreparationError as exc:
        if "max_bytes" in str(exc) or "exceeds" in str(exc):
            raise ContextPreparationError(
                f"selected {mode!r} context cannot fit max_bytes={max_bytes}"
            ) from exc
        raise
    return ContextPreparation(tuple(assessments), bundle)
