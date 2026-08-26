# ADR-0024：P7D1B 公开失败到真实 Skill Candidate 提案接口

- 状态：Accepted
- 日期：2026-08-26
- 范围：Phase 7 P7D1B engineering seam

## 背景

P7D1A 可以在一次预注册公开 baseline session 获得确定性失败后，生成
`research-run/v1`、`research-failure-observation/v1`、
`research-failure-analysis/v1` 和 `research-case-package/v2`。P7B1—P7B4
已经提供 Candidate manifest、byte closure、eligibility、Skill payload、静态验证和
语义审查协议。缺失的是一个窄接口：只有多个不同 lineage 的公开失败被同一个
Pattern 精确引用时，才允许调用一次 Candidate generator，并把输出映射到现有闭包。

## 决策

1. 新增唯一行为接口
   `propose_skill_candidate(plan, generator) -> SkillCandidateProposalOutcome`。
2. Module 在任何 generator 调用前验证：
   - 2—6 个 `research-case-package/v2`；
   - 每个 case 均为 `privacy_review_status=passed`、eligible、
     `benchmark_candidate` 且带 observation/analysis；
   - `independence_group`、`origin_run_id`、`dataset_lineage_id`、
     `task_template_id`、`semantic_duplicate_group` 五个维度逐项无碰撞；
   - 一个 `candidate_pattern`、`validated_pattern` 或 `active_pattern` 状态的
     `research-pattern/v1` 精确 pin 全部 source cases；
   - retry 为零、provider seed 未伪造，真实 Codex policy 为 read-only、
     approval-never、no-web、ephemeral。
3. generator 只调用一次。deterministic Adapter 用于 Math/Quant synthetic
   contract；Codex CLI Adapter 复用 P7C3 已验证的最小权限 launcher。
4. generator 只返回 `SKILL.md`、`agents/openai.yaml`、trigger/exclusion、七项
   eligibility evidence 和 lifecycle 文本。原始 trace、stderr 和 session ID 不进入
   Candidate；仅保留 hash 与 usage。临时 workspace 必须被安全删除。
5. 成功输出依次映射到既有对象：

   ```text
   candidate-manifest/v1
   -> artifact-closure-receipt/v1
   -> candidate-eligibility-attestation/v1
   -> skill-candidate-bundle/v1
   ```

   manifest closure 同时包含 baseline marker、Candidate payload descriptor、预注册
   test plan、每个 source case、共享 Pattern 和七项 criterion evidence 的精确字节。
6. plan 失效在 generator 调用前抛出；进程/解析/session/cleanup 失败返回
   `proposal_inconclusive`；受限内容或结构不闭合返回 `proposal_rejected`。两者均不
   产生 Candidate bundle，也不自动重试。

## Schema 映射证明

本批没有不可表达字段，因此不新增 successor schema：

| P7D1B 语义 | 既有表达 |
| --- | --- |
| source case/pattern pin、baseline/patch/tests、风险与 authoritative head | `candidate-manifest/v1` |
| 全部成员精确字节、DAG 与 receipt-last | `artifact-closure-receipt/v1` |
| 五维 lineage、至少两个 source cases、七项条件与 blockers | `candidate-eligibility-attestation/v1` |
| `SKILL.md`、`agents/openai.yaml`、trigger/exclusion 与 payload/evidence closure | `skill-candidate-bundle/v1` |
| generator session/turn、trace/stderr hash、usage 与 workspace cleanup | 非发布 `SkillCandidateProposalOutcome` |

generator 过程事实不构成新的长期 Core family；只有 Candidate 的不可变内容和既有
治理对象需要进入图。因此新增 schema 会重复现有边界。

## Evidence ceiling

Math/Quant fixtures 只证明 engineering contract。即使 P7D2 后续得到一次真实 Codex
Candidate，该结果仍只是 proposal：generator 与 criterion evidence 不是独立 reviewer，
lineage labels 不是外部身份验证，byte closure 不证明语义质量或行为改善。P7D1B 不执行
Candidate，不完成 fresh-session、hidden evaluation 或 PromotionDecision，也不授权
物化到仓库、安装、激活、发布或 Phase 8。

## 验证

- Math/Quant synthetic accept 和 explicit reject fixtures；
- source case deletion、Pattern pin mutation 和 lineage collision 在调用前拒绝；
- strict JSON、output limit、runner error 均一次调用、零重试、无 Candidate；
- 受限 plan/output 不回显敏感值；
- 真实 evidence class 缺 session 或 completed turn 时 inconclusive；
- Module export 只有一个 `propose_*` 行为接口。
