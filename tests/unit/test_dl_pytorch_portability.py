from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_evolution.adapters.deep_learning.pytorch_portability import (
    DLPytorchPortabilityError,
    run_pytorch_portability_trial,
)


def _plan() -> dict:
    return {
        "schema": "pytorch-portability-trial-plan/v1",
        "repository": {
            "commit_oid": "a" * 40,
            "tree_oid": "b" * 40,
            "archive_sha256": "c" * 64,
            "dirty": False,
        },
    }


class PytorchPortabilityTrialTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("RESEARCH_EVOLUTION_RUN_PYTORCH_CUDA") == "1",
        "real PyTorch/CUDA portability test is opt-in",
    )
    def test_real_cuda_trial_returns_public_safe_r3_r4_receipt(self) -> None:
        import torch

        self.assertTrue(torch.cuda.is_available())
        with tempfile.TemporaryDirectory(prefix="dl-portability-real-") as temp:
            root = Path(temp)
            receipt = run_pytorch_portability_trial(_plan(), artifact_root=root)

        payload = receipt.payload
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(
            payload["same_host_reproducibility"]["successful_seeds"],
            [7, 11, 13],
        )
        self.assertEqual(
            payload["same_host_reproducibility"]["exact_repeat_matches"], 3
        )
        self.assertTrue(
            payload["controlled_interruption"]["checkpoint_confirmed"]
        )
        self.assertTrue(
            payload["controlled_interruption"]["spawn_identity_verified"]
        )
        self.assertFalse(payload["controlled_interruption"]["double_charged"])
        self.assertFalse(
            payload["controlled_interruption"]["scheduler_preemption_observed"]
        )
        self.assertNotIn(str(root), str(payload))
        self.assertEqual(set(payload["privacy"].values()), {False})

    def test_artifact_root_must_be_empty_before_framework_import(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dl-portability-nonempty-") as temp:
            root = Path(temp)
            (root / "existing.bin").write_bytes(b"owned-by-caller")

            with mock.patch.dict(sys.modules, {"torch": None}):
                with self.assertRaisesRegex(
                    DLPytorchPortabilityError, "must be empty"
                ):
                    run_pytorch_portability_trial(_plan(), artifact_root=root)

            self.assertEqual(
                {path.name for path in root.iterdir()}, {"existing.bin"}
            )

    def test_framework_unavailable_fails_without_install_or_artifact_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="dl-portability-no-torch-") as temp:
            root = Path(temp)
            with mock.patch.dict(sys.modules, {"torch": None}):
                with self.assertRaisesRegex(
                    DLPytorchPortabilityError, "PyTorch is unavailable"
                ):
                    run_pytorch_portability_trial(_plan(), artifact_root=root)

            self.assertEqual(list(root.iterdir()), [])

    def test_invalid_plan_fails_before_framework_import_or_artifact_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="dl-portability-invalid-") as temp:
            root = Path(temp)
            with mock.patch.dict(sys.modules, {"torch": None}):
                with self.assertRaisesRegex(
                    DLPytorchPortabilityError, "trial plan"
                ):
                    run_pytorch_portability_trial({}, artifact_root=root)

            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
