"""Behavioral tests for the M5 heuristic registry."""

import unittest

from research_evolution.core import canonical_sha256
from research_evolution.experience import (
    HeuristicIndex,
    build_heuristic_index,
    heuristic_chain,
    propose_heuristic,
    transition_heuristic,
)
from tests.unit.test_experience_cases import _run
from tests.unit.test_experience_patterns import _make_case


def _propose(heuristic_id: str = "h-1", **overrides) -> dict:
    kwargs = {
        "heuristic_id": heuristic_id,
        "statement": "Validate the inputs before training",
        "scope": "ingest",
        "mode": "advisory",
        "evidence": ["synthetic observation"],
        "risk": "bad rows poison the run",
        "rollback": "restore the previous snapshot and re-run validation",
        "transition_rationale": "initial hypothesis",
        "regression_cases": [_make_case("case-h-reg")],
        "created_at": "2026-08-17T10:00:00Z",
    }
    kwargs.update(overrides)
    return propose_heuristic(**kwargs)


def _advance(payload: dict, new_id: str, status: str, **overrides) -> dict:
    kwargs = {
        "heuristic": payload,
        "new_heuristic_id": new_id,
        "status": status,
        "transition_rationale": f"move to {status}",
        "created_at": "2026-08-17T11:00:00Z",
    }
    kwargs.update(overrides)
    return transition_heuristic(**kwargs)


def _shadow(heuristic_id: str = "h-1") -> dict:
    candidate = _advance(_propose(heuristic_id), heuristic_id + "-cand", "candidate")
    return _advance(
        candidate,
        heuristic_id + "-sh",
        "shadow",
        created_at="2026-08-17T12:00:00Z",
    )


class ProposeHeuristicTest(unittest.TestCase):
    def test_happy_path_pins_regression_cases(self) -> None:
        case = _make_case("case-h-reg")
        payload = _propose(regression_cases=[case])
        self.assertEqual(payload["schema"], "heuristic/v1")
        self.assertEqual(payload["status"], "lesson_hypothesis")
        self.assertEqual(payload["exception"], [])
        self.assertNotIn("supersedes", payload)
        self.assertEqual(
            payload["regression_cases"],
            [{"case_id": "case-h-reg", "sha256": canonical_sha256(case)}],
        )

    def test_deterministic_across_calls(self) -> None:
        self.assertEqual(canonical_sha256(_propose()), canonical_sha256(_propose()))

    def test_regression_case_must_be_case_family(self) -> None:
        with self.assertRaisesRegex(ValueError, "declares"):
            _propose(regression_cases=[_run()])

    def test_regression_cases_must_be_distinct(self) -> None:
        case = _make_case("case-h-reg")
        with self.assertRaisesRegex(ValueError, "distinct"):
            _propose(regression_cases=[case, case])

    def test_regression_cases_min_one_via_self_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "assembled heuristic payload"):
            _propose(regression_cases=[])

    def test_ineligible_case_is_still_a_valid_regression_pin(self) -> None:
        # The eligibility gate guards pattern distillation, not heuristic
        # regression pins: a regression case is evidence of a failure mode,
        # not shareable-pattern source material (design point, M5 ledger 6).
        case = _make_case("case-h-inel", eligible=False)
        payload = _propose(regression_cases=[case])
        self.assertEqual(payload["regression_cases"][0]["case_id"], "case-h-inel")

    def test_free_text_is_scanned(self) -> None:
        with self.assertRaisesRegex(ValueError, "restricted content"):
            _propose(statement="saved to C:/evil/statement")
        with self.assertRaisesRegex(ValueError, "restricted content"):
            _propose(evidence=["read /etc/passwd first"])
        with self.assertRaisesRegex(ValueError, "restricted content"):
            _propose(rollback="undo ~/stuff")

    def test_assembled_payload_is_self_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "assembled heuristic payload"):
            _propose(mode="bogus-mode")


