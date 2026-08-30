"""Propose one byte-closed Skill Candidate from public failure cases.

The single public interface validates at least two independently labelled
``research-case-package/v2`` failure cases and one shared
``research-pattern/v1`` record before it calls an injected generator exactly
once.  A successful generation is mapped into the existing P7A/P7B manifest,
closure, eligibility, and Skill Candidate records.  The module creates no new
Core family and never installs, loads, reviews, promotes, publishes, or
activates a Skill.
"""

from __future__ import annotations

import hashlib
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from research_evolution.core import (
    CoreError,
    Record,
    canonical_bytes,
    canonical_sha256,
    load_record,
    load_strict_json,
)
from research_evolution.core._restricted import scan_value_for_restricted
from research_evolution.evaluation import Envelope
from research_evolution.evaluation.runner import ReplayResult

from ._process_containment import process_facts_are_valid
from .agent_forward_trial import (
    AgentForwardExecutionRequest,
    CodexCliAgentAdapter,
)
from .candidate_eligibility import (
    CandidateEligibilityAttestation,
    CandidateEligibilityError,
    assess_candidate_eligibility,
)
from .incubator import (
    ArtifactClosureError,
    ArtifactClosureReceipt,
    CandidateManifestError,
    close_candidate_bundle,
)
from .skill_candidate import (
    SkillCandidateBundle,
    SkillCandidateBundleError,
    draft_skill_candidate_bundle,
)

_ADAPTER_VERSION = "0.1.0"
_REAL_EVIDENCE_CLASS = "real_codex_cli"
_SIMULATED_EVIDENCE_CLASS = "simulated_skill_candidate_contract"
_EVIDENCE_CLASSES = frozenset({_REAL_EVIDENCE_CLASS, _SIMULATED_EVIDENCE_CLASS})
_DOMAINS = frozenset({"math", "quant"})
_PATTERN_STATUSES = frozenset(
    {"candidate_pattern", "validated_pattern", "active_pattern"}
)
_LINEAGE_FIELDS = (
    "independence_group",
    "origin_run_id",
    "dataset_lineage_id",
    "task_template_id",
    "semantic_duplicate_group",
)
_POLICY_FIELDS = frozenset(
    {
        "reasoning_effort",
        "sandbox",
        "approval_policy",
        "ephemeral",
        "web_search",
        "trace_max_bytes",
    }
)
_PRINCIPAL_FIELDS = frozenset({"author", "reviewer", "assessor", "drafter"})
_ENVELOPE_FIELDS = frozenset(
    {
        "model",
        "reasoning",
        "tools_sha256",
        "budget_sha256",
        "data_sha256",
        "evaluator_sha256",
    }
)
_OUTPUT_FIELDS = frozenset(
    {
        "description",
        "positive_triggers",
        "exclusions",
        "skill_md",
        "agent_metadata_yaml",
        "criterion_evidence",
        "criterion_rationales",
        "rollback_plan",
        "retirement_plan",
    }
)
_CRITERIA = (
    "clear_exclusions",
    "clear_positive_triggers",
    "explicit_failure_pause_boundaries",
    "measurable_gain_plan",
    "portable_resources",
    "stable_input_contract",
    "stable_output_contract",
)
_LIMITATIONS = (
    "Generator output and criterion evidence remain a proposal, not independent review.",
    "Protocol lineage labels are hash-bound but are not externally verified identities.",
    "A Candidate proposal does not prove runtime discovery, behavioral improvement, "
    "or research validity.",
    "No hidden evaluation, promotion, publication, installation, activation, or "
    "runtime loading is authorized.",
)


class SkillCandidateProposalError(ValueError):
    """The proposal plan, generator, or candidate violated a hard gate."""


@dataclass(frozen=True)
class SkillCandidateGenerationRequest:
    """One request crossing the internal Candidate-generator seam."""

    proposal_id: str
    workspace: Path
    prompt: str
    output_schema_path: Path
    final_output_path: Path
    context_sha256: str
    axes_sha256: str


@dataclass(frozen=True)
class SkillCandidateGenerationObservation:
    """Sanitized generator facts; raw trace and session id remain transient."""

    replay: ReplayResult
    launcher_process_started: bool
    agent_session_started: bool
    agent_turn_completed: bool
    session_id: str | None
    transcript_sha256: str | None
    stderr_sha256: str | None
    usage: dict[str, int]
    started_at: str
    completed_at: str
    execution_status: str
    process_cleanup_status: str
    process_tree_cleanup_verified: bool


class SkillCandidateGenerator(Protocol):
    """Internal port implemented by deterministic and Codex CLI Adapters."""

    @property
    def evidence_class(self) -> str: ...

    @property
    def identity(self) -> Mapping[str, str]: ...

    @property
    def execution_policy(self) -> Mapping[str, Any]: ...

    def generate(
        self, request: SkillCandidateGenerationRequest, envelope: Envelope
    ) -> SkillCandidateGenerationObservation: ...


