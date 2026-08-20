"""Declared-topology validation for the ML adapter (ADR-0008 addendum A5).

Private to the ml adapter package. The single integration point is
``MLAdapter.build_evaluation_contract``: immediately after the ml-case
schema load and before any contract construction, the declared experiment
topology is judged here. The DAG structural checks are an independent
pre-phase (never part of the mutation registries) and run BEFORE the two
rule registries — leakage derivation on a structurally unsound DAG is
meaningless, so structural errors fail closed first.

Two module-level registries carry the semantic rules, both read from
module globals at call time so mutation tests can patch the real registry
and still exercise the public ``build_evaluation_contract`` entry (A5
section 6 discipline — the registries are never captured as default
parameters, which would make patching inert):

- ``_LEAKAGE_PREDICATES``: the seven leakage predicates of the six rule
  families (A5 section 1);
- ``_SEMANTIC_FLOORS``: the three non-leakage floors — the split-parameter
  kind contract, the tuning seed floor, and the bidirectional assessment
  detail discipline (A5 section 3).

Diagnostics (A5 section 6): fixed rule ids plus trusted JSON paths
generated from the schema structure (``preprocessing[0].fit_scope``).
Caller-supplied strings (section identities, free-form parameter values)
are never echoed into error text — this module deliberately does NOT
import ``adapter._preview`` (that import would be circular), so topology
diagnostics render rule ids, paths, schema-enum tokens, and counts only.
At most ``_MAX_DIAGNOSTICS`` stable entries are rendered; scanning stays
linear, the total is counted, and a fixed
``N additional violations omitted`` trailer carries nothing but the count.
"""

from __future__ import annotations

import collections
from typing import Any, NamedTuple

from ..types import AdapterError

# Hard cap on rendered diagnostic entries (A5 section 6): the
# preprocessing/sampling arrays carry no schema maxItems, so the violation
# set itself can be unbounded.
_MAX_DIAGNOSTICS = 64


class _Violation(NamedTuple):
    """One judged violation.

    ``value`` carries the matched schema-ENUM token (or a fixed
    section-kind/label pair) so branch-weakening mutation tests filter
    structured data instead of parsing message text. It is never free-form
    caller text.
    """

    rule_id: str
    path: str
    detail: str
    value: str | None = None


def _raise_if_violations(violations: list[_Violation], contract: str) -> None:
    """Raise one aggregated AdapterError for *violations*, bounded.

    Entries render in caller-provided (registry/phase) order; at most
    ``_MAX_DIAGNOSTICS`` are shown, the scan has already counted the rest,
    and the fixed trailer names only the omitted count (A5 section 6).
    """
    if not violations:
        return
    lines = [
        f"{violation.rule_id} at {violation.path}: {violation.detail}"
        for violation in violations[:_MAX_DIAGNOSTICS]
    ]
    omitted = len(violations) - _MAX_DIAGNOSTICS
    if omitted > 0:
        lines.append(f"{omitted} additional violations omitted")
    raise AdapterError(
        f"declared ml-case topology violates the {contract} "
        f"({len(violations)} violation(s)):\n" + "\n".join(lines)
    )


# ---------------------------------------------------------------------------
# DAG structural pre-phase (A5 section 2). Nodes are exactly the ml-case
# sections carrying real pins: dataset (root, no upstream pin), split,
# preprocessing[*], sampling[*], selection. feature/tuning/assessment are
# declaration sections, not DAG nodes.
# ---------------------------------------------------------------------------

_PREPROCESSING = "preprocessing"
_SAMPLING = "sampling"

# Legal upstream target kinds per node kind. Inter-step pins (pre->pre,
# sampling->sampling, pre<->sampling) are not admitted by the current
# contract; every in-repo legal fixture pins directly at the split.
_ALLOWED_UPSTREAM = {
    "split": frozenset({"dataset"}),
    _PREPROCESSING: frozenset({"dataset", "split"}),
    _SAMPLING: frozenset({"dataset", "split"}),
    "selection": frozenset({"split", _PREPROCESSING, _SAMPLING}),
}


