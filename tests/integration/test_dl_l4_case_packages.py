"""Phase 6 L4 synthetic failures/comparison captured as Case Packages."""

import copy
import hashlib
import unittest
from pathlib import Path

from research_evolution.adapters.deep_learning.runner import DLRunnerError, run_fixture
from research_evolution.adapters.deep_learning.studies import build_fixture_study_report
from research_evolution.core import canonical_bytes, canonical_sha256, load_record
from research_evolution.experience.cases import (
    ArtifactInput,
    EligibilityInput,
    assert_case_eligible,
    capture_case,
    validate_case_payload,
)
from tests.unit.test_dl_runner_l3 import (
    _fixture as _l3_fixture,
    _manifest as _l3_manifest,
    _resume_manifest,
    _selected_payload,
)
from tests.unit.test_dl_studies import (
    _compute_evidence,
    _fixture,
    _manifest,
    _plan,
)

CREATED_AT = "2026-08-23T16:00:00Z"
REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_BYTES = (
    REPO_ROOT / "benchmarks" / "public" / "dl-adapter" / "catalog.json"
).read_bytes().replace(b"\r\n", b"\n")
CATALOG_SHA256 = hashlib.sha256(CATALOG_BYTES).hexdigest()


def _validated(payload: dict) -> dict:
    return load_record(canonical_bytes(payload)).data


def _outcomes() -> dict[str, dict]:
    failures = {}
    for kind in ("oom", "nan", "interrupt"):
        result = run_fixture(
            _manifest(f"case-package-{kind}", "study-case-package-failures"),
            _fixture(
                1,
                hidden_units=3,
                requested_steps=6,
                early_stopping=False,
                failure=kind,
            ),
        )
        failures[kind] = result.artifact
    partial = run_fixture(
        _l3_manifest("case-package-recovery-source"),
        _l3_fixture(requested_steps=4),
    )
    tampered = copy.deepcopy(_selected_payload(partial))
    tampered["model_state"]["output_bias"] = 999
    try:
        run_fixture(
            _resume_manifest("case-package-recovery-resume", partial),
            _l3_fixture(requested_steps=8),
            checkpoint_payload=tampered,
        )
    except DLRunnerError as exc:
        if "content hash" not in str(exc):
            raise
        failures["recovery-failure"] = {
            "schema": "synthetic-dl-recovery-rejection/v1",
            "status": "rejected",
            "rule": "checkpoint-content-hash-mismatch",
            "evidence_scope": "synthetic_engineering",
            "checkpoint_payload_retained": False,
        }
    else:
        raise AssertionError("tampered checkpoint was unexpectedly accepted")
    failures["compute-matched"] = build_fixture_study_report(
        _plan("compute_matched"), _compute_evidence()
    ).artifact
    return failures