@dataclass(frozen=True)
class SkillCandidateProposalPlan:
    """Immutable pre-registration for one Candidate generation attempt."""

    proposal_id: str
    domain: str
    source_cases: tuple[Mapping[str, Any], ...]
    source_pattern: Mapping[str, Any]
    baseline_bytes: bytes
    test_plan: Mapping[str, Any]
    evaluation_envelope: Mapping[str, Any]
    prompt: str
    reasoning_effort: str
    execution_envelope: Envelope
    candidate_id: str
    skill_name: str
    principals: Mapping[str, str]
    authoritative_head: Mapping[str, str]
    created_at: str


@dataclass(frozen=True)
class SkillCandidateProposalOutcome:
    """Non-publishable aggregate over existing immutable Candidate families."""

    status: str
    blockers: tuple[str, ...]
    manifest_payload: dict[str, Any] | None
    closure_receipt: ArtifactClosureReceipt | None
    eligibility_attestation: CandidateEligibilityAttestation | None
    candidate_bundle: SkillCandidateBundle | None
    member_bytes: dict[str, bytes] | None
    payload_bytes: dict[str, bytes] | None
    eligibility_evidence_bytes: dict[str, bytes] | None
    axes_sha256: str
    adapter_identity: dict[str, str]
    session_id_sha256: str | None
    transcript_sha256: str | None
    stderr_sha256: str | None
    usage: dict[str, int]
    workspace_cleaned: bool
    claims: dict[str, bool]
    limitations: tuple[str, ...] = _LIMITATIONS


class DeterministicSkillCandidateAdapter:
    """Exercise P7D1B without starting an external model."""

    def __init__(
        self,
        output: bytes,
        *,
        model: str,
        reasoning_effort: str,
        failure: tuple[str, str] | None = None,
        started_at: str = "2026-08-26T00:00:00Z",
        completed_at: str = "2026-08-26T00:00:01Z",
    ) -> None:
        if not isinstance(output, bytes):
            raise SkillCandidateProposalError("deterministic output must be exact bytes")
        if not model.strip() or not reasoning_effort.strip():
            raise SkillCandidateProposalError("deterministic Adapter identity is incomplete")
        self._output = output
        self._failure = failure
        self._identity = {
            "tool": "deterministic-skill-candidate",
            "version": _ADAPTER_VERSION,
            "model": model,
        }
        self._policy = {
            "reasoning_effort": reasoning_effort,
            "sandbox": "simulated-read-only",
            "approval_policy": "never",
            "ephemeral": True,
            "web_search": "disabled",
            "trace_max_bytes": 1 << 20,
        }
        self._started_at = started_at
        self._completed_at = completed_at
        self._requests: list[SkillCandidateGenerationRequest] = []

    @property
    def evidence_class(self) -> str:
        return _SIMULATED_EVIDENCE_CLASS

    @property
    def identity(self) -> Mapping[str, str]:
        return dict(self._identity)

    @property
    def execution_policy(self) -> Mapping[str, Any]:
        return dict(self._policy)

    @property
    def requests(self) -> tuple[SkillCandidateGenerationRequest, ...]:
        return tuple(self._requests)

    def generate(
        self, request: SkillCandidateGenerationRequest, envelope: Envelope
    ) -> SkillCandidateGenerationObservation:
        self._requests.append(request)
        if self._failure is not None:
            error_class, _private_detail = self._failure
            replay = ReplayResult(
                False,
                None,
                None,
                error_class,
                "deterministic Candidate Adapter failed",
                1,
            )
        elif len(self._output) > envelope.max_output_bytes:
            replay = ReplayResult(
                False,
                None,
                None,
                "output_limit",
                "deterministic Candidate output exceeded the frozen byte budget",
                1,
            )
        else:
            try:
                canonical = canonical_bytes(load_strict_json(self._output))
            except (CoreError, TypeError, ValueError):
                replay = ReplayResult(
                    False,
                    None,
                    None,
                    "parse_error",
                    "deterministic Candidate output was not strict JSON",
                    1,
                )
            else:
                replay = ReplayResult(
                    True,
                    canonical,
                    hashlib.sha256(canonical).hexdigest(),
                    None,
                    None,
                    1,
                )
        return SkillCandidateGenerationObservation(
            replay=replay,
            launcher_process_started=True,
            agent_session_started=False,
            agent_turn_completed=False,
            session_id=None,
            transcript_sha256=hashlib.sha256(self._output).hexdigest(),
            stderr_sha256=None,
            usage={},
            started_at=self._started_at,
            completed_at=self._completed_at,
            execution_status="not_applicable",
            process_cleanup_status="not_applicable",
            process_tree_cleanup_verified=True,
        )


