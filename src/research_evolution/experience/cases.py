"""Case capture builder, eligibility gate, and payload validation (M3).

ADR-0007 decision 13 lands the case builder / redactor / validator /
manifest tooling in this package. ``capture_case`` assembles a
``research-case-package/v2`` payload from already-existing member records:

- every member arrives as a payload, is validated through the core
  canonical machine, and enters the package as an ``{id, sha256}`` pin
  taken from the validated :class:`~research_evolution.core.Record` — the
  caller never hand-writes a hash, so hash copying is structurally
  impossible;
- artifact manifests are built from :class:`ArtifactInput` content whose
  hash the builder computes itself;
- there is no clock: ``created_at`` is a required argument (the E5 seed
  discipline), so identical arguments produce identical canonical bytes;
- every free-text field passes the default-deny scan before assembly, and
  any finding refuses the whole capture;
- the assembled payload is validated against its own schema before it is
  returned (the R33 lesson: check the product, not only the inputs).

The module imports only from the public face of
``research_evolution.core`` — never from adapters or from the evaluation
package — and performs no I/O of its own.
"""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
import hashlib

from ..core import Record, canonical_bytes, load_record

from .redaction import scan_for_restricted

# Expected family ids and identity fields, mirroring the frozen schema
# ``const``/required vocabulary. A unit test pins these strings equal to
# the on-disk schemas, so a schema rename breaks loudly here.
_TASK_FAMILY = "research-task/v1"
_RUN_FAMILY = "research-run/v1"
_CLAIM_FAMILY = "research-claim/v1"
_EVIDENCE_FAMILY = "research-evidence/v1"
_OBSERVATION_FAMILY = "research-failure-observation/v1"
_ANALYSIS_FAMILY = "research-failure-analysis/v1"
_CASE_FAMILY = "research-case-package/v2"

# (parameter name, expected family, identity field) for the array-shaped
# member slots, in payload order.
_ARRAY_MEMBERS = (
    ("claims", _CLAIM_FAMILY, "claim_id"),
    ("evidence", _EVIDENCE_FAMILY, "evidence_id"),
    ("observations", _OBSERVATION_FAMILY, "observation_id"),
    ("analyses", _ANALYSIS_FAMILY, "analysis_id"),
    ("derived_from", _CASE_FAMILY, "case_id"),
)


@dataclass(frozen=True)
class ArtifactInput:
    """One manifest entry: raw content plus an optional safe relative
    locator. The builder computes the hash; the hash is never copied."""

    name: str
    content: bytes
    locator: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("artifact name must be a non-blank string")
        if not isinstance(self.content, (bytes, bytearray)):
            raise ValueError("artifact content must be bytes")
        if self.locator is not None and not isinstance(self.locator, str):
            raise ValueError("artifact locator must be a string or None")


@dataclass(frozen=True)
class EligibilityInput:
    """Declarative answers to the four eligibility criteria (plan Phase 4
    task 3). The caller judges; the record names the failed criteria."""

    reproducible: bool
    source_known: bool
    sensitive_content_free: bool
    more_than_summary: bool

    def __post_init__(self) -> None:
        for field_name in (
            "reproducible",
            "source_known",
            "sensitive_content_free",
            "more_than_summary",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"eligibility answer {field_name!r} must be a bool")


# Fixed reason sentences, one per criterion, aligned with the clauses in
# the schema's eligibility description. Order is the field order above.
_INELIGIBLE_REASONS = (
    ("reproducible", "case is not reproducible"),
    ("source_known", "case source is unknown"),
    ("sensitive_content_free", "case carries unauthorized sensitive content"),
    ("more_than_summary", "case is reduced to a bare conclusion"),
)


def evaluate_eligibility(answers: EligibilityInput) -> tuple[str, tuple[str, ...]]:
    """Map declarative answers to the schema's eligibility record.

    Any False answer forces ``"ineligible"`` and contributes its fixed
    reason sentence, so an ineligible record always names at least one
    failed criterion — the reasons-when-ineligible discipline holds by
    construction (R36 ledger item 1).
    """
    if not isinstance(answers, EligibilityInput):
        raise ValueError("answers must be an EligibilityInput")
    reasons = tuple(
        sentence
        for field_name, sentence in _INELIGIBLE_REASONS
        if getattr(answers, field_name) is False
    )
    return ("eligible", ()) if not reasons else ("ineligible", reasons)


