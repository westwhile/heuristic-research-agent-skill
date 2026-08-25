"""Invariant tests for the family contract registry (``_families.py``).

The registry is the single metadata source shared by publish-time identity
and the graph checks (ADR-0003 decision 10). These tests pin its internal
consistency so a malformed entry fails here, at the table itself, instead
of surfacing as a misclassified graph violation.
"""

import unittest

from research_evolution.core._families import FAMILIES

_SHAPES = {"object", "array_of_objects", "array_of_scalars"}


class FamilyRegistryTest(unittest.TestCase):
    def test_membership_is_explicit(self) -> None:
        # Phase 1D D3 + Phase 3 E2 + Phase 4 M2 + Phase 7 P7A—P7B3 + CR4—CR6:
        # all thirty
        # schema families are registered and publishable — the seven research
        # families, the two export families (ADR-0004), the four evaluation
        # record families (ADR-0006), and the four research memory families
        # (ADR-0007: the case package successor v2 alongside the frozen v1,
        # research-pattern/v1, heuristic/v1, reuse-event/v1), plus the three
        # candidate-closure/context records from ADR-0010. A family whose
        # schema lands before its graph semantics (none today) must stay
        # absent here until then.
        self.assertEqual(
            set(FAMILIES),
            {
                "research-task/v1",
                "research-claim/v1",
                "research-evidence/v1",
                "research-run/v1",
                "research-failure-observation/v1",
                "research-failure-analysis/v1",
                "research-case-package/v1",
                "export-decision/v1",
                "export-receipt/v1",
                "evaluation-case/v1",
                "suite/v1",
                "evaluation-run/v1",
                "evaluation-attempt/v1",
                "evaluation-result/v1",
                "comparison-report/v1",
                "suite-comparison/v1",
                "research-case-package/v2",
                "research-pattern/v1",
                "heuristic/v1",
                "reuse-event/v1",
                "candidate-manifest/v1",
                "artifact-closure-receipt/v1",
                "candidate-eligibility-attestation/v1",
                "skill-candidate-bundle/v1",
                "skill-static-validation-receipt/v1",
                "context-bundle/v1",
                "context-bundle/v2",
                "context-material-assessment/v1",
                "artifact-record/v1",
                "evaluation-envelope-closure-receipt/v1",
            },
        )

    def test_identity_fields_are_unique_per_family(self) -> None:
        fields = [contract.identity_field for contract in FAMILIES.values()]
        duplicates = {field for field in fields if fields.count(field) > 1}
        # The sanctioned exceptions are versioned successors that share one
        # logical identity field with their frozen predecessor.
        self.assertEqual(duplicates, {"case_id", "context_bundle_id"})
        self.assertEqual(len(set(fields)), len(fields) - 2)

    def test_reference_targets_are_registered(self) -> None:
        for contract in FAMILIES.values():
            for ref in contract.references:
                self.assertIn(ref.target_family, FAMILIES)

    def test_reference_shapes_and_id_fields_are_consistent(self) -> None:
        for contract in FAMILIES.values():
            for ref in contract.references:
                self.assertIn(ref.shape, _SHAPES)
                if ref.shape == "array_of_scalars":
                    self.assertIsNone(ref.target_id_field)
                else:
                    self.assertIsNotNone(ref.target_id_field)

    def test_two_way_pairs_are_symmetric(self) -> None:
        pairs = [
            (family, ref)
            for family, contract in FAMILIES.items()
            for ref in contract.references
            if ref.two_way_with is not None
        ]
        # Only the claim/evidence pair links in both directions.
        self.assertEqual(len(pairs), 2)
        for family, ref in pairs:
            reverse = [
                candidate
                for candidate in FAMILIES[ref.target_family].references
                if candidate.field == ref.two_way_with
            ]
            self.assertEqual(len(reverse), 1)
            self.assertEqual(reverse[0].two_way_with, ref.field)
            self.assertEqual(reverse[0].target_family, family)

    def test_supersedes_scopes_are_valid(self) -> None:
        for contract in FAMILIES.values():
            if contract.supersedes is None:
                continue
            self.assertIn(contract.supersedes.scope, ("family", "anchor"))
            if contract.supersedes.scope == "anchor":
                reference_fields = [ref.field for ref in contract.references]
                self.assertIn(
                    contract.supersedes.anchor_field, reference_fields
                )
            else:
                self.assertIsNone(contract.supersedes.anchor_field)

    def test_hierarchical_references_require_pins(self) -> None:
        pinned = {
            ("research-run/v1", "task"),
            ("research-failure-observation/v1", "run"),
            ("research-failure-analysis/v1", "observation"),
            ("export-decision/v1", "case"),
            ("export-receipt/v1", "decision"),
            ("suite/v1", "cases"),
            ("evaluation-run/v1", "case"),
            ("evaluation-run/v1", "suite"),
            ("evaluation-attempt/v1", "case"),
            ("evaluation-attempt/v1", "suite"),
            ("evaluation-result/v1", "attempt"),
            ("comparison-report/v1", "champion"),
            ("comparison-report/v1", "challenger"),
            ("research-case-package/v2", "task"),
            ("research-case-package/v2", "runs"),
            ("research-case-package/v2", "claims"),
            ("research-case-package/v2", "evidence"),
            ("research-case-package/v2", "observations"),
            ("research-case-package/v2", "analyses"),
            ("research-case-package/v2", "derived_from"),
            ("research-pattern/v1", "source_cases"),
            ("heuristic/v1", "regression_cases"),
            ("reuse-event/v1", "run"),
            ("reuse-event/v1", "pattern"),
            ("candidate-manifest/v1", "source_cases"),
            ("candidate-manifest/v1", "source_patterns"),
            ("artifact-closure-receipt/v1", "candidate"),
            ("candidate-eligibility-attestation/v1", "candidate"),
            ("candidate-eligibility-attestation/v1", "closure_receipt"),
            ("candidate-eligibility-attestation/v1", "source_cases"),
            ("skill-candidate-bundle/v1", "candidate"),
            ("skill-candidate-bundle/v1", "closure_receipt"),
            ("skill-candidate-bundle/v1", "eligibility_attestation"),
            ("skill-candidate-bundle/v1", "source_cases"),
            ("context-bundle/v1", "candidate"),
            ("context-bundle/v2", "candidate"),
            ("context-bundle/v2", "assessments"),
            ("context-material-assessment/v1", "candidate"),
            ("evaluation-envelope-closure-receipt/v1", "candidate"),
            ("evaluation-envelope-closure-receipt/v1", "artifacts"),
        }
        for family, field in pinned:
            ref = next(
                candidate
                for candidate in FAMILIES[family].references
                if candidate.field == field
            )
            self.assertTrue(ref.pin_required)


if __name__ == "__main__":
    unittest.main()
