"""Behavioral tests for the M5 shadow runner (hypothetical-only trials)."""

import unittest

from research_evolution.core import canonical_sha256
from research_evolution.experience import record_shadow_report
from tests.unit.test_experience_cases import _run
from tests.unit.test_experience_heuristics import _advance, _propose, _shadow
from tests.unit.test_experience_patterns import _make_case, _two_case_pattern

RECORDED_AT = "2026-08-17T13:00:00Z"


def _observations(ids):
    return [
        {
            "heuristic_id": heuristic_id,
            "hypothetical_decision": "would halt the step",
            "expected_difference": "fewer bad rows downstream",
        }
        for heuristic_id in ids
    ]


def _shadow_set(count: int = 3) -> list:
    return [_shadow(f"h-{index}") for index in range(count)]


def _shadow_ids(heuristics) -> list:
    return [payload["heuristic_id"] for payload in heuristics]


class ShadowReportTest(unittest.TestCase):
    def test_happy_path_payload_shape(self) -> None:
        heuristics = _shadow_set(3)
        report = record_shadow_report(
            heuristics=heuristics,
            run=_run(),
            observations=_observations(_shadow_ids(heuristics)),
            recorded_at=RECORDED_AT,
        )
        payload = report.payload
        self.assertEqual(payload["kind"], "shadow-report")
        self.assertNotIn("schema", payload)
        self.assertEqual(report.sha256, canonical_sha256(payload))
        self.assertEqual(payload["run"]["run_id"], _run()["run_id"])
        self.assertEqual(
            [pin["heuristic_id"] for pin in payload["heuristics"]],
            sorted(_shadow_ids(heuristics)),
        )
        self.assertEqual(
            [entry["heuristic_id"] for entry in payload["observations"]],
            sorted(_shadow_ids(heuristics)),
        )
        for pin in payload["heuristics"]:
            self.assertEqual(pin["sha256"], canonical_sha256(
                next(h for h in heuristics if h["heuristic_id"] == pin["heuristic_id"])
            ))

    def test_deterministic_across_calls(self) -> None:
        heuristics = _shadow_set(3)
        kwargs = {
            "heuristics": heuristics,
            "run": _run(),
            "observations": _observations(_shadow_ids(heuristics)),
            "recorded_at": RECORDED_AT,
        }
        first = record_shadow_report(**kwargs)
        second = record_shadow_report(**kwargs)
        self.assertEqual(first.sha256, second.sha256)

    def test_heuristic_count_window_enforced(self) -> None:
        for count in (2, 9):
            with self.subTest(count=count):
                heuristics = _shadow_set(count)
                with self.assertRaisesRegex(ValueError, "between"):
                    record_shadow_report(
                        heuristics=heuristics,
                        run=_run(),
                        observations=_observations(_shadow_ids(heuristics)),
                        recorded_at=RECORDED_AT,
                    )

    def test_heuristics_must_be_shadow_status(self) -> None:
        heuristics = _shadow_set(2)
        candidate = _advance(_propose("h-9"), "h-9b", "candidate")
        heuristics.append(candidate)
        with self.assertRaisesRegex(ValueError, "status"):
            record_shadow_report(
                heuristics=heuristics,
                run=_run(),
                observations=_observations(_shadow_ids(heuristics)),
                recorded_at=RECORDED_AT,
            )

    def test_heuristics_must_be_heuristic_family(self) -> None:
        heuristics = _shadow_set(2)
        heuristics.append(_two_case_pattern("pat-x"))
        with self.assertRaisesRegex(ValueError, "declares"):
            record_shadow_report(
                heuristics=heuristics,
                run=_run(),
                observations=_observations([p["heuristic_id"] for p in heuristics[:2]] + ["x"]),
                recorded_at=RECORDED_AT,
            )

    def test_run_must_be_run_family(self) -> None:
        heuristics = _shadow_set(3)
        with self.assertRaisesRegex(ValueError, "declares"):
            record_shadow_report(
                heuristics=heuristics,
                run=_make_case("case-not-run"),
                observations=_observations(_shadow_ids(heuristics)),
                recorded_at=RECORDED_AT,
            )

    def test_observations_must_cover_each_heuristic_once(self) -> None:
        heuristics = _shadow_set(3)
        ids = _shadow_ids(heuristics)
        with self.assertRaisesRegex(ValueError, "exactly once"):
            record_shadow_report(
                heuristics=heuristics,
                run=_run(),
                observations=_observations(ids[:2]),
                recorded_at=RECORDED_AT,
            )
        with self.assertRaisesRegex(ValueError, "outside the trial set"):
            record_shadow_report(
                heuristics=heuristics,
                run=_run(),
                observations=_observations([ids[0], ids[1], "h-unknown"]),
                recorded_at=RECORDED_AT,
            )
        with self.assertRaisesRegex(ValueError, "duplicates"):
            record_shadow_report(
                heuristics=heuristics,
                run=_run(),
                observations=_observations([ids[0], ids[0], ids[2]]),
                recorded_at=RECORDED_AT,
            )

    def test_observation_keys_are_exact(self) -> None:
        heuristics = _shadow_set(3)
        observations = _observations(_shadow_ids(heuristics))
        observations[0]["extra_key"] = "nope"
        with self.assertRaisesRegex(ValueError, "keys must be exactly"):
            record_shadow_report(
                heuristics=heuristics,
                run=_run(),
                observations=observations,
                recorded_at=RECORDED_AT,
            )

    def test_observation_text_is_scanned(self) -> None:
        heuristics = _shadow_set(3)
        observations = _observations(_shadow_ids(heuristics))
        observations[1]["hypothetical_decision"] = "wipe C:/evil entirely"
        with self.assertRaisesRegex(ValueError, "shadow observation rejected"):
            record_shadow_report(
                heuristics=heuristics,
                run=_run(),
                observations=observations,
                recorded_at=RECORDED_AT,
            )

    def test_observation_text_must_be_nonempty_strings(self) -> None:
        heuristics = _shadow_set(3)
        observations = _observations(_shadow_ids(heuristics))
        observations[0]["expected_difference"] = ""
        with self.assertRaisesRegex(ValueError, "non-empty string"):
            record_shadow_report(
                heuristics=heuristics,
                run=_run(),
                observations=observations,
                recorded_at=RECORDED_AT,
            )

    def test_recorded_at_is_required(self) -> None:
        heuristics = _shadow_set(3)
        for bad in ("", 7):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "recorded_at"):
                    record_shadow_report(
                        heuristics=heuristics,
                        run=_run(),
                        observations=_observations(_shadow_ids(heuristics)),
                        recorded_at=bad,
                    )

    def test_heuristics_must_be_distinct_records(self) -> None:
        heuristics = _shadow_set(3)
        heuristics[1] = heuristics[0]
        with self.assertRaisesRegex(ValueError, "distinct"):
            record_shadow_report(
                heuristics=heuristics,
                run=_run(),
                observations=_observations(_shadow_ids(heuristics)),
                recorded_at=RECORDED_AT,
            )


if __name__ == "__main__":
    unittest.main()
