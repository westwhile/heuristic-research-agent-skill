# ADR-0016：Candidate eligibility 前置证明

- 状态：Accepted（Phase 7 P7B1）
- 日期：2026-08-25
- 范围：可复用 Skill 候选进入 payload drafting 前的 eligibility Gate

## 背景

P7A/CR6 已能证明 Candidate member 与 evaluation envelope 的字节闭包，CR8 已补上
context material 治理；这些事实都不能回答“该对象是否值得构造成可复用 Skill”。仅按
`case_id` 数量、作者自行勾选或目录存在判定，会把同一 run、同一问题模板、一次性答案、
项目脚本或快速变化知识错误升级为候选。

## 决策

1. 新增 domain-neutral Core family `candidate-eligibility-attestation/v1`。它同时 pin
   exact `candidate-manifest/v1`、`artifact-closure-receipt/v1` 与全部来源
   `research-case-package/v2`；图 registry 与 schema 同提交认识三类引用。
2. 单一纯 in-process interface 为
   `assess_candidate_eligibility(manifest, closure_receipt, assessment,
   evidence_bytes, assessed_at)`。调用方提供七项 criterion 的精确 evidence bytes；输出
   只保存名称、SHA-256 与大小，不保存 evidence 明文，不读写文件系统。
3. 七项 criterion 固定为：正触发、排除条件、稳定输入、稳定输出、失败/暂停边界、可移植
   资源与可测量增益计划。每项状态必须是 `satisfied`、`unsatisfied` 或 `unverified`，且
   criterion/evidence 集合精确、无遗漏、无额外项、无重复。
4. 来源 Case 必须与 manifest 等集合、等 pin，并显式声明 `independence_group`、
   `origin_run_id`、`dataset_lineage_id`、`task_template_id` 与
   `semantic_duplicate_group`。independence/origin/dataset/template/semantic group 任一碰撞均产生
   `ineligible`；不再按不同 Case ID 直接计作独立问题。
5. 仅 `reusable_skill_proposal` 可通过 kind Gate。`project_specific_script`、
   `one_off_answer` 与 `rapidly_changing_knowledge` 都产生稳定、可审计的 `ineligible`。
6. outcome 的确定性优先级为：任一硬 blocker 或 `unsatisfied` → `ineligible`；无硬
   blocker 但存在 `unverified` → `needs_more_evidence`；其余才是
   `eligible_for_payload_drafting`。reject/inconclusive 都是合法终态，不伪造 PASS。
7. assessor 仅验证 principal label 与 author label 不同；lineage、principal 与 criterion
   语义仍是协议声明。wrapper 直接构造会重新计算 ID、blockers 与 outcome，并执行受限
   内容扫描，不能绕过 builder。
8. `eligible_for_payload_drafting` 只允许进入后续 P7B2 草拟阶段。本批不生成 `SKILL.md`
   或其他真实 Skill payload，不实施 semantic/fresh-session/private evaluation，不生成
   PromotionDecision，不授权 publication、installation 或 activation。

## 结果与保留风险

P7B1 关闭了按 ID 计数和非可复用对象进入候选构造的工程入口，并让缺证据与明确失败均可
发布为不可变事实。它没有验证外部身份、真实问题独立性或 evidence 内容的真实性；这些
hash descriptor 也尚不是 Core 可解析 Artifact，后续使用前必须在 P7B2 纳入新的闭包。
真实身份与内容真实性必须由后续独立 semantic review、fresh-session 和 private evaluator Gate 完成。Math 与
Quant 合成 fixture 只证明同一 seam 的领域中性，不证明真实领域增益。

## 拒绝方案

1. 在 Candidate Manifest 上追加可变 eligibility 字段：会改变已冻结 v1，并混淆提议与
   后续事实；改用 additive attestation。
2. 只要求两个不同 `case_id`：无法排除同一 run、模板或语义重复组；改为 lineage 声明与
   多轴碰撞 Gate。
3. eligibility PASS 直接生成或安装 Skill：越过 semantic、fresh-session、private review
   与人工 publication 决策；明确推迟到后续独立批次。
