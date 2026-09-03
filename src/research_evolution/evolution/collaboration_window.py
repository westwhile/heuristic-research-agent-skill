"""P7F bounded collaboration with method autonomy and frozen semantics.

``run_collaboration_window`` is the Module's only high-leverage interface.  It
validates the complete three-slot plan and derives every ticket before calling
an adapter.  Workers may choose, combine, abandon, or replace methods inside a
ticket.  They may not change the active target, claim/evidence standard,
permissions, hard resource envelope, or lifecycle authority.

P7F2 deliberately provides only an in-process deterministic adapter.  The seam
therefore remains provisional and supplies synthetic contract evidence only;
it is not real multi-Agent execution, identity verification, independent
review, publication, installation, activation, or promotion evidence.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol, runtime_checkable

from research_evolution.core import CoreError, Record, canonical_bytes, load_record
from research_evolution.core._restricted import scan_value_for_restricted

_PLAN_SCHEMA = "collaboration-window-plan/v1"
_TICKET_SCHEMA = "collaboration-ticket/v1"
_OUTCOME_SCHEMA = "collaboration-worker-outcome/v1"
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
        claims["synthetic_collaboration_contract_exercised"] = bool(
            self.worker_outcomes
        )
        claims["method_autonomy_contract_exercised"] = any(
            record.data["substantive_method_changes"]
            for record in self.worker_outcomes
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
        int(route[part][field])
        for route in routes
        for part in ("base_budget", "extension_reserve")
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

    scope_ok = all(observation.scope_compliance.values()) and set(
        observation.scope_compliance
    ) == {
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
    payload: dict[str, Any] = {
        "schema": _OUTCOME_SCHEMA,
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
            copy.deepcopy(dict(item))
            for item in observation.verified_partial_artifacts
        ],
        "substantive_method_changes": [
            copy.deepcopy(dict(item))
            for item in observation.substantive_method_changes
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
        "claims": dict(_CLAIMS),
        "generated_at": generated_at,
        "limitations": list(_LIMITATIONS),
    }
    if observation.future_route_proposal is not None:
        payload["future_route_proposal"] = copy.deepcopy(
            dict(observation.future_route_proposal)
        )
    if observation.failure is not None:
        payload["failure"] = dict(observation.failure)
    return _record(payload, f"collaboration worker outcome {request.slot}")


def run_collaboration_window(
    plan: CollaborationWindowPlan,
    adapter: CollaborationAdapter,
) -> CollaborationWindowOutcome:
    """Validate, derive, and run one synthetic three-slot collaboration window."""

    if not isinstance(adapter, CollaborationAdapter):
        raise CollaborationWindowError("adapter does not implement CollaborationAdapter")
    if (
        adapter.tool != "deterministic-collaboration-adapter"
        or adapter.version != "1.0.0"
        or adapter.evidence_class != "synthetic_collaboration_contract"
    ):
        raise CollaborationWindowError("P7F2 accepts only the deterministic synthetic adapter")

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
        if observation.failure == {
            "stage": "scope_validation",
            "code": "scope_violation",
        }:
            blockers.append(f"{request.route_id}:scope_violation")
            break

    return CollaborationWindowOutcome(
        status="failed_closed" if blockers else "window_completed",
        blockers=tuple(blockers),
        plan_record=plan_record,
        ticket_records=tickets,
        worker_outcomes=tuple(outcomes),
    )
