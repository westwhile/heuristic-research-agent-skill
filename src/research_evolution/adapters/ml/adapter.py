"""Machine-learning domain adapter (ADR-0008; ARCHITECTURE §5.3).

Frozen mapping table:

- claim_class declares the evidentiary tier a claim asserts: engineering,
  data_acceptance, generalization (the out-of-sample tier, mapped to
  empirical_claim only — this adapter never produces predictive_claim,
  ADR-0008 addendum A2);
- the maturity ceiling is driven by experiment_run evidence alone:
  provenance (synthetic can never support a generalization claim past
  data_accepted), seed multiplicity (counted by UNIQUE seed — a single-seed
  best value cannot support a stable claim; caps at engineering_verified),
  and frozen-holdout discipline (required for empirically_supported). The
  four assessment kinds feed the gap-naming rules and never lift the
  ceiling by themselves. The three constraints are INDEPENDENT predicates
  over the public/real experiment record — each is evaluated and recorded
  even when no eligible experiment exists (a missing repeated-seed record
  still caps at engineering_verified), and the strictest one wins;
  concurrent violations are never hidden behind an if/elif chain or a
  provenance else-branch;
- binding is fail-closed at the study/case/final-evaluation seams (ADR-0008
  addenda A2/A3/A6/A7): every
  evidence item's study_id must equal the claim's; the claim's case_sha256
  must equal the contract's; and the claim's study_id must equal the
  contract's. Generalization experiment evidence must also pin that exact
  contract case. The ML adapter requires an evaluation-contract/v3 payload —
  older versions carry no case-derived selection/split binding surface;
- the case's assessment_declaration (carried by the v3 contract) is the
  evidentiary floor: it must name each of the four dimensions
  (calibration, subgroup, ood, drift) exactly once — an empty, partial,
  duplicated, or unknown-dimension declaration fails closed. This floor is
  adapter-enforced because the v2 schema keeps `dimension` a free string
  to stay domain-neutral. The declaration is then compared against the
  supplied evidence: a dimension declared not_performed contradicts
  present assessment evidence (AdapterError); a dimension declared but
  unfulfilled is a gap;
- terminal dispositions need RELEVANT evidence in both directions
  (addendum A3): engineering claims are carried by
  unit_test_run/experiment_run, data-acceptance claims by
  data_audit_report, generalization claims by experiment_run; "other" and
  the assessment kinds never produce supported/refuted
  (no-relevant-evidence);
- missing OOD/subgroup evaluations are NAMED (reasons/triggered_rules)
  without lowering the ceiling; calibration/drift gaps are honestly marked
  "not assessed" the same way. Detected gaps must be acknowledged in the
  claim's declared_assessment_gaps (per-dimension, machine-checked), and a
  generalization claim declaring an empty limitations array while gaps are
  named fails closed (acceptance gate);
- the contract must carry exactly one applicable bar for the suggested
  claim type: zero matches (claim not covered) and duplicate matches both
  fail closed; foreign claim types are skipped;
- externally_validated and production_observed are NEVER granted by this
  adapter: they require real deployment evidence outside Phase 5 scope;
- evaluation contracts derive their promotion bars from the case's gates;
  the forbidden channels and M-checkpoints are fixed by this adapter, not
  by the case author.

The declared experiment topology carried by ml-case/v1 (DAG of
{identity, sha256} declaration sections with upstream input pins) is the
surface the deterministic leakage rules judge. Those semantic checks are
enforced by build_evaluation_contract itself (ADR-0008 addendum A5): right
after the ml-case schema load and before any contract construction, the
private _topology module runs its DAG structural pre-phase, then the
seven leakage predicates and three semantic floors from its two runtime
registries. The other two seam operations never consume case topology.
"""

from __future__ import annotations

from typing import Any, Sequence

from research_evolution.core import canonical_sha256

from . import _evidence, _topology
from ..base import DomainAdapter
from ..types import (
    AdapterError,
    ClaimAssessment,
    DomainTask,
    EvaluationContract,
    _load_seam_record,
    _load_seam_record_one_of,
)

