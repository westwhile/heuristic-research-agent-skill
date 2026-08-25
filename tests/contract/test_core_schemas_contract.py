"""Contract tests: fixtures, schema integrity, and domain neutrality.

These tests pin the public contract of the core kernel (Phase 1A–1D, the
Phase 3 E2 evaluation record families, and the Phase 4 M2 research memory
families):

- the fixture tree on disk and FIXTURE_MANIFEST are compared
  bidirectionally, so an unlisted family/version directory or stray file is a
  test failure;
- every ``valid`` fixture loads; every ``invalid`` fixture raises the
  expected error class with the expected reason substring;
- the canonical hash of every family's minimal fixture is golden-pinned;
- every schema file's raw on-disk bytes are golden-pinned
  (SCHEMA_TEXT_SHA256, ADR-0004 decision 7; newline stability carried by
  .gitattributes);
- schema files are strict JSON, self-consistent, and free of domain vocabulary.
"""

import hashlib
import re
import unittest
from pathlib import Path

from research_evolution.core import (
    CoreError,
    RecordValidationError,
    SchemaDefinitionError,
    StrictJsonError,
    UnknownSchemaError,
    load_record,
)
from research_evolution.core._schema import SchemaRegistry

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "core"
SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "core"

_ERROR_CLASSES = {
    "StrictJsonError": StrictJsonError,
    "UnknownSchemaError": UnknownSchemaError,
    "RecordValidationError": RecordValidationError,
    "SchemaDefinitionError": SchemaDefinitionError,
}

