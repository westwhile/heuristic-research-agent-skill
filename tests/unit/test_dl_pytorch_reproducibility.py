"""Same-host PyTorch/CUDA reproducibility-report tests."""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_evolution.adapters import AdapterError
from research_evolution.adapters.deep_learning.manifest import DLRunManifest
from research_evolution.adapters.deep_learning.pytorch_observation import (
    DLObservedRun,
    pytorch_observation_identity,
)
from research_evolution.adapters.deep_learning.pytorch_reproducibility import (
    DLPytorchReproducibilityError,
    DLSameHostReproducibilityReport,
    pytorch_reproducibility_identity,
    run_pytorch_same_host_reproducibility,
)
from research_evolution.core import canonical_sha256, load_strict_json

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "adapters"
REPORT_FIXTURE = (
    ADAPTER_FIXTURES
    / "dl-same-host-reproducibility-report"
    / "v1"
    / "valid"
    / "minimal.json"
)
OBSERVATION_FIXTURE = (
    ADAPTER_FIXTURES / "dl-run-observation" / "v1" / "valid" / "minimal.json"
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
    / "pytorch_reproducibility.py"
)
GATE_SCRIPT = REPO_ROOT / "scripts" / "verify_dl_same_host_reproducibility.py"


def _runtime() -> dict:
    return {
        "mode": "gpu_fixture",
        "os": "windows",
        "architecture": "AMD64",
        "python_version": "3.14.5",
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


def _fixture(seed: int) -> dict:
    return {
        "schema": "pytorch-dl-fixture/v1",
        "fixture_id": f"tiny-cuda-reproducibility-{seed}",
        "case_sha256": "1" * 64,
        "samples": 16,
        "input_features": 4,
        "hidden_units": 8,
        "output_features": 1,
        "learning_rate": 0.01,
        "requested_steps": 1,
        "seed": seed,
    }


def _manifest_payload(seed: int, runtime: dict | None = None) -> dict:
    observed = copy.deepcopy(runtime or _runtime())
    fixture = _fixture(seed)
    payload = load_strict_json(MANIFEST_FIXTURE.read_bytes())
    payload["manifest_id"] = f"real-pytorch-repro-manifest-{seed}"
    payload["run_id"] = f"real-pytorch-repro-run-{seed}"
    payload["study_id"] = "synthetic-pytorch-repro-study-001"
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
            {"learning_rate": fixture["learning_rate"]}
        ),
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


def _plan(runtime: dict | None = None) -> tuple[list[DLRunManifest], list[dict]]:
    seeds = (7, 11, 13)
    manifests = [
        DLRunManifest.from_payload(_manifest_payload(seed, runtime)) for seed in seeds
    ]
    return manifests, [_fixture(seed) for seed in seeds]


def _observation(
    seed: int,
    repeat: str,
    *,
    final_loss: float = 1.25,
    runtime: dict | None = None,
) -> DLObservedRun:
    fixture = _fixture(seed)
    payload = load_strict_json(OBSERVATION_FIXTURE.read_bytes())
    payload["observation_id"] = f"dl-repro-{seed}-{repeat}"
    payload["manifest_sha256"] = hashlib.sha256(
        f"manifest-{seed}".encode("ascii")
    ).hexdigest()
    payload["run_id"] = f"real-pytorch-repro-run-{seed}"
    payload["study_id"] = "synthetic-pytorch-repro-study-001"
    payload["observed_at"] = (
        "2026-08-24T06:00:00Z" if repeat == "a" else "2026-08-24T06:00:01Z"
    )
    payload["runner"] = pytorch_observation_identity()
    payload["fixture"] = {
        "fixture_sha256": canonical_sha256(fixture),
        "seed": seed,
        "samples": fixture["samples"],
        "requested_steps": fixture["requested_steps"],
    }
    payload["execution"] = copy.deepcopy(runtime or _runtime())
    payload["metrics"] = [
        {"name": "initial_loss", "value": 2.0},
        {"name": "final_loss", "value": final_loss},
        {"name": "loss_delta", "value": final_loss - 2.0},
    ]
    duration = 0.05 if repeat == "a" else 0.07
    payload["resources"] = {
        "duration_seconds": duration,
        "peak_memory_bytes": 1024 if repeat == "a" else 2048,
    }
    payload["budget_ledger"] = {
        "declared": {
            "max_samples": 16,
            "max_steps": 1,
            "cost_limit": 60,
            "cost_unit": "accelerator_seconds",
        },
        "consumed": {
            "samples": 16,
            "steps": 1,
            "accelerator_seconds": duration,
            "accounting": "exact",
        },
    }
    return DLObservedRun.from_payload(payload)


