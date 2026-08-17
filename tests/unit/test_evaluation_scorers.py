"""Unit tests for the E4 scorer levels and score-vector discipline
(ADR-0006 decisions 5-6)."""

import json
import unittest
from pathlib import Path

from research_evolution.evaluation import (
    SCORER_LEVELS,
    ScoreEntry,
    package_judge_scores,
    package_rubric_scores,
    score_vector_payload,
    score_with_checker,
    score_with_oracle,
    scorer_identity,
    validate_score_vector,
)

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas" / "core"

CALIBRATION_SHA = "c" * 64
ORACLE = {"answer": 42, "units": "m"}


class ScorerLevelPinTest(unittest.TestCase):
    def test_levels_match_run_schema_enum(self) -> None:
        schema = json.loads(
            (SCHEMAS / "evaluation-run-v1.schema.json").read_text(encoding="utf-8")
        )
        enum = set(schema["properties"]["scorer"]["properties"]["level"]["enum"])
        self.assertEqual(enum, set(SCORER_LEVELS))

    def test_levels_match_case_schema_enum(self) -> None:
        schema = json.loads(
            (SCHEMAS / "evaluation-case-v1.schema.json").read_text(encoding="utf-8")
        )
        enum = set(
            schema["properties"]["evaluation_contract"]["properties"][
                "scorer_level"
            ]["enum"]
        )
        self.assertEqual(enum, set(SCORER_LEVELS))


class ScoreEntryTest(unittest.TestCase):
    def test_valid_entry(self) -> None:
        entry = ScoreEntry(dimension="exact_match:answer", value=1, unit=None)
        self.assertEqual(entry.value, 1.0)
        self.assertIsNone(entry.unit)

    def test_field_validation(self) -> None:
        with self.assertRaises(ValueError):
            ScoreEntry(dimension="", value=1.0)
        with self.assertRaises(ValueError):
            ScoreEntry(dimension="  ", value=1.0)
        with self.assertRaises(ValueError):
            ScoreEntry(dimension="d", value=True)
        with self.assertRaises(ValueError):
            ScoreEntry(dimension="d", value=float("nan"))
        with self.assertRaises(ValueError):
            ScoreEntry(dimension="d", value=float("inf"))
        with self.assertRaises(ValueError):
            ScoreEntry(dimension="d", value=1.0, unit="")

    def test_dimension_matches_frozen_schema_pattern(self) -> None:
        # R30-P3 regression: the run schema pins dimension to ^\S+$; the
        # entry must refuse what the schema would reject downstream.
        with self.assertRaises(ValueError):
            ScoreEntry("clarity of prose", 1.0)
        with self.assertRaises(ValueError):
            ScoreEntry("lead\nnewline", 1.0)
        self.assertEqual(ScoreEntry("exact_match:answer", 1.0).value, 1.0)


class OracleScorerTest(unittest.TestCase):
    def test_full_match(self) -> None:
        entries = score_with_oracle({"answer": 42, "units": "m"}, ORACLE)
        self.assertEqual(
            entries,
            (
                ScoreEntry("exact_match:answer", 1.0),
                ScoreEntry("exact_match:units", 1.0),
            ),
        )

    def test_partial_and_missing_fields(self) -> None:
        entries = score_with_oracle({"answer": 43}, ORACLE)
        self.assertEqual(
            entries,
            (
                ScoreEntry("exact_match:answer", 0.0),
                ScoreEntry("exact_match:units", 0.0),
            ),
        )

    def test_extra_output_fields_are_ignored(self) -> None:
        entries = score_with_oracle(
            {"answer": 42, "units": "m", "verbose_trace": "..."}, ORACLE
        )
        self.assertEqual(len(entries), 2)

    def test_deterministic_ordering(self) -> None:
        first = score_with_oracle({"answer": 42, "units": "m"}, ORACLE)
        second = score_with_oracle({"units": "m", "answer": 42}, ORACLE)
        self.assertEqual(first, second)

    def test_json_faithful_equality_rejects_python_false_matches(self) -> None:
        # R30-P2 regression: Python "==" confuses JSON types; every form
        # below must score 0.0, and the two controls must stay 1.0.
        false_match_cases = [
            ({"flag": True}, {"flag": 1}, "flag"),      # bool vs int
            ({"flag": False}, {"flag": 0}, "flag"),     # bool vs int zero
            ({"seq": [1, 1]}, {"seq": [1, True]}, "seq"),  # nested in list
            ({"note": None}, {}, "note"),               # absent vs null
        ]
        for oracle, output, field in false_match_cases:
            with self.subTest(oracle=oracle, output=output):
                (entry,) = score_with_oracle(output, oracle)
                self.assertEqual(entry, ScoreEntry(f"exact_match:{field}", 0.0))
        controls = [
            ({"note": None}, {"note": None}, "note"),   # null present vs null
            ({"n": 1}, {"n": 1.0}, "n"),                # JSON number semantics
            ({"seq": {"x": [1, 2]}}, {"seq": {"x": [1, 2]}}, "seq"),
        ]
        for oracle, output, field in controls:
            with self.subTest(oracle=oracle, output=output):
                (entry,) = score_with_oracle(output, oracle)
                self.assertEqual(entry, ScoreEntry(f"exact_match:{field}", 1.0))


