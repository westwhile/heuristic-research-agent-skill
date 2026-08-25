"""P7A contracts for immutable candidate closure and context transfer."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from research_evolution.core import canonical_sha256
from research_evolution.evolution import (
    ArtifactClosureError,
    ArtifactClosureReceipt,
    CandidateManifestError,
    ContextBundle,
    ContextBundleError,
    ContextBundleV2,
    ContextMaterialAssessment,
    ContextPreparationError,
    build_context_bundle,
    close_candidate_bundle,
    prepare_context,
)

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "evolution" / "p7a"
NOW = "2026-08-24T00:00:00Z"


def _sha(content: bytes | str) -> str:
    raw = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(raw).hexdigest()


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def _candidate(name: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    source = _fixture(name)
    members = {
        "members/baseline.bin": f"baseline:{source['fixture_id']}".encode(),
        "members/patch.bin": f"patch:{source['fixture_id']}".encode(),
        "members/tests.json": f"tests:{source['fixture_id']}".encode(),
    }
    case_refs = [
        {"case_id": case_id, "sha256": _sha(f"case:{case_id}")}
        for case_id in source["case_ids"]
    ]
    pattern_ref = {
        "pattern_id": source["pattern_id"],
        "sha256": _sha(f"pattern:{source['pattern_id']}"),
    }
    materials = [
        {
            "name": "safe-summary",
            "content_sha256": _sha(source["safe_summary"]),
            "content": source["safe_summary"],
            "retention": "minimal_safe",
        },
        {
            "name": "compact-detail",
            "content_sha256": _sha(source["compact_detail"]),
            "content": source["compact_detail"],
            "retention": "compact",
        },
        {
            "name": "normal-detail",
            "content_sha256": _sha(source["normal_detail"]),
            "content": source["normal_detail"],
            "retention": "normal_only",
        },
    ]
    manifest = {
        "schema": "candidate-manifest/v1",
        "candidate_id": f"candidate-{source['fixture_id']}",
        "status": "staged_candidate",
        "objective": source["objective"],
        "principals": {
            "author": f"author-{source['fixture_id']}",
            "reviewer": f"reviewer-{source['fixture_id']}",
        },
        "baseline_sha256": _sha(members["members/baseline.bin"]),
        "patch_sha256": _sha(members["members/patch.bin"]),
        "source_cases": case_refs,
        "source_patterns": [pattern_ref],
        "evaluation_envelope": {
            "model": "fixture-model",
            "reasoning": "fixture-reasoning",
            "tools_sha256": _sha("tools"),
            "budget_sha256": _sha("budget"),
            "data_sha256": _sha(f"data:{source['fixture_id']}"),
            "evaluator_sha256": _sha("evaluator"),
        },
        "members": [
            {
                "name": "members/baseline.bin",
                "role": "baseline",
                "sha256": _sha(members["members/baseline.bin"]),
                "size_bytes": len(members["members/baseline.bin"]),
                "depends_on": [],
            },
            {
                "name": "members/patch.bin",
                "role": "patch",
                "sha256": _sha(members["members/patch.bin"]),
                "size_bytes": len(members["members/patch.bin"]),
                "depends_on": ["members/baseline.bin"],
            },
            {
                "name": "members/tests.json",
                "role": "tests",
                "sha256": _sha(members["members/tests.json"]),
                "size_bytes": len(members["members/tests.json"]),
                "depends_on": ["members/patch.bin"],
            },
        ],
        "exclusions": [
            {"name": "private/source.bin", "reason": "Not part of the candidate."}
        ],
        "risks": ["The bounded candidate can fail its comparison."],
        "rollback": "Keep the immutable baseline selected.",
        "context": {
            "authoritative_head": {
                "record_id": f"head-{source['fixture_id']}",
                "sha256": _sha(f"head:{source['fixture_id']}"),
            },
            "unresolved_obligations": ["Independent semantic review remains open."],
            "source_lifecycle": [
                *[
                    {
                        "source_id": row["case_id"],
                        "sha256": row["sha256"],
                        "status": "current",
                        "rationale": "Pinned fixture source is current.",
                    }
                    for row in case_refs
                ],
                {
                    "source_id": pattern_ref["pattern_id"],
                    "sha256": pattern_ref["sha256"],
                    "status": "current",
                    "rationale": "Pinned fixture source is current.",
                },
            ],
            "materials": materials,
        },
        "claims": {
            "installation_authorized": False,
            "activation_authorized": False,
            "publication_authorized": False,
            "semantic_review_completed": False,
        },
        "created_at": NOW,
    }
    return manifest, members


def _context_policies(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["name"]: {
            "classification": "public",
            "taint_labels": [],
            "disposition": "include_original",
            "scanner": {
                "tool": "fixture-scanner",
                "version": "1.0.0",
                "policy_sha256": _sha("fixture-scanner-policy"),
            },
            "redaction": {"state": "not_required"},
            "export": {
                "outcome": "allow",
                "policy_sha256": _sha("fixture-export-policy"),
                "decided_by": "fixture-reviewer",
            },
            "retention_until": "2027-08-24T00:00:00Z",
            "encryption_required": False,
        }
        for row in manifest["context"]["materials"]
    }


class EvolutionIncubatorContractTest(unittest.TestCase):
    def test_context_v2_prepares_assessments_and_budgeted_bundle_through_one_interface(
        self,
    ) -> None:
        manifest, _ = _candidate("math")
        preparation = prepare_context(
            manifest,
            material_policies=_context_policies(manifest),
            mode="normal",
            max_bytes=30_000,
            tokenizer_id="fixture-tokenizer",
            tokenizer_revision="2026-08-24",
            max_tokens=10_000,
            built_at=NOW,
        )
        self.assertEqual(len(preparation.assessments), 3)
        self.assertEqual(preparation.bundle.payload["schema"], "context-bundle/v2")
        self.assertEqual(len(preparation.bundle.payload["included_materials"]), 3)
        self.assertLessEqual(
            preparation.bundle.payload["token_budget"]["estimated_tokens"],
            preparation.bundle.payload["token_budget"]["max_tokens"],
        )
        self.assertEqual(
            preparation.bundle.payload["token_budget"]["estimation_method"],
            "text_utf8_bytes_upper_bound/v1",
        )
        self.assertFalse(
            preparation.bundle.payload["claims"]["runtime_token_count_verified"]
        )

    def test_context_v2_requires_exact_policy_set_and_both_budgets(self) -> None:
        manifest, _ = _candidate("math")
        policies = _context_policies(manifest)
        policies.pop("normal-detail")
        with self.assertRaisesRegex(ContextPreparationError, "exactly match"):
            prepare_context(
                manifest,
                material_policies=policies,
                mode="normal",
                max_bytes=30_000,
                tokenizer_id="fixture-tokenizer",
                tokenizer_revision="2026-08-24",
                max_tokens=10_000,
                built_at=NOW,
            )
        with self.assertRaisesRegex(ContextPreparationError, "cannot fit max_tokens"):
            prepare_context(
                manifest,
                material_policies=_context_policies(manifest),
                mode="minimal_safe",
                max_bytes=30_000,
                tokenizer_id="fixture-tokenizer",
                tokenizer_revision="2026-08-24",
                max_tokens=1,
                built_at=NOW,
            )

    def test_context_v2_refuses_tainted_original_and_never_echoes_restricted_text(
        self,
    ) -> None:
        manifest, _ = _candidate("math")
        policies = _context_policies(manifest)
        policies["safe-summary"]["taint_labels"] = ["pii"]
        with self.assertRaisesRegex(ContextPreparationError, "untainted"):
            prepare_context(
                manifest,
                material_policies=policies,
                mode="minimal_safe",
                max_bytes=30_000,
                tokenizer_id="fixture-tokenizer",
                tokenizer_revision="2026-08-24",
                max_tokens=10_000,
                built_at=NOW,
            )

        restricted = "researcher@example.com"
        manifest, _ = _candidate("math")
        manifest["context"]["materials"][0]["content"] = restricted
        manifest["context"]["materials"][0]["content_sha256"] = _sha(restricted)
        with self.assertRaisesRegex(ContextPreparationError, "restricted content") as caught:
            prepare_context(
                manifest,
                material_policies=_context_policies(manifest),
                mode="minimal_safe",
                max_bytes=30_000,
                tokenizer_id="fixture-tokenizer",
                tokenizer_revision="2026-08-24",
                max_tokens=10_000,
                built_at=NOW,
            )
        self.assertNotIn(restricted, str(caught.exception))

        manifest, _ = _candidate("math")
        preparation = prepare_context(
            manifest,
            material_policies=_context_policies(manifest),
            mode="minimal_safe",
            max_bytes=30_000,
            tokenizer_id="fixture-tokenizer",
            tokenizer_revision="2026-08-24",
            max_tokens=10_000,
            built_at=NOW,
        )
        changed = preparation.assessments[0].payload
        changed["scanner"]["tool"] = restricted
        changed["context_material_assessment_id"] = "context-assessment-" + canonical_sha256(
            {
                key: value
                for key, value in changed.items()
                if key != "context_material_assessment_id"
            }
        )[:16]
        with self.assertRaisesRegex(ContextPreparationError, "restricted content") as caught:
            ContextMaterialAssessment.from_payload(changed)
        self.assertNotIn(restricted, str(caught.exception))

        changed_bundle = preparation.bundle.payload
        changed_bundle["token_budget"]["tokenizer_id"] = restricted
        changed_bundle["context_bundle_id"] = "context-" + canonical_sha256(
            {
                key: value
                for key, value in changed_bundle.items()
                if key != "context_bundle_id"
            }
        )[:16]
        with self.assertRaisesRegex(ContextPreparationError, "restricted content") as caught:
            ContextBundleV2.from_payload(changed_bundle)
        self.assertNotIn(restricted, str(caught.exception))

        manifest, _ = _candidate("math")
        policies = _context_policies(manifest)
        policies["safe-summary"]["export"]["decided_by"] = restricted
        with self.assertRaisesRegex(ContextPreparationError, "restricted content") as caught:
            prepare_context(
                manifest,
                material_policies=policies,
                mode="minimal_safe",
                max_bytes=30_000,
                tokenizer_id="fixture-tokenizer",
                tokenizer_revision="2026-08-24",
                max_tokens=10_000,
                built_at=NOW,
            )
        self.assertNotIn(restricted, str(caught.exception))

    def test_context_v2_redaction_binds_safe_output_and_receipt(self) -> None:
        manifest, _ = _candidate("math")
        policies = _context_policies(manifest)
        redacted = "Redacted public summary."
        policies["safe-summary"].update(
            {
                "classification": "confidential",
                "taint_labels": ["pii"],
                "disposition": "include_redacted",
                "redacted_content": redacted,
                "redaction": {
                    "state": "applied",
                    "output_classification": "public",
                    "output_sha256": _sha(redacted),
                    "receipt_sha256": _sha("redaction-receipt"),
                },
            }
        )
        preparation = prepare_context(
            manifest,
            material_policies=policies,
            mode="minimal_safe",
            max_bytes=30_000,
            tokenizer_id="fixture-tokenizer",
            tokenizer_revision="2026-08-24",
            max_tokens=10_000,
            built_at=NOW,
        )
        material = preparation.bundle.payload["included_materials"][0]
        self.assertEqual(material["content"], redacted)
        self.assertEqual(material["redaction_state"], "applied")
        self.assertEqual(material["classification"], "public")

        policies["safe-summary"]["redaction"]["output_sha256"] = "0" * 64
        with self.assertRaisesRegex(ContextPreparationError, "does not match"):
            prepare_context(
                manifest,
                material_policies=policies,
                mode="minimal_safe",
                max_bytes=30_000,
                tokenizer_id="fixture-tokenizer",
                tokenizer_revision="2026-08-24",
                max_tokens=10_000,
                built_at=NOW,
            )

    def test_context_v2_protects_restricted_material_without_plaintext(self) -> None:
        manifest, _ = _candidate("math")
        policies = _context_policies(manifest)
        source = manifest["context"]["materials"][0]
        policies["safe-summary"] = {
            "classification": "restricted",
            "taint_labels": ["licensed_restricted"],
            "disposition": "protected_hash_only",
            "scanner": {
                "tool": "fixture-scanner",
                "version": "1.0.0",
                "policy_sha256": _sha("fixture-scanner-policy"),
            },
            "redaction": {"state": "rejected"},
            "export": {
                "outcome": "deny",
                "policy_sha256": _sha("fixture-export-policy"),
                "decided_by": "fixture-reviewer",
            },
            "retention_until": "2027-08-24T00:00:00Z",
            "encryption_required": True,
            "protected_artifact": {
                "artifact_id": "protected-safe-summary",
                "record_sha256": _sha("protected-record"),
                "content_sha256": source["content_sha256"],
                "size_bytes": len(source["content"].encode("utf-8")),
                "storage_class": "external_encrypted",
            },
        }
        preparation = prepare_context(
            manifest,
            material_policies=policies,
            mode="minimal_safe",
            max_bytes=30_000,
            tokenizer_id="fixture-tokenizer",
            tokenizer_revision="2026-08-24",
            max_tokens=10_000,
            built_at=NOW,
        )
        self.assertEqual(preparation.bundle.payload["included_materials"], [])
        protected = preparation.bundle.payload["protected_materials"][0]
        self.assertNotIn("content", protected)
        self.assertTrue(protected["encryption_required"])
        self.assertEqual(protected["content_sha256"], source["content_sha256"])

    def test_context_v2_lifecycle_and_wrapper_mutations_fail_closed(self) -> None:
        manifest, _ = _candidate("quant")
        policies = _context_policies(manifest)
        policies["safe-summary"]["retention_until"] = NOW
        with self.assertRaisesRegex(ContextPreparationError, "after assessed_at"):
            prepare_context(
                manifest,
                material_policies=policies,
                mode="minimal_safe",
                max_bytes=30_000,
                tokenizer_id="fixture-tokenizer",
                tokenizer_revision="2026-08-24",
                max_tokens=10_000,
                built_at=NOW,
            )

        policies = _context_policies(manifest)
        preparation = prepare_context(
            manifest,
            material_policies=policies,
            mode="compact",
            max_bytes=30_000,
            tokenizer_id="fixture-tokenizer",
            tokenizer_revision="2026-08-24",
            max_tokens=10_000,
            built_at=NOW,
        )
        changed_assessment = preparation.assessments[0].payload
        changed_assessment["classification"] = "internal_safe"
        with self.assertRaisesRegex(ContextPreparationError, "does not bind"):
            ContextMaterialAssessment.from_payload(changed_assessment)

        changed_bundle = preparation.bundle.payload
        changed_bundle["included_materials"][0]["content"] += " mutation"
        changed_bundle["context_bundle_id"] = "context-" + canonical_sha256(
            {
                key: value
                for key, value in changed_bundle.items()
                if key != "context_bundle_id"
            }
        )[:16]
        with self.assertRaisesRegex(ContextPreparationError, "does not match"):
            ContextBundleV2.from_payload(changed_bundle)

    def test_math_and_quant_fixtures_use_the_same_two_interfaces(self) -> None:
        for name in ("math", "quant"):
            with self.subTest(fixture=name):
                manifest, members = _candidate(name)
                receipt = close_candidate_bundle(manifest, members, closed_at=NOW)
                self.assertTrue(receipt.payload["byte_closed"])
                self.assertFalse(receipt.payload["semantic_review_completed"])
                self.assertEqual(
                    receipt.payload["topological_order"],
                    [
                        "members/baseline.bin",
                        "members/patch.bin",
                        "members/tests.json",
                    ],
                )
                expected_counts = {
                    "normal": (3, 0),
                    "compact": (2, 1),
                    "minimal_safe": (1, 2),
                }
                for mode, counts in expected_counts.items():
                    bundle = build_context_bundle(
                        manifest, mode=mode, max_bytes=20_000, built_at=NOW
                    )
                    self.assertEqual(
                        (
                            len(bundle.payload["included_materials"]),
                            len(bundle.payload["omissions"]),
                        ),
                        counts,
                    )
                    self.assertFalse(bundle.payload["claims"]["publication_authorized"])

    def test_receipt_is_immutable_against_input_and_output_mutation(self) -> None:
        manifest, members = _candidate("math")
        receipt = close_candidate_bundle(manifest, members, closed_at=NOW)
        expected = receipt.sha256
        manifest["objective"] = "mutated"
        members["members/patch.bin"] = b"mutated"
        exposed = receipt.payload
        exposed["members"][0]["sha256"] = "0" * 64
        self.assertEqual(receipt.sha256, expected)
        self.assertNotEqual(receipt.payload["members"][0]["sha256"], "0" * 64)

    def test_member_mutation_missing_extra_and_wrong_type_fail_closed(self) -> None:
        manifest, members = _candidate("quant")
        mutated = dict(members)
        mutated["members/patch.bin"] = b"changed"
        with self.assertRaisesRegex(ArtifactClosureError, "hash or size"):
            close_candidate_bundle(manifest, mutated, closed_at=NOW)
        missing = dict(members)
        missing.pop("members/tests.json")
        with self.assertRaisesRegex(ArtifactClosureError, "member set mismatch"):
            close_candidate_bundle(manifest, missing, closed_at=NOW)
        extra = {**members, "members/extra.bin": b"extra"}
        with self.assertRaisesRegex(ArtifactClosureError, "member set mismatch"):
            close_candidate_bundle(manifest, extra, closed_at=NOW)
        wrong_type = dict(members)
        wrong_type["members/tests.json"] = bytearray(b"tests")  # type: ignore[assignment]
        with self.assertRaisesRegex(ArtifactClosureError, "exact bytes"):
            close_candidate_bundle(manifest, wrong_type, closed_at=NOW)

    def test_principal_dependency_and_receipt_last_rules_fail_closed(self) -> None:
        manifest, members = _candidate("math")
        same_principal = copy.deepcopy(manifest)
        same_principal["principals"]["reviewer"] = same_principal["principals"]["author"]
        with self.assertRaisesRegex(ArtifactClosureError, "must be distinct"):
            close_candidate_bundle(same_principal, members, closed_at=NOW)

        cyclic = copy.deepcopy(manifest)
        cyclic["members"][0]["depends_on"] = ["members/tests.json"]
        with self.assertRaisesRegex(ArtifactClosureError, "cycle"):
            close_candidate_bundle(cyclic, members, closed_at=NOW)

        reserved = copy.deepcopy(manifest)
        row = reserved["members"][2]
        old_name = row["name"]
        row["name"] = "artifact-closure-receipt.json"
        reserved_bytes = dict(members)
        reserved_bytes[row["name"]] = reserved_bytes.pop(old_name)
        with self.assertRaisesRegex(ArtifactClosureError, "generated last"):
            close_candidate_bundle(reserved, reserved_bytes, closed_at=NOW)

    def test_invalidated_source_blocks_closure_but_is_never_omitted_from_context(self) -> None:
        manifest, members = _candidate("quant")
        manifest["context"]["source_lifecycle"][0]["status"] = "retracted"
        manifest["context"]["source_lifecycle"][0]["rationale"] = "Source was retracted."
        with self.assertRaisesRegex(ArtifactClosureError, "invalidated sources"):
            close_candidate_bundle(manifest, members, closed_at=NOW)
        bundle = build_context_bundle(
            manifest, mode="minimal_safe", max_bytes=20_000, built_at=NOW
        )
        self.assertEqual(len(bundle.payload["invalidated_sources"]), 1)
        self.assertEqual(bundle.payload["invalidated_sources"][0]["status"], "retracted")

    def test_context_budget_never_triggers_an_implicit_mode_downgrade(self) -> None:
        manifest, _ = _candidate("math")
        with self.assertRaisesRegex(ContextBundleError, "cannot fit"):
            build_context_bundle(manifest, mode="normal", max_bytes=1, built_at=NOW)
        with self.assertRaisesRegex(ContextBundleError, "cannot fit"):
            build_context_bundle(
                manifest, mode="minimal_safe", max_bytes=1, built_at=NOW
            )

    def test_context_builder_rejects_restricted_material_without_echo(self) -> None:
        restricted_values = (
            "sk-" + "A" * 24,
            "researcher@example.com",
            r"C:\Users\researcher\private.txt",
        )
        for restricted in restricted_values:
            with self.subTest(restricted=restricted):
                manifest, _ = _candidate("math")
                material = manifest["context"]["materials"][0]
                material["content"] = restricted
                material["content_sha256"] = _sha(restricted)
                with self.assertRaisesRegex(
                    ContextBundleError, "restricted content"
                ) as caught:
                    build_context_bundle(
                        manifest,
                        mode="minimal_safe",
                        max_bytes=20_000,
                        built_at=NOW,
                    )
                self.assertNotIn(restricted, str(caught.exception))

    def test_manifest_semantic_mutations_fail_before_receipt_or_context(self) -> None:
        manifest, members = _candidate("math")
        bad_lifecycle = copy.deepcopy(manifest)
        bad_lifecycle["context"]["source_lifecycle"][-1]["source_id"] = "other-source"
        with self.assertRaisesRegex(CandidateManifestError, "exactly pin"):
            build_context_bundle(
                bad_lifecycle, mode="minimal_safe", max_bytes=20_000, built_at=NOW
            )
        bad_material = copy.deepcopy(manifest)
        bad_material["context"]["materials"][0]["content"] += " mutation"
        with self.assertRaisesRegex(CandidateManifestError, "content_sha256"):
            close_candidate_bundle(bad_material, members, closed_at=NOW)

    def test_receipt_and_context_wrapper_mutations_are_detected(self) -> None:
        manifest, members = _candidate("quant")
        receipt = close_candidate_bundle(manifest, members, closed_at=NOW)
        changed_receipt = receipt.payload
        changed_receipt["closure_root_sha256"] = "0" * 64
        with self.assertRaisesRegex(ArtifactClosureError, "closure_root"):
            ArtifactClosureReceipt.from_payload(changed_receipt)

        bundle = build_context_bundle(
            manifest, mode="compact", max_bytes=20_000, built_at=NOW
        )
        changed_bundle = bundle.payload
        changed_bundle["included_materials"][0]["content"] += " mutation"
        changed_bundle["context_bundle_id"] = "context-" + canonical_sha256(
            {key: value for key, value in changed_bundle.items() if key != "context_bundle_id"}
        )[:16]
        with self.assertRaisesRegex(ContextBundleError, "does not match its hash"):
            ContextBundle.from_payload(changed_bundle)


if __name__ == "__main__":
    unittest.main()
