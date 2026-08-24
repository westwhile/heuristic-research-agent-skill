"""Contract tests for the adapter seam and domain schemas (ADR-0005).

Mirrors tests/contract/test_core_schemas_contract.py with two deliberate
differences:

- no domain-neutrality scan — domain vocabulary is ALLOWED under
  schemas/adapters/ (the freeze is the other direction: domain fields must
  never flow back into schemas/core/, and the core contract test pins that);
- SeamBoundaryTest pins the ADR-0005 decision 1 boundary: adapter schema
  ids are rejected by the core default schema root, so seam and domain
  payloads can never enter the core record pipeline (never publishable to
  a core store).

The fixture tree under tests/fixtures/adapters/ and
ADAPTER_FIXTURE_MANIFEST are compared bidirectionally; every family's
minimal fixture and every schema file's raw bytes are golden-pinned
(ADR-0004 decision 7 applies to adapter schemas from birth).
"""

import hashlib
import unittest
from pathlib import Path

from research_evolution.core import (
    CoreError,
    RecordValidationError,
    UnknownSchemaError,
    load_record,
)
from research_evolution.core._schema import SchemaRegistry

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "adapters"
SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "adapters"
CORE_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "core"

_ERROR_CLASSES = {
    "RecordValidationError": RecordValidationError,
}