class DLSameHostReproducibilityReportTest(unittest.TestCase):
    def _payload(self) -> dict:
        return load_strict_json(REPORT_FIXTURE.read_bytes())

    def test_report_is_frozen_hash_bound_and_defensive(self) -> None:
        payload = self._payload()
        report = DLSameHostReproducibilityReport.from_payload(payload)
        before = report.sha256
        payload["report_id"] = "mutated"
        returned = report.payload
        returned["summary"]["exact_repeat_matches"] = 0
        self.assertEqual(report.sha256, before)
        self.assertEqual(report.plan_sha256, "1" * 64)
        self.assertEqual(report.payload["summary"]["exact_repeat_matches"], 3)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report._record = None

    def test_semantic_contradictions_fail_closed(self) -> None:
        probes = []
        wrong_coverage = self._payload()
        wrong_coverage["results"][1]["seed"] = 12
        probes.append((wrong_coverage, "reproducibility-result-coverage"))
        mismatched_repeat = self._payload()
        mismatched_repeat["results"][0]["repeat_b"]["stable_sha256"] = "f" * 64
        probes.append((mismatched_repeat, "reproducibility-stable-match"))
        wrong_stats = self._payload()
        wrong_stats["summary"]["final_loss"]["mean"] = 2
        probes.append((wrong_stats, "reproducibility-summary-statistics"))
        wrong_repeat = self._payload()
        wrong_repeat["results"][0]["repeat_a"].pop("final_loss")
        probes.append((wrong_repeat, "reproducibility-repeat-shape"))
        wrong_driver = self._payload()
        wrong_driver["driver_observation"]["status"] = "observed"
        probes.append((wrong_driver, "reproducibility-driver-status"))
        for payload, rule in probes:
            with self.subTest(rule=rule):
                with self.assertRaises(AdapterError) as ctx:
                    DLSameHostReproducibilityReport.from_payload(payload)
                self.assertTrue(
                    any(item.startswith(f"{rule}:") for item in ctx.exception.details),
                    ctx.exception.details,
                )


