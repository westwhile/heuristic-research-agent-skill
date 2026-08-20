"""Unit tests for the ML declared-topology layer (ADR-0008 addendum A5).

Every assertion enters through the public
``MLAdapter.build_evaluation_contract`` operation; the private ``_topology``
module is imported ONLY so mutation tests can patch its runtime registries
(A5 section 6 discipline — no test calls a private helper directly for its
verdict).
"""

import hashlib
import unittest
from pathlib import Path
from unittest import mock

from research_evolution.adapters import AdapterError
from research_evolution.adapters import ml as ml_package
from research_evolution.adapters.ml import MLAdapter
from research_evolution.adapters.ml import _topology
from research_evolution.core import load_strict_json

FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "adapters"
    / "ml-case"
    / "v1"
    / "valid"
)


def _case(name: str) -> dict:
    return load_strict_json((FIXTURES / name).read_bytes())


def _violation_lines(error: AdapterError) -> tuple[list[str], str | None]:
    """Split an aggregated topology error into entry lines and the optional
    fixed ``N additional violations omitted`` trailer."""
    lines = str(error).splitlines()[1:]
    if lines and lines[-1].endswith("additional violations omitted"):
        return lines[:-1], lines[-1]
    return lines, None


SAFE_CASES = ("minimal.json", "full.json", "group-split.json", "nested-split.json")

# Every schema-legal unsafe fixture -> the frozen rule id that must reject
# it (A5 section 1). All but unsafe-sampling-scope.json isolate exactly one
# violation; the original sampling fixture carries both P3 branches.
LEAKAGE_POSITIVES = {
    "unsafe-fit-scope-full-data.json": "preprocessing-fit-full-data",
    "unsafe-feature-selection.json": "feature-selection-fit-full-data",
    "unsafe-sampling-scope-full-data.json": "sampling-scope-unsafe",
    "unsafe-sampling-scope-pre-split.json": "sampling-scope-unsafe",
    "unsafe-sampling-scope.json": "sampling-scope-unsafe",
    "unsafe-scope-upstream-mismatch.json": "scope-upstream-mismatch",
    "unsafe-scope-upstream-mismatch-preprocessing-per-fold.json": "scope-upstream-mismatch",
    "unsafe-scope-upstream-mismatch-sampling-train-only.json": "scope-upstream-mismatch",
    "unsafe-scope-upstream-mismatch-sampling-per-fold.json": "scope-upstream-mismatch",
    "unsafe-target-encoding.json": "target-encoding-not-per-fold",
    "unsafe-tuning-split-test.json": "tuning-uses-protected-split",
    "unsafe-tuning-split-future-holdout.json": "tuning-uses-protected-split",
    "unsafe-selection-split-test.json": "selection-uses-test",
}

SPLIT_PARAMETER_NEGATIVES = (
    "unsafe-split-group-key-missing.json",
    "unsafe-split-group-key-wrong-type.json",
    "unsafe-split-group-key-blank.json",
    "unsafe-split-time-series-gap-missing.json",
    "unsafe-split-time-series-gap-blank.json",
    "unsafe-split-time-series-embargo-wrong-type.json",
    "unsafe-split-nested-outer-folds-missing.json",
    "unsafe-split-nested-outer-folds-bool.json",
    "unsafe-split-nested-inner-folds-float.json",
    "unsafe-split-nested-inner-folds-below-floor.json",
)

ASSESSMENT_DECLARED_MISSING = tuple(
    f"unsafe-assessment-{dimension}-detail-missing.json"
    for dimension in ("calibration", "subgroup", "ood", "drift")
)
ASSESSMENT_NOT_PERFORMED_PRESENT = tuple(
    f"unsafe-assessment-{dimension}-detail-present.json"
    for dimension in ("calibration", "subgroup", "ood", "drift")
)

FLOOR_NEGATIVES = {
    **dict.fromkeys(SPLIT_PARAMETER_NEGATIVES, "split-parameters-kind-contract"),
    "unsafe-tuning-seed-count-zero.json": "tuning-seed-count-floor",
    **dict.fromkeys(
        ASSESSMENT_DECLARED_MISSING, "assessment-declared-detail-missing"
    ),
    **dict.fromkeys(
        ASSESSMENT_NOT_PERFORMED_PRESENT,
        "assessment-not-performed-detail-present",
    ),
}

