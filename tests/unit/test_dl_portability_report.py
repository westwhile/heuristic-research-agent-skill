from __future__ import annotations

import unittest

from research_evolution.adapters.deep_learning.portability_report import (
    DLCrossEnvironmentReport,
    build_cross_environment_report,
)
from research_evolution.adapters.deep_learning.pytorch_portability import (
    DLPortabilityTrialReceipt,
)
from research_evolution.adapters.types import AdapterError


def _receipt_payload(
    *, receipt_id: str, device_model: str, driver_version: str
) -> dict:
    seed_rows = [
        {
            "seed": 7,
            "stable_sha256": "1" * 64,
            "final_loss": 0.111,
        },
        {
            "seed": 11,
            "stable_sha256": "2" * 64,
            "final_loss": 0.222,
        },
        {
            "seed": 13,
            "stable_sha256": "3" * 64,
            "final_loss": 0.333,
        },
    ]
    return {
        "schema": "dl-portability-trial-receipt/v1",
        "receipt_id": receipt_id,
        "trial_plan_sha256": "0" * 64,
        "observed_at": "2026-08-24T06:00:00Z",
        "evidence_scope": (
            "real_framework_hardware_portability_trial_readiness_engineering"
        ),
        "status": "completed",
        "repository": {
            "commit_oid": "a" * 40,
            "tree_oid": "b" * 40,
            "archive_sha256": "c" * 64,
            "dirty": False,
        },
        "runner": {
            "name": "pytorch-portability-trial-runner",
            "version": "0.1.0",
            "source_sha256": "d" * 64,
            "same_host_runner_sha256": "e" * 64,
            "interruption_runner_sha256": "f" * 64,
        },
        "execution": {
            "os": "windows",
            "architecture": "AMD64",
            "python_version": "3.14.5",
            "framework_version": "2.12.1+cu130",
            "cuda_version": "13.0",
            "driver": {
                "status": "observed",
                "source": "nvidia-smi",
                "version": driver_version,
            },
            "device": {
                "model": device_model,
                "count": 1,
                "memory_bytes": 8585216000,
                "compute_capability": "8.9",
            },
        },
        "same_host_reproducibility": {
            "report_sha256": "4" * 64,
            "plan_sha256": "5" * 64,
            "expected_seeds": [7, 11, 13],
            "successful_seeds": [7, 11, 13],
            "failed_seeds": [],
            "exact_repeat_matches": 3,
            "results": seed_rows,
        },
        "controlled_interruption": {
            "observation_sha256": "6" * 64,
            "checkpoint_confirmed": True,
            "spawn_identity_verified": True,
            "model_state_sha256": "7" * 64,
            "optimizer_state_sha256": "8" * 64,
            "scheduler_state_sha256": "9" * 64,
            "final_loss": 0.444,
            "double_charged": False,
            "scheduler_preemption_observed": False,
        },
        "privacy": {
            "local_paths_included": False,
            "credentials_included": False,
            "personal_identifiers_included": False,
            "automatic_upload_performed": False,
        },
        "limitations": [
            "A receipt does not prove an independent host or participant.",
            "Only bounded synthetic engineering behavior was executed.",
        ],
    }


