# ADR-0026：P7D6 Candidate contract 脱敏诊断与确定性校准

- 状态：Accepted
- 日期：2026-08-30
- 范围：Phase 7 P7D6 Candidate proposal contract diagnostics

## 背景

P7D5 的一次真实 Candidate proposal 会话满足单次调用、执行完成、进程树清理与隐私
边界，但最终只能返回通用 `candidate_contract_invalid`。该 blocker 能阻止无效
Candidate，却不能区分生成输出合同、manifest、字节闭包、资格评估或 Candidate bundle
中的失败阶段。原始模型输出和底层异常消息又不能为了诊断而持久化或回显。

## 决策

1. 保持唯一公开行为接口
   `propose_skill_candidate(plan, generator) -> SkillCandidateProposalOutcome` 不变；不新增
   Core schema，也不创建第二条 Candidate 构建路径。
2. 非发布 outcome 增加 `failure_stage` 与 `failure_code`。`proposal_ready` 时两者必须均为
   `None`；非 ready 时只允许返回固定枚举语义，不得返回异常消息、Candidate 字段值、
   transcript、session id、stderr、工作区路径或第三方响应正文。
3. Candidate contract 的稳定分类为：

   | stage | code |
   | --- | --- |
   | `output_contract` | `strict_json_invalid`、`output_fields_invalid`、`restricted_content`、`output_value_invalid`、`trigger_contract_invalid`、`criterion_contract_invalid` |
   | `manifest` | `candidate_manifest_invalid` |
   | `closure` | `artifact_closure_invalid` |
   | `eligibility` | `candidate_eligibility_invalid` |
   | `candidate_bundle` | `skill_candidate_bundle_invalid` |

4. 执行、资源与清理失败继续形成 `proposal_inconclusive`，统一使用 `execution` stage；
   code 为现有稳定 blocker。未知 Adapter `error_class` 必须降格为
   `generation_runner_error`，不得把 Adapter 提供的字符串透传到 outcome。
5. 对外 blocker 保持兼容：受限内容仍为 `restricted_candidate_output`，其他 contract
   拒绝仍为 `candidate_contract_invalid`。新字段只加深诊断，不把失败升级成 Candidate。
6. 确定性校准使用与真实 Adapter 相同的唯一端口，覆盖 Math/Quant accept、缺失字段、
   payload frontmatter 不一致、受限内容、未知 runner error、删除/lineage mutation 与
   cleanup failure。校准不得调用模型、不得物化 Skill，也不得修改 lifecycle 状态。

## Schema 映射证明

诊断属于一次 proposal 调用的本地控制面结果，不是可发布研究记录、Candidate 内容或
lifecycle receipt。既有 `candidate-manifest/v1`、`artifact-closure-receipt/v1`、
Candidate eligibility 与 `skill-candidate-bundle/v1` 已能表达成功路径；失败路径没有
需要跨 Core 图引用的新事实，因此本批不新增 schema。

## 隐私与失败语义

- 内部异常只携带固定 stage/code；原始异常通过 exception chaining 留在瞬时进程内，
  不进入 outcome。
- restricted-content 扫描仍先于 Candidate 字节构建；被拒绝的原始输出不持久化。
- manifest、closure、eligibility 与 bundle 异常在各自边界被转换，调用者不能通过
  `repr(outcome)` 恢复 Candidate 字段值或私有错误细节。
- workspace cleanup 或 process-tree cleanup 未闭合时，contract 解析和 Candidate 构建均
  不执行。

## Evidence ceiling

本批只证明脱敏诊断与 deterministic contract 的工程行为。它不证明真实 Candidate
有效、Skill 可安装、行为改善、独立语义审查、fresh-session acceptance、hidden
evaluation、Promotion、发布、安装或激活；也不授权重试任何已消费的 P7D5 槽位。

## 验证

- 公开 interface 的 ready/rejected/inconclusive 三类结果均固定 stage/code 关系；
- Math/Quant accept 与 reject fixtures 通过同一生成端口；
- restricted output、未知错误类及底层异常正文不出现在 outcome；
- case deletion、lineage collision 与 Pattern pin mutation 在 generator 调用前失败；
- workspace/process-tree cleanup failure 保持 fail closed；
- exact archive 双解释器、clean-install、质量 Gate 与本机 CUDA regression 保持通过。
