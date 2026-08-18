"""Behavioral tests for the M4 pattern registry and reuse records."""

import hashlib
import json
import unittest

from research_evolution.core import canonical_sha256
from research_evolution.experience import (
    EligibilityInput,
    SingletonAttestation,
    build_pattern_index,
    capture_case,
    distill_patterns,
    pattern_chain,
    record_reuse_outcome,
    reuse_summary,
    transition_pattern,
)
from research_evolution.experience import patterns as patterns_module
from research_evolution.experience import reuse as reuse_module
from tests.unit.test_experience_cases import (
    SCHEMAS,
    _base_kwargs,
    _run,
    _task,
)


def _make_case(
    case_id: str,
    *,
    summary: str = "Synthetic signature.",
    sig: bytes = b"signature",
    eligible: bool = True,
    facets: dict | None = None,
) -> dict:
    kwargs = _base_kwargs()
    kwargs["case_id"] = case_id
    kwargs["signature_summary"] = summary
    kwargs["signature_sha256"] = hashlib.sha256(sig).hexdigest()
    if facets is not None:
        kwargs["signature_facets"] = facets
    if not eligible:
        kwargs["eligibility"] = EligibilityInput(False, True, True, True)
    return capture_case(**kwargs)


def _distill_kwargs(cases: list) -> dict:
    return {
        "cases": cases,
        "pattern_id": "pat-1",
        "created_at": "2026-08-17T10:00:00Z",
        "last_validated": "2026-08-17T10:00:00Z",
        "scope": "unit test scope",
        "successful_tactics": ["tactic that worked"],
        "evidence_grade": "synthetic",
        "evidence_rationale": "synthetic de-identified evidence",
        "confidence": "low",
        "transition_rationale": "initial distillation",
    }


def _two_case_pattern(pattern_id: str = "pat-1") -> dict:
    cases = [_make_case("case-a"), _make_case("case-b")]
    kwargs = _distill_kwargs(cases)
    kwargs["pattern_id"] = pattern_id
    return distill_patterns(**kwargs)


def _attestation() -> SingletonAttestation:
    return SingletonAttestation(
        reproduction="run-2 reproduces the failure",
        counterfactual_fix="removing step X removes the failure",
        independent_review="reviewer confirmed the chain",
    )


class DistillTest(unittest.TestCase):
    def test_distill_happy_two_cases(self) -> None:
        cases = [_make_case("case-a"), _make_case("case-b")]
        payload = distill_patterns(**_distill_kwargs(cases))
        self.assertEqual(payload["schema"], "research-pattern/v1")
        self.assertEqual(payload["status"], "distilled")
        self.assertEqual(
            payload["source_cases"],
            [
                {"case_id": "case-a", "sha256": canonical_sha256(cases[0])},
                {"case_id": "case-b", "sha256": canonical_sha256(cases[1])},
            ],
        )
        self.assertEqual(
            payload["problem_signature"]["signature_sha256"],
            cases[0]["problem_signature"]["signature_sha256"],
        )
        self.assertNotIn("supersedes", payload)
        self.assertNotIn("promoted_skill", payload)

    def test_distill_refuses_ineligible_case(self) -> None:
        cases = [_make_case("case-a"), _make_case("case-bad", eligible=False)]
        with self.assertRaisesRegex(ValueError, "ineligible"):
            distill_patterns(**_distill_kwargs(cases))

    def test_distill_refuses_signature_disagreement(self) -> None:
        cases = [_make_case("case-a"), _make_case("case-b", sig=b"other")]
        with self.assertRaisesRegex(ValueError, "disagree on signature_sha256"):
            distill_patterns(**_distill_kwargs(cases))
        kwargs = _distill_kwargs(cases)
        kwargs["signature_summary"] = "Merged signature."
        kwargs["signature_sha256"] = hashlib.sha256(b"merged").hexdigest()
        payload = distill_patterns(**kwargs)
        self.assertEqual(
            payload["problem_signature"]["signature_sha256"],
            hashlib.sha256(b"merged").hexdigest(),
        )

    def test_distill_explicit_signature_requires_summary(self) -> None:
        kwargs = _distill_kwargs([_make_case("case-a")])
        kwargs["signature_sha256"] = hashlib.sha256(b"x").hexdigest()
        with self.assertRaisesRegex(ValueError, "signature_summary"):
            distill_patterns(**kwargs)

    def test_distill_scans_text_fields(self) -> None:
        kwargs = _distill_kwargs([_make_case("case-a"), _make_case("case-b")])
        kwargs["scope"] = "see C:/work/scope"
        with self.assertRaisesRegex(ValueError, "restricted content refused"):
            distill_patterns(**kwargs)

    def test_distill_refuses_duplicate_source_case(self) -> None:
        case = _make_case("case-a")
        with self.assertRaisesRegex(ValueError, "independent"):
            distill_patterns(**_distill_kwargs([case, case]))

    def test_distill_self_validates(self) -> None:
        kwargs = _distill_kwargs([_make_case("case-a")])
        kwargs["confidence"] = "bogus"
        with self.assertRaisesRegex(ValueError, "assembled pattern payload"):
            distill_patterns(**kwargs)
        kwargs = _distill_kwargs([_make_case("case-a")])
        kwargs["created_at"] = "not-a-date"
        with self.assertRaisesRegex(ValueError, "assembled pattern payload"):
            distill_patterns(**kwargs)