# Drop-rule mapping (A5 section 5): each predicate, dropped alone, must let
# its positive fixture pass through the public entry.
DROP_RULE_CASES = (
    ("_preprocessing_fit_full_data", "unsafe-fit-scope-full-data.json"),
    ("_feature_selection_fit_full_data", "unsafe-feature-selection.json"),
    ("_sampling_scope_unsafe", "unsafe-sampling-scope-full-data.json"),
    ("_scope_upstream_mismatch", "unsafe-scope-upstream-mismatch.json"),
    ("_target_encoding_not_per_fold", "unsafe-target-encoding.json"),
    ("_tuning_uses_protected_split", "unsafe-tuning-split-test.json"),
    ("_selection_uses_test", "unsafe-selection-split-test.json"),
)


def _weaken(predicate, keep):
    """A weakened copy of a real predicate (A5 branch mutation): only
    violations accepted by *keep* survive."""

    def weakened(case):
        return [v for v in predicate(case) if keep(v)]

    return weakened


def _registry_replaced(registry, target, replacement):
    return tuple(
        replacement if entry is target else entry for entry in registry
    )


def _registry_without(registry, target):
    return tuple(entry for entry in registry if entry is not target)


class TopologySafeCaseTest(unittest.TestCase):
    def test_safe_fixtures_build_contracts(self) -> None:
        for name in SAFE_CASES:
            with self.subTest(fixture=name):
                contract = MLAdapter().build_evaluation_contract(_case(name))
                self.assertEqual(
                    contract.payload["schema"], "evaluation-contract/v2"
                )

    def test_iid_extra_parameters_are_not_interpreted(self) -> None:
        # iid declares no required keys; free-form extras ride along
        # uninterpreted (A5 section 3, A5c narrowing).
        payload = _case("minimal.json")
        payload["split"]["parameters"] = {"notes": "anything", "weird": [1, False]}
        MLAdapter().build_evaluation_contract(payload)


class LeakagePredicateTest(unittest.TestCase):
    def test_every_positive_is_rejected_by_its_rule(self) -> None:
        for name, rule in LEAKAGE_POSITIVES.items():
            with self.subTest(fixture=name):
                with self.assertRaises(AdapterError) as ctx:
                    MLAdapter().build_evaluation_contract(_case(name))
                entries, trailer = _violation_lines(ctx.exception)
                self.assertIsNone(trailer)
                expected = 2 if name == "unsafe-sampling-scope.json" else 1
                self.assertEqual(len(entries), expected, str(ctx.exception))
                for entry in entries:
                    self.assertTrue(
                        entry.startswith(f"{rule} at "),
                        f"{rule} missing in {entry!r}",
                    )

    def test_double_violation_original_keeps_both_branches(self) -> None:
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(
                _case("unsafe-sampling-scope.json")
            )
        message = str(ctx.exception)
        self.assertIn("sampling[0].scope", message)
        self.assertIn("sampling[1].scope", message)
        self.assertIn("'full_data'", message)
        self.assertIn("'pre_split'", message)


class SemanticFloorTest(unittest.TestCase):
    def test_every_negative_is_rejected_by_its_floor(self) -> None:
        for name, rule in FLOOR_NEGATIVES.items():
            with self.subTest(fixture=name):
                with self.assertRaises(AdapterError) as ctx:
                    MLAdapter().build_evaluation_contract(_case(name))
                entries, trailer = _violation_lines(ctx.exception)
                self.assertIsNone(trailer)
                self.assertEqual(len(entries), 1, str(ctx.exception))
                self.assertTrue(
                    entries[0].startswith(f"{rule} at "),
                    f"{rule} missing in {entries[0]!r}",
                )


