"""Public-safe R6A submission and review protocol for external DL trials."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from research_evolution.adapters.deep_learning.pytorch_portability import (
    DLPortabilityTrialReceipt,
)
from research_evolution.adapters.types import AdapterError, _load_seam_record
from research_evolution.core import Record, canonical_sha256

_SUBMISSION_SCHEMA = "dl-external-trial-submission/v1"
_REVIEW_SCHEMA = "dl-external-trial-cohort-review/v1"
_ATTESTATION_SCHEMA = "dl-external-trial-attestation/v1"
_REVIEW_PLAN_SCHEMA = "dl-external-trial-cohort-review-plan/v1"
_PROTOCOL_ID = "dl-external-trial-protocol/v1"
_LIMITATIONS = (
    "Participant and host independence are self-declared until coordinator review.",
    "Private identity and consent records remain outside the repository.",
    "Trial participation does not establish external adoption or production reliability.",
    "Only bounded synthetic engineering metadata from an R5 receipt is bound.",
)


class DLExternalTrialProtocolError(AdapterError):
    """An R6A external-trial protocol artifact failed closed."""


@dataclass(frozen=True)
class DLExternalTrialSubmission:
    """Immutable public-safe submission bound to one exact R5 receipt."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _SUBMISSION_SCHEMA:
            raise AdapterError(
                f"DLExternalTrialSubmission wraps {_SUBMISSION_SCHEMA} payloads, "
                f"got {self._record.schema_id!r}"
            )
        violations = _submission_semantic_violations(self._record.data)
        if violations:
            raise AdapterError(
                f"invalid {_SUBMISSION_SCHEMA} semantics: "
                f"{len(violations)} violation(s)",
                details=violations,
            )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DLExternalTrialSubmission":
        return cls(_load_seam_record(_SUBMISSION_SCHEMA, payload))

    @classmethod
    def from_json(
        cls, source: str | bytes | bytearray
    ) -> "DLExternalTrialSubmission":
        return cls(_load_seam_record(_SUBMISSION_SCHEMA, source))

    @property
    def sha256(self) -> str:
        return self._record.sha256

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data