# invalid fixture name -> (expected error class, expected reason substring).
ADAPTER_FIXTURE_MANIFEST = {
    "domain-task/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-domain-schema-id.json": ("RecordValidationError", "domain_schema_id"),
            "bad-domain.json": ("RecordValidationError", "$.domain"),
            "draft-missing-schema.json": ("RecordValidationError", "core_task_draft"),
            "draft-wrong-schema-tag.json": ("RecordValidationError", "research-task/v1"),
            "missing-domain-payload.json": ("RecordValidationError", "domain_payload"),
            "payload-not-object.json": ("RecordValidationError", "domain_payload"),
        },
    },
    "claim-assessment/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-claim-type.json": ("RecordValidationError", "suggested_claim_type"),
            "bad-disposition.json": ("RecordValidationError", "suggested_disposition"),
            "bad-maturity-ceiling.json": (
                "RecordValidationError",
                "evidence_maturity_ceiling",
            ),
            "empty-reasons.json": ("RecordValidationError", "reasons"),
            "missing-triggered-rules.json": (
                "RecordValidationError",
                "triggered_rules",
            ),
            "whitespace-reason.json": ("RecordValidationError", "reasons"),
        },
    },
    "evaluation-contract/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-case-sha256.json": ("RecordValidationError", "case_sha256"),
            "bad-requirement-claim-type.json": ("RecordValidationError", "claim_type"),
            "bad-requirement-min-maturity.json": (
                "RecordValidationError",
                "min_maturity",
            ),
            "empty-required-evidence.json": (
                "RecordValidationError",
                "required_evidence",
            ),
            "requirement-missing-maturity.json": (
                "RecordValidationError",
                "min_maturity",
            ),
            "whitespace-forbidden-channel.json": (
                "RecordValidationError",
                "forbidden_channels",
            ),
        },
    },
    "evaluation-contract/v2": {
        "valid": ["all-vocabulary.json", "full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-assessment-status.json": (
                "RecordValidationError",
                "assessment_declaration",
            ),
            "missing-assessment-declaration.json": (
                "RecordValidationError",
                "assessment_declaration",
            ),
            "missing-study-id.json": ("RecordValidationError", "study_id"),
            "whitespace-study-id.json": ("RecordValidationError", "study_id"),
        },
    },
    "evaluation-contract/v3": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-selection-partition.json": (
                "RecordValidationError",
                "selection_partition",
            ),
            "bad-selection-sha256.json": (
                "RecordValidationError",
                "selection_sha256",
            ),
            "bad-split-sha256.json": ("RecordValidationError", "split_sha256"),
            "missing-selection-partition.json": (
                "RecordValidationError",
                "selection_partition",
            ),
        },
    },
    "math-task/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-sought.json": ("RecordValidationError", "sought"),
            "empty-completion-criteria.json": (
                "RecordValidationError",
                "completion_criteria",
            ),
            "missing-created-at.json": ("RecordValidationError", "created_at"),
            "missing-quantifiers.json": ("RecordValidationError", "quantifiers"),
            "whitespace-statement.json": ("RecordValidationError", "statement"),
        },
    },
    "math-claim/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-result.json": ("RecordValidationError", "$.result"),
            "missing-non-entailments.json": (
                "RecordValidationError",
                "non_entailments",
            ),
            "missing-quantifiers.json": ("RecordValidationError", "quantifiers"),
            "whitespace-statement.json": ("RecordValidationError", "statement"),
        },
    },
    "math-evidence/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-content-sha256.json": ("RecordValidationError", "content_sha256"),
            "bad-kind.json": ("RecordValidationError", "$.kind"),
            "missing-content-sha256.json": (
                "RecordValidationError",
                "content_sha256",
            ),
            "whitespace-summary.json": ("RecordValidationError", "summary"),
        },
    },
    "math-case/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-sought.json": ("RecordValidationError", "sought"),
            "missing-case-id.json": ("RecordValidationError", "case_id"),
            "missing-problem-id.json": ("RecordValidationError", "problem_id"),
            "whitespace-case-id.json": ("RecordValidationError", "case_id"),
        },
    },
    "quant-task/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "empty-completion-criteria.json": (
                "RecordValidationError",
                "completion_criteria",
            ),
            "missing-created-at.json": ("RecordValidationError", "created_at"),
            "missing-pit-policy.json": ("RecordValidationError", "pit_policy"),
            "whitespace-universe.json": ("RecordValidationError", "$.universe"),
        },
    },
    "quant-claim/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-claim-class.json": ("RecordValidationError", "claim_class"),
            "bad-outcome.json": ("RecordValidationError", "$.outcome"),
            "missing-non-entailments.json": (
                "RecordValidationError",
                "non_entailments",
            ),
            "whitespace-statement.json": ("RecordValidationError", "statement"),
        },
    },
    "quant-evidence/v1": {
        "valid": ["full.json", "minimal.json", "production-log.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-content-sha256.json": ("RecordValidationError", "content_sha256"),
            "bad-kind.json": ("RecordValidationError", "$.kind"),
            "bad-provenance.json": ("RecordValidationError", "data_provenance"),
            "whitespace-summary.json": ("RecordValidationError", "summary"),
        },
    },
    "quant-case/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-gate.json": ("RecordValidationError", "$.gates"),
            "empty-gates.json": ("RecordValidationError", "$.gates"),
            "missing-case-id.json": ("RecordValidationError", "case_id"),
            "missing-study-id.json": ("RecordValidationError", "study_id"),
        },
    },
    "domain-task/v2": {
        "valid": ["full.json", "math.json", "minimal.json", "quant.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-domain-schema-id.json": ("RecordValidationError", "domain_schema_id"),
            "bad-domain.json": ("RecordValidationError", "$.domain"),
            "draft-missing-schema.json": ("RecordValidationError", "core_task_draft"),
            "draft-wrong-schema-tag.json": ("RecordValidationError", "research-task/v1"),
            "missing-domain-payload.json": ("RecordValidationError", "domain_payload"),
            "payload-not-object.json": ("RecordValidationError", "domain_payload"),
        },
    },
    "dl-checkpoint-recovery-observation/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-evidence-scope.json": ("RecordValidationError", "evidence_scope"),
            "bad-observed-at.json": ("RecordValidationError", "observed_at"),
            "missing-manifest-sha256.json": (
                "RecordValidationError",
                "manifest_sha256",
            ),
            "wrong-runner.json": ("RecordValidationError", "runner.name"),
        },
    },
    "dl-run-manifest/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-created-at.json": ("RecordValidationError", "created_at"),
            "bad-device-count-type.json": ("RecordValidationError", "device_count"),
            "bad-evidence-scope.json": ("RecordValidationError", "evidence_scope"),
            "bad-locator.json": ("RecordValidationError", "locator"),
            "missing-case-sha256.json": ("RecordValidationError", "case_sha256"),
            "missing-max-tokens.json": ("RecordValidationError", "max_tokens"),
        },
    },
    "dl-run-observation/v1": {
        "valid": ["failed.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-evidence-scope.json": ("RecordValidationError", "evidence_scope"),
            "bad-observed-at.json": ("RecordValidationError", "observed_at"),
            "metrics-not-array.json": ("RecordValidationError", "metrics"),
            "missing-manifest-sha256.json": (
                "RecordValidationError",
                "manifest_sha256",
            ),
            "wrong-runner.json": ("RecordValidationError", "runner.name"),
        },
    },
    "dl-same-host-reproducibility-report/v1": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-evidence-scope.json": ("RecordValidationError", "evidence_scope"),
            "bad-observed-at.json": ("RecordValidationError", "observed_at"),
            "missing-plan-sha256.json": ("RecordValidationError", "plan_sha256"),
            "wrong-runner.json": ("RecordValidationError", "runner.name"),
        },
    },
    "ml-task/v1": {
        "valid": ["clustering.json", "full.json", "minimal.json", "regression.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-task-type.json": ("RecordValidationError", "task_type"),
            "empty-completion-criteria.json": (
                "RecordValidationError",
                "completion_criteria",
            ),
            "missing-created-at.json": ("RecordValidationError", "created_at"),
            "missing-holdout-policy.json": ("RecordValidationError", "holdout_policy"),
            "whitespace-holdout-policy.json": ("RecordValidationError", "holdout_policy"),
        },
    },
    "ml-case/v1": {
        "valid": [
            "full.json",
            "group-split.json",
            "minimal.json",
            "nested-split.json",
            "unsafe-assessment-calibration-detail-missing.json",
            "unsafe-assessment-calibration-detail-present.json",
            "unsafe-assessment-drift-detail-missing.json",
            "unsafe-assessment-drift-detail-present.json",
            "unsafe-assessment-ood-detail-missing.json",
            "unsafe-assessment-ood-detail-present.json",
            "unsafe-assessment-subgroup-detail-missing.json",
            "unsafe-assessment-subgroup-detail-present.json",
            "unsafe-feature-selection.json",
            "unsafe-fit-scope-full-data.json",
            "unsafe-sampling-scope-full-data.json",
            "unsafe-sampling-scope-pre-split.json",
            "unsafe-sampling-scope.json",
            "unsafe-scope-upstream-mismatch-preprocessing-per-fold.json",
            "unsafe-scope-upstream-mismatch-sampling-per-fold.json",
            "unsafe-scope-upstream-mismatch-sampling-train-only.json",
            "unsafe-scope-upstream-mismatch.json",
            "unsafe-selection-split-test.json",
            "unsafe-split-group-key-blank.json",
            "unsafe-split-group-key-missing.json",
            "unsafe-split-group-key-wrong-type.json",
            "unsafe-split-nested-inner-folds-below-floor.json",
            "unsafe-split-nested-inner-folds-float.json",
            "unsafe-split-nested-outer-folds-bool.json",
            "unsafe-split-nested-outer-folds-missing.json",
            "unsafe-split-time-series-embargo-wrong-type.json",
            "unsafe-split-time-series-gap-blank.json",
            "unsafe-split-time-series-gap-missing.json",
            "unsafe-target-encoding.json",
            "unsafe-tuning-seed-count-zero.json",
            "unsafe-tuning-split-future-holdout.json",
            "unsafe-tuning-split-test.json",
        ],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-assessment-status.json": (
                "RecordValidationError",
                "assessment.calibration.status",
            ),
            "bad-gate.json": ("RecordValidationError", "$.gates"),
            "bad-preprocessing-fit-scope.json": ("RecordValidationError", "fit_scope"),
            "bad-selection-split-used.json": ("RecordValidationError", "selection.split_used"),
            "bad-split-kind.json": ("RecordValidationError", "split.kind"),
            "bad-tuning-split-used.json": ("RecordValidationError", "tuning.split_used"),
            "empty-gates.json": ("RecordValidationError", "$.gates"),
            "malformed-dataset-sha256.json": ("RecordValidationError", "dataset.sha256"),
            "missing-assessment.json": ("RecordValidationError", "'assessment'"),
            "missing-dataset.json": ("RecordValidationError", "dataset"),
            "missing-sampling-scope.json": ("RecordValidationError", "'scope'"),
        },
    },
    "ml-claim/v1": {
        "valid": [
            "data-acceptance.json",
            "full.json",
            "minimal.json",
            "outcome-fail.json",
            "outcome-inconclusive.json",
        ],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-case-sha256.json": ("RecordValidationError", "case_sha256"),
            "bad-claim-class.json": ("RecordValidationError", "claim_class"),
            "bad-declared-assessment-gap.json": (
                "RecordValidationError",
                "declared_assessment_gaps",
            ),
            "bad-outcome.json": ("RecordValidationError", "$.outcome"),
            "missing-case-sha256.json": ("RecordValidationError", "case_sha256"),
            "missing-declared-assessment-gaps.json": (
                "RecordValidationError",
                "declared_assessment_gaps",
            ),
            "missing-limitations.json": ("RecordValidationError", "limitations"),
            "missing-non-entailments.json": (
                "RecordValidationError",
                "non_entailments",
            ),
            "whitespace-statement.json": ("RecordValidationError", "statement"),
        },
    },
    "ml-evidence/v1": {
        "valid": [
            "calibration.json",
            "data-audit.json",
            "drift.json",
            "duplicate-seeds-experiment.json",
            "full.json",
            "minimal.json",
            "ood.json",
            "other.json",
            "real-experiment.json",
            "single-seed-experiment.json",
            "subgroup.json",
            "synthetic-experiment.json",
        ],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-content-sha256.json": ("RecordValidationError", "content_sha256"),
            "bad-kind.json": ("RecordValidationError", "$.kind"),
            "bad-provenance.json": ("RecordValidationError", "data_provenance"),
            "bad-seed-type.json": ("RecordValidationError", "seeds"),
            "missing-frozen-holdout.json": ("RecordValidationError", "frozen_holdout"),
            "missing-seeds.json": ("RecordValidationError", "seeds"),
            "missing-study-id.json": ("RecordValidationError", "study_id"),
            "whitespace-summary.json": ("RecordValidationError", "summary"),
        },
    },
    "ml-evidence/v2": {
        "valid": ["full.json", "minimal.json"],
        "invalid": {
            "additional-property.json": ("RecordValidationError", "additional property"),
            "bad-case-sha256.json": ("RecordValidationError", "case_sha256"),
            "bad-final-partition.json": ("RecordValidationError", "partition"),
            "bad-final-split-sha256.json": (
                "RecordValidationError",
                "split_sha256",
            ),
            "bad-kind.json": ("RecordValidationError", "$.kind"),
            "missing-final-evaluation.json": (
                "RecordValidationError",
                "final_evaluation",
            ),
            "missing-case-sha256.json": (
                "RecordValidationError",
                "case_sha256",
            ),
        },
    },
}

