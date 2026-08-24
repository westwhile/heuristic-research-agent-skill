"""Behavioral tests for the M4 taxonomy machine and layered clustering."""

import hashlib
import json
import unittest
from pathlib import Path

from research_evolution.experience import (
    append_cluster_event,
    cluster_cases,
    compose_taxonomy,
    load_taxonomy,
    verify_cluster_log,
)
from tests.unit.test_experience_cases import _base_kwargs
from tests.unit.test_experience_patterns import _make_case

REPO_ROOT = Path(__file__).resolve().parents[2]
TAXONOMIES = REPO_ROOT / "taxonomies"


def _taxonomy_data(name: str) -> dict:
    return json.loads((TAXONOMIES / name).read_text(encoding="utf-8"))


def _general():
    return load_taxonomy(_taxonomy_data("general-v1.json"))


def _composed():
    return compose_taxonomy(
        _general(),
        load_taxonomy(_taxonomy_data("math-overlay-v1.json")),
        load_taxonomy(_taxonomy_data("quant-overlay-v1.json")),
    )


class TaxonomyTest(unittest.TestCase):
    def test_builtin_taxonomies_load_and_compose(self) -> None:
        general = _general()
        self.assertEqual(len(general.paths), 6)
        self.assertIn(("algorithm-design",), general.paths)
        composed = _composed()
        self.assertIn(("algorithm-design", "lemma-decomposition"), composed.paths)
        self.assertIn(("data-integrity", "survivorship-screening"), composed.paths)
        self.assertIn(("evaluation-methodology", "walk-forward-protocol"), composed.paths)
        self.assertEqual(composed.version, "general-v1+math-overlay-v1+quant-overlay-v1")
        self.assertEqual(compose_taxonomy(_general()).sha256, compose_taxonomy(_general()).sha256)

    def test_overlay_parent_pin_enforced(self) -> None:
        general = _general()
        overlay_data = _taxonomy_data("math-overlay-v1.json")
        overlay_data["parent_sha256"] = "0" * 64
        overlay = load_taxonomy(overlay_data)
        with self.assertRaisesRegex(ValueError, "pins parent"):
            compose_taxonomy(general, overlay)

    def test_overlay_attachment_enforced(self) -> None:
        general = _general()
        overlay = load_taxonomy(
            {
                "version": "bad-overlay",
                "parent_sha256": general.sha256,
                "nodes": {"no-such-node": {"child": {}}},
            }
        )
        with self.assertRaisesRegex(ValueError, "does not attach"):
            compose_taxonomy(general, overlay)

    def test_load_bad_shapes_refused(self) -> None:
        for bad in (
            {"nodes": {}},
            {"version": "v", "nodes": []},
            {"version": "v", "nodes": {"": {}}},
            {"version": "v", "nodes": {"x": []}},
            {"version": "v", "nodes": {}, "parent_sha256": "short"},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    load_taxonomy(bad)


class ClusterTest(unittest.TestCase):
    def test_exact_fingerprint_tier(self) -> None:
        same_a = _make_case("case-a")
        same_b = _make_case("case-b")
        other = _make_case("case-c", sig=b"other")
        clusters = cluster_cases([other, same_b, same_a])
        by_tier = {cluster.tier: cluster for cluster in clusters}
        exact = by_tier["exact_fingerprint"]
        self.assertEqual(
            [pin["case_id"] for pin in exact.members], ["case-a", "case-b"]
        )
        self.assertEqual(by_tier["singleton"].members[0]["case_id"], "case-c")
        again = cluster_cases([same_a, same_b, other])
        self.assertEqual(
            [cluster.cluster_id for cluster in clusters],
            [cluster.cluster_id for cluster in again],
        )

    def test_structural_fields_tier(self) -> None:
        left = _make_case("case-a", sig=b"one", facets={"area": "general"})
        right = _make_case("case-b", sig=b"two", facets={"area": "general"})
        lone = _make_case("case-c", sig=b"three", facets={"area": "other"})
        clusters = cluster_cases([left, right, lone])
        tiers = {cluster.tier for cluster in clusters}
        self.assertIn("structural_fields", tiers)
        structural = [c for c in clusters if c.tier == "structural_fields"][0]
        self.assertEqual(len(structural.members), 2)

    def test_taxonomy_path_tier(self) -> None:
        composed = _composed()
        left = _make_case(
            "case-a",
            sig=b"one",
            facets={"taxonomy_path": ["algorithm-design"], "note": "x"},
        )
        right = _make_case(
            "case-b",
            sig=b"two",
            facets={"taxonomy_path": ["algorithm-design"], "note": "y"},
        )
        invalid_path = _make_case(
            "case-c",
            sig=b"three",
            facets={"taxonomy_path": ["no-such-node"]},
        )
        clusters = cluster_cases([left, right, invalid_path], taxonomy=composed)
        tiers = {cluster.tier: cluster for cluster in clusters}
        self.assertEqual(
            [pin["case_id"] for pin in tiers["taxonomy_path"].members],
            ["case-a", "case-b"],
        )
        self.assertEqual(tiers["singleton"].members[0]["case_id"], "case-c")
        without_taxonomy = cluster_cases([left, right])
        self.assertNotIn(
            "taxonomy_path", {cluster.tier for cluster in without_taxonomy}
        )

    def test_semantic_proposal_tier(self) -> None:
        left = _make_case("case-a", sig=b"one", summary="lorem ipsum dolor")
        right = _make_case("case-b", sig=b"two", summary="lorem ipsum sit")
        lone = _make_case("case-c", sig=b"three", summary="zzz qqq unique words")
        clusters = cluster_cases([left, right, lone])
        by_tier = {cluster.tier: cluster for cluster in clusters}
        proposal = by_tier["semantic_proposal"]
        self.assertEqual(
            [pin["case_id"] for pin in proposal.members], ["case-a", "case-b"]
        )
        self.assertIn("proposal only", proposal.rationale)
        self.assertEqual(by_tier["singleton"].members[0]["case_id"], "case-c")

    def test_semantic_threshold_gates(self) -> None:
        left = _make_case("case-a", sig=b"one", summary="lorem ipsum dolor")
        right = _make_case("case-b", sig=b"two", summary="lorem ipsum sit")
        clusters = cluster_cases([left, right], semantic_threshold=0.6)
        self.assertEqual({cluster.tier for cluster in clusters}, {"singleton"})
        with self.assertRaises(ValueError):
            cluster_cases([left], semantic_threshold=0.0)
        with self.assertRaises(ValueError):
            cluster_cases([left], semantic_threshold=True)

    def test_unrelated_cjk_and_tokenless_text_stay_singletons(self) -> None:
        pairs = (
            ("量化金融中的因子回测", "深度学习图像分类完全无关"),
            ("🧪🧪", "🚀🚀"),
        )
        for index, (left_summary, right_summary) in enumerate(pairs):
            with self.subTest(pair=index):
                left = _make_case(
                    f"case-{index}-a",
                    sig=f"{index}-a".encode(),
                    summary=left_summary,
                )
                right = _make_case(
                    f"case-{index}-b",
                    sig=f"{index}-b".encode(),
                    summary=right_summary,
                )
                clusters = cluster_cases([left, right])
                self.assertEqual(
                    [cluster.tier for cluster in clusters],
                    ["singleton", "singleton"],
                )

    def test_unicode_semantic_proposals_preserve_domain_tokens(self) -> None:
        related_pairs = (
            ("量化金融因子回测校验", "量化金融因子回测验证"),
            ("時系列モデルを検証する", "時系列モデルを再検証する"),
            ("$AAPL 量化金融因子回测校验", "$AAPL 量化金融因子回测验证"),
            ("检验 x^2+y^2 模型残差", "验证 x^2+y^2 模型残差"),
            (
                "000001.SZ 量化因子暴露风险检查",
                "000001.SZ 量化因子暴露风险验证",
            ),
        )
        for index, (left_summary, right_summary) in enumerate(related_pairs):
            with self.subTest(pair=index):
                left = _make_case(
                    f"case-u-{index}-a",
                    sig=f"u-{index}-a".encode(),
                    summary=left_summary,
                )
                right = _make_case(
                    f"case-u-{index}-b",
                    sig=f"u-{index}-b".encode(),
                    summary=right_summary,
                )
                clusters = cluster_cases(
                    [left, right], semantic_threshold=0.4
                )
                self.assertEqual(len(clusters), 1)
                self.assertEqual(clusters[0].tier, "semantic_proposal")

    def test_duplicate_case_id_refused(self) -> None:
        case = _make_case("case-a")
        with self.assertRaisesRegex(ValueError, "duplicate case_id"):
            cluster_cases([case, case])

    def test_non_case_payload_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "research-case-package/v2"):
            cluster_cases([_make_case("case-a"), _base_kwargs()["task"]])


