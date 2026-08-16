# Core schemas

领域无关记录的版本化 JSON Schema。

已实现：`research-task/v1`、`research-claim/v1`、`research-evidence/v1`、`research-run/v1`、`research-failure-observation/v1`、`research-failure-analysis/v1`、`research-case-package/v1`（前三个见 `docs/architecture/core-interface.md`；后四个为 Phase 1C schema 层交付，发布与图校验支持分别在 C3/C4 落地，当前不可发布）。

计划中但未实现：EvaluationCase、CandidateBundle、PromotionDecision。这些条目仍是空白契约，不表示 schema 已实现。ExperiencePacket 已定性为 Experience Exporter 的派生产物，不作为 Core schema（ADR-0003 决策 9）。