class CheckerScorerTest(unittest.TestCase):
    def test_numeric_tolerance_within(self) -> None:
        entries = score_with_checker(
            {"estimate": 10.4},
            {
                "checker": "numeric_tolerance",
                "params": {"field": "estimate", "expected": 10.0, "tolerance": 0.5},
            },
        )
        self.assertEqual(
            [entry.dimension for entry in entries],
            ["absolute_error:estimate", "within_tolerance:estimate"],
        )
        self.assertAlmostEqual(entries[0].value, 0.4)
        self.assertEqual(entries[0].unit, "absolute")
        self.assertEqual(entries[1].value, 1.0)

    def test_numeric_tolerance_outside_and_missing(self) -> None:
        outside = score_with_checker(
            {"estimate": 11.0},
            {
                "checker": "numeric_tolerance",
                "params": {"field": "estimate", "expected": 10.0, "tolerance": 0.5},
            },
        )
        self.assertEqual(dict((e.dimension, e.value) for e in outside)["within_tolerance:estimate"], 0.0)
        missing = score_with_checker(
            {},
            {
                "checker": "numeric_tolerance",
                "params": {"field": "estimate", "expected": 10.0, "tolerance": 0.5},
            },
        )
        self.assertEqual(missing, (ScoreEntry("within_tolerance:estimate", 0.0),))

    def test_spec_validation(self) -> None:
        with self.assertRaises(ValueError):
            score_with_checker({}, {"checker": "no_such_checker", "params": {}})
        with self.assertRaises(ValueError):
            score_with_checker({}, {"checker": "numeric_tolerance"})
        with self.assertRaises(ValueError):
            score_with_checker(
                {"x": 1},
                {
                    "checker": "numeric_tolerance",
                    "params": {"field": "x", "expected": 1.0, "tolerance": -0.1},
                },
            )


class RubricAndJudgeTest(unittest.TestCase):
    def test_rubric_packaging_sorted(self) -> None:
        entries = package_rubric_scores({"clarity": 0.5, "accuracy": 1})
        self.assertEqual(
            entries,
            (
                ScoreEntry("accuracy", 1.0),
                ScoreEntry("clarity", 0.5),
            ),
        )

    def test_rubric_rejects_empty_and_non_finite(self) -> None:
        with self.assertRaises(ValueError):
            package_rubric_scores({})
        with self.assertRaises(ValueError):
            package_rubric_scores({"accuracy": float("nan")})

    def test_judge_requires_calibration_evidence(self) -> None:
        with self.assertRaises(ValueError):
            package_judge_scores({"accuracy": 1.0}, None)
        with self.assertRaises(ValueError):
            package_judge_scores({"accuracy": 1.0}, "")
        with self.assertRaises(ValueError):
            package_judge_scores({"accuracy": 1.0}, "not-a-sha")
        entries = package_judge_scores({"accuracy": 1.0}, CALIBRATION_SHA)
        self.assertEqual(entries, (ScoreEntry("accuracy", 1.0),))


class ScoreVectorTest(unittest.TestCase):
    def test_validate_rejects_empty_and_duplicates(self) -> None:
        with self.assertRaises(ValueError):
            validate_score_vector(())
        with self.assertRaises(ValueError):
            validate_score_vector(
                (ScoreEntry("a", 1.0), ScoreEntry("a", 0.0))
            )

    def test_payload_shape(self) -> None:
        payload = score_vector_payload(
            (
                ScoreEntry("absolute_error:x", 0.4, "absolute"),
                ScoreEntry("within_tolerance:x", 1.0),
            )
        )
        self.assertEqual(
            payload,
            [
                {"dimension": "absolute_error:x", "value": 0.4, "unit": "absolute"},
                {"dimension": "within_tolerance:x", "value": 1.0},
            ],
        )


class ScorerIdentityTest(unittest.TestCase):
    def test_identity_per_level(self) -> None:
        self.assertEqual(
            scorer_identity("oracle"),
            {"level": "oracle", "tool": "oracle-scorer", "version": "0.1.0"},
        )
        identity = scorer_identity(
            "calibrated_judge", calibration_sha256=CALIBRATION_SHA
        )
        self.assertEqual(identity["calibration_sha256"], CALIBRATION_SHA)
        self.assertEqual(identity["tool"], "calibrated-judge")

    def test_judge_identity_requires_calibration(self) -> None:
        with self.assertRaises(ValueError):
            scorer_identity("calibrated_judge")
        with self.assertRaises(ValueError):
            scorer_identity("no_such_level")

    def test_non_judge_level_refuses_calibration(self) -> None:
        # R30-P4: silently dropping calibration evidence would let a caller
        # believe it was traced when it was not.
        with self.assertRaises(ValueError):
            scorer_identity("oracle", calibration_sha256=CALIBRATION_SHA)


if __name__ == "__main__":
    unittest.main()
