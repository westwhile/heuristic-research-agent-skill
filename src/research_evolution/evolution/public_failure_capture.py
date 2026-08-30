"""Capture one public baseline Agent failure without retaining raw output.

The module freezes one public case, runs exactly one baseline execution through
an injected Adapter, reuses the existing evaluation attempt/result machinery,
and emits the existing research task/run/observation/analysis/case chain only
when a completed deterministic evaluation is a genuine failure.

P7D1A is a capture seam, not a Candidate, review, hidden-evaluation, promotion,
installation, activation, or publication seam.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from research_evolution.core import canonical_bytes, canonical_sha256, load_record
from research_evolution.core._restricted import (
    scan_for_restricted,
    scan_value_for_restricted,
)
from research_evolution.evaluation import Envelope, GateConfig, PipelineOutcome
from research_evolution.evaluation.pipeline import (
    _assemble_observation,
    _prepare_evaluation,
    interpreter_environment,
)
from research_evolution.evaluation.runner import ReplayResult

from ._process_containment import process_facts_are_valid
from .agent_forward_trial import (
    AgentForwardExecutionRequest,
    CodexCliAgentAdapter,
)

_ADAPTER_VERSION = "0.1.0"
_REAL_EVIDENCE_CLASS = "real_codex_cli"
_SIMULATED_EVIDENCE_CLASS = "simulated_public_failure_contract"
_EVIDENCE_CLASSES = frozenset({_REAL_EVIDENCE_CLASS, _SIMULATED_EVIDENCE_CLASS})
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
_DOMAINS = frozenset({"math", "quant"})
_LIMITATIONS = (
    "A captured public failure does not establish its root cause.",
    "Protocol lineage labels are not externally verified identities.",
    "A single baseline session is not replication or independent review.",
    "No Candidate, hidden evaluation, promotion, publication, installation, "
    "or activation is authorized.",
)


class PublicFailureCaptureError(ValueError):
    """The P7D1A plan, Adapter, or captured evidence violated a hard gate."""


@dataclass(frozen=True)
class PublicFailureExecutionRequest:
    """One baseline request crossing the internal executor seam."""

    capture_id: str
    workspace: Path
    prompt: str
    output_schema_path: Path
    final_output_path: Path
    axes_sha256: str
    public_case_sha256: str


@dataclass(frozen=True)
class PublicFailureExecutionObservation:
    """Sanitized process facts; raw trace, stderr, and session id stay transient."""

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


class PublicFailureExecutor(Protocol):
    """Internal port implemented by deterministic and Codex CLI Adapters."""

    @property
    def evidence_class(self) -> str: ...

    @property
    def identity(self) -> Mapping[str, str]: ...

    @property
    def execution_policy(self) -> Mapping[str, Any]: ...

    def execute(
        self, request: PublicFailureExecutionRequest, envelope: Envelope
    ) -> PublicFailureExecutionObservation: ...


@dataclass(frozen=True)
class PublicFailureCapturePlan:
    """Immutable pre-registration for one public baseline execution."""

    capture_id: str
    task: Mapping[str, Any]
    evaluation_case: Mapping[str, Any]
    suite: Mapping[str, Any]
    baseline: Mapping[str, str]
    public_case_input: bytes
    output_schema: Mapping[str, Any]
    prompt: str
    reasoning_effort: str
    envelope: Envelope
    scoring: Mapping[str, Any]
    gate_config: GateConfig
    case_id: str
    case_title: str
    signature_summary: str
    signature_sha256: str
    lineage: Mapping[str, str]
    source_project: str
    rights: str


@dataclass(frozen=True)
class PublicFailureCaptureOutcome:
    """Non-publishable aggregate over existing immutable Core families."""

    status: str
    blockers: tuple[str, ...]
    evaluation: PipelineOutcome
    task_payload: dict[str, Any]
    run_payload: dict[str, Any] | None
    observation_payload: dict[str, Any] | None
    analysis_payload: dict[str, Any] | None
    case_payload: dict[str, Any] | None
    axes_sha256: str
    adapter_identity: dict[str, str]
    session_id_sha256: str | None
    workspace_cleaned: bool
    claims: dict[str, bool]
    limitations: tuple[str, ...] = _LIMITATIONS


class DeterministicPublicFailureAdapter:
    """Exercise the P7D1A interface without starting an external model."""

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
            raise PublicFailureCaptureError("deterministic output must be exact bytes")
        if not model.strip() or not reasoning_effort.strip():
            raise PublicFailureCaptureError("deterministic Adapter identity is incomplete")
        self._output = output
        self._failure = failure
        self._identity = {
            "tool": "deterministic-public-failure",
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
        self._requests: list[PublicFailureExecutionRequest] = []

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
    def requests(self) -> tuple[PublicFailureExecutionRequest, ...]:
        return tuple(self._requests)

    def execute(
        self, request: PublicFailureExecutionRequest, envelope: Envelope
    ) -> PublicFailureExecutionObservation:
        self._requests.append(request)
        if self._failure is not None:
            error_class, _private_detail = self._failure
            replay = ReplayResult(
                False,
                None,
                None,
                error_class,
                "deterministic public-failure Adapter failed",
                1,
            )
        elif len(self._output) > envelope.max_output_bytes:
            replay = ReplayResult(
                False,
                None,
                None,
                "output_limit",
                "deterministic output exceeded the frozen byte budget",
                1,
            )
        else:
            try:
                payload = json.loads(self._output.decode("utf-8"))
                canonical = canonical_bytes(payload)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                replay = ReplayResult(
                    False,
                    None,
                    None,
                    "parse_error",
                    "deterministic output was not strict JSON",
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
        return PublicFailureExecutionObservation(
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


class CodexCliPublicFailureAdapter:
    """Adapt the existing least-privilege Codex CLI process Adapter to P7D1A."""

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

    @property
    def evidence_class(self) -> str:
        return _REAL_EVIDENCE_CLASS

    @property
    def identity(self) -> Mapping[str, str]:
        return dict(self._inner.identity)

    @property
    def execution_policy(self) -> Mapping[str, Any]:
        return dict(self._inner.execution_policy)

    def execute(
        self, request: PublicFailureExecutionRequest, envelope: Envelope
    ) -> PublicFailureExecutionObservation:
        started_at = _now()
        observed = self._inner.execute(
            AgentForwardExecutionRequest(
                trial_id=request.capture_id,
                arm="baseline",
                workspace=request.workspace,
                prompt=request.prompt,
                output_schema_path=request.output_schema_path,
                final_output_path=request.final_output_path,
                skill_name="p7d1a-no-candidate",
                skill_md_sha256=hashlib.sha256(b"").hexdigest(),
                candidate_bundle_sha256=request.public_case_sha256,
                axes_sha256=request.axes_sha256,
            ),
            envelope,
        )
        return PublicFailureExecutionObservation(
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


def _validated_record(
    payload: Mapping[str, Any], schema: str, what: str
) -> tuple[dict[str, Any], str]:
    try:
        record = load_record(canonical_bytes(payload))
    except Exception as exc:
        raise PublicFailureCaptureError(f"invalid {what}: {exc}") from exc
    if record.schema_id != schema:
        raise PublicFailureCaptureError(
            f"{what} declares {record.schema_id!r}; expected {schema!r}"
        )
    return record.data, record.sha256


def _validate_plan(plan: PublicFailureCapturePlan, executor: PublicFailureExecutor) -> tuple[
    dict[str, Any], str, dict[str, Any], str, dict[str, Any], str, dict[str, Any]
]:
    if not isinstance(plan, PublicFailureCapturePlan):
        raise PublicFailureCaptureError("plan must be PublicFailureCapturePlan")
    task, task_sha = _validated_record(plan.task, "research-task/v1", "task")
    case, case_sha = _validated_record(
        plan.evaluation_case, "evaluation-case/v1", "evaluation case"
    )
    suite, suite_sha = _validated_record(plan.suite, "suite/v1", "suite")
    if task["domain"] not in _DOMAINS or case["domain"] != task["domain"]:
        raise PublicFailureCaptureError("task and evaluation case must share Math/Quant domain")
    if case["input"]["content_sha256"] != hashlib.sha256(plan.public_case_input).hexdigest():
        raise PublicFailureCaptureError("public case bytes do not match the evaluation-case pin")
    if not isinstance(plan.public_case_input, bytes):
        raise PublicFailureCaptureError("public case input must be exact bytes")
    for label, value in (
        ("prompt", plan.prompt),
        ("case_title", plan.case_title),
        ("signature_summary", plan.signature_summary),
        ("source_project", plan.source_project),
        ("rights", plan.rights),
    ):
        if not isinstance(value, str) or not value.strip():
            raise PublicFailureCaptureError(f"{label} must be non-empty")
        if scan_for_restricted(value, label):
            raise PublicFailureCaptureError(f"{label} contains restricted content")
    try:
        public_text = plan.public_case_input.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PublicFailureCaptureError("public case input must be strict UTF-8") from exc
    if scan_for_restricted(public_text, "public_case_input"):
        raise PublicFailureCaptureError("public case input contains restricted content")
    restricted_schema = scan_value_for_restricted(plan.output_schema, "output_schema")
    if restricted_schema:
        raise PublicFailureCaptureError("output schema contains restricted content")
    try:
        output_schema = json.loads(canonical_bytes(plan.output_schema))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PublicFailureCaptureError("output schema is not strict JSON") from exc
    if plan.envelope.seed is not None:
        raise PublicFailureCaptureError("real baseline capture must not fabricate a provider seed")
    if plan.envelope.retry_attempts != 0:
        raise PublicFailureCaptureError("real baseline capture forbids retries")
    if executor.evidence_class not in _EVIDENCE_CLASSES:
        raise PublicFailureCaptureError("unsupported executor evidence class")
    policy = dict(executor.execution_policy)
    if set(policy) != _POLICY_FIELDS:
        raise PublicFailureCaptureError("executor policy fields are not exact")
    if policy["reasoning_effort"] != plan.reasoning_effort:
        raise PublicFailureCaptureError("executor reasoning differs from the frozen plan")
    if executor.evidence_class == _REAL_EVIDENCE_CLASS:
        expected = {
            "sandbox": "read-only",
            "approval_policy": "never",
            "ephemeral": True,
            "web_search": "disabled",
        }
        if any(policy[key] != value for key, value in expected.items()):
            raise PublicFailureCaptureError("real Codex executor violates least privilege")
    if isinstance(policy["trace_max_bytes"], bool) or not isinstance(
        policy["trace_max_bytes"], int
    ) or policy["trace_max_bytes"] < 1024:
        raise PublicFailureCaptureError("executor trace budget is invalid")
    if set(plan.lineage) != {
        "independence_group",
        "origin_run_id",
        "dataset_lineage_id",
        "task_template_id",
        "semantic_duplicate_group",
    } or any(not isinstance(value, str) or not value.strip() for value in plan.lineage.values()):
        raise PublicFailureCaptureError("lineage fields must be exact and non-empty")
    if scan_value_for_restricted(plan.lineage, "lineage"):
        raise PublicFailureCaptureError("lineage contains restricted content")
    baseline = dict(plan.baseline)
    if set(baseline) != {"candidate_id", "sha256"}:
        raise PublicFailureCaptureError("baseline reference fields are not exact")
    if len(baseline["sha256"]) != 64 or any(
        ch not in "0123456789abcdef" for ch in baseline["sha256"]
    ):
        raise PublicFailureCaptureError("baseline SHA-256 is invalid")
    return task, task_sha, case, case_sha, suite, suite_sha, output_schema


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return True
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & flag)


def _assert_plain_directory(path: Path) -> None:
    if not path.is_dir() or _is_reparse(path):
        raise PublicFailureCaptureError("temporary workspace contains a reparse point")


def _prepare_workspace(
    root: Path, public_case_input: bytes, output_schema: Mapping[str, Any]
) -> tuple[Path, Path, Path]:
    workspace = root / "baseline"
    workspace.mkdir()
    _assert_plain_directory(workspace)
    (workspace / "AGENTS.md").write_text(
        "# P7D1A isolated public baseline\n\n"
        "Read only this workspace. Do not use network access, credentials, prior sessions, "
        "or files outside this workspace. Return only the requested structured result.\n",
        encoding="utf-8",
    )
    (workspace / "case-input.json").write_bytes(public_case_input)
    control = workspace / ".p7d1a"
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
            "p7d1a-public-failure-"
        ):
            return False
        shutil.rmtree(resolved)
        return not resolved.exists()
    except OSError:
        return False


def _normalize_observation(value: Any) -> PublicFailureExecutionObservation:
    if not isinstance(value, PublicFailureExecutionObservation):
        raise PublicFailureCaptureError("executor returned an invalid observation")
    if not isinstance(value.replay, ReplayResult):
        raise PublicFailureCaptureError("executor replay has the wrong type")
    if value.agent_session_started != (value.session_id is not None):
        raise PublicFailureCaptureError("session fact and session id disagree")
    if value.agent_turn_completed and not value.agent_session_started:
        raise PublicFailureCaptureError("turn completion requires a started session")
    if not process_facts_are_valid(
        value.execution_status,
        value.process_cleanup_status,
        value.process_tree_cleanup_verified,
    ):
        raise PublicFailureCaptureError("execution and process cleanup facts are inconsistent")
    for digest in (value.transcript_sha256, value.stderr_sha256):
        if digest is not None and (
            len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)
        ):
            raise PublicFailureCaptureError("executor emitted an invalid SHA-256")
    if any(
        not isinstance(key, str)
        or isinstance(number, bool)
        or not isinstance(number, int)
        or number < 0
        for key, number in value.usage.items()
    ):
        raise PublicFailureCaptureError("usage values must be non-negative integers")
    return value


def _screen_replay(replay: ReplayResult) -> ReplayResult:
    if not replay.ok or replay.output_bytes is None:
        return replay
    try:
        text = replay.output_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return ReplayResult(
            False, None, None, "parse_error", "Agent output was not strict UTF-8", replay.attempts
        )
    if scan_for_restricted(text, "agent_output"):
        return ReplayResult(
            False,
            None,
            None,
            "runner_error",
            "Agent output failed restricted-content screening",
            replay.attempts,
        )
    return replay


def _artifact_entry(name: str, content: bytes) -> dict[str, str]:
    return {"name": name, "sha256": hashlib.sha256(content).hexdigest()}


def _build_failure_chain(
    *,
    plan: PublicFailureCapturePlan,
    task: Mapping[str, Any],
    task_sha: str,
    evaluation: PipelineOutcome,
    observation: PublicFailureExecutionObservation,
    identity: Mapping[str, str],
    axes_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    environment = interpreter_environment()
    run_payload: dict[str, Any] = {
        "schema": "research-run/v1",
        "run_id": plan.lineage["origin_run_id"],
        "task": {"task_id": task["task_id"], "sha256": task_sha},
        "executor": dict(identity),
        "environment": [
            {"name": "python", "version": environment["interpreter_version"]},
            {"name": "p7d1a_axes", "version": axes_sha256},
        ],
        "inputs": [
            {
                "name": "public_case_input",
                "kind": "case",
                "sha256": hashlib.sha256(plan.public_case_input).hexdigest(),
            },
            {
                "name": "output_schema",
                "kind": "config",
                "sha256": canonical_sha256(plan.output_schema),
            },
            {
                "name": "evaluation_envelope",
                "kind": "config",
                "sha256": plan.envelope.canonical_sha256,
            },
            {
                "name": "prompt",
                "kind": "config",
                "sha256": hashlib.sha256(plan.prompt.encode("utf-8")).hexdigest(),
            },
        ],
        "randomness": {
            "mode": "uncontrolled",
            "details": "Provider seed unavailable; automatic retries prohibited.",
        },
        "started_at": observation.started_at,
        "completed_at": observation.completed_at,
    }
    run_payload, run_sha = _validated_record(run_payload, "research-run/v1", "research run")
    failed_gates = sorted(
        row.gate for row in evaluation.gate_results if row.result == "fail"
    )
    facts = [
        "One pre-registered baseline execution completed with deterministic verdict fail.",
        "The completed output was scored without retaining its plaintext in the failure records.",
    ]
    facts.extend(f"Evaluation gate {gate} returned fail." for gate in failed_gates)
    observation_payload: dict[str, Any] = {
        "schema": "research-failure-observation/v1",
        "observation_id": f"{plan.capture_id}-observation",
        "run": {"run_id": run_payload["run_id"], "sha256": run_sha},
        "observer": {
            "tool": "public-failure-capture",
            "version": _ADAPTER_VERSION,
        },
        "facts": facts,
        "observed_at": observation.completed_at,
    }
    observation_payload, observation_sha = _validated_record(
        observation_payload,
        "research-failure-observation/v1",
        "failure observation",
    )
    analysis_payload: dict[str, Any] = {
        "schema": "research-failure-analysis/v1",
        "analysis_id": f"{plan.capture_id}-analysis",
        "observation": {
            "observation_id": observation_payload["observation_id"],
            "sha256": observation_sha,
        },
        "hypotheses": [
            "The baseline response may have omitted or violated one or more "
            "pre-registered deterministic requirements; root cause remains unverified."
        ],
        "created_at": observation.completed_at,
    }
    analysis_payload, analysis_sha = _validated_record(
        analysis_payload, "research-failure-analysis/v1", "failure analysis"
    )
    intermediate: list[dict[str, str]] = []
    if evaluation.result_payload is not None:
        intermediate.append(
            _artifact_entry(
                "evaluation_result", canonical_bytes(evaluation.result_payload)
            )
        )
    case_payload: dict[str, Any] = {
        "schema": "research-case-package/v2",
        "case_id": plan.case_id,
        "title": plan.case_title,
        "task": {"task_id": task["task_id"], "sha256": task_sha},
        "runs": [{"run_id": run_payload["run_id"], "sha256": run_sha}],
        "claims": [],
        "evidence": [],
        "observations": [
            {
                "observation_id": observation_payload["observation_id"],
                "sha256": observation_sha,
            }
        ],
        "analyses": [
            {
                "analysis_id": analysis_payload["analysis_id"],
                "sha256": analysis_sha,
            }
        ],
        "problem_signature": {
            "summary": plan.signature_summary,
            "signature_sha256": plan.signature_sha256,
            "facets": dict(plan.lineage),
        },
        "io_manifest": {
            "inputs": [_artifact_entry("public_case_input", plan.public_case_input)],
            "outputs": [
                _artifact_entry(
                    "evaluation_attempt", canonical_bytes(evaluation.attempt_payload)
                )
            ],
        },
        "intermediate_manifest": intermediate,
        "decision_timeline": [
            {
                "at": observation.completed_at,
                "entry": (
                    "The pre-registered public baseline session completed under the "
                    "frozen envelope."
                ),
            },
            {
                "at": observation.completed_at,
                "entry": (
                    "Deterministic evaluation returned fail; sanitized failure "
                    "evidence was captured without raw output."
                ),
            },
        ],
        "open_questions": [
            "The causal failure mechanism requires later semantic analysis."
        ],
        "environment": {
            "tool": identity["tool"],
            "version": identity["version"],
            "details": "One bounded public baseline session; raw output omitted.",
        },
        "privacy_review_status": "passed",
        "export_mode": "benchmark_candidate",
        "rights": plan.rights,
        "eligibility": {"status": "eligible", "reasons": []},
        "source": {"project": plan.source_project},
        "derived_from": [],
        "created_at": observation.completed_at,
    }
    case_payload, _case_sha = _validated_record(
        case_payload, "research-case-package/v2", "research case"
    )
    return run_payload, observation_payload, analysis_payload, case_payload


def capture_public_agent_failure(
    plan: PublicFailureCapturePlan,
    executor: PublicFailureExecutor,
) -> PublicFailureCaptureOutcome:
    """Run one baseline once and capture only a qualified public failure."""

    task, task_sha, case, case_sha, suite, suite_sha, output_schema = _validate_plan(
        plan, executor
    )
    policy = dict(executor.execution_policy)
    identity = dict(executor.identity)
    if set(identity) not in ({"tool", "version"}, {"tool", "version", "model"}):
        raise PublicFailureCaptureError("executor identity fields are not exact")
    axes_sha = canonical_sha256(
        {
            "task_sha256": task_sha,
            "evaluation_case_sha256": case_sha,
            "suite_sha256": suite_sha,
            "baseline": dict(plan.baseline),
            "public_case_sha256": hashlib.sha256(plan.public_case_input).hexdigest(),
            "output_schema_sha256": canonical_sha256(output_schema),
            "prompt_sha256": hashlib.sha256(plan.prompt.encode("utf-8")).hexdigest(),
            "envelope_sha256": plan.envelope.canonical_sha256,
            "scoring_sha256": canonical_sha256(plan.scoring),
            "lineage": dict(plan.lineage),
            "executor_policy": policy,
        }
    )
    prepared = _prepare_evaluation(
        run_id=f"{plan.capture_id}-evaluation",
        case=case,
        suite=suite,
        candidate=plan.baseline,
        envelope=plan.envelope,
        scoring=plan.scoring,
        gate_config=plan.gate_config,
        generated_at=case["created_at"],
        environment={
            **interpreter_environment(),
            "evidence_class": executor.evidence_class,
            "p7d1a_axes_sha256": axes_sha,
            "ephemeral_session": policy["ephemeral"],
            "sandbox": policy["sandbox"],
            "approval_policy": policy["approval_policy"],
            "web_search": policy["web_search"],
            "raw_output_persisted": False,
            "candidate_generated": False,
            "hidden_evaluation_completed": False,
        },
    )
    temp_root = Path(tempfile.mkdtemp(prefix="p7d1a-public-failure-")).resolve()
    _assert_plain_directory(temp_root)
    try:
        workspace, schema_path, final_path = _prepare_workspace(
            temp_root, plan.public_case_input, output_schema
        )
        request = PublicFailureExecutionRequest(
            capture_id=plan.capture_id,
            workspace=workspace,
            prompt=plan.prompt,
            output_schema_path=schema_path,
            final_output_path=final_path,
            axes_sha256=axes_sha,
            public_case_sha256=hashlib.sha256(plan.public_case_input).hexdigest(),
        )
        try:
            observation = _normalize_observation(executor.execute(request, plan.envelope))
        except PublicFailureCaptureError:
            raise
        except Exception as exc:
            observation = PublicFailureExecutionObservation(
                replay=ReplayResult(
                    False,
                    None,
                    None,
                    "runner_error",
                    f"executor raised {type(exc).__name__}; message suppressed",
                    1,
                ),
                launcher_process_started=False,
                agent_session_started=False,
                agent_turn_completed=False,
                session_id=None,
                transcript_sha256=None,
                stderr_sha256=None,
                usage={},
                started_at=case["created_at"],
                completed_at=case["created_at"],
                execution_status="executor_failed",
                process_cleanup_status="unverified",
                process_tree_cleanup_verified=False,
            )
    finally:
        workspace_cleaned = _safe_cleanup(temp_root)
    replay = _screen_replay(observation.replay)
    session_sha = (
        hashlib.sha256(observation.session_id.encode("utf-8")).hexdigest()
        if observation.session_id is not None
        else None
    )
    environment = dict(prepared.environment)
    environment.update(
        {
            "launcher_process_started": observation.launcher_process_started,
            "agent_session_started": observation.agent_session_started,
            "agent_turn_completed": observation.agent_turn_completed,
            "execution_status": observation.execution_status,
            "process_cleanup_status": observation.process_cleanup_status,
            "process_tree_cleanup_verified": observation.process_tree_cleanup_verified,
            "workspace_cleaned": workspace_cleaned,
            "usage": observation.usage,
        }
    )
    if session_sha is not None:
        environment["session_id_sha256"] = session_sha
    if observation.transcript_sha256 is not None:
        environment["transcript_sha256"] = observation.transcript_sha256
    if observation.stderr_sha256 is not None:
        environment["stderr_sha256"] = observation.stderr_sha256
    object.__setattr__(prepared, "environment", environment)
    evaluation = _assemble_observation(prepared, replay, identity)

    blockers: list[str] = []
    if not workspace_cleaned:
        blockers.append("workspace_cleanup_failed")
    if not observation.process_tree_cleanup_verified:
        blockers.append("process_tree_cleanup_failed")
    real_executor = executor.evidence_class == _REAL_EVIDENCE_CLASS
    if real_executor and not observation.agent_session_started:
        blockers.append("real_agent_session_missing")
    if real_executor and not observation.agent_turn_completed:
        blockers.append("real_agent_turn_incomplete")
    if evaluation.result_payload is None:
        blockers.append("scored_result_missing")
    if evaluation.verdict not in {"pass", "fail"}:
        blockers.append(f"evaluation_{evaluation.verdict}")

    qualified = not blockers and evaluation.verdict == "fail"
    run_payload = observation_payload = analysis_payload = case_payload = None
    if qualified:
        run_payload, observation_payload, analysis_payload, case_payload = _build_failure_chain(
            plan=plan,
            task=task,
            task_sha=task_sha,
            evaluation=evaluation,
            observation=observation,
            identity=identity,
            axes_sha256=axes_sha,
        )
        status = "qualified_failure"
    elif blockers:
        status = "capture_inconclusive"
    else:
        status = "no_failure"
    claims = {
        "one_baseline_attempt_executed": True,
        "raw_output_persisted": False,
        "workspace_cleanup_verified": workspace_cleaned,
        "process_tree_cleanup_verified": observation.process_tree_cleanup_verified,
        "real_agent_session_observed": real_executor and observation.agent_session_started,
        "real_agent_turn_completed": real_executor and observation.agent_turn_completed,
        "qualified_public_failure_captured": qualified,
        "root_cause_established": False,
        "candidate_generated": False,
        "independent_review_completed": False,
        "hidden_evaluation_completed": False,
        "promotion_authorized": False,
        "publication_authorized": False,
        "installation_authorized": False,
        "activation_authorized": False,
    }
    return PublicFailureCaptureOutcome(
        status=status,
        blockers=tuple(blockers),
        evaluation=evaluation,
        task_payload=task,
        run_payload=run_payload,
        observation_payload=observation_payload,
        analysis_payload=analysis_payload,
        case_payload=case_payload,
        axes_sha256=axes_sha,
        adapter_identity=identity,
        session_id_sha256=session_sha,
        workspace_cleaned=workspace_cleaned,
        claims=claims,
    )


__all__ = [
    "CodexCliPublicFailureAdapter",
    "DeterministicPublicFailureAdapter",
    "PublicFailureCaptureError",
    "PublicFailureCaptureOutcome",
    "PublicFailureCapturePlan",
    "PublicFailureExecutionObservation",
    "PublicFailureExecutionRequest",
    "PublicFailureExecutor",
    "capture_public_agent_failure",
]
