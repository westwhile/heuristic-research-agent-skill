"""Assess whether a byte-closed candidate may enter payload drafting.

The module is intentionally narrower than semantic review or promotion.  It
binds exact criterion-evidence bytes and declared source lineage to one
candidate/closure pair, then returns an immutable preflight attestation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
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
    ArtifactClosureError,
    ArtifactClosureReceipt,
    CandidateManifestError,
    _load_candidate,
    _validate_candidate_semantics,
)

_SCHEMA = "candidate-eligibility-attestation/v1"
_CRITERIA = frozenset(
    {
        "clear_positive_triggers",
        "clear_exclusions",
        "stable_input_contract",
        "stable_output_contract",
        "explicit_failure_pause_boundaries",
        "portable_resources",
        "measurable_gain_plan",
    }
)
_REUSABLE_KIND = "reusable_skill_proposal"
_COLLISION_FIELDS = (
    ("independence_group", "independence_group_collision"),
    ("origin_run_id", "origin_run_collision"),
    ("dataset_lineage_id", "dataset_lineage_collision"),
    ("task_template_id", "task_template_collision"),
    ("semantic_duplicate_group", "semantic_duplicate_collision"),
)
_LIMITATIONS = (
    "Criterion evidence bytes are hash-bound but their semantic truth is not established.",
    "Evidence hashes are not Core-resolvable artifacts and must be closed before later use.",
    "Lineage and principal labels are protocol assertions, not external identity proof.",
    "Eligibility permits payload drafting only; it is not semantic or fresh-session review.",
    "No private evaluation, promotion, publication, installation, or activation is authorized.",
)


class CandidateEligibilityError(ValueError):
    """A candidate eligibility attestation could not be built safely."""


def _attestation_id(payload: Mapping[str, Any]) -> str:
    bound = {
        key: value
        for key, value in payload.items()
        if key != "candidate_eligibility_attestation_id"
    }
    return "candidate-eligibility-" + canonical_sha256(bound)[:16]


def _load_closure(
    source: ArtifactClosureReceipt | Record | Mapping[str, Any] | str | bytes | bytearray,
) -> ArtifactClosureReceipt:
    if isinstance(source, ArtifactClosureReceipt):
        return ArtifactClosureReceipt.from_payload(source.payload)
    try:
        if isinstance(source, Record):
            return ArtifactClosureReceipt(source)
        if isinstance(source, Mapping):
            return ArtifactClosureReceipt.from_payload(source)
        record = load_record(source)
        return ArtifactClosureReceipt(record)
    except (ArtifactClosureError, CoreError, TypeError, ValueError) as exc:
        raise CandidateEligibilityError(f"invalid artifact closure receipt: {exc}") from exc


def _expected_blockers(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    candidate_kind = payload["candidate_kind"]
    if candidate_kind != _REUSABLE_KIND:
        blockers.append(
            {"code": "candidate_kind_not_reusable", "subject": candidate_kind}
        )
    source_cases = payload["source_cases"]
    for field, code in _COLLISION_FIELDS:
        values = [row[field] for row in source_cases]
        if len(set(values)) != len(values):
            blockers.append({"code": code, "subject": field})
    for row in sorted(payload["criteria"], key=lambda item: item["criterion"]):
        if row["status"] == "unsatisfied":
            blockers.append(
                {"code": "criterion_unsatisfied", "subject": row["criterion"]}
            )
        elif row["status"] == "unverified":
            blockers.append(
                {"code": "criterion_unverified", "subject": row["criterion"]}
            )
    return blockers


def _expected_outcome(blockers: list[dict[str, str]]) -> str:
    codes = {row["code"] for row in blockers}
    if codes - {"criterion_unverified"}:
        return "ineligible"
    if "criterion_unverified" in codes:
        return "needs_more_evidence"
    return "eligible_for_payload_drafting"


@dataclass(frozen=True)
class CandidateEligibilityAttestation:
    """Immutable P7B1 preflight result with no lifecycle authority."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _SCHEMA:
            raise CandidateEligibilityError(
                f"expected {_SCHEMA}, got {self._record.schema_id!r}"
            )
        payload = self._record.data
        restricted = scan_value_for_restricted(payload, "candidate_eligibility")
        if restricted:
            raise CandidateEligibilityError(
                "restricted content refused: " + "; ".join(restricted)
            )
        if payload["candidate_eligibility_attestation_id"] != _attestation_id(payload):
            raise CandidateEligibilityError("attestation id does not bind its payload")
        criteria = [row["criterion"] for row in payload["criteria"]]
        if len(criteria) != len(set(criteria)) or set(criteria) != _CRITERIA:
            raise CandidateEligibilityError("criterion set must contain each criterion once")
        evidence_names = [row["evidence"]["name"] for row in payload["criteria"]]
        if len(evidence_names) != len(set(evidence_names)):
            raise CandidateEligibilityError("criterion evidence names must be unique")
        source_ids = [row["case_id"] for row in payload["source_cases"]]
        if len(source_ids) != len(set(source_ids)):
            raise CandidateEligibilityError("source case identities must be unique")
        distinct_groups = len(
            {row["independence_group"] for row in payload["source_cases"]}
        )
        if payload["distinct_independence_groups"] != distinct_groups:
            raise CandidateEligibilityError(
                "distinct_independence_groups does not bind source cases"
            )
        expected_blockers = _expected_blockers(payload)
        if payload["blockers"] != expected_blockers:
            raise CandidateEligibilityError("blockers do not bind eligibility inputs")
        if payload["outcome"] != _expected_outcome(expected_blockers):
            raise CandidateEligibilityError("outcome does not bind eligibility blockers")

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any]
    ) -> CandidateEligibilityAttestation:
        try:
            return cls(load_record(canonical_bytes(dict(payload))))
        except CandidateEligibilityError:
            raise
        except (CoreError, TypeError, ValueError) as exc:
            raise CandidateEligibilityError(f"invalid {_SCHEMA}: {exc}") from exc

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def sha256(self) -> str:
        return self._record.sha256