class _DagNode(NamedTuple):
    path: str  # trusted, generated from the schema structure
    kind: str
    identity: str  # caller-supplied: compared, never echoed
    sha256: str
    input_sha256: str | None


def _dag_nodes(case: dict[str, Any]) -> list[_DagNode]:
    """Collect the DAG nodes in schema declaration order (deterministic)."""
    dataset = case["dataset"]
    split = case["split"]
    selection = case["selection"]
    nodes = [
        _DagNode(
            "dataset", "dataset", dataset["identity"], dataset["sha256"], None
        ),
        _DagNode(
            "split",
            "split",
            split["identity"],
            split["sha256"],
            split["input_sha256"],
        ),
    ]
    for kind in (_PREPROCESSING, _SAMPLING):
        for index, step in enumerate(case[kind]):
            nodes.append(
                _DagNode(
                    f"{kind}[{index}]",
                    kind,
                    step["identity"],
                    step["sha256"],
                    step["input_sha256"],
                )
            )
    nodes.append(
        _DagNode(
            "selection",
            "selection",
            selection["identity"],
            selection["sha256"],
            selection["input_sha256"],
        )
    )
    return nodes


def _dag_violations(case: dict[str, Any]) -> list[_Violation]:
    """All structural violations, in a stable phase-internal order:

    identity conflicts, ambiguous pin targets, then per-node pin checks
    (dangling / self-reference / illegal direction) in declaration order,
    then reference cycles. Caller identities are compared but never
    echoed; diagnostics carry rule ids, trusted paths, and counts only.
    """
    nodes = _dag_nodes(case)
    violations: list[_Violation] = []

    # One identity must pin one sha256 (and vice versa) within the case.
    by_identity: dict[str, dict[str, list[str]]] = {}
    for node in nodes:
        by_identity.setdefault(node.identity, {}).setdefault(
            node.sha256, []
        ).append(node.path)
    for by_sha in by_identity.values():
        if len(by_sha) > 1:
            first_path = next(group[0] for group in by_sha.values())
            section_count = sum(len(group) for group in by_sha.values())
            violations.append(
                _Violation(
                    "dag-identity-conflict",
                    first_path,
                    f"one identity is pinned by {section_count} sections with "
                    "differing sha256; within one case "
                    "the same identity must always carry the same hash",
                )
            )

    by_sha: dict[str, list[_DagNode]] = {}
    for node in nodes:
        by_sha.setdefault(node.sha256, []).append(node)
    for group in by_sha.values():
        if len(group) > 1:
            violations.append(
                _Violation(
                    "dag-ambiguous-pin-target",
                    group[0].path,
                    f"{len(group)} sections share one sha256, so an upstream "
                    "pin cannot resolve uniquely",
                )
            )

    # Pin resolution. The first matching section in declaration order is
    # the deterministic resolution; any ambiguity was reported above.
    resolved: dict[str, _DagNode] = {}
    for node in nodes:
        pin = node.input_sha256
        if pin is None:
            continue  # dataset root carries no upstream pin
        pin_path = f"{node.path}.input_sha256"
        if pin == node.sha256:
            violations.append(
                _Violation(
                    "dag-self-reference",
                    pin_path,
                    "a section must not pin itself as its own upstream",
                )
            )
            continue
        group = by_sha.get(pin)
        if not group:
            violations.append(
                _Violation(
                    "dag-dangling-pin",
                    pin_path,
                    "the upstream pin matches no declaration section in "
                    "this case",
                )
            )
            continue
        target = group[0]
        resolved[node.path] = target
        allowed = _ALLOWED_UPSTREAM[node.kind]
        if target.kind not in allowed:
            violations.append(
                _Violation(
                    "dag-illegal-direction",
                    pin_path,
                    f"a {node.kind} section may pin only "
                    f"{sorted(allowed)} as upstream; this pin resolves to "
                    f"{target.path} ({target.kind})",
                )
            )

    # Reference cycles: Kahn elimination over every resolved edge
    # (self-loops excluded — already reported above). Iterative, O(V+E),
    # no recursion, no ancestor rescanning. With the direction rules
    # enforced this can only fire when edges were direction-illegal (for
    # example two steps pinning each other); it is kept as the fail-closed
    # safety net the A5 DAG contract requires.
    edges = {
        path: target.path
        for path, target in resolved.items()
        if target.path != path
    }
    indegree = {node.path: 0 for node in nodes}
    for target_path in edges.values():
        indegree[target_path] += 1
    queue = collections.deque(
        node.path for node in nodes if indegree[node.path] == 0
    )
    remaining = set(indegree)
    while queue:
        current = queue.popleft()
        if current not in remaining:
            continue
        remaining.discard(current)
        target_path = edges.get(current)
        if target_path is not None and target_path in remaining:
            indegree[target_path] -= 1
            if indegree[target_path] == 0:
                queue.append(target_path)
    if remaining:
        first_cycle_path = next(
            node.path for node in nodes if node.path in remaining
        )
        violations.append(
            _Violation(
                "dag-reference-cycle",
                first_cycle_path,
                f"upstream pins form a reference cycle among "
                f"{len(remaining)} section(s); "
                "the declaration DAG must be acyclic",
            )
        )
    return violations


