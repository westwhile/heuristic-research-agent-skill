"""Final-evaluation evidence checks for the ML adapter (ADR-0008 A6).

The case-side selection facts arrive through ``evaluation-contract/v3``;
the result-side final-evaluation facts arrive through ``ml-evidence/v2``.
This private module is the single semantic comparison point.  The runtime
registry is deliberately patchable so mutation tests exercise the public
``MLAdapter.validate_claim`` interface after removing a real predicate.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..types import AdapterError

_Predicate = Callable[[dict[str, Any], dict[str, Any]], bool]


def _selection_uses_protected_partition(
    contract: dict[str, Any], evidence: dict[str, Any]
) -> bool:
    del evidence
    return contract["selection_partition"] == "test"


def _final_evaluation_is_not_protected(
    contract: dict[str, Any], evidence: dict[str, Any]
) -> bool:
    del contract
    return evidence["final_evaluation"]["partition"] not in {
        "test",
        "future_holdout",
    }


def _final_evaluation_split_mismatch(
    contract: dict[str, Any], evidence: dict[str, Any]
) -> bool:
    return evidence["final_evaluation"]["split_sha256"] != contract["split_sha256"]


def _final_evaluation_case_mismatch(
    contract: dict[str, Any], evidence: dict[str, Any]
) -> bool:
    return evidence["case_sha256"] != contract["case_sha256"]


_SELECTION_CONTRACT_PREDICATES: tuple[tuple[str, _Predicate], ...] = (
    ("selection-uses-protected-partition", _selection_uses_protected_partition),
)

_FINAL_EVALUATION_PREDICATES: tuple[tuple[str, _Predicate], ...] = (
    ("final-evaluation-case-mismatch", _final_evaluation_case_mismatch),
    ("final-evaluation-not-protected", _final_evaluation_is_not_protected),
    ("final-evaluation-split-mismatch", _final_evaluation_split_mismatch),
)


def validate_selection_contract(contract: dict[str, Any]) -> None:
    """Fail closed on a hand-built v3 contract that selects on test."""

    violations = [
        rule_id
        for rule_id, predicate in _SELECTION_CONTRACT_PREDICATES
        if predicate(contract, {})
    ]
    if violations:
        raise AdapterError(
            "selection contract violated: " + ", ".join(violations)
        )


def validate_final_evaluation(
    contract: dict[str, Any], evidence: dict[str, Any]
) -> None:
    """Fail closed when selection and final-evaluation declarations conflict."""

    violations = [
        rule_id
        for rule_id, predicate in _FINAL_EVALUATION_PREDICATES
        if predicate(contract, evidence)
    ]
    if violations:
        raise AdapterError(
            "final-evaluation contract violated: " + ", ".join(violations)
        )


__all__: list[str] = []