@dataclass(frozen=True)
class DLExternalTrialCohortReview:
    """Immutable coordinator review that never substitutes for R5 comparison."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _REVIEW_SCHEMA:
            raise AdapterError(
                f"DLExternalTrialCohortReview wraps {_REVIEW_SCHEMA} payloads, "
                f"got {self._record.schema_id!r}"
            )
        violations = _review_semantic_violations(self._record.data)
        if violations:
            raise AdapterError(
                f"invalid {_REVIEW_SCHEMA} semantics: {len(violations)} violation(s)",
                details=violations,
            )

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any]
    ) -> "DLExternalTrialCohortReview":
        return cls(_load_seam_record(_REVIEW_SCHEMA, payload))

    @classmethod
    def from_json(
        cls, source: str | bytes | bytearray
    ) -> "DLExternalTrialCohortReview":
        return cls(_load_seam_record(_REVIEW_SCHEMA, source))

    @property
    def sha256(self) -> str:
        return self._record.sha256

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data


def build_external_trial_submission(
    receipt: DLPortabilityTrialReceipt,
    attestation_payload: dict[str, Any] | str | bytes | bytearray,
) -> DLExternalTrialSubmission:
    """Bind one completed R5 receipt to a pseudonymous self-attestation."""

    if not isinstance(receipt, DLPortabilityTrialReceipt):
        raise DLExternalTrialProtocolError(
            "receipt must be a DLPortabilityTrialReceipt"
        )
    attestation = _validate_attestation(attestation_payload)
    receipt_payload = receipt.payload
    core = {
        "schema": _SUBMISSION_SCHEMA,
        "submitted_at": attestation["submitted_at"],
        "evidence_scope": (
            "external_trial_submission_self_attestation_engineering_only"
        ),
        "status": "submitted_unreviewed",
        "protocol": {
            "protocol_id": _PROTOCOL_ID,
            "protocol_sha256": attestation["protocol_sha256"],
        },
        "source_receipt": {
            "receipt_id": receipt_payload["receipt_id"],
            "receipt_sha256": receipt.sha256,
            "trial_plan_sha256": receipt_payload["trial_plan_sha256"],
            "repository": receipt_payload["repository"],
            "environment_sha256": canonical_sha256(receipt_payload["execution"]),
        },
        "participant": {
            "public_participant_id": attestation["public_participant_id"],
            "private_identity_record_sha256": attestation[
                "private_identity_record_sha256"
            ],
            "private_consent_record_sha256": attestation[
                "private_consent_record_sha256"
            ],
        },
        "attestation": {
            "evidence_level": "self_declared",
            **attestation["declarations"],
        },
        "consent": attestation["consent"],
        "privacy": {
            "local_paths_included": False,
            "credentials_included": False,
            "personal_identifiers_included": False,
            "raw_private_records_included": False,
            "automatic_upload_performed": False,
        },
        "claims": {
            "independent_participant_verified": False,
            "independent_host_verified": False,
            "external_adoption_verified": False,
            "production_reliability_verified": False,
        },
        "limitations": list(_LIMITATIONS),
    }
    submission_id = f"dl-external-submission-{canonical_sha256(core)[:16]}"
    return DLExternalTrialSubmission.from_payload(
        {"submission_id": submission_id, **core}
    )


def review_external_trial_cohort(
    submissions: list[DLExternalTrialSubmission],
    review_payload: dict[str, Any] | str | bytes | bytearray,
) -> DLExternalTrialCohortReview:
    """Review pseudonymous governance evidence before separate R5 comparison."""

    if (
        not isinstance(submissions, list)
        or len(submissions) < 2
        or any(not isinstance(item, DLExternalTrialSubmission) for item in submissions)
    ):
        raise DLExternalTrialProtocolError(
            "at least two DLExternalTrialSubmission values are required"
        )
    _reject_duplicate_submission_identity(submissions)
    first = submissions[0].payload
    protocol = first["protocol"]
    repository = first["source_receipt"]["repository"]
    trial_plan_sha256 = first["source_receipt"]["trial_plan_sha256"]
    for submission in submissions[1:]:
        payload = submission.payload
        if payload["protocol"] != protocol:
            raise DLExternalTrialProtocolError(
                "all submissions must bind the same external-trial protocol"
            )
        if (
            payload["source_receipt"]["repository"] != repository
            or payload["source_receipt"]["trial_plan_sha256"]
            != trial_plan_sha256
        ):
            raise DLExternalTrialProtocolError(
                "all submissions must bind the same repository archive and trial plan"
            )

    plan = _validate_review_plan(review_payload, submissions, protocol)
    submission_by_sha = {item.sha256: item for item in submissions}
    reviewed_rows: list[dict[str, Any]] = []
    for record in plan["records"]:
        submission = submission_by_sha[record["submission_sha256"]]
        payload = submission.payload
        participant = payload["participant"]
        if (
            record["public_participant_id"]
            != participant["public_participant_id"]
            or record["private_identity_record_sha256"]
            != participant["private_identity_record_sha256"]
            or record["private_consent_record_sha256"]
            != participant["private_consent_record_sha256"]
        ):
            raise DLExternalTrialProtocolError(
                "coordinator record does not bind the submission participant hashes"
            )
        review_values = (
            record["receipt_binding_review"],
            record["participant_independence_review"],
            record["host_independence_review"],
            record["consent_review"],
        )
        if record["disposition"] == "accepted" and "rejected" in review_values:
            raise DLExternalTrialProtocolError(
                "an accepted submission cannot contain a rejected review decision"
            )
        reviewed_rows.append(
            {
                "submission_id": payload["submission_id"],
                "submission_sha256": submission.sha256,
                "receipt_sha256": payload["source_receipt"]["receipt_sha256"],
                "environment_sha256": payload["source_receipt"][
                    "environment_sha256"
                ],
                **record,
            }
        )
    reviewed_rows.sort(key=lambda row: row["submission_sha256"])
    accepted = [row for row in reviewed_rows if row["disposition"] == "accepted"]
    environments = {row["environment_sha256"] for row in accepted}
    participants = {row["public_participant_id"] for row in accepted}
    participant_level = _review_level(
        accepted,
        ("receipt_binding_review", "participant_independence_review", "consent_review"),
    )
    host_level = _review_level(
        accepted,
        ("receipt_binding_review", "host_independence_review", "consent_review"),
    )
    distinct_host_records = len(
        {row["private_host_record_sha256"] for row in accepted}
    ) == len(accepted)
    if accepted and not distinct_host_records:
        host_level = "self_declared"
    eligible = (
        len(accepted) >= plan["minimum_independent_participants"]
        and len(environments) >= plan["minimum_distinct_environments"]
        and participant_level == "coordinator_verified"
        and host_level == "coordinator_verified"
        and distinct_host_records
    )
    status = (
        "no_accepted_submissions"
        if not accepted
        else "eligible_for_separate_technical_comparison"
        if eligible
        else "insufficient_verified_independence"
    )
    core = {
        "schema": _REVIEW_SCHEMA,
        "reviewed_at": plan["reviewed_at"],
        "evidence_scope": (
            "external_trial_coordinator_record_review_engineering_only"
        ),
        "protocol": protocol,
        "trial_plan_sha256": trial_plan_sha256,
        "repository": repository,
        "policy": {
            "minimum_independent_participants": plan[
                "minimum_independent_participants"
            ],
            "minimum_distinct_environments": plan[
                "minimum_distinct_environments"
            ],
        },
        "submissions": reviewed_rows,
        "summary": {
            "submitted": len(reviewed_rows),
            "accepted_submissions": len(accepted),
            "rejected_submissions": len(reviewed_rows) - len(accepted),
            "distinct_participants": len(participants),
            "distinct_environments": len(environments),
            "status": status,
        },
        "claims": {
            "independent_participants_evidence": participant_level,
            "independent_hosts_evidence": host_level,
            "external_adoption_verified": False,
            "production_reliability_verified": False,
        },
        "next_gate": {
            "r5_technical_comparison_required": True,
            "technical_comparison_completed": False,
            "external_adoption_evaluation_completed": False,
        },
        "privacy": {
            "local_paths_included": False,
            "credentials_included": False,
            "personal_identifiers_included": False,
            "raw_private_records_included": False,
            "automatic_upload_performed": False,
        },
        "limitations": [
            "Coordinator-verified means private hash-bound records were reviewed, "
            "not independently audited.",
            "A separate R5 report must compare the exact source receipts.",
            "Trial participation does not establish external adoption or "
            "production reliability.",
            "No raw identity, consent, host record, credential, or local path is included.",
        ],
    }
    review_id = f"dl-external-review-{canonical_sha256(core)[:16]}"
    return DLExternalTrialCohortReview.from_payload(
        {"review_id": review_id, **core}
    )


def _reject_duplicate_submission_identity(
    submissions: list[DLExternalTrialSubmission],
) -> None:
    projections = {
        "submission hash": [item.sha256 for item in submissions],
        "submission id": [item.payload["submission_id"] for item in submissions],
        "receipt hash": [
            item.payload["source_receipt"]["receipt_sha256"] for item in submissions
        ],
        "public participant id": [
            item.payload["participant"]["public_participant_id"]
            for item in submissions
        ],
        "private identity record": [
            item.payload["participant"]["private_identity_record_sha256"]
            for item in submissions
        ],
        "private consent record": [
            item.payload["participant"]["private_consent_record_sha256"]
            for item in submissions
        ],
    }
    duplicate_names = [
        name for name, values in projections.items() if len(set(values)) != len(values)
    ]
    if duplicate_names:
        raise DLExternalTrialProtocolError(
            "duplicate external-trial identity or receipt is forbidden: "
            + ", ".join(duplicate_names)
        )


def _validate_review_plan(
    source: Any,
    submissions: list[DLExternalTrialSubmission],
    protocol: dict[str, Any],
) -> dict[str, Any]:
    try:
        source = _load_seam_record(_REVIEW_PLAN_SCHEMA, source).data
    except AdapterError as exc:
        raise DLExternalTrialProtocolError(
            "cohort review plan schema validation failed", details=exc.details
        ) from exc
    required = {
        "schema",
        "reviewed_at",
        "protocol_sha256",
        "minimum_independent_participants",
        "minimum_distinct_environments",
        "records",
    }
    if not isinstance(source, dict) or set(source) != required:
        raise DLExternalTrialProtocolError("cohort review plan fields are invalid")
    if source["schema"] != _REVIEW_PLAN_SCHEMA:
        raise DLExternalTrialProtocolError("cohort review plan schema is invalid")
    if source["protocol_sha256"] != protocol["protocol_sha256"]:
        raise DLExternalTrialProtocolError(
            "cohort review plan does not bind the submission protocol"
        )
    if not isinstance(source["reviewed_at"], str):
        raise DLExternalTrialProtocolError("reviewed_at must be caller supplied")
    for name in (
        "minimum_independent_participants",
        "minimum_distinct_environments",
    ):
        value = source[name]
        if isinstance(value, bool) or not isinstance(value, int) or not 2 <= value <= 20:
            raise DLExternalTrialProtocolError(f"{name} must be an integer from 2 to 20")
    records = source["records"]
    if not isinstance(records, list) or len(records) != len(submissions):
        raise DLExternalTrialProtocolError(
            "coordinator records must cover every submission exactly once"
        )
    required_record = {
        "submission_sha256",
        "public_participant_id",
        "private_identity_record_sha256",
        "private_consent_record_sha256",
        "private_host_record_sha256",
        "private_host_record_hash_nonce_hardened",
        "disposition",
        "receipt_binding_review",
        "participant_independence_review",
        "host_independence_review",
        "consent_review",
    }
    decisions = {"verified", "unverified", "rejected"}
    for record in records:
        if not isinstance(record, dict) or set(record) != required_record:
            raise DLExternalTrialProtocolError("coordinator record fields are invalid")
        for name in (
            "submission_sha256",
            "private_identity_record_sha256",
            "private_consent_record_sha256",
            "private_host_record_sha256",
        ):
            if not _is_sha256(record[name]):
                raise DLExternalTrialProtocolError(
                    f"coordinator record {name} must be lowercase SHA-256"
                )
        if record["disposition"] not in {"accepted", "rejected"}:
            raise DLExternalTrialProtocolError(
                "coordinator record disposition is invalid"
            )
        if record["private_host_record_hash_nonce_hardened"] is not True:
            raise DLExternalTrialProtocolError(
                "private host record hash must be nonce hardened"
            )
        for name in (
            "receipt_binding_review",
            "participant_independence_review",
            "host_independence_review",
            "consent_review",
        ):
            if record[name] not in decisions:
                raise DLExternalTrialProtocolError(
                    f"coordinator record {name} is invalid"
                )
    expected = {item.sha256 for item in submissions}
    actual = [record["submission_sha256"] for record in records]
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise DLExternalTrialProtocolError(
            "coordinator records must bind each exact submission once"
        )
    violations = _public_safety_violations(source)
    if violations:
        raise DLExternalTrialProtocolError(
            "cohort review plan must remain public-safe", details=violations
        )
    return source


def _review_level(
    accepted: list[dict[str, Any]], fields: tuple[str, ...]
) -> str:
    if not accepted:
        return "not_verified"
    if all(row[field] == "verified" for row in accepted for field in fields):
        return "coordinator_verified"
    return "self_declared"


def _review_semantic_violations(payload: dict[str, Any]) -> tuple[str, ...]:
    violations = list(_public_safety_violations(payload))
    core = {key: value for key, value in payload.items() if key != "review_id"}
    expected_id = f"dl-external-review-{canonical_sha256(core)[:16]}"
    if payload["review_id"] != expected_id:
        violations.append(
            "external-trial-review-id: id must bind the canonical cohort review"
        )
    rows = payload["submissions"]
    accepted = [row for row in rows if row["disposition"] == "accepted"]
    unique_projections = (
        "submission_id",
        "submission_sha256",
        "receipt_sha256",
        "public_participant_id",
        "private_identity_record_sha256",
        "private_consent_record_sha256",
    )
    if any(
        len({row[field] for row in rows}) != len(rows)
        for field in unique_projections
    ):
        violations.append(
            "external-trial-review-duplicate: submission and participant "
            "bindings must be unique"
        )
    summary = payload["summary"]
    expected_counts = {
        "submitted": len(rows),
        "accepted_submissions": len(accepted),
        "rejected_submissions": len(rows) - len(accepted),
        "distinct_participants": len(
            {row["public_participant_id"] for row in accepted}
        ),
        "distinct_environments": len(
            {row["environment_sha256"] for row in accepted}
        ),
    }
    if any(summary[name] != value for name, value in expected_counts.items()):
        violations.append(
            "external-trial-review-counts: summary must match reviewed submissions"
        )
    participant_level = _review_level(
        accepted,
        ("receipt_binding_review", "participant_independence_review", "consent_review"),
    )
    host_level = _review_level(
        accepted,
        ("receipt_binding_review", "host_independence_review", "consent_review"),
    )
    distinct_host_records = len(
        {row["private_host_record_sha256"] for row in accepted}
    ) == len(accepted)
    if accepted and not distinct_host_records:
        host_level = "self_declared"
    if (
        payload["claims"]["independent_participants_evidence"]
        != participant_level
        or payload["claims"]["independent_hosts_evidence"] != host_level
    ):
        violations.append(
            "external-trial-review-level: claims must match coordinator decisions"
        )
    policy = payload["policy"]
    if any(
        isinstance(policy[name], bool)
        or not isinstance(policy[name], int)
        or not 2 <= policy[name] <= 20
        for name in (
            "minimum_independent_participants",
            "minimum_distinct_environments",
        )
    ):
        violations.append(
            "external-trial-review-policy: cohort minimums must be integers "
            "from 2 to 20"
        )
    eligible = (
        len(accepted) >= policy["minimum_independent_participants"]
        and expected_counts["distinct_environments"]
        >= policy["minimum_distinct_environments"]
        and participant_level == "coordinator_verified"
        and host_level == "coordinator_verified"
        and distinct_host_records
    )
    expected_status = (
        "no_accepted_submissions"
        if not accepted
        else "eligible_for_separate_technical_comparison"
        if eligible
        else "insufficient_verified_independence"
    )
    if summary["status"] != expected_status:
        violations.append(
            "external-trial-review-status: status must match evidence and policy"
        )
    return tuple(sorted(set(violations)))


def _validate_attestation(source: Any) -> dict[str, Any]:
    try:
        source = _load_seam_record(_ATTESTATION_SCHEMA, source).data
    except AdapterError as exc:
        raise DLExternalTrialProtocolError(
            "attestation schema validation failed", details=exc.details
        ) from exc
    required = {
        "schema",
        "protocol_sha256",
        "submitted_at",
        "public_participant_id",
        "private_identity_record_sha256",
        "private_consent_record_sha256",
        "declarations",
        "consent",
    }
    if not isinstance(source, dict) or set(source) != required:
        raise DLExternalTrialProtocolError("attestation fields are invalid")
    if source["schema"] != _ATTESTATION_SCHEMA:
        raise DLExternalTrialProtocolError("attestation schema is invalid")
    for name in (
        "protocol_sha256",
        "private_identity_record_sha256",
        "private_consent_record_sha256",
    ):
        if not _is_sha256(source[name]):
            raise DLExternalTrialProtocolError(f"{name} must be lowercase SHA-256")
    if source["private_identity_record_sha256"] == source[
        "private_consent_record_sha256"
    ]:
        raise DLExternalTrialProtocolError(
            "identity and consent records must have distinct hashes"
        )
    if not isinstance(source["public_participant_id"], str) or not re.fullmatch(
        r"participant-[0-9a-f]{16}", source["public_participant_id"]
    ):
        raise DLExternalTrialProtocolError(
            "public_participant_id must be a pseudonymous participant identifier"
        )
    expected_declarations = {
        "participant_is_not_maintainer": True,
        "participant_controlled_execution": True,
        "maintainer_operated_execution": False,
        "receipt_generated_by_participant": True,
        "private_record_hashes_nonce_hardened": True,
    }
    if source["declarations"] != expected_declarations:
        raise DLExternalTrialProtocolError(
            "all participant independence declarations are required"
        )
    expected_consent = {
        "protocol_version_accepted": True,
        "public_pseudonym_accepted": True,
        "public_technical_metadata_accepted": True,
    }
    if source["consent"] != expected_consent:
        raise DLExternalTrialProtocolError(
            "explicit protocol and publication consent is required"
        )
    if not isinstance(source["submitted_at"], str):
        raise DLExternalTrialProtocolError("submitted_at must be caller supplied")
    if _public_safety_violations(source):
        raise DLExternalTrialProtocolError(
            "attestation must not contain paths, credentials, or personal identifiers",
            details=_public_safety_violations(source),
        )
    return source


def _submission_semantic_violations(payload: dict[str, Any]) -> tuple[str, ...]:
    violations = list(_public_safety_violations(payload))
    core = {key: value for key, value in payload.items() if key != "submission_id"}
    expected_id = f"dl-external-submission-{canonical_sha256(core)[:16]}"
    if payload["submission_id"] != expected_id:
        violations.append(
            "external-trial-submission-id: id must bind the canonical submission"
        )
    participant = payload["participant"]
    if participant["private_identity_record_sha256"] == participant[
        "private_consent_record_sha256"
    ]:
        violations.append(
            "external-trial-private-records: identity and consent hashes must differ"
        )
    return tuple(violations)


def _public_safety_violations(value: Any) -> tuple[str, ...]:
    violations: set[str] = set()
    for item in _string_values(value):
        if re.search(r"[A-Za-z]:\\", item) or any(
            marker in item for marker in ("/home/", "/Users/", "file://")
        ):
            violations.add("external-trial-public-safe: local path detected")
        if (
            re.search(r"gh[pousr]_[A-Za-z0-9]{20,}", item)
            or re.search(r"sk-[A-Za-z0-9_-]{20,}", item)
            or re.search(r"AKIA[0-9A-Z]{16}", item)
            or re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", item)
        ):
            violations.add("external-trial-public-safe: credential shape detected")
        if re.search(
            r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+"
            r"\.[A-Za-z]{2,}(?![A-Za-z0-9.-])",
            item,
        ):
            violations.add("external-trial-public-safe: personal identifier detected")
    return tuple(sorted(violations))


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    return []


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


__all__ = [
    "DLExternalTrialCohortReview",
    "DLExternalTrialProtocolError",
    "DLExternalTrialSubmission",
    "build_external_trial_submission",
    "review_external_trial_cohort",
]
