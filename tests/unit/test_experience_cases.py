"""Behavioral and static-discipline tests for the M3 experience surface."""

import hashlib
import json
import re
import unittest
from pathlib import Path

from research_evolution import experience
from research_evolution.core import canonical_sha256, load_strict_json
from research_evolution.experience import (
    ArtifactInput,
    EligibilityInput,
    assert_case_eligible,
    capture_case,
    cases,
    evaluate_eligibility,
    scan_for_restricted,
    validate_case_payload,
)
from research_evolution.experience import heuristics as heuristics_module
from tests.contract.test_core_schemas_contract import _BANNED_TERMS

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIENCE_ROOT = REPO_ROOT / "src" / "research_evolution" / "experience"
CORE_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "core"
SCHEMAS = REPO_ROOT / "schemas" / "core"

# Imports the experience package must never make (ADR-0006 decision 4
# discipline applied to Phase 4 surfaces: no network, no subprocess).
_BANNED_IMPORTS = re.compile(
    r"^\s*(?:import|from)\s+"
    r"(?:socket|urllib|requests|httpx|http|ssl|subprocess|ctypes|asyncio)\b",
    re.MULTILINE,
)

# The experience package is generic infrastructure: it must not import the
# adapters or the evaluation package (the seam declared in cases.py).
_BANNED_SEAM_IMPORTS = re.compile(
    r"^\s*(?:import|from)\s+\S*(?:adapters|evaluation)\b",
    re.MULTILINE,
)


def _fixture(family: str, version: str, name: str) -> dict:
    path = CORE_FIXTURES / family / version / "valid" / name
    return load_strict_json(path.read_text(encoding="utf-8"))


def _task() -> dict:
    return _fixture("research-task", "v1", "minimal.json")


def _run() -> dict:
    return _fixture("research-run", "v1", "minimal.json")


def _case_v2() -> dict:
    return _fixture("research-case-package", "v2", "minimal.json")


def _base_kwargs() -> dict:
    return {
        "case_id": "case-m3-1",
        "title": "M3 unit test case",
        "created_at": "2026-08-17T09:05:00Z",
        "task": _task(),
        "runs": [_run()],
        "signature_summary": "Synthetic signature.",
        "signature_sha256": hashlib.sha256(b"signature").hexdigest(),
        "inputs": [ArtifactInput("input.bin", b"input-bytes")],
        "outputs": [
            ArtifactInput("output.bin", b"output-bytes", locator="artifacts/output.bin")
        ],
        "environment_tool": "unit-test",
        "environment_version": "1.0",
        "privacy_review_status": "pending",
        "export_mode": "local_full",
        "eligibility": EligibilityInput(True, True, True, True),
        "source_project": "unit-tests",
        "decision_timeline": [("2026-08-17T09:00:00Z", "Case captured.")],
    }