# invalid fixture name -> (expected error class, expected reason substring).
FIXTURE_MANIFEST = {
    "research-task/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-created-at-month.json": ("RecordValidationError", "created_at"),
            "bad-created-at.json": ("RecordValidationError", "created_at"),
            "bad-id-pattern.json": ("RecordValidationError", "task_id"),
            "duplicate-nested-key.json": ("StrictJsonError", "duplicate"),
            "duplicate-top-level-key.json": ("StrictJsonError", "duplicate"),
            "empty-completion-criteria.json": (
                "RecordValidationError",
                "completion_criteria",
            ),
            "missing-task-id.json": ("RecordValidationError", "task_id"),
            "nan-literal.json": ("StrictJsonError", "non-finite"),
            "number-scale-overflow.json": ("StrictJsonError", "decimal scale"),
            "top-level-array.json": ("StrictJsonError", "top-level"),
            "unicode-digit-exponent.json": ("StrictJsonError", "invalid number"),
            "unicode-digit-fraction.json": ("StrictJsonError", "invalid number"),
            "unicode-digit-integer.json": ("StrictJsonError", "invalid number"),
            "whitespace-title.json": ("RecordValidationError", "title"),
            "wrong-schema-field.json": ("RecordValidationError", "claim_id"),
        },
    },
    "research-claim/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-claim-type.json": ("RecordValidationError", "claim_type"),
            "bad-disposition.json": ("RecordValidationError", "disposition"),
            "bad-evidence-maturity.json": (
                "RecordValidationError",
                "evidence_maturity",
            ),
            "bad-evidence-sha256.json": ("RecordValidationError", "sha256"),
            "duplicate-key-nested.json": ("StrictJsonError", "duplicate"),
            "empty-statement.json": ("RecordValidationError", "statement"),
            "maturity-without-evidence.json": (
                "RecordValidationError",
                "supporting_evidence",
            ),
            "missing-non-entailments.json": ("RecordValidationError", "non_entailments"),
            "supported-no-evidence.json": (
                "RecordValidationError",
                "supporting_evidence",
            ),
            "superseded-no-evidence.json": (
                "RecordValidationError",
                "supporting_evidence",
            ),
            "whitespace-statement.json": ("RecordValidationError", "statement"),
            "withdrawn-no-evidence.json": (
                "RecordValidationError",
                "supporting_evidence",
            ),
        },
    },
    "research-evidence/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-content-sha256-newline.json": (
                "RecordValidationError",
                "content_sha256",
            ),
            "bad-content-sha256.json": ("RecordValidationError", "content_sha256"),
            "bad-input-kind.json": ("RecordValidationError", "kind"),
            "duplicate-key.json": ("StrictJsonError", "duplicate"),
            "empty-claim-ids.json": ("RecordValidationError", "claim_ids"),
            "input-unbound.json": ("RecordValidationError", "at least one"),
            "locator-backslash.json": ("RecordValidationError", "backslash"),
            "locator-device-name.json": ("RecordValidationError", "device name"),
            "locator-dotdot-escape.json": ("RecordValidationError", "'..'"),
            "locator-drive-absolute.json": ("RecordValidationError", "drive-letter"),
            "locator-drive-relative.json": ("RecordValidationError", "drive-letter"),
            "locator-root-absolute.json": ("RecordValidationError", "not allowed"),
            "locator-trailing-dot.json": ("RecordValidationError", "trailing"),
            "locator-unc.json": ("RecordValidationError", "backslash"),
            "missing-content-sha256.json": ("RecordValidationError", "content_sha256"),
            "missing-producer-version.json": ("RecordValidationError", "version"),
            "whitespace-applicability.json": ("RecordValidationError", "applicability"),
        },
    },
    "research-run/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-randomness-mode.json": ("RecordValidationError", "randomness"),
            "bad-task-sha256.json": ("RecordValidationError", "sha256"),
            "empty-environment.json": ("RecordValidationError", "environment"),
            "input-missing-sha256.json": ("RecordValidationError", "sha256"),
            "missing-task-pin.json": ("RecordValidationError", "sha256"),
            "missing-task.json": ("RecordValidationError", "task"),
        },
    },
    "research-failure-observation/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "bad-observed-at.json": ("RecordValidationError", "observed_at"),
            "empty-facts.json": ("RecordValidationError", "facts"),
            "missing-observer-version.json": ("RecordValidationError", "version"),
            "missing-run-pin.json": ("RecordValidationError", "sha256"),
            "root-cause-field.json": ("RecordValidationError", "additional property"),
            "run-ref-not-object.json": ("RecordValidationError", "run"),
        },
    },
    "research-failure-analysis/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-supersedes-pattern.json": ("RecordValidationError", "supersedes"),
            "empty-hypotheses.json": ("RecordValidationError", "hypotheses"),
            "missing-observation-pin.json": ("RecordValidationError", "sha256"),
            "missing-observation.json": ("RecordValidationError", "observation"),
            "whitespace-hypothesis.json": ("RecordValidationError", "hypotheses"),
        },
    },
    "research-case-package/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "empty-runs.json": ("RecordValidationError", "runs"),
            "member-bad-pin.json": ("RecordValidationError", "sha256"),
            "member-missing-pin.json": ("RecordValidationError", "sha256"),
            "missing-privacy-status.json": (
                "RecordValidationError",
                "privacy_review_status",
            ),
            "privacy-not-pending.json": (
                "RecordValidationError",
                "privacy_review_status",
            ),
            "task-as-array.json": ("RecordValidationError", "task"),
        },
    },
    "export-decision/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-export-mode.json": ("RecordValidationError", "export_mode"),
            "bad-outcome.json": ("RecordValidationError", "outcome"),
            "bad-supersedes-pattern.json": ("RecordValidationError", "supersedes"),
            "missing-case-pin.json": ("RecordValidationError", "sha256"),
            "missing-decided-at.json": ("RecordValidationError", "decided_at"),
            "whitespace-rationale.json": ("RecordValidationError", "rationale"),
        },
    },
    "export-receipt/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "artifact-locator-absolute.json": ("RecordValidationError", "drive-letter"),
            "artifact-missing-sha256.json": ("RecordValidationError", "sha256"),
            "bad-export-mode.json": ("RecordValidationError", "export_mode"),
            "bad-exported-at.json": ("RecordValidationError", "exported_at"),
            "empty-artifacts.json": ("RecordValidationError", "artifacts"),
            "missing-decision-pin.json": ("RecordValidationError", "sha256"),
            "whitespace-destination.json": ("RecordValidationError", "destination"),
        },
    },
    "evaluation-case/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-input-sha256.json": ("RecordValidationError", "content_sha256"),
            "bad-scorer-level.json": ("RecordValidationError", "scorer_level"),
            "bad-split.json": ("RecordValidationError", "$.split"),
            "missing-contamination-status.json": (
                "RecordValidationError",
                "contamination_status",
            ),
        },
    },
    "suite/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-case-sha256.json": ("RecordValidationError", "sha256"),
            "case-ref-missing-sha256.json": (
                "RecordValidationError",
                "missing required property 'sha256'",
            ),
            "empty-cases.json": ("RecordValidationError", "$.cases"),
            "missing-frozen-at.json": ("RecordValidationError", "frozen_at"),
        },
    },
    "evaluation-run/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-gate.json": ("RecordValidationError", "gate"),
            "bad-levels-covered.json": ("RecordValidationError", "levels_covered"),
            "bad-scorer-level.json": ("RecordValidationError", "scorer"),
            "empty-score-vector.json": ("RecordValidationError", "score_vector"),
        },
    },
    "evaluation-attempt/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-case-sha256.json": ("RecordValidationError", "sha256"),
            "bad-status.json": ("RecordValidationError", "status"),
            "completed-without-output.json": (
                "RecordValidationError",
                "complete_outputs",
            ),
            "error-without-diagnostic.json": ("RecordValidationError", "diagnostics"),
            "scorer-error-without-output.json": (
                "RecordValidationError",
                "complete_outputs",
            ),
        },
    },
    "evaluation-result/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-generated-at.json": ("RecordValidationError", "generated_at"),
            "carries-gate-results.json": (
                "RecordValidationError",
                "additional property",
            ),
            "carries-verdict.json": (
                "RecordValidationError",
                "additional property",
            ),
            "empty-score-vector.json": ("RecordValidationError", "score_vector"),
            "missing-attempt-pin.json": ("RecordValidationError", "sha256"),
        },
    },
    "comparison-report/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-statistics-method.json": ("RecordValidationError", "statistics"),
            "challenger-missing-sha256.json": ("RecordValidationError", "$.challenger"),
            "empty-score-deltas.json": ("RecordValidationError", "score_deltas"),
            "whitespace-conclusion.json": ("RecordValidationError", "conclusion"),
        },
    },
    "research-case-package/v2": {
        "valid": [
            "full.json",
            "minimal.json",
            "eligibility-ineligible.json",
            "export-mode-benchmark-candidate.json",
            "export-mode-metrics-only.json",
            "privacy-rejected.json",
        ],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-eligibility-status.json": ("RecordValidationError", "eligibility"),
            "bad-export-mode.json": ("RecordValidationError", "export_mode"),
            "bad-privacy-status.json": (
                "RecordValidationError",
                "privacy_review_status",
            ),
            "bad-signature-sha256.json": ("RecordValidationError", "signature_sha256"),
            "bad-timeline-at.json": ("RecordValidationError", "decision_timeline"),
            "derived-from-missing-pin.json": ("RecordValidationError", "sha256"),
            "empty-decision-timeline.json": (
                "RecordValidationError",
                "decision_timeline",
            ),
            "empty-io-inputs.json": ("RecordValidationError", "inputs"),
        },
    },
    "research-pattern/v1": {
        "valid": [
            "full.json",
            "minimal.json",
            "confidence-low.json",
            "status-candidate-pattern.json",
            "status-deprecated.json",
            "status-distilled.json",
            "status-rejected.json",
            "status-retired.json",
            "status-validated-pattern.json",
        ],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-confidence.json": ("RecordValidationError", "confidence"),
            "bad-last-validated.json": ("RecordValidationError", "last_validated"),
            "bad-status.json": ("RecordValidationError", "status"),
            "empty-source-cases.json": ("RecordValidationError", "source_cases"),
            "empty-successful-tactics.json": (
                "RecordValidationError",
                "successful_tactics",
            ),
            "missing-transition-rationale.json": (
                "RecordValidationError",
                "transition_rationale",
            ),
            "source-case-missing-pin.json": ("RecordValidationError", "sha256"),
            "whitespace-supersedes.json": ("RecordValidationError", "supersedes"),
        },
    },
    "heuristic/v1": {
        "valid": [
            "full.json",
            "minimal.json",
            "status-candidate.json",
            "status-deprecated.json",
            "status-promoted.json",
            "status-rejected.json",
            "status-retired.json",
            "status-validated.json",
        ],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-mode.json": ("RecordValidationError", "mode"),
            "bad-status.json": ("RecordValidationError", "status"),
            "empty-evidence.json": ("RecordValidationError", "evidence"),
            "empty-regression-cases.json": (
                "RecordValidationError",
                "regression_cases",
            ),
            "missing-rollback.json": ("RecordValidationError", "rollback"),
            "regression-case-missing-pin.json": ("RecordValidationError", "sha256"),
            "whitespace-supersedes.json": ("RecordValidationError", "supersedes"),
        },
    },
    "reuse-event/v1": {
        "valid": [
            "full.json",
            "minimal.json",
            "outcome-harmed.json",
            "outcome-neutral.json",
            "outcome-not-applicable.json",
        ],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-outcome.json": ("RecordValidationError", "outcome"),
            "bad-recorded-at.json": ("RecordValidationError", "recorded_at"),
            "missing-pattern-pin.json": ("RecordValidationError", "sha256"),
            "missing-run-pin.json": ("RecordValidationError", "sha256"),
            "run-ref-not-object.json": ("RecordValidationError", "run"),
            "whitespace-note.json": ("RecordValidationError", "note"),
        },
    },
    "candidate-manifest/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-member-sha256.json": ("RecordValidationError", "sha256"),
            "bad-status.json": ("RecordValidationError", "status"),
            "missing-reviewer.json": ("RecordValidationError", "reviewer"),
            "source-cases-too-few.json": ("RecordValidationError", "source_cases"),
        },
    },
    "artifact-closure-receipt/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-closed-at.json": ("RecordValidationError", "closed_at"),
            "byte-not-closed.json": ("RecordValidationError", "byte_closed"),
            "receipt-not-last.json": ("RecordValidationError", "receipt_last"),
            "semantic-review-completed.json": (
                "RecordValidationError",
                "semantic_review_completed",
            ),
        },
    },
    "context-bundle/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-built-at.json": ("RecordValidationError", "built_at"),
            "bad-mode.json": ("RecordValidationError", "mode"),
            "minimum-safe-false.json": (
                "RecordValidationError",
                "minimum_safe_preserved",
            ),
            "publication-authorized.json": (
                "RecordValidationError",
                "publication_authorized",
            ),
        },
    },
    "context-material-assessment/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-candidate-sha256.json": ("RecordValidationError", "sha256"),
            "bad-id.json": ("RecordValidationError", "context_material_assessment_id"),
            "missing-classification.json": ("RecordValidationError", "classification"),
            "unknown-taint.json": ("RecordValidationError", "source_taint_labels"),
        },
    },
    "context-bundle/v2": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-assessment-sha256.json": ("RecordValidationError", "sha256"),
            "bad-id.json": ("RecordValidationError", "context_bundle_id"),
            "bad-token-method.json": ("RecordValidationError", "estimation_method"),
            "restricted-inline.json": ("RecordValidationError", "classification"),
        },
    },
    "suite-comparison/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": (
                "RecordValidationError",
                "additional property",
            ),
            "bad-inference-status.json": (
                "RecordValidationError",
                "inference_status",
            ),
            "bad-observation-unit.json": (
                "RecordValidationError",
                "observation_unit",
            ),
            "champion-run-missing-pin.json": (
                "RecordValidationError",
                "sha256",
            ),
            "empty-metrics.json": ("RecordValidationError", "metrics"),
        },
    },
    "artifact-record/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": (
                "RecordValidationError",
                "additional property",
            ),
            "bad-created-at.json": ("RecordValidationError", "created_at"),
            "bad-role.json": ("RecordValidationError", "role"),
            "hidden-content-disclosed.json": (
                "RecordValidationError",
                "content_disclosed",
            ),
            "missing-content-sha256.json": (
                "RecordValidationError",
                "content_sha256",
            ),
        },
    },
    "evaluation-envelope-closure-receipt/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": (
                "RecordValidationError",
                "additional property",
            ),
            "artifact-missing-pin.json": (
                "RecordValidationError",
                "sha256",
            ),
            "bad-closed-at.json": ("RecordValidationError", "closed_at"),
            "envelope-not-closed.json": (
                "RecordValidationError",
                "evaluation_envelope_closed",
            ),
            "hidden-bytes-disclosed.json": (
                "RecordValidationError",
                "hidden_bytes_disclosed",
            ),
        },
    },
}

