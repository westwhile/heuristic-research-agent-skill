"""Attest the P7B4 semantic-review protocol for an immutable Skill candidate.

The module validates one structured review submission against an exact P7B2
candidate and exact P7B3 static-validation receipt.  It binds review evidence
bytes, reviewer-label separation, required semantic dimensions, and a
deterministic protocol outcome.  It does not perform a semantic review itself
and never upgrades a protocol fixture into real independent-review evidence.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from research_evolution.core import (
    CoreError,
    Record,
    UnsafePathError,
    canonical_bytes,
    canonical_sha256,
    load_record,
    validate_safe_relative_path,
)
from research_evolution.core._restricted import (
    scan_for_restricted,
    scan_value_for_restricted,
)

from .skill_candidate import SkillCandidateBundle, SkillCandidateBundleError
from .skill_static_validation import (
    SkillStaticValidationError,
    SkillStaticValidationReceipt,
)

_SCHEMA = "skill-semantic-review-attestation/v1"
_PROTOCOL_VERSION = "1.0.0"
_CONTRACT_KEYS = frozenset(
    {
        "protocol_id",
        "reviewer",
        "review_evidence",
        "dimensions",
        "declared_outcome",
    }
)
_REVIEWER_KEYS = frozenset(
    {
        "principal",
        "kind",
        "session_id",
        "model_id",
        "independence_group",
        "shared_context_with_drafter",
    }
)
_EVIDENCE_KEYS = frozenset({"name", "media_type", "sha256", "size_bytes"})
_DIMENSION_KEYS = frozenset(
    {"dimension", "result", "rationale", "evidence_sha256"}
)
_DIMENSIONS = (
    "task_correctness",
    "scope_and_contraindications",
    "trigger_precision",
    "failure_and_pause_boundaries",
    "negative_transfer_risk",
    "privacy_and_license",
    "rollback_and_retirement",
)
_CHECKS = (
    "candidate_bundle_integrity",
    "static_validation_integrity",
    "static_validation_passed",
    "reviewer_label_separation",
    "review_evidence_integrity",
    "restricted_content",
    "required_dimensions",
    "outcome_consistency",
)
_LATER_FALSE_CLAIMS = (
    "real_independent_semantic_review_completed",
    "semantic_review_completed",
    "fresh_session_validated",
    "private_evaluation_completed",
    "promotion_authorized",
    "publication_authorized",
    "installation_authorized",
    "activation_authorized",
    "runtime_loaded",
)
_LIMITATIONS = (
    "This attestation proves protocol shape and byte binding, not real "
    "independent semantic review.",
    "Reviewer and session values are declared labels; identity and "
    "organizational independence are not externally verified.",
    "Synthetic accept or reject fixtures are engineering tests and are not "
    "Candidate quality evidence.",
    "No Candidate is executed, materialized, installed, activated, published, or promoted.",
)


class SkillSemanticReviewError(ValueError):
    """A P7B4 review-protocol input or immutable attestation is unsafe."""


def _load_bundle(
    source: SkillCandidateBundle
    | Record
    | Mapping[str, Any]
    | str
    | bytes
    | bytearray,
) -> SkillCandidateBundle:
    try:
        if isinstance(source, SkillCandidateBundle):
            return SkillCandidateBundle.from_payload(source.payload)
        if isinstance(source, Record):
            return SkillCandidateBundle(source)
        if isinstance(source, Mapping):
            return SkillCandidateBundle.from_payload(source)
        return SkillCandidateBundle(load_record(source))
    except (SkillCandidateBundleError, CoreError, TypeError, ValueError) as exc:
        raise SkillSemanticReviewError(
            f"invalid skill-candidate-bundle/v1: {exc}"
        ) from exc


def _load_static_receipt(
    source: SkillStaticValidationReceipt
    | Record
    | Mapping[str, Any]
    | str
    | bytes
    | bytearray,
) -> SkillStaticValidationReceipt:
    try:
        if isinstance(source, SkillStaticValidationReceipt):
            return SkillStaticValidationReceipt.from_payload(source.payload)
        if isinstance(source, Record):
            return SkillStaticValidationReceipt(source)
        if isinstance(source, Mapping):
            return SkillStaticValidationReceipt.from_payload(source)
        return SkillStaticValidationReceipt(load_record(source))
    except (SkillStaticValidationError, CoreError, TypeError, ValueError) as exc:
        raise SkillSemanticReviewError(
            f"invalid skill-static-validation-receipt/v1: {exc}"
        ) from exc


def _non_empty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillSemanticReviewError(f"{label} must be a non-empty string")
    return value


def _safe_evidence_name(value: Any) -> str:
    name = _non_empty(value, "review evidence name")
    try:
        return validate_safe_relative_path(name)
    except (UnsafePathError, TypeError, ValueError) as exc:
        raise SkillSemanticReviewError(
            f"review evidence name is unsafe: {exc}"
        ) from exc


def _hex_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise SkillSemanticReviewError(f"{label} must be lowercase SHA-256")
    return value


def _load_contract(source: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(source, Mapping) or set(source) != _CONTRACT_KEYS:
        raise SkillSemanticReviewError(
            "review contract must contain exactly the required P7B4 fields"
        )
    contract = dict(source)
    restricted = scan_value_for_restricted(contract, "semantic_review_contract")
    if restricted:
        raise SkillSemanticReviewError(
            "restricted content refused: " + "; ".join(restricted)
        )

    _non_empty(contract["protocol_id"], "protocol_id")
    if contract["declared_outcome"] not in {
        "protocol_accept",
        "protocol_reject",
        "protocol_inconclusive",
    }:
        raise SkillSemanticReviewError("declared_outcome is invalid")

    raw_reviewer = contract["reviewer"]
    if not isinstance(raw_reviewer, Mapping) or set(raw_reviewer) != _REVIEWER_KEYS:
        raise SkillSemanticReviewError(
            "reviewer must contain exactly the required declaration fields"
        )
    reviewer = dict(raw_reviewer)
    for key in (
        "principal",
        "session_id",
        "model_id",
        "independence_group",
    ):
        _non_empty(reviewer[key], f"reviewer.{key}")
    if reviewer["kind"] not in {
        "synthetic_fixture",
        "human_declared",
        "model_assisted_declared",
    }:
        raise SkillSemanticReviewError("reviewer.kind is invalid")
    if not isinstance(reviewer["shared_context_with_drafter"], bool):
        raise SkillSemanticReviewError(
            "reviewer.shared_context_with_drafter must be boolean"
        )

    raw_evidence = contract["review_evidence"]
    if not isinstance(raw_evidence, Mapping) or set(raw_evidence) != _EVIDENCE_KEYS:
        raise SkillSemanticReviewError(
            "review_evidence must contain exactly name, media_type, sha256, and size_bytes"
        )
    evidence = dict(raw_evidence)
    evidence["name"] = _safe_evidence_name(evidence["name"])
    if evidence["media_type"] not in {
        "application/json",
        "text/markdown",
        "text/plain",
    }:
        raise SkillSemanticReviewError("review_evidence.media_type is invalid")
    _hex_sha256(evidence["sha256"], "review_evidence.sha256")
    if (
        isinstance(evidence["size_bytes"], bool)
        or not isinstance(evidence["size_bytes"], int)
        or evidence["size_bytes"] < 0
    ):
        raise SkillSemanticReviewError(
            "review_evidence.size_bytes must be a non-negative integer"
        )

    raw_dimensions = contract["dimensions"]
    if not isinstance(raw_dimensions, list):
        raise SkillSemanticReviewError("dimensions must be a list")
    dimensions: dict[str, dict[str, str]] = {}
    for raw in raw_dimensions:
        if not isinstance(raw, Mapping) or set(raw) != _DIMENSION_KEYS:
            raise SkillSemanticReviewError(
                "dimension rows must contain exactly the required fields"
            )
        row = dict(raw)
        dimension = _non_empty(row["dimension"], "dimension")
        if dimension not in _DIMENSIONS or dimension in dimensions:
            raise SkillSemanticReviewError(
                "dimensions must contain each required semantic dimension exactly once"
            )
        if row["result"] not in {"satisfied", "unsatisfied", "unverified"}:
            raise SkillSemanticReviewError("dimension result is invalid")
        _non_empty(row["rationale"], "dimension rationale")
        _hex_sha256(row["evidence_sha256"], "dimension evidence_sha256")
        dimensions[dimension] = row
    if set(dimensions) != set(_DIMENSIONS):
        raise SkillSemanticReviewError(
            "dimensions must contain each required semantic dimension exactly once"
        )

    contract["reviewer"] = reviewer
    contract["review_evidence"] = evidence
    contract["dimensions"] = [dimensions[name] for name in _DIMENSIONS]
    return contract


def _dimension_outcome(dimensions: list[dict[str, str]]) -> str:
    results = {row["result"] for row in dimensions}
    if "unverified" in results:
        return "protocol_inconclusive"
    if "unsatisfied" in results:
        return "protocol_reject"
    return "protocol_accept"


def _attestation_id(payload: Mapping[str, Any]) -> str:
    bound = {
        key: value
        for key, value in payload.items()
        if key != "skill_semantic_review_attestation_id"
    }
    return "skill-semantic-review-" + canonical_sha256(bound)[:16]


@dataclass(frozen=True)
class SkillSemanticReviewAttestation:
    """Immutable result of one P7B4 protocol attestation."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _SCHEMA:
            raise SkillSemanticReviewError(
                f"expected {_SCHEMA}, got {self._record.schema_id!r}"
            )
        payload = self._record.data
        if payload["skill_semantic_review_attestation_id"] != _attestation_id(
            payload
        ):
            raise SkillSemanticReviewError("attestation id does not bind its payload")
        if [row["dimension"] for row in payload["dimensions"]] != list(
            _DIMENSIONS
        ):
            raise SkillSemanticReviewError(
                "dimensions must use the deterministic P7B4 sequence"
            )
        if [row["check"] for row in payload["checks"]] != list(_CHECKS):
            raise SkillSemanticReviewError(
                "checks must use the deterministic P7B4 sequence"
            )
        failed = any(row["result"] == "fail" for row in payload["checks"])
        expected = (
            "protocol_inconclusive"
            if failed
            else _dimension_outcome(payload["dimensions"])
        )
        if payload["outcome"] != expected:
            raise SkillSemanticReviewError("outcome does not match protocol checks")
        if bool(payload["blockers"]) != failed:
            raise SkillSemanticReviewError("blockers do not match failed checks")
        if any(payload["claims"][name] for name in _LATER_FALSE_CLAIMS):
            raise SkillSemanticReviewError(
                "protocol attestation cannot claim real review or later lifecycle evidence"
            )

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any]
    ) -> SkillSemanticReviewAttestation:
        try:
            return cls(load_record(canonical_bytes(dict(payload))))
        except SkillSemanticReviewError:
            raise
        except (CoreError, TypeError, ValueError) as exc:
            raise SkillSemanticReviewError(f"invalid {_SCHEMA}: {exc}") from exc

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def sha256(self) -> str:
        return self._record.sha256


