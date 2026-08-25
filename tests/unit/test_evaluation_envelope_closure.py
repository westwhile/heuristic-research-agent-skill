"""Correctness Reset CR6: complete evaluation-envelope closure."""

from __future__ import annotations

import copy
import hashlib
import unittest
from typing import Any

from research_evolution.core import canonical_bytes, canonical_sha256, load_record
from research_evolution.core._graph import check_record_graph
from research_evolution.evolution import (
    ArtifactRecord,
    EvaluationEnvelopeClosureError,
    EvaluationEnvelopeClosureReceipt,
    close_evaluation_envelope,
)
from tests.unit.test_evolution_incubator import NOW, _candidate


REQUIRED_ROLES = (
    "authoritative_head_snapshot",
    "budget_configuration",
    "evaluator_configuration",
    "generator_configuration",
    "public_data_manifest",
    "rollback_target",
    "statistical_plan",
    "tool_configuration",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _artifact_payload(
    role: str,
    content: bytes,
    *,
    storage_class: str = "core_store",
    locator: str | None = None,
    attestation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_id = f"artifact-{role}"
    payload: dict[str, Any] = {
        "schema": "artifact-record/v1",
        "artifact_id": artifact_id,
        "role": role,
        "media_type": "application/octet-stream",
        "content_sha256": _sha(content),
        "size_bytes": len(content),
        "storage_class": storage_class,
        "redaction_state": "restricted" if storage_class == "hidden_evaluator" else "not_required",
        "created_at": NOW,
    }
    if locator is not None:
        payload["locator"] = locator
    if attestation is not None:
        payload["attestation"] = attestation
    return payload


def _inputs(name: str = "math") -> tuple[
    dict[str, Any],
    dict[str, bytes],
    list[dict[str, Any]],
    dict[str, bytes],
]:
    manifest, member_bytes = _candidate(name)
    rollback_bytes = manifest["rollback"].encode("utf-8")
    member_bytes["members/rollback.txt"] = rollback_bytes
    manifest["members"].append(
        {
            "name": "members/rollback.txt",
            "role": "other",
            "sha256": _sha(rollback_bytes),
            "size_bytes": len(rollback_bytes),
            "depends_on": ["members/patch.bin"],
        }
    )
    fixture_id = manifest["candidate_id"].removeprefix("candidate-")
    contents = {
        "authoritative_head_snapshot": f"head:{fixture_id}".encode(),
        "budget_configuration": b"budget",
        "evaluator_configuration": b"evaluator",
        "generator_configuration": b"generator",
        "public_data_manifest": f"data:{fixture_id}".encode(),
        "rollback_target": rollback_bytes,
        "statistical_plan": b"statistical-plan",
        "tool_configuration": b"tools",
    }
    artifacts: list[dict[str, Any]] = []
    artifact_bytes: dict[str, bytes] = {}
    for role in REQUIRED_ROLES:
        content = contents[role]
        if role == "rollback_target":
            payload = _artifact_payload(
                role,
                content,
                storage_class="bundle_member",
                locator="members/rollback.txt",
            )
        else:
            payload = _artifact_payload(
                role,
                content,
                locator=f"artifacts/{role}.json",
            )
            artifact_bytes[payload["artifact_id"]] = content
        artifacts.append(payload)
    return manifest, member_bytes, artifacts, artifact_bytes


class ArtifactRecordContractTest(unittest.TestCase):
    def test_public_and_hidden_storage_contracts_are_fail_closed(self) -> None:
        public = _artifact_payload(
            "tool_configuration", b"tools", locator="artifacts/tools.json"
        )
        record = ArtifactRecord.from_payload(public)
        self.assertEqual(record.content_sha256, _sha(b"tools"))

        missing_locator = copy.deepcopy(public)
        missing_locator.pop("locator")
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "requires locator"):
            ArtifactRecord.from_payload(missing_locator)

        hidden = _artifact_payload(
            "evaluator_configuration",
            b"hidden-evaluator",
            storage_class="hidden_evaluator",
            attestation={
                "attestor": "independent-evaluator",
                "independence_group": "hidden-suite-a",
                "observed_content_sha256": _sha(b"hidden-evaluator"),
                "observed_size_bytes": len(b"hidden-evaluator"),
                "bytes_observed": True,
                "content_disclosed": False,
                "semantic_review_completed": False,
                "limitations": ["Protocol identity is not cryptographic identity proof."],
            },
        )
        self.assertEqual(ArtifactRecord.from_payload(hidden).storage_class, "hidden_evaluator")
        leaked = copy.deepcopy(hidden)
        leaked["locator"] = "hidden/evaluator.json"
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "forbids locator"):
            ArtifactRecord.from_payload(leaked)