class DLPytorchReproducibilityRunnerTest(unittest.TestCase):
    def test_public_surface_identity_lazy_import_and_gate_are_pinned(self) -> None:
        import research_evolution.adapters.deep_learning.pytorch_reproducibility as module

        self.assertEqual(
            module.__all__,
            [
                "DLPytorchReproducibilityError",
                "DLSameHostReproducibilityReport",
                "pytorch_reproducibility_identity",
                "run_pytorch_same_host_reproducibility",
            ],
        )
        self.assertEqual(
            pytorch_reproducibility_identity(),
            {
                "name": "pytorch-same-host-reproducibility-runner",
                "version": "0.1.0",
                "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            },
        )
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertNotIn("torch", imported)
        self.assertTrue(GATE_SCRIPT.is_file())

    def test_three_seeds_run_twice_and_timing_is_not_compared(self) -> None:
        manifests, fixtures = _plan()
        calls: list[tuple[int, str]] = []

        def invoke(_root, seed, repeat, _manifest, _fixture_payload):
            calls.append((seed, repeat))
            return _observation(seed, repeat)

        with tempfile.TemporaryDirectory() as temporary:
            with (
                mock.patch(
                    "research_evolution.adapters.deep_learning."
                    "pytorch_reproducibility._invoke_repeat",
                    side_effect=invoke,
                ),
                mock.patch(
                    "research_evolution.adapters.deep_learning."
                    "pytorch_reproducibility._observe_driver",
                    return_value={
                        "status": "unavailable",
                        "source": "nvidia-smi",
                        "version": "unavailable",
                    },
                ),
            ):
                report = run_pytorch_same_host_reproducibility(
                    manifests, fixtures, temporary
                )
            self.assertEqual(list(Path(temporary).iterdir()), [])
        self.assertEqual(
            calls,
            [(7, "a"), (7, "b"), (11, "a"), (11, "b"), (13, "a"), (13, "b")],
        )
        payload = report.payload
        self.assertEqual(payload["summary"]["successful_seeds"], [7, 11, 13])
        self.assertEqual(payload["summary"]["failed_seeds"], [])
        self.assertEqual(payload["summary"]["exact_repeat_matches"], 3)
        for result in payload["results"]:
            self.assertEqual(result["status"], "reproduced")
            self.assertEqual(
                result["repeat_a"]["stable_sha256"],
                result["repeat_b"]["stable_sha256"],
            )
            self.assertNotEqual(
                result["repeat_a"]["observation_sha256"],
                result["repeat_b"]["observation_sha256"],
            )

    def test_one_failed_seed_remains_explicit(self) -> None:
        manifests, fixtures = _plan()

        def invoke(_root, seed, repeat, _manifest, _fixture_payload):
            if seed == 13:
                raise DLPytorchReproducibilityError("injected process failure")
            return _observation(seed, repeat, final_loss=float(seed))

        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch(
                "research_evolution.adapters.deep_learning."
                "pytorch_reproducibility._invoke_repeat",
                side_effect=invoke,
            ):
                report = run_pytorch_same_host_reproducibility(
                    manifests, fixtures, temporary
                )
        payload = report.payload
        self.assertEqual(payload["summary"]["successful_seeds"], [7, 11])
        self.assertEqual(payload["summary"]["failed_seeds"], [13])
        self.assertEqual(payload["results"][2]["failure_classes"], ["process_error"])
        self.assertEqual(payload["results"][2]["repeat_a"]["status"], "failed")

    def test_repeat_mismatch_is_failed_not_best_only_success(self) -> None:
        manifests, fixtures = _plan()

        def invoke(_root, seed, repeat, _manifest, _fixture_payload):
            loss = 2.0 if seed == 13 and repeat == "b" else 1.0
            return _observation(seed, repeat, final_loss=loss)

        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch(
                "research_evolution.adapters.deep_learning."
                "pytorch_reproducibility._invoke_repeat",
                side_effect=invoke,
            ):
                report = run_pytorch_same_host_reproducibility(
                    manifests, fixtures, temporary
                )
        failed = report.payload["results"][2]
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failure_classes"], ["repeat_mismatch"])

    def test_fewer_than_two_reproduced_seeds_issues_no_report(self) -> None:
        manifests, fixtures = _plan()

        def invoke(_root, seed, repeat, _manifest, _fixture_payload):
            if seed != 7:
                raise DLPytorchReproducibilityError("injected process failure")
            return _observation(seed, repeat)

        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch(
                "research_evolution.adapters.deep_learning."
                "pytorch_reproducibility._invoke_repeat",
                side_effect=invoke,
            ):
                with self.assertRaisesRegex(
                    DLPytorchReproducibilityError, "fewer than two seeds"
                ):
                    run_pytorch_same_host_reproducibility(
                        manifests, fixtures, temporary
                    )

    def test_plan_and_scratch_boundaries_fail_closed(self) -> None:
        manifests, fixtures = _plan()
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                DLPytorchReproducibilityError, "unique and supplied in sorted order"
            ):
                run_pytorch_same_host_reproducibility(
                    manifests, [fixtures[1], fixtures[0], fixtures[2]], temporary
                )

            drifted = copy.deepcopy(fixtures)
            drifted[2]["samples"] = 8
            with self.assertRaisesRegex(
                DLPytorchReproducibilityError, "fixtures differ on a frozen axis"
            ):
                run_pytorch_same_host_reproducibility(manifests, drifted, temporary)

            Path(temporary, "occupied").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(DLPytorchReproducibilityError, "must be empty"):
                run_pytorch_same_host_reproducibility(manifests, fixtures, temporary)

        with self.assertRaisesRegex(
            DLPytorchReproducibilityError, "outside the repository"
        ):
            run_pytorch_same_host_reproducibility(manifests, fixtures, REPO_ROOT)

    def test_driver_probe_is_explicitly_observed_or_unavailable(self) -> None:
        import research_evolution.adapters.deep_learning.pytorch_reproducibility as module

        observed = mock.Mock(returncode=0, stdout="580.88\n")
        unavailable = mock.Mock(returncode=1, stdout="")
        with mock.patch.object(module.subprocess, "run", return_value=observed):
            self.assertEqual(
                module._observe_driver(),
                {"status": "observed", "source": "nvidia-smi", "version": "580.88"},
            )
        with mock.patch.object(module.subprocess, "run", return_value=unavailable):
            self.assertEqual(
                module._observe_driver(),
                {
                    "status": "unavailable",
                    "source": "nvidia-smi",
                    "version": "unavailable",
                },
            )

    @unittest.skipUnless(
        os.environ.get("HEURISTIC_RUN_REAL_PYTORCH_CUDA_REPRODUCIBILITY") == "1",
        "real PyTorch/CUDA same-host gate is opt-in",
    )
    def test_real_pytorch_cuda_same_host_reproducibility(self) -> None:
        import torch

        if not torch.cuda.is_available():
            self.fail("opt-in same-host gate requires CUDA")
        properties = torch.cuda.get_device_properties(0)
        major, minor = torch.cuda.get_device_capability(0)
        runtime = {
            "mode": "gpu_fixture",
            "os": "windows" if os.name == "nt" else "linux",
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
                "compute_capability": f"{major}.{minor}",
            },
        }
        manifests, fixtures = _plan(runtime)
        with tempfile.TemporaryDirectory() as temporary:
            report = run_pytorch_same_host_reproducibility(
                manifests, fixtures, temporary
            )
        self.assertEqual(report.payload["summary"]["successful_seeds"], [7, 11, 13])
        self.assertEqual(report.payload["summary"]["exact_repeat_matches"], 3)
        self.assertEqual(report.payload["execution"], runtime)


if __name__ == "__main__":
    unittest.main()
