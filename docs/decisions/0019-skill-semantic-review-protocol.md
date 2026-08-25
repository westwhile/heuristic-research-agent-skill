# ADR-0019：P7B4 Candidate 独立语义审查协议

- 状态：Accepted
- 日期：2026-08-26

## 背景

P7B3 能够对 exact Candidate payload、平台元数据、触发条件、registry
冲突和 descriptor diff 做静态验证，但静态通过不说明任务语义正确、
适用范围充分、负迁移风险可接受或 reviewer 真正独立。P7B4 需要先冻结
一个可审计协议，同时避免把合成 fixture 或不同字符串标签夸大为真实
独立审查。

## 决策

1. 新增 `skill-semantic-review-attestation/v1`，同时 pin exact
   `skill-candidate-bundle/v1` 与 exact
   `skill-static-validation-receipt/v1`。
2. 唯一公开 seam 为 `attest_skill_semantic_review_protocol(...)`。它只做
   纯 in-process 合同验证和收据构造，不调用模型、Agent、子进程、文件
   系统、安装器或网络。
3. review evidence 以安全相对名称、media type、SHA-256 和 byte size
   描述；调用方必须提供 exact UTF-8 bytes。受限内容扫描不完整、hash/
   size 不符或非法 UTF-8时 fail closed。
4. reviewer 声明记录 principal、kind、session、model、independence group
   和是否与 drafter 共享上下文。协议要求 reviewer 标签同时区别于
   drafter 和 static validator，且声明未共享上下文；这些字段不是外部
   身份证明。
5. 七个语义维度固定为任务正确性、范围与禁忌、触发精度、失败与暂停
   边界、负迁移、隐私与许可证、回滚与退役。每项必须绑定同一 evidence
   bytes，并取 `satisfied`、`unsatisfied` 或 `unverified`。
6. 全部 satisfied 才产生 `protocol_accept`；任一 unsatisfied 产生
   `protocol_reject`；任一 unverified 或任何协议 Gate 失败产生
   `protocol_inconclusive`。声明 outcome 不一致也 fail closed。
7. P7B4 的真实独立 semantic review、fresh-session/private evaluation、
   Promotion、发布、安装、激活和 runtime claims 全部固定为 false。

## 后果与证据边界

- Math/Quant 接受与拒绝 fixture 只验证同一协议 seam 的领域无关性。
- reviewer 字符串不同、session 不同和 shared-context=false 只能证明声明
  结构，不能证明真实人员、模型、组织或上下文隔离。
- P7B4 不执行 Candidate，不物化或安装 Skill，也不完成 PromotionDecision。
