"""M6: qualification evidence pack (plan Phase 4 task 20; ADR-0007 decision 12).

The pack under ``staging/research-memory/`` is built entirely through the
public experience face with fixed, caller-injected timestamps.  The Phase 4
Math/Quant qualification bytes remain unchanged; Phase 5 L6 appends a
separately built ML subtree containing case, pattern, heuristic, lint, and
shadow evidence:

- per domain (math, quant): three eligible ``research-case-package/v2``
  payloads via :func:`capture_case`, two candidate patterns via
  :func:`distill_patterns` + :func:`transition_pattern` (pattern A from a
  shared-fingerprint pair, pattern B from a cross-signature pair with an
  explicit merged signature — the caller-judgment path);
- one correct abstain: a retrieval session whose frozen signature shares
  no fingerprint, facet, or summary token with any registered pattern,
  which must end in an explicit ``abstained`` result (task 20's "未找到适
  用模式" obligation).

Every payload here is SYNTHETIC de-identified data (ADR-0005 decision 9
precedent): no real project content, paths, or identities. The tree is
deterministic — this test rebuilds every artifact byte-for-byte and
re-checks the manifest, so the on-disk pack can never drift from the
machinery that produced it.
"""

import hashlib
import json
import unittest
from pathlib import Path

from research_evolution.core import canonical_bytes, canonical_sha256, load_record
from research_evolution.experience import (
    ArtifactInput,
    EligibilityInput,
    capture_case,
    distill_patterns,
    retrieve_patterns,
    transition_pattern,
)
from tests.unit.test_experience_cases import _run, _task
from tests.integration._ml_research_memory_pack import (
    build_ml_research_memory_pack,
)

STAGING = Path(__file__).resolve().parents[2] / "staging" / "research-memory"

_CREATED = "2026-08-18T09:00:00Z"
_DISTILLED_AT = "2026-08-18T10:00:00Z"
_PROMOTED_AT = "2026-08-18T11:00:00Z"
_QUERY_AT = "2026-08-18T12:00:00Z"
_L6_AT = "2026-08-21T13:00:00Z"

# Domain vocabularies deliberately avoid every _BANNED_TERMS token even
# though staging data is outside the static scan surface.
_DOMAINS = {
    "math": {
        "sig_a_summary": "synthetic math lemma boundary hypothesis check skipped",
        "sig_a_bytes": b"math-sig-a",
        "sig_b_summary": "synthetic math counterexample search stopped early",
        "sig_b_bytes": b"math-sig-b",
        "merged_summary": "synthetic math merged premature termination signature",
        "merged_bytes": b"math-sig-merged",
        "scope": "synthetic math review",
        "tactic_a": "check every lemma boundary hypothesis before reuse",
        "tactic_b": "bound the counterexample search budget before stopping",
    },
    "quant": {
        "sig_a_summary": "synthetic quant baseline parity check skipped",
        "sig_a_bytes": b"quant-sig-c",
        "sig_b_summary": "synthetic quant seed sweep collapsed early",
        "sig_b_bytes": b"quant-sig-d",
        "merged_summary": "synthetic quant merged premature conclusion signature",
        "merged_bytes": b"quant-sig-merged",
        "scope": "synthetic quant review",
        "tactic_a": "run the baseline parity check before any comparison",
        "tactic_b": "complete the full seed sweep before concluding",
    },
}

# The abstain query shares no token with any pattern vocabulary above.
_ABSTAIN_SUMMARY = "zzzq xwvj klmno pqrstu"
_ABSTAIN_BYTES = b"abstain-query-sig"