# Golden pins: canonical SHA-256 of each family's valid/minimal.json fixture.
MINIMAL_FIXTURE_SHA256 = {
    "claim-assessment/v1": (
        "fc5761d819cafe98d3ab08110311eb72e3aab8cb8067882ed7402917ba88a805"
    ),
    "domain-task/v1": (
        "d4220f70af2cc8df6bfe4790d914d8bae25f3f8bfd7987290f7e90e1320890cd"
    ),
    "domain-task/v2": (
        "6247567e285b884f869d7ad4d0e9dbc8a2bc740b1c14cbe600fb7969690ba488"
    ),
    "dl-checkpoint-recovery-observation/v1": (
        "f4f10c417ac0211c583162f054858fa744db5defb5d5c3376cc5fd09f91710b9"
    ),
    "dl-run-manifest/v1": (
        "55a7a42f595bf39697e7fff3ba1395225138e8c2a5221c8c594665ee2d11574a"
    ),
    "dl-run-observation/v1": (
        "8f3747c5c12c4f420c0c1c0d65d29c258183871e678d42a50214ad2e53d61ba2"
    ),
    "dl-same-host-reproducibility-report/v1": (
        "77d2c0508bb51fbd527896f56dd90a9314720a615008adf9e57317f675ee8eab"
    ),
    "evaluation-contract/v1": (
        "8d28c5756a2ec8f90341562bbfbdd605350c3bc52cb3a6b03bfd6eac4b02d1ab"
    ),
    "evaluation-contract/v2": (
        "74c6e459eded8f376c52bbe352567c8dd047c87d145f9002272fe86595049b01"
    ),
    "evaluation-contract/v3": (
        "9e2a7125b4b53b23b6d11ddf2164e055351c561e8add62acaf6aff7a37940c81"
    ),
    "math-case/v1": (
        "9836f8c7af72b063942e002acf63cf57255886c23e7981fa6495c704ac9ddac0"
    ),
    "math-claim/v1": (
        "a2d27809a0dedf7486f2f9136e433005c8c67e9ce7a290c236c974089166a0ab"
    ),
    "math-evidence/v1": (
        "12d43f360b06ea18ee44407313d89befb72a137d3cb99de13e2a67f8292754f8"
    ),
    "math-task/v1": (
        "ebde1b55848120a664ba912dcf8ac2a34e23759ea9209207a9f30e491be5e464"
    ),
    "quant-case/v1": (
        "7a52cba8b1cd40c84249be15b3c6ad4625d204c2b549333fd7ab32c1c57843d7"
    ),
    "quant-claim/v1": (
        "78ef0f843afa098f2cbd49ffb497f6f6e353d3eb182be442260cb3f8d1f426e4"
    ),
    "quant-evidence/v1": (
        "06a6c54fd30eb83e3b7eea64c3afd92244ceae4447c01f5bac6272d4c2253b46"
    ),
    "quant-task/v1": (
        "26d71ed439531b946676f7e192ccdaaca1fcde003fe5fc381521a1705971e410"
    ),
    "ml-case/v1": (
        "db1a76c3c319affc78a4ecc075cd68f5efc5a042dd9994d8aeac3473f5cb5837"
    ),
    "ml-claim/v1": (
        "5476a90a25128d8cb8e56c85b1a4dde09feac1d07fb20df3a94acc6e00197d1e"
    ),
    "ml-evidence/v1": (
        "45482e3ee65ec4a094885fbd38dce350fc4054a3e5e866748122e02ca65c90a9"
    ),
    "ml-evidence/v2": (
        "1faba84d0d981a953df28ad0c118f29339c574d56092bb6922d3758ec2e32b39"
    ),
    "ml-task/v1": (
        "01c7b20405bc53acd9dc218730b15269958c16b344701f305985037bb97234b9"
    ),
}