def assess_candidate_eligibility(
    manifest: Record | Mapping[str, Any] | str | bytes | bytearray,
    closure_receipt: ArtifactClosureReceipt
    | Record
    | Mapping[str, Any]
    | str
    | bytes
    | bytearray,
    assessment: Mapping[str, Any],
    evidence_bytes: Mapping[str, bytes],
    *,
    assessed_at: str,
) -> CandidateEligibilityAttestation:
    """Return a byte-bound eligibility outcome or fail on malformed inputs."""

    try:
        candidate = _load_candidate(manifest)
        candidate_payload = _validate_candidate_semantics(candidate)
    except CandidateManifestError as exc:
        raise CandidateEligibilityError(str(exc)) from exc
    closure = _load_closure(closure_receipt)
    expected_candidate = {
        "candidate_id": candidate_payload["candidate_id"],
        "sha256": candidate.sha256,
    }
    if closure.payload["candidate"] != expected_candidate:
        raise CandidateEligibilityError("closure receipt does not bind the candidate")

    restricted = scan_value_for_restricted(assessment, "candidate_eligibility_input")
    if restricted:
        raise CandidateEligibilityError(
            "restricted content refused: " + "; ".join(restricted)
        )
    try:
        assessor = assessment["assessor"]
        if assessor == candidate_payload["principals"]["author"]:
            raise CandidateEligibilityError(
                "eligibility assessor label must differ from candidate author"
            )
        source_cases = [dict(row) for row in assessment["source_cases"]]
        case_ids = [row["case_id"] for row in source_cases]
        if len(case_ids) != len(set(case_ids)):
            raise CandidateEligibilityError("source case identities must be unique")
        declared = {
            row["case_id"]: row["sha256"] for row in candidate_payload["source_cases"]
        }
        supplied = {row["case_id"]: row["sha256"] for row in source_cases}
        if supplied != declared:
            raise CandidateEligibilityError(
                "source case set must exactly match candidate source cases"
            )
        criteria = [dict(row) for row in assessment["criteria"]]
        criterion_names = [row["criterion"] for row in criteria]
        if len(criterion_names) != len(set(criterion_names)) or set(criterion_names) != _CRITERIA:
            raise CandidateEligibilityError(
                "criterion set must contain each required criterion once"
            )
        evidence_names = [row["evidence_name"] for row in criteria]
        if len(evidence_names) != len(set(evidence_names)):
            raise CandidateEligibilityError("criterion evidence names must be unique")
        if set(evidence_bytes) != set(evidence_names):
            raise CandidateEligibilityError(
                "evidence set must exactly match criterion evidence names"
            )
        criterion_rows: list[dict[str, Any]] = []
        for row in sorted(criteria, key=lambda item: item["criterion"]):
            content = evidence_bytes[row["evidence_name"]]
            if not isinstance(content, bytes):
                raise CandidateEligibilityError(
                    "criterion evidence must be supplied as exact bytes"
                )
            criterion_rows.append(
                {
                    "criterion": row["criterion"],
                    "status": row["status"],
                    "evidence": {
                        "name": row["evidence_name"],
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                    },
                    "rationale": row["rationale"],
                }
            )
    except CandidateEligibilityError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CandidateEligibilityError(
            "eligibility assessment is incomplete or malformed"
        ) from exc

    ordered_cases = sorted(source_cases, key=lambda row: row["case_id"])
    core: dict[str, Any] = {
        "schema": _SCHEMA,
        "candidate": expected_candidate,
        "closure_receipt": {
            "closure_receipt_id": closure.payload["closure_receipt_id"],
            "sha256": closure.sha256,
        },
        "assessor": assessor,
        "candidate_kind": assessment["candidate_kind"],
        "source_cases": ordered_cases,
        "distinct_independence_groups": len(
            {row["independence_group"] for row in ordered_cases}
        ),
        "criteria": criterion_rows,
        "assessed_at": assessed_at,
        "claims": {
            "byte_closure_verified": True,
            "eligibility_protocol_complete": True,
            "assessor_label_distinct_from_author": True,
            "source_independence_externally_verified": False,
            "semantic_review_completed": False,
            "fresh_session_validated": False,
            "private_evaluation_completed": False,
            "publication_authorized": False,
            "installation_authorized": False,
            "activation_authorized": False,
        },
        "limitations": list(_LIMITATIONS),
    }
    core["blockers"] = _expected_blockers(core)
    core["outcome"] = _expected_outcome(core["blockers"])
    core["candidate_eligibility_attestation_id"] = _attestation_id(core)
    return CandidateEligibilityAttestation.from_payload(core)
