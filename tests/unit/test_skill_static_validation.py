"""P7B3 contracts for fail-closed Candidate Skill static validation."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from research_evolution.core import (
    PublicationError,
    publish_record,
    verify_record_graph,
)
from research_evolution.evolution import (
    SkillStaticValidationError,
    SkillStaticValidationReceipt,
    draft_skill_candidate_bundle,
    validate_skill_candidate,
)

from .test_skill_candidate_bundle import NOW
from .test_skill_candidate_bundle import _inputs as _draft_inputs


def _inputs(
    domain: str = "math",
) -> tuple[Any, dict[str, bytes], dict[str, Any]]:
    eligibility, contract, payload, evidence = _draft_inputs(domain)
    skill_name = contract["skill_name"]
    positive = f"bounded {domain} research task"
    exclusion = f"unbounded or production {domain} operation"
    description = (
        f"Guide bounded {domain} research workflows. "
        f"Use for {positive}; do not use for {exclusion}."
    )
    contract["description"] = description
    payload["SKILL.md"] = (
        "---\n"
        f"name: {skill_name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"# {domain.title()} research workflow\n\n"
        "Follow the bounded procedure and stop when evidence is insufficient.\n"
    ).encode()
    openai_yaml = (
        "interface:\n"
        f'  display_name: "Research {domain.title()} Workflow"\n'
        f'  short_description: "Guide bounded {domain} evidence workflows"\n'
        f'  default_prompt: "Use ${skill_name} for a bounded research task."\n'
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    ).encode()
    payload["agents/openai.yaml"] = openai_yaml
    contract["payload_members"].append(
        {
            "name": "agents/openai.yaml",
            "role": "agent_metadata",
            "media_type": "application/yaml",
            "depends_on": ["SKILL.md"],
        }
    )
    bundle = draft_skill_candidate_bundle(
        eligibility,
        contract,
        payload,
        evidence,
        drafted_at=NOW,
    )
    validation_contract = {
        "validator": f"static-validator-{domain}",
        "policy_id": "p7b3-static-policy-v1",
        "registry_skills": [
            {
                "name": f"existing-{domain}-helper",
                "positive_triggers": [f"legacy {domain} helper task"],
            }
        ],
        "router_examples": [
            {"prompt": positive, "expected": "select_candidate"},
            {"prompt": exclusion, "expected": "reject_candidate"},
        ],
        "baseline_payload_members": [],
    }
    return bundle, payload, validation_contract


class SkillStaticValidationTest(unittest.TestCase):
    def test_math_and_quant_pass_one_static_validation_seam(self) -> None:
        receipts: list[SkillStaticValidationReceipt] = []
        for domain in ("math", "quant"):
            with self.subTest(domain=domain):
                bundle, payload, contract = _inputs(domain)
                receipt = validate_skill_candidate(
                    bundle,
                    payload,
                    contract,
                    validated_at=NOW,
                )
                receipts.append(receipt)
                self.assertEqual(
                    receipt.payload["schema"],
                    "skill-static-validation-receipt/v1",
                )
                self.assertEqual(receipt.payload["outcome"], "static_pass")
                self.assertEqual(receipt.payload["blockers"], [])
                self.assertTrue(receipt.payload["claims"]["payload_bytes_verified"])
                self.assertTrue(
                    receipt.payload["claims"]["platform_metadata_validated"]
                )
                self.assertTrue(
                    receipt.payload["claims"]["trigger_collision_checked"]
                )
                self.assertTrue(
                    receipt.payload["claims"]["router_examples_statically_checked"]
                )
                for claim in (
                    "semantic_review_completed",
                    "fresh_session_validated",
                    "private_evaluation_completed",
                    "publication_authorized",
                    "installation_authorized",
                    "activation_authorized",
                    "runtime_loaded",
                ):
                    self.assertFalse(receipt.payload["claims"][claim])
        self.assertNotEqual(receipts[0].sha256, receipts[1].sha256)

    def test_quant_registry_collision_is_auditable_static_fail(self) -> None:
        bundle, payload, contract = _inputs("quant")
        contract["registry_skills"][0] = {
            "name": bundle.payload["skill"]["name"],
            "positive_triggers": [
                bundle.payload["trigger_contract"]["positive_triggers"][0]
            ],
        }
        receipt = validate_skill_candidate(
            bundle, payload, contract, validated_at=NOW
        )
        self.assertEqual(receipt.payload["outcome"], "static_fail")
        self.assertEqual(
            {row["code"] for row in receipt.payload["blockers"]},
            {"skill_name_collision", "positive_trigger_collision"},
        )
        self.assertFalse(receipt.payload["claims"]["static_validation_passed"])
        self.assertFalse(receipt.payload["claims"]["trigger_collision_checked"])

    def test_payload_mutation_and_metadata_policy_fail_without_execution(self) -> None:
        bundle, payload, contract = _inputs("math")
        changed = dict(payload)
        changed["references/math.md"] += b"mutation"
        receipt = validate_skill_candidate(
            bundle, changed, contract, validated_at=NOW
        )
        self.assertEqual(receipt.payload["outcome"], "static_fail")
        self.assertIn(
            "payload_hash_or_size_mismatch",
            {row["code"] for row in receipt.payload["blockers"]},
        )
        self.assertFalse(receipt.payload["claims"]["payload_bytes_verified"])
        self.assertFalse(receipt.payload["claims"]["restricted_content_checked"])

        unsafe_metadata = dict(payload)
        unsafe_metadata["agents/openai.yaml"] = unsafe_metadata[
            "agents/openai.yaml"
        ].replace(b"false", b"true")
        receipt = validate_skill_candidate(
            bundle, unsafe_metadata, contract, validated_at=NOW
        )
        self.assertIn(
            "payload_hash_or_size_mismatch",
            {row["code"] for row in receipt.payload["blockers"]},
        )
        self.assertFalse(
            receipt.payload["claims"]["platform_metadata_validated"]
        )

    def test_router_examples_must_cover_declared_positive_and_negative_cases(
        self,
    ) -> None:
        bundle, payload, contract = _inputs("math")
        contract["router_examples"] = [
            {
                "prompt": "bounded math research task",
                "expected": "select_candidate",
            }
        ]
        receipt = validate_skill_candidate(
            bundle, payload, contract, validated_at=NOW
        )
        self.assertEqual(receipt.payload["outcome"], "static_fail")
        self.assertIn(
            "router_examples_incomplete",
            {row["code"] for row in receipt.payload["blockers"]},
        )

    def test_descriptor_only_payload_diff_is_deterministic(self) -> None:
        bundle, payload, contract = _inputs("math")
        reference = next(
            row
            for row in bundle.payload["payload_members"]
            if row["name"] == "references/math.md"
        )
        contract["baseline_payload_members"] = [
            {
                "name": "SKILL.md",
                "sha256": "0" * 64,
                "size_bytes": 1,
            },
            {
                "name": reference["name"],
                "sha256": reference["sha256"],
                "size_bytes": reference["size_bytes"],
            },
            {
                "name": "references/retired.md",
                "sha256": hashlib.sha256(b"retired").hexdigest(),
                "size_bytes": 7,
            },
        ]
        receipt = validate_skill_candidate(
            bundle, payload, contract, validated_at=NOW
        )
        self.assertEqual(
            receipt.payload["payload_diff"],
            {
                "baseline_snapshot_sha256": receipt.payload["payload_diff"][
                    "baseline_snapshot_sha256"
                ],
                "added": ["agents/openai.yaml"],
                "modified": ["SKILL.md"],
                "removed": ["references/retired.md"],
            },
        )

    def test_contract_restricted_content_and_wrapper_mutation_fail_closed(self) -> None:
        bundle, payload, contract = _inputs("math")
        restricted = "researcher@example.com"
        contract["router_examples"][0]["prompt"] = restricted
        with self.assertRaisesRegex(
            SkillStaticValidationError, "restricted content"
        ) as caught:
            validate_skill_candidate(bundle, payload, contract, validated_at=NOW)
        self.assertNotIn(restricted, str(caught.exception))

        bundle, payload, contract = _inputs("math")
        receipt = validate_skill_candidate(
            bundle, payload, contract, validated_at=NOW
        )
        mutated = receipt.payload
        mutated["outcome"] = "static_fail"
        with self.assertRaises(SkillStaticValidationError):
            SkillStaticValidationReceipt.from_payload(mutated)

    def test_graph_and_publication_recognize_static_validation_receipt(self) -> None:
        bundle, payload, contract = _inputs("math")
        receipt = validate_skill_candidate(
            bundle, payload, contract, validated_at=NOW
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            publish_record(json.dumps(receipt.payload), root=root)
            report = verify_record_graph(root)
        self.assertFalse(report.ok)
        self.assertEqual(
            report.families, {"skill-static-validation-receipt/v1": 1}
        )
        self.assertEqual(
            {violation.kind for violation in report.violations},
            {"dangling_reference"},
        )

        changed = receipt.payload
        restricted = "researcher@example.com"
        changed["limitations"][0] = restricted
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            with self.assertRaisesRegex(PublicationError, "restricted content") as caught:
                publish_record(json.dumps(changed), root=root)
            self.assertFalse(root.exists())
        self.assertNotIn(restricted, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