# Golden pins (ADR-0004 decision 7): SHA-256 of each schema file's raw
# on-disk bytes. Newline stability is carried by .gitattributes.
ADAPTER_SCHEMA_TEXT_SHA256 = {
    "claim-assessment-v1.schema.json": (
        "c172cf54e70f1a3f6f01330e9b61a87e6e992ca05e20d8fe74e9182bd6ebc42e"
    ),
    "domain-task-v1.schema.json": (
        "3e49118d4d3b17b68fafc95a2f5dd7389eefe0a200acd0c5194bc5127d8faf61"
    ),
    "domain-task-v2.schema.json": (
        "a0d69dbc81f99262de4d1eb0b6d0e21b2e1270fcd57e83ded60c45bd0b8da775"
    ),
    "dl-checkpoint-recovery-observation-v1.schema.json": (
        "8671549b3686297276037dbcdc5045823072514a8e8fa20e3a8c11dacaab7687"
    ),
    "dl-run-manifest-v1.schema.json": (
        "9495f56a62691e81d4ca92025221672744bb8089bbcf80e322a0c7202c5c4acf"
    ),
    "dl-run-observation-v1.schema.json": (
        "9c791d59e998b6f411223054b93c36cd273381c8108231a2e561c4ef125db225"
    ),
    "dl-same-host-reproducibility-report-v1.schema.json": (
        "25e311b8c82e2333da7294a71dbbe4d0167c8a7241e832c5f3ff193c85fec266"
    ),
    "evaluation-contract-v1.schema.json": (
        "ab8294815264af74b19d325c7e1bd9e70bf938d4a39192736aee6a5d3e65be27"
    ),
    "evaluation-contract-v2.schema.json": (
        "324a00414ad44653d2b3ed5e966221eced350e0cfa49ca9781e40c8fa209368a"
    ),
    "evaluation-contract-v3.schema.json": (
        "85f504a336a50fc544123544e023d66d7aa08566e2da6756bfa148ac604566ae"
    ),
    "math-case-v1.schema.json": (
        "6c17344f768b6294468cd2d869b2820aa2f85ff33ccb8e9ba62e1071f38b4faa"
    ),
    "math-claim-v1.schema.json": (
        "9823d6b3dc2a55683e007fe1b2ca2171f4e9284ae6e4626d990f0b4c7facb448"
    ),
    "math-evidence-v1.schema.json": (
        "ff88b52782b66c5160afe1d9b2cb004ee09692be0d4af1cd5c48701d89cf1179"
    ),
    "math-task-v1.schema.json": (
        "2794bee04967dc9c784e523de36bb926d68e0e2057f15ed82cd969981e74984a"
    ),
    "quant-case-v1.schema.json": (
        "e7c6e8bb0e0cbb258be65a0bd9629e916dd89f0264312494dc86d827c6aa26ac"
    ),
    "quant-claim-v1.schema.json": (
        "a154a8b805ca2f6716927826acd0db4a44c2a8c69a098176f0ea1c902f86e940"
    ),
    "quant-evidence-v1.schema.json": (
        "c6de86dc72403c1de8d50ab493d092ece7d82222582d14b0f80bd53a0dec31ef"
    ),
    "quant-task-v1.schema.json": (
        "80a0c41c517a28f91154b3400ebc58566eecf8ce892fe958f1647de217793f33"
    ),
    "ml-case-v1.schema.json": (
        "6c62f0d57ed3e791488496f2496e0b8c82d595dab127b2fd3e855393267ad6b0"
    ),
    "ml-claim-v1.schema.json": (
        "0d549e740615e60e2abc9790c9ba2dc8980e01b9be4d8a96cf8b3cee5a3ed22f"
    ),
    "ml-evidence-v1.schema.json": (
        "9e570378326ecafb942c6cda2a61fbf829c41f7c7fe59af49a2de60d0bdafb9b"
    ),
    "ml-evidence-v2.schema.json": (
        "2cc375e9bdde843b2458e456a0eb940c52c43fdd6c52a4c6eb2d0eed32ca0679"
    ),
    "ml-task-v1.schema.json": (
        "abef4cba8d8e36815f58d51aa78e31a8581872b8b7a432f9ca1deba5a0687637"
    ),
}