# ---------------------------------------------------------------------------
# Leakage predicates (A5 section 1): six rule families, seven predicates.
# Each entry is a module-level function carrying its frozen rule id; the
# registry tuple below is read at call time by validate_declared_topology.
# ---------------------------------------------------------------------------

# Scope labels that declare fold-safe behaviour; a safe label pinned at the
# pre-split dataset is the scope/upstream mismatch (predicate P4).
_SAFE_SCOPE_LABELS = frozenset({"train_only", "per_fold"})


def _preprocessing_fit_full_data(case: dict[str, Any]) -> list[_Violation]:
    """P1: a preprocessing step fit on full_data is leakage."""
    return [
        _Violation(
            "preprocessing-fit-full-data",
            f"preprocessing[{index}].fit_scope",
            "preprocessing fit on full_data (before the split) is leakage",
            "full_data",
        )
        for index, step in enumerate(case["preprocessing"])
        if step["fit_scope"] == "full_data"
    ]


def _feature_selection_fit_full_data(case: dict[str, Any]) -> list[_Violation]:
    """P2: feature selection fit on full_data is leakage."""
    if case["feature"]["selection_scope"] != "full_data":
        return []
    return [
        _Violation(
            "feature-selection-fit-full-data",
            "feature.selection_scope",
            "feature selection fit on full_data is leakage",
            "full_data",
        )
    ]


def _sampling_scope_unsafe(case: dict[str, Any]) -> list[_Violation]:
    """P3: resampling scoped full_data or pre_split is leakage."""
    violations = []
    for index, step in enumerate(case["sampling"]):
        scope = step["scope"]
        if scope in ("full_data", "pre_split"):
            violations.append(
                _Violation(
                    "sampling-scope-unsafe",
                    f"sampling[{index}].scope",
                    f"resampling declared with scope {scope!r} applies "
                    "outside the training folds (task 3 sampling clause)",
                    scope,
                )
            )
    return violations


def _scope_upstream_mismatch(case: dict[str, Any]) -> list[_Violation]:
    """P4: a train_only/per_fold step whose upstream pin resolves to the
    pre-split dataset contradicts its own safe label.

    Runs only after the DAG pre-phase passed, so every pin resolves and
    the dataset is the sole pre-split node a preprocessing/sampling step
    may legally name besides the split.
    """
    dataset_sha = case["dataset"]["sha256"]
    violations = []
    for kind in (_PREPROCESSING, _SAMPLING):
        label_field = "fit_scope" if kind == _PREPROCESSING else "scope"
        for index, step in enumerate(case[kind]):
            label = step[label_field]
            if label in _SAFE_SCOPE_LABELS and step["input_sha256"] == dataset_sha:
                violations.append(
                    _Violation(
                        "scope-upstream-mismatch",
                        f"{kind}[{index}].input_sha256",
                        f"the step declares the safe label {label!r} but "
                        "pins the pre-split dataset as its upstream; a "
                        f"{label!r} step must pin the split output",
                        f"{kind}:{label}",
                    )
                )
    return violations


