# ADR-0017：Skill Candidate Bundle 草拟与证据闭包

- 状态：Accepted（Phase 7 P7B2）
- 日期：2026-08-25
- 范围：P7B1 eligibility 通过后的候选 Skill payload 草拟与 evidence byte closure

## 背景

P7B1 能决定一个 byte-closed Candidate 是否可以进入 payload drafting，但七项 criterion
evidence 仍只是名称、SHA-256 与大小描述符。若下一阶段只生成一个 `SKILL.md` 目录而不把
这些 evidence bytes 纳入新的闭包，后续 reviewer 无法确定看到的证据是否就是 eligibility
时绑定的字节；若直接把 evidence 放进可安装 payload，又会把治理材料和运行时 Skill
混在一起。

## 决策

1. 新增 domain-neutral Core family `skill-candidate-bundle/v1`。它直接 pin exact
   `candidate-manifest/v1`、`artifact-closure-receipt/v1`、
   `candidate-eligibility-attestation/v1` 和全部来源 `research-case-package/v2`；Core graph
   与 schema 同提交认识这些引用。
2. 单一纯 in-process interface 为
   `draft_skill_candidate_bundle(eligibility_attestation, skill_contract,
   payload_bytes, eligibility_evidence_bytes, drafted_at)`。它不读写文件系统、不调用 Skill
   初始化器、不安装或加载任何 payload。
3. 只有 outcome 为 `eligible_for_payload_drafting` 且 blockers 为空的 attestation 可进入。
   `needs_more_evidence` 与 `ineligible` 均在 payload 处理前 fail closed。
4. payload 与 eligibility evidence 是两个不相交的 member 集合，但共同进入一张
   `closure_root_sha256`。七项 evidence 名称、SHA-256、大小必须与 P7B1 attestation 精确
   一致；任一遗漏、额外、非 bytes、hash/size 漂移均失败。
5. 首版只接收严格 UTF-8 文本，payload/evidence 在闭包前执行不回显命中值的 restricted
   content scan。opaque/binary assets 推迟到有独立分类、许可与导出策略的 successor。
6. payload 必须恰有一个根 `SKILL.md`；frontmatter 只允许 `name` 与 `description`，且与
   skill contract 精确相等。其他成员只允许位于 `agents/`、`scripts/`、`references/`、
   `assets/`，角色由路径确定；辅助 README/CHANGELOG/安装指南不进入 Skill payload。
7. payload member DAG 必须无重复、悬空、自依赖或 cycle，并产生确定性拓扑序。closure root
   覆盖所有上游 pins、source cases、Skill/trigger/lifecycle contract、payload/evidence
   descriptors 与拓扑序；bundle ID 再绑定完整 record。
8. evidence 只属于 candidate governance closure，不进入可安装 payload。P7B2 不执行
   runtime discovery、trigger/Router 行为测试、semantic/fresh-session/private evaluation，
   不生成 PromotionDecision，也不授权 publication、installation 或 activation。

## 结果与保留风险

P7B2 关闭了“eligibility evidence 只有裸 hash、候选 payload 与证据不在同一闭包”的工程
缺口，并把 Skill Creator 的最小 frontmatter 与 progressive-disclosure 布局固化为静态
contract。Math/Quant 合成 fixture 只证明同一 seam 的领域中性和 mutation discipline；它们
不是可安装真实 Skill、真实 Agent 行为或外部采用证据。trigger/exclusion 文本的语义、来源
独立性与 reviewer 身份仍是协议声明；后续必须以独立 semantic review 和 fresh-session
forward test 绑定 exact bundle hash。

## 拒绝方案

1. 原地扩展 `candidate-manifest/v1` 或 eligibility v1：违反冻结 family 与事实轴分离。
2. 只关闭 `SKILL.md` 而保留 evidence 裸 hash：后续无法证明 reviewer 使用了同一证据字节。
3. 把 evidence 文件放进可安装 Skill：污染 runtime payload 并扩大隐私、许可和上下文面。
4. 在本批调用官方初始化器或写入 `skills/staging/`：会把结构合同测试升级成真实 Skill
   生成/安装动作，越过本批授权边界。