class DagStructureTest(unittest.TestCase):
    """Structural errors are an independent pre-phase: they fail closed
    before any leakage predicate or semantic floor runs (A5 sections 2/6)."""

    def test_dangling_pin(self) -> None:
        payload = _case("minimal.json")
        payload["split"]["input_sha256"] = "0" * 64
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(payload)
        self.assertIn("dag-dangling-pin at split.input_sha256", str(ctx.exception))

    def test_self_reference(self) -> None:
        payload = _case("full.json")
        step = payload["preprocessing"][0]
        step["input_sha256"] = step["sha256"]
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(payload)
        self.assertIn(
            "dag-self-reference at preprocessing[0].input_sha256",
            str(ctx.exception),
        )

    def test_illegal_direction_split_to_step(self) -> None:
        payload = _case("full.json")
        payload["split"]["input_sha256"] = payload["preprocessing"][0]["sha256"]
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(payload)
        self.assertIn("dag-illegal-direction at split.input_sha256", str(ctx.exception))

    def test_illegal_direction_selection_to_dataset(self) -> None:
        payload = _case("minimal.json")
        payload["selection"]["input_sha256"] = payload["dataset"]["sha256"]
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(payload)
        self.assertIn(
            "dag-illegal-direction at selection.input_sha256", str(ctx.exception)
        )

    def test_ambiguous_pin_target(self) -> None:
        payload = _case("full.json")
        payload["sampling"][0]["sha256"] = payload["preprocessing"][0]["sha256"]
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(payload)
        self.assertIn("dag-ambiguous-pin-target", str(ctx.exception))

    def test_identity_conflict(self) -> None:
        payload = _case("full.json")
        payload["preprocessing"][0]["identity"] = payload["split"]["identity"]
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(payload)
        self.assertIn("dag-identity-conflict", str(ctx.exception))

    def test_reference_cycle(self) -> None:
        # Two steps pinning each other: direction-illegal AND cyclic; the
        # Kahn safety net must report the cycle explicitly.
        payload = _case("full.json")
        first, second = payload["preprocessing"]
        first["input_sha256"] = second["sha256"]
        second["input_sha256"] = first["sha256"]
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(payload)
        message = str(ctx.exception)
        self.assertIn("dag-reference-cycle", message)
        self.assertIn("dag-illegal-direction", message)
        cycle_entry = next(
            line
            for line in message.splitlines()
            if line.startswith("dag-reference-cycle")
        )
        self.assertEqual(
            cycle_entry,
            "dag-reference-cycle at preprocessing[0]: upstream pins form a "
            "reference cycle among 2 section(s); the declaration DAG must be "
            "acyclic",
        )

    def test_structure_errors_precede_leakage_predicates(self) -> None:
        # P1 violation present, but the DAG error wins the phase.
        payload = _case("unsafe-fit-scope-full-data.json")
        payload["split"]["input_sha256"] = "0" * 64
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(payload)
        message = str(ctx.exception)
        self.assertIn("dag-dangling-pin", message)
        self.assertNotIn("preprocessing-fit-full-data", message)


