"""Phase 6 L3 checkpoint, exact-recovery, and early-stopping tests."""

import copy
import json
import unittest
from pathlib import Path

from research_evolution.adapters.deep_learning import DLRunManifest
from research_evolution.adapters.deep_learning.runner import (
    DLRunnerError,
    run_fixture,
)
from research_evolution.core import canonical_sha256, load_strict_json

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"
MANIFEST_FIXTURE = FIXTURES / "dl-run-manifest" / "v1" / "valid" / "minimal.json"


def _manifest_payload(run_id: str, *, retention: str = "best_and_last") -> dict:
    payload = load_strict_json(MANIFEST_FIXTURE.read_bytes())
    payload["manifest_id"] = f"manifest-{run_id}"
    payload["run_id"] = run_id
    payload["runner"]["version"] = "0.2.0"
    payload["budget"].update(
        {"max_steps": 20, "max_epochs": 20, "max_flops": 0}
    )
    payload["checkpoint_policy"]["retention"] = retention
    payload["checkpoint_policy"]["max_retained"] = {
        "none": 0,
        "last": 1,
        "best_and_last": 2,
        "all": 0,
    }[retention]
    return payload


def _manifest(run_id: str, *, retention: str = "best_and_last") -> DLRunManifest:
    return DLRunManifest.from_payload(
        _manifest_payload(run_id, retention=retention)
    )


def _fixture(
    *,
    seed: int = 7,
    requested_steps: int = 8,
    early_stopping: dict | None = None,
    failure: str = "none",
    at_step: int = 0,
) -> dict:
    return {
        "schema": "synthetic-dl-fixture/v2",
        "fixture_id": "tiny-regression-l3",
        "features": [[-1.0], [0.0], [1.0], [2.0]],
        "targets": [-1.0, 1.0, 3.0, 5.0],
        "validation_features": [[-0.5], [0.5], [1.5]],
        "validation_targets": [0.0, 2.0, 4.0],
        "hidden_units": 3,
        "learning_rate": 0.05,
        "requested_steps": requested_steps,
        "seed": seed,
        "failure_injection": {"kind": failure, "at_step": at_step},
        "early_stopping": early_stopping
        or {"enabled": False, "patience": 0, "min_delta": 0, "warmup_steps": 0},
    }


def _selected_payload(result) -> dict:
    selected = result.artifact["checkpointing"]["selected_checkpoint"]
    for payload in result.checkpoint_payloads:
        if canonical_sha256(payload) == selected["content_sha256"]:
            return payload
    raise AssertionError("selected checkpoint payload was not returned")


def _resume_manifest(run_id: str, source_result) -> DLRunManifest:
    selected = source_result.artifact["checkpointing"]["selected_checkpoint"]
    payload = _manifest_payload(run_id)
    payload["checkpoint_policy"]["resume"] = {
        "mode": "exact_checkpoint",
        "checkpoint_id": selected["checkpoint_id"],
        "locator": selected["locator"],
        "content_sha256": selected["content_sha256"],
        "source_run_id": selected["source_run_id"],
        "completed_steps": selected["completed_steps"],
        "completed_epochs": selected["completed_epochs"],
        "consumed_budget_sha256": selected["consumed_budget_sha256"],
        "optimizer_state_sha256": selected["optimizer_state_sha256"],
    }
    return DLRunManifest.from_payload(payload)