def _pin_member(
    payload: Mapping[str, Any],
    expected_family: str,
    id_field: str,
    what: str,
) -> dict[str, Any]:
    """Validate one member payload and return its ``{id, sha256}`` pin.

    Serialization goes through the core canonical machine (the R34
    lesson): a payload reloaded from a store carries ``Decimal`` values
    and only the canonical serializer writes them faithfully.
    """
    try:
        record = load_record(canonical_bytes(payload))
    except Exception as exc:
        raise ValueError(f"{what} payload is not a valid core record: {exc}")
    if record.schema_id != expected_family:
        raise ValueError(
            f"{what} payload declares {record.schema_id!r}; "
            f"expected {expected_family!r}"
        )
    return {id_field: record.data[id_field], "sha256": record.sha256}


def _manifest_entry(artifact: ArtifactInput) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": artifact.name,
        "sha256": hashlib.sha256(bytes(artifact.content)).hexdigest(),
    }
    if artifact.locator is not None:
        entry["locator"] = artifact.locator
    return entry


def _scan_facets(node: Any, field: str, findings: list[str]) -> None:
    """Recursively scan the string leaves of ``problem_signature.facets``.

    This is capture-time screening, not interpretation (R37-P3): the
    kernel still never reads facets, but restricted bytes must not ride
    them into an append-only store.
    """
    if isinstance(node, str):
        findings.extend(scan_for_restricted(node, field))
    elif isinstance(node, Mapping):
        for key, value in node.items():
            _scan_facets(value, f"{field}[{key}]", findings)
    elif isinstance(node, Sequence) and not isinstance(node, (bytes, bytearray)):
        for index, value in enumerate(node):
            _scan_facets(value, f"{field}[{index}]", findings)