class CodexCliSkillCandidateAdapter:
    """Adapt the existing least-privilege Codex CLI process to P7D1B."""

    def __init__(
        self,
        launcher: Path,
        *,
        powershell: Path,
        cli_version: str,
        model: str,
        reasoning_effort: str,
        trace_max_bytes: int = 4 << 20,
    ) -> None:
        self._inner = CodexCliAgentAdapter(
            launcher,
            powershell=powershell,
            cli_version=cli_version,
            model=model,
            reasoning_effort=reasoning_effort,
            trace_max_bytes=trace_max_bytes,
        )
        self._identity = {
            "tool": "codex-cli-skill-candidate",
            "version": cli_version,
            "model": model,
        }

    @property
    def evidence_class(self) -> str:
        return _REAL_EVIDENCE_CLASS

    @property
    def identity(self) -> Mapping[str, str]:
        return dict(self._identity)

    @property
    def execution_policy(self) -> Mapping[str, Any]:
        return dict(self._inner.execution_policy)

    def generate(
        self, request: SkillCandidateGenerationRequest, envelope: Envelope
    ) -> SkillCandidateGenerationObservation:
        started_at = _now()
        observed = self._inner.execute(
            AgentForwardExecutionRequest(
                trial_id=request.proposal_id,
                arm="candidate",
                workspace=request.workspace,
                prompt=request.prompt,
                output_schema_path=request.output_schema_path,
                final_output_path=request.final_output_path,
                skill_name="p7d1b-proposal-only",
                skill_md_sha256=hashlib.sha256(b"").hexdigest(),
                candidate_bundle_sha256=request.context_sha256,
                axes_sha256=request.axes_sha256,
            ),
            envelope,
        )
        return SkillCandidateGenerationObservation(
            replay=observed.replay,
            launcher_process_started=observed.launcher_process_started,
            agent_session_started=observed.agent_session_started,
            agent_turn_completed=observed.agent_turn_completed,
            session_id=observed.session_id,
            transcript_sha256=observed.transcript_sha256,
            stderr_sha256=observed.stderr_sha256,
            usage=observed.usage,
            started_at=started_at,
            completed_at=_now(),
            execution_status=observed.execution_status,
            process_cleanup_status=observed.process_cleanup_status,
            process_tree_cleanup_verified=observed.process_tree_cleanup_verified,
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _validated_record(
    source: Mapping[str, Any], schema: str, label: str
) -> Record:
    try:
        record = load_record(canonical_bytes(dict(source)))
    except (CoreError, TypeError, ValueError) as exc:
        raise SkillCandidateProposalError(f"invalid {label}: {exc}") from exc
    if record.schema_id != schema:
        raise SkillCandidateProposalError(
            f"{label} declares {record.schema_id!r}; expected {schema!r}"
        )
    if scan_value_for_restricted(record.data, label):
        raise SkillCandidateProposalError(f"{label} contains restricted content")
    return record


def _validate_generator(generator: SkillCandidateGenerator, reasoning: str) -> tuple[
    dict[str, str], dict[str, Any]
]:
    if generator.evidence_class not in _EVIDENCE_CLASSES:
        raise SkillCandidateProposalError("unsupported generator evidence class")
    identity = dict(generator.identity)
    if set(identity) not in ({"tool", "version"}, {"tool", "version", "model"}):
        raise SkillCandidateProposalError("generator identity fields are not exact")
    if any(not isinstance(value, str) or not value.strip() for value in identity.values()):
        raise SkillCandidateProposalError("generator identity is incomplete")
    policy = dict(generator.execution_policy)
    if set(policy) != _POLICY_FIELDS:
        raise SkillCandidateProposalError("generator policy fields are not exact")
    if policy["reasoning_effort"] != reasoning:
        raise SkillCandidateProposalError("generator reasoning differs from frozen plan")
    if generator.evidence_class == _REAL_EVIDENCE_CLASS:
        required = {
            "sandbox": "read-only",
            "approval_policy": "never",
            "ephemeral": True,
            "web_search": "disabled",
        }
        if any(policy[key] != value for key, value in required.items()):
            raise SkillCandidateProposalError("real Codex generator violates least privilege")
    trace_max = policy["trace_max_bytes"]
    if isinstance(trace_max, bool) or not isinstance(trace_max, int) or trace_max < 1024:
        raise SkillCandidateProposalError("generator trace budget is invalid")
    return identity, policy


def _validate_plan(
    plan: SkillCandidateProposalPlan, generator: SkillCandidateGenerator
) -> tuple[list[Record], Record, list[dict[str, str]], dict[str, str], dict[str, Any]]:
    if not isinstance(plan, SkillCandidateProposalPlan):
        raise SkillCandidateProposalError("plan must be SkillCandidateProposalPlan")
    if plan.domain not in _DOMAINS:
        raise SkillCandidateProposalError("domain must be math or quant")
    if len(plan.source_cases) < 2 or len(plan.source_cases) > 6:
        raise SkillCandidateProposalError("two to six source failure cases are required")
    if not isinstance(plan.baseline_bytes, bytes):
        raise SkillCandidateProposalError("baseline must be supplied as exact bytes")
    if plan.execution_envelope.seed is not None:
        raise SkillCandidateProposalError("Candidate generation must not fabricate a provider seed")
    if plan.execution_envelope.retry_attempts != 0:
        raise SkillCandidateProposalError("Candidate generation forbids retries")
    for label, value in (
        ("proposal_id", plan.proposal_id),
        ("prompt", plan.prompt),
        ("candidate_id", plan.candidate_id),
        ("skill_name", plan.skill_name),
        ("created_at", plan.created_at),
    ):
        if not isinstance(value, str) or not value.strip():
            raise SkillCandidateProposalError(f"{label} must be non-empty")
    restricted_inputs = {
        "prompt": plan.prompt,
        "test_plan": plan.test_plan,
        "evaluation_envelope": plan.evaluation_envelope,
        "principals": plan.principals,
        "authoritative_head": plan.authoritative_head,
    }
    if scan_value_for_restricted(restricted_inputs, "candidate_proposal_plan"):
        raise SkillCandidateProposalError("Candidate proposal plan contains restricted content")

    principals = dict(plan.principals)
    if set(principals) != _PRINCIPAL_FIELDS or any(
        not isinstance(value, str) or not value.strip() for value in principals.values()
    ):
        raise SkillCandidateProposalError("principal fields must be exact and non-empty")
    if len(set(principals.values())) != len(principals):
        raise SkillCandidateProposalError("proposal principal labels must be distinct")

    evaluation_envelope = dict(plan.evaluation_envelope)
    if set(evaluation_envelope) != _ENVELOPE_FIELDS:
        raise SkillCandidateProposalError("candidate evaluation envelope fields are not exact")
    for name in _ENVELOPE_FIELDS - {"model", "reasoning"}:
        if not _valid_sha256(evaluation_envelope[name]):
            raise SkillCandidateProposalError(f"candidate evaluation envelope {name} is invalid")
    if any(
        not isinstance(evaluation_envelope[name], str)
        or not evaluation_envelope[name].strip()
        for name in ("model", "reasoning")
    ):
        raise SkillCandidateProposalError("candidate evaluation model/reasoning is incomplete")

    authoritative = dict(plan.authoritative_head)
    if set(authoritative) != {"record_id", "sha256"} or not isinstance(
        authoritative["record_id"], str
    ) or not authoritative["record_id"].strip() or not _valid_sha256(
        authoritative["sha256"]
    ):
        raise SkillCandidateProposalError("authoritative head reference is invalid")

    cases = [
        _validated_record(source, "research-case-package/v2", "source case")
        for source in plan.source_cases
    ]
    case_ids = [record.data["case_id"] for record in cases]
    if len(case_ids) != len(set(case_ids)):
        raise SkillCandidateProposalError("source case identities must be unique")
    lineages: list[dict[str, str]] = []
    for record in cases:
        payload = record.data
        if (
            payload["privacy_review_status"] != "passed"
            or payload["eligibility"]["status"] != "eligible"
            or payload["export_mode"] != "benchmark_candidate"
            or not payload["observations"]
            or not payload["analyses"]
        ):
            raise SkillCandidateProposalError(
                "source cases must be privacy-passed eligible failure packages"
            )
        facets = payload["problem_signature"].get("facets")
        if not isinstance(facets, dict) or set(facets) != set(_LINEAGE_FIELDS):
            raise SkillCandidateProposalError("source case lineage fields are not exact")
        lineage = {name: facets[name] for name in _LINEAGE_FIELDS}
        if any(not isinstance(value, str) or not value.strip() for value in lineage.values()):
            raise SkillCandidateProposalError("source case lineage values are incomplete")
        lineages.append(lineage)
    for field in _LINEAGE_FIELDS:
        values = [lineage[field] for lineage in lineages]
        if len(values) != len(set(values)):
            raise SkillCandidateProposalError(f"source case {field} values must be distinct")

    pattern = _validated_record(
        plan.source_pattern, "research-pattern/v1", "source pattern"
    )
    if pattern.data["status"] not in _PATTERN_STATUSES:
        raise SkillCandidateProposalError("source Pattern is not reusable-candidate status")
    expected_cases = {
        record.data["case_id"]: record.sha256 for record in cases
    }
    actual_cases = {
        row["case_id"]: row["sha256"] for row in pattern.data["source_cases"]
    }
    if actual_cases != expected_cases or len(actual_cases) != len(
        pattern.data["source_cases"]
    ):
        raise SkillCandidateProposalError("source Pattern must exactly pin all failure cases")

    identity, policy = _validate_generator(generator, plan.reasoning_effort)
    return cases, pattern, lineages, identity, policy


def _output_schema() -> dict[str, Any]:
    criteria = list(_CRITERIA)
    criterion_properties = {name: {"type": "string", "minLength": 1} for name in criteria}
    return {
        "type": "object",
        "required": sorted(_OUTPUT_FIELDS),
        "properties": {
            "description": {"type": "string", "minLength": 1},
            "positive_triggers": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "exclusions": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "skill_md": {"type": "string", "minLength": 1},
            "agent_metadata_yaml": {"type": "string", "minLength": 1},
            "criterion_evidence": {
                "type": "object",
                "required": criteria,
                "properties": criterion_properties,
                "additionalProperties": False,
            },
            "criterion_rationales": {
                "type": "object",
                "required": criteria,
                "properties": criterion_properties,
                "additionalProperties": False,
            },
            "rollback_plan": {"type": "string", "minLength": 1},
            "retirement_plan": {"type": "string", "minLength": 1},
        },
        "additionalProperties": False,
    }


def _context_payload(
    plan: SkillCandidateProposalPlan, cases: list[Record], pattern: Record
) -> dict[str, Any]:
    return {
        "schema": "p7d1b-candidate-generation-context/v1",
        "proposal_id": plan.proposal_id,
        "domain": plan.domain,
        "candidate_id": plan.candidate_id,
        "skill_name": plan.skill_name,
        "source_cases": [
            record.data
            for record in sorted(cases, key=lambda item: item.data["case_id"])
        ],
        "source_pattern": pattern.data,
        "test_plan": dict(plan.test_plan),
        "evaluation_envelope": dict(plan.evaluation_envelope),
        "constraints": {
            "payload_files": ["SKILL.md", "agents/openai.yaml"],
            "candidate_only": True,
            "installation_authorized": False,
            "activation_authorized": False,
            "publication_authorized": False,
        },
    }


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return True
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _assert_plain_directory(path: Path) -> None:
    if not path.is_dir() or _is_reparse(path):
        raise SkillCandidateProposalError("temporary workspace contains a reparse point")


def _prepare_workspace(
    root: Path, context: Mapping[str, Any], output_schema: Mapping[str, Any]
) -> tuple[Path, Path, Path]:
    workspace = root / "candidate"
    workspace.mkdir()
    _assert_plain_directory(workspace)
    (workspace / "AGENTS.md").write_text(
        "# P7D1B isolated Candidate proposal\n\n"
        "Read only this workspace. Do not use network access, credentials, prior "
        "sessions, or files outside this workspace. Propose only the requested "
        "Candidate; do not install, activate, publish, or run it.\n",
        encoding="utf-8",
    )
    (workspace / "candidate-context.json").write_bytes(canonical_bytes(context))
    control = workspace / ".p7d1b"
    control.mkdir()
    _assert_plain_directory(control)
    schema_path = control / "output-schema.json"
    schema_path.write_bytes(canonical_bytes(output_schema))
    return workspace, schema_path, control / "final.json"


def _safe_cleanup(root: Path) -> bool:
    expected_parent = Path(tempfile.gettempdir()).resolve()
    try:
        resolved = root.resolve()
        if resolved.parent != expected_parent or not resolved.name.startswith(
            "p7d1b-skill-candidate-"
        ):
            return False
        shutil.rmtree(resolved)
        return not resolved.exists()
    except OSError:
        return False


def _normalize_observation(value: Any) -> SkillCandidateGenerationObservation:
    if not isinstance(value, SkillCandidateGenerationObservation):
        raise SkillCandidateProposalError("generator returned an invalid observation")
    if not isinstance(value.replay, ReplayResult):
        raise SkillCandidateProposalError("generator replay has the wrong type")
    if value.agent_session_started != (value.session_id is not None):
        raise SkillCandidateProposalError("session fact and session id disagree")
    if value.agent_turn_completed and not value.agent_session_started:
        raise SkillCandidateProposalError("turn completion requires a started session")
    if not process_facts_are_valid(
        value.execution_status,
        value.process_cleanup_status,
        value.process_tree_cleanup_verified,
    ):
        raise SkillCandidateProposalError("execution and process cleanup facts are inconsistent")
    for digest in (value.transcript_sha256, value.stderr_sha256):
        if digest is not None and not _valid_sha256(digest):
            raise SkillCandidateProposalError("generator emitted an invalid SHA-256")
    if any(
        not isinstance(key, str)
        or isinstance(number, bool)
        or not isinstance(number, int)
        or number < 0
        for key, number in value.usage.items()
    ):
        raise SkillCandidateProposalError("generator usage values are invalid")
    return value


def _parse_candidate_output(output: bytes) -> dict[str, Any]:
    try:
        value = load_strict_json(output)
    except (CoreError, TypeError, ValueError) as exc:
        raise SkillCandidateProposalError("Candidate output is not strict JSON") from exc
    if not isinstance(value, dict) or set(value) != _OUTPUT_FIELDS:
        raise SkillCandidateProposalError("Candidate output fields are not exact")
    if scan_value_for_restricted(value, "candidate_generator_output"):
        raise SkillCandidateProposalError("Candidate output contains restricted content")
    for name in (
        "description",
        "skill_md",
        "agent_metadata_yaml",
        "rollback_plan",
        "retirement_plan",
    ):
        if not isinstance(value[name], str) or not value[name].strip():
            raise SkillCandidateProposalError(f"Candidate output {name} is empty")
    for name in ("positive_triggers", "exclusions"):
        rows = value[name]
        if (
            not isinstance(rows, list)
            or not rows
            or not all(isinstance(row, str) and row.strip() for row in rows)
            or len(rows) != len(set(rows))
        ):
            raise SkillCandidateProposalError(f"Candidate output {name} is invalid")
    if set(value["positive_triggers"]) & set(value["exclusions"]):
        raise SkillCandidateProposalError("Candidate triggers and exclusions overlap")
    for name in ("criterion_evidence", "criterion_rationales"):
        rows = value[name]
        if not isinstance(rows, dict) or set(rows) != set(_CRITERIA) or any(
            not isinstance(row, str) or not row.strip() for row in rows.values()
        ):
            raise SkillCandidateProposalError(f"Candidate output {name} is invalid")
    return value


def _member_row(
    name: str, role: str, content: bytes, depends_on: list[str]
) -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "depends_on": depends_on,
    }