class TransitionTest(unittest.TestCase):
    def test_forward_transition_happy(self) -> None:
        pattern = _two_case_pattern()
        successor = transition_pattern(
            pattern=pattern,
            new_pattern_id="pat-2",
            status="candidate_pattern",
            transition_rationale="two independent cases support promotion",
            created_at="2026-08-17T11:00:00Z",
        )
        self.assertEqual(successor["supersedes"], "pat-1")
        self.assertEqual(successor["status"], "candidate_pattern")
        self.assertEqual(successor["scope"], pattern["scope"])
        self.assertEqual(successor["source_cases"], pattern["source_cases"])

    def test_singleton_candidate_requires_attestation(self) -> None:
        pattern = distill_patterns(**_distill_kwargs([_make_case("case-a")]))
        with self.assertRaisesRegex(ValueError, "all three attestation elements"):
            transition_pattern(
                pattern=pattern,
                new_pattern_id="pat-2",
                status="candidate_pattern",
                transition_rationale="singleton promotion",
                created_at="2026-08-17T11:00:00Z",
            )
        successor = transition_pattern(
            pattern=pattern,
            new_pattern_id="pat-2",
            status="candidate_pattern",
            transition_rationale="singleton promotion",
            created_at="2026-08-17T11:00:00Z",
            singleton_attestation=_attestation(),
        )
        self.assertIn("Singleton exception attestation", successor["transition_rationale"])
        self.assertIn("reproduction=run-2 reproduces", successor["transition_rationale"])
        self.assertIn("independent review=reviewer confirmed", successor["transition_rationale"])

    def test_singleton_never_beyond_candidate(self) -> None:
        pattern = distill_patterns(**_distill_kwargs([_make_case("case-a")]))
        candidate = transition_pattern(
            pattern=pattern,
            new_pattern_id="pat-2",
            status="candidate_pattern",
            transition_rationale="singleton promotion",
            created_at="2026-08-17T11:00:00Z",
            singleton_attestation=_attestation(),
        )
        for status in ("validated_pattern", "active_pattern"):
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "never goes beyond"):
                    transition_pattern(
                        pattern=candidate,
                        new_pattern_id="pat-3",
                        status=status,
                        transition_rationale="attempted singleton jump",
                        created_at="2026-08-17T12:00:00Z",
                        singleton_attestation=_attestation(),
                    )

    def test_attestation_only_for_singleton_candidate(self) -> None:
        pattern = _two_case_pattern()
        with self.assertRaisesRegex(ValueError, "single-case"):
            transition_pattern(
                pattern=pattern,
                new_pattern_id="pat-2",
                status="candidate_pattern",
                transition_rationale="two cases, spurious attestation",
                created_at="2026-08-17T11:00:00Z",
                singleton_attestation=_attestation(),
            )
        singleton = distill_patterns(**_distill_kwargs([_make_case("case-a")]))
        with self.assertRaisesRegex(ValueError, "candidate_pattern"):
            transition_pattern(
                pattern=singleton,
                new_pattern_id="pat-9",
                status="rejected",
                transition_rationale="attested rejection is nonsense",
                created_at="2026-08-17T11:00:00Z",
                singleton_attestation=_attestation(),
            )

    def test_terminal_states_never_move(self) -> None:
        pattern = _two_case_pattern()
        candidate = transition_pattern(
            pattern=pattern,
            new_pattern_id="pat-2",
            status="candidate_pattern",
            transition_rationale="promotion",
            created_at="2026-08-17T11:00:00Z",
        )
        retired = transition_pattern(
            pattern=candidate,
            new_pattern_id="pat-3",
            status="retired",
            transition_rationale="superseded by a better pattern",
            created_at="2026-08-17T12:00:00Z",
        )
        self.assertEqual(retired["status"], "retired")
        with self.assertRaisesRegex(ValueError, "terminal"):
            transition_pattern(
                pattern=retired,
                new_pattern_id="pat-4",
                status="active_pattern",
                transition_rationale="revival attempt",
                created_at="2026-08-17T13:00:00Z",
            )

    def test_backward_and_equal_moves_refused(self) -> None:
        pattern = _two_case_pattern()
        candidate = transition_pattern(
            pattern=pattern,
            new_pattern_id="pat-2",
            status="candidate_pattern",
            transition_rationale="promotion",
            created_at="2026-08-17T11:00:00Z",
        )
        for status in ("distilled", "captured", "candidate_pattern"):
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "strictly forward"):
                    transition_pattern(
                        pattern=candidate,
                        new_pattern_id="pat-3",
                        status=status,
                        transition_rationale="backward move",
                        created_at="2026-08-17T12:00:00Z",
                    )

    def test_self_supersede_refused(self) -> None:
        pattern = _two_case_pattern()
        with self.assertRaisesRegex(ValueError, "equals the predecessor"):
            transition_pattern(
                pattern=pattern,
                new_pattern_id="pat-1",
                status="candidate_pattern",
                transition_rationale="self loop",
                created_at="2026-08-17T11:00:00Z",
            )

    def test_unknown_status_refused(self) -> None:
        pattern = _two_case_pattern()
        with self.assertRaisesRegex(ValueError, "unknown pattern status"):
            transition_pattern(
                pattern=pattern,
                new_pattern_id="pat-2",
                status="bogus",
                transition_rationale="nonsense",
                created_at="2026-08-17T11:00:00Z",
            )

    def test_overrides_and_scan(self) -> None:
        pattern = _two_case_pattern()
        successor = transition_pattern(
            pattern=pattern,
            new_pattern_id="pat-2",
            status="candidate_pattern",
            transition_rationale="promotion with updates",
            created_at="2026-08-17T11:00:00Z",
            confidence="medium",
            evidence_grade="synthetic-plus",
            last_validated="2026-08-17T11:30:00Z",
        )
        self.assertEqual(successor["confidence"], "medium")
        self.assertEqual(successor["evidence"]["grade"], "synthetic-plus")
        self.assertEqual(
            successor["evidence"]["rationale"], pattern["evidence"]["rationale"]
        )
        self.assertEqual(successor["last_validated"], "2026-08-17T11:30:00Z")
        with self.assertRaisesRegex(ValueError, "restricted content refused"):
            transition_pattern(
                pattern=pattern,
                new_pattern_id="pat-3",
                status="candidate_pattern",
                transition_rationale="promotion",
                created_at="2026-08-17T11:00:00Z",
                scope="files under /etc/passwd",
            )

    def test_source_cases_override(self) -> None:
        pattern = _two_case_pattern()
        cases = [_make_case("case-c"), _make_case("case-d"), _make_case("case-e")]
        successor = transition_pattern(
            pattern=pattern,
            new_pattern_id="pat-2",
            status="candidate_pattern",
            transition_rationale="widened evidence base",
            created_at="2026-08-17T11:00:00Z",
            source_cases=cases,
        )
        self.assertEqual(len(successor["source_cases"]), 3)
        with self.assertRaisesRegex(ValueError, "ineligible"):
            transition_pattern(
                pattern=pattern,
                new_pattern_id="pat-3",
                status="candidate_pattern",
                transition_rationale="bad widening",
                created_at="2026-08-17T11:00:00Z",
                source_cases=[_make_case("case-f", eligible=False)],
            )


