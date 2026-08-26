"""P7C3 real-Agent smoke seam for one baseline/Candidate pair.

The module owns exact-candidate verification, repository-external workspace
projection, arm isolation, runtime-load checking, attempt/result assembly, and
safe cleanup behind one interface.  A true external Codex CLI adapter and a
deterministic contract adapter cross the same internal seam.

P7C3 is deliberately a bounded single-operator smoke.  It does not establish
independent semantic review, statistical improvement, hidden evaluation,
publication, promotion, installation, or activation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from research_evolution.core import canonical_bytes, canonical_sha256, load_strict_json
from research_evolution.core._restricted import scan_for_restricted
from research_evolution.evaluation import Envelope, PipelineOutcome
from research_evolution.evaluation.pipeline import (
    _assemble_observation,
    _prepare_evaluation,
    interpreter_environment,
)
from research_evolution.evaluation.runner import ReplayResult

from .skill_forward_test import (
    SkillForwardTestError,
    SkillForwardTestPlan,
    _preflight_with_identity,
)

_ADAPTER_VERSION = "0.1.0"
_ARMS = ("baseline", "candidate")
_REAL_EVIDENCE_CLASS = "real_codex_cli"
_SIMULATED_EVIDENCE_CLASS = "simulated_agent_contract"
_EVIDENCE_CLASSES = frozenset({_REAL_EVIDENCE_CLASS, _SIMULATED_EVIDENCE_CLASS})
_REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max", "ultra"})
_SKILL_RUNTIME_DIMENSION = "exact_match:skill_runtime"
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,95}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_WORKSPACE_POLICY = {
    "workspace_location": "system_temporary_directory",
    "candidate_location": ".agents/skills/<exact-skill-name>",
    "candidate_installed": False,
    "candidate_activated": False,
    "model_sandbox": "read-only",
    "network": "disabled",
    "session_persistence": "ephemeral",
}
_LIMITATIONS = (
    "A fresh ephemeral process is not an independent semantic reviewer.",
    "The public Math smoke is not a hidden, private, or statistical evaluation.",
    "Runtime digest echo proves bounded byte access, not general Skill quality.",
    "No publication, promotion, installation, activation, or adoption is authorized.",
)


class AgentForwardTrialError(ValueError):
    """The P7C3 plan, workspace, or adapter violates a hard contract."""


@dataclass(frozen=True)
class AgentForwardExecutionRequest:
    """One internal request passed to an Agent executor Adapter."""

    trial_id: str
    arm: str
    workspace: Path
    prompt: str
    output_schema_path: Path
    final_output_path: Path
    skill_name: str
    skill_md_sha256: str
    candidate_bundle_sha256: str
    axes_sha256: str


@dataclass(frozen=True)
class AgentExecutionObservation:
    """Sanitized process facts plus the existing replay observation."""

    replay: ReplayResult
    launcher_process_started: bool
    agent_session_started: bool
    agent_turn_completed: bool
    session_id: str | None
    runtime_loaded: bool
    observed_skill_name: str | None
    observed_skill_sha256: str | None
    transcript_sha256: str | None
    stderr_sha256: str | None
    usage: dict[str, int]


class AgentForwardExecutor(Protocol):
    """Internal port implemented by the deterministic and Codex adapters."""

    @property
    def evidence_class(self) -> str: ...

    @property
    def identity(self) -> Mapping[str, str]: ...

    @property
    def execution_policy(self) -> Mapping[str, Any]: ...

    def execute(
        self, request: AgentForwardExecutionRequest, envelope: Envelope
    ) -> AgentExecutionObservation: ...


@dataclass(frozen=True)
class AgentForwardTrialPlan:
    """Immutable P7C3 inputs layered over the P7C1 frozen chain."""

    forward_test_plan: SkillForwardTestPlan
    prompt: str
    reasoning_effort: str
    expected_candidate_runtime_loaded: bool


@dataclass(frozen=True)
class AgentForwardTrialOutcome:
    """Non-publishable aggregate over existing Core attempt/result records."""

    status: str
    blockers: tuple[str, ...]
    baseline: PipelineOutcome | None
    candidate: PipelineOutcome | None
    observations: dict[str, AgentExecutionObservation]
    axes_sha256: str
    adapter_identity: dict[str, str]
    workspace_cleaned: bool
    claims: dict[str, bool]
    limitations: tuple[str, ...] = _LIMITATIONS


def _runtime_fields(output: bytes | None) -> tuple[bool, str | None, str | None]:
    if output is None:
        return False, None, None
    try:
        payload = load_strict_json(output)
    except Exception:
        return False, None, None
    if not isinstance(payload, Mapping):
        return False, None, None
    runtime = payload.get("skill_runtime")
    if not isinstance(runtime, Mapping):
        return False, None, None
    loaded = runtime.get("loaded") is True
    name = runtime.get("name")
    digest = runtime.get("skill_md_sha256")
    return (
        loaded,
        name if isinstance(name, str) else None,
        digest if isinstance(digest, str) else None,
    )


class DeterministicAgentForwardAdapter:
    """Exercise the P7C3 interface without invoking an external model."""

    def __init__(
        self,
        outputs: Mapping[str, bytes],
        *,
        model: str,
        reasoning_effort: str,
        failures: Mapping[str, tuple[str, str]] | None = None,
    ) -> None:
        if set(outputs) != set(_ARMS):
            raise AgentForwardTrialError("adapter outputs must cover both arms exactly")
        if not model.strip():
            raise AgentForwardTrialError("adapter model must be non-empty")
        if not reasoning_effort.strip():
            raise AgentForwardTrialError("reasoning effort must be non-empty")
        self._outputs = dict(outputs)
        self._failures = dict(failures or {})
        if not set(self._failures).issubset(_ARMS):
            raise AgentForwardTrialError("adapter failures contain an unknown arm")
        self._identity = {
            "tool": "deterministic-agent-forward",
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
        self._requests: list[AgentForwardExecutionRequest] = []
        self._workspace_snapshots: list[tuple[str, tuple[str, ...]]] = []

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
    def requests(self) -> tuple[AgentForwardExecutionRequest, ...]:
        return tuple(self._requests)

    @property
    def workspace_snapshots(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return tuple(self._workspace_snapshots)

    def execute(
        self, request: AgentForwardExecutionRequest, envelope: Envelope
    ) -> AgentExecutionObservation:
        self._requests.append(request)
        names = tuple(
            sorted(
                path.relative_to(request.workspace).as_posix()
                for path in request.workspace.rglob("*")
                if path.is_file()
            )
        )
        self._workspace_snapshots.append((request.arm, names))
        if request.arm in self._failures:
            error_class, _ = self._failures[request.arm]
            replay = ReplayResult(
                False,
                None,
                None,
                error_class,
                "deterministic Agent adapter failed",
                1,
            )
            return AgentExecutionObservation(
                replay=replay,
                launcher_process_started=False,
                agent_session_started=False,
                agent_turn_completed=False,
                session_id=None,
                runtime_loaded=False,
                observed_skill_name=None,
                observed_skill_sha256=None,
                transcript_sha256=None,
                stderr_sha256=None,
                usage={},
            )
        output = self._outputs[request.arm]
        if len(output) > envelope.max_output_bytes:
            replay = ReplayResult(
                False,
                None,
                None,
                "output_limit",
                "Agent final output exceeded the frozen byte budget",
                1,
            )
        else:
            try:
                canonical = canonical_bytes(load_strict_json(output))
            except Exception:
                replay = ReplayResult(
                    False,
                    None,
                    None,
                    "parse_error",
                    "Agent final output was not strict JSON",
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
        loaded, name, digest = _runtime_fields(replay.output_bytes)
        transcript = canonical_bytes({"arm": request.arm, "output_sha256": replay.output_sha256})
        return AgentExecutionObservation(
            replay=replay,
            launcher_process_started=False,
            agent_session_started=True,
            agent_turn_completed=True,
            session_id=f"simulated-{request.trial_id}-{request.arm}",
            runtime_loaded=loaded,
            observed_skill_name=name,
            observed_skill_sha256=digest,
            transcript_sha256=hashlib.sha256(transcript).hexdigest(),
            stderr_sha256=None,
            usage={},
        )


def _filtered_codex_environment() -> dict[str, str]:
    allowed = {
        "APPDATA",
        "COMSPEC",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed and value}


def _trace_facts(trace: bytes) -> tuple[str | None, bool, dict[str, int]]:
    """Extract only session/turn/usage facts from bounded Codex JSONL."""

    session_id: str | None = None
    turn_completed = False
    usage: dict[str, int] = {}
    for raw_line in trace.splitlines():
        try:
            event = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        thread_id = event.get("thread_id")
        if event.get("type") == "thread.started" and isinstance(thread_id, str):
            stripped = thread_id.strip()
            session_id = stripped or None
        if event.get("type") == "turn.completed":
            turn_completed = True
            raw_usage = event.get("usage")
            if isinstance(raw_usage, dict):
                usage = {
                    key: value
                    for key, value in raw_usage.items()
                    if isinstance(key, str)
                    and isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                }
    if session_id is None:
        return None, False, {}
    return session_id, turn_completed, usage


class CodexCliAgentAdapter:
    """Invoke the authenticated Codex CLI with a frozen least-privilege policy."""

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
        launcher = launcher.resolve()
        powershell = powershell.resolve()
        if not launcher.is_file() or launcher.suffix.lower() != ".ps1":
            raise AgentForwardTrialError("Codex launcher must be an existing PowerShell file")
        if not powershell.is_file():
            raise AgentForwardTrialError("PowerShell executable is unavailable")
        if not cli_version.strip() or not model.strip():
            raise AgentForwardTrialError("Codex CLI version and model must be non-empty")
        if reasoning_effort not in _REASONING_EFFORTS:
            raise AgentForwardTrialError("unsupported reasoning effort")
        if isinstance(trace_max_bytes, bool) or trace_max_bytes < 1024:
            raise AgentForwardTrialError("trace_max_bytes must be at least 1024")
        self._launcher = launcher
        self._powershell = powershell
        self._trace_max_bytes = trace_max_bytes
        self._identity = {
            "tool": "codex-cli-agent-forward",
            "version": cli_version,
            "model": model,
        }
        self._policy = {
            "reasoning_effort": reasoning_effort,
            "sandbox": "read-only",
            "approval_policy": "never",
            "ephemeral": True,
            "web_search": "disabled",
            "trace_max_bytes": trace_max_bytes,
        }

    @property
    def evidence_class(self) -> str:
        return _REAL_EVIDENCE_CLASS

    @property
    def identity(self) -> Mapping[str, str]:
        return dict(self._identity)

    @property
    def execution_policy(self) -> Mapping[str, Any]:
        return dict(self._policy)

    def _command(self, request: AgentForwardExecutionRequest) -> list[str]:
        reasoning = self._policy["reasoning_effort"]
        return [
            str(self._powershell),
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(self._launcher),
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--model",
            self._identity["model"],
            "--color",
            "never",
            "--json",
            "--output-schema",
            str(request.output_schema_path),
            "--output-last-message",
            str(request.final_output_path),
            "--cd",
            str(request.workspace),
            "--config",
            'approval_policy="never"',
            "--config",
            'web_search="disabled"',
            "--config",
            f'model_reasoning_effort="{reasoning}"',
            "--config",
            'shell_environment_policy.inherit="core"',
            "--config",
            "shell_environment_policy.ignore_default_excludes=false",
            "-",
        ]

    def execute(
        self, request: AgentForwardExecutionRequest, envelope: Envelope
    ) -> AgentExecutionObservation:
        try:
            completed = subprocess.run(
                self._command(request),
                cwd=request.workspace,
                env=_filtered_codex_environment(),
                input=request.prompt.encode("utf-8"),
                capture_output=True,
                timeout=envelope.timeout_ms / 1000,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            trace = exc.stdout if isinstance(exc.stdout, bytes) else b""
            stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
            session_id, turn_completed, usage = _trace_facts(trace)
            return AgentExecutionObservation(
                replay=ReplayResult(
                    False,
                    None,
                    None,
                    "timeout",
                    "Codex CLI exceeded the frozen timeout",
                    1,
                ),
                launcher_process_started=True,
                agent_session_started=session_id is not None,
                agent_turn_completed=turn_completed,
                session_id=session_id,
                runtime_loaded=False,
                observed_skill_name=None,
                observed_skill_sha256=None,
                transcript_sha256=hashlib.sha256(trace).hexdigest() if trace else None,
                stderr_sha256=hashlib.sha256(stderr).hexdigest() if stderr else None,
                usage=usage,
            )
        except OSError:
            return AgentExecutionObservation(
                replay=ReplayResult(
                    False,
                    None,
                    None,
                    "runner_error",
                    "Codex CLI process could not be started",
                    1,
                ),
                launcher_process_started=False,
                agent_session_started=False,
                agent_turn_completed=False,
                session_id=None,
                runtime_loaded=False,
                observed_skill_name=None,
                observed_skill_sha256=None,
                transcript_sha256=None,
                stderr_sha256=None,
                usage={},
            )

        trace = completed.stdout
        stderr = completed.stderr if isinstance(completed.stderr, bytes) else b""
        trace_sha = hashlib.sha256(trace).hexdigest()
        stderr_sha = hashlib.sha256(stderr).hexdigest()
        if len(trace) > self._trace_max_bytes:
            replay = ReplayResult(
                False,
                None,
                None,
                "output_limit",
                "Codex JSONL trace exceeded the frozen trace byte budget",
                1,
            )
            return AgentExecutionObservation(
                replay=replay,
                launcher_process_started=True,
                agent_session_started=False,
                agent_turn_completed=False,
                session_id=None,
                runtime_loaded=False,
                observed_skill_name=None,
                observed_skill_sha256=None,
                transcript_sha256=trace_sha,
                stderr_sha256=stderr_sha,
                usage={},
            )
        session_id, turn_completed, usage = _trace_facts(trace)
        if completed.returncode != 0:
            replay = ReplayResult(
                False,
                None,
                None,
                "runner_error",
                f"Codex CLI exited with code {completed.returncode}",
                1,
            )
        elif not request.final_output_path.is_file():
            replay = ReplayResult(
                False,
                None,
                None,
                "runner_error",
                "Codex CLI did not produce the structured final output",
                1,
            )
        else:
            output = request.final_output_path.read_bytes()
            if len(output) > envelope.max_output_bytes:
                replay = ReplayResult(
                    False,
                    None,
                    None,
                    "output_limit",
                    "Codex final output exceeded the frozen byte budget",
                    1,
                )
            else:
                try:
                    canonical = canonical_bytes(load_strict_json(output))
                except Exception:
                    replay = ReplayResult(
                        False,
                        None,
                        None,
                        "parse_error",
                        "Codex final output was not strict JSON",
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
        loaded, name, digest = _runtime_fields(replay.output_bytes)
        return AgentExecutionObservation(
            replay=replay,
            launcher_process_started=True,
            agent_session_started=session_id is not None,
            agent_turn_completed=turn_completed,
            session_id=session_id,
            runtime_loaded=loaded,
            observed_skill_name=name,
            observed_skill_sha256=digest,
            transcript_sha256=trace_sha,
            stderr_sha256=stderr_sha,
            usage=usage,
        )


def _validate_execution_policy(
    executor: AgentForwardExecutor, reasoning_effort: str
) -> dict[str, Any]:
    policy = dict(executor.execution_policy)
    if set(policy) != {
        "reasoning_effort",
        "sandbox",
        "approval_policy",
        "ephemeral",
        "web_search",
        "trace_max_bytes",
    }:
        raise AgentForwardTrialError("executor policy fields are not exact")
    if policy["reasoning_effort"] != reasoning_effort:
        raise AgentForwardTrialError("executor reasoning differs from the frozen plan")
    if executor.evidence_class == _REAL_EVIDENCE_CLASS:
        required = {
            "sandbox": "read-only",
            "approval_policy": "never",
            "ephemeral": True,
            "web_search": "disabled",
        }
        if any(policy[name] != value for name, value in required.items()):
            raise AgentForwardTrialError("real Codex executor violates least privilege")
    trace_max = policy["trace_max_bytes"]
    if isinstance(trace_max, bool) or not isinstance(trace_max, int) or trace_max < 1024:
        raise AgentForwardTrialError("executor trace budget is invalid")
    return policy


def _output_schema() -> dict[str, Any]:
    nullable_string = {"type": ["string", "null"]}
    nullable_sha = {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"}
    return {
        "type": "object",
        "required": ["answer", "route", "skill_runtime"],
        "properties": {
            "answer": {"type": "string"},
            "route": {"enum": ["select_candidate", "reject_candidate"]},
            "skill_runtime": {
                "type": "object",
                "required": ["loaded", "name", "skill_md_sha256"],
                "properties": {
                    "loaded": {"type": "boolean"},
                    "name": nullable_string,
                    "skill_md_sha256": nullable_sha,
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & reparse)


def _assert_plain_directory(path: Path) -> None:
    if not path.is_dir() or _is_reparse(path):
        raise AgentForwardTrialError("temporary workspace contains a reparse point")


def _safe_destination(root: Path, name: str) -> Path:
    pure = PurePosixPath(name)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise AgentForwardTrialError("candidate payload contains an unsafe path")
    destination = root.joinpath(*pure.parts)
    resolved_root = root.resolve()
    resolved_parent = destination.parent.resolve()
    if not resolved_parent.is_relative_to(resolved_root):
        raise AgentForwardTrialError("candidate payload escapes the temporary Skill root")
    return destination


def _prepare_workspace(
    root: Path,
    arm: str,
    *,
    skill_name: str,
    candidate_payload: Mapping[str, bytes],
    case_input: bytes,
) -> tuple[Path, Path, Path]:
    workspace = root / arm
    workspace.mkdir()
    _assert_plain_directory(workspace)
    instruction = (
        b"# P7C3 isolated smoke\n\n"
        b"Read only this workspace. Do not use network access, credentials, prior sessions, "
        b"or files outside this workspace. Return only the requested structured result.\n"
    )
    (workspace / "AGENTS.md").write_bytes(instruction)
    (workspace / "case-input.json").write_bytes(case_input)
    control = workspace / ".p7c3"
    control.mkdir()
    _assert_plain_directory(control)
    schema_path = control / "output-schema.json"
    schema_path.write_bytes(canonical_bytes(_output_schema()))
    final_path = control / "final.json"
    if arm == "candidate":
        skill_root = workspace / ".agents" / "skills" / skill_name
        skill_root.mkdir(parents=True)
        for name, content in candidate_payload.items():
            destination = _safe_destination(skill_root, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            for parent in destination.parents:
                if parent == workspace.parent:
                    break
                if parent.exists():
                    _assert_plain_directory(parent)
                if parent == workspace:
                    break
            destination.write_bytes(content)
    return workspace, schema_path, final_path


def _safe_cleanup(root: Path) -> bool:
    expected_parent = Path(tempfile.gettempdir()).resolve()
    try:
        resolved = root.resolve()
        if resolved.parent != expected_parent or not resolved.name.startswith(
            "p7c3-agent-forward-"
        ):
            return False
        shutil.rmtree(resolved)
        return not resolved.exists()
    except OSError:
        return False


def _normalize_observation(value: Any) -> AgentExecutionObservation:
    if not isinstance(value, AgentExecutionObservation):
        return AgentExecutionObservation(
            replay=ReplayResult(
                False,
                None,
                None,
                "runner_error",
                "Agent executor returned an invalid observation",
                1,
            ),
            launcher_process_started=False,
            agent_session_started=False,
            agent_turn_completed=False,
            session_id=None,
            runtime_loaded=False,
            observed_skill_name=None,
            observed_skill_sha256=None,
            transcript_sha256=None,
            stderr_sha256=None,
            usage={},
        )
    replay = value.replay
    if not isinstance(replay, ReplayResult):
        raise AgentForwardTrialError("Agent observation replay has the wrong type")
    if value.session_id is not None and not value.session_id.strip():
        raise AgentForwardTrialError("Agent session id must be non-empty when present")
    for name in (
        "launcher_process_started",
        "agent_session_started",
        "agent_turn_completed",
    ):
        if not isinstance(getattr(value, name), bool):
            raise AgentForwardTrialError(f"Agent {name} fact must be boolean")
    if value.agent_session_started != (value.session_id is not None):
        raise AgentForwardTrialError("Agent session fact and session id disagree")
    if value.agent_turn_completed and not value.agent_session_started:
        raise AgentForwardTrialError("Agent turn completion requires a started session")
    if value.transcript_sha256 is not None and _HEX_64.fullmatch(value.transcript_sha256) is None:
        raise AgentForwardTrialError("Agent transcript hash is invalid")
    if value.stderr_sha256 is not None and _HEX_64.fullmatch(value.stderr_sha256) is None:
        raise AgentForwardTrialError("Agent stderr hash is invalid")
    if (
        value.observed_skill_sha256 is not None
        and _HEX_64.fullmatch(value.observed_skill_sha256) is None
    ):
        raise AgentForwardTrialError("observed Skill hash is invalid")
    if any(
        not isinstance(key, str)
        or isinstance(number, bool)
        or not isinstance(number, int)
        or number < 0
        for key, number in value.usage.items()
    ):
        raise AgentForwardTrialError("Agent usage values must be non-negative integers")
    return value


def _execute_once(
    executor: AgentForwardExecutor,
    request: AgentForwardExecutionRequest,
    envelope: Envelope,
) -> AgentExecutionObservation:
    try:
        value = executor.execute(request, envelope)
    except Exception as exc:  # external messages may carry local or private values
        value = AgentExecutionObservation(
            replay=ReplayResult(
                False,
                None,
                None,
                "runner_error",
                f"Agent executor raised {type(exc).__name__}; message suppressed",
                1,
            ),
            launcher_process_started=False,
            agent_session_started=False,
            agent_turn_completed=False,
            session_id=None,
            runtime_loaded=False,
            observed_skill_name=None,
            observed_skill_sha256=None,
            transcript_sha256=None,
            stderr_sha256=None,
            usage={},
        )
    return _normalize_observation(value)


def _runtime_expectation(
    arm: str,
    *,
    candidate_expected_loaded: bool,
    skill_name: str,
    skill_sha256: str,
) -> dict[str, Any]:
    loaded = arm == "candidate" and candidate_expected_loaded
    return {
        "loaded": loaded,
        "name": skill_name if loaded else None,
        "skill_md_sha256": skill_sha256 if loaded else None,
    }


def _runtime_match_components(
    observation: AgentExecutionObservation, expected: Mapping[str, Any]
) -> dict[str, bool]:
    return {
        "runtime_loaded_matches": observation.runtime_loaded is expected["loaded"],
        "runtime_name_matches": observation.observed_skill_name == expected["name"],
        "runtime_digest_matches": (
            observation.observed_skill_sha256 == expected["skill_md_sha256"]
        ),
    }


def run_agent_skill_forward_trial(
    plan: AgentForwardTrialPlan,
    executor: AgentForwardExecutor,
) -> AgentForwardTrialOutcome:
    """Run one isolated baseline/Candidate Agent smoke through a single seam."""

    if executor.evidence_class not in _EVIDENCE_CLASSES:
        raise AgentForwardTrialError("unsupported Agent evidence class")
    if not isinstance(plan.reasoning_effort, str) or not plan.reasoning_effort.strip():
        raise AgentForwardTrialError("reasoning effort must be non-empty")
    if not isinstance(plan.prompt, str) or not plan.prompt.strip() or len(plan.prompt) > 16_384:
        raise AgentForwardTrialError("prompt must be non-empty and at most 16384 characters")
    if scan_for_restricted(plan.prompt, "agent_forward_prompt"):
        raise AgentForwardTrialError("prompt contains restricted content")
    if plan.forward_test_plan.envelope.seed is not None:
        raise AgentForwardTrialError("real Agent smoke must not fabricate a provider seed")
    if plan.forward_test_plan.envelope.retry_attempts != 0:
        raise AgentForwardTrialError("real Agent smoke forbids automatic retries")
    floors = dict(plan.forward_test_plan.gate_config.regression_floors)
    if floors.get(_SKILL_RUNTIME_DIMENSION) != 1.0:
        raise AgentForwardTrialError("runtime digest oracle must be a hard regression floor")

    policy = _validate_execution_policy(executor, plan.reasoning_effort)
    try:
        manifest, bundle, static, semantic, closure, identity, base_axes = _preflight_with_identity(
            plan.forward_test_plan, executor.identity
        )
    except SkillForwardTestError as exc:
        raise AgentForwardTrialError(str(exc)) from exc
    if manifest.data["evaluation_envelope"]["reasoning"] != plan.reasoning_effort:
        raise AgentForwardTrialError("manifest reasoning differs from the frozen plan")
    if static.payload["outcome"] != "static_pass":
        raise AgentForwardTrialError("static validation must pass before Agent execution")
    if semantic.payload["outcome"] != "protocol_accept":
        raise AgentForwardTrialError("semantic protocol must accept before Agent execution")
    if not semantic.payload["claims"]["synthetic_fixture"]:
        raise AgentForwardTrialError("P7C3 smoke does not accept unverified real-review claims")

    skill_name = bundle.payload["skill"]["name"]
    if _SAFE_IDENTIFIER.fullmatch(skill_name) is None:
        raise AgentForwardTrialError("Skill name is not a bounded portable identifier")
    skill_bytes = plan.forward_test_plan.candidate_payload.get("SKILL.md")
    if skill_bytes is None:
        raise AgentForwardTrialError("candidate payload omits SKILL.md")
    skill_sha = hashlib.sha256(skill_bytes).hexdigest()
    axes_sha = canonical_sha256(
        {
            "p7c1_axes_sha256": base_axes,
            "prompt_sha256": hashlib.sha256(plan.prompt.encode("utf-8")).hexdigest(),
            "reasoning_effort": plan.reasoning_effort,
            "expected_candidate_runtime_loaded": plan.expected_candidate_runtime_loaded,
            "executor_policy": policy,
            "workspace_policy": _WORKSPACE_POLICY,
        }
    )
    temp_root = Path(tempfile.mkdtemp(prefix="p7c3-agent-forward-")).resolve()
    _assert_plain_directory(temp_root)
    observations: dict[str, AgentExecutionObservation] = {}
    try:
        for arm in _ARMS:
            workspace, schema_path, final_path = _prepare_workspace(
                temp_root,
                arm,
                skill_name=skill_name,
                candidate_payload=plan.forward_test_plan.candidate_payload,
                case_input=plan.forward_test_plan.case_input,
            )
            request = AgentForwardExecutionRequest(
                trial_id=plan.forward_test_plan.test_id,
                arm=arm,
                workspace=workspace,
                prompt=plan.prompt,
                output_schema_path=schema_path,
                final_output_path=final_path,
                skill_name=skill_name,
                skill_md_sha256=skill_sha,
                candidate_bundle_sha256=bundle.sha256,
                axes_sha256=axes_sha,
            )
            observations[arm] = _execute_once(executor, request, plan.forward_test_plan.envelope)
    finally:
        workspace_cleaned = _safe_cleanup(temp_root)

    outcomes: dict[str, PipelineOutcome] = {}
    runtime_matches: dict[str, bool] = {}
    runtime_match_components: dict[str, dict[str, bool]] = {}
    for arm in _ARMS:
        observation = observations[arm]
        expected_runtime = _runtime_expectation(
            arm,
            candidate_expected_loaded=plan.expected_candidate_runtime_loaded,
            skill_name=skill_name,
            skill_sha256=skill_sha,
        )
        runtime_match_components[arm] = _runtime_match_components(observation, expected_runtime)
        runtime_matches[arm] = all(runtime_match_components[arm].values())
        scoring = dict(plan.forward_test_plan.scoring)
        oracle = dict(scoring["oracle"])
        oracle["skill_runtime"] = expected_runtime
        scoring["oracle"] = oracle
        session_sha = (
            hashlib.sha256(observation.session_id.encode("utf-8")).hexdigest()
            if observation.session_id is not None
            else None
        )
        environment: dict[str, Any] = {
            **interpreter_environment(),
            "evidence_class": executor.evidence_class,
            "agent_forward_axes_sha256": axes_sha,
            "candidate_manifest_sha256": manifest.sha256,
            "skill_candidate_bundle_sha256": bundle.sha256,
            "static_validation_receipt_sha256": static.sha256,
            "semantic_review_attestation_sha256": semantic.sha256,
            "envelope_closure_receipt_sha256": closure.sha256,
            "trigger_mode": plan.forward_test_plan.trigger_mode,
            "expected_route": plan.forward_test_plan.expected_route,
            "candidate_payload_materialized": arm == "candidate",
            "candidate_installed": False,
            "candidate_activated": False,
            "runtime_loaded": observation.runtime_loaded,
            **runtime_match_components[arm],
            "runtime_expectation_verified": runtime_matches[arm],
            "launcher_process_started": observation.launcher_process_started,
            "agent_session_started": observation.agent_session_started,
            "agent_turn_completed": observation.agent_turn_completed,
            "ephemeral_session": policy["ephemeral"],
            "sandbox": policy["sandbox"],
            "approval_policy": policy["approval_policy"],
            "web_search": policy["web_search"],
            "workspace_cleaned": workspace_cleaned,
            "fresh_session_validated": False,
            "independent_review_claimed": False,
            "real_agent_session_claimed": (
                executor.evidence_class == _REAL_EVIDENCE_CLASS
                and observation.agent_session_started
            ),
            "real_agent_turn_completed_claimed": (
                executor.evidence_class == _REAL_EVIDENCE_CLASS and observation.agent_turn_completed
            ),
            "usage": observation.usage,
        }
        if session_sha is not None:
            environment["session_id_sha256"] = session_sha
        if observation.transcript_sha256 is not None:
            environment["transcript_sha256"] = observation.transcript_sha256
        if observation.stderr_sha256 is not None:
            environment["stderr_sha256"] = observation.stderr_sha256
        if observation.observed_skill_sha256 is not None:
            environment["observed_skill_sha256"] = observation.observed_skill_sha256
        candidate_ref = (
            {
                "candidate_id": f"baseline-{manifest.data['candidate_id']}",
                "sha256": manifest.data["baseline_sha256"],
            }
            if arm == "baseline"
            else {
                "candidate_id": bundle.payload["skill_candidate_bundle_id"],
                "sha256": bundle.sha256,
            }
        )
        prepared = _prepare_evaluation(
            run_id=f"{plan.forward_test_plan.test_id}-{arm}",
            case=plan.forward_test_plan.case,
            suite=plan.forward_test_plan.suite,
            candidate=candidate_ref,
            envelope=plan.forward_test_plan.envelope,
            scoring=scoring,
            gate_config=plan.forward_test_plan.gate_config,
            generated_at=plan.forward_test_plan.generated_at,
            environment=environment,
        )
        outcomes[arm] = _assemble_observation(prepared, observation.replay, identity)

    blockers: list[str] = []
    if not workspace_cleaned:
        blockers.append("workspace_cleanup_failed")
    for arm in _ARMS:
        if not runtime_matches[arm]:
            blockers.append(f"{arm}_runtime_expectation_failed")
        if outcomes[arm].result_payload is None:
            blockers.append(f"{arm}_result_missing")
        elif outcomes[arm].verdict != "pass":
            blockers.append(f"{arm}_verdict_{outcomes[arm].verdict}")
    real_executor = executor.evidence_class == _REAL_EVIDENCE_CLASS
    if real_executor:
        for arm in _ARMS:
            observation = observations[arm]
            if not observation.agent_session_started:
                blockers.append(f"{arm}_agent_session_missing")
            elif not observation.agent_turn_completed:
                blockers.append(f"{arm}_agent_turn_incomplete")
    session_ids = [observations[arm].session_id for arm in _ARMS]
    real_sessions_observed = real_executor and all(
        observations[arm].agent_session_started for arm in _ARMS
    )
    real_turns_completed = real_executor and all(
        observations[arm].agent_turn_completed for arm in _ARMS
    )
    distinct_session_pair = (
        real_sessions_observed and all(session_ids) and len(set(session_ids)) == len(session_ids)
    )
    if real_sessions_observed and not distinct_session_pair:
        blockers.append("agent_session_ids_not_distinct")
    status = "smoke_completed"
    if blockers:
        status = (
            "smoke_rejected"
            if all(outcomes[arm].result_payload is not None for arm in _ARMS)
            else "smoke_inconclusive"
        )
    claims = {
        "candidate_payload_materialized_ephemerally": True,
        "workspace_cleanup_verified": workspace_cleaned,
        "runtime_expectation_verified": all(runtime_matches.values()),
        "candidate_runtime_loaded": observations["candidate"].runtime_loaded,
        "real_agent_session_observed": real_sessions_observed,
        "real_agent_turn_completed": real_turns_completed,
        "distinct_ephemeral_sessions_observed": bool(distinct_session_pair),
        "real_independent_semantic_review_completed": False,
        "fresh_session_validated": False,
        "hidden_evaluation_completed": False,
        "promotion_authorized": False,
        "publication_authorized": False,
        "installation_authorized": False,
        "activation_authorized": False,
    }
    return AgentForwardTrialOutcome(
        status=status,
        blockers=tuple(blockers),
        baseline=outcomes["baseline"],
        candidate=outcomes["candidate"],
        observations=observations,
        axes_sha256=axes_sha,
        adapter_identity=identity,
        workspace_cleaned=workspace_cleaned,
        claims=claims,
    )


__all__ = [
    "AgentExecutionObservation",
    "AgentForwardExecutionRequest",
    "AgentForwardExecutor",
    "AgentForwardTrialError",
    "AgentForwardTrialOutcome",
    "AgentForwardTrialPlan",
    "CodexCliAgentAdapter",
    "DeterministicAgentForwardAdapter",
    "run_agent_skill_forward_trial",
]