class ClusterEventLogTest(unittest.TestCase):
    def test_append_chain_verify_and_tamper(self) -> None:
        log = ()
        log = append_cluster_event(
            log,
            kind="merge",
            cluster_ids=["singleton-b", "singleton-a"],
            rationale="same fingerprint",
            at="2026-08-17T09:10:00Z",
        )
        original = log
        log = append_cluster_event(
            log,
            kind="split",
            cluster_ids=["exact_fingerprint-abc"],
            rationale="facets diverged",
            at="2026-08-17T09:20:00Z",
        )
        verify_cluster_log(log)
        self.assertEqual(len(log), 2)
        self.assertEqual(log[0]["cluster_ids"], ["singleton-a", "singleton-b"])
        self.assertEqual(log[1]["prev_sha256"], log[0]["event_sha256"])
        # The input log is never mutated.
        self.assertEqual(len(original), 1)
        tampered = [dict(log[0], rationale="edited"), log[1]]
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify_cluster_log(tampered)
        reordered = [log[1], log[0]]
        with self.assertRaisesRegex(ValueError, "chain broken"):
            verify_cluster_log(reordered)

    def test_event_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "merge or split"):
            append_cluster_event(
                (), kind="delete", cluster_ids=["c"], rationale="r", at="t"
            )
        with self.assertRaisesRegex(ValueError, "at least one"):
            append_cluster_event((), kind="merge", cluster_ids=[], rationale="r", at="t")
        with self.assertRaisesRegex(ValueError, "rationale"):
            append_cluster_event((), kind="merge", cluster_ids=["c"], rationale=" ", at="t")


if __name__ == "__main__":
    unittest.main()