class EvaluationEnvelopeClosureContractTest(unittest.TestCase):
    def test_math_and_quant_close_candidate_members_and_all_required_roles(self) -> None:
        for name in ("math", "quant"):
            with self.subTest(name=name):
                manifest, members, artifacts, artifact_bytes = _inputs(name)
                receipt = close_evaluation_envelope(
                    manifest,
                    members,
                    artifacts,
                    artifact_bytes,
                    closed_at=NOW,
                )
                self.assertTrue(receipt.payload["candidate_members_byte_closed"])
                self.assertTrue(receipt.payload["evaluation_envelope_closed"])
                self.assertFalse(receipt.payload["semantic_review_completed"])
                self.assertEqual(
                    tuple(row["role"] for row in receipt.payload["artifacts"]),
                    REQUIRED_ROLES,
                )
                self.assertEqual(
                    receipt.payload["required_roles"], list(REQUIRED_ROLES)
                )

    def test_missing_extra_duplicate_or_mutated_artifact_fails_closed(self) -> None:
        manifest, members, artifacts, artifact_bytes = _inputs()
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "required roles"):
            close_evaluation_envelope(
                manifest, members, artifacts[:-1], artifact_bytes, closed_at=NOW
            )

        duplicate = copy.deepcopy(artifacts)
        duplicate[-1]["role"] = duplicate[0]["role"]
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "required roles"):
            close_evaluation_envelope(
                manifest, members, duplicate, artifact_bytes, closed_at=NOW
            )

        extra_bytes = {**artifact_bytes, "artifact-extra": b"extra"}
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "artifact byte set"):
            close_evaluation_envelope(
                manifest, members, artifacts, extra_bytes, closed_at=NOW
            )

        changed = dict(artifact_bytes)
        changed["artifact-tool_configuration"] = b"changed"
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "hash or size"):
            close_evaluation_envelope(
                manifest, members, artifacts, changed, closed_at=NOW
            )

    def test_candidate_bare_hashes_and_rollback_are_bound_to_artifact_bytes(self) -> None:
        manifest, members, artifacts, artifact_bytes = _inputs()
        manifest["evaluation_envelope"]["tools_sha256"] = "0" * 64
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "tool_configuration"):
            close_evaluation_envelope(
                manifest, members, artifacts, artifact_bytes, closed_at=NOW
            )

        manifest, members, artifacts, artifact_bytes = _inputs()
        manifest["rollback"] = "different rollback target"
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "rollback_target"):
            close_evaluation_envelope(
                manifest, members, artifacts, artifact_bytes, closed_at=NOW
            )

    def test_hidden_evaluator_requires_independent_attestation_and_no_bytes(self) -> None:
        manifest, members, artifacts, artifact_bytes = _inputs()
        index = next(
            index
            for index, row in enumerate(artifacts)
            if row["role"] == "evaluator_configuration"
        )
        hidden_content = artifact_bytes.pop("artifact-evaluator_configuration")
        artifacts[index] = _artifact_payload(
            "evaluator_configuration",
            hidden_content,
            storage_class="hidden_evaluator",
            attestation={
                "attestor": "independent-evaluator",
                "independence_group": "hidden-suite-a",
                "observed_content_sha256": _sha(hidden_content),
                "observed_size_bytes": len(hidden_content),
                "bytes_observed": True,
                "content_disclosed": False,
                "semantic_review_completed": False,
                "limitations": ["Protocol identity is not cryptographic identity proof."],
            },
        )
        receipt = close_evaluation_envelope(
            manifest, members, artifacts, artifact_bytes, closed_at=NOW
        )
        self.assertFalse(receipt.payload["hidden_bytes_disclosed"])

        disclosed = {**artifact_bytes, "artifact-evaluator_configuration": hidden_content}
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "artifact byte set"):
            close_evaluation_envelope(
                manifest, members, artifacts, disclosed, closed_at=NOW
            )

        same_principal = copy.deepcopy(artifacts)
        same_principal[index]["attestation"]["attestor"] = manifest["principals"]["reviewer"]
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "independent"):
            close_evaluation_envelope(
                manifest, members, same_principal, artifact_bytes, closed_at=NOW
            )

    def test_public_data_and_rollback_cannot_be_hidden(self) -> None:
        manifest, members, artifacts, artifact_bytes = _inputs()
        index = next(
            index
            for index, row in enumerate(artifacts)
            if row["role"] == "public_data_manifest"
        )
        content = artifact_bytes.pop("artifact-public_data_manifest")
        artifacts[index] = _artifact_payload(
            "public_data_manifest",
            content,
            storage_class="hidden_evaluator",
            attestation={
                "attestor": "independent-evaluator",
                "independence_group": "hidden-suite-a",
                "observed_content_sha256": _sha(content),
                "observed_size_bytes": len(content),
                "bytes_observed": True,
                "content_disclosed": False,
                "semantic_review_completed": False,
                "limitations": ["Synthetic test attestation."],
            },
        )
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "cannot be hidden"):
            close_evaluation_envelope(
                manifest, members, artifacts, artifact_bytes, closed_at=NOW
            )

    def test_receipt_wrapper_detects_root_and_reference_mutation(self) -> None:
        manifest, members, artifacts, artifact_bytes = _inputs()
        receipt = close_evaluation_envelope(
            manifest, members, artifacts, artifact_bytes, closed_at=NOW
        )
        changed = receipt.payload
        changed["artifacts"][0]["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "closure_root"):
            EvaluationEnvelopeClosureReceipt.from_payload(changed)

        changed = receipt.payload
        changed["artifacts"][0]["sha256"] = canonical_sha256({"wrong": True})
        changed["closure_root_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in changed.items()
                if key not in {"envelope_closure_receipt_id", "closure_root_sha256"}
            }
        )
        with self.assertRaisesRegex(EvaluationEnvelopeClosureError, "receipt_id"):
            EvaluationEnvelopeClosureReceipt.from_payload(changed)

    def test_core_graph_verifies_candidate_and_every_artifact_pin(self) -> None:
        manifest, members, artifacts, artifact_bytes = _inputs()
        receipt = close_evaluation_envelope(
            manifest, members, artifacts, artifact_bytes, closed_at=NOW
        )
        candidate_record = load_record(canonical_bytes(manifest))
        artifact_records = {
            row["artifact_id"]: load_record(canonical_bytes(row)) for row in artifacts
        }
        records = {
            "candidate-manifest/v1": {
                manifest["candidate_id"]: candidate_record,
            },
            "artifact-record/v1": artifact_records,
            "evaluation-envelope-closure-receipt/v1": {
                receipt.payload["envelope_closure_receipt_id"]: load_record(
                    canonical_bytes(receipt.payload)
                ),
            },
        }
        violations, _ = check_record_graph(records)
        self.assertNotIn("pin_mismatch", {row.kind for row in violations})

        changed = receipt.payload
        changed["artifacts"][0]["sha256"] = "0" * 64
        records["evaluation-envelope-closure-receipt/v1"] = {
            changed["envelope_closure_receipt_id"]: load_record(canonical_bytes(changed))
        }
        violations, _ = check_record_graph(records)
        pin_mismatches = [row for row in violations if row.kind == "pin_mismatch"]
        self.assertEqual(len(pin_mismatches), 1)
        self.assertIn(changed["artifacts"][0]["artifact_id"], pin_mismatches[0].detail)


if __name__ == "__main__":
    unittest.main()