# Evidence kind that carries experimental results: the seed/provenance/
# frozen-holdout ceiling drivers read only experiment_run items. The four
# assessment kinds feed the gap-naming rules below and never lift a
# generalization claim by themselves (ADR-0008 addendum A2);
# unit_test_run, data_audit_report, and other are supporting evidence only.
_EXPERIMENT_KINDS = frozenset({"experiment_run"})

# Provenances that can carry a generalization claim (ADR-0008 decision 4:
# empirically_supported requires real or public data). Synthetic evidence
# proves pipeline behavior only.
_REAL_OR_PUBLIC = frozenset({"public", "real"})

# Claim class to the evidence kinds RELEVANT to its asserted outcome
# (ADR-0008 addenda A2/A3): supported and refuted suggestions both require
# relevant evidence; "other" and the four assessment kinds never carry a
# terminal disposition for any claim class.
_RELEVANT_KINDS = {
    "engineering": frozenset({"unit_test_run", "experiment_run"}),
    "data_acceptance": frozenset({"data_audit_report"}),
    "generalization": frozenset({"experiment_run"}),
}

# Case assessment section -> the detail field that carries its method/key
# (ADR-0008 decision 4).
_ASSESSMENT_DETAIL_FIELD = {
    "calibration": "method",
    "subgroup": "group_key",
    "ood": "probe",
    "drift": "method",
}

# Assessment dimension -> the evidence kind that fulfills it.
_ASSESSMENT_KIND = {
    "calibration": "calibration_assessment",
    "subgroup": "subgroup_assessment",
    "ood": "ood_assessment",
    "drift": "drift_assessment",
}

# Gap rule id per dimension. The rules name the gap; the ceiling never
# moves and no conclusion is fabricated (acceptance gate).
_ASSESSMENT_GAP_RULE = {
    "ood": "ood-assessment-missing",
    "subgroup": "subgroup-assessment-missing",
    "calibration": "calibration-not-assessed",
    "drift": "drift-not-assessed",
}

# Forbidden evidence channels for every ML contract (ADR-0008 decisions
# 3/4; the governance gates of the plan's Phase 5 acceptance list).
_FORBIDDEN_CHANNELS = (
    "synthetic-as-real-data-evidence",
    "pre-split-data-preparation",
    "test-set-for-model-selection",
    "holdout-for-tuning",
    "single-seed-best-as-stable-claim",
)

# Governance M-gates as case checkpoints.
_CHECKPOINTS = (
    "M0: dataset identity, content hash, and split lineage pins declared; kind-appropriate split parameters present",
    "M1: preprocessing and sampling fit scopes declared per step; nothing fit before the split",
    "M2: feature selection and target encoding declared in-fold or explicitly none",
    "M3: tuning never uses test or future holdout; selection never uses test metrics",
    "M4: seeds recorded and repetition aggregated as mean/variance, never best-only",
    "M5: OOD, subgroup, calibration, and drift gaps reported as limitations, never fabricated",
    "M6: model/resource changes and heuristic changes are layered, never mixed in one comparison",
)

# ML-path rank for comparing a ceiling against the contract's bar. The
# governance ladder's math rung (mathematically_verified) does not apply on
# this path; a contract requiring it is an authoring error this adapter
# cannot interpret. externally_validated and production_observed stay on
# the ladder: a case may legitimately require them, and every adapter
# ceiling is then honestly below the bar — the adapter never grants them,
# it reports them.
_ML_RANK = {
    "draft": 0,
    "engineering_verified": 1,
    "data_accepted": 2,
    "evaluation_eligible": 3,
    "empirically_supported": 4,
    "externally_validated": 5,
    "production_observed": 6,
}

# Claim class to governance claim type.
_CLAIM_TYPE = {
    "engineering": "engineering_claim",
    "data_acceptance": "data_claim",
    "generalization": "empirical_claim",
}

# ML-family claim types whose contract bars this adapter can interpret:
# exactly the claim types the ML path can produce. mathematical_claim
# belongs to the math path and predictive_claim is never produced by this
# adapter (ADR-0008 addendum A2); both are silently skipped as foreign
# contract entries.
_ML_CLAIM_TYPES = frozenset(
    {
        "engineering_claim",
        "data_claim",
        "empirical_claim",
    }
)

# Case gate to contract entry (claim_type, min_maturity).
_GATE_ENTRY = {
    "engineering": ("engineering_claim", "engineering_verified"),
    "data_acceptance": ("data_claim", "data_accepted"),
    "generalization": ("empirical_claim", "empirically_supported"),
}


