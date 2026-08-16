"""Math domain adapter (ADR-0005 decisions 4/5/7; ARCHITECTURE §5.1).

Frozen mapping table:

- result vocabulary proof / disproof / partial / inconclusive; partial and
  inconclusive are legitimate terminals and are never forced into
  supported/refuted;
- proof/disproof suggest supported/refuted ONLY with certificate-class
  evidence (proof_certificate, formal_verification); without it the
  suggestion is inconclusive — numeric evidence can never discharge a
  global claim;
- maturity ceiling: mathematically_verified only when certificate-class
  evidence is present, otherwise engineering_verified;
- evaluation contracts derive their maturity bar from the case's sought
  class: bounded_verification caps at engineering_verified.
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

# Certificate class: the only evidence kinds that can lift a
# mathematical_claim to mathematically_verified (ADR-0005 decision 4).
_CERTIFICATE_KINDS = frozenset({"proof_certificate", "formal_verification"})

# Forbidden evidence channels for every math contract (ADR-0005 decision 5
# Math item; governance forbidden-expression list).
_FORBIDDEN_CHANNELS = (
    "numeric-extrapolation-as-proof",
    "llm-consensus-as-proof",
)

# Governance M-gates as case checkpoints.
_CHECKPOINTS = (
    "M0: problem, object domain, and quantifiers frozen",
    "M1: candidate and evidence hashes bound",
    "M2: independent verifier check",
    "M3: coverage bridge from local result to global claim",
    "M4: proof/disproof certificate with audit",
)

# Math-path rank for comparing ceiling against the contract's bar. The
# governance ladder's quant rungs do not apply here; on the math path the
# only comparison that matters is engineering_verified < mathematically_verified.
_MATH_RANK = {"engineering_verified": 1, "mathematically_verified": 2}


class MathAdapter(DomainAdapter):
    """DomainAdapter implementation for mathematics."""

    @property
    def domain(self) -> str:
        return "math"

    def normalize_task(self, domain_input: dict[str, Any]) -> DomainTask:
        payload = _load_seam_record("math-task/v1", domain_input).data
        core_task_draft = {
            "schema": "research-task/v1",
            "task_id": payload["task_id"],
            "title": payload["title"],
            "problem_statement": payload["statement"],
            "domain": "math",
            "scope": payload["scope"],
            "resources": payload["resources"],
            "completion_criteria": payload["completion_criteria"],
            "permissions": payload["permissions"],
            "allowed_external_effects": payload["allowed_external_effects"],
            "created_at": payload["created_at"],
            "domain_context": {
                "problem_id": payload["problem_id"],
                "object_domain": payload["object_domain"],
                "quantifiers": payload["quantifiers"],
                "assumptions": payload["assumptions"],
                "dependencies": payload["dependencies"],
                "sought": payload["sought"],
            },
        }
        return DomainTask.from_payload(
            {
                "schema": "domain-task/v1",
                "domain": "math",
                "domain_schema_id": "math-task/v1",
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
        claim_data = _load_seam_record("math-claim/v1", claim).data
        if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence):
            raise AdapterError("evidence must be a sequence of math-evidence/v1 payloads")
        evidence_data = []
        for index, item in enumerate(evidence):
            if not isinstance(item, dict):
                raise AdapterError(f"evidence[{index}] is not a payload object")
            evidence_data.append(_load_seam_record("math-evidence/v1", item).data)
        if not isinstance(contract, EvaluationContract):
            raise AdapterError("contract must be an EvaluationContract")

        certificate_present = any(
            item["kind"] in _CERTIFICATE_KINDS for item in evidence_data
        )
        result = claim_data["result"]
        reasons: list[str] = []
        triggered_rules: list[str] = []

        if certificate_present:
            ceiling = "mathematically_verified"
            triggered_rules.append("certificate-class-evidence-present")
            reasons.append(
                "Certificate-class evidence is present, so the maturity "
                "ceiling can reach mathematically_verified."
            )
        else:
            ceiling = "engineering_verified"
            triggered_rules.append("numeric-evidence-ceiling")
            reasons.append(
                "Only non-certificate evidence (computational, literature, or "
                "other) is present; the maturity ceiling is engineering_verified."
            )

        if result in ("proof", "disproof"):
            if certificate_present:
                disposition = "supported" if result == "proof" else "refuted"
                reasons.append(
                    f"A {result} result with certificate-class evidence "
                    f"suggests {disposition}."
                )
            else:
                disposition = "inconclusive"
                triggered_rules.append("global-claim-requires-certificate")
                reasons.append(
                    f"A {result} claim without certificate-class evidence "
                    "cannot be suggested supported/refuted: numeric "
                    "extrapolation or consensus must never discharge a global "
                    "claim (forbidden channel numeric-extrapolation-as-proof)."
                )
        else:
            disposition = "inconclusive"
            reasons.append(
                f"result {result!r} is a legitimate terminal and is not "
                "forced into supported/refuted."
            )

        # The contract's promotion bar is load-bearing: compare the ceiling
        # against the case requirement for mathematical_claim. A bar outside
        # the math promotion path is a contract-authoring error this adapter
        # cannot interpret; fail closed rather than silently mis-rank it.
        for entry in contract.required_evidence:
            if entry["claim_type"] != "mathematical_claim":
                continue
            bar = entry["min_maturity"]
            if bar not in _MATH_RANK:
                raise AdapterError(
                    f"evaluation contract requires min_maturity {bar!r} for "
                    "mathematical_claim, which is not on the math promotion "
                    f"path {sorted(_MATH_RANK)}; the adapter cannot interpret it"
                )
            if _MATH_RANK[ceiling] < _MATH_RANK[bar]:
                triggered_rules.append("below-case-promotion-bar")
                reasons.append(
                    f"The case contract requires {bar} for "
                    f"mathematical_claim; the evidence ceiling {ceiling} is "
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
                "suggested_claim_type": "mathematical_claim",
                "suggested_disposition": disposition,
                "evidence_maturity_ceiling": ceiling,
                "reasons": reasons,
                "triggered_rules": triggered_rules,
            }
        )

    def build_evaluation_contract(self, case: dict[str, Any]) -> EvaluationContract:
        case_data = _load_seam_record("math-case/v1", case).data
        sought = case_data["sought"]
        min_maturity = (
            "engineering_verified"
            if sought == "bounded_verification"
            else "mathematically_verified"
        )
        return EvaluationContract.from_payload(
            {
                "schema": "evaluation-contract/v1",
                "case_sha256": canonical_sha256(case_data),
                "required_evidence": [
                    {
                        "claim_type": "mathematical_claim",
                        "min_maturity": min_maturity,
                    }
                ],
                "forbidden_channels": list(_FORBIDDEN_CHANNELS),
                "checkpoints": list(_CHECKPOINTS),
            }
        )