def _build_candidate(
    *,
    plan: SkillCandidateProposalPlan,
    cases: list[Record],
    pattern: Record,
    lineages: list[dict[str, str]],
    generated: dict[str, Any],
) -> tuple[
    dict[str, Any],
    ArtifactClosureReceipt,
    CandidateEligibilityAttestation,
    SkillCandidateBundle,
    dict[str, bytes],
    dict[str, bytes],
    dict[str, bytes],
]:
    ordered_cases = sorted(cases, key=lambda item: item.data["case_id"])
    case_refs = [
        {"case_id": record.data["case_id"], "sha256": record.sha256}
        for record in ordered_cases
    ]
    pattern_ref = {
        "pattern_id": pattern.data["pattern_id"],
        "sha256": pattern.sha256,
    }
    payload_bytes = {
        "SKILL.md": generated["skill_md"].encode("utf-8"),
        "agents/openai.yaml": generated["agent_metadata_yaml"].encode("utf-8"),
    }
    patch_bytes = canonical_bytes(
        {
            name: content.decode("utf-8", errors="strict")
            for name, content in sorted(payload_bytes.items())
        }
    )
    tests_bytes = canonical_bytes(dict(plan.test_plan))
    member_bytes: dict[str, bytes] = {
        "members/baseline.bin": plan.baseline_bytes,
        "members/candidate-payload.json": patch_bytes,
        "members/tests.json": tests_bytes,
        "sources/pattern.json": pattern.canonical_bytes,
    }
    for index, record in enumerate(ordered_cases, start=1):
        member_bytes[f"sources/case-{index:03d}.json"] = record.canonical_bytes
    eligibility_evidence_bytes = {
        f"evidence/{criterion}.txt": generated["criterion_evidence"][criterion].encode("utf-8")
        for criterion in _CRITERIA
    }
    member_bytes.update(eligibility_evidence_bytes)
    source_names = sorted(name for name in member_bytes if name.startswith("sources/"))
    members = [
        _member_row("members/baseline.bin", "baseline", plan.baseline_bytes, []),
        _member_row(
            "members/candidate-payload.json",
            "patch",
            patch_bytes,
            ["members/baseline.bin", *source_names],
        ),
        _member_row(
            "members/tests.json",
            "tests",
            tests_bytes,
            ["members/candidate-payload.json"],
        ),
    ]
    members.extend(
        _member_row(name, "source_snapshot", member_bytes[name], [])
        for name in source_names
    )
    members.extend(
        _member_row(
            name,
            "evidence",
            content,
            ["members/tests.json"],
        )
        for name, content in sorted(eligibility_evidence_bytes.items())
    )
    context_summary = (
        "Public failure cases and one reusable-candidate Pattern are hash-pinned; "
        "raw Agent outputs, traces, session identifiers, and local paths are excluded."
    )
    source_lifecycle = [
        {
            "source_id": row["case_id"],
            "sha256": row["sha256"],
            "status": "current",
            "rationale": "The public failure package is the exact frozen proposal source.",
        }
        for row in case_refs
    ]
    source_lifecycle.append(
        {
            "source_id": pattern_ref["pattern_id"],
            "sha256": pattern_ref["sha256"],
            "status": "current",
            "rationale": "The Pattern exactly pins every source failure package.",
        }
    )
    manifest: dict[str, Any] = {
        "schema": "candidate-manifest/v1",
        "candidate_id": plan.candidate_id,
        "status": "staged_candidate",
        "objective": generated["description"],
        "principals": {
            "author": plan.principals["author"],
            "reviewer": plan.principals["reviewer"],
        },
        "baseline_sha256": hashlib.sha256(plan.baseline_bytes).hexdigest(),
        "patch_sha256": hashlib.sha256(patch_bytes).hexdigest(),
        "source_cases": case_refs,
        "source_patterns": [pattern_ref],
        "evaluation_envelope": dict(plan.evaluation_envelope),
        "members": sorted(members, key=lambda row: row["name"]),
        "exclusions": [
            {
                "name": "raw/agent-output.json",
                "reason": (
                    "Raw baseline and generator outputs are not retained in the "
                    "Candidate closure."
                ),
            }
        ],
        "risks": [
            "The proposed Skill may fail static, semantic, forward, or hidden evaluation."
        ],
        "rollback": generated["rollback_plan"],
        "context": {
            "authoritative_head": dict(plan.authoritative_head),
            "unresolved_obligations": [
                "Independent semantic review and fresh-session evaluation remain open."
            ],
            "source_lifecycle": sorted(source_lifecycle, key=lambda row: row["source_id"]),
            "materials": [
                {
                    "name": "minimal-safe-summary",
                    "content_sha256": hashlib.sha256(context_summary.encode("utf-8")).hexdigest(),
                    "content": context_summary,
                    "retention": "minimal_safe",
                }
            ],
        },
        "claims": {
            "installation_authorized": False,
            "activation_authorized": False,
            "publication_authorized": False,
            "semantic_review_completed": False,
        },
        "created_at": plan.created_at,
    }
    closure = close_candidate_bundle(manifest, member_bytes, closed_at=plan.created_at)
    lineage_by_case = {
        record.data["case_id"]: lineage
        for record, lineage in zip(cases, lineages, strict=True)
    }
    assessment_cases = [
        {**row, **lineage_by_case[row["case_id"]]} for row in case_refs
    ]
    assessment = {
        "assessor": plan.principals["assessor"],
        "candidate_kind": "reusable_skill_proposal",
        "source_cases": assessment_cases,
        "criteria": [
            {
                "criterion": criterion,
                "status": "satisfied",
                "evidence_name": f"evidence/{criterion}.txt",
                "rationale": generated["criterion_rationales"][criterion],
            }
            for criterion in _CRITERIA
        ],
    }
    eligibility = assess_candidate_eligibility(
        manifest,
        closure,
        assessment,
        eligibility_evidence_bytes,
        assessed_at=plan.created_at,
    )
    contract = {
        "drafter": plan.principals["drafter"],
        "skill_name": plan.skill_name,
        "description": generated["description"],
        "positive_triggers": generated["positive_triggers"],
        "exclusions": generated["exclusions"],
        "payload_members": [
            {
                "name": "SKILL.md",
                "role": "skill_instructions",
                "media_type": "text/markdown",
                "depends_on": [],
            },
            {
                "name": "agents/openai.yaml",
                "role": "agent_metadata",
                "media_type": "text/yaml",
                "depends_on": ["SKILL.md"],
            },
        ],
        "rollback_plan": generated["rollback_plan"],
        "retirement_plan": generated["retirement_plan"],
    }
    bundle = draft_skill_candidate_bundle(
        eligibility,
        contract,
        payload_bytes,
        eligibility_evidence_bytes,
        drafted_at=plan.created_at,
    )
    return (
        manifest,
        closure,
        eligibility,
        bundle,
        member_bytes,
        payload_bytes,
        eligibility_evidence_bytes,
    )


