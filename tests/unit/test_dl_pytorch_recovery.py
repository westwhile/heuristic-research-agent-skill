"""Real PyTorch/CUDA checkpoint-recovery interface tests."""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import os
import platform
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_evolution.adapters import AdapterError
from research_evolution.adapters.deep_learning.manifest import DLRunManifest
from research_evolution.adapters.deep_learning.pytorch_recovery import (
    DLCheckpointRecoveryObservation,
    DLPytorchRecoveryError,
    pytorch_recovery_identity,
    run_pytorch_checkpoint_recovery,
)
from research_evolution.core import canonical_bytes, canonical_sha256, load_strict_json

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "adapters"
OBSERVATION_FIXTURE = (
    ADAPTER_FIXTURES
    / "dl-checkpoint-recovery-observation"
    / "v1"
    / "valid"
    / "minimal.json"
)
MANIFEST_FIXTURE = (
    ADAPTER_FIXTURES / "dl-run-manifest" / "v1" / "valid" / "minimal.json"
)
SOURCE = (
    REPO_ROOT
    / "src"
    / "research_evolution"
    / "adapters"
    / "deep_learning"
    / "pytorch_recovery.py"
)
GATE_SCRIPT = REPO_ROOT / "scripts" / "verify_dl_checkpoint_recovery.py"


def _fixture() -> dict:
    return {
        "schema": "pytorch-dl-recovery-fixture/v1",
        "fixture_id": "tiny-cuda-recovery-001",
        "case_sha256": "1" * 64,
        "samples": 16,
        "input_features": 4,
        "hidden_units": 8,
        "output_features": 1,
        "learning_rate": 0.01,
        "momentum": 0.9,
        "requested_steps": 4,
        "checkpoint_step": 2,
        "seed": 20260824,
        "scheduler_step_size": 2,
        "scheduler_gamma": 0.5,
    }


def _runtime() -> dict:
    return {
        "mode": "gpu_fixture",
        "os": "windows",
        "architecture": "AMD64",
        "python_version": "3.12.13",
        "framework": {
            "name": "pytorch",
            "version": "2.12.1+cu130",
            "backend": "cuda",
            "backend_version": "13.0",
            "determinism": "strict",
        },
        "hardware": {
            "device_model": "NVIDIA GeForce RTX 4060 Laptop GPU",
            "device_count": 1,
            "memory_bytes_per_device": 8585216000,
            "compute_capability": "8.9",
        },
    }


def _manifest_payload(runtime: dict | None = None) -> dict:
    observed = copy.deepcopy(runtime or _runtime())
    fixture = _fixture()
    payload = load_strict_json(MANIFEST_FIXTURE.read_bytes())
    payload["manifest_id"] = "real-pytorch-recovery-manifest-001"
    payload["run_id"] = "real-pytorch-recovery-run-001"
    payload["study_id"] = "synthetic-pytorch-recovery-study-001"
    payload["execution_mode"] = "gpu_fixture"
    payload["runner"] = pytorch_recovery_identity()
    payload["hardware"] = {
        "accelerator": "cuda",
        "device_model": observed["hardware"]["device_model"],
        "device_count": observed["hardware"]["device_count"],
        "memory_bytes_per_device": observed["hardware"]["memory_bytes_per_device"],
    }
    payload["runtime"] = {
        "os": observed["os"],
        "architecture": observed["architecture"],
        "python_version": observed["python_version"],
    }
    payload["framework"] = {
        "name": "pytorch",
        "version": observed["framework"]["version"],
        "backend_version": observed["framework"]["backend_version"],
        "determinism": "strict",
    }
    payload["container"] = {"kind": "none"}
    payload["budget"] = {
        "max_samples": fixture["samples"],
        "max_steps": fixture["requested_steps"],
        "max_epochs": 0,
        "max_tokens": 0,
        "max_flops": 0,
        "cost_limit": 60,
        "cost_unit": "accelerator_seconds",
    }
    payload["optimizer"] = {
        "name": "sgd",
        "config_sha256": canonical_sha256(
            {
                "learning_rate": fixture["learning_rate"],
                "momentum": fixture["momentum"],
            }
        ),
    }
    payload["scheduler"] = {
        "name": "step_lr",
        "config_sha256": canonical_sha256(
            {
                "step_size": fixture["scheduler_step_size"],
                "gamma": fixture["scheduler_gamma"],
            }
        ),
    }
    payload["checkpoint_policy"] = {
        "artifact_reference": "external_locator_and_hash_only",
        "retention": "last",
        "max_retained": 1,
        "selection_metric": "final_loss",
        "selection_direction": "minimize",
        "save_optimizer_state": True,
        "save_scheduler_state": True,
        "recovery_accounting": "cumulative_no_double_charge",
        "resume": {"mode": "fresh"},
    }
    return payload