def _evidence_case(domain: str, index: int, summary: str, sig: bytes) -> dict:
    return capture_case(
        case_id=f"case-{domain}-{index}",
        title=f"Synthetic {domain} qualification case {index}",
        created_at=_CREATED,
        task=_task(),
        runs=[_run()],
        signature_summary=summary,
        signature_sha256=hashlib.sha256(sig).hexdigest(),
        inputs=[ArtifactInput("input.bin", f"{domain}-{index}-in".encode())],
        outputs=[
            ArtifactInput(
                "output.bin",
                f"{domain}-{index}-out".encode(),
                locator=f"artifacts/{domain}-{index}/output.bin",
            )
        ],
        environment_tool="evidence-builder",
        environment_version="1.0",
        privacy_review_status="pending",
        export_mode="local_full",
        eligibility=EligibilityInput(True, True, True, True),
        source_project="synthetic-evidence",
        decision_timeline=[(_CREATED, "Synthetic qualification case captured.")],
    )


def _evidence_patterns(domain: str, cases: list) -> dict:
    spec = _DOMAINS[domain]
    common = {
        "created_at": _DISTILLED_AT,
        "last_validated": _DISTILLED_AT,
        "scope": spec["scope"],
        "evidence_grade": "synthetic",
        "evidence_rationale": "synthetic de-identified qualification evidence",
        "confidence": "low",
        "preconditions": ["synthetic precondition holds"],
        "contraindications": ["do not apply outside the synthetic review scope"],
        "failed_tactics": ["skipping the check entirely"],
        "transition_rationale": "initial distillation",
    }
    distilled_a = distill_patterns(
        cases=cases[:2],
        pattern_id=f"pat-{domain}-a",
        successful_tactics=[spec["tactic_a"]],
        **common,
    )
    distilled_b = distill_patterns(
        cases=cases[1:],
        pattern_id=f"pat-{domain}-b",
        successful_tactics=[spec["tactic_b"]],
        signature_summary=spec["merged_summary"],
        signature_sha256=hashlib.sha256(spec["merged_bytes"]).hexdigest(),
        **common,
    )
    candidate_a = transition_pattern(
        pattern=distilled_a,
        new_pattern_id=f"pat-{domain}-a-v2",
        status="candidate_pattern",
        transition_rationale=(
            "two independent synthetic cases share the exact signature "
            "fingerprint; promoted to candidate per task 9 multi-case rule"
        ),
        created_at=_PROMOTED_AT,
        last_validated=_PROMOTED_AT,
    )
    candidate_b = transition_pattern(
        pattern=distilled_b,
        new_pattern_id=f"pat-{domain}-b-v2",
        status="candidate_pattern",
        transition_rationale=(
            "two independent synthetic cases distilled under an explicit "
            "merged signature; promoted to candidate per task 9 multi-case rule"
        ),
        created_at=_PROMOTED_AT,
        last_validated=_PROMOTED_AT,
    )
    return {
        "a": (distilled_a, candidate_a),
        "b": (distilled_b, candidate_b),
    }


def build_evidence_pack() -> dict:
    """Rebuild the full pack deterministically; returns the file map."""
    files: dict[str, bytes] = {}
    candidate_tips: list[dict] = []
    for domain in ("math", "quant"):
        spec = _DOMAINS[domain]
        cases = [
            _evidence_case(domain, 1, spec["sig_a_summary"], spec["sig_a_bytes"]),
            _evidence_case(domain, 2, spec["sig_a_summary"], spec["sig_a_bytes"]),
            _evidence_case(domain, 3, spec["sig_b_summary"], spec["sig_b_bytes"]),
        ]
        for index, case in enumerate(cases, start=1):
            files[f"evidence/{domain}/case-{domain}-{index}.json"] = canonical_bytes(case)
        patterns = _evidence_patterns(domain, cases)
        for label in ("a", "b"):
            distilled, candidate = patterns[label]
            files[f"evidence/{domain}/pattern-{domain}-{label}-v1.json"] = canonical_bytes(distilled)
            files[f"evidence/{domain}/pattern-{domain}-{label}-v2.json"] = canonical_bytes(candidate)
            candidate_tips.append(candidate)
    abstain = retrieve_patterns(
        signature_summary=_ABSTAIN_SUMMARY,
        signature_sha256=hashlib.sha256(_ABSTAIN_BYTES).hexdigest(),
        patterns=candidate_tips,
        recorded_at=_QUERY_AT,
    )
    files["evidence/abstain/retrieval-session.json"] = canonical_bytes(
        abstain.session_entry
    )
    ml = build_ml_research_memory_pack()
    files.update(ml["files"])
    manifest = {
        "kind": "research-memory-evidence-manifest",
        "generated_at": _L6_AT,
        "synthetic": True,
        "domains": {
            **{
                domain: {"cases": 3, "candidate_patterns": 2}
                for domain in _DOMAINS
            },
            "ml": {
                "cases": 4,
                "candidate_patterns": 1,
                "shadow_heuristics": 3,
            },
        },
        "abstain_sessions": 1,
        "shadow_reports": 1,
        "files": {
            path: hashlib.sha256(content).hexdigest()
            for path, content in sorted(files.items())
        },
    }
    files["manifest.json"] = canonical_bytes(manifest)
    return {
        "files": files,
        "abstain": abstain,
        "candidate_tips": candidate_tips,
        "ml": ml,
    }


class EvidencePackIntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.built = build_evidence_pack()

    def test_tree_matches_rebuild_byte_for_byte(self) -> None:
        files = self.built["files"]
        on_disk = {
            path.relative_to(STAGING).as_posix(): path.read_bytes()
            for path in sorted(STAGING.rglob("*.json"))
        }
        self.assertEqual(set(on_disk), set(files))
        for path, content in files.items():
            with self.subTest(path=path):
                self.assertEqual(on_disk[path], content, path)

    def test_manifest_hashes_match_file_bytes(self) -> None:
        manifest_data = json.loads((STAGING / "manifest.json").read_text(encoding="utf-8"))
        for path, expected in manifest_data["files"].items():
            with self.subTest(path=path):
                actual = hashlib.sha256((STAGING / path).read_bytes()).hexdigest()
                self.assertEqual(actual, expected, path)

    def test_every_payload_is_a_valid_record_or_session(self) -> None:
        for path in sorted(STAGING.rglob("*.json")):
            relative = path.relative_to(STAGING).as_posix()
            if path.name in ("manifest.json", "retrieval-session.json"):
                continue
            if relative.startswith("evidence/ml/captures/"):
                continue
            if relative.startswith("evidence/ml/shadow/"):
                continue
            with self.subTest(path=path.name):
                load_record(path.read_bytes())

    def test_qualification_counts_per_domain(self) -> None:
        for domain in ("math", "quant"):
            with self.subTest(domain=domain):
                cases = list((STAGING / "evidence" / domain).glob("case-*.json"))
                candidates = list(
                    (STAGING / "evidence" / domain).glob("pattern-*-v2.json")
                )
                self.assertGreaterEqual(len(cases), 3)
                self.assertGreaterEqual(len(candidates), 2)
                for path in cases:
                    record = load_record(path.read_bytes())
                    self.assertEqual(record.data["eligibility"]["status"], "eligible")
                for path in candidates:
                    record = load_record(path.read_bytes())
                    self.assertEqual(record.data["status"], "candidate_pattern")
                    self.assertGreaterEqual(len(record.data["source_cases"]), 2)

    def test_abstain_is_explicit(self) -> None:
        abstain = self.built["abstain"]
        self.assertTrue(abstain.abstained)
        self.assertEqual(abstain.candidates, ())
        self.assertEqual(
            abstain.session_sha256, canonical_sha256(abstain.session_entry)
        )

    def test_staging_area_is_not_a_skill_root(self) -> None:
        # The staging subtree holds no installable unit, and no path
        # component places it inside an auto-discovery skills/ root
        # (ADR-0007 decision 10, gate 10 applied to this repo).
        self.assertEqual(list(STAGING.rglob("SKILL.md")), [])
        self.assertNotIn("skills", STAGING.parts)


if __name__ == "__main__":
    unittest.main()