class DLRunnerL3CheckpointTest(unittest.TestCase):
    def test_checkpoint_artifact_contains_only_locator_hash_and_lineage(
        self,
    ) -> None:
        result = run_fixture(_manifest("dl-l3-golden"), _fixture())
        artifact_text = json.dumps(result.artifact, default=str)
        self.assertEqual(
            result.sha256,
            "0e1964052079ef6e6ed822fa286b16d1a68292f8b6aea119fa61195f6e96d81e",
        )
        self.assertEqual(result.status, "completed")
        self.assertGreaterEqual(len(result.checkpoint_payloads), 1)
        self.assertNotIn("model_state", artifact_text)
        self.assertNotIn("input_weights", artifact_text)
        selected = result.artifact["checkpointing"]["selected_checkpoint"]
        self.assertTrue(selected["locator"].startswith("checkpoint://"))
        self.assertEqual(len(selected["content_sha256"]), 64)
        self.assertTrue(selected["resume_eligible"])

    def test_checkpoint_payloads_are_defensive_copies(self) -> None:
        result = run_fixture(_manifest("dl-l3-frozen"), _fixture())
        before = result.sha256
        payloads = result.checkpoint_payloads
        payloads[0]["model_state"]["output_bias"] = 999
        self.assertEqual(result.sha256, before)
        self.assertNotEqual(
            result.checkpoint_payloads[0]["model_state"]["output_bias"], 999
        )

    def test_retention_none_exposes_no_selectable_checkpoint(self) -> None:
        result = run_fixture(
            _manifest("dl-l3-no-retention", retention="none"), _fixture()
        )
        self.assertEqual(result.checkpoint_payloads, ())
        self.assertEqual(result.artifact["checkpointing"]["retained"], [])
        self.assertIsNone(
            result.artifact["checkpointing"]["selected_checkpoint"]
        )

    def test_exact_resume_matches_uninterrupted_model_and_does_not_double_charge(
        self,
    ) -> None:
        partial_fixture = _fixture(requested_steps=4)
        partial = run_fixture(_manifest("dl-l3-partial"), partial_fixture)
        checkpoint_payload = _selected_payload(partial)

        resumed = run_fixture(
            _resume_manifest("dl-l3-resumed", partial),
            _fixture(requested_steps=8),
            checkpoint_payload=checkpoint_payload,
        )
        uninterrupted = run_fixture(
            _manifest("dl-l3-uninterrupted"), _fixture(requested_steps=8)
        )
        resumed_checkpoint = _selected_payload(resumed)
        uninterrupted_checkpoint = _selected_payload(uninterrupted)
        self.assertEqual(
            resumed_checkpoint["model_state"],
            uninterrupted_checkpoint["model_state"],
        )
        self.assertEqual(resumed.budget_ledger["consumed"]["steps"], 8)
        self.assertEqual(resumed.budget_ledger["segment_consumed"]["steps"], 4)
        self.assertEqual(
            resumed.budget_ledger["prior_consumption_sha256"],
            partial.artifact["checkpointing"]["selected_checkpoint"][
                "consumed_budget_sha256"
            ],
        )

    def test_resume_tampering_and_wrong_lineage_fail_closed(self) -> None:
        partial = run_fixture(
            _manifest("dl-l3-source"), _fixture(requested_steps=4)
        )
        checkpoint = _selected_payload(partial)
        tampered = copy.deepcopy(checkpoint)
        tampered["model_state"]["output_bias"] = 999
        with self.assertRaisesRegex(DLRunnerError, "content hash"):
            run_fixture(
                _resume_manifest("dl-l3-tampered", partial),
                _fixture(requested_steps=8),
                checkpoint_payload=tampered,
            )

        wrong_fixture = _fixture(requested_steps=8)
        wrong_fixture["validation_targets"][0] = 99.0
        with self.assertRaisesRegex(DLRunnerError, "training_identity"):
            run_fixture(
                _resume_manifest("dl-l3-wrong-fixture", partial),
                wrong_fixture,
                checkpoint_payload=checkpoint,
            )

    def test_resume_budget_is_cumulative_and_stops_after_remaining_cap(self) -> None:
        partial = run_fixture(
            _manifest("dl-l3-budget-source"), _fixture(requested_steps=4)
        )
        checkpoint = _selected_payload(partial)
        resume_payload = _resume_manifest(
            "dl-l3-budget-resume", partial
        ).payload
        resume_payload["budget"]["max_steps"] = 6
        resumed = run_fixture(
            DLRunManifest.from_payload(resume_payload),
            _fixture(requested_steps=8),
            checkpoint_payload=checkpoint,
        )
        self.assertEqual(resumed.status, "budget_exhausted")
        self.assertEqual(resumed.budget_ledger["consumed"]["steps"], 6)
        self.assertEqual(resumed.budget_ledger["segment_consumed"]["steps"], 2)

    def test_fresh_and_exact_resume_payload_presence_is_fail_closed(self) -> None:
        with self.assertRaisesRegex(DLRunnerError, "fresh execution"):
            run_fixture(
                _manifest("dl-l3-fresh-extra"),
                _fixture(),
                checkpoint_payload={"unexpected": True},
            )
        partial = run_fixture(
            _manifest("dl-l3-source-missing"), _fixture(requested_steps=4)
        )
        with self.assertRaisesRegex(DLRunnerError, "requires checkpoint_payload"):
            run_fixture(
                _resume_manifest("dl-l3-missing", partial),
                _fixture(requested_steps=8),
            )


class DLRunnerL3EarlyStoppingTest(unittest.TestCase):
    def test_early_stopping_selects_validation_checkpoint_and_records_last(
        self,
    ) -> None:
        fixture = _fixture(
            requested_steps=8,
            early_stopping={
                "enabled": True,
                "patience": 2,
                "min_delta": 100.0,
                "warmup_steps": 0,
            },
        )
        result = run_fixture(_manifest("dl-l3-early"), fixture)
        artifact = result.artifact
        self.assertEqual(result.status, "early_stopped")
        self.assertEqual(artifact["budget_ledger"]["consumed"]["steps"], 2)
        self.assertEqual(artifact["early_stopping"]["best_step"], 0)
        self.assertTrue(artifact["early_stopping"]["triggered"])
        self.assertEqual(
            artifact["checkpointing"]["selected_checkpoint"]["completed_steps"],
            0,
        )
        roles = {
            role
            for checkpoint in artifact["checkpointing"]["retained"]
            for role in checkpoint["roles"]
        }
        self.assertEqual(roles, {"best", "last"})

    def test_early_stopping_requires_best_retention(self) -> None:
        fixture = _fixture(
            early_stopping={
                "enabled": True,
                "patience": 2,
                "min_delta": 0.0,
                "warmup_steps": 0,
            }
        )
        with self.assertRaisesRegex(DLRunnerError, "early stopping requires"):
            run_fixture(_manifest("dl-l3-bad-retention", retention="last"), fixture)

    def test_v2_policy_and_fixture_shape_fail_closed(self) -> None:
        bad = _fixture()
        bad["validation_features"][0].append(1.0)
        with self.assertRaisesRegex(DLRunnerError, "feature width"):
            run_fixture(_manifest("dl-l3-bad-width"), bad)

        payload = _manifest_payload("dl-l3-scheduler")
        payload["scheduler"]["name"] = "cosine"
        payload["checkpoint_policy"]["save_scheduler_state"] = True
        with self.assertRaisesRegex(DLRunnerError, "scheduler state"):
            run_fixture(DLRunManifest.from_payload(payload), _fixture())

    def test_dry_run_v2_emits_no_metrics_or_checkpoints(self) -> None:
        payload = _manifest_payload("dl-l3-dry")
        payload["execution_mode"] = "dry_run"
        result = run_fixture(DLRunManifest.from_payload(payload), _fixture())
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.artifact["metrics"], {})
        self.assertEqual(result.checkpoint_payloads, ())
        self.assertEqual(result.budget_ledger["consumed"]["steps"], 0)


if __name__ == "__main__":
    unittest.main()
