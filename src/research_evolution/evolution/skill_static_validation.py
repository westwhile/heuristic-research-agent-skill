"""Fail-closed static validation for an immutable Candidate Skill bundle.

The module is deliberately pure and in-process.  It validates exact P7B2
payload bytes, a narrow ``agents/openai.yaml`` profile, trigger examples,
registry collisions, and a descriptor-only payload diff.  It never writes a
Skill directory, invokes a runtime, installs a Skill, or performs semantic
review.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
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

_SCHEMA = "skill-static-validation-receipt/v1"
_METADATA_PATH = "agents/openai.yaml"
_VALIDATOR_TOOL = "in-process-skill-static-validator"
_VALIDATOR_VERSION = "1.0.0"
_CONTRACT_KEYS = frozenset(
    {
        "validator",
        "policy_id",
        "registry_skills",
        "router_examples",
        "baseline_payload_members",
    }
)
_REGISTRY_KEYS = frozenset({"name", "positive_triggers"})
_ROUTER_KEYS = frozenset({"prompt", "expected"})
_BASELINE_KEYS = frozenset({"name", "sha256", "size_bytes"})
_CHECKS = (
    "bundle_integrity",
    "payload_integrity",
    "restricted_content",
    "platform_metadata",
    "trigger_contract",
    "registry_collision",
    "router_examples",
    "payload_diff",
)
_FALSE_CLAIMS = (
    "semantic_review_completed",
    "fresh_session_validated",
    "private_evaluation_completed",
    "publication_authorized",
    "installation_authorized",
    "activation_authorized",
    "runtime_loaded",
)
_LIMITATIONS = (
    "Static validation does not establish semantic correctness or reviewer independence.",
    "Router examples are checked against declared strings, not executed by an Agent.",
    "Registry collision checks use an exact normalized snapshot and are not semantic search.",
    "No Skill is materialized, loaded, installed, activated, published, or promoted.",
)
_QUOTED_FIELD = re.compile(r'^  ([a-z_]+): ("(?:[^"\\]|\\.)*")$')


class SkillStaticValidationError(ValueError):
    """A static-validation input or immutable receipt is unsafe."""


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
        raise SkillStaticValidationError(
            f"invalid skill-candidate-bundle/v1: {exc}"
        ) from exc


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _safe_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillStaticValidationError(f"{label} must be a non-empty string")
    return value


def _safe_member_name(value: Any, label: str) -> str:
    name = _safe_name(value, label)
    try:
        return validate_safe_relative_path(name)
    except (UnsafePathError, TypeError, ValueError) as exc:
        raise SkillStaticValidationError(f"{label} is unsafe: {exc}") from exc


def _load_contract(source: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(source, Mapping) or set(source) != _CONTRACT_KEYS:
        raise SkillStaticValidationError(
            "validation contract must contain exactly the required P7B3 fields"
        )
    contract = dict(source)
    restricted = scan_value_for_restricted(contract, "static_validation_contract")
    if restricted:
        raise SkillStaticValidationError(
            "restricted content refused: " + "; ".join(restricted)
        )
    _safe_name(contract["validator"], "validator")
    _safe_name(contract["policy_id"], "policy_id")

    registry: list[dict[str, Any]] = []
    seen_registry: set[str] = set()
    if not isinstance(contract["registry_skills"], list):
        raise SkillStaticValidationError("registry_skills must be a list")
    for raw in contract["registry_skills"]:
        if not isinstance(raw, Mapping) or set(raw) != _REGISTRY_KEYS:
            raise SkillStaticValidationError(
                "registry skill rows must contain exactly name and positive_triggers"
            )
        row = dict(raw)
        name = _safe_name(row["name"], "registry skill name")
        normalized_name = _normalized(name)
        if normalized_name in seen_registry:
            raise SkillStaticValidationError("registry skill names must be unique")
        seen_registry.add(normalized_name)
        triggers = row["positive_triggers"]
        if not isinstance(triggers, list) or not triggers or not all(
            isinstance(item, str) and item.strip() for item in triggers
        ):
            raise SkillStaticValidationError(
                "registry positive_triggers must contain non-empty strings"
            )
        if len({_normalized(item) for item in triggers}) != len(triggers):
            raise SkillStaticValidationError(
                "registry positive_triggers must be unique per skill"
            )
        registry.append({"name": name, "positive_triggers": list(triggers)})

    examples: list[dict[str, str]] = []
    seen_prompts: set[str] = set()
    if not isinstance(contract["router_examples"], list):
        raise SkillStaticValidationError("router_examples must be a list")
    for raw in contract["router_examples"]:
        if not isinstance(raw, Mapping) or set(raw) != _ROUTER_KEYS:
            raise SkillStaticValidationError(
                "router example rows must contain exactly prompt and expected"
            )
        prompt = _safe_name(raw["prompt"], "router prompt")
        expected = raw["expected"]
        if expected not in {"select_candidate", "reject_candidate"}:
            raise SkillStaticValidationError("router example expected value is invalid")
        normalized_prompt = _normalized(prompt)
        if normalized_prompt in seen_prompts:
            raise SkillStaticValidationError("router prompts must be unique")
        seen_prompts.add(normalized_prompt)
        examples.append({"prompt": prompt, "expected": expected})

    baseline: list[dict[str, Any]] = []
    seen_baseline: set[str] = set()
    if not isinstance(contract["baseline_payload_members"], list):
        raise SkillStaticValidationError("baseline_payload_members must be a list")
    for raw in contract["baseline_payload_members"]:
        if not isinstance(raw, Mapping) or set(raw) != _BASELINE_KEYS:
            raise SkillStaticValidationError(
                "baseline member rows must contain exactly name, sha256, and size_bytes"
            )
        row = dict(raw)
        name = _safe_member_name(row["name"], "baseline member name")
        sha256 = row["sha256"]
        size_bytes = row["size_bytes"]
        if (
            not isinstance(sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
            or isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
        ):
            raise SkillStaticValidationError("baseline member descriptor is invalid")
        if name in seen_baseline:
            raise SkillStaticValidationError("baseline member names must be unique")
        seen_baseline.add(name)
        baseline.append({"name": name, "sha256": sha256, "size_bytes": size_bytes})

    contract["registry_skills"] = sorted(registry, key=lambda row: row["name"])
    contract["router_examples"] = sorted(examples, key=lambda row: row["prompt"])
    contract["baseline_payload_members"] = sorted(
        baseline, key=lambda row: row["name"]
    )
    return contract


def _parse_platform_metadata(content: str, skill_name: str) -> tuple[bool, str | None]:
    lines = content.splitlines()
    if len(lines) != 6 or lines[0] != "interface:" or lines[4] != "policy:":
        return False, "platform_metadata_layout_invalid"
    values: dict[str, str] = {}
    for line in lines[1:4]:
        match = _QUOTED_FIELD.fullmatch(line)
        if match is None:
            return False, "platform_metadata_strings_must_be_quoted"
        key, quoted = match.groups()
        if key in values:
            return False, "platform_metadata_field_duplicate"
        try:
            value = json.loads(quoted)
        except json.JSONDecodeError:
            return False, "platform_metadata_string_invalid"
        if not isinstance(value, str) or not value.strip():
            return False, "platform_metadata_string_empty"
        values[key] = value
    if set(values) != {"display_name", "short_description", "default_prompt"}:
        return False, "platform_metadata_interface_invalid"
    if not 25 <= len(values["short_description"]) <= 64:
        return False, "platform_metadata_short_description_invalid"
    if f"${skill_name}" not in values["default_prompt"]:
        return False, "platform_metadata_default_prompt_missing_skill"
    if lines[5] != "  allow_implicit_invocation: false":
        return False, "implicit_invocation_not_authorized"
    return True, None


def _receipt_id(payload: Mapping[str, Any]) -> str:
    bound = {
        key: value
        for key, value in payload.items()
        if key != "skill_static_validation_receipt_id"
    }
    return "skill-static-validation-" + canonical_sha256(bound)[:16]


@dataclass(frozen=True)
class SkillStaticValidationReceipt:
    """Immutable result of one P7B3 static-validation execution."""

    _record: Record

    def __post_init__(self) -> None:
        if self._record.schema_id != _SCHEMA:
            raise SkillStaticValidationError(
                f"expected {_SCHEMA}, got {self._record.schema_id!r}"
            )
        payload = self._record.data
        if payload["skill_static_validation_receipt_id"] != _receipt_id(payload):
            raise SkillStaticValidationError("receipt id does not bind its payload")
        checks = payload["checks"]
        names = [row["check"] for row in checks]
        if names != list(_CHECKS):
            raise SkillStaticValidationError(
                "checks must contain the deterministic P7B3 check sequence"
            )
        failed = [row for row in checks if row["result"] == "fail"]
        expected_outcome = "static_fail" if failed else "static_pass"
        if payload["outcome"] != expected_outcome:
            raise SkillStaticValidationError("outcome does not match check results")
        if bool(payload["blockers"]) != bool(failed):
            raise SkillStaticValidationError("blockers do not match failed checks")
        claims = payload["claims"]
        if claims["static_validation_passed"] != (not failed):
            raise SkillStaticValidationError(
                "static_validation_passed does not match outcome"
            )
        if any(claims[name] for name in _FALSE_CLAIMS):
            raise SkillStaticValidationError(
                "static validation cannot authorize later lifecycle claims"
            )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SkillStaticValidationReceipt:
        try:
            return cls(load_record(canonical_bytes(dict(payload))))
        except SkillStaticValidationError:
            raise
        except (CoreError, TypeError, ValueError) as exc:
            raise SkillStaticValidationError(f"invalid {_SCHEMA}: {exc}") from exc

    @property
    def payload(self) -> dict[str, Any]:
        return self._record.data

    @property
    def sha256(self) -> str:
        return self._record.sha256


def validate_skill_candidate(
    candidate_bundle: SkillCandidateBundle
    | Record
    | Mapping[str, Any]
    | str
    | bytes
    | bytearray,
    payload_bytes: Mapping[str, bytes],
    validation_contract: Mapping[str, Any],
    *,
    validated_at: str,
) -> SkillStaticValidationReceipt:
    """Validate one exact Candidate Skill without materializing or running it."""

    bundle = _load_bundle(candidate_bundle)
    bundle_payload = bundle.payload
    contract = _load_contract(validation_contract)
    blockers: list[dict[str, str]] = []
    failed_checks: set[str] = set()

    def fail(check: str, code: str, subject: str) -> None:
        failed_checks.add(check)
        blockers.append({"code": code, "subject": subject})

    declared = {row["name"]: row for row in bundle_payload["payload_members"]}
    supplied_names = set(payload_bytes) if isinstance(payload_bytes, Mapping) else set()
    payload_verified = supplied_names == set(declared)
    if not payload_verified:
        fail("payload_integrity", "payload_set_mismatch", "candidate_payload")

    decoded: dict[str, str] = {}
    restricted_ok = True
    if isinstance(payload_bytes, Mapping):
        for name in sorted(set(declared) & supplied_names):
            content = payload_bytes[name]
            descriptor = declared[name]
            if not isinstance(content, bytes):
                payload_verified = False
                fail("payload_integrity", "payload_member_not_exact_bytes", name)
                continue
            if (
                hashlib.sha256(content).hexdigest() != descriptor["sha256"]
                or len(content) != descriptor["size_bytes"]
            ):
                payload_verified = False
                fail("payload_integrity", "payload_hash_or_size_mismatch", name)
                continue
            try:
                text = content.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                payload_verified = False
                fail("payload_integrity", "payload_not_strict_utf8", name)
                continue
            decoded[name] = text
            if scan_for_restricted(text, f"candidate_payload.{name}"):
                restricted_ok = False
                fail("restricted_content", "restricted_content_detected", name)
    if not payload_verified and restricted_ok:
        restricted_ok = False
        fail(
            "restricted_content",
            "restricted_scan_incomplete",
            "candidate_payload",
        )

    metadata_present = _METADATA_PATH in declared
    metadata_descriptor: dict[str, Any] = {
        "required_path": _METADATA_PATH,
        "present": metadata_present,
    }
    metadata_ok = False
    if not metadata_present:
        fail("platform_metadata", "platform_metadata_missing", _METADATA_PATH)
    elif _METADATA_PATH not in decoded:
        fail("platform_metadata", "platform_metadata_unavailable", _METADATA_PATH)
    else:
        descriptor = declared[_METADATA_PATH]
        metadata_descriptor.update(
            {
                "sha256": descriptor["sha256"],
                "size_bytes": descriptor["size_bytes"],
            }
        )
        metadata_ok, code = _parse_platform_metadata(
            decoded[_METADATA_PATH], bundle_payload["skill"]["name"]
        )
        if not metadata_ok:
            fail("platform_metadata", code or "platform_metadata_invalid", _METADATA_PATH)

    description = _normalized(bundle_payload["skill"]["description"])
    positive = {
        _normalized(item) for item in bundle_payload["trigger_contract"]["positive_triggers"]
    }
    exclusions = {
        _normalized(item) for item in bundle_payload["trigger_contract"]["exclusions"]
    }
    trigger_ok = True
    if not all(item in description for item in positive):
        trigger_ok = False
        fail(
            "trigger_contract",
            "description_missing_positive_trigger",
            "skill.description",
        )
    if not all(item in description for item in exclusions):
        trigger_ok = False
        fail(
            "trigger_contract",
            "description_missing_exclusion",
            "skill.description",
        )

    candidate_name = _normalized(bundle_payload["skill"]["name"])
    collision_free = True
    for row in contract["registry_skills"]:
        if _normalized(row["name"]) == candidate_name:
            collision_free = False
            fail("registry_collision", "skill_name_collision", row["name"])
        overlap = positive & {_normalized(item) for item in row["positive_triggers"]}
        for trigger in sorted(overlap):
            collision_free = False
            fail("registry_collision", "positive_trigger_collision", trigger)

    examples = contract["router_examples"]
    expected_kinds = {row["expected"] for row in examples}
    router_ok = expected_kinds == {"select_candidate", "reject_candidate"}
    if not router_ok:
        fail("router_examples", "router_examples_incomplete", "router_examples")
    for row in examples:
        normalized_prompt = _normalized(row["prompt"])
        expected_set = positive if row["expected"] == "select_candidate" else exclusions
        if normalized_prompt not in expected_set:
            router_ok = False
            fail(
                "router_examples",
                "router_example_not_declared",
                hashlib.sha256(row["prompt"].encode("utf-8")).hexdigest(),
            )

    candidate_rows = {
        row["name"]: {
            "name": row["name"],
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
        }
        for row in bundle_payload["payload_members"]
    }
    baseline_rows = {
        row["name"]: row for row in contract["baseline_payload_members"]
    }
    added = sorted(set(candidate_rows) - set(baseline_rows))
    removed = sorted(set(baseline_rows) - set(candidate_rows))
    modified = sorted(
        name
        for name in set(candidate_rows) & set(baseline_rows)
        if candidate_rows[name] != baseline_rows[name]
    )

    if not restricted_ok:
        failed_checks.add("restricted_content")
    check_results = [
        {
            "check": check,
            "result": "fail" if check in failed_checks else "pass",
        }
        for check in _CHECKS
    ]
    blockers = sorted(blockers, key=lambda row: (row["code"], row["subject"]))
    outcome = "static_fail" if blockers else "static_pass"
    policy_payload = {
        "policy_id": contract["policy_id"],
        "required_platform_metadata": _METADATA_PATH,
        "implicit_invocation_authorized": False,
        "normalization": "unicode-nfkc-casefold-whitespace",
        "validator_tool": _VALIDATOR_TOOL,
        "validator_version": _VALIDATOR_VERSION,
    }
    core: dict[str, Any] = {
        "schema": _SCHEMA,
        "candidate_bundle": {
            "skill_candidate_bundle_id": bundle_payload[
                "skill_candidate_bundle_id"
            ],
            "sha256": bundle.sha256,
        },
        "validated_at": validated_at,
        "validator": {
            "principal": contract["validator"],
            "tool": _VALIDATOR_TOOL,
            "version": _VALIDATOR_VERSION,
            "policy_id": contract["policy_id"],
            "policy_sha256": canonical_sha256(policy_payload),
        },
        "registry_snapshot": {
            "sha256": canonical_sha256(contract["registry_skills"]),
            "skills_count": len(contract["registry_skills"]),
        },
        "platform_metadata": metadata_descriptor,
        "router_examples": {
            "sha256": canonical_sha256(contract["router_examples"]),
            "total": len(examples),
            "select_candidate": sum(
                row["expected"] == "select_candidate" for row in examples
            ),
            "reject_candidate": sum(
                row["expected"] == "reject_candidate" for row in examples
            ),
        },
        "payload_diff": {
            "baseline_snapshot_sha256": canonical_sha256(
                contract["baseline_payload_members"]
            ),
            "added": added,
            "modified": modified,
            "removed": removed,
        },
        "checks": check_results,
        "blockers": blockers,
        "outcome": outcome,
        "claims": {
            "candidate_bundle_verified": True,
            "payload_bytes_verified": payload_verified,
            "restricted_content_checked": restricted_ok,
            "platform_metadata_validated": metadata_ok,
            "trigger_contract_statically_checked": trigger_ok,
            "trigger_collision_checked": collision_free,
            "router_examples_statically_checked": router_ok,
            "static_validation_completed": True,
            "static_validation_passed": outcome == "static_pass",
            **{name: False for name in _FALSE_CLAIMS},
        },
        "limitations": list(_LIMITATIONS),
    }
    core["skill_static_validation_receipt_id"] = _receipt_id(core)
    return SkillStaticValidationReceipt.from_payload(core)
