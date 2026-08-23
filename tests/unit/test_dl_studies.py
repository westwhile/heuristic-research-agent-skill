"""Phase 6 L4 synthetic study reporting and resource-parity tests."""

import ast
import dataclasses
import os
import tempfile
import unittest
from pathlib import Path

from research_evolution.adapters.deep_learning import DLRunManifest
from research_evolution.adapters.deep_learning.runner import run_fixture
from research_evolution.adapters.deep_learning.selection import select_fixture_runs
from research_evolution.adapters.deep_learning.studies import (
    DLStudyArmEvidence,
    DLStudyError,
    build_fixture_study_report,
    reporter_identity,
)
from research_evolution.core import canonical_bytes, load_strict_json

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"
MANIFEST_FIXTURE = FIXTURES / "dl-run-manifest" / "v1" / "valid" / "minimal.json"
STUDIES_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "research_evolution"
    / "adapters"
    / "deep_learning"
    / "studies.py"
)
CASE_SHA256 = "1" * 64
SEEDS = (1, 2, 3)


def _manifest(run_id: str, study_id: str) -> DLRunManifest:
    payload = load_strict_json(MANIFEST_FIXTURE.read_bytes())
    payload["manifest_id"] = f"manifest-{run_id}"
    payload["run_id"] = run_id
    payload["study_id"] = study_id
    payload["runner"]["version"] = "0.2.0"
    payload["budget"].update(
        {
            "max_samples": 4,
            "max_steps": 20,
            "max_epochs": 20,
            "max_tokens": 0,
            "max_flops": 1_000_000,
            "cost_limit": 60,
        }
    )
    payload["checkpoint_policy"].update(
        {"retention": "best_and_last", "max_retained": 2}
    )
    return DLRunManifest.from_payload(payload)


def _fixture(
    seed: int,
    *,
    hidden_units: int,
    requested_steps: int,
    early_stopping: bool,
    failure: str = "none",
) -> dict:
    return {
        "schema": "synthetic-dl-fixture/v2",
        "fixture_id": "tiny-regression-l4",
        "features": [[-1.0], [0.0], [1.0], [2.0]],
        "targets": [-1.0, 1.0, 3.0, 5.0],
        "validation_features": [[-0.5], [0.5], [1.5]],
        "validation_targets": [0.0, 2.0, 4.0],
        "hidden_units": hidden_units,
        "learning_rate": 0.05,
        "requested_steps": requested_steps,
        "seed": seed,
        "failure_injection": {
            "kind": failure,
            "at_step": 1 if failure != "none" else 0,
        },
        "early_stopping": {
            "enabled": early_stopping,
            "patience": requested_steps if early_stopping else 0,
            "min_delta": 0,
            "warmup_steps": 0,
        },
    }