class TransitionHeuristicTest(unittest.TestCase):
    def test_forward_axis_lesson_candidate_shadow(self) -> None:
        root = _propose("h-1")
        candidate = _advance(root, "h-1b", "candidate", statement="Sharper statement")
        self.assertEqual(candidate["supersedes"], "h-1")
        self.assertEqual(candidate["status"], "candidate")
        self.assertEqual(candidate["statement"], "Sharper statement")
        self.assertEqual(candidate["scope"], root["scope"])
        self.assertEqual(candidate["regression_cases"], root["regression_cases"])
        shadow = _advance(candidate, "h-1c", "shadow")
        self.assertEqual(shadow["supersedes"], "h-1b")
        self.assertEqual(shadow["status"], "shadow")

    def test_phase4_ceiling_refuses_later_vocabulary(self) -> None:
        root = _propose("h-1")
        for status in ("validated", "promoted", "deprecated", "retired"):
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "Phase 4 ceiling"):
                    _advance(root, "h-1b", status)

    def test_rejected_is_reachable_sideways_and_terminal(self) -> None:
        root = _propose("h-1")
        rejected = _advance(root, "h-1b", "rejected")
        self.assertEqual(rejected["status"], "rejected")
        with self.assertRaisesRegex(ValueError, "terminal"):
            _advance(rejected, "h-1c", "candidate")

    def test_backward_and_same_state_moves_refused(self) -> None:
        root = _propose("h-1")
        candidate = _advance(root, "h-1b", "candidate")
        with self.assertRaisesRegex(ValueError, "strictly forward"):
            _advance(candidate, "h-1c", "lesson_hypothesis")
        with self.assertRaisesRegex(ValueError, "strictly forward"):
            _advance(candidate, "h-1c", "candidate")

    def test_successor_id_must_differ(self) -> None:
        root = _propose("h-1")
        with self.assertRaisesRegex(ValueError, "equals the predecessor id"):
            _advance(root, "h-1", "candidate")

    def test_unknown_status_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown heuristic status"):
            _advance(_propose("h-1"), "h-1b", "weird")

    def test_predecessor_beyond_ceiling_cannot_extend(self) -> None:
        root = dict(_propose("h-1"), status="validated")
        with self.assertRaisesRegex(ValueError, "unreachable in Phase 4"):
            _advance(root, "h-1b", "candidate")

    def test_override_text_is_scanned(self) -> None:
        with self.assertRaisesRegex(ValueError, "restricted content"):
            _advance(_propose("h-1"), "h-1b", "candidate", rollback="wipe C:/evil")

    def test_regression_cases_can_be_repinned(self) -> None:
        root = _propose("h-1")
        new_case = _make_case("case-h-new")
        candidate = _advance(root, "h-1b", "candidate", regression_cases=[new_case])
        self.assertEqual(
            candidate["regression_cases"],
            [{"case_id": "case-h-new", "sha256": canonical_sha256(new_case)}],
        )

    def test_predecessor_must_be_heuristic_family(self) -> None:
        with self.assertRaisesRegex(ValueError, "declares"):
            _advance(_run(), "h-1b", "candidate")


class HeuristicIndexTest(unittest.TestCase):
    def test_tips_and_deterministic_hash(self) -> None:
        root = _propose("h-1")
        successor = _advance(root, "h-1b", "candidate")
        other = _propose("h-2")
        index = build_heuristic_index([root, successor, other])
        self.assertEqual(index.tips, ("h-1b", "h-2"))
        reversed_index = build_heuristic_index([other, successor, root])
        self.assertEqual(index.sha256, reversed_index.sha256)
        self.assertEqual(
            [data["heuristic_id"] for data in index.records],
            ["h-1", "h-1b", "h-2"],
        )

    def test_fork_surfaces_as_two_tips(self) -> None:
        root = _propose("h-1")
        left = _advance(root, "h-1b", "candidate")
        right = _advance(root, "h-1c", "candidate")
        index = build_heuristic_index([root, left, right])
        self.assertEqual(index.tips, ("h-1b", "h-1c"))

    def test_duplicate_id_in_input_refused(self) -> None:
        root = _propose("h-1")
        with self.assertRaisesRegex(ValueError, "duplicate heuristic_id"):
            build_heuristic_index([root, root])

    def test_members_must_be_heuristic_family(self) -> None:
        with self.assertRaisesRegex(ValueError, "declares"):
            build_heuristic_index([_run()])

    def test_chain_walks_tip_to_root(self) -> None:
        shadow = _shadow("h-1")
        index = build_heuristic_index([
            _propose("h-1"),
            _advance(_propose("h-1"), "h-1-cand", "candidate"),
            shadow,
        ])
        chain = heuristic_chain(index, "h-1-sh")
        self.assertEqual(
            [data["heuristic_id"] for data in chain],
            ["h-1-sh", "h-1-cand", "h-1"],
        )

    def test_chain_fails_closed_on_missing_predecessor(self) -> None:
        shadow = _shadow("h-1")
        index = build_heuristic_index([shadow])
        with self.assertRaisesRegex(ValueError, "predecessor"):
            heuristic_chain(index, "h-1-sh")

    def test_chain_unknown_tip_refused(self) -> None:
        index = build_heuristic_index([_propose("h-1")])
        with self.assertRaisesRegex(ValueError, "not in the index"):
            heuristic_chain(index, "h-nope")

    def test_chain_requires_index_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "HeuristicIndex"):
            heuristic_chain({"records": ()}, "h-1")


if __name__ == "__main__":
    unittest.main()