def _target_encoding_not_per_fold(case: dict[str, Any]) -> list[_Violation]:
    """P5: target encoding applied outside the folds is leakage."""
    scope = case["feature"]["target_encoding_scope"]
    if scope in ("per_fold", "none"):
        return []
    return [
        _Violation(
            "target-encoding-not-per-fold",
            "feature.target_encoding_scope",
            f"target encoding declared {scope!r}; only per_fold, or an "
            "explicit none when not applied, is accepted",
            scope,
        )
    ]


def _tuning_uses_protected_split(case: dict[str, Any]) -> list[_Violation]:
    """P6: tuning never draws comparisons from test/future_holdout."""
    used = case["tuning"]["split_used"]
    if used not in ("test", "future_holdout"):
        return []
    return [
        _Violation(
            "tuning-uses-protected-split",
            "tuning.split_used",
            f"tuning draws comparisons from the protected partition "
            f"{used!r}; test and future_holdout never participate in tuning",
            used,
        )
    ]


def _selection_uses_test(case: dict[str, Any]) -> list[_Violation]:
    """P7: the test partition never selects the final model."""
    if case["selection"]["split_used"] != "test":
        return []
    return [
        _Violation(
            "selection-uses-test",
            "selection.split_used",
            "final-model selection drew on the test partition; the test "
            "set never selects the final model (task 8)",
            "test",
        )
    ]


# ---------------------------------------------------------------------------
# Semantic floors (A5 section 3): schema-free-form surfaces whose
# kind-appropriate content is a semantic-layer obligation
# (declared-is-the-floor). Free-form parameter VALUES are never echoed.
# ---------------------------------------------------------------------------


def _has_nonblank(value: Any) -> bool:
    """A string carrying at least one non-whitespace character."""
    return isinstance(value, str) and bool(value.strip())


def _is_json_integer(value: Any) -> bool:
    """A JSON integer. bool is an int subclass in Python and is excluded
    deliberately — ``true`` is not an integer fold count."""
    return isinstance(value, int) and not isinstance(value, bool)


def _split_parameters_kind_contract(case: dict[str, Any]) -> list[_Violation]:
    """Split kind -> parameter contract (types judged first, since the
    schema leaves parameters free-form):

    - iid: no required keys; extra parameters are allowed and not
      interpreted at this layer;
    - group: ``group_key`` — a string with a non-whitespace character;
    - time_series: ``gap`` and ``embargo`` — strings with a non-whitespace
      character (kept in the "5 sessions" form, never parsed numerically);
    - nested: ``outer_folds`` and ``inner_folds`` — non-bool JSON integers,
      each >= 2.
    """
    rule = "split-parameters-kind-contract"
    split = case["split"]
    kind = split["kind"]
    parameters = split["parameters"]
    violations = []
    if kind in ("group", "time_series"):
        keys = ("group_key",) if kind == "group" else ("gap", "embargo")
        for key in keys:
            if not _has_nonblank(parameters.get(key)):
                violations.append(
                    _Violation(
                        rule,
                        f"split.parameters.{key}",
                        f"a {kind} split requires {key!r} to be a string "
                        "with a non-whitespace character; missing keys, "
                        "non-string JSON values, and blank strings all "
                        "fail closed",
                    )
                )
    elif kind == "nested":
        for key in ("outer_folds", "inner_folds"):
            value = parameters.get(key)
            if not (_is_json_integer(value) and value >= 2):
                violations.append(
                    _Violation(
                        rule,
                        f"split.parameters.{key}",
                        f"a nested split requires {key!r} to be a JSON "
                        "integer (not bool) >= 2; missing keys, other JSON "
                        "types, and out-of-range integers all fail closed",
                    )
                )
    # iid: nothing required.
    return violations


