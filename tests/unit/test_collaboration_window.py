"""P7F collaboration-window autonomy contracts."""

from __future__ import annotations

import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from research_evolution.core import (
    PublicationError,
    canonical_bytes,
    load_record,
    publish_record,
    verify_record_graph,
)
from research_evolution.evolution import (
    CollaborationWindowError,
    CollaborationWindowPlan,
    CollaborationWorkerObservation,
    DeterministicCollaborationAdapter,
    run_collaboration_window,
)


NOW = "2026-09-04T02:00:00Z"


def _task(domain: str = "math") -> Any:
    return load_record(
        canonical_bytes(
            {
                "schema": "research-task/v1",
                "task_id": f"p7f-{domain}-task",
                "title": f"Synthetic {domain} collaboration contract",
                "problem_statement": "Exercise a bounded collaboration window.",
                "domain": domain,
                "scope": {"fixture": "synthetic"},
                "resources": {"compute": "deterministic-in-process"},
                "completion_criteria": ["Return contract-valid worker outcomes."],
                "permissions": ["read:synthetic"],
                "allowed_external_effects": [],
                "created_at": NOW,
            }
        )
    )


def _routes() -> tuple[dict[str, Any], ...]:
    return (
        {
            "route_id": "route-a",
            "slot": "A",
            "route_class": "direct",
            "bounded_question": "Can the primary invariant close the target?",
            "intended_contribution": "A candidate argument or bounded negative result.",
            "targeted_bottleneck": "Primary invariant",
            "why_high_value_now": "It directly addresses the active target.",
            "rerank_condition": "A stronger invariant becomes available.",
            "success_signal": "A checkable candidate artifact is produced.",
            "bounded_negative_signal": "The invariant fails on a frozen witness.",
            "no_new_opportunity_signal": "No stronger invariant is identified.",
            "base_budget": {
                "max_runtime_seconds": 30,
                "max_tool_calls": 3,
                "max_output_bytes": 4096,
            },
            "extension_reserve": {
                "max_runtime_seconds": 10,
                "max_tool_calls": 1,
                "max_output_bytes": 1024,
            },
        },
        {
            "route_id": "route-b",
            "slot": "B",
            "route_class": "enabling",
            "bounded_question": "Can an auxiliary representation expose structure?",
            "intended_contribution": "A verified partial artifact.",
            "targeted_bottleneck": "Representation gap",
            "why_high_value_now": "It may unlock the direct route.",
            "rerank_condition": "The representation proves irrelevant.",
            "success_signal": "A reusable intermediate artifact is produced.",
            "bounded_negative_signal": "The representation loses required information.",
            "no_new_opportunity_signal": "No alternate representation is identified.",
            "base_budget": {
                "max_runtime_seconds": 30,
                "max_tool_calls": 3,
                "max_output_bytes": 4096,
            },
            "extension_reserve": {
                "max_runtime_seconds": 10,
                "max_tool_calls": 1,
                "max_output_bytes": 1024,
            },
        },
        {
            "route_id": "route-c",
            "slot": "C",
            "route_class": "hedge",
            "bounded_question": "Can a disjoint sanity route falsify assumptions?",
            "intended_contribution": "A bounded diagnostic.",
            "targeted_bottleneck": "Assumption risk",
            "why_high_value_now": "It protects against a shared blind spot.",
            "rerank_condition": "A direct contradiction is found.",
            "success_signal": "A checkable diagnostic is produced.",
            "bounded_negative_signal": "The diagnostic route is exhausted.",
            "no_new_opportunity_signal": "No additional diagnostic is justified.",
            "base_budget": {
                "max_runtime_seconds": 20,
                "max_tool_calls": 2,
                "max_output_bytes": 2048,
            },
            "extension_reserve": {
                "max_runtime_seconds": 5,
                "max_tool_calls": 1,
                "max_output_bytes": 512,
            },
        },
    )


