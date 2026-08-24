# Core schemas

领域无关记录的版本化 JSON Schema。

已实现：`research-task/v1`、`research-claim/v1`、`research-evidence/v1`、`research-run/v1`、`research-failure-observation/v1`、`research-failure-analysis/v1`、`research-case-package/v1`、`export-decision/v1`、`export-receipt/v1`（Phase 1）、`evaluation-case/v1`、`suite/v1`、`evaluation-run/v1`、`comparison-report/v1`（Phase 3，ADR-0006）、`research-case-package/v2`、`research-pattern/v1`、`heuristic/v1`、`reuse-event/v1`（Phase 4，ADR-0007），以及 `candidate-manifest/v1`、`artifact-closure-receipt/v1`、`context-bundle/v1`（Phase 7 P7A，ADR-0010）——二十个均可发布，且图校验在同一提交中完整认识每个 family（见 `docs/architecture/core-interface.md`）。全部 schema 文本由合同测试的 golden SHA-256 pin 逐字节冻结，演进规则见 `docs/governance/SCHEMA_COMPATIBILITY.md`。

计划中但未实现：CandidateBundle、SkillCandidateBundle、PromotionDecision（Phase 4 显式不交付，ADR-0007 决策 1）。这些条目仍是空白契约，不表示 schema 已实现。ExperiencePacket 已定性为 Experience Exporter 的派生产物，不作为 Core schema（ADR-0003 决策 9）。