def _stage_factory(*, corrupt_content_hash: bool = False):
    state_hashes = {
        "model_state_sha256": "6" * 64,
        "optimizer_state_sha256": "7" * 64,
        "scheduler_state_sha256": "8" * 64,
    }

    def invoke(root: Path, role: str, request: dict) -> dict:
        base = {
            "role": role,
            "duration_seconds": 0.1,
            "peak_memory_bytes": 1024,
            "execution": _runtime(),
        }
        if role == "source":
            raw = b"bounded-checkpoint"
            (root / "checkpoint.pt").write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            return {
                **base,
                "completed_steps": 2,
                "checkpoint": {
                    "content_sha256": "f" * 64 if corrupt_content_hash else digest,
                    "size_bytes": len(raw),
                    **state_hashes,
                    "completed_steps": 2,
                },
            }
        return {
            **base,
            "completed_steps": 2 if role == "resume" else 4,
            **state_hashes,
            "final_loss": 1.25,
        }

    return invoke


class DLCheckpointRecoveryObservationTest(unittest.TestCase):
    def _payload(self) -> dict:
        return load_strict_json(OBSERVATION_FIXTURE.read_bytes())

    def test_receipt_is_frozen_hash_bound_and_defensive(self) -> None:
        payload = self._payload()
        observation = DLCheckpointRecoveryObservation.from_payload(payload)
        before = observation.sha256
        payload["run_id"] = "mutated"
        returned = observation.payload
        returned["budget_ledger"]["source_steps"] = 99
        self.assertEqual(observation.sha256, before)
        self.assertEqual(observation.manifest_sha256, "1" * 64)
        self.assertEqual(observation.payload["budget_ledger"]["source_steps"], 2)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            observation._record = None

    def test_semantic_contradictions_fail_closed(self) -> None:
        probes = []
        duplicate_role = self._payload()
        duplicate_role["processes"][1]["role"] = "source"
        probes.append((duplicate_role, "recovery-process-roles"))
        wrong_checkpoint_step = self._payload()
        wrong_checkpoint_step["checkpoint"]["completed_steps"] = 1
        probes.append((wrong_checkpoint_step, "recovery-checkpoint-step"))
        wrong_hash = self._payload()
        wrong_hash["equivalence"]["control_model_state_sha256"] = "c" * 64
        probes.append((wrong_hash, "recovery-model-equivalence"))
        double_count = self._payload()
        double_count["budget_ledger"]["resume_segment_steps"] = 4
        probes.append((double_count, "recovery-budget-resume"))
        for payload, rule in probes:
            with self.subTest(rule=rule):
                with self.assertRaises(AdapterError) as ctx:
                    DLCheckpointRecoveryObservation.from_payload(payload)
                self.assertTrue(
                    any(item.startswith(f"{rule}:") for item in ctx.exception.details),
                    ctx.exception.details,
                )


