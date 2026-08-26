"""P7C1 synthetic Candidate live-execution conformance seam.

``run_skill_forward_test`` is the module's single high-leverage interface.  It
validates the exact P7A/P7B chain, freezes every non-Skill axis once, executes
baseline and challenger through one injected adapter, and reuses the existing
evaluation attempt/result/run assembly.  P7C1 deliberately supports only
synthetic conformance: no Skill bytes are materialized or passed to a runner,
and no real Agent, fresh-session, independent-review, installation, activation,
publication, or promotion claim can be produced.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
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
from research_evolution.core._restricted import scan_for_restricted
from research_evolution.evaluation import Envelope, GateConfig, PipelineOutcome
from research_evolution.evaluation.envelope import ERROR_CLASSES
from research_evolution.evaluation.pipeline import (
    _assemble_observation,
    _prepare_evaluation,
    interpreter_environment,
)
from research_evolution.evaluation.runner import ReplayResult

from .envelope_closure import (
    EvaluationEnvelopeClosureError,
    EvaluationEnvelopeClosureReceipt,
)
from .skill_candidate import SkillCandidateBundle, SkillCandidateBundleError
from .skill_semantic_review import (
    SkillSemanticReviewAttestation,
    SkillSemanticReviewError,
)
from .skill_static_validation import (
    SkillStaticValidationError,
    SkillStaticValidationReceipt,
)

_EVIDENCE_CLASS = "synthetic_conformance"
_ADAPTER_VERSION = "0.1.0"
_ARMS = ("baseline", "candidate")
_TRIGGER_EXPECTATIONS = {
    "explicit_invocation": "select_candidate",
    "implicit_positive": "select_candidate",
    "declared_exclusion": "reject_candidate",
    "adjacent_skill_conflict": "reject_candidate",
}
_MANIFEST_ARTIFACT_BINDINGS = {
    "authoritative_head_snapshot": ("context", "authoritative_head", "sha256"),
    "budget_configuration": ("evaluation_envelope", "budget_sha256"),
    "evaluator_configuration": ("evaluation_envelope", "evaluator_sha256"),
    "public_data_manifest": ("evaluation_envelope", "data_sha256"),
    "tool_configuration": ("evaluation_envelope", "tools_sha256"),
}
_LIMITATIONS = (
    "Both adapters execute synthetic conformance bytes, not a real Agent or Skill payload.",
    "The local-process adapter is a fixed repository worker, not a security sandbox.",
    "Declared protocol labels do not prove real reviewer identity or fresh-session isolation.",
    "No installation, activation, publication, promotion, or external adoption is authorized.",
)


class SkillForwardTestError(ValueError):
    """A P7C1 plan or adapter violates the synthetic conformance contract."""


@dataclass(frozen=True)
class ForwardTestRequest:
    """One frozen arm request passed across the internal adapter seam."""

    test_id: str
    arm: str
    case_id: str
    candidate_id: str
    candidate_sha256: str
    case_input: bytes
    case_input_sha256: str
    axes_sha256: str
    trigger_mode: str
    expected_route: str
    skill_bundle_sha256: str | None


class SkillForwardTestAdapter(Protocol):
    """Internal port implemented by both P7C1 adapters."""

    @property
    def evidence_class(self) -> str: ...

    @property
    def identity(self) -> Mapping[str, str]: ...

    def execute(self, request: ForwardTestRequest, envelope: Envelope) -> ReplayResult: ...


@dataclass(frozen=True)
class SkillForwardTestPlan:
    """All immutable inputs consumed by :func:`run_skill_forward_test`."""

    test_id: str
    candidate_manifest: Record | Mapping[str, Any] | str | bytes | bytearray
    candidate_bundle: (
        SkillCandidateBundle | Record | Mapping[str, Any] | str | bytes | bytearray
    )
    candidate_payload: Mapping[str, bytes]
    static_validation_receipt: (
        SkillStaticValidationReceipt
        | Record
        | Mapping[str, Any]
        | str
        | bytes
        | bytearray
    )
    semantic_review_attestation: (
        SkillSemanticReviewAttestation
        | Record
        | Mapping[str, Any]
        | str
        | bytes
        | bytearray
    )
    envelope_closure_receipt: (
        EvaluationEnvelopeClosureReceipt
        | Record
        | Mapping[str, Any]
        | str
        | bytes
        | bytearray
    )
    case: Mapping[str, Any]
    suite: Mapping[str, Any]
    case_input: bytes
    envelope: Envelope
    scoring: Mapping[str, Any]
    gate_config: GateConfig
    generated_at: str
    trigger_mode: str
    expected_route: str


@dataclass(frozen=True)
class SkillForwardTestOutcome:
    """A non-publishable P7C1 aggregate over existing Core records."""

    status: str
    blockers: tuple[str, ...]
    baseline: PipelineOutcome | None
    candidate: PipelineOutcome | None
    axes_sha256: str
    adapter_identity: dict[str, str]
    limitations: tuple[str, ...] = _LIMITATIONS

    @property
    def claims(self) -> dict[str, bool]:
        started = self.baseline is not None or self.candidate is not None
        return {
            "synthetic_conformance_executed": started,
            "candidate_only_axes_frozen": bool(self.axes_sha256),
            "real_agent_execution_observed": False,
            "real_independent_semantic_review_completed": False,
            "fresh_session_validated": False,
            "runtime_loaded": False,
            "promotion_authorized": False,
            "publication_authorized": False,
            "installation_authorized": False,
            "activation_authorized": False,
        }


def _observe_output(output: bytes, envelope: Envelope) -> ReplayResult:
    if not isinstance(output, bytes):
        return ReplayResult(
            False, None, None, "runner_error", "adapter output was not bytes", 1
        )
    if len(output) > envelope.max_output_bytes:
        return ReplayResult(
            False,
            None,
            None,
            "output_limit",
            "adapter output exceeded the frozen byte budget",
            1,
        )
    try:
        parsed = load_strict_json(output)
    except CoreError:
        return ReplayResult(
            False,
            None,
            None,
            "parse_error",
            "adapter output was not strict JSON",
            1,
        )
    canonical = canonical_bytes(parsed)
    return ReplayResult(
        True,
        canonical,
        hashlib.sha256(canonical).hexdigest(),
        None,
        None,
        1,
    )


class DeterministicInProcessAdapter:
    """Return frozen synthetic outputs without filesystem or process I/O."""

    def __init__(
        self,
        outputs: Mapping[str, bytes],
        *,
        model: str,
        failures: Mapping[str, tuple[str, str]] | None = None,
    ) -> None:
        if set(outputs) != set(_ARMS):
            raise SkillForwardTestError("adapter outputs must cover both arms exactly")
        if not isinstance(model, str) or not model.strip():
            raise SkillForwardTestError("adapter model must be a non-empty string")
        normalized_failures = dict(failures or {})
        if not set(normalized_failures).issubset(_ARMS):
            raise SkillForwardTestError("adapter failures contain an unknown arm")
        for error_class, detail in normalized_failures.values():
            if error_class not in ERROR_CLASSES:
                raise SkillForwardTestError("adapter failure uses an unknown error class")
            if not isinstance(detail, str) or not detail.strip():
                raise SkillForwardTestError("adapter failure detail must be non-empty")
        self._outputs = dict(outputs)
        self._failures = normalized_failures
        self._identity = {
            "tool": "deterministic-in-process-forward-test",
            "version": _ADAPTER_VERSION,
            "model": model,
        }
        self._requests: list[ForwardTestRequest] = []

    @property
    def evidence_class(self) -> str:
        return _EVIDENCE_CLASS

    @property
    def identity(self) -> Mapping[str, str]:
        return dict(self._identity)

    @property
    def requests(self) -> tuple[ForwardTestRequest, ...]:
        return tuple(self._requests)

    def execute(self, request: ForwardTestRequest, envelope: Envelope) -> ReplayResult:
        self._requests.append(request)
        if request.arm in self._failures:
            error_class, detail = self._failures[request.arm]
            return ReplayResult(False, None, None, error_class, detail, 1)
        return _observe_output(self._outputs[request.arm], envelope)


def _subprocess_environment() -> dict[str, str]:
    env = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    for name in ("SYSTEMROOT", "WINDIR"):
        value = os.environ.get(name)
        if value:
            env[name] = value
    return env


class ConstrainedLocalProcessAdapter:
    """Cross a real process seam through a fixed, no-file worker.

    The caller supplies only frozen synthetic output bytes and optional delay
    or exit behavior.  The executable and worker are not caller-selectable,
    the working directory is temporary, the environment is allowlisted, and
    stderr is never copied into a Core diagnostic.  This is intentionally not
    a sandbox and cannot execute Candidate payload bytes.
    """

    def __init__(
        self,
        outputs: Mapping[str, bytes],
        *,
        model: str,
        delays_ms: Mapping[str, int] | None = None,
        exit_codes: Mapping[str, int] | None = None,
    ) -> None:
        if set(outputs) != set(_ARMS):
            raise SkillForwardTestError("adapter outputs must cover both arms exactly")
        if not isinstance(model, str) or not model.strip():
            raise SkillForwardTestError("adapter model must be a non-empty string")
        delays = dict(delays_ms or {})
        exits = dict(exit_codes or {})
        if not set(delays).issubset(_ARMS) or not set(exits).issubset(_ARMS):
            raise SkillForwardTestError("local-process behavior contains an unknown arm")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in delays.values()
        ):
            raise SkillForwardTestError("local-process delays must be non-negative integers")
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > 125
            for value in exits.values()
        ):
            raise SkillForwardTestError("local-process exit codes must be integers from 0 to 125")
        self._outputs = dict(outputs)
        self._delays_ms = delays
        self._exit_codes = exits
        self._identity = {
            "tool": "constrained-local-process-forward-test",
            "version": _ADAPTER_VERSION,
            "model": model,
        }
        self._worker = Path(__file__).with_name("_skill_forward_test_worker.py").resolve()
        if not self._worker.is_file():
            raise SkillForwardTestError("fixed local-process worker is unavailable")

    @property
    def evidence_class(self) -> str:
        return _EVIDENCE_CLASS

    @property
    def identity(self) -> Mapping[str, str]:
        return dict(self._identity)

    def execute(self, request: ForwardTestRequest, envelope: Envelope) -> ReplayResult:
        worker_request = {
            "arm": request.arm,
            "axes_sha256": request.axes_sha256,
            "case_input_sha256": request.case_input_sha256,
            "delay_ms": self._delays_ms.get(request.arm, 0),
            "exit_code": self._exit_codes.get(request.arm, 0),
            "output_base64": base64.b64encode(self._outputs[request.arm]).decode("ascii"),
        }
        try:
            with tempfile.TemporaryDirectory(prefix="p7c1-forward-test-") as tmp:
                completed = subprocess.run(
                    [sys.executable, "-B", "-I", str(self._worker)],
                    cwd=tmp,
                    env=_subprocess_environment(),
                    input=canonical_bytes(worker_request),
                    capture_output=True,
                    timeout=envelope.timeout_ms / 1000,
                    check=False,
                )
        except subprocess.TimeoutExpired:
            return ReplayResult(
                False,
                None,
                None,
                "timeout",
                "fixed local-process worker exceeded the frozen timeout",
                1,
            )
        except OSError:
            return ReplayResult(
                False,
                None,
                None,
                "runner_error",
                "fixed local-process worker could not be started",
                1,
            )
        if completed.returncode != 0:
            return ReplayResult(
                False,
                None,
                None,
                "runner_error",
                f"fixed local-process worker exited with code {completed.returncode}",
                1,
            )
        return _observe_output(completed.stdout, envelope)


def _load_record_source(
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
        raise SkillForwardTestError(f"invalid {label}: {exc}") from exc
    if record.schema_id != schema_id:
        raise SkillForwardTestError(
            f"expected {schema_id} for {label}, got {record.schema_id!r}"
        )
    return record


def _load_bundle(source: SkillForwardTestPlan) -> SkillCandidateBundle:
    value = source.candidate_bundle
    try:
        if isinstance(value, SkillCandidateBundle):
            return SkillCandidateBundle.from_payload(value.payload)
        if isinstance(value, Record):
            return SkillCandidateBundle(value)
        if isinstance(value, Mapping):
            return SkillCandidateBundle.from_payload(value)
        return SkillCandidateBundle(load_record(value))
    except (SkillCandidateBundleError, CoreError, TypeError, ValueError) as exc:
        raise SkillForwardTestError(f"invalid skill candidate bundle: {exc}") from exc


def _load_static(source: SkillForwardTestPlan) -> SkillStaticValidationReceipt:
    value = source.static_validation_receipt
    try:
        if isinstance(value, SkillStaticValidationReceipt):
            return SkillStaticValidationReceipt.from_payload(value.payload)
        if isinstance(value, Record):
            return SkillStaticValidationReceipt(value)
        if isinstance(value, Mapping):
            return SkillStaticValidationReceipt.from_payload(value)
        return SkillStaticValidationReceipt(load_record(value))
    except (SkillStaticValidationError, CoreError, TypeError, ValueError) as exc:
        raise SkillForwardTestError(f"invalid static validation receipt: {exc}") from exc


def _load_semantic(source: SkillForwardTestPlan) -> SkillSemanticReviewAttestation:
    value = source.semantic_review_attestation
    try:
        if isinstance(value, SkillSemanticReviewAttestation):
            return SkillSemanticReviewAttestation.from_payload(value.payload)
        if isinstance(value, Record):
            return SkillSemanticReviewAttestation(value)
        if isinstance(value, Mapping):
            return SkillSemanticReviewAttestation.from_payload(value)
        return SkillSemanticReviewAttestation(load_record(value))
    except (SkillSemanticReviewError, CoreError, TypeError, ValueError) as exc:
        raise SkillForwardTestError(f"invalid semantic review attestation: {exc}") from exc


def _load_envelope(source: SkillForwardTestPlan) -> EvaluationEnvelopeClosureReceipt:
    value = source.envelope_closure_receipt
    try:
        if isinstance(value, EvaluationEnvelopeClosureReceipt):
            return EvaluationEnvelopeClosureReceipt.from_payload(value.payload)
        if isinstance(value, Record):
            return EvaluationEnvelopeClosureReceipt(value)
        if isinstance(value, Mapping):
            return EvaluationEnvelopeClosureReceipt.from_payload(value)
        return EvaluationEnvelopeClosureReceipt.from_payload(load_record(value).data)
    except (EvaluationEnvelopeClosureError, CoreError, TypeError, ValueError) as exc:
        raise SkillForwardTestError(f"invalid envelope closure receipt: {exc}") from exc


def _nested(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = payload
    for field in path:
        value = value[field]
    return value


def _verify_payload_bytes(bundle: SkillCandidateBundle, payload: Mapping[str, bytes]) -> None:
    declared = {row["name"]: row for row in bundle.payload["payload_members"]}
    if set(payload) != set(declared):
        raise SkillForwardTestError("candidate payload byte set does not match the bundle")
    for name, descriptor in declared.items():
        content = payload[name]
        if not isinstance(content, bytes):
            raise SkillForwardTestError("candidate payload members must be exact bytes")
        if hashlib.sha256(content).hexdigest() != descriptor["sha256"] or len(
            content
        ) != descriptor["size_bytes"]:
            raise SkillForwardTestError(
                f"candidate payload member {name!r} hash or size mismatch"
            )
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise SkillForwardTestError(
                f"candidate payload member {name!r} is not strict UTF-8"
            ) from exc
        if scan_for_restricted(text, f"candidate_payload:{name}"):
            raise SkillForwardTestError(
                f"candidate payload member {name!r} contains restricted content"
            )


def _validated_identity(
    source: Mapping[str, str], model: str
) -> dict[str, str]:
    """Validate the runner fields shared by synthetic and real successors."""

    identity = dict(source)
    if set(identity) != {"tool", "version", "model"}:
        raise SkillForwardTestError("adapter identity must contain tool, version, and model")
    if any(not isinstance(value, str) or not value.strip() for value in identity.values()):
        raise SkillForwardTestError("adapter identity fields must be non-empty strings")
    if identity["model"] != model:
        raise SkillForwardTestError("adapter model differs from the frozen manifest model")
    return identity


def _normalize_observation(result: ReplayResult, attempts: int) -> ReplayResult:
    if not isinstance(result, ReplayResult):
        return ReplayResult(
            False, None, None, "runner_error", "adapter returned an invalid result", attempts
        )
    if result.ok:
        if result.output_bytes is None or result.output_sha256 is None:
            return ReplayResult(
                False,
                None,
                None,
                "runner_error",
                "adapter success omitted output bytes or hash",
                attempts,
            )
        if hashlib.sha256(result.output_bytes).hexdigest() != result.output_sha256:
            return ReplayResult(
                False,
                None,
                None,
                "runner_error",
                "adapter success output hash mismatch",
                attempts,
            )
        return ReplayResult(
            True, result.output_bytes, result.output_sha256, None, None, attempts
        )
    error_class = result.error_class if result.error_class in ERROR_CLASSES else "runner_error"
    detail = result.error_detail or "adapter failed without a diagnostic"
    if scan_for_restricted(detail, "forward_test_adapter_diagnostic"):
        detail = "adapter diagnostic suppressed by restricted-content policy"
    return ReplayResult(False, None, None, error_class, detail, attempts)


def _execute_with_retries(
    adapter: SkillForwardTestAdapter,
    request: ForwardTestRequest,
    envelope: Envelope,
) -> ReplayResult:
    attempts = 0
    while True:
        attempts += 1
        try:
            raw = adapter.execute(request, envelope)
        except Exception as exc:  # adapter messages may contain private values
            raw = ReplayResult(
                False,
                None,
                None,
                "runner_error",
                f"adapter raised {type(exc).__name__}; message suppressed",
                1,
            )
        result = _normalize_observation(raw, attempts)
        if (
            result.ok
            or result.error_class not in envelope.retry_on
            or attempts > envelope.retry_attempts
        ):
            return result


def _preflight_with_identity(
    plan: SkillForwardTestPlan,
    identity_source: Mapping[str, str],
) -> tuple[
    Record,
    SkillCandidateBundle,
    SkillStaticValidationReceipt,
    SkillSemanticReviewAttestation,
    EvaluationEnvelopeClosureReceipt,
    dict[str, str],
    str,
]:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,95}", plan.test_id) is None:
        raise SkillForwardTestError("test_id must be a bounded portable identifier")
    expected_route = _TRIGGER_EXPECTATIONS.get(plan.trigger_mode)
    if expected_route is None or plan.expected_route != expected_route:
        raise SkillForwardTestError("trigger mode and expected route are inconsistent")
    oracle = plan.scoring.get("oracle")
    if (
        plan.scoring.get("level") != "oracle"
        or not isinstance(oracle, Mapping)
        or oracle.get("route") != expected_route
    ):
        raise SkillForwardTestError(
            "P7C1 scoring must bind the expected Router outcome in an oracle"
        )
    if not isinstance(plan.case_input, bytes):
        raise SkillForwardTestError("case_input must be exact bytes")

    manifest = _load_record_source(
        plan.candidate_manifest,
        schema_id="candidate-manifest/v1",
        label="candidate manifest",
    )
    bundle = _load_bundle(plan)
    static = _load_static(plan)
    semantic = _load_semantic(plan)
    closure = _load_envelope(plan)
    manifest_pin = {
        "candidate_id": manifest.data["candidate_id"],
        "sha256": manifest.sha256,
    }
    if bundle.payload["candidate"] != manifest_pin:
        raise SkillForwardTestError("skill bundle does not pin the exact candidate manifest")
    bundle_pin = {
        "skill_candidate_bundle_id": bundle.payload["skill_candidate_bundle_id"],
        "sha256": bundle.sha256,
    }
    if static.payload["candidate_bundle"] != bundle_pin:
        raise SkillForwardTestError("static receipt does not pin the exact skill bundle")
    if semantic.payload["candidate_bundle"] != bundle_pin:
        raise SkillForwardTestError("semantic attestation does not pin the exact skill bundle")
    static_pin = {
        "skill_static_validation_receipt_id": static.payload[
            "skill_static_validation_receipt_id"
        ],
        "sha256": static.sha256,
    }
    if semantic.payload["static_validation_receipt"] != static_pin:
        raise SkillForwardTestError("semantic attestation does not pin the exact static receipt")
    if closure.payload["candidate"] != manifest_pin:
        raise SkillForwardTestError("envelope closure does not pin the exact candidate manifest")

    _verify_payload_bytes(bundle, plan.candidate_payload)
    case_record = _load_record_source(
        plan.case, schema_id="evaluation-case/v1", label="evaluation case"
    )
    if hashlib.sha256(plan.case_input).hexdigest() != case_record.data["input"][
        "content_sha256"
    ]:
        raise SkillForwardTestError("case input bytes do not match the evaluation case")

    artifacts = {row["role"]: row for row in closure.payload["artifacts"]}
    for role, path in _MANIFEST_ARTIFACT_BINDINGS.items():
        if artifacts[role]["content_sha256"] != _nested(manifest.data, path):
            raise SkillForwardTestError(
                f"envelope closure {role} does not match the candidate manifest"
            )
    rollback_sha = hashlib.sha256(manifest.data["rollback"].encode()).hexdigest()
    if artifacts["rollback_target"]["content_sha256"] != rollback_sha:
        raise SkillForwardTestError(
            "envelope closure rollback target does not match the candidate manifest"
        )

    model = manifest.data["evaluation_envelope"]["model"]
    identity = _validated_identity(identity_source, model)
    expected_runner = plan.gate_config.expected_runner
    if expected_runner != (identity["tool"], identity["version"]):
        raise SkillForwardTestError("gate policy does not freeze the exact adapter identity")
    if plan.gate_config.expected_scorer_tool is None:
        raise SkillForwardTestError("gate policy must freeze the scorer tool")

    axes_payload = {
        "candidate_manifest_sha256": manifest.sha256,
        "skill_candidate_bundle_sha256": bundle.sha256,
        "static_validation_receipt_sha256": static.sha256,
        "semantic_review_attestation_sha256": semantic.sha256,
        "envelope_closure_receipt_sha256": closure.sha256,
        "model": model,
        "reasoning": manifest.data["evaluation_envelope"]["reasoning"],
        "artifacts": {
            role: artifacts[role]["content_sha256"] for role in sorted(artifacts)
        },
        "evaluation_envelope_sha256": plan.envelope.canonical_sha256,
        "case_sha256": case_record.sha256,
        "suite_sha256": load_record(canonical_bytes(plan.suite)).sha256,
        "trigger_mode": plan.trigger_mode,
        "expected_route": plan.expected_route,
        "runner": identity,
    }
    return manifest, bundle, static, semantic, closure, identity, canonical_sha256(axes_payload)


def _preflight(
    plan: SkillForwardTestPlan,
    adapter: SkillForwardTestAdapter,
) -> tuple[
    Record,
    SkillCandidateBundle,
    SkillStaticValidationReceipt,
    SkillSemanticReviewAttestation,
    EvaluationEnvelopeClosureReceipt,
    dict[str, str],
    str,
]:
    if adapter.evidence_class != _EVIDENCE_CLASS:
        raise SkillForwardTestError("P7C1 accepts only synthetic conformance adapters")
    return _preflight_with_identity(plan, adapter.identity)


def run_skill_forward_test(
    plan: SkillForwardTestPlan,
    adapter: SkillForwardTestAdapter,
) -> SkillForwardTestOutcome:
    """Execute one synthetic baseline/Candidate pair through one deep seam.

    Valid protocol rejection is returned without starting either arm.  Once
    execution starts, both arm failures remain publishable through existing
    ``evaluation-attempt/v1`` payloads; ``evaluation-result/v1`` remains
    optional and no output or score is fabricated.
    """

    manifest, bundle, static, semantic, closure, identity, axes_sha = _preflight(
        plan, adapter
    )
    blockers: list[str] = []
    if static.payload["outcome"] != "static_pass":
        blockers.append("static_validation_not_passed")
    if semantic.payload["outcome"] != "protocol_accept":
        blockers.append(f"semantic_{semantic.payload['outcome']}")
    if not semantic.payload["claims"]["synthetic_fixture"]:
        blockers.append("p7c1_requires_synthetic_semantic_fixture")
    if blockers:
        return SkillForwardTestOutcome(
            status="prerequisite_rejected",
            blockers=tuple(blockers),
            baseline=None,
            candidate=None,
            axes_sha256=axes_sha,
            adapter_identity=identity,
        )

    base_environment = interpreter_environment()
    environment: dict[str, Any] = {
        **base_environment,
        "evidence_class": _EVIDENCE_CLASS,
        "forward_test_axes_sha256": axes_sha,
        "candidate_manifest_sha256": manifest.sha256,
        "skill_candidate_bundle_sha256": bundle.sha256,
        "static_validation_receipt_sha256": static.sha256,
        "semantic_review_attestation_sha256": semantic.sha256,
        "envelope_closure_receipt_sha256": closure.sha256,
        "trigger_mode": plan.trigger_mode,
        "expected_route": plan.expected_route,
        "candidate_payload_materialized": False,
        "runtime_loaded": False,
        "fresh_session_claimed": False,
        "real_agent_execution_claimed": False,
    }
    baseline_ref = {
        "candidate_id": f"baseline-{manifest.data['candidate_id']}",
        "sha256": manifest.data["baseline_sha256"],
    }
    candidate_ref = {
        "candidate_id": bundle.payload["skill_candidate_bundle_id"],
        "sha256": bundle.sha256,
    }
    baseline_prepared = _prepare_evaluation(
        run_id=f"{plan.test_id}-baseline",
        case=plan.case,
        suite=plan.suite,
        candidate=baseline_ref,
        envelope=plan.envelope,
        scoring=plan.scoring,
        gate_config=plan.gate_config,
        generated_at=plan.generated_at,
        environment=environment,
    )
    candidate_prepared = _prepare_evaluation(
        run_id=f"{plan.test_id}-candidate",
        case=plan.case,
        suite=plan.suite,
        candidate=candidate_ref,
        envelope=plan.envelope,
        scoring=plan.scoring,
        gate_config=plan.gate_config,
        generated_at=plan.generated_at,
        environment=environment,
    )
    requests = {
        "baseline": ForwardTestRequest(
            test_id=plan.test_id,
            arm="baseline",
            case_id=plan.case["evaluation_case_id"],
            candidate_id=baseline_ref["candidate_id"],
            candidate_sha256=baseline_ref["sha256"],
            case_input=plan.case_input,
            case_input_sha256=hashlib.sha256(plan.case_input).hexdigest(),
            axes_sha256=axes_sha,
            trigger_mode=plan.trigger_mode,
            expected_route=plan.expected_route,
            skill_bundle_sha256=None,
        ),
        "candidate": ForwardTestRequest(
            test_id=plan.test_id,
            arm="candidate",
            case_id=plan.case["evaluation_case_id"],
            candidate_id=candidate_ref["candidate_id"],
            candidate_sha256=candidate_ref["sha256"],
            case_input=plan.case_input,
            case_input_sha256=hashlib.sha256(plan.case_input).hexdigest(),
            axes_sha256=axes_sha,
            trigger_mode=plan.trigger_mode,
            expected_route=plan.expected_route,
            skill_bundle_sha256=bundle.sha256,
        ),
    }
    baseline_replay = _execute_with_retries(adapter, requests["baseline"], plan.envelope)
    candidate_replay = _execute_with_retries(adapter, requests["candidate"], plan.envelope)
    baseline = _assemble_observation(baseline_prepared, baseline_replay, identity)
    candidate = _assemble_observation(candidate_prepared, candidate_replay, identity)
    completed = all(
        outcome.result_payload is not None and outcome.run_payload is not None
        for outcome in (baseline, candidate)
    )
    return SkillForwardTestOutcome(
        status="conformance_completed" if completed else "conformance_inconclusive",
        blockers=(),
        baseline=baseline,
        candidate=candidate,
        axes_sha256=axes_sha,
        adapter_identity=identity,
    )


__all__ = [
    "ConstrainedLocalProcessAdapter",
    "DeterministicInProcessAdapter",
    "ForwardTestRequest",
    "SkillForwardTestAdapter",
    "SkillForwardTestError",
    "SkillForwardTestOutcome",
    "SkillForwardTestPlan",
    "run_skill_forward_test",
]
