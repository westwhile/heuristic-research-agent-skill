"""Quant domain adapter (ADR-0005 decisions 4/5/7; ARCHITECTURE §5.1).

Frozen mapping table:

- claim_class declares the evidentiary tier a claim asserts: engineering,
  data_acceptance, oos_empirical, real_market;
- evidence data_provenance is the ceiling driver: synthetic or sample
  provenance caps any empirical/real-market claim at data_accepted —
  synthetic or sample evidence can never support an out-of-sample or
  real-market claim; real_pit lifts oos_empirical to empirically_supported;
  production lifts real_market to externally_validated;
- production_observed is NEVER granted by this adapter: it requires
  long-horizon production observation beyond any adapter's judgement;
- kind/provenance consistency is enforced (a synthetic_backtest cannot
  carry real_pit provenance); inconsistent pairs fail closed;
- evaluation contracts derive their promotion bars from the case's gates;
  the forbidden channels and Q-checkpoints are fixed by ADR-0005 decision 5,
  not by the case author.
"""

from __future__ import annotations

from typing import Any, Sequence

from research_evolution.core import canonical_sha256

from ..base import DomainAdapter
from ..types import (
    AdapterError,
    ClaimAssessment,
    DomainTask,
    EvaluationContract,
    _load_seam_record,
)

# Consistency rule: these evidence kinds must carry exactly this
# data_provenance; any other pairing is an authoring error and fails
# closed. Kinds not listed here (unit_test_run, data_audit_report, ...)
# are provenance-free.
_KIND_PROVENANCE = {
    "synthetic_backtest": "synthetic",
    "sample_backtest": "sample",
    "real_data_backtest": "real_pit",
    "production_log": "production",
}

# Forbidden evidence channels for every quant contract (ADR-0005 decision 5
# Quant items plus the governance forbidden-expression list).
_FORBIDDEN_CHANNELS = (
    "future-function-features",
    "non-pit-data",
    "label-without-lead-alignment",
    "backtest-as-live-returns",
    "synthetic-as-real-data-evidence",
)

# Governance Q-gates as case checkpoints.
_CHECKPOINTS = (
    "Q0: schema, primary keys, coverage, and per-unit time fields declared",
    "Q1: PIT revision policy and sample-pool availability times declared",
    "Q2: signal, execution, and label construction free of leakage",
    "Q3: costs, fill limits, position limits, liquidity, and benchmark conventions stated",
    "Q4: time-ordered out-of-sample evaluation plus a future holdout window",
    "Q5: bounded claims are never written as real-return claims",
)

# Quant-path rank for comparing a ceiling against the contract's bar. The
# governance ladder's math rung (mathematically_verified) does not apply on
# this path; a contract requiring it is an authoring error this adapter
# cannot interpret. production_observed stays on the ladder as rank 6: a
# case may legitimately require it, and every adapter ceiling is then
# honestly below the bar — the adapter never grants it, it reports it.
_QUANT_RANK = {
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
    "oos_empirical": "empirical_claim",
    "real_market": "strategy_claim",
}

# Quant-family claim types whose contract bars this adapter can interpret
# (everything but mathematical_claim, which belongs to the math path).
_QUANT_CLAIM_TYPES = frozenset(
    {
        "engineering_claim",
        "data_claim",
        "empirical_claim",
        "predictive_claim",
        "strategy_claim",
        "production_claim",
    }
)

# Case gate to contract entry (claim_type, min_maturity).
_GATE_ENTRY = {
    "engineering": ("engineering_claim", "engineering_verified"),
    "data_acceptance": ("data_claim", "data_accepted"),
    "oos_empirical": ("empirical_claim", "empirically_supported"),
    "real_market": ("strategy_claim", "externally_validated"),
}