# Golden pins: canonical SHA-256 of each family's valid/minimal.json fixture.
MINIMAL_FIXTURE_SHA256 = {
    "artifact-record/v1": (
        "b54a0cff2110d9a1e6b7f6eb8f18a6b2a9715e8e02db1289834d78e5157feb3c"
    ),
    "artifact-closure-receipt/v1": (
        "31023abcf8518679d1b9b2d933dfd374341ffe0af4da419693c84db09a2aea88"
    ),
    "candidate-manifest/v1": (
        "4a251d80b2aec6cd9c4656896136f7801cfa86cf291659ff6254739a25889b7e"
    ),
    "comparison-report/v1": (
        "bf36390b526c89c65b6a3c1e79f5f3a1bc5a9ea545ba27924db803218e1542cb"
    ),
    "evaluation-case/v1": (
        "95e8a4bf98b88f746c0b9d653c7067bee5845e624681fe2a8da35be7b61b30f7"
    ),
    "evaluation-attempt/v1": (
        "6179fefaee14d5c650bfe49268b142528dd8d4b90c2ac09650ed85b5e15ef66c"
    ),
    "evaluation-result/v1": (
        "b6a1bdc98169a257ee81698689093a19e03adec623cb4b4cdbf797f4e58aa08f"
    ),
    "evaluation-envelope-closure-receipt/v1": (
        "8172f2d98dccd6f3afb93fc162c245d63dfbaad623dc7dc0f719446d04066f83"
    ),
    "evaluation-run/v1": (
        "c73ef291b765868e9cb556cc5d63f3d3bb17a77f5de07aee270096954d24db7e"
    ),
    "export-decision/v1": (
        "752c486c686785603c248de08379279ac366ba85b7f7c64fb1f6638da08b877f"
    ),
    "export-receipt/v1": (
        "acbf6c46800da6f12a104d885dbd3bb727e5bbd688a128992239259be1247ebc"
    ),
    "heuristic/v1": (
        "8533c35152d56a11f47900b06958a065988f7087f5a316e110dd3ec31b83fbed"
    ),
    "research-case-package/v1": (
        "d83202cfeafc280b98df1b7d9e0c69be70e1d8681c3c6fbc0e5b252c7a5f2ae5"
    ),
    "research-case-package/v2": (
        "042eca632dfeab36b6d02e3279cf56b2eb650072e84b6223a6ed2572444c1fff"
    ),
    "research-claim/v1": (
        "a496686fd72c63ee8cba7c3e59281a7575f8ee499798072457e2bcce6796c769"
    ),
    "research-evidence/v1": (
        "a77ec6c1bb747e00d95d5a0d227f6bc0f6f8e9592bd93ca6911978810f09b3a4"
    ),
    "research-failure-analysis/v1": (
        "97143007a8f05ca7e243228f490f8bee23c06323155b3ad68710ae34b4fddeed"
    ),
    "research-failure-observation/v1": (
        "946bd26918fe3ec254be0fa375c0a2090ddde0dffee5d4fb6de9c3d546300ece"
    ),
    "research-pattern/v1": (
        "cce2f8f67b911b85005a08c48490be3d000f1a099883216818a0c5785299945c"
    ),
    "research-run/v1": (
        "f6a3a6273e87f9ac38efc332b98b14b5c9b95ec3f5652567502d7063df8e4c9e"
    ),
    "research-task/v1": (
        "7a73b657e4b3e8ae6250e0a56b0dee7a73b3838ca4bdd637fe58b7d044e7519a"
    ),
    "reuse-event/v1": (
        "21054deab507d4a8ce66ca818aa38d8a674cf2b7b0484d82de0585fe9cda9669"
    ),
    "suite/v1": (
        "72e17ae19ab298e6c04f6886b8dcf2c1c6ea48306d4d35672c6fc853c7fe301b"
    ),
    "context-bundle/v1": (
        "912f081adada126661f0c0cd4baacc8ad5faf5cf308636aa7efa8b5d3a3e4f8e"
    ),
    "context-bundle/v2": (
        "97ad32a7f784c9bca716a1f248c1edd6d3992f6228019e9cd7ac140969099764"
    ),
    "context-material-assessment/v1": (
        "9d88af279e7ac3a30055ec9ace31180efad45700912c36a936e7fb88a8d4a484"
    ),
    "suite-comparison/v1": (
        "bea90285ac9e9cfa7cecb2be836450beb26fa9d5396d0bea7a68962a3e370302"
    ),
}

