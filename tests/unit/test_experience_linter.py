"""Behavioral tests for the M5 deterministic heuristic linter."""

import unittest

from research_evolution.core import canonical_sha256
from research_evolution.experience import (
    assert_no_promoted_skill,
    assert_registry_clean,
    lint_heuristics,
)
from tests.unit.test_experience_cases import _run
from tests.unit.test_experience_heuristics import _advance, _propose
from tests.unit.test_experience_patterns import _two_case_pattern

NOW = "2026-08-17T00:00:00Z"


def _kinds(report):
    return [finding.kind for finding in report.findings]


def _reject_kinds(report):
    return [finding.kind for finding in report.rejections]


class DuplicateLintTest(unittest.TestCase):
    def test_identical_statement_and_scope_across_chains_rejects(self) -> None:
        report = lint_heuristics([_propose("h-1"), _propose("h-2")], now=NOW)
        self.assertIn("duplicate", _reject_kinds(report))
        finding = report.rejections[0]
        self.assertEqual(finding.heuristic_ids, ("h-1", "h-2"))

    def test_same_statement_different_scope_is_not_duplicate(self) -> None:
        report = lint_heuristics(
            [_propose("h-1"), _propose("h-2", scope="scoring")], now=NOW
        )
        self.assertNotIn("duplicate", _kinds(report))

    def test_superseded_versions_are_not_linted(self) -> None:
        old = _propose("h-1")
        tip = _advance(old, "h-1b", "candidate")
        report = lint_heuristics([old, tip, _propose("h-2")], now=NOW)
        duplicates = [f for f in report.findings if f.kind == "duplicate"]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].heuristic_ids, ("h-1b", "h-2"))


class ConflictLintTest(unittest.TestCase):
    def test_negation_asymmetric_pair_same_scope_rejects(self) -> None:
        # Identical content tokens after negation removal; exactly one side
        # negated ("never" is in the frozen negation vocabulary, "always"
        # is a content token, so it must not appear in either statement).
        left = _propose("h-1", statement="Validate the inputs")
        right = _propose("h-2", statement="Never validate the inputs")
        report = lint_heuristics([left, right], now=NOW)
        self.assertIn("conflict", _reject_kinds(report))

    def test_same_scope_different_content_is_not_conflict(self) -> None:
        left = _propose("h-1", statement="Validate the inputs")
        right = _propose("h-2", statement="Record the outputs")
        report = lint_heuristics([left, right], now=NOW)
        self.assertNotIn("conflict", _kinds(report))

    def test_both_negated_is_not_conflict(self) -> None:
        left = _propose("h-1", statement="Never validate the inputs")
        right = _propose("h-2", statement="Do not validate the inputs")
        report = lint_heuristics([left, right], now=NOW)
        self.assertNotIn("conflict", _kinds(report))

    def test_negation_asymmetry_different_scope_is_not_conflict(self) -> None:
        left = _propose("h-1", statement="Validate the inputs")
        right = _propose(
            "h-2", statement="Never validate the inputs", scope="scoring"
        )
        report = lint_heuristics([left, right], now=NOW)
        self.assertNotIn("conflict", _kinds(report))


class PrecedenceCycleLintTest(unittest.TestCase):
    def test_exception_citation_cycle_rejects(self) -> None:
        first = _propose("h-1", exception=["yields to h-2"])
        second = _propose("h-2", exception=["h-1 takes precedence"])
        report = lint_heuristics([first, second], now=NOW)
        self.assertIn("precedence_cycle", _reject_kinds(report))

    def test_acyclic_citation_is_clean(self) -> None:
        first = _propose("h-1", exception=["yields to h-2"])
        second = _propose("h-2", scope="scoring")
        report = lint_heuristics([first, second], now=NOW)
        self.assertNotIn("precedence_cycle", _kinds(report))

    def test_self_citation_is_ignored(self) -> None:
        first = _propose("h-1", exception=["h-1 defers to itself only"])
        report = lint_heuristics([first], now=NOW)
        self.assertNotIn("precedence_cycle", _kinds(report))


class ScopeLintTest(unittest.TestCase):
    def test_dead_scope_is_reported_not_rejected(self) -> None:
        for scope in ("never", "nowhere", "no scope"):
            with self.subTest(scope=scope):
                report = lint_heuristics([_propose("h-1", scope=scope)], now=NOW)
                self.assertIn("dead_rule", _kinds(report))
                self.assertNotIn("dead_rule", _reject_kinds(report))

    def test_universal_scope_blocking_rejects_with_task17_rationale(self) -> None:
        report = lint_heuristics(
            [_propose("h-1", scope="always", mode="blocking")], now=NOW
        )
        self.assertIn("always_triggered", _reject_kinds(report))
        self.assertIn("deterministic global invariant", report.rejections[0].detail)

    def test_universal_scope_advisory_is_reported(self) -> None:
        report = lint_heuristics([_propose("h-1", scope="everywhere")], now=NOW)
        self.assertIn("always_triggered", _kinds(report))
        self.assertNotIn("always_triggered", _reject_kinds(report))

    def test_scoped_rule_is_clean(self) -> None:
        report = lint_heuristics([_propose("h-1")], now=NOW)
        self.assertEqual(report.findings, ())