def _plan(domain: str = "math") -> CollaborationWindowPlan:
    return CollaborationWindowPlan(
        collaboration_window_plan_id=f"collaboration-window-{domain}-001",
        task=_task(domain),
        active_target="Resolve the frozen synthetic target without changing its scope.",
        claim_scope="Only the frozen synthetic target.",
        completion_standard="Produce a checkable artifact or an explicit bounded negative.",
        evidence_standard="Only named hash-bound synthetic artifacts count as evidence.",
        forbidden_expansions=("new target", "weaker evidence"),
        input_artifacts=(
            {
                "name": f"inputs/{domain}-fixture.json",
                "sha256": "1" * 64,
                "size_bytes": 64,
            },
        ),
        routes=_routes(),
        allowed_tools=("deterministic-lookup",),
        writable_staging="staging/p7f",
        hard_budget={
            "max_runtime_seconds": 105,
            "max_tool_calls": 11,
            "max_output_bytes": 13824,
        },
        created_at=NOW,
    )


def _observation(route_id: str, role: str) -> CollaborationWorkerObservation:
    return CollaborationWorkerObservation(
        route_id=route_id,
        role=role,
        status="candidate",
        candidate_artifacts=(
            {
                "name": f"outputs/{route_id}.json",
                "sha256": "2" * 64,
                "size_bytes": 32,
            },
        ),
        substantive_method_changes=(
            {
                "summary": "Replaced the initial tactic with an equivalent method.",
                "rationale": "The replacement stays inside the frozen target and envelope.",
            },
        ),
        opportunity_chain=(),
        future_route_proposal=None,
        cannot_imply=(),
        reopen_conditions=(),
        resource_usage={
            "runtime_seconds": 4,
            "tool_calls": 1,
            "output_bytes": 512,
            "extra_budget_extensions": 0,
        },
        scope_compliance={
            "target_unchanged": True,
            "claim_scope_unchanged": True,
            "evidence_standard_preserved": True,
            "permissions_respected": True,
        },
        failure=None,
    )


def _adapter() -> DeterministicCollaborationAdapter:
    return DeterministicCollaborationAdapter(
        {
            "route-a": _observation("route-a", "explorer_a"),
            "route-b": replace(
                _observation("route-b", "explorer_b"),
                status="verified_partial",
                candidate_artifacts=(),
                verified_partial_artifacts=(
                    {
                        "name": "outputs/route-b-partial.json",
                        "sha256": "3" * 64,
                        "size_bytes": 24,
                    },
                ),
            ),
            "route-c": replace(
                _observation("route-c", "explorer_c"),
                status="bounded_negative",
                candidate_artifacts=(),
                cannot_imply=("No global conclusion follows from this route.",),
                reopen_conditions=("Reopen only if the frozen assumption changes.",),
            ),
        }
    )