def _fixture_dir(schema_id: str, kind: str) -> Path:
    family, version = schema_id.split("/")
    return FIXTURES_ROOT / family / version / kind


def _manifest_files() -> set[str]:
    expected: set[str] = set()
    for schema_id, groups in ADAPTER_FIXTURE_MANIFEST.items():
        family, version = schema_id.split("/")
        for name in groups["valid"]:
            expected.add(f"{family}/{version}/valid/{name}")
        for name in groups["invalid"]:
            expected.add(f"{family}/{version}/invalid/{name}")
    return expected


class AdapterFixtureManifestTest(unittest.TestCase):
    def test_fixture_tree_matches_manifest_bidirectionally(self) -> None:
        on_disk = {
            path.relative_to(FIXTURES_ROOT).as_posix()
            for path in FIXTURES_ROOT.rglob("*")
            if path.is_file()
        }
        self.assertEqual(_manifest_files(), on_disk)

    def test_every_schema_has_valid_and_invalid_fixtures(self) -> None:
        for groups in ADAPTER_FIXTURE_MANIFEST.values():
            self.assertGreaterEqual(len(groups["valid"]), 2)
            self.assertGreaterEqual(len(groups["invalid"]), 5)


class AdapterFixtureBehaviorTest(unittest.TestCase):
    def test_valid_fixtures_load(self) -> None:
        for schema_id, groups in ADAPTER_FIXTURE_MANIFEST.items():
            for name in groups["valid"]:
                path = _fixture_dir(schema_id, "valid") / name
                with self.subTest(fixture=f"{schema_id}/valid/{name}"):
                    record = load_record(path.read_bytes(), schema_root=SCHEMA_ROOT)
                    self.assertEqual(record.schema_id, schema_id)

    def test_invalid_fixtures_fail_with_expected_error(self) -> None:
        for schema_id, groups in ADAPTER_FIXTURE_MANIFEST.items():
            for name, (error_name, reason) in groups["invalid"].items():
                path = _fixture_dir(schema_id, "invalid") / name
                with self.subTest(fixture=f"{schema_id}/invalid/{name}"):
                    with self.assertRaises(CoreError) as ctx:
                        load_record(path.read_bytes(), schema_root=SCHEMA_ROOT)
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
                    # One failure category per invalid fixture.
                    violations = getattr(ctx.exception, "violations", None)
                    if violations is not None:
                        self.assertEqual(
                            len(violations),
                            1,
                            f"fixture should isolate one violation: {ctx.exception}",
                        )

    def test_minimal_fixture_hashes_are_golden_pinned(self) -> None:
        for schema_id, expected in MINIMAL_FIXTURE_SHA256.items():
            path = _fixture_dir(schema_id, "valid") / "minimal.json"
            with self.subTest(fixture=f"{schema_id}/valid/minimal.json"):
                record = load_record(path.read_bytes(), schema_root=SCHEMA_ROOT)
                self.assertEqual(record.sha256, expected)

    def test_reloading_is_deterministic(self) -> None:
        for schema_id, groups in ADAPTER_FIXTURE_MANIFEST.items():
            for name in groups["valid"]:
                path = _fixture_dir(schema_id, "valid") / name
                first = load_record(path.read_bytes(), schema_root=SCHEMA_ROOT).sha256
                second = load_record(path.read_bytes(), schema_root=SCHEMA_ROOT).sha256
                self.assertEqual(first, second, f"nondeterministic hash for {path}")


