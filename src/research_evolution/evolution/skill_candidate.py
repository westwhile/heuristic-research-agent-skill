"""Draft one byte-closed candidate Skill bundle without performing I/O.

The single public interface consumes an eligible P7B1 attestation plus exact
candidate payload and criterion-evidence bytes.  It returns an immutable Core
record.  Drafting is structural only: no Skill is installed, loaded, reviewed,
promoted, published, or activated.
"""

from __future__ import annotations

import hashlib
import heapq
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

from .candidate_eligibility import (
    CandidateEligibilityAttestation,
    CandidateEligibilityError,
)

_SCHEMA = "skill-candidate-bundle/v1"
_ENTRYPOINT = "SKILL.md"
_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
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
_CONTRACT_KEYS = frozenset(
    {
        "drafter",
        "skill_name",
        "description",
        "positive_triggers",
        "exclusions",
        "payload_members",
        "rollback_plan",
        "retirement_plan",
    }
)
_MEMBER_KEYS = frozenset({"name", "role", "media_type", "depends_on"})
_ROLE_BY_ROOT = {
    "agents": "agent_metadata",
    "assets": "asset",
    "references": "reference",
    "scripts": "script",
}
_TEXT_MEDIA_TYPES = frozenset(
    {
        "application/json",
        "application/yaml",
        "text/markdown",
        "text/plain",
        "text/x-python",
        "text/yaml",
    }
)
_FORBIDDEN_AUXILIARY = frozenset(
    {"CHANGELOG.md", "INSTALLATION_GUIDE.md", "QUICK_REFERENCE.md", "README.md"}
)
_LIMITATIONS = (
    "Payload and eligibility evidence byte closure is structural, not semantic review.",
    "Skill frontmatter and layout checks do not prove runtime discovery or behavior.",
    "Criterion evidence content and source independence remain protocol assertions.",
    "Only UTF-8 text payload and eligibility-evidence members are accepted in this P7B2 contract.",
    "No fresh-session/private evaluation, promotion, publication, installation, "
    "activation, or runtime loading is authorized.",
)


class SkillCandidateBundleError(ValueError):
    """A candidate Skill bundle could not be drafted safely."""


def _load_eligibility(
    source: CandidateEligibilityAttestation
    | Record
    | Mapping[str, Any]
    | str
    | bytes
    | bytearray,
) -> CandidateEligibilityAttestation:
    if isinstance(source, CandidateEligibilityAttestation):
        return CandidateEligibilityAttestation.from_payload(source.payload)
    try:
        if isinstance(source, Record):
            return CandidateEligibilityAttestation(source)
        if isinstance(source, Mapping):
            return CandidateEligibilityAttestation.from_payload(source)
        return CandidateEligibilityAttestation(load_record(source))
    except (CandidateEligibilityError, CoreError, TypeError, ValueError) as exc:
        raise SkillCandidateBundleError(
            f"invalid candidate eligibility attestation: {exc}"
        ) from exc


def _expected_role(name: str) -> str:
    try:
        normalized = validate_safe_relative_path(name)
    except (UnsafePathError, TypeError, ValueError) as exc:
        raise SkillCandidateBundleError(f"unsafe payload member path: {exc}") from exc
    if normalized == _ENTRYPOINT:
        return "skill_instructions"
    if normalized in _FORBIDDEN_AUXILIARY:
        raise SkillCandidateBundleError(
            f"auxiliary file {normalized!r} is not part of a candidate Skill payload"
        )
    root = normalized.split("/", 1)[0]
    if root not in _ROLE_BY_ROOT or "/" not in normalized:
        raise SkillCandidateBundleError(
            f"payload member {normalized!r} is outside the supported Skill layout"
        )
    leaf = normalized.rsplit("/", 1)[-1]
    if leaf in _FORBIDDEN_AUXILIARY:
        raise SkillCandidateBundleError(
            f"auxiliary file {normalized!r} is not part of a candidate Skill payload"
        )
    return _ROLE_BY_ROOT[root]


