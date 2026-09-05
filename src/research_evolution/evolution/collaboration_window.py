"""P7F bounded collaboration with method autonomy and frozen semantics.

``run_collaboration_window`` is the Module's only high-leverage interface.  It
validates the complete three-slot plan and derives every ticket before calling
an adapter.  Workers may choose, combine, abandon, or replace methods inside a
ticket.  They may not change the active target, claim/evidence standard,
permissions, hard resource envelope, or lifecycle authority.

P7F3 adds one constrained local-process adapter behind that same interface.
Deterministic fake-launcher evidence remains synthetic; authenticated CLI facts
may establish bounded execution only, never identity, independent review, or
lifecycle authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from research_evolution.core import CoreError, Record, canonical_bytes, load_record
from research_evolution.core._restricted import scan_value_for_restricted

from ._process_containment import process_facts_are_valid, run_process_contained

_PLAN_SCHEMA = "collaboration-window-plan/v1"
_TICKET_SCHEMA = "collaboration-ticket/v1"
_OUTCOME_SCHEMA = "collaboration-worker-outcome/v1"
_OUTCOME_SCHEMA_V2 = "collaboration-worker-outcome/v2"
_SLOTS = ("A", "B", "C")
_ROLES = {"A": "explorer_a", "B": "explorer_b", "C": "explorer_c"}
_BUDGET_FIELDS = ("max_runtime_seconds", "max_tool_calls", "max_output_bytes")
_USAGE_FIELDS = {
    "max_runtime_seconds": "runtime_seconds",
    "max_tool_calls": "tool_calls",
    "max_output_bytes": "output_bytes",
}
_REQUIRED_OUTPUTS = ("artifacts", "opportunity_chain", "status")
_LIMITATIONS = (
    "Only a deterministic in-process adapter is implemented; the seam is provisional.",
    "Worker labels are neutral protocol roles and do not verify separate identities.",
    "Method autonomy is exercised only against synthetic observations.",
    "No independent review, publication, installation, activation, or promotion is authorized.",
)
_PROCESS_LIMITATIONS = (
    "The adapter proves only bounded local-process execution and sanitized structural facts.",
    "Neutral worker labels do not verify separate human, model, or account identities.",
    "Fake-launcher evidence is synthetic and authenticated CLI evidence is not semantic review.",
    "No independent review, publication, installation, activation, or promotion is authorized.",
)
_CLAIMS = {
    "synthetic_collaboration_contract_exercised": True,
    "real_multi_agent_execution_observed": False,
    "real_agent_identity_verified": False,
    "collaboration_seam_stable": False,
    "independent_verification_completed": False,
    "publication_authorized": False,
    "installation_authorized": False,
    "activation_authorized": False,
    "promotion_authorized": False,
}
_AUTONOMY = {
    "choose_methods": True,
    "combine_methods": True,
    "abandon_methods": True,
    "replace_methods": True,
    "create_auxiliary_work": True,
    "run_allowed_tools": True,
    "stop_early": True,
    "change_active_target": False,
    "expand_claim_scope": False,
    "lower_evidence_standard": False,
    "expand_permissions": False,
    "expand_budget": False,
    "publish_authoritative_state": False,
}


class CollaborationWindowError(ValueError):
    """A collaboration plan or observation violated a fail-closed contract."""


@dataclass(frozen=True)
class CollaborationWindowPlan:
    """Caller-owned immutable inputs for one bounded collaboration window."""

    collaboration_window_plan_id: str
    task: Record
    active_target: str
    claim_scope: str
    completion_standard: str
    evidence_standard: str
    forbidden_expansions: tuple[str, ...]
    input_artifacts: tuple[Mapping[str, Any], ...]
    routes: tuple[Mapping[str, Any], ...]
    allowed_tools: tuple[str, ...]
    writable_staging: str
    hard_budget: Mapping[str, int]
    created_at: str


@dataclass(frozen=True)
class CollaborationWorkerRequest:
    """Exact ticket projection delivered to an adapter."""

    ticket: Record
    slot: str
    role: str
    route_id: str


@dataclass(frozen=True)
class CollaborationWorkerObservation:
    """Adapter observation; the Module validates and converts it to a Record."""

    route_id: str
    role: str
    status: str
    candidate_artifacts: tuple[Mapping[str, Any], ...] = ()
    verified_partial_artifacts: tuple[Mapping[str, Any], ...] = ()
    substantive_method_changes: tuple[Mapping[str, Any], ...] = ()
    opportunity_chain: tuple[Mapping[str, Any], ...] = ()
    future_route_proposal: Mapping[str, Any] | None = None
    cannot_imply: tuple[str, ...] = ()
    reopen_conditions: tuple[str, ...] = ()
    resource_usage: Mapping[str, int] | None = None
    scope_compliance: Mapping[str, bool] | None = None
    failure: Mapping[str, str] | None = None
    work_product: Mapping[str, str] | None = None
    execution: Mapping[str, Any] | None = None


@runtime_checkable
class CollaborationAdapter(Protocol):
    """Provisional adapter seam; a second real implementation is not yet present."""

    @property
    def tool(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def evidence_class(self) -> str: ...

    def execute(self, request: CollaborationWorkerRequest) -> CollaborationWorkerObservation:
        """Return one bounded observation without lifecycle side effects."""


class DeterministicCollaborationAdapter:
    """P7F2 fixed-observation adapter with no process, network, or filesystem I/O."""

    def __init__(
        self,
        observations: Mapping[str, CollaborationWorkerObservation],
    ) -> None:
        self._observations = copy.deepcopy(dict(observations))
        self._requests: list[CollaborationWorkerRequest] = []

    @property
    def tool(self) -> str:
        return "deterministic-collaboration-adapter"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def evidence_class(self) -> str:
        return "synthetic_collaboration_contract"

    @property
    def requests(self) -> tuple[CollaborationWorkerRequest, ...]:
        return tuple(self._requests)

    @property
    def observations(self) -> dict[str, CollaborationWorkerObservation]:
        return copy.deepcopy(self._observations)

    def execute(self, request: CollaborationWorkerRequest) -> CollaborationWorkerObservation:
        self._requests.append(request)
        try:
            observation = self._observations[request.route_id]
        except KeyError as exc:
            raise CollaborationWindowError(
                f"deterministic observation missing for {request.route_id!r}"
            ) from exc
        return copy.deepcopy(observation)


_REAL_ADAPTER_TOOL = "codex-cli-collaboration-adapter"
_REAL_ADAPTER_VERSION = "0.1.0"
_EXECUTION_MODES = {
    "deterministic_fake_launcher": "deterministic_fake_launcher_contract",
    "authenticated_codex_cli": "real_codex_cli",
}
_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
_WORKER_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "route_id",
        "role",
        "status",
        "work_product",
        "substantive_method_changes",
        "opportunity_chain",
        "future_route_proposal",
        "cannot_imply",
        "reopen_conditions",
    ],
    "properties": {
        "route_id": {"type": "string"},
        "role": {"enum": ["explorer_a", "explorer_b", "explorer_c"]},
        "status": {
            "enum": [
                "candidate",
                "verified_partial",
                "bounded_negative",
                "no_new_opportunity",
                "inconclusive",
                "failed",
            ]
        },
        "work_product": {
            "type": "object",
            "required": ["approach", "result", "verification"],
            "properties": {
                "approach": {"type": "string", "minLength": 1, "maxLength": 4096},
                "result": {"type": "string", "minLength": 1, "maxLength": 8192},
                "verification": {"type": "string", "minLength": 1, "maxLength": 4096},
            },
            "additionalProperties": False,
        },
        "substantive_method_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["summary", "rationale"],
                "properties": {
                    "summary": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "opportunity_chain": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "summary", "evidence_sha256", "expected_gain"],
                "properties": {
                    "kind": {
                        "enum": [
                            "substantive_method_change",
                            "new_opportunity",
                            "route_exhausted",
                            "future_route_proposal",
                            "natural_stop",
                        ]
                    },
                    "summary": {"type": "string"},
                    "evidence_sha256": {"type": "string"},
                    "expected_gain": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "future_route_proposal": {
            "type": "object",
            "required": ["present", "proposed_target", "reason", "evidence_sha256"],
            "properties": {
                "present": {"type": "boolean"},
                "proposed_target": {"type": "string"},
                "reason": {"type": "string"},
                "evidence_sha256": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "cannot_imply": {"type": "array", "items": {"type": "string"}},
        "reopen_conditions": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def _collaboration_environment() -> dict[str, str]:
    allowed = {
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "PATH",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed and value}


def _collaboration_trace_facts(
    trace: bytes,
) -> tuple[str | None, bool, dict[str, int], int]:
    session_id: str | None = None
    turn_completed = False
    usage: dict[str, int] = {}
    tool_calls = 0
    for raw_line in trace.splitlines():
        try:
            event = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            session_id = event["thread_id"].strip() or None
        if event.get("type") == "turn.completed":
            turn_completed = True
            raw_usage = event.get("usage")
            if isinstance(raw_usage, dict):
                usage = {
                    key: value
                    for key, value in raw_usage.items()
                    if key
                    in {"input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"}
                    and isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                }
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") in {"command_execution", "mcp_tool_call", "web_search"}
        ):
            tool_calls += 1
    return session_id, turn_completed, usage, tool_calls


def _closed_usage(raw: Mapping[str, int]) -> dict[str, int | bool]:
    required = {"input_tokens", "output_tokens"}
    computed_total = raw.get("input_tokens", -1) + raw.get("output_tokens", -1)
    reported_total = raw.get("total_tokens")
    closed = required.issubset(raw) and (reported_total is None or reported_total == computed_total)
    cached = raw.get("cached_input_tokens", 0)
    if cached > raw.get("input_tokens", -1):
        closed = False
    return {
        "input_tokens": int(raw.get("input_tokens", 0)),
        "cached_input_tokens": int(cached),
        "output_tokens": int(raw.get("output_tokens", 0)),
        "total_tokens": int(computed_total if required.issubset(raw) else 0),
        "usage_closed": bool(closed),
    }


def _worker_payload_is_valid(payload: Mapping[str, Any]) -> bool:
    required = {
        "route_id",
        "role",
        "status",
        "work_product",
        "substantive_method_changes",
        "opportunity_chain",
        "future_route_proposal",
        "cannot_imply",
        "reopen_conditions",
    }
    if set(payload) != required:
        return False
    if not all(isinstance(payload.get(key), str) for key in ("route_id", "role", "status")):
        return False
    if payload["role"] not in _ROLES.values() or payload["status"] not in {
        "candidate",
        "verified_partial",
        "bounded_negative",
        "no_new_opportunity",
        "inconclusive",
        "failed",
    }:
        return False
    work = payload.get("work_product")
    if not isinstance(work, dict) or set(work) != {"approach", "result", "verification"}:
        return False
    work_limits = {"approach": 4096, "result": 8192, "verification": 4096}
    if any(
        not isinstance(value, str) or not value.strip() or len(value) > work_limits[key]
        for key, value in work.items()
    ):
        return False
    for key in (
        "substantive_method_changes",
        "opportunity_chain",
        "cannot_imply",
        "reopen_conditions",
    ):
        if not isinstance(payload.get(key), list):
            return False
    for item in payload["substantive_method_changes"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"summary", "rationale"}
            or any(
                not isinstance(value, str) or not value.strip() or len(value) > 2048
                for value in item.values()
            )
        ):
            return False
    for item in payload["opportunity_chain"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"kind", "summary", "evidence_sha256", "expected_gain"}
            or any(not isinstance(value, str) for value in item.values())
            or item["kind"]
            not in {
                "substantive_method_change",
                "new_opportunity",
                "route_exhausted",
                "future_route_proposal",
                "natural_stop",
            }
            or not item["summary"].strip()
            or len(item["summary"]) > 2048
            or (
                bool(item["evidence_sha256"])
                and (
                    len(item["evidence_sha256"]) != 64
                    or not set(item["evidence_sha256"]).issubset(set("0123456789abcdef"))
                )
            )
        ):
            return False
    future = payload["future_route_proposal"]
    if (
        not isinstance(future, dict)
        or set(future) != {"present", "proposed_target", "reason", "evidence_sha256"}
        or not isinstance(future["present"], bool)
        or any(
            not isinstance(future[key], str)
            for key in ("proposed_target", "reason", "evidence_sha256")
        )
    ):
        return False
    if future["present"] and any(
        not future[key].strip() for key in ("proposed_target", "reason", "evidence_sha256")
    ):
        return False
    if future["present"] and (
        len(future["evidence_sha256"]) != 64
        or not set(future["evidence_sha256"]).issubset(set("0123456789abcdef"))
    ):
        return False
    if not future["present"] and any(
        future[key] for key in ("proposed_target", "reason", "evidence_sha256")
    ):
        return False
    if any(
        not isinstance(item, str) or not item.strip() or len(item) > 2048
        for item in payload["cannot_imply"]
    ):
        return False
    if any(
        not isinstance(item, str) or not item.strip() or len(item) > 2048
        for item in payload["reopen_conditions"]
    ):
        return False
    return True


def _remove_workspace(root: Path) -> bool:
    for attempt in range(8):
        try:
            shutil.rmtree(root)
        except FileNotFoundError:
            return True
        except OSError:
            if not root.exists():
                return True
        else:
            return not root.exists()
        if attempt < 7:
            time.sleep(min(0.05 * (2**attempt), 0.5))
    return not root.exists()


class CodexCliCollaborationAdapter:
    """Run one bounded worker in an owned local process and return sanitized facts."""

    def __init__(
        self,
        launcher: Path,
        *,
        powershell: Path,
        cli_version: str,
        model: str,
        reasoning_effort: str,
        execution_mode: str,
        trace_max_bytes: int = 4 << 20,
    ) -> None:
        launcher = launcher.resolve()
        powershell = powershell.resolve()
        if not launcher.is_file() or launcher.suffix.lower() != ".ps1":
            raise CollaborationWindowError("Codex launcher must be an existing PowerShell file")
        if not powershell.is_file():
            raise CollaborationWindowError("PowerShell executable is unavailable")
        if not cli_version.strip() or not model.strip():
            raise CollaborationWindowError("Codex CLI version and model must be non-empty")
        if reasoning_effort not in _REASONING_EFFORTS:
            raise CollaborationWindowError("unsupported reasoning effort")
        if execution_mode not in _EXECUTION_MODES:
            raise CollaborationWindowError("unsupported collaboration execution mode")
        if execution_mode == "authenticated_codex_cli" and launcher.name.lower() != "codex-cli.ps1":
            raise CollaborationWindowError(
                "authenticated launcher must be the frozen codex-cli.ps1 entry point"
            )
        if isinstance(trace_max_bytes, bool) or trace_max_bytes < 1024:
            raise CollaborationWindowError("trace_max_bytes must be at least 1024")
        self._launcher = launcher
        self._powershell = powershell
        self._cli_version = cli_version
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._execution_mode = execution_mode
        self._trace_max_bytes = trace_max_bytes
        self._launcher_sha256 = hashlib.sha256(launcher.read_bytes()).hexdigest()

    @property
    def tool(self) -> str:
        return _REAL_ADAPTER_TOOL

    @property
    def version(self) -> str:
        return _REAL_ADAPTER_VERSION

    @property
    def evidence_class(self) -> str:
        return _EXECUTION_MODES[self._execution_mode]

    @property
    def metadata(self) -> dict[str, str]:
        return {
            "cli_version": self._cli_version,
            "model": self._model,
            "reasoning_effort": self._reasoning_effort,
            "launcher_sha256": self._launcher_sha256,
        }

    def _command(self, workspace: Path, output_schema: Path, final_output: Path) -> list[str]:
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
            self._model,
            "--color",
            "never",
            "--json",
            "--output-schema",
            str(output_schema),
            "--output-last-message",
            str(final_output),
            "--cd",
            str(workspace),
            "--config",
            'approval_policy="never"',
            "--config",
            'web_search="disabled"',
            "--config",
            f'model_reasoning_effort="{self._reasoning_effort}"',
            "--config",
            'shell_environment_policy.inherit="core"',
            "--config",
            "shell_environment_policy.ignore_default_excludes=false",
            "-",
        ]

    def execute(self, request: CollaborationWorkerRequest) -> CollaborationWorkerObservation:
        root = Path(tempfile.mkdtemp(prefix="p7f3-collaboration-"))
        started = time.monotonic()
        completed = None
        observation: CollaborationWorkerObservation | None = None
        workspace_clean = False
        try:
            output_schema = root / "worker-output.schema.json"
            final_output = root / "worker-output.json"
            request_path = root / "collaboration-request.json"
            output_schema.write_text(json.dumps(_WORKER_OUTPUT_SCHEMA), encoding="utf-8")
            request_path.write_bytes(request.ticket.canonical_bytes)
            prompt = (
                "Solve only the bounded ticket in collaboration-request.json. Choose, combine, "
                "abandon, or replace methods as useful, but preserve its target, evidence, "
                "permissions, and budget. Return only the required structured object."
            )
            timeout = float(request.ticket.data["budget"]["base"]["max_runtime_seconds"])
            completed = run_process_contained(
                self._command(root, output_schema, final_output),
                cwd=root,
                env=_collaboration_environment(),
                input_bytes=prompt.encode("utf-8"),
                timeout_seconds=timeout,
            )
            runtime_seconds = max(0, math.ceil(time.monotonic() - started))
            trace = completed.stdout
            stderr = completed.stderr
            session_id, turn_completed, raw_usage, tool_calls = _collaboration_trace_facts(trace)
            usage = _closed_usage(raw_usage)
            output_bytes = final_output.read_bytes() if final_output.is_file() else b""
            output_sha = hashlib.sha256(output_bytes).hexdigest() if output_bytes else None
            execution: dict[str, Any] = {
                "launcher_process_started": completed.process_started,
                "agent_session_started": session_id is not None,
                "agent_turn_completed": turn_completed,
                "session_sha256": hashlib.sha256((session_id or "").encode()).hexdigest(),
                "trace_sha256": hashlib.sha256(trace).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
                "execution_status": completed.execution_status,
                "process_cleanup_status": completed.process_cleanup_status,
                "process_tree_cleanup_verified": completed.process_tree_cleanup_verified,
                "workspace_cleanup_verified": False,
                "usage": usage,
            }
            failure: dict[str, str] | None = None
            parsed: dict[str, Any] = {}
            if (
                not process_facts_are_valid(
                    completed.execution_status,
                    completed.process_cleanup_status,
                    completed.process_tree_cleanup_verified,
                )
                or completed.execution_status != "completed"
            ):
                failure = {"stage": "adapter_execution", "code": completed.execution_status}
            elif completed.returncode != 0:
                failure = {
                    "stage": "adapter_execution",
                    "code": "launcher_exit_nonzero",
                }
            elif not completed.process_tree_cleanup_verified:
                failure = {
                    "stage": "adapter_execution",
                    "code": "cleanup_failed",
                }
            elif session_id is None or not turn_completed:
                failure = {
                    "stage": "adapter_execution",
                    "code": "session_or_turn_incomplete",
                }
            elif len(trace) > self._trace_max_bytes:
                failure = {"stage": "adapter_execution", "code": "trace_limit_exceeded"}
            elif not usage["usage_closed"]:
                failure = {"stage": "usage_validation", "code": "usage_incomplete_or_inconsistent"}
            elif not output_bytes or len(output_bytes) > int(
                request.ticket.data["budget"]["base"]["max_output_bytes"]
            ):
                failure = {"stage": "output_validation", "code": "output_missing_or_oversized"}
            else:
                try:
                    loaded = json.loads(output_bytes)
                    if not isinstance(loaded, dict):
                        raise ValueError
                    parsed = loaded
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    failure = {"stage": "output_validation", "code": "invalid_structured_output"}
            if not failure and not _worker_payload_is_valid(parsed):
                failure = {"stage": "output_validation", "code": "invalid_structured_output"}
            if not failure and (
                parsed.get("route_id") != request.route_id or parsed.get("role") != request.role
            ):
                failure = {"stage": "output_validation", "code": "ticket_binding_mismatch"}
            if not failure and scan_value_for_restricted(parsed, "worker output"):
                failure = {"stage": "output_validation", "code": "restricted_output"}
            if not failure and parsed.get("status") in {"failed", "inconclusive"}:
                failure = {
                    "stage": "observation_validation",
                    "code": f"worker_reported_{parsed['status']}",
                }
            status = (
                str(parsed.get("status"))
                if failure and failure["stage"] == "observation_validation"
                else "failed"
                if failure
                else str(parsed.get("status"))
            )
            future = parsed.get("future_route_proposal", {}) if not failure else {}
            normalized_opportunities = tuple(
                {
                    key: value
                    for key, value in item.items()
                    if key in {"kind", "summary"} or bool(value)
                }
                for item in (parsed.get("opportunity_chain", ()) if not failure else ())
            )
            future_proposal = (
                {
                    "proposed_target": future["proposed_target"],
                    "reason": future["reason"],
                    "evidence_sha256": future["evidence_sha256"],
                }
                if future.get("present") is True
                else None
            )
            artifact = (
                (
                    {
                        "name": f"outputs/{request.route_id}.json",
                        "sha256": str(output_sha),
                        "size_bytes": len(output_bytes),
                    },
                )
                if not failure
                else ()
            )
            observation = CollaborationWorkerObservation(
                route_id=request.route_id,
                role=request.role,
                status=status,
                candidate_artifacts=artifact if status == "candidate" else (),
                verified_partial_artifacts=artifact if status == "verified_partial" else (),
                substantive_method_changes=tuple(
                    parsed.get("substantive_method_changes", ()) if not failure else ()
                ),
                opportunity_chain=normalized_opportunities,
                future_route_proposal=future_proposal,
                cannot_imply=tuple(parsed.get("cannot_imply", ()) if not failure else ()),
                reopen_conditions=tuple(parsed.get("reopen_conditions", ()) if not failure else ()),
                resource_usage={
                    "runtime_seconds": runtime_seconds,
                    "tool_calls": tool_calls,
                    "output_bytes": len(output_bytes),
                    "extra_budget_extensions": 0,
                },
                scope_compliance={
                    "target_unchanged": True,
                    "claim_scope_unchanged": True,
                    "evidence_standard_preserved": True,
                    "permissions_respected": True,
                },
                failure=failure,
                work_product=parsed.get("work_product") if not failure else None,
                execution=execution,
            )
        finally:
            workspace_clean = _remove_workspace(root)
            if completed is not None and "execution" in locals():
                execution["workspace_cleanup_verified"] = workspace_clean
        if observation is None:
            raise CollaborationWindowError("adapter produced no observation")
        if not workspace_clean:
            primary_failure = observation.failure
            observation = replace(
                observation,
                status="failed",
                candidate_artifacts=(),
                verified_partial_artifacts=(),
                substantive_method_changes=(),
                opportunity_chain=(),
                cannot_imply=(),
                reopen_conditions=(),
                failure=primary_failure
                or {
                    "stage": "workspace_cleanup",
                    "code": "workspace_cleanup_failed",
                },
                work_product=None,
            )
        return observation


@dataclass(frozen=True)
class CollaborationWindowOutcome:
    """Non-authoritative aggregate over validated plan, tickets, and outcomes."""

    status: str
    blockers: tuple[str, ...]
    plan_record: Record
    ticket_records: tuple[Record, ...]
    worker_outcomes: tuple[Record, ...]
    limitations: tuple[str, ...] = _LIMITATIONS

    @property
    def claims(self) -> dict[str, bool]:
        claims = dict(_CLAIMS)
        claims["synthetic_collaboration_contract_exercised"] = any(
            record.data["claims"]["synthetic_collaboration_contract_exercised"]
            for record in self.worker_outcomes
        )
        claims["real_multi_agent_execution_observed"] = bool(self.worker_outcomes) and all(
            record.data["claims"]["real_multi_agent_execution_observed"]
            for record in self.worker_outcomes
        )
        claims["method_autonomy_contract_exercised"] = any(
            record.data["substantive_method_changes"] for record in self.worker_outcomes
        )
        return claims


def _record(payload: Mapping[str, Any], label: str) -> Record:
    restricted = scan_value_for_restricted(payload, label)
    if restricted:
        raise CollaborationWindowError(
            f"{label} contains restricted content: " + "; ".join(restricted)
        )
    try:
        return load_record(canonical_bytes(dict(payload)))
    except (CoreError, TypeError, ValueError) as exc:
        raise CollaborationWindowError(f"invalid {label}: {exc}") from exc


def _sum_budget(routes: list[dict[str, Any]], field: str) -> int:
    return sum(
        int(route[part][field]) for route in routes for part in ("base_budget", "extension_reserve")
    )


def _build_plan(plan: CollaborationWindowPlan) -> tuple[Record, list[dict[str, Any]]]:
    if not isinstance(plan.task, Record) or plan.task.schema_id != "research-task/v1":
        raise CollaborationWindowError("task must be a validated research-task/v1 Record")
    routes = [copy.deepcopy(dict(route)) for route in plan.routes]
    input_artifacts = [copy.deepcopy(dict(item)) for item in plan.input_artifacts]
    slots = [route.get("slot") for route in routes]
    if sorted(str(slot) for slot in slots) != list(_SLOTS) or len(set(slots)) != 3:
        raise CollaborationWindowError("routes must contain slots A, B, and C exactly once")
    payload = {
        "schema": _PLAN_SCHEMA,
        "collaboration_window_plan_id": plan.collaboration_window_plan_id,
        "task": {"task_id": plan.task.data["task_id"], "sha256": plan.task.sha256},
        "active_target": plan.active_target,
        "semantic_scope": {
            "claim_scope": plan.claim_scope,
            "completion_standard": plan.completion_standard,
            "evidence_standard": plan.evidence_standard,
            "forbidden_expansions": list(plan.forbidden_expansions),
        },
        "input_artifacts": input_artifacts,
        "routes": routes,
        "policy": {
            "allowed_tools": list(plan.allowed_tools),
            "network_access": "disabled",
            "filesystem_write_scope": "isolated_staging_only",
            "allowed_external_effects": [],
            "child_cap": 3,
            "max_extra_budget_extensions": 1,
            "hard_budget": dict(plan.hard_budget),
        },
        "created_at": plan.created_at,
        "limitations": list(_LIMITATIONS),
    }
    record = _record(payload, "collaboration window plan")
    route_ids = [route["route_id"] for route in routes]
    if len(route_ids) != len(set(route_ids)):
        raise CollaborationWindowError("route identifiers must be unique")
    hedge_count = sum(route["route_class"] == "hedge" for route in routes)
    if hedge_count > 1:
        raise CollaborationWindowError("a collaboration window permits at most one hedge")
    if sum(route["route_class"] in {"direct", "enabling"} for route in routes) < 2:
        raise CollaborationWindowError("at least two routes must be direct or enabling")
    if len(set(plan.allowed_tools)) != len(plan.allowed_tools):
        raise CollaborationWindowError("allowed tools must be unique")
    artifact_names = [item["name"] for item in input_artifacts]
    if len(artifact_names) != len(set(artifact_names)):
        raise CollaborationWindowError("input artifact names must be unique")
    for field in _BUDGET_FIELDS:
        if _sum_budget(routes, field) > int(plan.hard_budget[field]):
            raise CollaborationWindowError(
                f"route base plus reserve exceeds hard budget for {field}"
            )
    return record, sorted(routes, key=lambda item: _SLOTS.index(item["slot"]))


def _build_ticket(
    plan: CollaborationWindowPlan,
    plan_record: Record,
    route: Mapping[str, Any],
) -> Record:
    slot = str(route["slot"])
    payload = {
        "schema": _TICKET_SCHEMA,
        "collaboration_ticket_id": (
            f"collaboration-ticket-{plan.collaboration_window_plan_id.removeprefix('collaboration-window-')}-{slot}"
        ),
        "window": {
            "collaboration_window_plan_id": plan.collaboration_window_plan_id,
            "sha256": plan_record.sha256,
        },
        "task": {"task_id": plan.task.data["task_id"], "sha256": plan.task.sha256},
        "route_id": route["route_id"],
        "slot": slot,
        "role": _ROLES[slot],
        "bounded_question": route["bounded_question"],
        "semantic_scope": {
            "active_target": plan.active_target,
            "claim_scope": plan.claim_scope,
            "completion_standard": plan.completion_standard,
            "evidence_standard": plan.evidence_standard,
            "forbidden_expansions": list(plan.forbidden_expansions),
        },
        "input_artifacts": [copy.deepcopy(dict(item)) for item in plan.input_artifacts],
        "allowed_tools": list(plan.allowed_tools),
        "writable_staging": f"{plan.writable_staging}/{slot.lower()}",
        "budget": {
            "base": copy.deepcopy(route["base_budget"]),
            "extension_reserve": copy.deepcopy(route["extension_reserve"]),
            "max_extra_budget_extensions": 1,
        },
        "stop_conditions": {
            "success": route["success_signal"],
            "bounded_negative": route["bounded_negative_signal"],
            "no_new_opportunity": route["no_new_opportunity_signal"],
        },
        "required_outputs": list(_REQUIRED_OUTPUTS),
        "autonomy": dict(_AUTONOMY),
        "generated_at": plan.created_at,
        "limitations": list(_LIMITATIONS),
    }
    ticket = _record(payload, f"collaboration ticket {slot}")
    if set(ticket.data["required_outputs"]) != set(_REQUIRED_OUTPUTS):
        raise CollaborationWindowError("ticket required output set is incomplete")
    return ticket


def _validate_observation(
    request: CollaborationWorkerRequest,
    observation: CollaborationWorkerObservation,
) -> CollaborationWorkerObservation:
    if observation.route_id != request.route_id or observation.role != request.role:
        raise CollaborationWindowError("observation route or neutral role does not match ticket")
    if observation.resource_usage is None or observation.scope_compliance is None:
        raise CollaborationWindowError("observation must report resource and scope compliance")

    scope_ok = all(observation.scope_compliance.values()) and set(observation.scope_compliance) == {
        "target_unchanged",
        "claim_scope_unchanged",
        "evidence_standard_preserved",
        "permissions_respected",
    }
    if not scope_ok:
        return replace(
            observation,
            status="failed",
            candidate_artifacts=(),
            verified_partial_artifacts=(),
            failure={"stage": "scope_validation", "code": "scope_violation"},
        )

    ticket_budget = request.ticket.data["budget"]
    extensions = observation.resource_usage.get("extra_budget_extensions")
    if extensions not in (0, 1):
        raise CollaborationWindowError("extra budget extensions must be zero or one")
    if extensions == 1:
        opportunities = [
            item
            for item in observation.opportunity_chain
            if item.get("kind") == "new_opportunity"
            and item.get("evidence_sha256")
            and item.get("expected_gain")
        ]
        if len(opportunities) != 1:
            raise CollaborationWindowError(
                "one extension requires exactly one evidence-backed new opportunity"
            )
    for budget_field, usage_field in _USAGE_FIELDS.items():
        limit = int(ticket_budget["base"][budget_field])
        if extensions == 1:
            limit += int(ticket_budget["extension_reserve"][budget_field])
        if int(observation.resource_usage.get(usage_field, -1)) > limit:
            raise CollaborationWindowError(
                f"resource usage exceeds ticket budget for {usage_field}"
            )

    if observation.status == "candidate" and not observation.candidate_artifacts:
        raise CollaborationWindowError("candidate status requires a candidate artifact")
    if observation.status == "verified_partial" and not observation.verified_partial_artifacts:
        raise CollaborationWindowError("verified_partial status requires a partial artifact")
    if observation.status == "bounded_negative" and (
        not observation.cannot_imply or not observation.reopen_conditions
    ):
        raise CollaborationWindowError(
            "bounded_negative status requires cannot_imply and reopen_conditions"
        )
    if observation.status in {"failed", "inconclusive"} and observation.failure is None:
        raise CollaborationWindowError("failed or inconclusive status requires failure metadata")
    if observation.status not in {"failed", "inconclusive"} and observation.failure is not None:
        raise CollaborationWindowError("successful observations cannot carry failure metadata")

    future_events = [
        item
        for item in observation.opportunity_chain
        if item.get("kind") == "future_route_proposal"
    ]
    if bool(future_events) != (observation.future_route_proposal is not None):
        raise CollaborationWindowError(
            "future route proposal must have exactly one matching opportunity event"
        )
    if observation.future_route_proposal is not None:
        event_evidence = future_events[0].get("evidence_sha256") if future_events else None
        proposal_evidence = observation.future_route_proposal.get("evidence_sha256")
        if len(future_events) != 1 or event_evidence != proposal_evidence:
            raise CollaborationWindowError(
                "future route proposal evidence does not match its event"
            )
    return observation


def _build_outcome(
    request: CollaborationWorkerRequest,
    observation: CollaborationWorkerObservation,
    *,
    generated_at: str,
    adapter: CollaborationAdapter,
) -> Record:
    is_process_adapter = adapter.tool == _REAL_ADAPTER_TOOL
    schema = _OUTCOME_SCHEMA_V2 if is_process_adapter else _OUTCOME_SCHEMA
    claims = dict(_CLAIMS)
    claims["synthetic_collaboration_contract_exercised"] = (
        not is_process_adapter or adapter.evidence_class == "deterministic_fake_launcher_contract"
    )
    if is_process_adapter:
        execution = dict(observation.execution or {})
        claims["real_multi_agent_execution_observed"] = bool(
            adapter.evidence_class == "real_codex_cli"
            and execution.get("launcher_process_started")
            and execution.get("agent_session_started")
            and execution.get("agent_turn_completed")
            and execution.get("process_tree_cleanup_verified")
            and execution.get("workspace_cleanup_verified")
            and dict(execution.get("usage", {})).get("usage_closed")
            and observation.failure is None
        )
    payload: dict[str, Any] = {
        "schema": schema,
        "collaboration_worker_outcome_id": (
            f"collaboration-outcome-{request.ticket.data['collaboration_ticket_id'].removeprefix('collaboration-ticket-')}"
        ),
        "ticket": {
            "collaboration_ticket_id": request.ticket.data["collaboration_ticket_id"],
            "sha256": request.ticket.sha256,
        },
        "route_id": observation.route_id,
        "role": observation.role,
        "status": observation.status,
        "candidate_artifacts": [
            copy.deepcopy(dict(item)) for item in observation.candidate_artifacts
        ],
        "verified_partial_artifacts": [
            copy.deepcopy(dict(item)) for item in observation.verified_partial_artifacts
        ],
        "substantive_method_changes": [
            copy.deepcopy(dict(item)) for item in observation.substantive_method_changes
        ],
        "opportunity_chain": [copy.deepcopy(dict(item)) for item in observation.opportunity_chain],
        "cannot_imply": list(observation.cannot_imply),
        "reopen_conditions": list(observation.reopen_conditions),
        "resource_usage": dict(observation.resource_usage or {}),
        "scope_compliance": dict(observation.scope_compliance or {}),
        "adapter": {
            "tool": adapter.tool,
            "version": adapter.version,
            "evidence_class": adapter.evidence_class,
        },
        "claims": claims,
        "generated_at": generated_at,
        "limitations": list(_PROCESS_LIMITATIONS if is_process_adapter else _LIMITATIONS),
    }
    if observation.future_route_proposal is not None:
        payload["future_route_proposal"] = copy.deepcopy(dict(observation.future_route_proposal))
    if observation.failure is not None:
        payload["failure"] = dict(observation.failure)
    if is_process_adapter:
        if observation.work_product is not None:
            payload["work_product"] = dict(observation.work_product)
        payload["execution"] = copy.deepcopy(dict(observation.execution or {}))
        metadata = getattr(adapter, "metadata", {})
        payload["adapter"].update(dict(metadata))
    return _record(payload, f"collaboration worker outcome {request.slot}")


def run_collaboration_window(
    plan: CollaborationWindowPlan,
    adapter: CollaborationAdapter,
) -> CollaborationWindowOutcome:
    """Validate, derive, and run one synthetic three-slot collaboration window."""

    if not isinstance(adapter, CollaborationAdapter):
        raise CollaborationWindowError("adapter does not implement CollaborationAdapter")
    identities = {
        (
            "deterministic-collaboration-adapter",
            "1.0.0",
            "synthetic_collaboration_contract",
        ),
        (
            _REAL_ADAPTER_TOOL,
            _REAL_ADAPTER_VERSION,
            "deterministic_fake_launcher_contract",
        ),
        (_REAL_ADAPTER_TOOL, _REAL_ADAPTER_VERSION, "real_codex_cli"),
    }
    if (adapter.tool, adapter.version, adapter.evidence_class) not in identities:
        raise CollaborationWindowError("unsupported collaboration adapter identity")

    plan_record, routes = _build_plan(plan)
    tickets = tuple(_build_ticket(plan, plan_record, route) for route in routes)
    requests = tuple(
        CollaborationWorkerRequest(
            ticket=ticket,
            slot=ticket.data["slot"],
            role=ticket.data["role"],
            route_id=ticket.data["route_id"],
        )
        for ticket in tickets
    )

    outcomes: list[Record] = []
    blockers: list[str] = []
    for request in requests:
        try:
            raw_observation = adapter.execute(request)
        except CollaborationWindowError:
            raise
        except Exception as exc:
            raise CollaborationWindowError(
                f"adapter execution failed for {request.route_id!r}: {type(exc).__name__}"
            ) from exc
        observation = _validate_observation(request, raw_observation)
        outcome = _build_outcome(
            request,
            observation,
            generated_at=plan.created_at,
            adapter=adapter,
        )
        outcomes.append(outcome)
        if observation.failure is not None:
            blockers.append(f"{request.route_id}:{observation.failure['code']}")
            break

    return CollaborationWindowOutcome(
        status="failed_closed" if blockers else "window_completed",
        blockers=tuple(blockers),
        plan_record=plan_record,
        ticket_records=tickets,
        worker_outcomes=tuple(outcomes),
        limitations=_PROCESS_LIMITATIONS if adapter.tool == _REAL_ADAPTER_TOOL else _LIMITATIONS,
    )
