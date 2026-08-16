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
the graph fully understands it" atomic.
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
    )
}