class RedactionScanTest(unittest.TestCase):
    def test_drive_letter_path(self) -> None:
        findings = scan_for_restricted(r"saved to C:\work\case.json", "f")
        self.assertIn("f: drive-letter path", findings)

    def test_url_scheme_is_not_a_drive_letter(self) -> None:
        # The letter-lookbehind keeps "s:/" inside "https://" from
        # misreporting as a drive letter.
        self.assertEqual(scan_for_restricted("see https://example.com/docs", "f"), ())

    def test_unc_path(self) -> None:
        findings = scan_for_restricted(r"share \\server\share\f.bin", "f")
        self.assertIn("f: UNC path", findings)

    def test_absolute_posix_path(self) -> None:
        for text in (
            "see /etc/hosts for details",
            "read /tmp then stop",
            "/var/log/x",
        ):
            with self.subTest(text=text):
                findings = scan_for_restricted(text, "f")
                self.assertIn("f: absolute POSIX path", findings)

    def test_home_relative_path(self) -> None:
        findings = scan_for_restricted("logs at ~/runs/out", "f")
        self.assertIn("f: home-relative path", findings)

    def test_email_address(self) -> None:
        findings = scan_for_restricted("contact a.b+x@example-site.com", "f")
        self.assertIn("f: email address", findings)

    def test_pem_marker(self) -> None:
        findings = scan_for_restricted("-----BEGIN PRIVATE KEY-----", "f")
        self.assertIn("f: PEM block marker", findings)

    def test_aws_style_key(self) -> None:
        findings = scan_for_restricted("key AKIAIOSFODNN7EXAMPLE inside", "f")
        self.assertIn("f: AWS-style access key id", findings)

    def test_api_token_fragment(self) -> None:
        findings = scan_for_restricted("token sk-" + "a" * 20, "f")
        self.assertIn("f: API token fragment", findings)

    def test_clean_text_passes(self) -> None:
        digest = hashlib.sha256(b"x").hexdigest()
        for text in (
            "and/or",
            "1/2",
            "ratio 1:2",
            f"pinned at {digest}",
            "https://example.com/docs",
            "artifacts/input.bin",
            "./rel/path.bin",
        ):
            with self.subTest(text=text):
                self.assertEqual(scan_for_restricted(text, "f"), ())

    def test_findings_aggregate_with_provenance(self) -> None:
        findings = scan_for_restricted("mail a@b.com about /etc/hosts", "field9")
        self.assertEqual(
            findings,
            ("field9: absolute POSIX path", "field9: email address"),
        )

    def test_non_string_refused(self) -> None:
        for bad in (b"bytes", 5, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    scan_for_restricted(bad, "f")


class EligibilityTest(unittest.TestCase):
    def test_all_true_is_eligible(self) -> None:
        status, reasons = evaluate_eligibility(EligibilityInput(True, True, True, True))
        self.assertEqual(status, "eligible")
        self.assertEqual(reasons, ())

    def test_each_false_names_its_criterion(self) -> None:
        names = (
            "reproducible",
            "source_known",
            "sensitive_content_free",
            "more_than_summary",
        )
        expected = {
            "reproducible": "case is not reproducible",
            "source_known": "case source is unknown",
            "sensitive_content_free": "case carries unauthorized sensitive content",
            "more_than_summary": "case is reduced to a bare conclusion",
        }
        for field_name, sentence in expected.items():
            with self.subTest(field=field_name):
                answers = EligibilityInput(
                    **{name: name != field_name for name in names}
                )
                status, reasons = evaluate_eligibility(answers)
                self.assertEqual(status, "ineligible")
                self.assertEqual(reasons, (sentence,))

    def test_all_false_lists_four_reasons_in_order(self) -> None:
        status, reasons = evaluate_eligibility(
            EligibilityInput(False, False, False, False)
        )
        self.assertEqual(status, "ineligible")
        self.assertEqual(
            reasons,
            (
                "case is not reproducible",
                "case source is unknown",
                "case carries unauthorized sensitive content",
                "case is reduced to a bare conclusion",
            ),
        )

    def test_non_bool_answers_refused(self) -> None:
        for bad in (1, "yes", None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    EligibilityInput(bad, True, True, True)

    def test_non_input_refused(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_eligibility({"reproducible": True})


class CaptureCaseTest(unittest.TestCase):
    def test_minimal_happy_path_and_pins(self) -> None:
        kwargs = _base_kwargs()
        payload = capture_case(**kwargs)
        record = validate_case_payload(payload)
        self.assertEqual(record.schema_id, "research-case-package/v2")
        self.assertEqual(record.sha256, canonical_sha256(payload))
        self.assertEqual(
            payload["task"],
            {"task_id": _task()["task_id"], "sha256": canonical_sha256(_task())},
        )
        self.assertEqual(
            payload["runs"],
            [{"run_id": _run()["run_id"], "sha256": canonical_sha256(_run())}],
        )
        self.assertEqual(payload["claims"], [])
        self.assertEqual(payload["derived_from"], [])
        self.assertEqual(payload["eligibility"], {"status": "eligible", "reasons": []})
        self.assertNotIn("rights", payload)

    def test_full_optional_fields(self) -> None:
        members = {
            "claims": [_fixture("research-claim", "v1", "minimal.json")],
            "evidence": [_fixture("research-evidence", "v1", "minimal.json")],
            "observations": [
                _fixture("research-failure-observation", "v1", "minimal.json")
            ],
            "analyses": [_fixture("research-failure-analysis", "v1", "minimal.json")],
            "derived_from": [_case_v2()],
        }
        kwargs = _base_kwargs()
        kwargs.update(
            members,
            intermediates=[ArtifactInput("checkpoint.bin", b"ckpt", "artifacts/checkpoint.bin")],
            open_questions=["Does it scale?"],
            signature_facets={"area": "general"},
            environment_details="Interpreter 3.14.5, single machine.",
            source_external_manifest_sha256=hashlib.sha256(b"ext").hexdigest(),
            rights="Synthetic content.",
        )
        payload = capture_case(**kwargs)
        validate_case_payload(payload)
        for slot, id_field in (
            ("claims", "claim_id"),
            ("evidence", "evidence_id"),
            ("observations", "observation_id"),
            ("analyses", "analysis_id"),
        ):
            with self.subTest(slot=slot):
                member = members[slot][0]
                self.assertEqual(
                    payload[slot],
                    [{id_field: member[id_field], "sha256": canonical_sha256(member)}],
                )
        self.assertEqual(
            payload["derived_from"],
            [{"case_id": "case-v2-minimal", "sha256": canonical_sha256(_case_v2())}],
        )
        self.assertEqual(payload["problem_signature"]["facets"], {"area": "general"})
        self.assertEqual(payload["rights"], "Synthetic content.")
        self.assertEqual(payload["open_questions"], ["Does it scale?"])
        self.assertEqual(
            payload["environment"]["details"], "Interpreter 3.14.5, single machine."
        )
        self.assertEqual(
            payload["source"]["external_manifest_sha256"],
            hashlib.sha256(b"ext").hexdigest(),
        )
        self.assertEqual(
            payload["intermediate_manifest"],
            [
                {
                    "name": "checkpoint.bin",
                    "sha256": hashlib.sha256(b"ckpt").hexdigest(),
                    "locator": "artifacts/checkpoint.bin",
                }
            ],
        )

    def test_member_family_mismatch_refused(self) -> None:
        kwargs = _base_kwargs()
        kwargs["claims"] = [_run()]
        with self.assertRaisesRegex(ValueError, "research-claim/v1"):
            capture_case(**kwargs)
        kwargs = _base_kwargs()
        kwargs["task"] = _run()
        with self.assertRaisesRegex(ValueError, "research-task/v1"):
            capture_case(**kwargs)

    def test_derived_from_rejects_v1(self) -> None:
        kwargs = _base_kwargs()
        kwargs["derived_from"] = [_fixture("research-case-package", "v1", "minimal.json")]
        with self.assertRaisesRegex(ValueError, "research-case-package/v2"):
            capture_case(**kwargs)

    def test_invalid_member_payload_refused(self) -> None:
        kwargs = _base_kwargs()
        kwargs["task"] = {"schema": "research-task/v1"}
        with self.assertRaisesRegex(ValueError, "task payload is not a valid"):
            capture_case(**kwargs)

    def test_restricted_content_refused(self) -> None:
        variants = {
            "title": {"title": r"Saved to C:\work\case.json"},
            "summary": {"signature_summary": "see /etc/hosts"},
            "timeline": {
                "decision_timeline": [("2026-08-17T09:00:00Z", "mail a@b.com now")]
            },
            "open_questions": {"open_questions": ["token sk-" + "a" * 20 + " leaked?"]},
            "source_project": {"source_project": r"repo at \\server\share"},
            "environment_tool": {"environment_tool": "C:/evil/tool"},
            "environment_version": {"environment_version": "/tmp/1.0"},
            "environment_details": {"environment_details": "see ~/logs"},
            "signature_facets": {"signature_facets": {"note": "/etc/passwd"}},
            "rights": {"rights": "uses AKIAIOSFODNN7EXAMPLE"},
            "artifact_name": {"inputs": [ArtifactInput("~/secret.bin", b"x")]},
            "artifact_locator": {
                "outputs": [ArtifactInput("out.bin", b"x", "/abs/out.bin")]
            },
        }
        for name, override in variants.items():
            with self.subTest(field=name):
                kwargs = _base_kwargs()
                kwargs.update(override)
                with self.assertRaisesRegex(ValueError, "restricted content refused"):
                    capture_case(**kwargs)

    def test_facets_leaf_scan_provenance(self) -> None:
        # Nested string leaves are screened with their full path named in
        # the finding (R37-P3); the kernel still never interprets facets.
        kwargs = _base_kwargs()
        kwargs["signature_facets"] = {"outer": {"inner": "~/x"}}
        with self.assertRaisesRegex(
            ValueError,
            r"problem_signature\.facets\[outer\]\[inner\]: home-relative path",
        ):
            capture_case(**kwargs)

    def test_artifact_hash_and_locator(self) -> None:
        kwargs = _base_kwargs()
        kwargs["inputs"] = [ArtifactInput("hello.txt", b"hello")]
        payload = capture_case(**kwargs)
        entry = payload["io_manifest"]["inputs"][0]
        self.assertEqual(entry["sha256"], hashlib.sha256(b"hello").hexdigest())
        self.assertNotIn("locator", entry)
        self.assertEqual(
            payload["io_manifest"]["outputs"][0]["locator"], "artifacts/output.bin"
        )

    def test_assembled_output_self_validates(self) -> None:
        kwargs = _base_kwargs()
        kwargs["created_at"] = "not-a-date"
        with self.assertRaisesRegex(ValueError, "assembled case payload"):
            capture_case(**kwargs)
        kwargs = _base_kwargs()
        kwargs["export_mode"] = "bogus"
        with self.assertRaisesRegex(ValueError, "assembled case payload"):
            capture_case(**kwargs)

    def test_determinism(self) -> None:
        first = capture_case(**_base_kwargs())
        second = capture_case(**_base_kwargs())
        self.assertEqual(first, second)
        self.assertEqual(canonical_sha256(first), canonical_sha256(second))

    def test_eligibility_wired_into_payload(self) -> None:
        kwargs = _base_kwargs()
        kwargs["eligibility"] = EligibilityInput(False, True, True, False)
        payload = capture_case(**kwargs)
        self.assertEqual(
            payload["eligibility"],
            {
                "status": "ineligible",
                "reasons": [
                    "case is not reproducible",
                    "case is reduced to a bare conclusion",
                ],
            },
        )

    def test_timeline_entry_shape(self) -> None:
        kwargs = _base_kwargs()
        kwargs["decision_timeline"] = [("2026-08-17T09:00:00Z",)]
        with self.assertRaisesRegex(ValueError, "decision_timeline"):
            capture_case(**kwargs)
        kwargs = _base_kwargs()
        kwargs["decision_timeline"] = [("2026-08-17T09:00:00Z", 5)]
        with self.assertRaisesRegex(ValueError, "decision_timeline"):
            capture_case(**kwargs)


class EligibilityGateTest(unittest.TestCase):
    def test_assert_case_eligible_passes(self) -> None:
        payload = capture_case(**_base_kwargs())
        self.assertIsNone(assert_case_eligible(payload))

    def test_assert_case_eligible_refuses_ineligible(self) -> None:
        kwargs = _base_kwargs()
        kwargs["eligibility"] = EligibilityInput(True, False, True, True)
        payload = capture_case(**kwargs)
        with self.assertRaisesRegex(ValueError, "case source is unknown"):
            assert_case_eligible(payload)

    def test_assert_case_eligible_refuses_other_family(self) -> None:
        with self.assertRaisesRegex(ValueError, "research-case-package/v2"):
            assert_case_eligible(_task())

    def test_validate_case_payload(self) -> None:
        payload = capture_case(**_base_kwargs())
        record = validate_case_payload(payload)
        self.assertEqual(record.data["case_id"], "case-m3-1")
        with self.assertRaisesRegex(ValueError, "declares"):
            validate_case_payload(_task())
        with self.assertRaisesRegex(ValueError, "not a valid core record"):
            validate_case_payload({"schema": "research-case-package/v2"})


class FamilyConstantsTest(unittest.TestCase):
    def test_family_constants_match_schema_consts(self) -> None:
        expected = (
            ("research-task-v1.schema.json", cases._TASK_FAMILY),
            ("research-run-v1.schema.json", cases._RUN_FAMILY),
            ("research-claim-v1.schema.json", cases._CLAIM_FAMILY),
            ("research-evidence-v1.schema.json", cases._EVIDENCE_FAMILY),
            ("research-failure-observation-v1.schema.json", cases._OBSERVATION_FAMILY),
            ("research-failure-analysis-v1.schema.json", cases._ANALYSIS_FAMILY),
            ("research-case-package-v2.schema.json", cases._CASE_FAMILY),
            ("heuristic-v1.schema.json", heuristics_module._HEURISTIC_FAMILY),
        )
        for filename, constant in expected:
            with self.subTest(schema=filename):
                schema = json.loads((SCHEMAS / filename).read_text(encoding="utf-8"))
                self.assertEqual(schema["properties"]["schema"]["const"], constant)


class ExperienceStaticDisciplineTest(unittest.TestCase):
    def test_experience_package_makes_no_banned_imports(self) -> None:
        for path in sorted(EXPERIENCE_ROOT.glob("*.py")):
            with self.subTest(module=path.name):
                match = _BANNED_IMPORTS.search(path.read_text(encoding="utf-8"))
                self.assertIsNone(match)

    def test_experience_package_is_domain_neutral(self) -> None:
        # The experience surface is generic infrastructure, not an adapter:
        # the core domain-neutrality discipline (tests/contract
        # _BANNED_TERMS) applies.
        for path in sorted(EXPERIENCE_ROOT.glob("*.py")):
            with self.subTest(module=path.name):
                match = _BANNED_TERMS.search(path.read_text(encoding="utf-8"))
                self.assertIsNone(match)

    def test_experience_package_imports_no_adapters_or_evaluation(self) -> None:
        for path in sorted(EXPERIENCE_ROOT.glob("*.py")):
            with self.subTest(module=path.name):
                match = _BANNED_SEAM_IMPORTS.search(path.read_text(encoding="utf-8"))
                self.assertIsNone(match)

    def test_public_face_is_pinned(self) -> None:
        self.assertEqual(
            experience.__all__,
            sorted(
                [
                    "ArtifactInput",
                    "Cluster",
                    "EligibilityInput",
                    "HeuristicIndex",
                    "LintFinding",
                    "LintReport",
                    "PatternCandidate",
                    "PatternIndex",
                    "RetrievalResult",
                    "ShadowReport",
                    "SingletonAttestation",
                    "TIERS",
                    "Taxonomy",
                    "append_cluster_event",
                    "assert_case_eligible",
                    "assert_no_promoted_skill",
                    "assert_registry_clean",
                    "build_heuristic_index",
                    "build_pattern_index",
                    "capture_case",
                    "cluster_cases",
                    "compose_taxonomy",
                    "distill_patterns",
                    "evaluate_eligibility",
                    "heuristic_chain",
                    "lint_heuristics",
                    "load_taxonomy",
                    "pattern_chain",
                    "propose_heuristic",
                    "record_reuse_outcome",
                    "record_shadow_report",
                    "retrieve_patterns",
                    "reuse_summary",
                    "scan_for_restricted",
                    "transition_heuristic",
                    "transition_pattern",
                    "validate_case_payload",
                    "verify_cluster_log",
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