class QuantAdapter(DomainAdapter):
    """DomainAdapter implementation for quantitative research."""

    @property
    def domain(self) -> str:
        return "quant"

    def normalize_task(self, domain_input: dict[str, Any]) -> DomainTask:
        payload = _load_seam_record("quant-task/v1", domain_input).data
        core_task_draft = {
            "schema": "research-task/v1",
            "task_id": payload["task_id"],
            "title": payload["title"],
            "problem_statement": payload["statement"],
            "domain": "quant",
            "scope": payload["scope"],
            "resources": payload["resources"],
            "completion_criteria": payload["completion_criteria"],
            "permissions": payload["permissions"],
            "allowed_external_effects": payload["allowed_external_effects"],
            "created_at": payload["created_at"],
            "domain_context": {
                "study_id": payload["study_id"],
                "universe": payload["universe"],
                "calendar": payload["calendar"],
                "frequency": payload["frequency"],
                "pit_policy": payload["pit_policy"],
                "data_spec": payload["data_spec"],
                "cost_model": payload["cost_model"],
            },
        }
        return DomainTask.from_payload(
            {
                "schema": "domain-task/v1",
                "domain": "quant",
                "domain_schema_id": "quant-task/v1",
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
        claim_data = _load_seam_record("quant-claim/v1", claim).data
        if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence):
            raise AdapterError("evidence must be a sequence of quant-evidence/v1 payloads")
        evidence_data = []
        for index, item in enumerate(evidence):
            if not isinstance(item, dict):
                raise AdapterError(f"evidence[{index}] is not a payload object")
            loaded = _load_seam_record("quant-evidence/v1", item).data
            expected_provenance = _KIND_PROVENANCE.get(loaded["kind"])
            if (
                expected_provenance is not None
                and loaded["data_provenance"] != expected_provenance
            ):
                raise AdapterError(
                    f"evidence[{index}] kind {loaded['kind']!r} requires "
                    f"data_provenance {expected_provenance!r}, got "
                    f"{loaded['data_provenance']!r}: kind/provenance mismatch"
                )
            evidence_data.append(loaded)
        if not isinstance(contract, EvaluationContract):
            raise AdapterError("contract must be an EvaluationContract")

        claim_class = claim_data["claim_class"]
        outcome = claim_data["outcome"]
        suggested_claim_type = _CLAIM_TYPE[claim_class]
        provenances = {item["data_provenance"] for item in evidence_data}
        real_present = "real_pit" in provenances or "production" in provenances
        production_present = "production" in provenances

        reasons: list[str] = []
        triggered_rules: list[str] = []

        if not evidence_data:
            triggered_rules.append("no-evidence")
            reasons.append("No evidence payloads were supplied.")
        if real_present:
            triggered_rules.append("real-pit-evidence-present")
            reasons.append(
                "Point-in-time correct or production evidence is present."
            )
        if production_present:
            triggered_rules.append("production-evidence-present")
            reasons.append("Production (live-trading) evidence is present.")

        # Maturity ceiling: provenance is the driver, the asserted outcome
        # never lifts it.
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
        elif claim_class == "oos_empirical":
            if real_present:
                ceiling = "empirically_supported"
                reasons.append(
                    "Real point-in-time evidence can lift an out-of-sample "
                    "empirical claim to empirically_supported."
                )
            else:
                ceiling = "data_accepted"
                triggered_rules.append("synthetic-evidence-cap")
                reasons.append(
                    "Only synthetic or sample evidence is present; an "
                    "out-of-sample empirical claim caps at data_accepted "
                    "(forbidden channel synthetic-as-real-data-evidence)."
                )
        else:  # real_market
            if production_present:
                ceiling = "externally_validated"
                reasons.append(
                    "Production evidence can lift a real-market claim to "
                    "externally_validated; production_observed requires "
                    "long-horizon production observation and is never "
                    "granted by this adapter."
                )
            elif real_present:
                ceiling = "empirically_supported"
                reasons.append(
                    "Without production evidence a real-market claim caps at "
                    "empirically_supported; production_observed is never "
                    "granted by this adapter."
                )
            else:
                ceiling = "data_accepted"
                triggered_rules.append("synthetic-evidence-cap")
                reasons.append(
                    "Only synthetic or sample evidence is present; a "
                    "real-market claim caps at data_accepted and "
                    "production_observed is never granted by this adapter."
                )

        # Disposition: the asserted outcome maps conservatively; pass on the
        # empirical/real-market tiers requires the provenance to back it.
        if outcome == "fail":
            if evidence_data:
                disposition = "refuted"
                reasons.append(
                    "An asserted fail with evidence suggests refuted."
                )
            else:
                disposition = "inconclusive"
                reasons.append(
                    "An asserted fail without evidence cannot be suggested "
                    "refuted."
                )
        elif outcome == "inconclusive":
            disposition = "inconclusive"
            reasons.append(
                "outcome 'inconclusive' is a legitimate terminal and is not "
                "forced into supported/refuted."
            )
        elif claim_class in ("engineering", "data_acceptance"):
            if evidence_data:
                disposition = "supported"
                reasons.append(
                    f"An asserted pass on a {claim_class} claim with evidence "
                    "suggests supported."
                )
            else:
                disposition = "inconclusive"
                reasons.append(
                    f"An asserted pass on a {claim_class} claim without "
                    "evidence cannot be suggested supported."
                )
        elif claim_class == "oos_empirical":
            if real_present:
                disposition = "supported"
                reasons.append(
                    "An asserted pass on an out-of-sample empirical claim "
                    "backed by real point-in-time evidence suggests supported."
                )
            else:
                disposition = "inconclusive"
                reasons.append(
                    "An asserted pass on an out-of-sample empirical claim "
                    "backed only by synthetic or sample evidence is "
                    "inconclusive: the provenance cannot carry the tier."
                )
        else:  # real_market
            if production_present:
                disposition = "supported"
                reasons.append(
                    "An asserted pass on a real-market claim backed by "
                    "production evidence suggests supported."
                )
            else:
                disposition = "inconclusive"
                reasons.append(
                    "An asserted pass on a real-market claim without "
                    "production evidence is inconclusive: backtests never "
                    "entail live-trading returns (forbidden channel "
                    "backtest-as-live-returns)."
                )

        # The contract's promotion bar is load-bearing: compare the ceiling
        # against the case requirement for this claim type. A bar outside
        # the quant promotion path (mathematically_verified) is a
        # contract-authoring error this adapter cannot interpret; fail
        # closed rather than silently mis-rank it. A production_observed bar
        # is interpretable and honestly never met by an adapter ceiling.
        for entry in contract.required_evidence:
            entry_claim_type = entry["claim_type"]
            if entry_claim_type not in _QUANT_CLAIM_TYPES:
                continue
            bar = entry["min_maturity"]
            if bar not in _QUANT_RANK:
                raise AdapterError(
                    f"evaluation contract requires min_maturity {bar!r} for "
                    f"{entry_claim_type}, which is not on the quant promotion "
                    f"path {sorted(_QUANT_RANK)}; the adapter cannot interpret it"
                )
            if entry_claim_type != suggested_claim_type:
                continue
            if _QUANT_RANK[ceiling] < _QUANT_RANK[bar]:
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
        case_data = _load_seam_record("quant-case/v1", case).data
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
        return EvaluationContract.from_payload(
            {
                "schema": "evaluation-contract/v1",
                "case_sha256": canonical_sha256(case_data),
                "required_evidence": required_evidence,
                "forbidden_channels": list(_FORBIDDEN_CHANNELS),
                "checkpoints": list(_CHECKPOINTS),
            }
        )