def _tuning_seed_count_floor(case: dict[str, Any]) -> list[_Violation]:
    """tuning.seed_count >= 1 (the schema engine has no numeric-floor
    keyword; the floor is a semantic-layer obligation)."""
    count = case["tuning"]["seed_count"]
    if _is_json_integer(count) and count >= 1:
        return []
    return [
        _Violation(
            "tuning-seed-count-floor",
            "tuning.seed_count",
            "seed_count must be a JSON integer >= 1 (semantic floor; the "
            "schema layer pins only the integer type)",
        )
    ]


# The detail field carrying each assessment dimension's method/key. This
# mapping is duplicated from adapter.py deliberately: importing it from
# .adapter would be circular (adapter imports this module), and the two
# uses are pinned against each other by the shared fixtures.
_DETAIL_FIELD = {
    "calibration": "method",
    "subgroup": "group_key",
    "ood": "probe",
    "drift": "method",
}


def _assessment_detail_bidirectional(case: dict[str, Any]) -> list[_Violation]:
    """Assessment detail discipline, both directions fail closed:

    - status == declared requires the dimension's detail field present as
      a non-whitespace string;
    - status == not_performed FORBIDS carrying the detail field (a
      "not performed but method declared" payload is doubly ambiguous).
    """
    violations = []
    for dimension in ("calibration", "subgroup", "ood", "drift"):
        section = case["assessment"][dimension]
        field = _DETAIL_FIELD[dimension]
        path = f"assessment.{dimension}.{field}"
        if section["status"] == "declared":
            if not _has_nonblank(section.get(field)):
                violations.append(
                    _Violation(
                        "assessment-declared-detail-missing",
                        path,
                        f"status 'declared' requires {field!r} present as "
                        "a string with a non-whitespace character",
                    )
                )
        elif field in section:
            violations.append(
                _Violation(
                    "assessment-not-performed-detail-present",
                    path,
                    f"status 'not_performed' forbids carrying {field!r}; "
                    "a dimension that was not performed must not declare "
                    "a method",
                )
            )
    return violations


# Runtime registries (A5 section 6): tuples of module-level functions,
# read from module globals at call time by validate_declared_topology.
# Mutation tests patch these attributes with reduced/weakened tuples and
# still enter through the public build_evaluation_contract operation.
_LEAKAGE_PREDICATES = (
    _preprocessing_fit_full_data,
    _feature_selection_fit_full_data,
    _sampling_scope_unsafe,
    _scope_upstream_mismatch,
    _target_encoding_not_per_fold,
    _tuning_uses_protected_split,
    _selection_uses_test,
)

_SEMANTIC_FLOORS = (
    _split_parameters_kind_contract,
    _tuning_seed_count_floor,
    _assessment_detail_bidirectional,
)


def validate_declared_topology(case: dict[str, Any]) -> None:
    """Judge the declared experiment topology of an ml-case payload.

    Single private entry point, invoked by
    ``MLAdapter.build_evaluation_contract`` after the schema load and
    before any contract construction:

    1. DAG structural pre-phase (independent of the registries) — a
       structurally unsound DAG fails closed here and the rule registries
       never run on it;
    2. the leakage predicate registry, then the semantic floor registry —
       both read from module globals at THIS call, violations aggregated
       in registry order and raised once, bounded by _MAX_DIAGNOSTICS.
    """
    _raise_if_violations(_dag_violations(case), "DAG structure contract")
    violations: list[_Violation] = []
    for predicate in _LEAKAGE_PREDICATES:
        violations.extend(predicate(case))
    for floor in _SEMANTIC_FLOORS:
        violations.extend(floor(case))
    _raise_if_violations(violations, "semantic leakage/floor contract")