# Golden pins (ADR-0004 decision 7): SHA-256 of each schema file's raw
# on-disk bytes. Newline stability is carried by .gitattributes
# (``*.json text eol=lf``); any byte-level edit of a frozen schema — even
# pure reformatting — fails this pin.
SCHEMA_TEXT_SHA256 = {
    "artifact-record-v1.schema.json": (
        "1acb72c52221a79bfa5ae514619a22b4bb46cbfcd2774496415c9d6f3d2a8f8f"
    ),
    "artifact-closure-receipt-v1.schema.json": (
        "42a96a1118c57451de8a40031d545a012be64704fa66de3d7d8cc91ba217c5c9"
    ),
    "candidate-manifest-v1.schema.json": (
        "916a17a143bf2db627eecabab4679549bc4fcb04eb478a0af1acad6a2d426ceb"
    ),
    "comparison-report-v1.schema.json": (
        "a89e6839f477413fc6f14d4a9d286e84c80d747526109cb7c3a5418b93c83479"
    ),
    "evaluation-case-v1.schema.json": (
        "1d79cfb8c6efb087e730fa1cb59dd322333911c8768357cb7f2bf81f6ead932a"
    ),
    "evaluation-attempt-v1.schema.json": (
        "ae4af3cbbf88dee2bd9a24a5072eecf0477731bfba2694a5116fb873a13a7c67"
    ),
    "evaluation-result-v1.schema.json": (
        "a4cdb9289a8cbaf7d1feaaadd8b7a8ab152e8e7c5dfe76608a4f8a3702b6843a"
    ),
    "evaluation-envelope-closure-receipt-v1.schema.json": (
        "43346178e8ce1061f946a758756aa3529e283d80c45d3333c9c29f7fd810dd7d"
    ),
    "evaluation-run-v1.schema.json": (
        "f0ae7997dcbeb1a53e654fbd74b3aa2a9171221d7cca6832c7294564f7901b36"
    ),
    "export-decision-v1.schema.json": (
        "1d4a4209df2d5d230a9713c56e1bfc35b8f727a79b0021abeff4e69cf2162c48"
    ),
    "export-receipt-v1.schema.json": (
        "00bb452c0c417ab17254988d4e5597abebe5cbca1607ac68096a705493dd09e4"
    ),
    "heuristic-v1.schema.json": (
        "a79d7f724c2e22a346de941fae5393192b424d67645a4158fe0dea17a1101dab"
    ),
    "research-case-package-v1.schema.json": (
        "3945496445ea2e4a809bb49a58c4bbbb469de8c18c4dc517ad3f3a63ec894a25"
    ),
    "research-case-package-v2.schema.json": (
        "92e66e0a28fd65ca81fe21e93297ca13c4d06a0f327b78c8850787de8436d27d"
    ),
    "research-claim-v1.schema.json": (
        "0eac88fff6fb4fa1f2046154051fc252148c79c980dac98c6a52d1212f57ff59"
    ),
    "research-evidence-v1.schema.json": (
        "db0e1abee5f2b14f6c5bbfcf73e5a6eafccf9e9d2ec7a5bbb5aa2c22b8e4891c"
    ),
    "research-failure-analysis-v1.schema.json": (
        "4d33b5f3123736c23bf60b9aa0f6eb02a3a14438bf3a02f2d12a7ae0399e60d9"
    ),
    "research-failure-observation-v1.schema.json": (
        "5e31a795bc92a19051189d2518fd054b75134d5dc4f313ffeaf81b6aa49cf397"
    ),
    "research-pattern-v1.schema.json": (
        "45fe40e87866cb1ceb40d5399572524de72fdcf85de91231002fafdd2f597113"
    ),
    "research-run-v1.schema.json": (
        "a6068ea50910147c42e00d685ab675e4852df929860e0540c11803d0615767bc"
    ),
    "research-task-v1.schema.json": (
        "95f5450d50e3ff712ec21b74458be2ff0c727b9f4544d04666f0691c679afc6e"
    ),
    "reuse-event-v1.schema.json": (
        "52b82c7badd9a8cddf07955f778c5262d53f030e7b3749762302330e55297fb5"
    ),
    "suite-v1.schema.json": (
        "217368272ab7c555b4961d1681eb1047ff5ca070248f3559499c2b4ccacf938a"
    ),
    "context-bundle-v1.schema.json": (
        "aa1f4039c2359d8e92ac80cfa3916d21c7b2359ad36eda7755a930c99b4a83d7"
    ),
    "context-bundle-v2.schema.json": (
        "bf5b51dc47ccc134c38e663fd4b03e5010e7dbca39c3f5dfd83aa2124bed94ef"
    ),
    "context-material-assessment-v1.schema.json": (
        "1416a26af2ab0e3ef59b63033ed4b3b8904e3b1db9d023895bfb48cbfd3df673"
    ),
    "suite-comparison-v1.schema.json": (
        "b5b656b76041e4529945e5dcb1c558f8cfae0299481e32838d7ea6ed1f7feab8"
    ),
}

