"""Family contract registry: the single private metadata source.

ADR-0003 (decision 10): each entry declares, for one publishable record
family, its identity field, its supersedes capability (if any) with its
lineage scope, and its reference table (field -> target family, direction,
pin requirement). :mod:`._store` derives publish-time identity from this
table and :mod:`._graph` drives every cross-record check from it, so a
family becomes publishable exactly when the graph fully understands it —
there is no second table to drift out of sync.

This registry is data, not a rules language: composite semantics (case
closure, lineage scopes) live in the private validators that read the
table. Registry membership is the publishability boundary: a family whose
schema exists but which has no entry here fails closed at publish time
(:func:`._store.identity_of` raises). The case package joined in C4
together with its closure validator, keeping "publishable exactly when
the graph fully understands it" atomic. The two export families joined
in D3 (ADR-0004) the same way: one layer registering both families and
the graph's ``unauthorized_export`` gate in a single commit. The four
evaluation families joined in E2 (ADR-0006 decision 1) additively — the
generic graph machinery serves every reference they declare, so no new
composite validator was introduced with them. The four research-memory
families joined in M2 (ADR-0007 decisions 2, 3, 6, 7): the case package
successor v2 registers alongside the frozen v1 with the same member
references plus backward-only derived_from lineage; research-pattern/v1
and heuristic/v1 carry family-scoped supersedes lineage (the claim
precedent); reuse-event/v1 is a fact-axis record with two pinned
references. Every reference they declare is served by the generic graph
machinery; no new composite validator and no new violation kind was
introduced with them.
The three Phase 7 P7A incubation families join additively: candidate
manifests pin their source cases and patterns, while closure receipts and
context bundles each pin one candidate manifest. Their byte-closure,
principal-separation, lifecycle, and budget semantics remain inside the
pure in-process evolution module; the graph continues to serve exact
identity and hash-pin integrity.
Correctness Reset CR6 adds an artifact record and an evaluation-envelope
closure receipt. The receipt pins the existing candidate manifest and every
artifact record; byte/attestation and required-role semantics stay in the
pure in-process envelope-closure module.
Correctness Reset CR8 keeps context-bundle/v1 frozen and adds a plaintext-free
material assessment plus context-bundle/v2. The bundle pins its candidate and
all assessments; privacy, taint, lifecycle, and preflight budget semantics stay
inside the pure in-process context-governance module.
Phase 7 P7B1 adds one candidate-eligibility attestation that pins the candidate,
its byte-closure receipt, and its source cases. Eligibility outcome, lineage,
and evidence-byte semantics remain inside the pure in-process evolution module.
Phase 7 P7B2 adds one Skill candidate bundle that pins the P7B1 attestation and
its transitive candidate/closure/case identities. Payload/evidence byte closure
and Skill-layout semantics remain inside the pure in-process evolution module.
Phase 7 P7B3 adds one static-validation receipt that pins the exact Skill
candidate bundle. Payload, metadata, trigger, registry-snapshot, router-example,
and diff semantics remain inside the pure in-process evolution module.
Phase 7 P7B4 adds one semantic-review protocol attestation that pins both the
exact Skill candidate bundle and its P7B3 static-validation receipt. Review
evidence binding, declared reviewer-label separation, required dimensions, and
protocol outcomes remain inside the pure in-process evolution module; the
family deliberately cannot claim a real independent semantic review.
"""

from __future__ import annotations

from dataclasses import dataclass

