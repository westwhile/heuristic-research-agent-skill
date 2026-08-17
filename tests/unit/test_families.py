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
        # Phase 1D D3 + Phase 3 E2: all thirteen schema families are
        # registered and publishable — the seven research families, the two
        # export families (ADR-0004), and the four evaluation record
        # families (ADR-0006). A family whose schema lands before its
        # graph semantics (none today) must stay absent here until then.
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
                "comparison-report/v1",
            },
        )

    def test_identity_fields_are_unique_per_family(self) -> None:
        fields = [contract.identity_field for contract in FAMILIES.values()]
        self.assertEqual(len(fields), len(set(fields)))

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
            ("comparison-report/v1", "champion"),
            ("comparison-report/v1", "challenger"),
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
