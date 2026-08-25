# Core schemas

领域无关记录的版本化 JSON Schema。

已实现：`research-task/v1`、`research-claim/v1`、`research-evidence/v1`、`research-run/v1`、`research-failure-observation/v1`、`research-failure-analysis/v1`、`research-case-package/v1`、`export-decision/v1`、`export-receipt/v1`（Phase 1）、`evaluation-case/v1`、`suite/v1`、`evaluation-run/v1`、`comparison-report/v1`（Phase 3，ADR-0006）、`evaluation-attempt/v1`、`evaluation-result/v1`（Correctness Reset CR4，ADR-0011）、`suite-comparison/v1`（Correctness Reset CR5，ADR-0012）、`artifact-record/v1`、`evaluation-envelope-closure-receipt/v1`（Correctness Reset CR6，ADR-0013）、`research-case-package/v2`、`research-pattern/v1`、`heuristic/v1`、`reuse-event/v1`（Phase 4，ADR-0007），`candidate-manifest/v1`、`artifact-closure-receipt/v1`、`context-bundle/v1`（Phase 7 P7A，ADR-0010），以及 `context-material-assessment/v1`、`context-bundle/v2`（Correctness Reset CR8，ADR-0015）——二十七个均可发布，且图校验在同一提交中完整认识每个 family（见 `docs/architecture/core-interface.md`）。全部 schema 文本由合同测试的 golden SHA-256 pin 逐字节冻结，演进规则见 `docs/governance/SCHEMA_COMPATIBILITY.md`。

`comparison-report/v1` 作为已冻结历史 family 保持可读取、可渲染和可验证，但其按单个 run 的 metric dimensions 构造统计样本的公开 `compare()` 入口已在 CR5 退役并 fail-closed。新建比较必须使用 `suite-comparison/v1`：观测单位固定为完整 `case × seed × frozen envelope` 配对网格，指标分别分析，且显式记录预注册方向/角色、ROPE 或 guardrail 非劣效界值、paired permutation、paired bootstrap、Holm 调整和效应量。该 family 不是 `PromotionDecision`。

CR6 不改 P7A 三个 v1 family，而以 `artifact-record/v1` 和 `evaluation-envelope-closure-receipt/v1` 补上完整 evaluation-envelope 闭包。receipt pin 既有 candidate manifest 和恰好八个 Artifact records，并覆盖 candidate member bytes、authoritative head、tools、budget、public data、evaluator、generator、统计计划与 rollback target。`core_store` 必须提供精确 bytes，`bundle_member` 必须解析到 candidate member；只有 evaluator configuration 可使用 `hidden_evaluator`，且禁止 locator/明文输入并要求 principal-separated byte attestation。该 attestation 不是密码学身份或真实 hidden evaluator 执行证据。

CR8 保持 `context-bundle/v1` 冻结，以 plaintext-free `context-material-assessment/v1` 和 `context-bundle/v2` 增加 classification/taint、redaction/export disposition、retention/encryption/tombstone descriptor 与 byte/token 双预算。`prepare_context` 要求 policy 与 candidate materials 精确一一对应；restricted plaintext 在 builder 与 wrapper 两条路径均 fail-closed。token 数只是 UTF-8 byte upper-bound preflight estimate，外部 protected artifact 也只是 hash descriptor；两者均不构成 runtime usage、storage、身份或语义验证证据。

计划中但未实现：CandidateBundle、SkillCandidateBundle、PromotionDecision（Phase 4 显式不交付，ADR-0007 决策 1）。这些条目仍是空白契约，不表示 schema 已实现。ExperiencePacket 已定性为 Experience Exporter 的派生产物，不作为 Core schema（ADR-0003 决策 9）。