class VacuousRollbackLintTest(unittest.TestCase):
    def test_frozen_boilerplate_phrases_reject_on_blocking(self) -> None:
        for rollback in ("just revert", "n/a", "revert", "trivial"):
            with self.subTest(rollback=rollback):
                report = lint_heuristics(
                    [_propose("h-1", mode="blocking", rollback=rollback)], now=NOW
                )
                self.assertIn("vacuous_rollback", _reject_kinds(report))

    def test_rollback_copying_statement_rejects(self) -> None:
        statement = "Validate the inputs before training"
        report = lint_heuristics(
            [_propose("h-1", mode="blocking", rollback=statement)], now=NOW
        )
        self.assertIn("vacuous_rollback", _reject_kinds(report))

    def test_too_few_content_tokens_rejects(self) -> None:
        report = lint_heuristics(
            [_propose("h-1", mode="blocking", rollback="revert this")], now=NOW
        )
        self.assertIn("vacuous_rollback", _reject_kinds(report))

    def test_vacuous_rollback_on_advisory_is_reported(self) -> None:
        report = lint_heuristics([_propose("h-1", rollback="revert")], now=NOW)
        self.assertIn("vacuous_rollback", _kinds(report))
        self.assertNotIn("vacuous_rollback", _reject_kinds(report))

    def test_substantive_rollback_is_clean(self) -> None:
        report = lint_heuristics([_propose("h-1", mode="blocking")], now=NOW)
        self.assertEqual(report.findings, ())


class ReportLintTest(unittest.TestCase):
    def test_complexity_budget_over_token_limit(self) -> None:
        statement = " ".join(f"token{i}" for i in range(201))
        report = lint_heuristics([_propose("h-1", statement=statement)], now=NOW)
        self.assertIn("complexity_budget", _kinds(report))
        self.assertNotIn("complexity_budget", _reject_kinds(report))

    def test_compression_candidate_on_high_overlap(self) -> None:
        # 4 shared tokens out of a 5-token union: jaccard exactly 0.8.
        left = _propose("h-1", statement="validate model inputs carefully always")
        right = _propose("h-2", statement="validate model inputs carefully")
        report = lint_heuristics([left, right], now=NOW)
        self.assertIn("compression_candidate", _kinds(report))

    def test_no_compression_candidate_on_low_overlap(self) -> None:
        report = lint_heuristics(
            [
                _propose("h-1"),
                _propose(
                    "h-2",
                    statement="Record the outputs after scoring",
                    scope="scoring",
                ),
            ],
            now=NOW,
        )
        self.assertNotIn("compression_candidate", _kinds(report))

    def test_unrelated_cjk_and_tokenless_text_do_not_suggest_compression(self) -> None:
        pairs = (
            ("量化金融中的因子回测", "深度学习图像分类完全无关"),
            ("🧪🧪", "🚀🚀"),
        )
        for index, (left_statement, right_statement) in enumerate(pairs):
            with self.subTest(pair=index):
                report = lint_heuristics(
                    [
                        _propose(f"h-{index}-a", statement=left_statement),
                        _propose(f"h-{index}-b", statement=right_statement),
                    ],
                    now=NOW,
                )
                self.assertNotIn("compression_candidate", _kinds(report))

    def test_staleness_relative_to_injected_now(self) -> None:
        stale = _propose("h-1", created_at="2026-01-01T00:00:00Z")
        report = lint_heuristics([stale], now=NOW)
        self.assertIn("staleness", _kinds(report))
        fresh = lint_heuristics([_propose("h-2")], now=NOW)
        self.assertNotIn("staleness", _kinds(fresh))

    def test_report_artifact_is_hash_bound_and_deterministic(self) -> None:
        tips = [_propose("h-1", scope="never"), _propose("h-2", scope="scoring")]
        first = lint_heuristics(tips, now=NOW)
        second = lint_heuristics(list(reversed(tips)), now=NOW)
        self.assertEqual(first.report_sha256, second.report_sha256)
        self.assertEqual(first.findings, second.findings)
        self.assertEqual(
            first.report_sha256, canonical_sha256(first.report_entry)
        )
        self.assertEqual(first.report_entry["kind"], "heuristic-lint-report")
        self.assertEqual(first.report_entry["tips"], 2)

    def test_lint_input_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "staleness_days must be positive"):
            lint_heuristics([], now=NOW, staleness_days=0)
        with self.assertRaisesRegex(ValueError, "staleness_days must be an int"):
            lint_heuristics([], now=NOW, staleness_days=True)
        with self.assertRaisesRegex(ValueError, "RFC3339"):
            lint_heuristics([], now="not-a-date")
        with self.assertRaisesRegex(ValueError, "declares"):
            lint_heuristics([_run()], now=NOW)


class RegistryGateTest(unittest.TestCase):
    def test_assert_registry_clean_raises_on_reject(self) -> None:
        tips = [_propose("h-1"), _propose("h-2")]
        with self.assertRaisesRegex(ValueError, "registry lint rejected"):
            assert_registry_clean(tips, now=NOW)

    def test_assert_registry_clean_passes_clean_registry(self) -> None:
        assert_registry_clean([_propose("h-1")], now=NOW)

    def test_assert_no_promoted_skill(self) -> None:
        pattern = _two_case_pattern()
        assert_no_promoted_skill(pattern)
        promoted = dict(pattern, promoted_skill="skill-x")
        with self.assertRaisesRegex(ValueError, "no promotion path"):
            assert_no_promoted_skill(promoted)

    def test_assert_no_promoted_skill_validates_family(self) -> None:
        with self.assertRaisesRegex(ValueError, "declares"):
            assert_no_promoted_skill(_run())
        with self.assertRaisesRegex(ValueError, "not a valid core record"):
            assert_no_promoted_skill({"schema": "research-pattern/v1"})


if __name__ == "__main__":
    unittest.main()