def attest_skill_semantic_review_protocol(
    candidate_bundle: SkillCandidateBundle
    | Record
    | Mapping[str, Any]
    | str
    | bytes
    | bytearray,
    static_validation_receipt: SkillStaticValidationReceipt
    | Record
    | Mapping[str, Any]
    | str
    | bytes
    | bytearray,
    review_contract: Mapping[str, Any],
    review_evidence_bytes: bytes,
    *,
    reviewed_at: str,
) -> SkillSemanticReviewAttestation:
    """Bind one declared review to exact artifacts without performing review."""

    bundle = _load_bundle(candidate_bundle)
    static = _load_static_receipt(static_validation_receipt)
    contract = _load_contract(review_contract)
    bundle_payload = bundle.payload
    static_payload = static.payload
    reviewer = contract["reviewer"]
    blockers: list[dict[str, str]] = []
    failed_checks: set[str] = set()

    def fail(check: str, code: str, subject: str) -> None:
        failed_checks.add(check)
        blockers.append({"code": code, "subject": subject})

    static_candidate = static_payload["candidate_bundle"]
    static_bound = (
        static_candidate["skill_candidate_bundle_id"]
        == bundle_payload["skill_candidate_bundle_id"]
        and static_candidate["sha256"] == bundle.sha256
    )
    if not static_bound:
        fail(
            "static_validation_integrity",
            "static_receipt_candidate_mismatch",
            "static_validation_receipt",
        )

    static_passed = (
        static_bound
        and static_payload["outcome"] == "static_pass"
        and static_payload["claims"]["static_validation_passed"]
    )
    if not static_passed:
        fail(
            "static_validation_passed",
            "static_validation_prerequisite_not_passed",
            "static_validation_receipt",
        )

    drafter = bundle_payload["drafter"]
    static_validator = static_payload["validator"]["principal"]
    reviewer_distinct_drafter = reviewer["principal"] != drafter
    reviewer_distinct_validator = reviewer["principal"] != static_validator
    shared_context_absent = not reviewer["shared_context_with_drafter"]
    if not reviewer_distinct_drafter:
        fail(
            "reviewer_label_separation",
            "reviewer_matches_drafter_label",
            "reviewer.principal",
        )
    if not reviewer_distinct_validator:
        fail(
            "reviewer_label_separation",
            "reviewer_matches_static_validator_label",
            "reviewer.principal",
        )
    if not shared_context_absent:
        fail(
            "reviewer_label_separation",
            "shared_context_with_drafter_declared",
            "reviewer.shared_context_with_drafter",
        )

    descriptor = contract["review_evidence"]
    evidence_verified = isinstance(review_evidence_bytes, bytes)
    if evidence_verified:
        evidence_verified = (
            hashlib.sha256(review_evidence_bytes).hexdigest()
            == descriptor["sha256"]
            and len(review_evidence_bytes) == descriptor["size_bytes"]
        )
    if not evidence_verified:
        fail(
            "review_evidence_integrity",
            "review_evidence_hash_or_size_mismatch",
            descriptor["name"],
        )

    restricted_ok = evidence_verified
    if evidence_verified:
        try:
            evidence_text = review_evidence_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            restricted_ok = False
            fail(
                "review_evidence_integrity",
                "review_evidence_not_strict_utf8",
                descriptor["name"],
            )
        else:
            if scan_for_restricted(evidence_text, "semantic_review_evidence"):
                restricted_ok = False
                fail(
                    "restricted_content",
                    "restricted_content_detected",
                    descriptor["name"],
                )
    if not evidence_verified:
        restricted_ok = False
        fail(
            "restricted_content",
            "restricted_scan_incomplete",
            descriptor["name"],
        )

    dimension_evidence_bound = all(
        row["evidence_sha256"] == descriptor["sha256"]
        for row in contract["dimensions"]
    )
    if not dimension_evidence_bound:
        fail(
            "required_dimensions",
            "dimension_evidence_not_bound",
            "dimensions",
        )

    dimension_outcome = _dimension_outcome(contract["dimensions"])
    outcome_consistent = contract["declared_outcome"] == dimension_outcome
    if not outcome_consistent:
        fail(
            "outcome_consistency",
            "declared_outcome_mismatch",
            "declared_outcome",
        )

    check_results = [
        {
            "check": check,
            "result": "fail" if check in failed_checks else "pass",
        }
        for check in _CHECKS
    ]
    blockers = sorted(blockers, key=lambda row: (row["code"], row["subject"]))
    outcome = "protocol_inconclusive" if blockers else dimension_outcome
    protocol_payload = {
        "protocol_id": contract["protocol_id"],
        "version": _PROTOCOL_VERSION,
        "required_dimensions": list(_DIMENSIONS),
        "real_review_claim_authorized": False,
    }
    core: dict[str, Any] = {
        "schema": _SCHEMA,
        "candidate_bundle": {
            "skill_candidate_bundle_id": bundle_payload[
                "skill_candidate_bundle_id"
            ],
            "sha256": bundle.sha256,
        },
        "static_validation_receipt": {
            "skill_static_validation_receipt_id": static_payload[
                "skill_static_validation_receipt_id"
            ],
            "sha256": static.sha256,
        },
        "reviewed_at": reviewed_at,
        "protocol": {
            "protocol_id": contract["protocol_id"],
            "version": _PROTOCOL_VERSION,
            "sha256": canonical_sha256(protocol_payload),
        },
        "drafter": {"principal": drafter},
        "reviewer": dict(reviewer),
        "review_evidence": dict(descriptor),
        "dimensions": [dict(row) for row in contract["dimensions"]],
        "checks": check_results,
        "blockers": blockers,
        "outcome": outcome,
        "claims": {
            "exact_candidate_bound": static_bound,
            "static_validation_receipt_verified": static_bound,
            "static_validation_passed": static_passed,
            "reviewer_label_distinct_from_drafter": reviewer_distinct_drafter,
            "reviewer_label_distinct_from_static_validator": reviewer_distinct_validator,
            "shared_context_with_drafter_absent": shared_context_absent,
            "review_evidence_bytes_verified": evidence_verified,
            "restricted_content_checked": restricted_ok,
            "required_dimensions_recorded": dimension_evidence_bound,
            "semantic_review_protocol_attested": True,
            "synthetic_fixture": reviewer["kind"] == "synthetic_fixture",
            **{name: False for name in _LATER_FALSE_CLAIMS},
        },
        "limitations": list(_LIMITATIONS),
    }
    core["skill_semantic_review_attestation_id"] = _attestation_id(core)
    return SkillSemanticReviewAttestation.from_payload(core)
