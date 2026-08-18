"""Behavioral tests for the M4 deterministic retrieval MVP."""

import hashlib
import unittest

from research_evolution.core import canonical_sha256
from research_evolution.experience import (
    build_pattern_index,
    distill_patterns,
    retrieve_patterns,
    transition_pattern,
)
from tests.unit.test_experience_patterns import (
    _distill_kwargs,
    _make_case,
    _two_case_pattern,
)


def _query() -> dict:
    return {
        "signature_summary": "Synthetic signature.",
        "signature_sha256": hashlib.sha256(b"signature").hexdigest(),
        "recorded_at": "2026-08-17T16:00:00Z",
    }


def _promoted(pattern: dict, new_id: str, status: str = "candidate_pattern") -> dict:
    return transition_pattern(
        pattern=pattern,
        new_pattern_id=new_id,
        status=status,
        transition_rationale="promotion for retrieval tests",
        created_at="2026-08-17T11:00:00Z",
    )


def _index_with_three():
    exact = _promoted(_two_case_pattern("pat-exact"), "pat-exact-2")
    structural_kwargs = _distill_kwargs([_make_case("case-x", sig=b"sx"), _make_case("case-y", sig=b"sy")])
    structural_kwargs.update(
        pattern_id="pat-structural",
        signature_summary="different structural summary",
        signature_sha256=hashlib.sha256(b"structural").hexdigest(),
        signature_facets={"area": "general"},
    )
    structural = _promoted(distill_patterns(**structural_kwargs), "pat-structural-2")
    semantic_kwargs = _distill_kwargs([_make_case("case-p", sig=b"sp"), _make_case("case-q", sig=b"sq")])
    semantic_kwargs.update(
        pattern_id="pat-semantic",
        signature_summary="Synthetic signature variant",
        signature_sha256=hashlib.sha256(b"semantic").hexdigest(),
    )
    semantic = _promoted(distill_patterns(**semantic_kwargs), "pat-semantic-2")
    return build_pattern_index(
        [
            _two_case_pattern("pat-exact"),
            exact,
            distill_patterns(**structural_kwargs),
            structural,
            distill_patterns(**semantic_kwargs),
            semantic,
        ]
    )


class RetrievalTest(unittest.TestCase):
    def test_exact_match_ranked_first(self) -> None:
        index = _index_with_three()
        result = retrieve_patterns(
            patterns=index,
            facets={"area": "general"},
            **_query(),
        )
        self.assertFalse(result.abstained)
        ordered = [(c.pattern_id, c.match_tier) for c in result.candidates]
        self.assertEqual(ordered[0], ("pat-exact-2", "exact_fingerprint"))
        self.assertEqual(ordered[1], ("pat-structural-2", "structural_fields"))
        self.assertEqual(ordered[2], ("pat-semantic-2", "semantic_proposal"))

    def test_candidate_carries_six_elements(self) -> None:
        index = _index_with_three()
        result = retrieve_patterns(patterns=index, **_query())
        candidate = result.candidates[0]
        self.assertEqual(candidate.applicability["scope"], "unit test scope")
        self.assertIn("preconditions", candidate.applicability)
        self.assertEqual(candidate.contraindications, ())
        self.assertEqual(candidate.evidence["grade"], "synthetic")
        self.assertEqual(len(candidate.source_cases), 2)
        self.assertEqual(candidate.last_validated, "2026-08-17T10:00:00Z")
        self.assertEqual(
            candidate.differences, ("no signature difference: exact fingerprint match",)
        )
        self.assertEqual(candidate.sha256, canonical_sha256(
            [r for r in index.records if r["pattern_id"] == "pat-exact-2"][0]
        ))

    def test_abstain_is_explicit(self) -> None:
        index = _index_with_three()
        query = _query()
        query["signature_summary"] = "zzz no overlap anywhere"
        query["signature_sha256"] = hashlib.sha256(b"nomatch").hexdigest()
        result = retrieve_patterns(patterns=index, **query)
        self.assertTrue(result.abstained)
        self.assertEqual(result.candidates, ())
        self.assertTrue(result.session_entry["abstained"])

    def test_limit_validation_and_cap(self) -> None:
        index = _index_with_three()
        for bad in (0, 6, True, "3"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    retrieve_patterns(patterns=index, limit=bad, **_query())
        result = retrieve_patterns(patterns=index, limit=1, **_query())
        self.assertEqual(len(result.candidates), 1)

    def test_only_promoted_nonterminal_tips_retrievable(self) -> None:
        distilled = _two_case_pattern("pat-d")
        candidate_base = _two_case_pattern("pat-c")
        candidate = _promoted(candidate_base, "pat-c-2")
        retired_base = _two_case_pattern("pat-r")
        retired_mid = _promoted(retired_base, "pat-r-2")
        retired = transition_pattern(
            pattern=retired_mid,
            new_pattern_id="pat-r-3",
            status="retired",
            transition_rationale="retired for the filter test",
            created_at="2026-08-17T12:00:00Z",
        )
        index = build_pattern_index(
            [distilled, candidate_base, candidate, retired_base, retired_mid, retired]
        )
        result = retrieve_patterns(patterns=index, **_query())
        ids = {c.pattern_id for c in result.candidates}
        self.assertEqual(ids, {"pat-c-2"})

    def test_session_entry_is_hash_bound_and_deterministic(self) -> None:
        index = _index_with_three()
        first = retrieve_patterns(patterns=index, **_query())
        second = retrieve_patterns(patterns=index, **_query())
        self.assertEqual(first.session_sha256, second.session_sha256)
        later = retrieve_patterns(
            patterns=index, **dict(_query(), recorded_at="2026-08-17T17:00:00Z")
        )
        self.assertNotEqual(first.session_sha256, later.session_sha256)
        self.assertEqual(
            first.session_entry["candidates"],
            [{"pattern_id": c.pattern_id, "sha256": c.sha256} for c in first.candidates],
        )

    def test_query_text_is_scanned(self) -> None:
        index = _index_with_three()
        query = _query()
        query["signature_summary"] = "see /etc/passwd"
        with self.assertRaisesRegex(ValueError, "restricted content refused"):
            retrieve_patterns(patterns=index, **query)
        query = _query()
        with self.assertRaisesRegex(ValueError, "restricted content refused"):
            retrieve_patterns(patterns=index, facets={"note": "~/secret"}, **query)

    def test_semantic_candidate_is_marked_proposal_only(self) -> None:
        index = _index_with_three()
        query = _query()
        query["signature_sha256"] = hashlib.sha256(b"nomatch").hexdigest()
        result = retrieve_patterns(patterns=index, **query)
        semantic = [c for c in result.candidates if c.match_tier == "semantic_proposal"]
        self.assertTrue(semantic)
        self.assertTrue(
            any("semantic proposal only" in note for note in semantic[0].differences)
        )


if __name__ == "__main__":
    unittest.main()