def _case_package(slug: str, outcome: dict) -> dict:
    task_id = f"task-dl-l4-{slug}"
    task = _validated(
        {
            "schema": "research-task/v1",
            "task_id": task_id,
            "title": f"Synthetic DL L4 {slug} acceptance",
            "problem_statement": (
                "Capture one deterministic synthetic DL governance outcome "
                "without promoting it to real execution evidence."
            ),
            "domain": "engineering",
            "scope": {
                "time_range": "2026-08-23",
                "data": "bounded synthetic fixture only",
            },
            "resources": {"compute": "standard-library-cpu", "budget_minutes": 5},
            "completion_criteria": [
                "The outcome and its limitations are hash-bound in a Case Package."
            ],
            "permissions": ["read:repo"],
            "allowed_external_effects": [],
            "created_at": CREATED_AT,
        }
    )
    outcome_bytes = canonical_bytes(outcome)
    run = _validated(
        {
            "schema": "research-run/v1",
            "run_id": f"run-dl-l4-{slug}",
            "task": {"task_id": task_id, "sha256": canonical_sha256(task)},
            "executor": {"tool": "reference-dl-l4-case-builder", "version": "0.1.0"},
            "environment": [
                {"name": "execution-envelope", "version": "synthetic-cpu-only"}
            ],
            "inputs": [
                {
                    "name": "public DL L4 catalog",
                    "kind": "case",
                    "sha256": CATALOG_SHA256,
                }
            ],
            "randomness": {"mode": "fixed_seed", "seed": 1},
            "started_at": CREATED_AT,
            "completed_at": CREATED_AT,
        }
    )
    claim_id = f"claim-dl-l4-{slug}"
    evidence = _validated(
        {
            "schema": "research-evidence/v1",
            "evidence_id": f"evidence-dl-l4-{slug}",
            "claim_ids": [claim_id],
            "producer": {"tool": "reference-dl-l4-case-builder", "version": "0.1.0"},
            "inputs": [
                {
                    "name": "synthetic outcome",
                    "kind": "other",
                    "sha256": hashlib.sha256(outcome_bytes).hexdigest(),
                }
            ],
            "generated_at": CREATED_AT,
            "content_sha256": hashlib.sha256(outcome_bytes).hexdigest(),
            "applicability": "Synthetic DL governance engineering behavior only.",
            "evidence_level": "engineering-only",
            "limitations": [
                "No real framework, GPU, dataset, outage, or scheduler was observed."
            ],
        }
    )
    claim = _validated(
        {
            "schema": "research-claim/v1",
            "claim_id": claim_id,
            "claim_type": "engineering_claim",
            "statement": f"The synthetic {slug} governance scenario is reproducible.",
            "scope": "The exact bounded Phase 6 L4 synthetic artifact only.",
            "disposition": "supported",
            "evidence_maturity": "engineering_verified",
            "supporting_evidence": [
                {
                    "evidence_id": evidence["evidence_id"],
                    "sha256": canonical_sha256(evidence),
                }
            ],
            "limitations": ["The claim is limited to deterministic protocol behavior."],
            "non_entailments": [
                "Does not establish real OOM, preemption, recovery, model quality, or GPU support."
            ],
            "created_at": CREATED_AT,
        }
    )
    return capture_case(
        case_id=f"case-dl-l4-{slug}",
        title=f"Synthetic DL L4 case: {slug}",
        created_at=CREATED_AT,
        task=task,
        runs=[run],
        claims=[claim],
        evidence=[evidence],
        signature_summary=f"Synthetic DL governance scenario {slug}.",
        signature_sha256=hashlib.sha256(slug.encode("utf-8")).hexdigest(),
        signature_facets={"domain": "ml-dl-governance", "category": slug},
        inputs=[ArtifactInput("catalog.json", CATALOG_BYTES)],
        outputs=[ArtifactInput("outcome.json", outcome_bytes)],
        environment_tool="reference-dl-l4-case-builder",
        environment_version="0.1.0",
        environment_details="Deterministic in-memory synthetic CPU protocol machine.",
        privacy_review_status="passed",
        export_mode="benchmark_candidate",
        eligibility=EligibilityInput(True, True, True, True),
        source_project="phase6-l4-synthetic",
        decision_timeline=[
            (CREATED_AT, "The synthetic protocol and expected outcome were frozen."),
            (CREATED_AT, "The outcome was captured without promotion."),
        ],
        open_questions=[
            "How does this protocol behave under an authorized real framework and hardware study?"
        ],
    )


class DLL4CasePackageTest(unittest.TestCase):
    def test_five_required_scenarios_form_eligible_case_packages(self) -> None:
        outcomes = _outcomes()
        self.assertEqual(
            set(outcomes),
            {"oom", "nan", "interrupt", "recovery-failure", "compute-matched"},
        )
        packages = {slug: _case_package(slug, outcome) for slug, outcome in outcomes.items()}
        for payload in packages.values():
            self.assertEqual(validate_case_payload(payload).schema_id, "research-case-package/v2")
            self.assertIsNone(assert_case_eligible(payload))
            self.assertEqual(payload["eligibility"]["status"], "eligible")
            self.assertEqual(payload["privacy_review_status"], "passed")

        first = {slug: canonical_sha256(payload) for slug, payload in packages.items()}
        second = {
            slug: canonical_sha256(_case_package(slug, outcome))
            for slug, outcome in outcomes.items()
        }
        self.assertEqual(first, second)

    def test_case_packages_hash_outputs_without_embedding_checkpoint_payloads(self) -> None:
        packages = [_case_package(slug, outcome) for slug, outcome in _outcomes().items()]
        encoded = canonical_bytes(packages).decode("utf-8")
        self.assertNotIn("model_state", encoded)
        self.assertNotIn("input_weights", encoded)
        self.assertNotIn('"optimizer_state":', encoded)


if __name__ == "__main__":
    unittest.main()