def _preview(values: set[str], limit: int = 3, width: int = 40) -> str:
    """Bounded, safe diagnostic rendering of caller-supplied strings
    (R42e/R42f review): at most ``limit`` entries, each truncated to
    ``width`` characters and then escaped with :func:`ascii` — the schema
    pattern ``^\\S+$`` excludes whitespace but not ESC, NUL, or Unicode
    bidi controls, so raw caller text must never reach the error message.
    ``ascii`` is applied to the truncated slice only, never to a full
    oversized string, so no large temporary is materialized."""
    shown = []
    for value in sorted(values)[:limit]:
        escaped = ascii(value[:width])
        if len(value) > width:
            shown.append(f"{escaped}...<{len(value)} chars>")
        else:
            shown.append(escaped)
    suffix = "" if len(values) <= limit else f", ...<{len(values)} total>"
    return "[" + ", ".join(shown) + suffix + "]"


def _require_complete_assessment_declaration(
    declaration: Sequence[dict[str, str]], source: str
) -> None:
    """Fail closed unless the declaration names each ml assessment
    dimension exactly once (ADR-0008 addendum A3; R42c/R42d review).

    The evaluation-contract/v3 schema keeps ``dimension`` a free string so
    the seam stays domain-neutral, so this four-dimension floor lives in
    the adapter. It is enforced both when a contract is built from a case
    and when one is consumed by ``validate_claim``: a hand-crafted
    contract with an empty, partial, or duplicated declaration must never
    silently drop assessment gap rules.

    Single pass with bounded diagnostics (R42d/R42e review): the schema
    sets neither ``maxItems`` nor ``maxLength``, so a legal contract may
    carry an arbitrary number of arbitrarily long free-form dimensions —
    a per-item ``list.count`` would be quadratic, and echoing
    caller-supplied dimension strings would amplify the error text. The
    count fast-reject runs first; once the length is pinned to the
    expected four, every summary below is bounded by construction, and
    caller strings are rendered only through :func:`_preview`
    (count-capped, length-truncated, and control-character-escaped). ``missing`` is drawn from the
    trusted expected vocabulary and is always safe to list.
    """
    dimensions = [entry["dimension"] for entry in declaration]
    expected = set(_ASSESSMENT_KIND)
    if len(dimensions) != len(expected):
        # The missing summary is bounded by the expected set (four), and
        # caller-supplied dimension strings are never expanded here.
        missing = sorted(expected - set(dimensions))
        raise AdapterError(
            f"assessment declaration in {source} carries "
            f"{len(dimensions)} entries; exactly {len(expected)} are "
            f"required, one per ml assessment dimension {sorted(expected)}"
            f" (missing: {missing if missing else 'none'})"
        )
    # Length is pinned from here on, so every summary below is bounded.
    seen: set[str] = set()
    duplicates: set[str] = set()
    for dimension in dimensions:
        if dimension in seen:
            duplicates.add(dimension)
        seen.add(dimension)
    if duplicates:
        raise AdapterError(
            f"assessment declaration in {source} repeats "
            f"{len(duplicates)} dimension(s) {_preview(duplicates)} — "
            "more than once; each ml assessment dimension must appear "
            "exactly once"
        )
    if seen != expected:
        missing = sorted(expected - seen)
        unknown = seen - expected
        raise AdapterError(
            f"assessment declaration in {source} must name each ml "
            f"assessment dimension {sorted(expected)} exactly once "
            f"(missing: {missing if missing else 'none'}; unknown: "
            f"{len(unknown)} supplied {_preview(unknown)})"
        )