def _topological_order(members: Mapping[str, Mapping[str, Any]]) -> list[str]:
    indegree = {name: len(row["depends_on"]) for name, row in members.items()}
    children: dict[str, list[str]] = {name: [] for name in members}
    for name, row in members.items():
        dependencies = row["depends_on"]
        if len(dependencies) != len(set(dependencies)):
            raise SkillCandidateBundleError(f"member {name!r} repeats a dependency")
        if name in dependencies:
            raise SkillCandidateBundleError(f"member {name!r} depends on itself")
        missing = set(dependencies) - set(members)
        if missing:
            raise SkillCandidateBundleError(
                f"member {name!r} has unknown dependencies: {sorted(missing)!r}"
            )
        for dependency in dependencies:
            children[dependency].append(name)
    ready = [name for name, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        name = heapq.heappop(ready)
        ordered.append(name)
        for child in sorted(children[name]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    if len(ordered) != len(members):
        raise SkillCandidateBundleError("payload member dependency graph contains a cycle")
    return ordered


def _frontmatter_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value


def _validate_skill_md(content: str, *, name: str, description: str) -> None:
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise SkillCandidateBundleError("SKILL.md must start with YAML frontmatter")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise SkillCandidateBundleError("SKILL.md frontmatter is not closed") from exc
    frontmatter: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip() or ":" not in line:
            raise SkillCandidateBundleError(
                "SKILL.md frontmatter must use one-line key/value fields"
            )
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if key in frontmatter:
            raise SkillCandidateBundleError(
                f"SKILL.md frontmatter repeats field {key!r}"
            )
        frontmatter[key] = _frontmatter_value(raw_value)
    if set(frontmatter) != {"name", "description"}:
        raise SkillCandidateBundleError(
            "SKILL.md frontmatter must contain exactly name and description"
        )
    if frontmatter["name"] != name or frontmatter["description"] != description:
        raise SkillCandidateBundleError(
            "SKILL.md frontmatter must exactly match the declared Skill contract"
        )
    if not "\n".join(lines[closing + 1 :]).strip():
        raise SkillCandidateBundleError("SKILL.md body must not be empty")
    if len(lines[closing + 1 :]) > 500:
        raise SkillCandidateBundleError("SKILL.md body exceeds the 500-line limit")


def _closure_root(payload: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "candidate": payload["candidate"],
            "closure_receipt": payload["closure_receipt"],
            "eligibility_attestation": payload["eligibility_attestation"],
            "source_cases": payload["source_cases"],
            "skill": payload["skill"],
            "trigger_contract": payload["trigger_contract"],
            "payload_members": payload["payload_members"],
            "eligibility_evidence_members": payload[
                "eligibility_evidence_members"
            ],
            "topological_order": payload["closure"]["topological_order"],
            "lifecycle": payload["lifecycle"],
        }
    )


def _bundle_id(payload: Mapping[str, Any]) -> str:
    bound = {key: value for key, value in payload.items() if key != "skill_candidate_bundle_id"}
    return "skill-candidate-" + canonical_sha256(bound)[:16]


@dataclass(frozen=True)
class SkillCandidateBundle:
    """Immutable P7B2 candidate payload and evidence closure record."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _SCHEMA:
            raise SkillCandidateBundleError(
                f"expected {_SCHEMA}, got {self._record.schema_id!r}"
            )
        payload = self._record.data
        restricted = scan_value_for_restricted(payload, "skill_candidate_bundle")
        if restricted:
            raise SkillCandidateBundleError(
                "restricted content refused: " + "; ".join(restricted)
            )
        if payload["skill_candidate_bundle_id"] != _bundle_id(payload):
            raise SkillCandidateBundleError("bundle id does not bind its payload")
        payload_rows = payload["payload_members"]
        names = [row["name"] for row in payload_rows]
        if len(names) != len(set(names)) or _ENTRYPOINT not in names:
            raise SkillCandidateBundleError(
                "payload members must be unique and include SKILL.md"
            )
        members = {row["name"]: row for row in payload_rows}
        for name, row in members.items():
            if row["role"] != _expected_role(name):
                raise SkillCandidateBundleError(
                    f"payload member {name!r} has the wrong role"
                )
        expected_order = _topological_order(members)
        if payload["closure"]["topological_order"] != expected_order:
            raise SkillCandidateBundleError(
                "topological_order is not the deterministic dependency order"
            )
        evidence_rows = payload["eligibility_evidence_members"]
        evidence_names = [row["name"] for row in evidence_rows]
        criteria = [row["criterion"] for row in evidence_rows]
        if (
            len(evidence_names) != len(set(evidence_names))
            or set(criteria) != _CRITERIA
            or len(criteria) != len(set(criteria))
            or set(evidence_names) & set(names)
        ):
            raise SkillCandidateBundleError(
                "eligibility evidence must contain each criterion once and stay outside payload"
            )
        if payload["closure"]["closure_root_sha256"] != _closure_root(payload):
            raise SkillCandidateBundleError(
                "closure_root_sha256 does not bind payload and evidence members"
            )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SkillCandidateBundle:
        try:
            return cls(load_record(canonical_bytes(dict(payload))))
        except SkillCandidateBundleError:
            raise
        except (CoreError, TypeError, ValueError) as exc:
            raise SkillCandidateBundleError(f"invalid {_SCHEMA}: {exc}") from exc

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def sha256(self) -> str:
        return self._record.sha256


def draft_skill_candidate_bundle(
    eligibility_attestation: CandidateEligibilityAttestation
    | Record
    | Mapping[str, Any]
    | str
    | bytes
    | bytearray,
    skill_contract: Mapping[str, Any],
    payload_bytes: Mapping[str, bytes],
    eligibility_evidence_bytes: Mapping[str, bytes],
    *,
    drafted_at: str,
) -> SkillCandidateBundle:
    """Return one structurally drafted, byte-closed candidate or fail closed."""

    eligibility = _load_eligibility(eligibility_attestation)
    eligibility_payload = eligibility.payload
    if eligibility_payload["outcome"] != "eligible_for_payload_drafting":
        raise SkillCandidateBundleError(
            "candidate eligibility outcome does not permit payload drafting"
        )
    if eligibility_payload["blockers"]:
        raise SkillCandidateBundleError(
            "eligible payload drafting cannot carry eligibility blockers"
        )
    if set(skill_contract) != _CONTRACT_KEYS:
        raise SkillCandidateBundleError(
            "skill contract must contain exactly the required P7B2 fields"
        )
    restricted = scan_value_for_restricted(skill_contract, "skill_contract")
    if restricted:
        raise SkillCandidateBundleError(
            "restricted content refused: " + "; ".join(restricted)
        )

    try:
        drafter = skill_contract["drafter"]
        skill_name = skill_contract["skill_name"]
        description = skill_contract["description"]
        positive_triggers = list(skill_contract["positive_triggers"])
        exclusions = list(skill_contract["exclusions"])
        rollback_plan = skill_contract["rollback_plan"]
        retirement_plan = skill_contract["retirement_plan"]
        declared_rows = [dict(row) for row in skill_contract["payload_members"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise SkillCandidateBundleError("skill contract is malformed") from exc
    if (
        not isinstance(skill_name, str)
        or not _SKILL_NAME.fullmatch(skill_name)
        or len(skill_name) > 64
    ):
        raise SkillCandidateBundleError(
            "skill_name must use lowercase hyphen-case and be at most 64 characters"
        )
    if not isinstance(description, str) or not description.strip():
        raise SkillCandidateBundleError("description must be non-empty")
    for label, values in (
        ("positive_triggers", positive_triggers),
        ("exclusions", exclusions),
    ):
        if not values or not all(isinstance(value, str) and value.strip() for value in values):
            raise SkillCandidateBundleError(f"{label} must contain non-empty strings")
        if len(values) != len(set(values)):
            raise SkillCandidateBundleError(f"{label} must not contain duplicates")
    if set(positive_triggers) & set(exclusions):
        raise SkillCandidateBundleError(
            "positive triggers and exclusions must not overlap"
        )

    declared: dict[str, dict[str, Any]] = {}
    for row in declared_rows:
        if set(row) != _MEMBER_KEYS:
            raise SkillCandidateBundleError(
                "payload member declarations must use exactly name, role, "
                "media_type, and depends_on"
            )
        name = row["name"]
        if not isinstance(name, str) or name in declared:
            raise SkillCandidateBundleError("payload member names must be unique strings")
        expected_role = _expected_role(name)
        if row["role"] != expected_role:
            raise SkillCandidateBundleError(
                f"payload member {name!r} must use role {expected_role!r}"
            )
        if row["media_type"] not in _TEXT_MEDIA_TYPES:
            raise SkillCandidateBundleError(
                f"payload member {name!r} must use a supported UTF-8 text media type"
            )
        if not isinstance(row["depends_on"], list) or not all(
            isinstance(item, str) for item in row["depends_on"]
        ):
            raise SkillCandidateBundleError(
                f"payload member {name!r} dependencies must be a list of paths"
            )
        declared[name] = row
    if set(payload_bytes) != set(declared):
        raise SkillCandidateBundleError(
            "payload byte set must exactly match payload member declarations"
        )

    payload_rows: list[dict[str, Any]] = []
    decoded: dict[str, str] = {}
    for name in sorted(declared):
        content = payload_bytes[name]
        if not isinstance(content, bytes):
            raise SkillCandidateBundleError(
                "payload members must be supplied as exact bytes"
            )
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise SkillCandidateBundleError(
                f"payload member {name!r} is not strict UTF-8 text"
            ) from exc
        findings = scan_for_restricted(text, f"payload.{name}")
        if findings:
            raise SkillCandidateBundleError(
                "restricted content refused: " + "; ".join(findings)
            )
        decoded[name] = text
        row = declared[name]
        payload_rows.append(
            {
                "name": name,
                "role": row["role"],
                "media_type": row["media_type"],
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "depends_on": list(row["depends_on"]),
            }
        )
    if _ENTRYPOINT not in decoded:
        raise SkillCandidateBundleError("payload must contain SKILL.md")
    _validate_skill_md(decoded[_ENTRYPOINT], name=skill_name, description=description)
    member_map = {row["name"]: row for row in payload_rows}
    order = _topological_order(member_map)

    expected_evidence = {
        row["evidence"]["name"]: row for row in eligibility_payload["criteria"]
    }
    if set(eligibility_evidence_bytes) != set(expected_evidence):
        raise SkillCandidateBundleError(
            "eligibility evidence byte set must exactly match the attestation"
        )
    evidence_rows: list[dict[str, Any]] = []
    for name, row in sorted(expected_evidence.items()):
        content = eligibility_evidence_bytes[name]
        if not isinstance(content, bytes):
            raise SkillCandidateBundleError(
                "eligibility evidence must be supplied as exact bytes"
            )
        try:
            evidence_text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise SkillCandidateBundleError(
                f"eligibility evidence {name!r} is not strict UTF-8 text"
            ) from exc
        findings = scan_for_restricted(
            evidence_text, f"eligibility_evidence.{name}"
        )
        if findings:
            raise SkillCandidateBundleError(
                "restricted content refused: " + "; ".join(findings)
            )
        descriptor = row["evidence"]
        if (
            hashlib.sha256(content).hexdigest() != descriptor["sha256"]
            or len(content) != descriptor["size_bytes"]
        ):
            raise SkillCandidateBundleError(
                f"eligibility evidence {name!r} hash or size mismatch"
            )
        evidence_rows.append(
            {
                "name": name,
                "criterion": row["criterion"],
                "sha256": descriptor["sha256"],
                "size_bytes": descriptor["size_bytes"],
            }
        )

    core: dict[str, Any] = {
        "schema": _SCHEMA,
        "status": "drafted_candidate",
        "candidate": eligibility_payload["candidate"],
        "closure_receipt": eligibility_payload["closure_receipt"],
        "eligibility_attestation": {
            "candidate_eligibility_attestation_id": eligibility_payload[
                "candidate_eligibility_attestation_id"
            ],
            "sha256": eligibility.sha256,
        },
        "source_cases": eligibility_payload["source_cases"],
        "drafter": drafter,
        "skill": {
            "name": skill_name,
            "description": description,
            "entrypoint": _ENTRYPOINT,
        },
        "trigger_contract": {
            "positive_triggers": positive_triggers,
            "exclusions": exclusions,
        },
        "payload_members": payload_rows,
        "eligibility_evidence_members": evidence_rows,
        "lifecycle": {
            "rollback_plan": rollback_plan,
            "retirement_plan": retirement_plan,
        },
        "closure": {
            "topological_order": order,
            "closure_root_sha256": "0" * 64,
            "receipt_last": True,
            "payload_byte_closed": True,
            "eligibility_evidence_byte_closed": True,
        },
        "claims": {
            "semantic_review_completed": False,
            "fresh_session_validated": False,
            "private_evaluation_completed": False,
            "promotion_authorized": False,
            "publication_authorized": False,
            "installation_authorized": False,
            "activation_authorized": False,
            "runtime_loaded": False,
        },
        "drafted_at": drafted_at,
        "limitations": list(_LIMITATIONS),
    }
    core["closure"]["closure_root_sha256"] = _closure_root(core)
    core["skill_candidate_bundle_id"] = _bundle_id(core)
    return SkillCandidateBundle.from_payload(core)