def _arm(
    arm_id: str,
    *,
    hidden_units: int,
    requested_steps: int,
    early_stopping: bool = False,
    failure_seed: int | None = None,
    failure_kind: str = "none",
) -> DLStudyArmEvidence:
    study_id = f"study-{arm_id}"
    manifests = tuple(
        _manifest(f"{arm_id}-seed-{seed}", study_id) for seed in SEEDS
    )
    fixtures = tuple(
        _fixture(
            seed,
            hidden_units=hidden_units,
            requested_steps=requested_steps,
            early_stopping=early_stopping,
            failure=(failure_kind if seed == failure_seed else "none"),
        )
        for seed in SEEDS
    )
    runs = tuple(
        run_fixture(manifest, fixture)
        for manifest, fixture in zip(manifests, fixtures, strict=True)
    )
    plan = {
        "schema": "synthetic-dl-selection-plan/v1",
        "selection_id": f"selection-{arm_id}",
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
    return DLStudyArmEvidence(
        select_fixture_runs(runs, plan), runs, manifests, fixtures
    )


def _plan(kind: str) -> dict:
    factor = "early_stopping" if kind == "ablation" else "hidden_units"
    matching = {
        "ablation": "all_consumed_dimensions",
        "scale": "none",
        "compute_matched": "flops_proxy",
    }[kind]
    return {
        "schema": "synthetic-dl-study-plan/v1",
        "report_id": f"l4-{kind}-report",
        "comparison_kind": kind,
        "declared_factor": factor,
        "matching_dimension": matching,
        "arms": [
            {
                "arm_id": "baseline",
                "role": "baseline",
                "selection_id": "selection-baseline",
            },
            {
                "arm_id": "candidate",
                "role": "candidate",
                "selection_id": "selection-candidate",
            },
        ],
    }


def _ablation_evidence() -> dict[str, DLStudyArmEvidence]:
    return {
        "baseline": _arm(
            "baseline", hidden_units=3, requested_steps=6, early_stopping=False
        ),
        "candidate": _arm(
            "candidate", hidden_units=3, requested_steps=6, early_stopping=True
        ),
    }


def _scale_evidence() -> dict[str, DLStudyArmEvidence]:
    return {
        "baseline": _arm("baseline", hidden_units=2, requested_steps=6),
        "candidate": _arm("candidate", hidden_units=4, requested_steps=6),
    }


def _compute_evidence() -> dict[str, DLStudyArmEvidence]:
    return {
        "baseline": _arm("baseline", hidden_units=2, requested_steps=8),
        "candidate": _arm("candidate", hidden_units=4, requested_steps=4),
    }


class DLStudyReportTest(unittest.TestCase):
    def test_identity_and_deterministic_canonical_report(self) -> None:
        self.assertEqual(
            reporter_identity(),
            {"name": "reference-dl-study-reporter", "version": "0.1.0"},
        )
        evidence = _compute_evidence()
        first = build_fixture_study_report(_plan("compute_matched"), evidence)
        second = build_fixture_study_report(_plan("compute_matched"), evidence)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(
            first.sha256,
            "b0ab85d04a3288d9d5256253ca176bcf75efe5801dfae678151d57314e5e854e",
        )
        self.assertEqual(first.status, "eligible_descriptive_comparison")

    def test_ablation_changes_one_factor_with_full_resource_parity(self) -> None:
        report = build_fixture_study_report(_plan("ablation"), _ablation_evidence())
        comparison = report.artifact["comparison"]
        self.assertEqual(comparison["status"], "eligible_descriptive_comparison")
        self.assertTrue(comparison["comparison_allowed"])
        self.assertTrue(comparison["resource_parity"])
        self.assertFalse(comparison["capability_claim_allowed"])

    def test_scale_is_descriptive_and_surfaces_compute_mismatch(self) -> None:
        report = build_fixture_study_report(_plan("scale"), _scale_evidence())
        comparison = report.artifact["comparison"]
        self.assertEqual(comparison["status"], "descriptive_scale_only")
        self.assertFalse(comparison["comparison_allowed"])
        self.assertFalse(comparison["resource_parity"])
        self.assertIsNone(comparison["candidate_minus_baseline_mean"])
        self.assertTrue(
            any("flops_proxy" in field for field in comparison["resource_mismatch_fields"])
        )

    def test_compute_matched_allows_steps_to_differ_but_matches_flops(self) -> None:
        report = build_fixture_study_report(
            _plan("compute_matched"), _compute_evidence()
        ).artifact
        comparison = report["comparison"]
        self.assertTrue(comparison["resource_parity"])
        self.assertEqual(comparison["resource_mismatch_fields"], [])
        by_role = {arm["role"]: arm for arm in report["arms"]}
        self.assertEqual(
            by_role["baseline"]["consumed_by_seed"][0]["consumed"]["flops_proxy"],
            by_role["candidate"]["consumed_by_seed"][0]["consumed"]["flops_proxy"],
        )
        self.assertNotEqual(
            by_role["baseline"]["consumed_by_seed"][0]["consumed"]["steps"],
            by_role["candidate"]["consumed_by_seed"][0]["consumed"]["steps"],
        )

    def test_failed_seed_blocks_comparison_and_remains_in_inventory(self) -> None:
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
        artifact = build_fixture_study_report(_plan("ablation"), evidence).artifact
        self.assertEqual(artifact["comparison"]["status"], "incomplete_evidence")
        self.assertFalse(artifact["comparison"]["comparison_allowed"])
        self.assertIsNone(
            artifact["comparison"]["candidate_minus_baseline_mean"]
        )
        self.assertEqual(len(artifact["failure_inventory"]), 1)
        failure = artifact["failure_inventory"][0]
        self.assertEqual(failure["seed"], 3)
        self.assertEqual(failure["failure_class"], "resource_exhausted")

    def test_report_contains_references_not_checkpoint_payloads(self) -> None:
        report = build_fixture_study_report(
            _plan("compute_matched"), _compute_evidence()
        )
        encoded = canonical_bytes(report.artifact).decode("utf-8")
        self.assertIn("checkpoint://", encoded)
        self.assertIn("content_sha256", encoded)
        self.assertNotIn("model_state", encoded)
        self.assertNotIn('"optimizer_state":', encoded)
        self.assertEqual(
            report.artifact["artifact_retention"]["checkpoint_payloads"],
            "not_read_or_persisted",
        )

    def test_report_is_frozen_and_defensive(self) -> None:
        report = build_fixture_study_report(
            _plan("compute_matched"), _compute_evidence()
        )
        before = report.sha256
        artifact = report.artifact
        artifact["comparison"]["status"] = "tampered"
        self.assertEqual(report.sha256, before)
        self.assertEqual(report.status, "eligible_descriptive_comparison")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report._artifact_bytes = b"{}"

    def test_no_filesystem_side_effects(self) -> None:
        plan = _plan("compute_matched")
        evidence = _compute_evidence()
        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                build_fixture_study_report(plan, evidence)
                leftovers = list(Path(temp).rglob("*"))
            finally:
                os.chdir(previous)
        self.assertEqual(leftovers, [])

    def test_dependency_surface_is_standard_library_and_l3_results_only(self) -> None:
        tree = ast.parse(STUDIES_SOURCE.read_text(encoding="utf-8"))
        absolute_imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        from_imports = {
            (node.level, node.module)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertEqual(absolute_imports, {"hashlib"})
        self.assertEqual(
            from_imports,
            {
                (0, "__future__"),
                (0, "collections.abc"),
                (0, "dataclasses"),
                (0, "typing"),
                (0, "research_evolution.core"),
                (1, "manifest"),
                (1, "runner"),
                (1, "selection"),
            },
        )


class DLStudyInputGateTest(unittest.TestCase):
    def test_wrong_declared_factor_and_matching_dimension_fail_closed(self) -> None:
        plan = _plan("compute_matched")
        plan["declared_factor"] = "learning_rate"
        with self.assertRaisesRegex(DLStudyError, "declared_factor"):
            build_fixture_study_report(plan, _compute_evidence())

        plan = _plan("compute_matched")
        plan["matching_dimension"] = "steps"
        with self.assertRaisesRegex(DLStudyError, "matching_dimension"):
            build_fixture_study_report(plan, _compute_evidence())

    def test_arm_keys_and_selection_binding_fail_closed(self) -> None:
        evidence = _compute_evidence()
        with self.assertRaisesRegex(DLStudyError, "keys must exactly match"):
            build_fixture_study_report(
                _plan("compute_matched"), {"baseline": evidence["baseline"]}
            )

        plan = _plan("compute_matched")
        plan["arms"][1]["selection_id"] = "wrong-selection"
        with self.assertRaisesRegex(DLStudyError, "selection_id"):
            build_fixture_study_report(plan, evidence)

    def test_unregistered_run_and_changed_frozen_axis_fail_closed(self) -> None:
        evidence = _compute_evidence()
        extra = _arm("extra", hidden_units=4, requested_steps=4).runs[0]
        bad_candidate = DLStudyArmEvidence(
            evidence["candidate"].selection,
            evidence["candidate"].runs + (extra,),
            evidence["candidate"].manifests
            + (_manifest("extra-seed-1", "study-extra"),),
            evidence["candidate"].fixtures
            + (
                _fixture(
                    1,
                    hidden_units=4,
                    requested_steps=4,
                    early_stopping=False,
                ),
            ),
        )
        with self.assertRaisesRegex(DLStudyError, "study_id"):
            build_fixture_study_report(
                _plan("compute_matched"),
                {"baseline": evidence["baseline"], "candidate": bad_candidate},
            )

        wrong_case_runs = []
        wrong_case_manifests = []
        wrong_case_fixtures = []
        for seed in SEEDS:
            manifest = _manifest(f"candidate-seed-{seed}", "study-candidate").payload
            manifest["case_sha256"] = "9" * 64
            manifest = DLRunManifest.from_payload(manifest)
            fixture = _fixture(
                seed,
                hidden_units=4,
                requested_steps=4,
                early_stopping=False,
            )
            wrong_case_runs.append(
                run_fixture(manifest, fixture)
            )
            wrong_case_manifests.append(manifest)
            wrong_case_fixtures.append(fixture)
        with self.assertRaisesRegex(DLStudyError, "case_sha256"):
            build_fixture_study_report(
                _plan("compute_matched"),
                {
                    "baseline": evidence["baseline"],
                    "candidate": DLStudyArmEvidence(
                        evidence["candidate"].selection,
                        tuple(wrong_case_runs),
                        tuple(wrong_case_manifests),
                        tuple(wrong_case_fixtures),
                    ),
                },
            )

    def test_manifest_and_fixture_hash_bindings_fail_closed(self) -> None:
        evidence = _compute_evidence()
        candidate = evidence["candidate"]
        tampered_fixtures = list(candidate.fixtures)
        tampered_fixtures[0] = {
            **tampered_fixtures[0],
            "learning_rate": 0.2,
        }
        with self.assertRaisesRegex(DLStudyError, "fixture hash"):
            build_fixture_study_report(
                _plan("compute_matched"),
                {
                    "baseline": evidence["baseline"],
                    "candidate": DLStudyArmEvidence(
                        candidate.selection,
                        candidate.runs,
                        candidate.manifests,
                        tuple(tampered_fixtures),
                    ),
                },
            )

        wrong_manifests = list(candidate.manifests)
        wrong_manifests[0] = _manifest(
            "candidate-seed-1", "study-candidate"
        )
        wrong_payload = wrong_manifests[0].payload
        wrong_payload["hardware"]["device_model"] = "different-declaration"
        wrong_manifests[0] = DLRunManifest.from_payload(wrong_payload)
        with self.assertRaisesRegex(DLStudyError, "manifest hash"):
            build_fixture_study_report(
                _plan("compute_matched"),
                {
                    "baseline": evidence["baseline"],
                    "candidate": DLStudyArmEvidence(
                        candidate.selection,
                        candidate.runs,
                        tuple(wrong_manifests),
                        candidate.fixtures,
                    ),
                },
            )


if __name__ == "__main__":
    unittest.main()