TASK = "research-task/v1"
CLAIM = "research-claim/v1"
EVIDENCE = "research-evidence/v1"
RUN = "research-run/v1"
OBSERVATION = "research-failure-observation/v1"
ANALYSIS = "research-failure-analysis/v1"
CASE = "research-case-package/v1"
EXPORT_DECISION = "export-decision/v1"
EXPORT_RECEIPT = "export-receipt/v1"
EVALUATION_CASE = "evaluation-case/v1"
SUITE = "suite/v1"
EVALUATION_RUN = "evaluation-run/v1"
COMPARISON_REPORT = "comparison-report/v1"
SUITE_COMPARISON = "suite-comparison/v1"
EVALUATION_ATTEMPT = "evaluation-attempt/v1"
EVALUATION_RESULT = "evaluation-result/v1"
CASE_V2 = "research-case-package/v2"
PATTERN = "research-pattern/v1"
HEURISTIC = "heuristic/v1"
REUSE_EVENT = "reuse-event/v1"
CANDIDATE_MANIFEST = "candidate-manifest/v1"
ARTIFACT_CLOSURE_RECEIPT = "artifact-closure-receipt/v1"
CANDIDATE_ELIGIBILITY_ATTESTATION = "candidate-eligibility-attestation/v1"
SKILL_CANDIDATE_BUNDLE = "skill-candidate-bundle/v1"
SKILL_STATIC_VALIDATION_RECEIPT = "skill-static-validation-receipt/v1"
SKILL_SEMANTIC_REVIEW_ATTESTATION = "skill-semantic-review-attestation/v1"
CONTEXT_BUNDLE = "context-bundle/v1"
CONTEXT_BUNDLE_V2 = "context-bundle/v2"
CONTEXT_MATERIAL_ASSESSMENT = "context-material-assessment/v1"
ARTIFACT_RECORD = "artifact-record/v1"
EVALUATION_ENVELOPE_CLOSURE = "evaluation-envelope-closure-receipt/v1"


@dataclass(frozen=True)
class ReferenceContract:
    """One outbound reference field of a record family.

    ``shape`` is ``"object"`` (a single reference object), or
    ``"array_of_objects"`` (a member list of reference objects), or
    ``"array_of_scalars"`` (a plain id list). ``target_id_field`` is the id
    key inside a reference object and is ``None`` for scalar lists, where
    the item itself is the id. ``pin_required`` mirrors the schema-layer
    pin contract; the graph checks pin agreement whenever a pin is present,
    required or not. ``two_way_with`` names the reverse field on the target
    family when the pair must link in both directions (only the
    claim/evidence pair); one-directional hierarchical references leave it
    ``None`` and never trigger ``one_way_link``.
    """

    field: str
    shape: str
    target_family: str
    target_id_field: str | None
    pin_required: bool
    two_way_with: str | None = None


@dataclass(frozen=True)
class SupersedesContract:
    """Supersedes capability of a family.

    ``scope="family"``: lineage ranges over the whole family (claims).
    ``scope="anchor"``: lineage ranges only over records sharing one anchor
    — the target id extracted from the ``anchor_field`` reference — so a
    failure analysis may supersede only within its own observation's chain
    and an export decision only within its own case's chain
    (``lineage_scope_mismatch`` otherwise).
    """

    scope: str
    anchor_field: str | None = None


@dataclass(frozen=True)
class FamilyContract:
    """The complete per-family graph and identity contract."""

    schema_id: str
    identity_field: str
    supersedes: SupersedesContract | None
    references: tuple[ReferenceContract, ...]