class CrossEnvironmentReportTests(unittest.TestCase):
    def test_report_rejects_tampered_environment_count(self) -> None:
        receipts = [
            DLPortabilityTrialReceipt.from_payload(
                _receipt_payload(
                    receipt_id=f"portability-receipt-env-{suffix}",
                    device_model=device,
                    driver_version=driver,
                )
            )
            for suffix, device, driver in (
                ("a", "NVIDIA RTX 4060 Laptop GPU", "610.88"),
                ("b", "NVIDIA RTX 4090", "611.10"),
            )
        ]
        report = build_cross_environment_report(
            receipts,
            {
                "policy_id": "dl-cross-environment-comparison-policy/v1",
                "expected_seeds": [7, 11, 13],
                "final_loss_absolute_tolerance": 1e-12,
            },
        )
        tampered = report.payload
        tampered["summary"]["environment_count"] = 1
        tampered["summary"]["verdict"] = "single_environment_only"

        with self.assertRaises(AdapterError) as context:
            DLCrossEnvironmentReport.from_payload(tampered)
        self.assertTrue(
            any("environment-count" in detail for detail in context.exception.details)
        )

    def test_report_rejects_tampered_receipt_count(self) -> None:
        receipts = [
            DLPortabilityTrialReceipt.from_payload(
                _receipt_payload(
                    receipt_id=f"portability-receipt-count-{suffix}",
                    device_model=device,
                    driver_version=driver,
                )
            )
            for suffix, device, driver in (
                ("a", "NVIDIA RTX 4060 Laptop GPU", "610.88"),
                ("b", "NVIDIA RTX 4090", "611.10"),
            )
        ]
        report = build_cross_environment_report(
            receipts,
            {
                "policy_id": "dl-cross-environment-comparison-policy/v1",
                "expected_seeds": [7, 11, 13],
                "final_loss_absolute_tolerance": 1e-12,
            },
        )
        tampered = report.payload
        tampered["summary"]["receipt_count"] = 3

        with self.assertRaises(AdapterError) as context:
            DLCrossEnvironmentReport.from_payload(tampered)
        self.assertTrue(
            any("receipt-count" in detail for detail in context.exception.details)
        )

    def test_receipt_rejects_personal_identifier_in_technical_fields(self) -> None:
        payload = _receipt_payload(
            receipt_id="portability-receipt-identifier-leak",
            device_model="alice" + "@" + "example.com",
            driver_version="610.88",
        )

        with self.assertRaises(AdapterError) as context:
            DLPortabilityTrialReceipt.from_payload(payload)
        self.assertTrue(
            any("identifier" in detail for detail in context.exception.details)
        )

    def test_receipt_rejects_driver_status_version_contradiction(self) -> None:
        payload = _receipt_payload(
            receipt_id="portability-receipt-driver-contradiction",
            device_model="NVIDIA RTX 4060 Laptop GPU",
            driver_version="610.88",
        )
        payload["execution"]["driver"]["status"] = "unavailable"

        with self.assertRaises(AdapterError) as context:
            DLPortabilityTrialReceipt.from_payload(payload)
        self.assertTrue(
            any("driver" in detail for detail in context.exception.details)
        )

    def test_distinct_receipts_from_one_environment_are_not_cross_environment(
        self,
    ) -> None:
        first = DLPortabilityTrialReceipt.from_payload(
            _receipt_payload(
                receipt_id="portability-receipt-same-env-a",
                device_model="NVIDIA RTX 4060 Laptop GPU",
                driver_version="610.88",
            )
        )
        second = DLPortabilityTrialReceipt.from_payload(
            _receipt_payload(
                receipt_id="portability-receipt-same-env-b",
                device_model="NVIDIA RTX 4060 Laptop GPU",
                driver_version="610.88",
            )
        )

        report = build_cross_environment_report(
            [first, second],
            {
                "policy_id": "dl-cross-environment-comparison-policy/v1",
                "expected_seeds": [7, 11, 13],
                "final_loss_absolute_tolerance": 1e-12,
            },
        )

        self.assertEqual(report.payload["summary"]["environment_count"], 1)
        self.assertEqual(
            report.payload["summary"]["verdict"], "single_environment_only"
        )

    def test_receipt_rejects_credential_shape_when_privacy_flags_are_false(
        self,
    ) -> None:
        payload = _receipt_payload(
            receipt_id="portability-receipt-secret-leak",
            device_model="gh" + "p_" + "A" * 36,
            driver_version="610.88",
        )

        with self.assertRaises(AdapterError) as context:
            DLPortabilityTrialReceipt.from_payload(payload)
        self.assertTrue(
            any("credential" in detail for detail in context.exception.details)
        )

    def test_receipt_rejects_hidden_local_path_when_privacy_flags_are_false(
        self,
    ) -> None:
        payload = _receipt_payload(
            receipt_id="portability-receipt-path-leak",
            device_model="C:" + r"\Users\alice\private-gpu-name",
            driver_version="610.88",
        )

        with self.assertRaises(AdapterError) as context:
            DLPortabilityTrialReceipt.from_payload(payload)
        self.assertTrue(
            any("public-safe" in detail for detail in context.exception.details)
        )

    def test_two_distinct_environments_never_imply_independence_or_adoption(
        self,
    ) -> None:
        first = DLPortabilityTrialReceipt.from_payload(
            _receipt_payload(
                receipt_id="portability-receipt-a",
                device_model="NVIDIA RTX 4060 Laptop GPU",
                driver_version="610.88",
            )
        )
        second = DLPortabilityTrialReceipt.from_payload(
            _receipt_payload(
                receipt_id="portability-receipt-b",
                device_model="NVIDIA RTX 4090",
                driver_version="611.10",
            )
        )

        report = build_cross_environment_report(
            [first, second],
            {
                "policy_id": "dl-cross-environment-comparison-policy/v1",
                "expected_seeds": [7, 11, 13],
                "final_loss_absolute_tolerance": 1e-12,
            },
        )

        self.assertEqual(report.payload["summary"]["receipt_count"], 2)
        self.assertEqual(report.payload["summary"]["environment_count"], 2)
        self.assertEqual(report.payload["summary"]["verdict"], "exact_match")
        self.assertFalse(report.payload["claims"]["independent_hosts_verified"])
        self.assertFalse(
            report.payload["claims"]["independent_participants_verified"]
        )
        self.assertFalse(report.payload["claims"]["external_adoption_verified"])


if __name__ == "__main__":
    unittest.main()