class PatternIndexTest(unittest.TestCase):
    def _chain_of_three(self) -> list:
        one = _two_case_pattern("pat-1")
        two = transition_pattern(
            pattern=one,
            new_pattern_id="pat-2",
            status="candidate_pattern",
            transition_rationale="promotion",
            created_at="2026-08-17T11:00:00Z",
        )
        three = transition_pattern(
            pattern=two,
            new_pattern_id="pat-3",
            status="validated_pattern",
            transition_rationale="further validation",
            created_at="2026-08-17T12:00:00Z",
        )
        return [one, two, three]

    def test_tips_and_chain(self) -> None:
        versions = self._chain_of_three()
        index = build_pattern_index(versions)
        self.assertEqual(index.tips, ("pat-3",))
        chain = pattern_chain(index, "pat-3")
        self.assertEqual(
            [data["pattern_id"] for data in chain], ["pat-3", "pat-2", "pat-1"]
        )
        self.assertEqual(chain[0]["status"], "validated_pattern")
        again = build_pattern_index(list(reversed(versions)))
        self.assertEqual(index.sha256, again.sha256)

    def test_duplicate_pattern_id_refused(self) -> None:
        pattern = _two_case_pattern()
        with self.assertRaisesRegex(ValueError, "duplicate pattern_id"):
            build_pattern_index([pattern, pattern])

    def test_fork_surfaces_two_tips(self) -> None:
        one = _two_case_pattern("pat-1")
        left = transition_pattern(
            pattern=one,
            new_pattern_id="pat-2a",
            status="candidate_pattern",
            transition_rationale="left fork",
            created_at="2026-08-17T11:00:00Z",
        )
        right = transition_pattern(
            pattern=one,
            new_pattern_id="pat-2b",
            status="rejected",
            transition_rationale="right fork",
            created_at="2026-08-17T11:30:00Z",
        )
        index = build_pattern_index([one, left, right])
        self.assertEqual(index.tips, ("pat-2a", "pat-2b"))

    def test_chain_failures(self) -> None:
        index = build_pattern_index(self._chain_of_three())
        with self.assertRaisesRegex(ValueError, "not in the index"):
            pattern_chain(index, "pat-99")
        partial = build_pattern_index(self._chain_of_three()[1:])
        with self.assertRaisesRegex(ValueError, "missing"):
            pattern_chain(partial, "pat-3")


