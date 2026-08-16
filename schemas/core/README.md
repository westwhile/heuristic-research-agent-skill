# Core schemas

领域无关记录的版本化 JSON Schema。

已实现：`research-task/v1`、`research-claim/v1`、`research-evidence/v1`、`research-run/v1`、`research-failure-observation/v1`、`research-failure-analysis/v1`、`research-case-package/v1`（七个均可发布，且图校验在同一提交中完整认识每个 family——见 `docs/architecture/core-interface.md`）。

计划中但未实现：EvaluationCase、CandidateBundle、PromotionDecision。这些条目仍是空白契约，不表示 schema 已实现。ExperiencePacket 已定性为 Experience Exporter 的派生产物，不作为 Core schema（ADR-0003 决策 9）。