def propose_skill_candidate(
    plan: SkillCandidateProposalPlan, generator: SkillCandidateGenerator
) -> SkillCandidateProposalOutcome:
    """Call one generator once and return one closed Candidate proposal or no Candidate."""

    cases, pattern, lineages, identity, policy = _validate_plan(plan, generator)
    output_schema = _output_schema()
    context = _context_payload(plan, cases, pattern)
    context_sha = canonical_sha256(context)
    axes_sha = canonical_sha256(
        {
            "proposal_id": plan.proposal_id,
            "domain": plan.domain,
            "candidate_id": plan.candidate_id,
            "skill_name": plan.skill_name,
            "source_cases": [
                {"case_id": record.data["case_id"], "sha256": record.sha256}
                for record in sorted(cases, key=lambda item: item.data["case_id"])
            ],
            "source_pattern": {
                "pattern_id": pattern.data["pattern_id"],
                "sha256": pattern.sha256,
            },
            "baseline_sha256": hashlib.sha256(plan.baseline_bytes).hexdigest(),
            "test_plan_sha256": canonical_sha256(plan.test_plan),
            "evaluation_envelope": dict(plan.evaluation_envelope),
            "prompt_sha256": hashlib.sha256(plan.prompt.encode("utf-8")).hexdigest(),
            "execution_envelope_sha256": plan.execution_envelope.canonical_sha256,
            "generator_policy": policy,
            "output_schema_sha256": canonical_sha256(output_schema),
            "authoritative_head": dict(plan.authoritative_head),
        }
    )
    temp_root = Path(tempfile.mkdtemp(prefix="p7d1b-skill-candidate-")).resolve()
    _assert_plain_directory(temp_root)
    try:
        workspace, schema_path, final_path = _prepare_workspace(
            temp_root, context, output_schema
        )
        request = SkillCandidateGenerationRequest(
            proposal_id=plan.proposal_id,
            workspace=workspace,
            prompt=plan.prompt,
            output_schema_path=schema_path,
            final_output_path=final_path,
            context_sha256=context_sha,
            axes_sha256=axes_sha,
        )
        try:
            observation = _normalize_observation(
                generator.generate(request, plan.execution_envelope)
            )
        except SkillCandidateProposalError:
            raise
        except Exception as exc:
            observation = SkillCandidateGenerationObservation(
                replay=ReplayResult(
                    False,
                    None,
                    None,
                    "runner_error",
                    f"generator raised {type(exc).__name__}; message suppressed",
                    1,
                ),
                launcher_process_started=False,
                agent_session_started=False,
                agent_turn_completed=False,
                session_id=None,
                transcript_sha256=None,
                stderr_sha256=None,
                usage={},
                started_at=plan.created_at,
                completed_at=plan.created_at,
                execution_status="executor_failed",
                process_cleanup_status="unverified",
                process_tree_cleanup_verified=False,
            )
    finally:
        workspace_cleaned = _safe_cleanup(temp_root)

    session_sha = (
        hashlib.sha256(observation.session_id.encode("utf-8")).hexdigest()
        if observation.session_id is not None
        else None
    )
    blockers: list[str] = []
    if not workspace_cleaned:
        blockers.append("workspace_cleanup_failed")
    if not observation.process_tree_cleanup_verified:
        blockers.append("process_tree_cleanup_failed")
    real_generator = generator.evidence_class == _REAL_EVIDENCE_CLASS
    if real_generator and not observation.agent_session_started:
        blockers.append("real_agent_session_missing")
    if real_generator and not observation.agent_turn_completed:
        blockers.append("real_agent_turn_incomplete")
    candidate_output = observation.replay.output_bytes
    if not observation.replay.ok or candidate_output is None:
        blockers.append(f"generation_{observation.replay.error_class or 'error'}")

    manifest = None
    closure = None
    eligibility = None
    bundle = None
    member_bytes = None
    payload_bytes = None
    evidence_bytes = None
    if blockers:
        status = "proposal_inconclusive"
    else:
        assert candidate_output is not None
        try:
            generated = _parse_candidate_output(candidate_output)
        except SkillCandidateProposalError as exc:
            status = "proposal_rejected"
            if "restricted content" in str(exc):
                blockers.append("restricted_candidate_output")
            else:
                blockers.append("candidate_contract_invalid")
        else:
            try:
                (
                    manifest,
                    closure,
                    eligibility,
                    bundle,
                    member_bytes,
                    payload_bytes,
                    evidence_bytes,
                ) = _build_candidate(
                    plan=plan,
                    cases=cases,
                    pattern=pattern,
                    lineages=lineages,
                    generated=generated,
                )
            except (
                ArtifactClosureError,
                CandidateEligibilityError,
                CandidateManifestError,
                SkillCandidateBundleError,
                CoreError,
                TypeError,
                ValueError,
            ):
                status = "proposal_rejected"
                blockers.append("candidate_contract_invalid")
            else:
                status = "proposal_ready"

    ready = status == "proposal_ready"
    claims = {
        "generator_called_once": True,
        "raw_trace_persisted": False,
        "workspace_cleanup_verified": workspace_cleaned,
        "process_tree_cleanup_verified": observation.process_tree_cleanup_verified,
        "real_agent_session_observed": real_generator and observation.agent_session_started,
        "real_agent_turn_completed": real_generator and observation.agent_turn_completed,
        "candidate_proposal_generated": ready,
        "byte_closure_verified": ready,
        "source_independence_externally_verified": False,
        "semantic_review_completed": False,
        "fresh_session_validated": False,
        "hidden_evaluation_completed": False,
        "promotion_authorized": False,
        "publication_authorized": False,
        "installation_authorized": False,
        "activation_authorized": False,
        "runtime_loaded": False,
    }
    return SkillCandidateProposalOutcome(
        status=status,
        blockers=tuple(blockers),
        manifest_payload=manifest,
        closure_receipt=closure,
        eligibility_attestation=eligibility,
        candidate_bundle=bundle,
        member_bytes=member_bytes,
        payload_bytes=payload_bytes,
        eligibility_evidence_bytes=evidence_bytes,
        axes_sha256=axes_sha,
        adapter_identity=identity,
        session_id_sha256=session_sha,
        transcript_sha256=observation.transcript_sha256,
        stderr_sha256=observation.stderr_sha256,
        usage=dict(observation.usage),
        workspace_cleaned=workspace_cleaned,
        claims=claims,
    )


__all__ = [
    "CodexCliSkillCandidateAdapter",
    "DeterministicSkillCandidateAdapter",
    "SkillCandidateGenerationObservation",
    "SkillCandidateGenerationRequest",
    "SkillCandidateGenerator",
    "SkillCandidateProposalError",
    "SkillCandidateProposalOutcome",
    "SkillCandidateProposalPlan",
    "propose_skill_candidate",
]
