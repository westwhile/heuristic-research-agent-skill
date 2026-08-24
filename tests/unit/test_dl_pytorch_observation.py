"""Real PyTorch/CUDA engineering-observation interface tests."""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import os
import platform
import unittest
from pathlib import Path
from unittest import mock

from research_evolution.adapters import AdapterError
from research_evolution.adapters.deep_learning.manifest import DLRunManifest
from research_evolution.adapters.deep_learning.pytorch_observation import (
    DLPytorchObservationError,
    DLObservedRun,
    pytorch_observation_identity,
    run_pytorch_gpu_fixture,
)
from research_evolution.core import canonical_sha256, load_strict_json

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "adapters"
OBSERVATION_FIXTURES = (
    ADAPTER_FIXTURES / "dl-run-observation" / "v1" / "valid"
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
    / "pytorch_observation.py"
)


def _fixture() -> dict:
    return {
        "schema": "pytorch-dl-fixture/v1",
        "fixture_id": "tiny-cuda-regression-001",
        "case_sha256": "1" * 64,
        "samples": 16,
        "input_features": 4,
        "hidden_units": 8,
        "output_features": 1,
        "learning_rate": 0.01,
        "requested_steps": 1,
        "seed": 20260824,
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
    payload = load_strict_json(MANIFEST_FIXTURE.read_bytes())
    payload["manifest_id"] = "real-pytorch-observation-manifest-001"
    payload["run_id"] = "real-pytorch-observation-run-001"
    payload["study_id"] = "synthetic-pytorch-cuda-study-001"
    payload["execution_mode"] = "gpu_fixture"
    payload["runner"] = pytorch_observation_identity()
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
        "max_samples": 16,
        "max_steps": 1,
        "max_epochs": 0,
        "max_tokens": 0,
        "max_flops": 0,
        "cost_limit": 60,
        "cost_unit": "accelerator_seconds",
    }
    payload["optimizer"] = {
        "name": "sgd",
        "config_sha256": canonical_sha256({"learning_rate": 0.01}),
    }
    payload["scheduler"] = {
        "name": "none",
        "config_sha256": canonical_sha256({}),
    }
    payload["checkpoint_policy"] = {
        "artifact_reference": "external_locator_and_hash_only",
        "retention": "none",
        "max_retained": 0,
        "selection_metric": "final_loss",
        "selection_direction": "minimize",
        "save_optimizer_state": False,
        "save_scheduler_state": False,
        "recovery_accounting": "cumulative_no_double_charge",
        "resume": {"mode": "fresh"},
    }
    return payload


