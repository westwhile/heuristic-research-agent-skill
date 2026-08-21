"""L5 synthetic ML catalog and public-seam vertical slices."""

from __future__ import annotations

import hashlib
import unittest
from collections import Counter
from pathlib import Path

from research_evolution.adapters import AdapterError
from research_evolution.adapters.ml import MLAdapter
from research_evolution.adapters.ml.runner import run_synthetic_experiment
from research_evolution.core import (
    canonical_bytes,
    canonical_sha256,
    load_record,
    load_strict_json,
)
from tests.unit.test_ml_split_execution import (
    _group_payload,
    _time_series_payload,
)

_ROOT = Path(__file__).resolve().parents[2]
_CATALOG = _ROOT / "benchmarks" / "public" / "ml-adapter" / "catalog.json"
_CLAIM = (
    _ROOT
    / "tests"
    / "fixtures"
    / "adapters"
    / "ml-claim"
    / "v1"
    / "valid"
    / "full.json"
)
_TASK = (
    _ROOT
    / "tests"
    / "fixtures"
    / "adapters"
    / "ml-task"
    / "v1"
    / "valid"
    / "minimal.json"
)


def _repository_normalized_sha256(raw: bytes) -> str:
    """Hash text as stored by Git under the repository LF attributes."""

    normalized = raw.replace(b"\r\n", b"\n")
    if b"\r" in normalized:
        raise AssertionError("catalog fixture contains an unsupported lone CR")
    return hashlib.sha256(normalized).hexdigest()


class MLAdapterPublicCatalogTest(unittest.TestCase):
    def test_catalog_is_hash_pinned_synthetic_and_executable(self) -> None:
        catalog = load_strict_json(_CATALOG.read_bytes())
        self.assertEqual(
            set(catalog),
            {"schema", "catalog_id", "provenance", "description", "cases"},
        )
        self.assertEqual(catalog["schema"], "ml-adapter-case-catalog/v1")
        self.assertEqual(catalog["provenance"], "synthetic")
        self.assertIn("[SYNTHETIC]", catalog["description"])
        self.assertGreaterEqual(len(catalog["cases"]), 15)
        self.assertLessEqual(len(catalog["cases"]), 25)
        self.assertEqual(
            len({entry["case_id"] for entry in catalog["cases"]}),
            len(catalog["cases"]),
        )

        adapter = MLAdapter()
        categories: set[str] = set()
        outcomes: set[str] = set()
        accepted_split_kinds: set[str] = set()
        rejected_rules: set[str] = set()
        category_counts: Counter[str] = Counter()
        for entry in catalog["cases"]:
            with self.subTest(case_id=entry["case_id"]):
                self.assertEqual(
                    set(entry),
                    {
                        "case_id",
                        "category",
                        "locator",
                        "sha256",
                        "expected",
                        "rule_id",
                    },
                )
                categories.add(entry["category"])
                category_counts[entry["category"]] += 1
                outcomes.add(entry["expected"])
                path = (_ROOT / entry["locator"]).resolve()
                path.relative_to(_ROOT.resolve())
                fixture_root = (
                    _ROOT
                    / "tests"
                    / "fixtures"
                    / "adapters"
                    / "ml-case"
                    / "v1"
                    / "valid"
                ).resolve()
                path.relative_to(fixture_root)
                raw = path.read_bytes()
                self.assertEqual(
                    _repository_normalized_sha256(raw), entry["sha256"]
                )
                payload = load_strict_json(raw)
                if entry["expected"] == "accepted":
                    self.assertIsNone(entry["rule_id"])
                    accepted_split_kinds.add(payload["split"]["kind"])
                    self.assertEqual(
                        adapter.build_evaluation_contract(payload).payload["schema"],
                        "evaluation-contract/v3",
                    )
                else:
                    self.assertEqual(entry["expected"], "rejected")
                    self.assertIsInstance(entry["rule_id"], str)
                    rejected_rules.add(entry["rule_id"])
                    with self.assertRaises(AdapterError) as ctx:
                        adapter.build_evaluation_contract(payload)
                    self.assertIn(entry["rule_id"], str(ctx.exception))
        self.assertEqual(
            categories,
            {"contract-positive", "leakage-negative", "semantic-negative"},
        )
        self.assertEqual(outcomes, {"accepted", "rejected"})
        self.assertEqual(
            category_counts,
            {
                "contract-positive": 4,
                "leakage-negative": 12,
                "semantic-negative": 4,
            },
        )
        self.assertEqual(
            accepted_split_kinds, {"iid", "group", "time_series", "nested"}
        )
        self.assertEqual(
            rejected_rules,
            {
                "preprocessing-fit-full-data",
                "feature-selection-fit-full-data",
                "sampling-scope-unsafe",
                "scope-upstream-mismatch",
                "target-encoding-not-per-fold",
                "tuning-uses-protected-split",
                "selection-uses-test",
                "split-parameters-kind-contract",
                "tuning-seed-count-floor",
            },
        )


class MLSyntheticVerticalSliceTest(unittest.TestCase):
    def _assert_public_chain(self, dataset: dict, case: dict, kind: str) -> None:
        adapter = MLAdapter()
        domain_task = load_strict_json(_TASK.read_bytes())
        domain_task["study_id"] = case["study_id"]
        task = adapter.normalize_task(domain_task)
        core_task = load_record(canonical_bytes(task.to_core_task_payload()))
        contract = adapter.build_evaluation_contract(case)
        result = run_synthetic_experiment(
            dataset,
            case,
            contract=contract,
            final_partition="test",
        )
        claim = load_strict_json(_CLAIM.read_bytes())
        claim["study_id"] = case["study_id"]
        claim["case_sha256"] = canonical_sha256(case)
        assessment = adapter.validate_claim(claim, [result.evidence], contract)

        self.assertEqual(core_task.schema_id, "research-task/v1")
        self.assertEqual(core_task.data["domain"], "ml")
        self.assertEqual(result.artifact["split_validation"]["kind"], kind)
        self.assertEqual(
            result.evidence["final_evaluation"]["split_sha256"],
            case["split"]["sha256"],
        )
        self.assertTrue(result.artifact["parity"]["resource_parity"])
        self.assertEqual(assessment.suggested_disposition, "inconclusive")
        self.assertIn("synthetic-evidence-cap", assessment.triggered_rules)
        for gap_rule in (
            "ood-assessment-missing",
            "subgroup-assessment-missing",
            "calibration-not-assessed",
            "drift-not-assessed",
        ):
            self.assertIn(gap_rule, assessment.triggered_rules)

    def test_non_time_group_split_public_chain(self) -> None:
        self._assert_public_chain(*_group_payload(), "group")

    def test_time_series_gap_embargo_public_chain(self) -> None:
        self._assert_public_chain(*_time_series_payload(), "time_series")

    def test_both_slices_repeat_byte_identically(self) -> None:
        for label, build in (
            ("group", _group_payload),
            ("time_series", _time_series_payload),
        ):
            with self.subTest(slice=label):
                dataset, case = build()
                contract = MLAdapter().build_evaluation_contract(case)
                results = [
                    run_synthetic_experiment(
                        dataset,
                        case,
                        contract=contract,
                        final_partition="test",
                    )
                    for _ in range(3)
                ]
                self.assertEqual(len({result.artifact_sha256 for result in results}), 1)
                self.assertEqual(results[0].artifact["seeds"], [3, 5, 7])
                self.assertEqual(len(results[0].artifact["per_seed"]), 3)


if __name__ == "__main__":
    unittest.main()