class ReuseTest(unittest.TestCase):
    def _reuse_kwargs(self) -> dict:
        return {
            "reuse_event_id": "reuse-1",
            "run": _run(),
            "pattern": _two_case_pattern(),
            "outcome": "helped",
            "recorded_at": "2026-08-17T15:00:00Z",
        }

    def test_record_reuse_happy(self) -> None:
        kwargs = self._reuse_kwargs()
        kwargs["note"] = "operator selected the pattern"
        payload = record_reuse_outcome(**kwargs)
        self.assertEqual(payload["schema"], "reuse-event/v1")
        self.assertEqual(
            payload["run"],
            {"run_id": _run()["run_id"], "sha256": canonical_sha256(_run())},
        )
        self.assertEqual(
            payload["pattern"]["pattern_id"], "pat-1"
        )
        self.assertEqual(payload["note"], "operator selected the pattern")

    def test_record_reuse_family_mismatch(self) -> None:
        kwargs = self._reuse_kwargs()
        kwargs["run"] = _task()
        with self.assertRaisesRegex(ValueError, "research-run/v1"):
            record_reuse_outcome(**kwargs)
        kwargs = self._reuse_kwargs()
        kwargs["pattern"] = _run()
        with self.assertRaisesRegex(ValueError, "research-pattern/v1"):
            record_reuse_outcome(**kwargs)

    def test_record_reuse_note_scanned(self) -> None:
        kwargs = self._reuse_kwargs()
        kwargs["note"] = "reach me at a@b.com"
        with self.assertRaisesRegex(ValueError, "restricted content refused"):
            record_reuse_outcome(**kwargs)

    def test_record_reuse_self_validates(self) -> None:
        kwargs = self._reuse_kwargs()
        kwargs["outcome"] = "bogus"
        with self.assertRaisesRegex(ValueError, "assembled reuse event payload"):
            record_reuse_outcome(**kwargs)

    def test_reuse_summary(self) -> None:
        pattern_a = _two_case_pattern("pat-1")
        pattern_b = _two_case_pattern("pat-9")
        events = [
            record_reuse_outcome(
                **dict(self._reuse_kwargs(), reuse_event_id="reuse-1", pattern=pattern_a)
            ),
            record_reuse_outcome(
                **dict(
                    self._reuse_kwargs(),
                    reuse_event_id="reuse-2",
                    pattern=pattern_a,
                    outcome="harmed",
                )
            ),
            record_reuse_outcome(
                **dict(
                    self._reuse_kwargs(),
                    reuse_event_id="reuse-3",
                    pattern=pattern_b,
                    outcome="not_applicable",
                )
            ),
        ]
        summary = reuse_summary(events)
        self.assertEqual(summary["events"], 3)
        pin_a = canonical_sha256(pattern_a)
        self.assertEqual(summary["patterns"][pin_a]["helped"], 1)
        self.assertEqual(summary["patterns"][pin_a]["harmed"], 1)
        self.assertEqual(summary["patterns"][pin_a]["total"], 2)
        pin_b = canonical_sha256(pattern_b)
        self.assertEqual(summary["patterns"][pin_b]["not_applicable"], 1)
        self.assertEqual(summary["patterns"][pin_b]["pattern_id"], "pat-9")
        again = reuse_summary(list(reversed(events)))
        self.assertEqual(summary, again)
        with self.assertRaisesRegex(ValueError, "reuse-event/v1"):
            reuse_summary([_task()])


class RegistryFamilyConstantsTest(unittest.TestCase):
    def test_family_constants_match_schema_consts(self) -> None:
        expected = (
            ("research-pattern-v1.schema.json", patterns_module._PATTERN_FAMILY),
            ("reuse-event-v1.schema.json", reuse_module._REUSE_FAMILY),
        )
        for filename, constant in expected:
            with self.subTest(schema=filename):
                schema = json.loads((SCHEMAS / filename).read_text(encoding="utf-8"))
                self.assertEqual(schema["properties"]["schema"]["const"], constant)


if __name__ == "__main__":
    unittest.main()