class DLPytorchRecoveryRunnerTest(unittest.TestCase):
    def test_public_surface_source_identity_and_lazy_import_are_pinned(self) -> None:
        import research_evolution.adapters.deep_learning.pytorch_recovery as module

        self.assertEqual(
            module.__all__,
            [
                "DLPytorchRecoveryError",
                "DLCheckpointRecoveryObservation",
                "pytorch_recovery_identity",
                "run_pytorch_checkpoint_recovery",
            ],
        )
        identity = pytorch_recovery_identity()
        self.assertEqual(identity["name"], "pytorch-gpu-checkpoint-recovery-runner")
        self.assertEqual(identity["version"], "0.1.0")
        self.assertEqual(
            identity["source_sha256"], hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        )
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertNotIn("torch", imported)

    def test_gate_distinguishes_git_object_ids_from_sha256(self) -> None:
        namespace = runpy.run_path(str(GATE_SCRIPT))
        validate = namespace["_hex_identifier"]
        self.assertEqual(validate("a" * 40, "commit", 40), "a" * 40)
        self.assertEqual(validate("b" * 64, "archive", 64), "b" * 64)
        with self.assertRaisesRegex(ValueError, "40 lowercase hexadecimal"):
            validate("c" * 64, "commit", 40)

    def test_mocked_three_process_receipt_is_exact_and_path_free(self) -> None:
        runtime = _runtime()
        manifest = DLRunManifest.from_payload(_manifest_payload(runtime))
        with tempfile.TemporaryDirectory(prefix="dl-recovery-unit-") as temp:
            root = Path(temp)
            with (
                mock.patch(
                    "research_evolution.adapters.deep_learning.pytorch_recovery._load_torch",
                    return_value=object(),
                ),
                mock.patch(
                    "research_evolution.adapters.deep_learning.pytorch_recovery._observe_runtime",
                    return_value=runtime,
                ),
                mock.patch(
                    "research_evolution.adapters.deep_learning.pytorch_recovery._invoke_stage",
                    side_effect=_stage_factory(),
                ),
                mock.patch(
                    "research_evolution.adapters.deep_learning.pytorch_recovery._utc_now",
                    return_value="2026-08-24T04:30:00Z",
                ),
                mock.patch.dict(os.environ, {"CUBLAS_WORKSPACE_CONFIG": ":4096:8"}),
            ):
                result = run_pytorch_checkpoint_recovery(
                    manifest, _fixture(), root
                )
            self.assertEqual(result.payload["status"], "completed")
            self.assertEqual(
                {row["role"] for row in result.payload["processes"]},
                {"source", "resume", "uninterrupted_control"},
            )
            self.assertFalse(result.payload["budget_ledger"]["double_charged"])
            self.assertNotIn(str(root), str(result.payload))
            self.assertTrue((root / "checkpoint.pt").is_file())

    def test_checkpoint_integrity_tampering_fails_before_resume(self) -> None:
        runtime = _runtime()
        manifest = DLRunManifest.from_payload(_manifest_payload(runtime))
        with tempfile.TemporaryDirectory(prefix="dl-recovery-tamper-") as temp:
            with (
                mock.patch(
                    "research_evolution.adapters.deep_learning.pytorch_recovery._load_torch",
                    return_value=object(),
                ),
                mock.patch(
                    "research_evolution.adapters.deep_learning.pytorch_recovery._observe_runtime",
                    return_value=runtime,
                ),
                mock.patch(
                    "research_evolution.adapters.deep_learning.pytorch_recovery._invoke_stage",
                    side_effect=_stage_factory(corrupt_content_hash=True),
                ) as invoke,
                mock.patch.dict(os.environ, {"CUBLAS_WORKSPACE_CONFIG": ":4096:8"}),
            ):
                with self.assertRaisesRegex(
                    DLPytorchRecoveryError, "integrity verification"
                ):
                    run_pytorch_checkpoint_recovery(manifest, _fixture(), temp)
            self.assertEqual(invoke.call_count, 1)

    def test_subprocess_strict_json_numbers_are_normalized_at_framework_seam(
        self,
    ) -> None:
        import research_evolution.adapters.deep_learning.pytorch_recovery as module

        def run(command, **_kwargs):
            result_path = Path(command[-1])
            result_path.write_bytes(
                canonical_bytes(
                    {
                        "ok": True,
                        "payload": {
                            "role": "resume",
                            "completed_steps": 2,
                            "duration_seconds": 0.125,
                            "peak_memory_bytes": 1024,
                            "execution": _runtime(),
                            "model_state_sha256": "6" * 64,
                            "optimizer_state_sha256": "7" * 64,
                            "scheduler_state_sha256": "8" * 64,
                            "final_loss": 1.25,
                        },
                    }
                )
            )
            return mock.Mock(returncode=0)

        with tempfile.TemporaryDirectory(prefix="dl-recovery-decimal-") as temp:
            with mock.patch.object(module.subprocess, "run", side_effect=run):
                result = module._invoke_stage(Path(temp), "resume", {})
        self.assertIsInstance(result["duration_seconds"], float)
        self.assertIsInstance(result["final_loss"], float)

    def test_manifest_and_artifact_root_gates_fail_closed(self) -> None:
        runtime = _runtime()
        bad = _manifest_payload(runtime)
        bad["checkpoint_policy"]["save_scheduler_state"] = False
        manifest = DLRunManifest.from_payload(bad)
        with tempfile.TemporaryDirectory(prefix="dl-recovery-root-") as temp:
            with mock.patch.dict(
                os.environ, {"CUBLAS_WORKSPACE_CONFIG": ":4096:8"}
            ):
                with self.assertRaisesRegex(
                    DLPytorchRecoveryError, "exact-state checkpoint"
                ):
                    run_pytorch_checkpoint_recovery(manifest, _fixture(), temp)
        manifest = DLRunManifest.from_payload(_manifest_payload(runtime))
        with tempfile.TemporaryDirectory(prefix="dl-recovery-root-") as temp:
            (Path(temp) / "existing.txt").write_text("occupied", encoding="utf-8")
            with mock.patch.dict(
                os.environ, {"CUBLAS_WORKSPACE_CONFIG": ":4096:8"}
            ):
                with self.assertRaisesRegex(DLPytorchRecoveryError, "must be empty"):
                    run_pytorch_checkpoint_recovery(manifest, _fixture(), temp)


