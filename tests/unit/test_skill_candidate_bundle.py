"""P7B2 contracts for byte-closed candidate Skill payload drafting."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from research_evolution.core import (
    PublicationError,
    RecordValidationError,
    canonical_bytes,
    load_record,
    publish_record,
    verify_record_graph,
)
from research_evolution.evolution import (
    SkillCandidateBundle,
    SkillCandidateBundleError,
    assess_candidate_eligibility,
    draft_skill_candidate_bundle,
)

from .test_candidate_eligibility import _inputs as _eligibility_inputs


NOW = "2026-08-25T00:00:00Z"


def _inputs(
    domain: str = "math",
) -> tuple[Any, dict[str, Any], dict[str, bytes], dict[str, bytes]]:
    manifest, receipt, assessment, evidence = _eligibility_inputs(domain)
    eligibility = assess_candidate_eligibility(
        manifest,
        receipt,
        assessment,
        evidence,
        assessed_at=NOW,
    )
    skill_name = f"research-{domain}-workflow"
    description = (
        f"Guide bounded {domain} research workflows. "
        f"Use when a {domain} task needs an auditable evidence-first process."
    )
    skill_md = (
        "---\n"
        f"name: {skill_name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"# {domain.title()} research workflow\n\n"
        "Follow the bounded procedure and stop when evidence is insufficient.\n"
    ).encode("utf-8")
    reference = (
        f"# {domain.title()} reference\n\n"
        "This synthetic contract fixture contains no external source material.\n"
    ).encode("utf-8")
    payload = {
        "SKILL.md": skill_md,
        f"references/{domain}.md": reference,
    }
    contract = {
        "drafter": f"candidate-drafter-{domain}",
        "skill_name": skill_name,
        "description": description,
        "positive_triggers": [f"bounded {domain} research task"],
        "exclusions": [f"unbounded or production {domain} operation"],
        "payload_members": [
            {
                "name": "SKILL.md",
                "role": "skill_instructions",
                "media_type": "text/markdown",
                "depends_on": [],
            },
            {
                "name": f"references/{domain}.md",
                "role": "reference",
                "media_type": "text/markdown",
                "depends_on": ["SKILL.md"],
            },
        ],
        "rollback_plan": "Retain the immutable pre-candidate baseline.",
        "retirement_plan": "Retire only through a separately reviewed successor.",
    }
    return eligibility, contract, payload, evidence


class SkillCandidateBundleTest(unittest.TestCase):
    def test_math_and_quant_draft_distinct_closed_bundles_through_one_seam(
        self,
    ) -> None:
        bundles: list[SkillCandidateBundle] = []
        for domain in ("math", "quant"):
            with self.subTest(domain=domain):
                eligibility, contract, payload, evidence = _inputs(domain)
                bundle = draft_skill_candidate_bundle(
                    eligibility,
                    contract,
                    payload,
                    evidence,
                    drafted_at=NOW,
                )
                bundles.append(bundle)
                self.assertEqual(bundle.payload["schema"], "skill-candidate-bundle/v1")
                self.assertEqual(bundle.payload["status"], "drafted_candidate")
                self.assertEqual(bundle.payload["skill"]["name"], contract["skill_name"])
                self.assertEqual(bundle.payload["skill"]["entrypoint"], "SKILL.md")
                self.assertEqual(len(bundle.payload["payload_members"]), 2)
                self.assertEqual(len(bundle.payload["eligibility_evidence_members"]), 7)
                self.assertTrue(bundle.payload["closure"]["payload_byte_closed"])
                self.assertTrue(
                    bundle.payload["closure"]["eligibility_evidence_byte_closed"]
                )
                for claim in (
                    "semantic_review_completed",
                    "fresh_session_validated",
                    "private_evaluation_completed",
                    "promotion_authorized",
                    "publication_authorized",
                    "installation_authorized",
                    "activation_authorized",
                    "runtime_loaded",
                ):
                    self.assertFalse(bundle.payload["claims"][claim])
        self.assertNotEqual(bundles[0].sha256, bundles[1].sha256)
        self.assertNotEqual(
            bundles[0].payload["closure"]["closure_root_sha256"],
            bundles[1].payload["closure"]["closure_root_sha256"],
        )

    def test_only_eligible_attestations_can_enter_payload_drafting(self) -> None:
        manifest, receipt, assessment, evidence = _eligibility_inputs("math")
        assessment["criteria"][0]["status"] = "unverified"
        deferred = assess_candidate_eligibility(
            manifest, receipt, assessment, evidence, assessed_at=NOW
        )
        _, contract, payload, _ = _inputs("math")
        with self.assertRaisesRegex(
            SkillCandidateBundleError, "does not permit payload drafting"
        ):
            draft_skill_candidate_bundle(
                deferred,
                contract,
                payload,
                evidence,
                drafted_at=NOW,
            )

        assessment["criteria"][1]["status"] = "unsatisfied"
        rejected = assess_candidate_eligibility(
            manifest, receipt, assessment, evidence, assessed_at=NOW
        )
        with self.assertRaisesRegex(
            SkillCandidateBundleError, "does not permit payload drafting"
        ):
            draft_skill_candidate_bundle(
                rejected,
                contract,
                payload,
                evidence,
                drafted_at=NOW,
            )

    def test_restricted_eligibility_evidence_is_refused_without_echo(self) -> None:
        manifest, receipt, assessment, evidence = _eligibility_inputs("math")
        evidence_name = assessment["criteria"][0]["evidence_name"]
        restricted = ("sk-" + "A" * 24).encode("utf-8")
        evidence[evidence_name] = restricted
        eligibility = assess_candidate_eligibility(
            manifest, receipt, assessment, evidence, assessed_at=NOW
        )
        _, contract, payload, _ = _inputs("math")
        with self.assertRaisesRegex(
            SkillCandidateBundleError, "restricted content"
        ) as caught:
            draft_skill_candidate_bundle(
                eligibility,
                contract,
                payload,
                evidence,
                drafted_at=NOW,
            )
        self.assertNotIn(restricted.decode("utf-8"), str(caught.exception))

    def test_payload_and_evidence_sets_are_exact(self) -> None:
        eligibility, contract, payload, evidence = _inputs("math")
        extra_payload = {**payload, "references/extra.md": b"extra"}
        with self.assertRaisesRegex(
            SkillCandidateBundleError, "payload byte set must exactly match"
        ):
            draft_skill_candidate_bundle(
                eligibility,
                contract,
                extra_payload,
                evidence,
                drafted_at=NOW,
            )

        missing_evidence = dict(evidence)
        missing_evidence.pop(next(iter(missing_evidence)))
        with self.assertRaisesRegex(
            SkillCandidateBundleError, "evidence byte set must exactly match"
        ):
            draft_skill_candidate_bundle(
                eligibility,
                contract,
                payload,
                missing_evidence,
                drafted_at=NOW,
            )

    def test_skill_layout_frontmatter_and_dependency_graph_fail_closed(self) -> None:
        eligibility, contract, payload, evidence = _inputs("math")

        wrong_frontmatter = dict(payload)
        wrong_frontmatter["SKILL.md"] = wrong_frontmatter["SKILL.md"].replace(
            b"name: research-math-workflow",
            b"name: different-name",
        )
        with self.assertRaisesRegex(
            SkillCandidateBundleError, "frontmatter must exactly match"
        ):
            draft_skill_candidate_bundle(
                eligibility,
                contract,
                wrong_frontmatter,
                evidence,
                drafted_at=NOW,
            )

        auxiliary_contract = copy.deepcopy(contract)
        auxiliary_contract["payload_members"].append(
            {
                "name": "README.md",
                "role": "reference",
                "media_type": "text/markdown",
                "depends_on": ["SKILL.md"],
            }
        )
        with self.assertRaisesRegex(SkillCandidateBundleError, "auxiliary file"):
            draft_skill_candidate_bundle(
                eligibility,
                auxiliary_contract,
                {**payload, "README.md": b"not part of a Skill payload"},
                evidence,
                drafted_at=NOW,
            )

        cyclic_contract = copy.deepcopy(contract)
        cyclic_contract["payload_members"][0]["depends_on"] = [
            "references/math.md"
        ]
        with self.assertRaisesRegex(SkillCandidateBundleError, "contains a cycle"):
            draft_skill_candidate_bundle(
                eligibility,
                cyclic_contract,
                payload,
                evidence,
                drafted_at=NOW,
            )

    def test_payload_restricted_content_and_non_utf8_fail_without_echo(self) -> None:
        eligibility, contract, payload, evidence = _inputs("math")
        restricted = "researcher@example.com"
        changed = dict(payload)
        changed["references/math.md"] = restricted.encode("utf-8")
        with self.assertRaisesRegex(
            SkillCandidateBundleError, "restricted content"
        ) as caught:
            draft_skill_candidate_bundle(
                eligibility,
                contract,
                changed,
                evidence,
                drafted_at=NOW,
            )
        self.assertNotIn(restricted, str(caught.exception))

        changed["references/math.md"] = b"\xff\xfe"
        with self.assertRaisesRegex(SkillCandidateBundleError, "strict UTF-8"):
            draft_skill_candidate_bundle(
                eligibility,
                contract,
                changed,
                evidence,
                drafted_at=NOW,
            )

    def test_wrapper_mutation_breaks_id_or_closure_binding(self) -> None:
        eligibility, contract, payload, evidence = _inputs("math")
        bundle = draft_skill_candidate_bundle(
            eligibility,
            contract,
            payload,
            evidence,
            drafted_at=NOW,
        )
        original_sha256 = bundle.sha256
        mutated = bundle.payload
        mutated["payload_members"][0]["sha256"] = "0" * 64
        self.assertEqual(bundle.sha256, original_sha256)
        with self.assertRaisesRegex(SkillCandidateBundleError, "bundle id"):
            SkillCandidateBundle.from_payload(mutated)

    def test_schema_refuses_impossible_negative_member_sizes(self) -> None:
        eligibility, contract, payload, evidence = _inputs("math")
        bundle = draft_skill_candidate_bundle(
            eligibility,
            contract,
            payload,
            evidence,
            drafted_at=NOW,
        )
        for field in ("payload_members", "eligibility_evidence_members"):
            with self.subTest(field=field):
                mutated = bundle.payload
                mutated[field][0]["size_bytes"] = -1
                with self.assertRaises(RecordValidationError):
                    load_record(canonical_bytes(mutated))

    def test_core_graph_recognizes_candidate_bundle_references(self) -> None:
        eligibility, contract, payload, evidence = _inputs("math")
        bundle = draft_skill_candidate_bundle(
            eligibility,
            contract,
            payload,
            evidence,
            drafted_at=NOW,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "store"
            publish_record(json.dumps(bundle.payload), root=root)
            report = verify_record_graph(root)

        self.assertFalse(report.ok)
        self.assertEqual(report.records_total, 1)
        self.assertEqual(report.families, {"skill-candidate-bundle/v1": 1})
        self.assertEqual(
            {violation.kind for violation in report.violations},
            {"dangling_reference"},
        )

    def test_publication_rejects_restricted_candidate_before_store_write(
        self,
    ) -> None:
        eligibility, contract, payload, evidence = _inputs("math")
        bundle = draft_skill_candidate_bundle(
            eligibility,
            contract,
            payload,
            evidence,
            drafted_at=NOW,
        )
        changed = bundle.payload
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