class DiagnosticCapTest(unittest.TestCase):
    """A5 section 6: at most 64 stable entries, linear scan, exact trailer."""

    @staticmethod
    def _many_steps_payload(unsafe_scope: bool) -> dict:
        payload = _case("minimal.json")
        split_sha = payload["split"]["sha256"]
        steps = []
        for index in range(70):
            identity = f"cap-prep-{index}"
            steps.append(
                {
                    "identity": identity,
                    "sha256": hashlib.sha256(identity.encode()).hexdigest(),
                    "input_sha256": (
                        hashlib.sha256(f"cap-missing-{index}".encode()).hexdigest()
                        if not unsafe_scope
                        else split_sha
                    ),
                    "operation": "standard-scaler",
                    "fit_scope": "full_data",
                }
            )
        payload["preprocessing"] = steps
        return payload

    @staticmethod
    def _large_shared_preprocessing_payload(shared_field: str) -> dict:
        """Build a schema-legal 5,000-step public-entry stress case."""
        payload = _case("minimal.json")
        split_sha = payload["split"]["sha256"]
        steps = []
        for index in range(5_000):
            identity = (
                "shared-identity"
                if shared_field == "identity"
                else f"bounded-{index}"
            )
            sha256 = (
                "a" * 64
                if shared_field == "sha256"
                else hashlib.sha256(f"bounded-{index}".encode()).hexdigest()
            )
            steps.append(
                {
                    "identity": identity,
                    "sha256": sha256,
                    "input_sha256": split_sha,
                    "operation": "standard-scaler",
                    "fit_scope": "train_only",
                }
            )
        payload["preprocessing"] = steps
        return payload

    def test_leakage_phase_cap(self) -> None:
        payload = self._many_steps_payload(unsafe_scope=True)
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(payload)
        entries, trailer = _violation_lines(ctx.exception)
        self.assertEqual(len(entries), 64)
        self.assertEqual(trailer, "6 additional violations omitted")

    def test_dag_phase_cap(self) -> None:
        payload = self._many_steps_payload(unsafe_scope=False)
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(payload)
        entries, trailer = _violation_lines(ctx.exception)
        self.assertEqual(len(entries), 64)
        self.assertEqual(trailer, "6 additional violations omitted")
        for entry in entries:
            self.assertTrue(entry.startswith("dag-dangling-pin at "), entry)

    def test_single_ambiguous_sha_diagnostic_is_bounded(self) -> None:
        payload = self._large_shared_preprocessing_payload("sha256")
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(payload)
        message = str(ctx.exception)
        self.assertIn(
            "dag-ambiguous-pin-target at preprocessing[0]: "
            "5000 sections share one sha256",
            message,
        )
        self.assertLess(len(message), 512)
        self.assertNotIn("preprocessing[4999]", message)

    def test_single_identity_conflict_diagnostic_is_bounded(self) -> None:
        payload = self._large_shared_preprocessing_payload("identity")
        with self.assertRaises(AdapterError) as ctx:
            MLAdapter().build_evaluation_contract(payload)
        message = str(ctx.exception)
        self.assertIn(
            "dag-identity-conflict at preprocessing[0]: "
            "one identity is pinned by 5000 sections with differing sha256",
            message,
        )
        self.assertLess(len(message), 512)
        self.assertNotIn("preprocessing[4999]", message)


class RegistryPinTest(unittest.TestCase):
    def test_registry_counts(self) -> None:
        self.assertEqual(len(_topology._LEAKAGE_PREDICATES), 7)
        self.assertEqual(len(_topology._SEMANTIC_FLOORS), 3)

    def test_no_new_public_surface(self) -> None:
        self.assertEqual(ml_package.__all__, ["MLAdapter"])


class DropRuleMutationTest(unittest.TestCase):
    """A5 section 5: deleting one real registry entry must let its positive
    false-PASS through the public build_evaluation_contract entry."""

    def test_drop_each_leakage_predicate(self) -> None:
        for function_name, fixture in DROP_RULE_CASES:
            target = next(
                entry
                for entry in _topology._LEAKAGE_PREDICATES
                if entry.__name__ == function_name
            )
            reduced = _registry_without(_topology._LEAKAGE_PREDICATES, target)
            with self.subTest(predicate=function_name, fixture=fixture):
                with mock.patch.object(
                    _topology, "_LEAKAGE_PREDICATES", reduced
                ):
                    MLAdapter().build_evaluation_contract(_case(fixture))

    def test_drop_each_semantic_floor(self) -> None:
        floor_fixtures = {
            "_split_parameters_kind_contract": SPLIT_PARAMETER_NEGATIVES,
            "_tuning_seed_count_floor": ("unsafe-tuning-seed-count-zero.json",),
            "_assessment_detail_bidirectional": (
                ASSESSMENT_DECLARED_MISSING + ASSESSMENT_NOT_PERFORMED_PRESENT
            ),
        }
        for function_name, fixtures in floor_fixtures.items():
            target = next(
                entry
                for entry in _topology._SEMANTIC_FLOORS
                if entry.__name__ == function_name
            )
            reduced = _registry_without(_topology._SEMANTIC_FLOORS, target)
            for fixture in fixtures:
                with self.subTest(floor=function_name, fixture=fixture):
                    with mock.patch.object(
                        _topology, "_SEMANTIC_FLOORS", reduced
                    ):
                        MLAdapter().build_evaluation_contract(_case(fixture))