# Domain vocabulary that must never leak into the domain-neutral core schemas.
_BANNED_TERMS = re.compile(
    r"\b(theorem|proof|factor|backtest|signal|sharpe|drawdown|ohlcv|"
    r"neural|neuron|cuda|gpu|alpha)\b",
    re.IGNORECASE,
)


def _fixture_dir(schema_id: str, kind: str) -> Path:
    family, version = schema_id.split("/")
    return FIXTURES_ROOT / family / version / kind


def _manifest_files() -> set[str]:
    expected: set[str] = set()
    for schema_id, groups in FIXTURE_MANIFEST.items():
        family, version = schema_id.split("/")
        for name in groups["valid"]:
            expected.add(f"{family}/{version}/valid/{name}")
        for name in groups["invalid"]:
            expected.add(f"{family}/{version}/invalid/{name}")
    return expected


class FixtureManifestTest(unittest.TestCase):
    def test_fixture_tree_matches_manifest_bidirectionally(self) -> None:
        on_disk = {
            path.relative_to(FIXTURES_ROOT).as_posix()
            for path in FIXTURES_ROOT.rglob("*")
            if path.is_file()
        }
        self.assertEqual(_manifest_files(), on_disk)

    def test_every_schema_has_valid_and_invalid_fixtures(self) -> None:
        for groups in FIXTURE_MANIFEST.values():
            self.assertGreaterEqual(len(groups["valid"]), 2)
            self.assertGreaterEqual(len(groups["invalid"]), 5)