class MLAdapter(DomainAdapter):
    """DomainAdapter implementation for machine-learning research."""

    @property
    def domain(self) -> str:
        return "ml"

    def normalize_task(self, domain_input: dict[str, Any]) -> DomainTask:
        payload = _load_seam_record("ml-task/v1", domain_input).data
        core_task_draft = {
            "schema": "research-task/v1",
            "task_id": payload["task_id"],
            "title": payload["title"],
            "problem_statement": payload["statement"],
            "domain": "ml",
            "scope": payload["scope"],
            "resources": payload["resources"],
            "completion_criteria": payload["completion_criteria"],
            "permissions": payload["permissions"],
            "allowed_external_effects": payload["allowed_external_effects"],
            "created_at": payload["created_at"],
            "domain_context": {
                "study_id": payload["study_id"],
                "task_type": payload["task_type"],
                "data_spec": payload["data_spec"],
                "holdout_policy": payload["holdout_policy"],
            },
        }
        return DomainTask.from_payload(
            {
                "schema": "domain-task/v2",
                "domain": "ml",
                "domain_schema_id": "ml-task/v1",
                "domain_payload": payload,
                "core_task_draft": core_task_draft,
            }
        )

    def validate_claim(
        self,
        claim: dict[str, Any],
        evidence: Sequence[dict[str, Any]],
        contract: EvaluationContract,
    ) -> ClaimAssessment:
        claim_data = _load_seam_record("ml-claim/v1", claim).data
        # Contract-internal validity comes FIRST, before any binding that
        # involves claim or evidence: the contract is the judging
        # instrument, and a malformed one fails closed on its own (R42d
        # review — the check order now matches this invariant).
        if not isinstance(contract, EvaluationContract):
            raise AdapterError("contract must be an EvaluationContract")
        if contract.payload["schema"] != "evaluation-contract/v3":
            raise AdapterError(
                "the ml adapter requires an evaluation-contract/v3 payload: "
                "older versions carry no case-derived selection/split pins, got "
                f"{contract.payload['schema']!r}"
            )
        # The declaration is the case's evidentiary floor: it must cover
        # each of the four ml assessment dimensions exactly once — an
        # empty, partial, or duplicated declaration would silently drop
        # gap rules (R42c review).
        _require_complete_assessment_declaration(
            contract.payload["assessment_declaration"], "the evaluation contract"
        )
        _evidence.validate_selection_contract(contract.payload)
        if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence):
            raise AdapterError(
                "evidence must be a sequence of ml-evidence/v1 or ml-evidence/v2 payloads"
            )
        evidence_data = []
        for index, item in enumerate(evidence):
            if not isinstance(item, dict):
                raise AdapterError(f"evidence[{index}] is not a payload object")
            evidence_data.append(
                _load_seam_record_one_of(
                    ("ml-evidence/v1", "ml-evidence/v2"), item
                ).data
            )
        # Study binding (ADR-0008 addendum A2): every evidence item must
        # belong to the claim's study; a mismatch fails closed.
        for index, item in enumerate(evidence_data):
            if item["study_id"] != claim_data["study_id"]:
                raise AdapterError(
                    f"evidence[{index}] study_id {item['study_id']!r} does not "
                    f"match the claim's study_id {claim_data['study_id']!r}; "
                    "claim and evidence must be bound to one study"
                )
        # Case/study binding (ADR-0008 addendum A3): the claim must pin the
        # exact case this contract was derived from and name the same study.
        if claim_data["case_sha256"] != contract.case_sha256:
            raise AdapterError(
                "claim case_sha256 does not match the contract's case_sha256; "
                "the claim does not answer the case this contract judges"
            )
        if claim_data["study_id"] != contract.payload["study_id"]:
            raise AdapterError(
                f"claim study_id {claim_data['study_id']!r} does not match "
                "the contract's study_id; claim and case must belong to one "
                "study"
            )

        claim_class = claim_data["claim_class"]
        outcome = claim_data["outcome"]
        suggested_claim_type = _CLAIM_TYPE[claim_class]
        kinds = {item["kind"] for item in evidence_data}

        if claim_class == "generalization":
            for index, item in enumerate(evidence_data):
                if item["kind"] != "experiment_run":
                    continue
                if item["schema"] != "ml-evidence/v2":
                    raise AdapterError(
                        f"evidence[{index}] experiment_run must use ml-evidence/v2 "
                        "for a generalization claim; v1 has no final-evaluation "
                        "partition/split pin"
                    )
                _evidence.validate_final_evaluation(contract.payload, item)

        # Declaration <-> result comparison (ADR-0008 addendum A3): a
        # dimension declared not_performed contradicts supplied assessment
        # evidence (fail closed); a dimension declared but unfulfilled, or
        # declared not_performed, is a gap (named for the generalization
        # tier below).
        gaps: list[str] = []
        for entry in contract.payload["assessment_declaration"]:
            # Coverage was enforced above: every dimension here is a known
            # ml assessment dimension appearing exactly once.
            dimension = entry["dimension"]
            present = _ASSESSMENT_KIND[dimension] in kinds
            if entry["status"] == "not_performed" and present:
                raise AdapterError(
                    f"assessment dimension {dimension!r} is declared "
                    "not_performed in the case but assessment evidence for "
                    "it was supplied; the declaration is contradicted"
                )
            if not (entry["status"] == "declared" and present):
                gaps.append(dimension)

        experiment_items = [
            item for item in evidence_data if item["kind"] in _EXPERIMENT_KINDS
        ]
        eligible = [
            item
            for item in experiment_items
            if item["data_provenance"] in _REAL_OR_PUBLIC
        ]
        # Seed multiplicity is counted by UNIQUE seed: listing the same seed
        # twice is not a repeated-seed study (R42 regression).
        multi_seed = [item for item in eligible if len(set(item["seeds"])) >= 2]
        solid = [item for item in multi_seed if item["frozen_holdout"]]

        reasons: list[str] = []
        triggered_rules: list[str] = []

        if not evidence_data:
            triggered_rules.append("no-evidence")
            reasons.append("No evidence payloads were supplied.")

        # Maturity ceiling: the experiment evidence drives it; the asserted
        # outcome never lifts it.
        if claim_class == "engineering":
            ceiling = "engineering_verified"
            reasons.append(
                "An engineering claim caps at engineering_verified."
            )
        elif claim_class == "data_acceptance":
            ceiling = "data_accepted"
            reasons.append(
                "A data-acceptance claim caps at data_accepted."
            )
        else:  # generalization
            # Independent constraints, each recorded, strictest ceiling wins
            # (ADR-0008 addendum A2): concurrent violations all land on the
            # ledger, never hidden behind an if/elif chain.
            # Independent constraints, each recorded, strictest ceiling
            # wins (ADR-0008 addendum A2): concurrent violations all land
            # on the ledger, never hidden behind an if/elif chain. The
            # seed-stability and frozen-holdout predicates are NOT nested
            # behind the provenance check: when no public/real experiment
            # exists, the missing repeated-seed and frozen-holdout records
            # still register and pull the ceiling to engineering_verified
            # (R42c review — an else-branch here let a synthetic single-seed
            # unfrozen record keep a falsely high data_accepted ceiling).
            constraints: list[tuple[str, str, str]] = []
            if not eligible:
                constraints.append(
                    (
                        "data_accepted",
                        "synthetic-evidence-cap",
                        "No public or real experiment evidence is present; a "
                        "generalization claim caps at data_accepted (forbidden "
                        "channel synthetic-as-real-data-evidence).",
                    )
                )
            if not multi_seed:
                constraints.append(
                    (
                        "engineering_verified",
                        "single-seed-cap",
                        "No public or real experiment item repeats across "
                        "distinct seeds; a single-seed best value cannot "
                        "support a stable claim, so a generalization claim "
                        "caps at engineering_verified (forbidden channel "
                        "single-seed-best-as-stable-claim).",
                    )
                )
            if not solid:
                constraints.append(
                    (
                        "data_accepted",
                        "frozen-holdout-missing",
                        "No repeated-seed public or real experiment item "
                        "was produced on a frozen holdout; a "
                        "generalization claim caps at data_accepted.",
                    )
                )
            if constraints:
                ceiling = min(
                    (item[0] for item in constraints), key=_ML_RANK.__getitem__
                )
                for _, rule, reason in constraints:
                    triggered_rules.append(rule)
                    reasons.append(reason)
            else:
                ceiling = "empirically_supported"
                reasons.append(
                    "Repeated-seed public or real experiment evidence "
                    "produced on a frozen holdout can lift a generalization "
                    "claim to empirically_supported."
                )
            # Missing OOD/subgroup evaluations are named without moving the
            # ceiling (acceptance gate); calibration/drift gaps are honestly
            # marked "not assessed" the same way. Every detected gap must be
            # acknowledged per-dimension in the claim's
            # declared_assessment_gaps, and an empty declared limitations
            # array contradicts the detected gaps — both fail closed
            # (ADR-0008 addendum A3).
            gap_rules: list[str] = []
            for dimension in ("ood", "subgroup", "calibration", "drift"):
                if dimension not in gaps:
                    continue
                gap_rules.append(_ASSESSMENT_GAP_RULE[dimension])
                if dimension == "ood":
                    reasons.append(
                        "No OOD assessment evidence is present; the gap is "
                        "reported as a limitation, not fabricated, and the "
                        "ceiling is not moved."
                    )
                elif dimension == "subgroup":
                    reasons.append(
                        "No subgroup assessment evidence is present; the gap "
                        "is reported as a limitation, not fabricated, and the "
                        "ceiling is not moved."
                    )
                elif dimension == "calibration":
                    reasons.append(
                        "Calibration was not assessed in the supplied "
                        "evidence; this is named without moving the ceiling."
                    )
                else:
                    reasons.append(
                        "Drift was not assessed in the supplied evidence; "
                        "this is named without moving the ceiling."
                    )
            triggered_rules.extend(gap_rules)
            undeclared = [
                dimension
                for dimension in gaps
                if dimension not in set(claim_data["declared_assessment_gaps"])
            ]
            if undeclared:
                raise AdapterError(
                    "generalization claim does not acknowledge the detected "
                    f"assessment gaps {undeclared} in declared_assessment_gaps"
                )
            if gap_rules and not claim_data["limitations"]:
                raise AdapterError(
                    "generalization claim declares an empty limitations array "
                    f"while assessment gaps were detected ({', '.join(gap_rules)}); "
                    "declare the gaps as limitations or supply the assessments"
                )

        # Disposition: the asserted outcome maps conservatively, and BOTH
        # terminal directions require evidence relevant to the claim class
        # (ADR-0008 addendum A3); pass on the generalization tier requires
        # the evidence to carry the tier.
        relevant = [
            item
            for item in evidence_data
            if item["kind"] in _RELEVANT_KINDS[claim_class]
        ]
        if outcome == "fail":
            if not evidence_data:
                disposition = "inconclusive"
                reasons.append(
                    "An asserted fail without evidence cannot be suggested "
                    "refuted."
                )
            elif not relevant:
                disposition = "inconclusive"
                triggered_rules.append("no-relevant-evidence")
                reasons.append(
                    f"An asserted fail on a {claim_class} claim whose "
                    "evidence carries no relevant kind "
                    f"{sorted(_RELEVANT_KINDS[claim_class])} cannot be "
                    "suggested refuted."
                )
            else:
                disposition = "refuted"
                reasons.append(
                    "An asserted fail with relevant evidence suggests refuted."
                )
        elif outcome == "inconclusive":
            disposition = "inconclusive"
            reasons.append(
                "outcome 'inconclusive' is a legitimate terminal and is not "
                "forced into supported/refuted."
            )
        elif claim_class in ("engineering", "data_acceptance"):
            if not evidence_data:
                disposition = "inconclusive"
                reasons.append(
                    f"An asserted pass on a {claim_class} claim without "
                    "evidence cannot be suggested supported."
                )
            elif not relevant:
                disposition = "inconclusive"
                triggered_rules.append("no-relevant-evidence")
                reasons.append(
                    f"An asserted pass on a {claim_class} claim whose "
                    "evidence carries no relevant kind "
                    f"{sorted(_RELEVANT_KINDS[claim_class])} cannot be "
                    "suggested supported."
                )
            else:
                disposition = "supported"
                reasons.append(
                    f"An asserted pass on a {claim_class} claim with "
                    "relevant evidence suggests supported."
                )
        else:  # generalization
            if ceiling == "empirically_supported":
                disposition = "supported"
                reasons.append(
                    "An asserted pass on a generalization claim backed by "
                    "repeated-seed frozen-holdout public or real evidence "
                    "suggests supported."
                )
            else:
                disposition = "inconclusive"
                reasons.append(
                    "An asserted pass on a generalization claim whose "
                    "evidence cannot carry the tier is inconclusive."
                )

        # The contract's promotion bar is load-bearing: compare the ceiling
        # against the case requirement for this claim type. Exactly one
        # applicable bar must exist — zero matches mean the case does not
        # cover this claim, and duplicate matches are ambiguous; both fail
        # closed (ADR-0008 addendum A3). A bar outside the ML promotion path
        # (mathematically_verified) is a contract-authoring error this
        # adapter cannot interpret. An externally_validated or
        # production_observed bar is interpretable and honestly never met by
        # an adapter ceiling.
        matched_bar = False
        for entry in contract.required_evidence:
            entry_claim_type = entry["claim_type"]
            if entry_claim_type not in _ML_CLAIM_TYPES:
                continue
            bar = entry["min_maturity"]
            if bar not in _ML_RANK:
                raise AdapterError(
                    f"evaluation contract requires min_maturity {bar!r} for "
                    f"{entry_claim_type}, which is not on the ml promotion "
                    f"path {sorted(_ML_RANK)}; the adapter cannot interpret it"
                )
            if entry_claim_type != suggested_claim_type:
                continue
            if matched_bar:
                raise AdapterError(
                    "evaluation contract carries duplicate bars for "
                    f"{suggested_claim_type!r}; exactly one applicable bar "
                    "is required"
                )
            matched_bar = True
            if _ML_RANK[ceiling] < _ML_RANK[bar]:
                triggered_rules.append("below-case-promotion-bar")
                reasons.append(
                    f"The case contract requires {bar} for "
                    f"{entry_claim_type}; the evidence ceiling {ceiling} is "
                    "below that bar."
                )
            else:
                reasons.append(
                    f"The evidence ceiling {ceiling} meets the case "
                    f"promotion bar {bar}."
                )
        if not matched_bar:
            raise AdapterError(
                "evaluation contract carries no applicable bar for "
                f"{suggested_claim_type!r}; the case does not cover this claim"
            )

        return ClaimAssessment.from_payload(
            {
                "schema": "claim-assessment/v1",
                "suggested_claim_type": suggested_claim_type,
                "suggested_disposition": disposition,
                "evidence_maturity_ceiling": ceiling,
                "reasons": reasons,
                "triggered_rules": triggered_rules,
            }
        )

    def build_evaluation_contract(self, case: dict[str, Any]) -> EvaluationContract:
        case_data = _load_seam_record("ml-case/v1", case).data
        # ADR-0008 addendum A5: judge the declared experiment topology
        # before any contract is constructed — DAG structural pre-phase
        # first, then the leakage predicates and semantic floors. Single
        # integration point; _topology is private to this package.
        _topology.validate_declared_topology(case_data)
        required_evidence: list[dict[str, str]] = []
        seen_claim_types: set[str] = set()
        for gate in case_data["gates"]:
            claim_type, min_maturity = _GATE_ENTRY[gate]
            if claim_type in seen_claim_types:
                continue
            seen_claim_types.add(claim_type)
            required_evidence.append(
                {"claim_type": claim_type, "min_maturity": min_maturity}
            )
        # The case's assessment section rides the contract (v2) so
        # validate_claim can compare declaration against supplied evidence.
        assessment_declaration: list[dict[str, str]] = []
        for dimension in ("calibration", "subgroup", "ood", "drift"):
            section = case_data["assessment"][dimension]
            declaration_entry = {
                "dimension": dimension,
                "status": section["status"],
            }
            detail_field = _ASSESSMENT_DETAIL_FIELD[dimension]
            if detail_field in section:
                declaration_entry["detail"] = section[detail_field]
            assessment_declaration.append(declaration_entry)
        # Tripwire: the ml-case schema already requires exactly these four
        # dimensions, so this guards future schema drift rather than author
        # input — the contract must never carry a partial floor (R42c
        # review, same check as the validate_claim entry point).
        _require_complete_assessment_declaration(
            assessment_declaration, "the built evaluation contract"
        )
        return EvaluationContract.from_payload(
            {
                "schema": "evaluation-contract/v3",
                "case_sha256": canonical_sha256(case_data),
                "study_id": case_data["study_id"],
                "required_evidence": required_evidence,
                "forbidden_channels": list(_FORBIDDEN_CHANNELS),
                "checkpoints": list(_CHECKPOINTS),
                "assessment_declaration": assessment_declaration,
                "selection_partition": case_data["selection"]["split_used"],
                "selection_sha256": case_data["selection"]["sha256"],
                "split_sha256": case_data["split"]["sha256"],
            }
        )