FAMILIES: dict[str, FamilyContract] = {
    contract.schema_id: contract
    for contract in (
        FamilyContract(
            schema_id=TASK,
            identity_field="task_id",
            supersedes=None,
            references=(),
        ),
        FamilyContract(
            schema_id=CLAIM,
            identity_field="claim_id",
            supersedes=SupersedesContract(scope="family"),
            references=(
                ReferenceContract(
                    field="supporting_evidence",
                    shape="array_of_objects",
                    target_family=EVIDENCE,
                    target_id_field="evidence_id",
                    pin_required=False,
                    two_way_with="claim_ids",
                ),
            ),
        ),
        FamilyContract(
            schema_id=EVIDENCE,
            identity_field="evidence_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="claim_ids",
                    shape="array_of_scalars",
                    target_family=CLAIM,
                    target_id_field=None,
                    pin_required=False,
                    two_way_with="supporting_evidence",
                ),
            ),
        ),
        FamilyContract(
            schema_id=RUN,
            identity_field="run_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="task",
                    shape="object",
                    target_family=TASK,
                    target_id_field="task_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=OBSERVATION,
            identity_field="observation_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="run",
                    shape="object",
                    target_family=RUN,
                    target_id_field="run_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=ANALYSIS,
            identity_field="analysis_id",
            supersedes=SupersedesContract(
                scope="anchor", anchor_field="observation"
            ),
            references=(
                ReferenceContract(
                    field="observation",
                    shape="object",
                    target_family=OBSERVATION,
                    target_id_field="observation_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=CASE,
            identity_field="case_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="task",
                    shape="object",
                    target_family=TASK,
                    target_id_field="task_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="runs",
                    shape="array_of_objects",
                    target_family=RUN,
                    target_id_field="run_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="claims",
                    shape="array_of_objects",
                    target_family=CLAIM,
                    target_id_field="claim_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="evidence",
                    shape="array_of_objects",
                    target_family=EVIDENCE,
                    target_id_field="evidence_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="observations",
                    shape="array_of_objects",
                    target_family=OBSERVATION,
                    target_id_field="observation_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="analyses",
                    shape="array_of_objects",
                    target_family=ANALYSIS,
                    target_id_field="analysis_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=EXPORT_DECISION,
            identity_field="decision_id",
            supersedes=SupersedesContract(
                scope="anchor", anchor_field="case"
            ),
            references=(
                ReferenceContract(
                    field="case",
                    shape="object",
                    target_family=CASE,
                    target_id_field="case_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=EXPORT_RECEIPT,
            identity_field="receipt_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="decision",
                    shape="object",
                    target_family=EXPORT_DECISION,
                    target_id_field="decision_id",
                    pin_required=True,
                ),
            ),
        ),
        # Phase 3 evaluation families (ADR-0006 decision 1): additive
        # registration. Every reference below is served by the generic
        # graph machinery (dangling/pin/duplicate/self/cycle); no new
        # composite validator is introduced for them.
        FamilyContract(
            schema_id=EVALUATION_CASE,
            identity_field="evaluation_case_id",
            supersedes=None,
            references=(),
        ),
        FamilyContract(
            schema_id=SUITE,
            identity_field="suite_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="cases",
                    shape="array_of_objects",
                    target_family=EVALUATION_CASE,
                    target_id_field="evaluation_case_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=EVALUATION_RUN,
            identity_field="evaluation_run_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="case",
                    shape="object",
                    target_family=EVALUATION_CASE,
                    target_id_field="evaluation_case_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="suite",
                    shape="object",
                    target_family=SUITE,
                    target_id_field="suite_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=COMPARISON_REPORT,
            identity_field="report_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="champion",
                    shape="object",
                    target_family=EVALUATION_RUN,
                    target_id_field="evaluation_run_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="challenger",
                    shape="object",
                    target_family=EVALUATION_RUN,
                    target_id_field="evaluation_run_id",
                    pin_required=True,
                ),
            ),
        ),
        # Correctness Reset CR5 successor: observations are case/seed/frozen-
        # envelope pairs and every referenced run remains hash-pinned. The
        # historical comparison-report/v1 family stays readable but its
        # unsafe construction entry point is retired.
        FamilyContract(
            schema_id=SUITE_COMPARISON,
            identity_field="suite_comparison_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="suite",
                    shape="object",
                    target_family=SUITE,
                    target_id_field="suite_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="champion_runs",
                    shape="array_of_objects",
                    target_family=EVALUATION_RUN,
                    target_id_field="evaluation_run_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="challenger_runs",
                    shape="array_of_objects",
                    target_family=EVALUATION_RUN,
                    target_id_field="evaluation_run_id",
                    pin_required=True,
                ),
            ),
        ),
        # Correctness Reset CR4: an attempt is the always-publishable
        # execution fact; a result exists only after scoring succeeds and
        # pins exactly one attempt. The frozen evaluation-run/v1 family
        # remains registered for backward compatibility.
        FamilyContract(
            schema_id=EVALUATION_ATTEMPT,
            identity_field="evaluation_attempt_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="case",
                    shape="object",
                    target_family=EVALUATION_CASE,
                    target_id_field="evaluation_case_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="suite",
                    shape="object",
                    target_family=SUITE,
                    target_id_field="suite_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=EVALUATION_RESULT,
            identity_field="evaluation_result_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="attempt",
                    shape="object",
                    target_family=EVALUATION_ATTEMPT,
                    target_id_field="evaluation_attempt_id",
                    pin_required=True,
                ),
            ),
        ),
        # Phase 4 M2 research memory families (ADR-0007 decisions 2, 3, 6,
        # 7): additive registration. The case package successor v2 keeps the
        # six v1 member references and adds backward-only derived_from
        # lineage targeting v2 itself; pattern and heuristic carry
        # family-scoped supersedes lineage (the claim precedent);
        # reuse-event/v1 is a fact-axis record with two pinned references.
        # Every reference below is served by the generic graph machinery
        # (dangling/pin/duplicate/self/cycle); no new composite validator
        # and no new violation kind is introduced.
        FamilyContract(
            schema_id=CASE_V2,
            identity_field="case_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="task",
                    shape="object",
                    target_family=TASK,
                    target_id_field="task_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="runs",
                    shape="array_of_objects",
                    target_family=RUN,
                    target_id_field="run_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="claims",
                    shape="array_of_objects",
                    target_family=CLAIM,
                    target_id_field="claim_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="evidence",
                    shape="array_of_objects",
                    target_family=EVIDENCE,
                    target_id_field="evidence_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="observations",
                    shape="array_of_objects",
                    target_family=OBSERVATION,
                    target_id_field="observation_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="analyses",
                    shape="array_of_objects",
                    target_family=ANALYSIS,
                    target_id_field="analysis_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="derived_from",
                    shape="array_of_objects",
                    target_family=CASE_V2,
                    target_id_field="case_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=PATTERN,
            identity_field="pattern_id",
            supersedes=SupersedesContract(scope="family"),
            references=(
                ReferenceContract(
                    field="source_cases",
                    shape="array_of_objects",
                    target_family=CASE_V2,
                    target_id_field="case_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=HEURISTIC,
            identity_field="heuristic_id",
            supersedes=SupersedesContract(scope="family"),
            references=(
                ReferenceContract(
                    field="regression_cases",
                    shape="array_of_objects",
                    target_family=CASE_V2,
                    target_id_field="case_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=REUSE_EVENT,
            identity_field="reuse_event_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="run",
                    shape="object",
                    target_family=RUN,
                    target_id_field="run_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="pattern",
                    shape="object",
                    target_family=PATTERN,
                    target_id_field="pattern_id",
                    pin_required=True,
                ),
            ),
        ),
        # Phase 7 P7A incubation records (ADR-0010): additive pinned
        # references only. Candidate-specific semantic closure lives in the
        # evolution module and does not extend the generic graph rules.
        FamilyContract(
            schema_id=CANDIDATE_MANIFEST,
            identity_field="candidate_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="source_cases",
                    shape="array_of_objects",
                    target_family=CASE_V2,
                    target_id_field="case_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="source_patterns",
                    shape="array_of_objects",
                    target_family=PATTERN,
                    target_id_field="pattern_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=ARTIFACT_CLOSURE_RECEIPT,
            identity_field="closure_receipt_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="candidate",
                    shape="object",
                    target_family=CANDIDATE_MANIFEST,
                    target_id_field="candidate_id",
                    pin_required=True,
                ),
            ),
        ),
        # Phase 7 P7B1 preflight: the attestation pins the exact candidate,
        # its byte-closure receipt, and every source case. Outcome and
        # independence/criterion semantics stay in candidate_eligibility.py.
        FamilyContract(
            schema_id=CANDIDATE_ELIGIBILITY_ATTESTATION,
            identity_field="candidate_eligibility_attestation_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="candidate",
                    shape="object",
                    target_family=CANDIDATE_MANIFEST,
                    target_id_field="candidate_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="closure_receipt",
                    shape="object",
                    target_family=ARTIFACT_CLOSURE_RECEIPT,
                    target_id_field="closure_receipt_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="source_cases",
                    shape="array_of_objects",
                    target_family=CASE_V2,
                    target_id_field="case_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=SKILL_CANDIDATE_BUNDLE,
            identity_field="skill_candidate_bundle_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="candidate",
                    shape="object",
                    target_family=CANDIDATE_MANIFEST,
                    target_id_field="candidate_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="closure_receipt",
                    shape="object",
                    target_family=ARTIFACT_CLOSURE_RECEIPT,
                    target_id_field="closure_receipt_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="eligibility_attestation",
                    shape="object",
                    target_family=CANDIDATE_ELIGIBILITY_ATTESTATION,
                    target_id_field="candidate_eligibility_attestation_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="source_cases",
                    shape="array_of_objects",
                    target_family=CASE_V2,
                    target_id_field="case_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=SKILL_STATIC_VALIDATION_RECEIPT,
            identity_field="skill_static_validation_receipt_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="candidate_bundle",
                    shape="object",
                    target_family=SKILL_CANDIDATE_BUNDLE,
                    target_id_field="skill_candidate_bundle_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=SKILL_SEMANTIC_REVIEW_ATTESTATION,
            identity_field="skill_semantic_review_attestation_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="candidate_bundle",
                    shape="object",
                    target_family=SKILL_CANDIDATE_BUNDLE,
                    target_id_field="skill_candidate_bundle_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="static_validation_receipt",
                    shape="object",
                    target_family=SKILL_STATIC_VALIDATION_RECEIPT,
                    target_id_field="skill_static_validation_receipt_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=CONTEXT_BUNDLE,
            identity_field="context_bundle_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="candidate",
                    shape="object",
                    target_family=CANDIDATE_MANIFEST,
                    target_id_field="candidate_id",
                    pin_required=True,
                ),
            ),
        ),
        # CR8 adds plaintext-free material assessments and a governed
        # ContextBundle successor. Conditional privacy, taint and budget
        # semantics remain inside the pure in-process evolution module.
        FamilyContract(
            schema_id=CONTEXT_MATERIAL_ASSESSMENT,
            identity_field="context_material_assessment_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="candidate",
                    shape="object",
                    target_family=CANDIDATE_MANIFEST,
                    target_id_field="candidate_id",
                    pin_required=True,
                ),
            ),
        ),
        FamilyContract(
            schema_id=CONTEXT_BUNDLE_V2,
            identity_field="context_bundle_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="candidate",
                    shape="object",
                    target_family=CANDIDATE_MANIFEST,
                    target_id_field="candidate_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="assessments",
                    shape="array_of_objects",
                    target_family=CONTEXT_MATERIAL_ASSESSMENT,
                    target_id_field="context_material_assessment_id",
                    pin_required=True,
                ),
            ),
        ),
        # Correctness Reset CR6: artifact records are independent immutable
        # byte descriptors. The envelope receipt closes the existing P7A
        # candidate and pins every descriptor; the deep module validates
        # public bytes and hidden-evaluator attestations before construction.
        FamilyContract(
            schema_id=ARTIFACT_RECORD,
            identity_field="artifact_id",
            supersedes=None,
            references=(),
        ),
        FamilyContract(
            schema_id=EVALUATION_ENVELOPE_CLOSURE,
            identity_field="envelope_closure_receipt_id",
            supersedes=None,
            references=(
                ReferenceContract(
                    field="candidate",
                    shape="object",
                    target_family=CANDIDATE_MANIFEST,
                    target_id_field="candidate_id",
                    pin_required=True,
                ),
                ReferenceContract(
                    field="artifacts",
                    shape="array_of_objects",
                    target_family=ARTIFACT_RECORD,
                    target_id_field="artifact_id",
                    pin_required=True,
                ),
            ),
        ),
    )
}