class FixtureBehaviorTest(unittest.TestCase):
    def test_valid_fixtures_load(self) -> None:
        for schema_id, groups in FIXTURE_MANIFEST.items():
            for name in groups["valid"]:
                path = _fixture_dir(schema_id, "valid") / name
                with self.subTest(fixture=f"{schema_id}/valid/{name}"):
                    record = load_record(path.read_bytes())
                    self.assertEqual(record.schema_id, schema_id)

    def test_invalid_fixtures_fail_with_expected_error(self) -> None:
        for schema_id, groups in FIXTURE_MANIFEST.items():
            for name, (error_name, reason) in groups["invalid"].items():
                path = _fixture_dir(schema_id, "invalid") / name
                with self.subTest(fixture=f"{schema_id}/invalid/{name}"):
                    with self.assertRaises(CoreError) as ctx:
                        load_record(path.read_bytes())
                    self.assertEqual(
                        type(ctx.exception).__name__,
                        error_name,
                        f"wrong error class: {ctx.exception}",
                    )
                    self.assertIn(
                        reason,
                        str(ctx.exception),
                        f"reason substring missing: {ctx.exception}",
                    )

    def test_minimal_fixture_hashes_are_golden_pinned(self) -> None:
        for schema_id, expected in MINIMAL_FIXTURE_SHA256.items():
            path = _fixture_dir(schema_id, "valid") / "minimal.json"
            with self.subTest(fixture=f"{schema_id}/valid/minimal.json"):
                record = load_record(path.read_bytes())
                self.assertEqual(record.sha256, expected)

    def test_reloading_is_deterministic(self) -> None:
        for schema_id, groups in FIXTURE_MANIFEST.items():
            for name in groups["valid"]:
                path = _fixture_dir(schema_id, "valid") / name
                first = load_record(path.read_bytes()).sha256
                second = load_record(path.read_bytes()).sha256
                self.assertEqual(first, second, f"nondeterministic hash for {path}")