class AdapterSchemaIntegrityTest(unittest.TestCase):
    def test_registry_loads_exactly_the_twenty_three_adapter_schemas(self) -> None:
        registry = SchemaRegistry(SCHEMA_ROOT)
        self.assertEqual(
            registry.schema_ids,
            (
                "claim-assessment/v1",
                "dl-checkpoint-recovery-observation/v1",
                "dl-run-manifest/v1",
                "dl-run-observation/v1",
                "dl-same-host-reproducibility-report/v1",
                "domain-task/v1",
                "domain-task/v2",
                "evaluation-contract/v1",
                "evaluation-contract/v2",
                "evaluation-contract/v3",
                "math-case/v1",
                "math-claim/v1",
                "math-evidence/v1",
                "math-task/v1",
                "ml-case/v1",
                "ml-claim/v1",
                "ml-evidence/v1",
                "ml-evidence/v2",
                "ml-task/v1",
                "quant-case/v1",
                "quant-claim/v1",
                "quant-evidence/v1",
                "quant-task/v1",
            ),
        )

    def test_schema_text_bytes_are_golden_pinned(self) -> None:
        on_disk = {path.name for path in SCHEMA_ROOT.glob("*.schema.json")}
        self.assertEqual(set(ADAPTER_SCHEMA_TEXT_SHA256), on_disk)
        for name, expected in sorted(ADAPTER_SCHEMA_TEXT_SHA256.items()):
            with self.subTest(schema=name):
                raw = (SCHEMA_ROOT / name).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)


class SeamBoundaryTest(unittest.TestCase):
    """ADR-0005 decision 1: adapter schemas are not core record families."""

    def test_adapter_schema_ids_are_unknown_to_the_core_default_root(self) -> None:
        for schema_id in ADAPTER_FIXTURE_MANIFEST:
            path = _fixture_dir(schema_id, "valid") / "minimal.json"
            with self.subTest(schema=schema_id):
                with self.assertRaises(UnknownSchemaError):
                    load_record(path.read_bytes())

    def test_core_registry_does_not_register_adapter_schemas(self) -> None:
        core_registry = SchemaRegistry(CORE_SCHEMA_ROOT)
        for schema_id in ADAPTER_FIXTURE_MANIFEST:
            with self.subTest(schema=schema_id):
                self.assertFalse(core_registry.has(schema_id))


if __name__ == "__main__":
    unittest.main()
