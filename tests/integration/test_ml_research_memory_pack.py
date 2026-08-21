"""L6 acceptance tests for the synthetic ML research-memory evidence pack."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from research_evolution.core import (
    canonical_bytes,
    canonical_sha256,
    load_record,
    publish_record,
    verify_record_graph,
)
from research_evolution.experience import (
    assert_no_promoted_skill,
    build_heuristic_index,
    heuristic_chain,
)
from tests.integration._ml_research_memory_pack import (
    build_ml_research_memory_pack,
)


_ROOT = Path(__file__).resolve().parents[2]
_STAGING = _ROOT / "staging" / "research-memory"
_ML_ROOT = _STAGING / "evidence" / "ml"


class MLResearchMemoryPackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.built = build_ml_research_memory_pack()

    def test_builder_produces_the_frozen_counts(self) -> None:
        self.assertEqual(len(self.built["files"]), 38)
        self.assertEqual(len(self.built["records"]), 32)
        self.assertEqual(len(self.built["cases"]), 4)
        self.assertEqual(len(self.built["patterns"]), 2)
        self.assertEqual(len(self.built["heuristic_versions"]), 9)
        self.assertEqual(len(self.built["heuristic_tips"]), 3)

    def test_four_capture_categories_are_exact_and_synthetic(self) -> None:
        self.assertEqual(
            set(self.built["bundles"]),
            {
                "protocol",
                "negative-result",
                "leakage-repair",
                "reproduction-difference",
            },
        )
        for slug, bundle in self.built["bundles"].items():
            with self.subTest(slug=slug):
                self.assertEqual(bundle["kind"], "ml-research-memory-capture/v1")
                self.assertEqual(bundle["category"], slug)
                self.assertEqual(bundle["provenance"], "synthetic")
                self.assertTrue(bundle["limitations"])

    def test_protocol_generalization_claim_matches_its_assessment(self) -> None:
        bundle = self.built["bundles"]["protocol"]
        claim = bundle["protocol"]["claim"]
        assessment = bundle["execution"]["assessment"]
        self.assertEqual(claim["claim_class"], "generalization")
        self.assertIn("baseline", claim["statement"].lower())
        self.assertIn("test", claim["statement"].lower())
        self.assertEqual(assessment["suggested_claim_type"], "empirical_claim")
        self.assertEqual(assessment["suggested_disposition"], "inconclusive")
        self.assertIn("synthetic-evidence-cap", assessment["triggered_rules"])

    def test_every_core_record_validates_and_ids_are_unique(self) -> None:
        identities: set[tuple[str, str]] = set()
        identity_field = {
            "research-task/v1": "task_id",
            "research-run/v1": "run_id",
            "research-claim/v1": "claim_id",
            "research-evidence/v1": "evidence_id",
            "research-failure-observation/v1": "observation_id",
            "research-failure-analysis/v1": "analysis_id",
            "research-case-package/v2": "case_id",
            "research-pattern/v1": "pattern_id",
            "heuristic/v1": "heuristic_id",
        }
        for payload in self.built["records"]:
            record = load_record(canonical_bytes(payload))
            key = (record.schema_id, record.data[identity_field[record.schema_id]])
            self.assertNotIn(key, identities)
            identities.add(key)

    def test_complete_core_record_graph_closes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ml-l6-graph-") as tmp:
            root = Path(tmp) / "store"
            for payload in self.built["records"]:
                publish_record(canonical_bytes(payload), root=root)
            report = verify_record_graph(root)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.records_total, 32)

    def test_case_packages_are_eligible_and_member_complete(self) -> None:
        for slug, case in self.built["cases"].items():
            with self.subTest(slug=slug):
                self.assertEqual(case["schema"], "research-case-package/v2")
                self.assertEqual(case["eligibility"], {"status": "eligible", "reasons": []})
                self.assertEqual(case["privacy_review_status"], "passed")
                self.assertEqual(case["export_mode"], "benchmark_candidate")
                self.assertEqual(len(case["runs"]), 1)
                self.assertEqual(len(case["claims"]), 1)
                self.assertEqual(len(case["evidence"]), 1)
                self.assertTrue(case["decision_timeline"])

    def test_case_artifact_manifests_bind_the_canonical_bundles(self) -> None:
        for slug, case in self.built["cases"].items():
            with self.subTest(slug=slug):
                bundle = self.built["bundles"][slug]
                output = case["io_manifest"]["outputs"][0]
                self.assertEqual(
                    output["sha256"], hashlib.sha256(canonical_bytes(bundle)).hexdigest()
                )
                self.assertEqual(
                    output["locator"], f"evidence/ml/captures/{slug}.json"
                )
                protocol = case["io_manifest"]["inputs"][0]
                self.assertEqual(
                    protocol["sha256"],
                    hashlib.sha256(canonical_bytes(bundle["protocol"])).hexdigest(),
                )

    def test_candidate_pattern_is_cross_case_and_never_a_skill(self) -> None:
        distilled, candidate = self.built["patterns"]
        self.assertEqual(distilled["status"], "distilled")
        self.assertEqual(candidate["status"], "candidate_pattern")
        self.assertEqual(candidate["supersedes"], distilled["pattern_id"])
        self.assertEqual(len(candidate["source_cases"]), 2)
        self.assertEqual(
            {pin["case_id"] for pin in candidate["source_cases"]},
            {"case-ml-leakage-repair", "case-ml-reproduction-difference"},
        )
        self.assertEqual(candidate["confidence"], "low")
        assert_no_promoted_skill(candidate)

    def test_three_heuristic_chains_end_at_shadow(self) -> None:
        versions = self.built["heuristic_versions"]
        index = build_heuristic_index(versions)
        self.assertEqual(len(index.tips), 3)
        self.assertEqual(set(index.tips), {item["heuristic_id"] for item in self.built["heuristic_tips"]})
        for tip in index.tips:
            with self.subTest(tip=tip):
                chain = heuristic_chain(index, tip)
                self.assertEqual(
                    [entry["status"] for entry in chain],
                    ["shadow", "candidate", "lesson_hypothesis"],
                )
                self.assertEqual(len(chain[0]["regression_cases"]), 1)

    def test_heuristic_lint_has_no_rejections(self) -> None:
        report = self.built["lint_report"]
        self.assertEqual(report.rejections, ())
        self.assertEqual(report.report_entry["tips"], 3)
        self.assertEqual(report.report_sha256, canonical_sha256(report.report_entry))

    def test_shadow_report_is_hypothetical_and_exactly_three(self) -> None:
        report = self.built["shadow_report"]
        payload = report.payload
        self.assertEqual(payload["kind"], "shadow-report")
        self.assertNotIn("schema", payload)
        self.assertEqual(len(payload["heuristics"]), 3)
        self.assertEqual(len(payload["observations"]), 3)
        self.assertEqual(report.sha256, canonical_sha256(payload))
        for observation in payload["observations"]:
            self.assertIn("would", observation["hypothetical_decision"])

    def test_evidence_boundary_stays_engineering_only(self) -> None:
        for payload in self.built["records"]:
            if payload["schema"] == "research-claim/v1":
                self.assertEqual(payload["claim_type"], "engineering_claim")
                self.assertEqual(payload["evidence_maturity"], "engineering_verified")
                joined = " ".join(payload["non_entailments"]).lower()
                self.assertIn("real-data", joined)
                self.assertIn("skill", joined)
            elif payload["schema"] == "research-evidence/v1":
                self.assertEqual(payload["evidence_level"], "engineering-only")
        self.assertEqual(list(_ML_ROOT.rglob("SKILL.md")), [])

    def test_materialized_ml_tree_matches_rebuild_byte_for_byte(self) -> None:
        expected = {
            path.removeprefix("evidence/ml/"): content
            for path, content in self.built["files"].items()
        }
        on_disk = {
            path.relative_to(_ML_ROOT).as_posix(): path.read_bytes()
            for path in sorted(_ML_ROOT.rglob("*.json"))
        }
        self.assertEqual(set(on_disk), set(expected))
        for path, content in expected.items():
            with self.subTest(path=path):
                self.assertEqual(on_disk[path], content)


if __name__ == "__main__":
    unittest.main()