class SchemaIntegrityTest(unittest.TestCase):
    def test_registry_loads_exactly_the_twenty_seven_schemas(self) -> None:
        registry = SchemaRegistry(SCHEMA_ROOT)
        self.assertEqual(
            registry.schema_ids,
            (
                "artifact-closure-receipt/v1",
                "artifact-record/v1",
                "candidate-manifest/v1",
                "comparison-report/v1",
                "context-bundle/v1",
                "context-bundle/v2",
                "context-material-assessment/v1",
                "evaluation-attempt/v1",
                "evaluation-case/v1",
                "evaluation-envelope-closure-receipt/v1",
                "evaluation-result/v1",
                "evaluation-run/v1",
                "export-decision/v1",
                "export-receipt/v1",
                "heuristic/v1",
                "research-case-package/v1",
                "research-case-package/v2",
                "research-claim/v1",
                "research-evidence/v1",
                "research-failure-analysis/v1",
                "research-failure-observation/v1",
                "research-pattern/v1",
                "research-run/v1",
                "research-task/v1",
                "reuse-event/v1",
                "suite-comparison/v1",
                "suite/v1",
            ),
        )

    def test_schema_text_bytes_are_golden_pinned(self) -> None:
        on_disk = {path.name for path in SCHEMA_ROOT.glob("*.schema.json")}
        self.assertEqual(set(SCHEMA_TEXT_SHA256), on_disk)
        for name, expected in sorted(SCHEMA_TEXT_SHA256.items()):
            with self.subTest(schema=name):
                raw = (SCHEMA_ROOT / name).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)

    def test_schema_files_are_domain_neutral(self) -> None:
        for path in sorted(SCHEMA_ROOT.glob("*.schema.json")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(schema=path.name):
                match = _BANNED_TERMS.search(text)
                self.assertIsNone(
                    match,
                    f"domain term {match.group(0)!r} leaked into {path.name}"
                    if match
                    else "",
                )


if __name__ == "__main__":
    unittest.main()
