"""Phase 6 manifest interface tests (ADR-0009)."""

import ast
import copy
import dataclasses
import os
import tempfile
import unittest
from pathlib import Path

import research_evolution.adapters.deep_learning as deep_learning
from research_evolution.adapters import AdapterError
from research_evolution.adapters.deep_learning import DLRunManifest
from research_evolution.core import CoreError, canonical_sha256, load_record, load_strict_json

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"
DL_FIXTURES = FIXTURES / "dl-run-manifest" / "v1" / "valid"
MANIFEST_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "research_evolution"
    / "adapters"
    / "deep_learning"
    / "manifest.py"
)


def _payload(name: str = "minimal.json") -> dict:
    return load_strict_json((DL_FIXTURES / name).read_bytes())


class DLRunManifestInterfaceTest(unittest.TestCase):
    def test_submodule_surface_is_pinned(self) -> None:
        self.assertEqual(deep_learning.__all__, ["DLRunManifest"])

    def test_minimal_manifest_is_hash_bound_and_configuration_only(self) -> None:
        raw = (DL_FIXTURES / "minimal.json").read_bytes()
        manifest = DLRunManifest.from_json(raw)
        self.assertEqual(manifest.sha256, canonical_sha256(load_strict_json(raw)))
        self.assertEqual(manifest.payload["evidence_scope"], "configuration_only")
        self.assertEqual(manifest.case_sha256, "1" * 64)
        self.assertFalse(manifest.requests_gpu)
        self.assertEqual(manifest.resume_mode, "fresh")

    def test_full_manifest_records_requested_gpu_and_exact_resume(self) -> None:
        manifest = DLRunManifest.from_json((DL_FIXTURES / "full.json").read_bytes())
        self.assertTrue(manifest.requests_gpu)
        self.assertEqual(manifest.resume_mode, "exact_checkpoint")
        self.assertEqual(manifest.payload["hardware"]["accelerator"], "cuda")

    def test_from_payload_matches_from_json(self) -> None:
        raw = (DL_FIXTURES / "minimal.json").read_bytes()
        self.assertEqual(
            DLRunManifest.from_payload(load_strict_json(raw)).sha256,
            DLRunManifest.from_json(raw).sha256,
        )

    def test_input_and_returned_payloads_are_defensive_copies(self) -> None:
        payload = _payload()
        manifest = DLRunManifest.from_payload(payload)
        before = manifest.sha256
        payload["hardware"]["device_count"] = 99
        returned = manifest.payload
        returned["budget"]["max_steps"] = 999
        self.assertEqual(manifest.sha256, before)
        self.assertEqual(manifest.payload["hardware"]["device_count"], 1)
        self.assertEqual(manifest.payload["budget"]["max_steps"], 10)

    def test_instance_is_frozen(self) -> None:
        manifest = DLRunManifest.from_payload(_payload())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            manifest._record = None

    def test_schema_failure_is_adapter_error_with_core_cause(self) -> None:
        payload = _payload()
        del payload["case_sha256"]
        with self.assertRaises(AdapterError) as ctx:
            DLRunManifest.from_payload(payload)
        self.assertIsInstance(ctx.exception.__cause__, CoreError)
        self.assertGreater(len(ctx.exception.details), 0)

    def test_direct_construction_with_foreign_record_fails(self) -> None:
        record = load_record(
            (FIXTURES / "ml-task" / "v1" / "valid" / "minimal.json").read_bytes(),
            schema_root=Path(__file__).resolve().parents[2] / "schemas" / "adapters",
        )
        with self.assertRaises(AdapterError):
            DLRunManifest(record)

    def test_construction_has_no_filesystem_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                DLRunManifest.from_payload(_payload())
                leftovers = list(Path(temp).rglob("*"))
            finally:
                os.chdir(previous)
        self.assertEqual(leftovers, [])

    def test_manifest_dependency_surface_is_pinned(self) -> None:
        tree = ast.parse(MANIFEST_SOURCE.read_text(encoding="utf-8"))
        imports = {
            (node.level, node.module)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertEqual(
            imports,
            {
                (0, "__future__"),
                (0, "dataclasses"),
                (0, "typing"),
                (0, "research_evolution.core"),
                (2, "types"),
            },
        )
        self.assertFalse(any(isinstance(node, ast.Import) for node in ast.walk(tree)))


class DLRunManifestSemanticGateTest(unittest.TestCase):
    def assert_rule(self, payload: dict, rule_id: str) -> None:
        with self.assertRaises(AdapterError) as ctx:
            DLRunManifest.from_payload(payload)
        self.assertTrue(
            any(detail.startswith(f"{rule_id}:") for detail in ctx.exception.details),
            ctx.exception.details,
        )

    def test_resource_and_budget_numeric_floors(self) -> None:
        probes = (
            ("hardware", "device_count", 0, "dl-device-count-positive"),
            ("hardware", "memory_bytes_per_device", 0, "dl-device-memory-positive"),
            ("budget", "max_samples", 0, "dl-sample-budget-positive"),
            ("budget", "max_steps", -1, "dl-budget-nonnegative"),
        )
        for section, field, value, rule in probes:
            with self.subTest(field=f"{section}.{field}"):
                payload = _payload()
                payload[section][field] = value
                self.assert_rule(payload, rule)

    def test_at_least_one_work_or_cost_cap_is_positive(self) -> None:
        payload = _payload()
        for field in ("max_steps", "max_epochs", "max_tokens", "max_flops", "cost_limit"):
            payload["budget"][field] = 0
        self.assert_rule(payload, "dl-work-budget-required")

    def test_execution_mode_matches_accelerator(self) -> None:
        cpu_fixture_on_cuda = _payload()
        cpu_fixture_on_cuda["hardware"]["accelerator"] = "cuda"
        cpu_fixture_on_cuda["framework"]["backend_version"] = "cuda-12.8"
        self.assert_rule(cpu_fixture_on_cuda, "dl-mode-accelerator-match")

        gpu_mode_on_cpu = _payload()
        gpu_mode_on_cpu["execution_mode"] = "gpu_fixture"
        self.assert_rule(gpu_mode_on_cpu, "dl-mode-accelerator-match")

    def test_backend_version_presence_matches_accelerator(self) -> None:
        cuda_without_backend = _payload("full.json")
        del cuda_without_backend["framework"]["backend_version"]
        self.assert_rule(cuda_without_backend, "dl-backend-version-required")

        cpu_with_backend = _payload()
        cpu_with_backend["framework"]["backend_version"] = "cuda-12.8"
        self.assert_rule(cpu_with_backend, "dl-backend-version-forbidden")

    def test_runtime_os_matches_accelerator(self) -> None:
        rocm_on_windows = _payload("full.json")
        rocm_on_windows["hardware"]["accelerator"] = "rocm"
        rocm_on_windows["runtime"]["os"] = "windows"
        rocm_on_windows["framework"]["backend_version"] = "rocm-7.0"
        self.assert_rule(rocm_on_windows, "dl-runtime-accelerator-match")

        mps_on_linux = _payload("full.json")
        mps_on_linux["hardware"]["accelerator"] = "mps"
        mps_on_linux["runtime"]["os"] = "linux"
        del mps_on_linux["framework"]["backend_version"]
        self.assert_rule(mps_on_linux, "dl-runtime-accelerator-match")

    def test_container_declaration_is_all_or_nothing(self) -> None:
        host_with_image = _payload()
        host_with_image["container"].update(
            {"image": "example.invalid/image:1", "digest_sha256": "a" * 64}
        )
        self.assert_rule(host_with_image, "dl-container-pins-forbidden")

        unpinned_container = _payload()
        unpinned_container["container"] = {"kind": "docker", "image": "example.invalid/image:1"}
        self.assert_rule(unpinned_container, "dl-container-pins-required")

    def test_retention_policy_matches_count(self) -> None:
        wrong_exact_count = _payload()
        wrong_exact_count["checkpoint_policy"]["max_retained"] = 2
        self.assert_rule(wrong_exact_count, "dl-retention-count-match")

        empty_last_n = _payload()
        empty_last_n["checkpoint_policy"]["retention"] = "last_n"
        empty_last_n["checkpoint_policy"]["max_retained"] = 0
        self.assert_rule(empty_last_n, "dl-retention-count-match")

    def test_fresh_run_carries_no_checkpoint_state(self) -> None:
        payload = _payload()
        payload["checkpoint_policy"]["resume"]["checkpoint_id"] = "unexpected"
        self.assert_rule(payload, "dl-fresh-resume-empty")

    def test_exact_resume_requires_complete_lineage(self) -> None:
        payload = _payload("full.json")
        del payload["checkpoint_policy"]["resume"]["content_sha256"]
        self.assert_rule(payload, "dl-exact-resume-complete")

    def test_exact_resume_requires_optimizer_and_scheduler_state_policies(self) -> None:
        no_optimizer_state = _payload("full.json")
        no_optimizer_state["checkpoint_policy"]["save_optimizer_state"] = False
        self.assert_rule(no_optimizer_state, "dl-exact-resume-optimizer")

        no_scheduler_state = _payload("full.json")
        no_scheduler_state["checkpoint_policy"]["save_scheduler_state"] = False
        self.assert_rule(no_scheduler_state, "dl-exact-resume-scheduler")

    def test_scheduler_none_cannot_carry_scheduler_state(self) -> None:
        payload = _payload()
        payload["checkpoint_policy"]["save_scheduler_state"] = True
        self.assert_rule(payload, "dl-scheduler-state-forbidden")

    def test_resume_progress_cannot_exceed_declared_budget(self) -> None:
        steps = _payload("full.json")
        steps["checkpoint_policy"]["resume"]["completed_steps"] = 1001
        self.assert_rule(steps, "dl-resume-within-budget")

        epochs = _payload("full.json")
        epochs["checkpoint_policy"]["resume"]["completed_epochs"] = 11
        self.assert_rule(epochs, "dl-resume-within-budget")


if __name__ == "__main__":
    unittest.main()