def capture_case(
    *,
    case_id: str,
    title: str,
    created_at: str,
    task: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    signature_summary: str,
    signature_sha256: str,
    inputs: Sequence[ArtifactInput],
    outputs: Sequence[ArtifactInput],
    environment_tool: str,
    environment_version: str,
    privacy_review_status: str,
    export_mode: str,
    eligibility: EligibilityInput,
    source_project: str,
    decision_timeline: Sequence[tuple[str, str]],
    claims: Sequence[Mapping[str, Any]] = (),
    evidence: Sequence[Mapping[str, Any]] = (),
    observations: Sequence[Mapping[str, Any]] = (),
    analyses: Sequence[Mapping[str, Any]] = (),
    derived_from: Sequence[Mapping[str, Any]] = (),
    intermediates: Sequence[ArtifactInput] = (),
    open_questions: Sequence[str] = (),
    signature_facets: Mapping[str, Any] | None = None,
    environment_details: str | None = None,
    source_external_manifest_sha256: str | None = None,
    rights: str | None = None,
) -> dict[str, Any]:
    """Assemble one publishable ``research-case-package/v2`` payload.

    Member records (*task*, *runs*, *claims*, *evidence*, *observations*,
    *analyses*, *derived_from*) are payloads of already-existing records;
    each is validated and pinned by hash. ``signature_sha256`` is computed
    by the caller (the signature normalization rule is a caller concern);
    ``created_at`` is injected by the caller — this function has no clock.
    ``decision_timeline`` entries are ``(at, entry)`` pairs. Errors are
    plain ``ValueError`` (the evaluation-package precedent).
    """
    # 1. Default-deny scan of every free-text field, before any hashing.
    findings: list[str] = []
    findings.extend(scan_for_restricted(title, "title"))
    findings.extend(
        scan_for_restricted(signature_summary, "problem_signature.summary")
    )
    if signature_facets is not None:
        _scan_facets(signature_facets, "problem_signature.facets", findings)
    if not isinstance(eligibility, EligibilityInput):
        raise ValueError("eligibility must be an EligibilityInput")

    timeline: list[dict[str, str]] = []
    for index, item in enumerate(decision_timeline):
        try:
            at, entry = item
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"decision_timeline[{index}] must be an (at, entry) pair: {exc}"
            )
        if not isinstance(at, str) or not isinstance(entry, str):
            raise ValueError(f"decision_timeline[{index}] must hold two strings")
        findings.extend(
            scan_for_restricted(entry, f"decision_timeline[{index}].entry")
        )
        timeline.append({"at": at, "entry": entry})

    questions: list[str] = []
    for index, question in enumerate(open_questions):
        findings.extend(scan_for_restricted(question, f"open_questions[{index}]"))
        questions.append(question)

    findings.extend(scan_for_restricted(source_project, "source.project"))
    findings.extend(scan_for_restricted(environment_tool, "environment.tool"))
    findings.extend(scan_for_restricted(environment_version, "environment.version"))
    if environment_details is not None:
        findings.extend(
            scan_for_restricted(environment_details, "environment.details")
        )
    if rights is not None:
        findings.extend(scan_for_restricted(rights, "rights"))

    artifact_slots = (
        ("inputs", inputs),
        ("outputs", outputs),
        ("intermediates", intermediates),
    )
    manifests: dict[str, list[dict[str, Any]]] = {}
    for slot, artifacts in artifact_slots:
        entries: list[dict[str, Any]] = []
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, ArtifactInput):
                raise ValueError(f"{slot}[{index}] must be an ArtifactInput")
            findings.extend(
                scan_for_restricted(artifact.name, f"{slot}[{index}].name")
            )
            if artifact.locator is not None:
                findings.extend(
                    scan_for_restricted(artifact.locator, f"{slot}[{index}].locator")
                )
            entries.append(_manifest_entry(artifact))
        manifests[slot] = entries

    if findings:
        raise ValueError("restricted content refused: " + "; ".join(findings))

    # 2. Validate and pin every member record.
    task_pin = _pin_member(task, _TASK_FAMILY, "task_id", "task")
    run_pins = [
        _pin_member(run, _RUN_FAMILY, "run_id", f"runs[{index}]")
        for index, run in enumerate(runs)
    ]
    array_pins: dict[str, list[dict[str, Any]]] = {}
    member_inputs = {
        "claims": claims,
        "evidence": evidence,
        "observations": observations,
        "analyses": analyses,
        "derived_from": derived_from,
    }
    for slot, expected_family, id_field in _ARRAY_MEMBERS:
        array_pins[slot] = [
            _pin_member(
                member, expected_family, id_field, f"{slot}[{index}]"
            )
            for index, member in enumerate(member_inputs[slot])
        ]

    # 3. Assemble the payload.
    status, reasons = evaluate_eligibility(eligibility)
    signature: dict[str, Any] = {
        "summary": signature_summary,
        "signature_sha256": signature_sha256,
    }
    if signature_facets is not None:
        signature["facets"] = dict(signature_facets)
    environment_payload: dict[str, Any] = {
        "tool": environment_tool,
        "version": environment_version,
    }
    if environment_details is not None:
        environment_payload["details"] = environment_details
    source_payload: dict[str, Any] = {"project": source_project}
    if source_external_manifest_sha256 is not None:
        source_payload["external_manifest_sha256"] = source_external_manifest_sha256

    payload: dict[str, Any] = {
        "schema": _CASE_FAMILY,
        "case_id": case_id,
        "title": title,
        "task": task_pin,
        "runs": run_pins,
        "claims": array_pins["claims"],
        "evidence": array_pins["evidence"],
        "observations": array_pins["observations"],
        "analyses": array_pins["analyses"],
        "problem_signature": signature,
        "io_manifest": {
            "inputs": manifests["inputs"],
            "outputs": manifests["outputs"],
        },
        "intermediate_manifest": manifests["intermediates"],
        "decision_timeline": timeline,
        "open_questions": questions,
        "environment": environment_payload,
        "privacy_review_status": privacy_review_status,
        "export_mode": export_mode,
        "eligibility": {"status": status, "reasons": list(reasons)},
        "source": source_payload,
        "derived_from": array_pins["derived_from"],
        "created_at": created_at,
    }
    if rights is not None:
        payload["rights"] = rights

    # 4. Validate the assembled product, not just the inputs (R33): a
    # payload this function declares schema-shaped must actually be.
    try:
        load_record(canonical_bytes(payload))
    except Exception as exc:
        raise ValueError(f"assembled case payload is not a valid core record: {exc}")
    return payload


def validate_case_payload(payload: Mapping[str, Any]) -> Record:
    """Validate one ``research-case-package/v2`` payload and return the
    hash-bound Record. Malformed payloads and payloads of any other family
    raise ``ValueError``.
    """
    try:
        record = load_record(canonical_bytes(payload))
    except Exception as exc:
        raise ValueError(f"case payload is not a valid core record: {exc}")
    if record.schema_id != _CASE_FAMILY:
        raise ValueError(
            f"case payload declares {record.schema_id!r}; expected {_CASE_FAMILY!r}"
        )
    return record


def assert_case_eligible(payload: Mapping[str, Any]) -> None:
    """Fail closed unless *payload* is a valid v2 case marked eligible.

    M4's pattern distillation calls this gate before any case may
    contribute to a shareable pattern (R36 ledger item 3).
    """
    record = validate_case_payload(payload)
    eligibility = record.data["eligibility"]
    if eligibility["status"] != "eligible":
        reasons = "; ".join(eligibility["reasons"]) or "no reasons recorded"
        raise ValueError(
            f"case {record.data['case_id']!r} is ineligible: {reasons}"
        )
