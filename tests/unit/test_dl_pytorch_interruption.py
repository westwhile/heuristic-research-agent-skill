"""Controlled PyTorch/CUDA child-interruption recovery interface tests."""

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
from research_evolution.adapters.deep_learning.pytorch_interruption import (
    DLControlledInterruptionRecoveryObservation,
    DLPytorchInterruptionError,
    _terminate_verified_child,
    _validate_commit_signal,
    _wait_for_commit_signal,
    pytorch_interruption_identity,
    run_pytorch_controlled_interruption_recovery,
)
from research_evolution.adapters.deep_learning.pytorch_recovery import (
    pytorch_recovery_identity,
)
from research_evolution.core import canonical_sha256, load_strict_json

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "adapters"
OBSERVATION_FIXTURE = (
    ADAPTER_FIXTURES
    / "dl-controlled-interruption-recovery-observation"
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
    / "pytorch_interruption.py"
)
GATE_SCRIPT = REPO_ROOT / "scripts" / "verify_dl_controlled_interruption_recovery.py"


def _fixture() -> dict:
    return {
        "schema": "pytorch-dl-recovery-fixture/v1",
        "fixture_id": "tiny-cuda-controlled-interruption-001",
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
    payload["manifest_id"] = "real-pytorch-interruption-manifest-001"
    payload["run_id"] = "real-pytorch-interruption-run-001"
    payload["study_id"] = "synthetic-pytorch-interruption-study-001"
    payload["execution_mode"] = "gpu_fixture"
    payload["runner"] = pytorch_interruption_identity()
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


def _checkpoint(root: Path) -> dict:
    raw = b"bounded-controlled-interruption-checkpoint"
    (root / "checkpoint.pt").write_bytes(raw)
    return {
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "model_state_sha256": "6" * 64,
        "optimizer_state_sha256": "7" * 64,
        "scheduler_state_sha256": "8" * 64,
        "completed_steps": 2,
    }


def _source(root: Path, runtime: dict) -> dict:
    return {
        "role": "interruptible_source",
        "completed_steps": 2,
        "duration_seconds": 0.1,
        "peak_memory_bytes": 1024,
        "execution": runtime,
        "checkpoint": _checkpoint(root),
        "checkpoint_lifecycle": {
            "temporary_payload_verified": True,
            "atomic_replacement_completed": True,
            "authoritative_payload_verified": True,
        },
        "interruption": {
            "kind": "parent_requested_owned_child_termination",
            "checkpoint_confirmed_before_request": True,
            "spawn_identity_verified": True,
            "termination_method": "popen_terminate",
            "source_exit_observed": True,
            "source_returncode_nonzero": True,
        },
    }


def _later_stage(role: str, runtime: dict) -> dict:
    return {
        "role": role,
        "completed_steps": 2 if role == "resume" else 4,
        "duration_seconds": 0.1,
        "peak_memory_bytes": 1024,
        "execution": runtime,
        "model_state_sha256": "a" * 64,
        "optimizer_state_sha256": "b" * 64,
        "scheduler_state_sha256": "c" * 64,
        "final_loss": 1.25,
    }


class DLControlledInterruptionObservationTest(unittest.TestCase):
    def _payload(self) -> dict:
        return load_strict_json(OBSERVATION_FIXTURE.read_bytes())

    def test_receipt_is_frozen_hash_bound_and_defensive(self) -> None:
        payload = self._payload()
        observation = DLControlledInterruptionRecoveryObservation.from_payload(payload)
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
        duplicate_role["processes"][1]["role"] = "interruptible_source"
        probes.append((duplicate_role, "interruption-process-roles"))
        wrong_hash = self._payload()
        wrong_hash["equivalence"]["control_model_state_sha256"] = "d" * 64
        probes.append((wrong_hash, "interruption-model-equivalence"))
        double_count = self._payload()
        double_count["budget_ledger"]["resume_segment_steps"] = 4
        probes.append((double_count, "interruption-budget-resume"))
        for payload, rule in probes:
            with self.subTest(rule=rule):
                with self.assertRaises(AdapterError) as ctx:
                    DLControlledInterruptionRecoveryObservation.from_payload(payload)
                self.assertTrue(
                    any(item.startswith(f"{rule}:") for item in ctx.exception.details),
                    ctx.exception.details,
                )


class DLPytorchInterruptionRunnerTest(unittest.TestCase):
    def test_public_surface_identity_lazy_import_and_process_scope_are_pinned(self) -> None:
        import research_evolution.adapters.deep_learning.pytorch_interruption as module

        self.assertEqual(
            module.__all__,
            [
                "DLPytorchInterruptionError",
                "DLControlledInterruptionRecoveryObservation",
                "pytorch_interruption_identity",
                "run_pytorch_controlled_interruption_recovery",
            ],
        )
        identity = pytorch_interruption_identity()
        self.assertEqual(
            identity["name"],
            "pytorch-gpu-controlled-interruption-recovery-runner",
        )
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
        source_text = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("os.kill", source_text)
        self.assertNotIn("taskkill", source_text.lower())
        self.assertNotIn("Get-Process", source_text)

    def test_gate_distinguishes_git_object_ids_from_sha256(self) -> None:
        namespace = runpy.run_path(str(GATE_SCRIPT))
        validate = namespace["_hex_identifier"]
        self.assertEqual(validate("a" * 40, "commit", 40), "a" * 40)
        self.assertEqual(validate("b" * 64, "archive", 64), "b" * 64)
        with self.assertRaisesRegex(ValueError, "40 lowercase hexadecimal"):
            validate("c" * 64, "commit", 40)

    def test_mocked_receipt_is_exact_path_free_and_preserves_one_checkpoint(self) -> None:
        runtime = _runtime()
        manifest = DLRunManifest.from_payload(_manifest_payload(runtime))
        with tempfile.TemporaryDirectory(prefix="dl-interruption-unit-") as temp:
            root = Path(temp)

            def invoke(_root: Path, role: str, _request: dict) -> dict:
                return _later_stage(role, runtime)

            with (
                mock.patch(
                    "research_evolution.adapters.deep_learning.pytorch_interruption._load_torch",
                    return_value=object(),
                ),
                mock.patch(
                    "research_evolution.adapters.deep_learning.pytorch_interruption._observe_runtime",
                    return_value=runtime,
                ),
                mock.patch(
                    "research_evolution.adapters.deep_learning.pytorch_interruption._interrupt_after_commit",
                    side_effect=lambda *_args: _source(root, runtime),
                ),
                mock.patch(
                    "research_evolution.adapters.deep_learning.pytorch_interruption._invoke_stage",
                    side_effect=invoke,
                ),
                mock.patch(
                    "research_evolution.adapters.deep_learning.pytorch_interruption._utc_now",
                    return_value="2026-08-24T08:30:00Z",
                ),
                mock.patch.dict(os.environ, {"CUBLAS_WORKSPACE_CONFIG": ":4096:8"}),
            ):
                result = run_pytorch_controlled_interruption_recovery(
                    manifest, _fixture(), root
                )
            self.assertEqual(result.payload["status"], "completed")
            self.assertTrue(
                result.payload["interruption"]["checkpoint_confirmed_before_request"]
            )
            self.assertTrue(result.payload["interruption"]["spawn_identity_verified"])
            self.assertFalse(result.payload["budget_ledger"]["double_charged"])
            self.assertNotIn(str(root), str(result.payload))
            self.assertEqual([path.name for path in root.iterdir()], ["checkpoint.pt"])

    def test_signal_validation_rejects_stale_and_tampered_receipts(self) -> None:
        runtime = _runtime()
        with tempfile.TemporaryDirectory(prefix="dl-interruption-signal-") as temp:
            root = Path(temp)
            receipt = _checkpoint(root)
            process = mock.Mock(pid=4321)
            process.poll.return_value = None
            signal = {
                "schema": "pytorch-controlled-interruption-commit-signal/v1",
                "role": "interruptible_source",
                "nonce": "a" * 32,
                "pid": 4321,
                "parent_pid": 1234,
                "completed_steps": 2,
                "duration_seconds": 0.1,
                "peak_memory_bytes": 1024,
                "execution": runtime,
                "checkpoint": receipt,
                "checkpoint_lifecycle": {
                    "temporary_payload_verified": True,
                    "atomic_replacement_completed": True,
                    "authoritative_payload_verified": True,
                },
            }
            validated = _validate_commit_signal(
                signal,
                process,
                expected_nonce="a" * 32,
                expected_parent_pid=1234,
                checkpoint_path=root / "checkpoint.pt",
                execution=runtime,
            )
            self.assertEqual(validated["completed_steps"], 2)
            with self.assertRaisesRegex(DLPytorchInterruptionError, "stale"):
                _validate_commit_signal(
                    signal,
                    process,
                    expected_nonce="b" * 32,
                    expected_parent_pid=1234,
                    checkpoint_path=root / "checkpoint.pt",
                    execution=runtime,
                )
            (root / "checkpoint.pt").write_bytes(b"truncated")
            with self.assertRaisesRegex(
                DLPytorchInterruptionError, "integrity verification"
            ):
                _validate_commit_signal(
                    signal,
                    process,
                    expected_nonce="a" * 32,
                    expected_parent_pid=1234,
                    checkpoint_path=root / "checkpoint.pt",
                    execution=runtime,
                )

    def test_no_termination_is_authorized_before_checkpoint_confirmation(self) -> None:
        process = mock.Mock(pid=4321)
        process.poll.return_value = 1
        with tempfile.TemporaryDirectory(prefix="dl-interruption-no-signal-") as temp:
            with self.assertRaisesRegex(
                DLPytorchInterruptionError, "before checkpoint confirmation"
            ):
                _wait_for_commit_signal(
                    Path(temp) / "missing.json", process, timeout_seconds=1
                )
        process.terminate.assert_not_called()

    def test_termination_targets_only_the_verified_spawned_child(self) -> None:
        process = mock.Mock(pid=4321)
        process.poll.return_value = None
        process.wait.return_value = -15
        with self.assertRaisesRegex(DLPytorchInterruptionError, "refusing"):
            _terminate_verified_child(process, expected_pid=9999)
        process.terminate.assert_not_called()
        receipt = _terminate_verified_child(process, expected_pid=4321)
        process.terminate.assert_called_once_with()
        self.assertEqual(receipt["termination_method"], "popen_terminate")
        self.assertTrue(receipt["source_exit_observed"])

    def test_manifest_requires_exact_interruption_runner(self) -> None:
        runtime = _runtime()
        payload = _manifest_payload(runtime)
        payload["runner"] = pytorch_recovery_identity()
        manifest = DLRunManifest.from_payload(payload)
        with tempfile.TemporaryDirectory(prefix="dl-interruption-manifest-") as temp:
            with mock.patch.dict(
                os.environ, {"CUBLAS_WORKSPACE_CONFIG": ":4096:8"}
            ):
                with self.assertRaisesRegex(
                    DLPytorchInterruptionError, "interruption runner identity"
                ):
                    run_pytorch_controlled_interruption_recovery(
                        manifest, _fixture(), temp
                    )


@unittest.skipUnless(
    os.environ.get("HEURISTIC_RUN_REAL_PYTORCH_CUDA_INTERRUPTION") == "1",
    "real PyTorch/CUDA controlled interruption recovery is opt-in",
)
class RealPyTorchCUDAInterruptionTest(unittest.TestCase):
    def test_real_owned_child_termination_resume_matches_control(self) -> None:
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
        with tempfile.TemporaryDirectory(prefix="dl-interruption-real-") as temp:
            result = run_pytorch_controlled_interruption_recovery(
                DLRunManifest.from_payload(_manifest_payload(runtime)),
                _fixture(),
                temp,
            )
            self.assertTrue(
                result.payload["interruption"]["checkpoint_confirmed_before_request"]
            )
            self.assertTrue(result.payload["interruption"]["spawn_identity_verified"])
            self.assertTrue(result.payload["equivalence"]["model_state_exact"])
            self.assertTrue(result.payload["equivalence"]["optimizer_state_exact"])
            self.assertTrue(result.payload["equivalence"]["scheduler_state_exact"])
            self.assertFalse(result.payload["budget_ledger"]["double_charged"])


if __name__ == "__main__":
    unittest.main()