class BranchWeakeningMutationTest(unittest.TestCase):
    """A5 section 5: enum branches and P4 combinations are mutated with a
    WEAKENED copy of the real predicate, still via the public entry — a
    whole-predicate drop cannot prove a single branch load-bearing."""

    def _patched_leakage(self, function_name, keep):
        target = next(
            entry
            for entry in _topology._LEAKAGE_PREDICATES
            if entry.__name__ == function_name
        )
        return mock.patch.object(
            _topology,
            "_LEAKAGE_PREDICATES",
            _registry_replaced(
                _topology._LEAKAGE_PREDICATES,
                target,
                _weaken(target, keep),
            ),
        )

    def _patched_floor(self, function_name, keep):
        target = next(
            entry
            for entry in _topology._SEMANTIC_FLOORS
            if entry.__name__ == function_name
        )
        return mock.patch.object(
            _topology,
            "_SEMANTIC_FLOORS",
            _registry_replaced(
                _topology._SEMANTIC_FLOORS, target, _weaken(target, keep)
            ),
        )

    def test_p3_branches(self) -> None:
        # Weakened to full_data-only, the pre_split positive passes.
        with self._patched_leakage(
            "_sampling_scope_unsafe", lambda v: v.value == "full_data"
        ):
            MLAdapter().build_evaluation_contract(
                _case("unsafe-sampling-scope-pre-split.json")
            )
        # Weakened to pre_split-only, the full_data positive passes.
        with self._patched_leakage(
            "_sampling_scope_unsafe", lambda v: v.value == "pre_split"
        ):
            MLAdapter().build_evaluation_contract(
                _case("unsafe-sampling-scope-full-data.json")
            )

    def test_p6_branches(self) -> None:
        with self._patched_leakage(
            "_tuning_uses_protected_split", lambda v: v.value == "test"
        ):
            MLAdapter().build_evaluation_contract(
                _case("unsafe-tuning-split-future-holdout.json")
            )
        with self._patched_leakage(
            "_tuning_uses_protected_split", lambda v: v.value == "future_holdout"
        ):
            MLAdapter().build_evaluation_contract(
                _case("unsafe-tuning-split-test.json")
            )

    def test_p4_combinations(self) -> None:
        # Weakened to preprocessing+train_only only (the originally covered
        # combination), the three derived combinations pass.
        keep = lambda v: v.value == "preprocessing:train_only"  # noqa: E731
        with self._patched_leakage("_scope_upstream_mismatch", keep):
            for fixture in (
                "unsafe-scope-upstream-mismatch-preprocessing-per-fold.json",
                "unsafe-scope-upstream-mismatch-sampling-train-only.json",
                "unsafe-scope-upstream-mismatch-sampling-per-fold.json",
            ):
                with self.subTest(fixture=fixture):
                    MLAdapter().build_evaluation_contract(_case(fixture))

    def test_assessment_floor_declared_direction_only(self) -> None:
        keep = lambda v: v.rule_id == "assessment-declared-detail-missing"  # noqa: E731
        with self._patched_floor("_assessment_detail_bidirectional", keep):
            for fixture in ASSESSMENT_NOT_PERFORMED_PRESENT:
                with self.subTest(fixture=fixture):
                    MLAdapter().build_evaluation_contract(_case(fixture))

    def test_assessment_floor_not_performed_direction_only(self) -> None:
        keep = lambda v: v.rule_id == "assessment-not-performed-detail-present"  # noqa: E731
        with self._patched_floor("_assessment_detail_bidirectional", keep):
            for fixture in ASSESSMENT_DECLARED_MISSING:
                with self.subTest(fixture=fixture):
                    MLAdapter().build_evaluation_contract(_case(fixture))

    def test_split_parameter_floor_group_only(self) -> None:
        # Weakened to the group branch, the time_series and nested
        # negatives pass.
        keep = lambda v: v.path == "split.parameters.group_key"  # noqa: E731
        with self._patched_floor("_split_parameters_kind_contract", keep):
            for fixture in SPLIT_PARAMETER_NEGATIVES:
                if "group-key" in fixture:
                    continue
                with self.subTest(fixture=fixture):
                    MLAdapter().build_evaluation_contract(_case(fixture))


if __name__ == "__main__":
    unittest.main()