@unittest.skipUnless(
    os.environ.get("HEURISTIC_RUN_REAL_PYTORCH_CUDA_RECOVERY") == "1",
    "real PyTorch/CUDA checkpoint recovery is opt-in",
)
class RealPyTorchCUDARecoveryTest(unittest.TestCase):
    def test_real_cuda_checkpoint_resume_matches_uninterrupted_control(self) -> None:
        import torch

        self.assertTrue(torch.cuda.is_available())
        properties = torch.cuda.get_device_properties(0)
        capability = torch.cuda.get_device_capability(0)
        runtime = {
            "mode": "gpu_fixture",
            "os": platform.system().lower(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "framework": {
                "name": "pytorch",
                "version": torch.__version__,
                "backend": "cuda",
                "backend_version": torch.version.cuda,
                "determinism": "strict",
            },
            "hardware": {
                "device_model": properties.name,
                "device_count": torch.cuda.device_count(),
                "memory_bytes_per_device": properties.total_memory,
                "compute_capability": f"{capability[0]}.{capability[1]}",
            },
        }
        with tempfile.TemporaryDirectory(prefix="dl-recovery-real-") as temp:
            result = run_pytorch_checkpoint_recovery(
                DLRunManifest.from_payload(_manifest_payload(runtime)),
                _fixture(),
                temp,
            )
            self.assertEqual(result.payload["status"], "completed")
            self.assertTrue(result.payload["equivalence"]["model_state_exact"])
            self.assertTrue(result.payload["equivalence"]["optimizer_state_exact"])
            self.assertTrue(result.payload["equivalence"]["scheduler_state_exact"])
            self.assertFalse(result.payload["budget_ledger"]["double_charged"])


if __name__ == "__main__":
    unittest.main()