class DLObservedRunInterfaceTest(unittest.TestCase):
    def _payload(self, name: str = "minimal.json") -> dict:
        return load_strict_json((OBSERVATION_FIXTURES / name).read_bytes())

    def test_valid_observation_is_frozen_hash_bound_and_defensive(self) -> None:
        payload = self._payload()
        observation = DLObservedRun.from_payload(payload)
        before = observation.sha256
        payload["status"] = "failed"
        returned = observation.payload
        returned["execution"]["hardware"]["device_count"] = 99
        self.assertEqual(observation.sha256, before)
        self.assertEqual(observation.status, "completed")
        self.assertEqual(observation.manifest_sha256, "2" * 64)
        self.assertEqual(
            observation.payload["execution"]["hardware"]["device_count"], 1
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            observation._record = None

    def test_failed_observation_is_preserved(self) -> None:
        observation = DLObservedRun.from_json(
            (OBSERVATION_FIXTURES / "failed.json").read_bytes()
        )
        self.assertEqual(observation.status, "failed")
        self.assertEqual(observation.failure_class, "runtime_error")
        self.assertEqual(observation.payload["metrics"], [])

    def test_status_failure_and_metric_semantics_fail_closed(self) -> None:
        probes = []
        completed_with_failure = self._payload()
        completed_with_failure["failure"] = {
            "class": "runtime_error",
            "message": "failed",
        }
        probes.append((completed_with_failure, "observation-status-failure-match"))
        duplicate_metrics = self._payload()
        duplicate_metrics["metrics"][2]["name"] = "final_loss"
        probes.append((duplicate_metrics, "observation-completed-metrics"))
        negative_resources = self._payload()
        negative_resources["resources"]["duration_seconds"] = -1
        probes.append((negative_resources, "observation-resource-nonnegative"))
        for payload, rule in probes:
            with self.subTest(rule=rule):
                with self.assertRaises(AdapterError) as ctx:
                    DLObservedRun.from_payload(payload)
                self.assertTrue(
                    any(item.startswith(f"{rule}:") for item in ctx.exception.details),
                    ctx.exception.details,
                )


class DLPytorchObservationRunnerTest(unittest.TestCase):
    def test_public_surface_and_source_identity_are_pinned(self) -> None:
        identity = pytorch_observation_identity()
        self.assertEqual(
            identity,
            {
                "name": "pytorch-gpu-fixture-runner",
                "version": "0.1.0",
                "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            },
        )
        import research_evolution.adapters.deep_learning.pytorch_observation as module

        self.assertEqual(
            module.__all__,
            [
                "DLPytorchObservationError",
                "DLObservedRun",
                "pytorch_observation_identity",
                "run_pytorch_gpu_fixture",
            ],
        )

    def test_module_has_no_eager_torch_import(self) -> None:
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 0
        )
        self.assertNotIn("torch", imported)

    def test_fixture_and_manifest_gates_fail_closed_before_framework_load(self) -> None:
        manifest = DLRunManifest.from_payload(_manifest_payload())
        bad_fixture = _fixture()
        bad_fixture["unexpected"] = True
        with mock.patch(
            "research_evolution.adapters.deep_learning.pytorch_observation._load_torch"
        ) as load_torch:
            with self.assertRaisesRegex(
                DLPytorchObservationError, "fixture fields must be exactly"
            ):
                run_pytorch_gpu_fixture(manifest, bad_fixture)
            load_torch.assert_not_called()

        wrong_runner = _manifest_payload()
        wrong_runner["runner"]["version"] = "9.9.9"
        with self.assertRaisesRegex(DLPytorchObservationError, "manifest.runner"):
            run_pytorch_gpu_fixture(
                DLRunManifest.from_payload(wrong_runner), _fixture()
            )

    def test_missing_pytorch_is_a_precise_non_observation_error(self) -> None:
        manifest = DLRunManifest.from_payload(_manifest_payload())
        with (
            mock.patch(
                "research_evolution.adapters.deep_learning.pytorch_observation._load_torch",
                side_effect=DLPytorchObservationError(
                    "PyTorch is not installed; no execution was observed"
                ),
            ),
            mock.patch.dict(
                os.environ, {"CUBLAS_WORKSPACE_CONFIG": ":4096:8"}
            ),
        ):
            with self.assertRaisesRegex(
                DLPytorchObservationError, "no execution was observed"
            ):
                run_pytorch_gpu_fixture(manifest, _fixture())

    def test_success_converts_decimal_learning_rate_at_framework_boundary(self) -> None:
        runtime = _runtime()
        manifest = DLRunManifest.from_payload(_manifest_payload(runtime))
        captured: dict = {}

        def execute(_torch, normalized):
            captured.update(normalized)
            return {
                "metrics": [
                    {"name": "initial_loss", "value": 1.25},
                    {"name": "final_loss", "value": 1.20},
                    {"name": "loss_delta", "value": -0.05},
                ],
                "resources": {
                    "duration_seconds": 0.05,
                    "peak_memory_bytes": 1024,
                },
                "completed_steps": 1,
                "accounting": "exact",
            }

        with (
            mock.patch(
                "research_evolution.adapters.deep_learning.pytorch_observation._load_torch",
                return_value=object(),
            ),
            mock.patch(
                "research_evolution.adapters.deep_learning.pytorch_observation._observe_runtime",
                return_value=runtime,
            ),
            mock.patch(
                "research_evolution.adapters.deep_learning.pytorch_observation._execute_fixture",
                side_effect=execute,
            ),
            mock.patch(
                "research_evolution.adapters.deep_learning.pytorch_observation._utc_now",
                return_value="2026-08-24T01:30:00Z",
            ),
            mock.patch.dict(
                os.environ, {"CUBLAS_WORKSPACE_CONFIG": ":4096:8"}
            ),
        ):
            result = run_pytorch_gpu_fixture(manifest, _fixture())
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.failure_class, "none")
        self.assertIsInstance(captured["learning_rate"], float)
        self.assertEqual(result.payload["fixture"]["fixture_sha256"], canonical_sha256(_fixture()))

    def test_runtime_failure_is_preserved_without_raw_exception_text(self) -> None:
        runtime = _runtime()
        manifest = DLRunManifest.from_payload(_manifest_payload(runtime))
        with (
            mock.patch(
                "research_evolution.adapters.deep_learning.pytorch_observation._load_torch",
                return_value=object(),
            ),
            mock.patch(
                "research_evolution.adapters.deep_learning.pytorch_observation._observe_runtime",
                return_value=runtime,
            ),
            mock.patch(
                "research_evolution.adapters.deep_learning.pytorch_observation._execute_fixture",
                side_effect=RuntimeError("sensitive caller detail"),
            ),
            mock.patch(
                "research_evolution.adapters.deep_learning.pytorch_observation._utc_now",
                return_value="2026-08-24T01:30:00Z",
            ),
            mock.patch.dict(
                os.environ, {"CUBLAS_WORKSPACE_CONFIG": ":4096:8"}
            ),
        ):
            result = run_pytorch_gpu_fixture(manifest, _fixture())
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_class, "runtime_error")
        self.assertNotIn("sensitive caller detail", str(result.payload))
        self.assertEqual(result.payload["metrics"], [])
        self.assertEqual(
            result.payload["budget_ledger"]["consumed"]["accounting"],
            "lower_bound",
        )


@unittest.skipUnless(
    os.environ.get("HEURISTIC_RUN_REAL_PYTORCH_CUDA") == "1",
    "real PyTorch/CUDA observation is opt-in",
)
class RealPyTorchCUDAObservationTest(unittest.TestCase):
    def test_real_cuda_fixture_via_public_interface(self) -> None:
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
        result = run_pytorch_gpu_fixture(
            DLRunManifest.from_payload(_manifest_payload(runtime)), _fixture()
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.failure_class, "none")
        self.assertEqual(len(result.payload["metrics"]), 3)
        self.assertGreater(result.payload["resources"]["peak_memory_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