class CollaborationWindowTests(unittest.TestCase):
    def test_math_and_quant_cross_one_domain_neutral_three_slot_interface(self) -> None:
        for domain in ("math", "quant"):
            with self.subTest(domain=domain):
                adapter = _adapter()
                outcome = run_collaboration_window(_plan(domain), adapter)

                self.assertEqual(outcome.status, "window_completed")
                self.assertEqual(outcome.blockers, ())
                self.assertEqual([request.slot for request in adapter.requests], ["A", "B", "C"])
                self.assertEqual(
                    [request.role for request in adapter.requests],
                    ["explorer_a", "explorer_b", "explorer_c"],
                )
                self.assertEqual(len(outcome.ticket_records), 3)
                self.assertEqual(len(outcome.worker_outcomes), 3)
                self.assertEqual(
                    outcome.worker_outcomes[0].data["substantive_method_changes"][0][
                        "summary"
                    ],
                    "Replaced the initial tactic with an equivalent method.",
                )
                self.assertTrue(outcome.claims["synthetic_collaboration_contract_exercised"])
                self.assertTrue(outcome.claims["method_autonomy_contract_exercised"])
                for claim in (
                    "real_multi_agent_execution_observed",
                    "real_agent_identity_verified",
                    "collaboration_seam_stable",
                    "independent_verification_completed",
                    "publication_authorized",
                    "installation_authorized",
                    "activation_authorized",
                    "promotion_authorized",
                ):
                    self.assertFalse(outcome.claims[claim])

    def test_two_hedges_fail_before_adapter_execution(self) -> None:
        routes = list(_routes())
        routes[1] = {**routes[1], "route_class": "hedge"}
        adapter = _adapter()
        with self.assertRaisesRegex(CollaborationWindowError, "at most one hedge"):
            run_collaboration_window(replace(_plan(), routes=tuple(routes)), adapter)
        self.assertEqual(adapter.requests, ())

    def test_deleted_slot_and_unknown_tactic_field_fail_preflight(self) -> None:
        adapter = _adapter()
        with self.assertRaisesRegex(CollaborationWindowError, "slots A, B, and C"):
            run_collaboration_window(replace(_plan(), routes=_routes()[:-1]), adapter)
        self.assertEqual(adapter.requests, ())

        routes = [copy.deepcopy(route) for route in _routes()]
        routes[0]["method_family"] = "over-prescribed"
        with self.assertRaisesRegex(CollaborationWindowError, "additional property"):
            run_collaboration_window(replace(_plan(), routes=tuple(routes)), adapter)
        self.assertEqual(adapter.requests, ())

    def test_hard_budget_fails_before_adapter_execution(self) -> None:
        adapter = _adapter()
        with self.assertRaisesRegex(CollaborationWindowError, "hard budget"):
            run_collaboration_window(
                replace(
                    _plan(),
                    hard_budget={
                        "max_runtime_seconds": 104,
                        "max_tool_calls": 11,
                        "max_output_bytes": 13824,
                    },
                ),
                adapter,
            )
        self.assertEqual(adapter.requests, ())

    def test_restricted_plan_is_rejected_without_echoing_matched_value(self) -> None:
        adapter = _adapter()
        sensitive = "operator@example.invalid"
        with self.assertRaises(CollaborationWindowError) as caught:
            run_collaboration_window(replace(_plan(), active_target=sensitive), adapter)
        self.assertIn("email address", str(caught.exception))
        self.assertNotIn(sensitive, str(caught.exception))
        self.assertEqual(adapter.requests, ())

    def test_direct_publication_rechecks_restricted_plan_without_writing(self) -> None:
        plan_payload = run_collaboration_window(_plan(), _adapter()).plan_record.data
        sensitive = "sk-" + "A" * 24
        plan_payload["active_target"] = sensitive
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "store"
            with self.assertRaises(PublicationError) as caught:
                publish_record(canonical_bytes(plan_payload), root=root)
            self.assertFalse(root.exists())
        self.assertIn("restricted content", str(caught.exception))
        self.assertNotIn(sensitive, str(caught.exception))

    def test_deterministic_adapter_copies_inputs_and_observations(self) -> None:
        source = _adapter().observations
        adapter = DeterministicCollaborationAdapter(source)
        source.clear()
        exported = adapter.observations
        exported.clear()

        outcome = run_collaboration_window(_plan(), adapter)
        self.assertEqual(outcome.status, "window_completed")
        self.assertEqual(len(adapter.requests), 3)

    def test_scope_drift_fails_closed_and_stops_later_dispatch(self) -> None:
        drift = replace(
            _observation("route-a", "explorer_a"),
            scope_compliance={
                "target_unchanged": False,
                "claim_scope_unchanged": True,
                "evidence_standard_preserved": True,
                "permissions_respected": True,
            },
        )
        adapter = _adapter()
        adapter = DeterministicCollaborationAdapter(
            {**adapter.observations, "route-a": drift}
        )
        outcome = run_collaboration_window(_plan(), adapter)

        self.assertEqual(outcome.status, "failed_closed")
        self.assertEqual(outcome.blockers, ("route-a:scope_violation",))
        self.assertEqual(len(adapter.requests), 1)
        self.assertEqual(outcome.worker_outcomes[0].data["status"], "failed")
        self.assertEqual(
            outcome.worker_outcomes[0].data["failure"],
            {"stage": "scope_validation", "code": "scope_violation"},
        )

    def test_one_evidence_backed_extension_is_allowed_but_unjustified_is_rejected(self) -> None:
        extended = replace(
            _observation("route-a", "explorer_a"),
            opportunity_chain=(
                {
                    "kind": "new_opportunity",
                    "summary": "A bounded follow-up became checkable.",
                    "evidence_sha256": "4" * 64,
                    "expected_gain": "May close the same active target.",
                },
            ),
            resource_usage={
                "runtime_seconds": 35,
                "tool_calls": 4,
                "output_bytes": 4800,
                "extra_budget_extensions": 1,
            },
        )
        adapter = _adapter()
        outcome = run_collaboration_window(
            _plan(),
            DeterministicCollaborationAdapter(
                {**adapter.observations, "route-a": extended}
            ),
        )
        self.assertEqual(outcome.status, "window_completed")

        unjustified = replace(extended, opportunity_chain=())
        with self.assertRaisesRegex(CollaborationWindowError, "evidence-backed new opportunity"):
            run_collaboration_window(
                _plan(),
                DeterministicCollaborationAdapter(
                    {**adapter.observations, "route-a": unjustified}
                ),
            )

    def test_future_route_proposal_cannot_mutate_active_target(self) -> None:
        proposal = replace(
            _observation("route-a", "explorer_a"),
            opportunity_chain=(
                {
                    "kind": "future_route_proposal",
                    "summary": "A separate target may deserve a later window.",
                    "evidence_sha256": "5" * 64,
                    "expected_gain": "Could inform a later planning decision.",
                },
            ),
            future_route_proposal={
                "proposed_target": "A distinct future target",
                "reason": "The current window cannot authorize target expansion.",
                "evidence_sha256": "5" * 64,
            },
        )
        adapter = _adapter()
        outcome = run_collaboration_window(
            _plan(),
            DeterministicCollaborationAdapter(
                {**adapter.observations, "route-a": proposal}
            ),
        )
        self.assertEqual(
            outcome.plan_record.data["active_target"],
            _plan().active_target,
        )
        self.assertEqual(
            outcome.worker_outcomes[0].data["future_route_proposal"]["proposed_target"],
            "A distinct future target",
        )

    def test_task_window_ticket_outcome_graph_is_fully_resolvable(self) -> None:
        plan = _plan()
        outcome = run_collaboration_window(plan, _adapter())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "store"
            for record in (
                plan.task,
                outcome.plan_record,
                *outcome.ticket_records,
                *outcome.worker_outcomes,
            ):
                publish_record(record.canonical_bytes, root=root)
            report = verify_record_graph(root)

        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 8)

    def test_ticket_window_pin_mismatch_is_detected_by_generic_graph(self) -> None:
        plan = _plan()
        outcome = run_collaboration_window(plan, _adapter())
        bad_ticket = copy.deepcopy(outcome.ticket_records[0].data)
        bad_ticket["window"]["sha256"] = "9" * 64
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "store"
            publish_record(plan.task.canonical_bytes, root=root)
            publish_record(outcome.plan_record.canonical_bytes, root=root)
            publish_record(canonical_bytes(bad_ticket), root=root)
            report = verify_record_graph(root)

        self.assertFalse(report.ok)
        self.assertEqual(
            {violation.kind for violation in report.violations},
            {"pin_mismatch"},
        )


if __name__ == "__main__":
    unittest.main()
