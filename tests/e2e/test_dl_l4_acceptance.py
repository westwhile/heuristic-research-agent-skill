"""Execute every public Phase 6 L4 synthetic acceptance scenario."""

import copy
import unittest
from pathlib import Path

from research_evolution.adapters.deep_learning.runner import DLRunnerError, run_fixture
from research_evolution.adapters.deep_learning.selection import select_fixture_runs
from research_evolution.adapters.deep_learning.studies import build_fixture_study_report
from research_evolution.core import canonical_bytes, load_strict_json
from tests.unit.test_dl_runner_l3 import (
    _fixture as _l3_fixture,
    _manifest as _l3_manifest,
    _resume_manifest,
    _selected_payload,
)
from tests.unit.test_dl_studies import (
    CASE_SHA256,
    SEEDS,
    _ablation_evidence,
    _arm,
    _compute_evidence,
    _fixture,
    _manifest,
    _plan,
    _scale_evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG = REPO_ROOT / "benchmarks" / "public" / "dl-adapter" / "catalog.json"


def _selection_with_two_failures():
    arm_id = "minimum-gate"
    study_id = f"study-{arm_id}"
    runs = tuple(
        run_fixture(
            _manifest(f"{arm_id}-seed-{seed}", study_id),
            _fixture(
                seed,
                hidden_units=3,
                requested_steps=6,
                early_stopping=False,
                failure="nan" if seed in {2, 3} else "none",
            ),
        )
        for seed in SEEDS
    )
    plan = {
        "schema": "synthetic-dl-selection-plan/v1",
        "selection_id": "selection-minimum-gate",
        "study_id": study_id,
        "case_sha256": CASE_SHA256,
        "metric": "validation_loss",
        "direction": "minimize",
        "expected_runs": [
            {"run_id": f"{arm_id}-seed-{seed}", "seed": seed}
            for seed in SEEDS
        ],
        "minimum_successful_runs": 2,
    }
    return select_fixture_runs(runs, plan)


def _run_scenario(name: str) -> str:
    if name.startswith("injected-"):
        kind = name.removeprefix("injected-")
        result = run_fixture(
            _manifest(f"catalog-{kind}", "study-catalog-failures"),
            _fixture(
                1,
                hidden_units=3,
                requested_steps=6,
                early_stopping=False,
                failure=kind,
            ),
        )
        return f"{result.status}/{result.failure_class}"

    if name == "failed-expected-seed":
        evidence = {
            "baseline": _arm(
                "baseline",
                hidden_units=3,
                requested_steps=6,
                early_stopping=False,
                failure_seed=3,
                failure_kind="oom",
            ),
            "candidate": _arm(
                "candidate",
                hidden_units=3,
                requested_steps=6,
                early_stopping=True,
            ),
        }
        return build_fixture_study_report(_plan("ablation"), evidence).status

    if name == "minimum-successful-runs-not-met":
        return _selection_with_two_failures().status

    if name == "checkpoint-content-tamper":
        partial = run_fixture(
            _l3_manifest("catalog-checkpoint-source"),
            _l3_fixture(requested_steps=4),
        )
        tampered = copy.deepcopy(_selected_payload(partial))
        tampered["model_state"]["output_bias"] = 999
        try:
            run_fixture(
                _resume_manifest("catalog-checkpoint-resume", partial),
                _l3_fixture(requested_steps=8),
                checkpoint_payload=tampered,
            )
        except DLRunnerError as exc:
            return "rejected/content-hash" if "content hash" in str(exc) else str(exc)
        return "unexpected-accept"

    if name == "early-stopping-ablation":
        return build_fixture_study_report(
            _plan("ablation"), _ablation_evidence()
        ).status
    if name == "hidden-unit-scale":
        return build_fixture_study_report(_plan("scale"), _scale_evidence()).status
    if name == "flops-matched-hidden-unit-change":
        return build_fixture_study_report(
            _plan("compute_matched"), _compute_evidence()
        ).status
    if name == "report-reference-only":
        artifact = build_fixture_study_report(
            _plan("compute_matched"), _compute_evidence()
        ).artifact
        encoded = canonical_bytes(artifact).decode("utf-8")
        if "model_state" in encoded or '"optimizer_state":' in encoded:
            return "payload-leaked"
        return artifact["artifact_retention"]["report_contains"]
    raise AssertionError(f"unhandled catalog scenario: {name}")


class DLL4AcceptanceCatalogTest(unittest.TestCase):
    def test_catalog_shape_and_scenario_coverage(self) -> None:
        catalog = load_strict_json(CATALOG.read_bytes())
        self.assertEqual(catalog["schema"], "dl-adapter-case-catalog/v1")
        self.assertEqual(catalog["provenance"], "synthetic")
        self.assertEqual(catalog["evidence_scope"], "synthetic_engineering")
        self.assertEqual(len(catalog["cases"]), 10)
        self.assertEqual(
            {case["category"] for case in catalog["cases"]},
            {
                "failure-preservation",
                "selection-integrity",
                "checkpoint-integrity",
                "comparison-fairness",
                "artifact-retention",
            },
        )
        ids = [case["case_id"] for case in catalog["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(case_id.startswith("DLC-") for case_id in ids))

    def test_every_catalog_case_reaches_its_expected_outcome(self) -> None:
        catalog = load_strict_json(CATALOG.read_bytes())
        outcomes = {
            case["case_id"]: _run_scenario(case["scenario"])
            for case in catalog["cases"]
        }
        expected = {
            case["case_id"]: case["expected_outcome"]
            for case in catalog["cases"]
        }
        self.assertEqual(outcomes, expected)


if __name__ == "__main__":
    unittest.main()
