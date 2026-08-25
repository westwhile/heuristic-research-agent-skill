# ADR-0013：ArtifactRecord 与完整 Evaluation Envelope Closure

- 状态：Accepted（Correctness Reset CR6）
- 日期：2026-08-25
- 关联：ADR-0010（P7A candidate member closure）、ADR-0012（suite-level statistics）、`candidate-manifest/v1`

## 背景

P7A `close_candidate_bundle()` 只逐字节验证 `members`。`candidate-manifest/v1` 的 tools、budget、data、evaluator 和 authoritative head 只有裸 content hash，generator configuration、统计计划及可复现 rollback target 也没有统一 Core 对象。由此可能签发 `byte_closed=true`，但真正重放候选比较所需的 evaluation envelope 仍没有形成可解析图闭包。

既有 P7A 三个 v1 family 已冻结，不能原地扩大 `artifact-closure-receipt/v1` 的主张。CR6 只关闭工程层面的 artifact/pin/byte closure 缺口；不执行 Candidate Agent、不运行 hidden evaluator、不完成语义评审，也不生成 PromotionDecision。

## 决策

1. **additive family**：新增 `artifact-record/v1` 与 `evaluation-envelope-closure-receipt/v1`。ArtifactRecord 是内容寻址描述；receipt pin 既有 `candidate-manifest/v1` 及全部 ArtifactRecords。两个 family 与 Core graph registry 同提交注册。
2. **统一 ArtifactRef**：receipt 中每项固定包含 `artifact_id`、Core record `sha256` pin、`role`、`media_type`、`content_sha256`、`size_bytes`、`storage_class`、可选安全相对 `locator` 与 `redaction_state`。Core record pin 和内容 byte hash 分开命名，避免把“记录哈希”与“工件哈希”混成一个字段。
3. **闭包角色等集合**：每张 receipt 必须恰好覆盖并确定性排序八个角色：authoritative head snapshot、tool configuration、budget configuration、public data manifest、evaluator configuration、generator configuration、statistical plan 与 rollback target。缺少、额外、重复角色一律失败。
4. **三种 storage class**：`bundle_member` 必须解析到并逐字节匹配 candidate member；`core_store` 必须由调用方提供精确 bytes 并匹配 ArtifactRecord；`hidden_evaluator` 禁止 locator 与 bytes 输入，只允许 evaluator configuration，并要求记录内携带不披露内容的 byte attestation。
5. **裸 hash 对账**：authoritative head、tools、budget、public data、evaluator 的 ArtifactRecord content hash 必须与 `candidate-manifest/v1` 的既有字段完全相等；rollback ArtifactRecord 必须绑定 manifest rollback UTF-8 bytes。generator/statistical plan 由新增 ArtifactRecord 提供缺失的可解析对象。
6. **隐藏边界**：hidden evaluator attestation 必须声明 bytes 已观察、内容未披露、语义评审未完成，并回显相同 content hash/size；attestor principal 必须不同于 candidate author/reviewer。principal 字符串不是密码学身份或真实组织独立性证明，因此 receipt 只记 `hidden_bytes_disclosed=false`，不声称 hidden evaluator 已执行。
7. **receipt root**：closure root 覆盖 candidate pin、完整 member rows/DAG/exclusions、required roles、全部 ArtifactRefs、false claims 与 limitations；receipt ID 再绑定 candidate、closed_at 和 root。任一 member、artifact pin、content hash、role、storage 或 boundary flag 漂移都使 wrapper 或 Core graph fail closed。
8. **纯 in-process deep module**：唯一入口 `close_evaluation_envelope()` 不读取文件系统、不访问网络、不安装/激活/发布任何对象。调用方显式提供 candidate、member bytes、ArtifactRecords 和公开 artifact bytes；没有第二实现，不引入 repository/port/plugin 表面。
9. **证据上限**：Math/Quant 合成 fixtures 只证明同一 closure seam、mutation discipline 和 Core pin graph。`evaluation_envelope_closed=true` 表示“公开 bytes 已验证、隐藏 evaluator bytes 已按协议 attest”，不表示任务输出正确、候选更优、blind holdout、真实独立 reviewer、外部采用或科研有效性。

## 后果

收益：P7A 的 candidate member closure 与比较所需配置不再断开；公开依赖不能只写一个无法解析的 hash；隐藏 evaluator 内容不会通过 candidate-side closure 接口泄漏；后续 sandbox runner 可以消费一张确定性的完整 envelope receipt。

代价：调用方必须为八个角色构造并保存 ArtifactRecords；公开 core-store 依赖在 closure 时仍需提供 bytes；hidden attestation 的真实身份、权限隔离与签名留给独立 evaluator 批次；既有 `artifact-closure-receipt/v1` 继续只代表 member byte closure，不能被追溯升级。

## 拒绝的方案

1. **原地扩展 P7A v1 schema**：违反冻结 schema 与历史 receipt 语义。
2. **保留裸 hash 并在文档里声称可解析**：没有对应 bytes 或 Core record，不能重放也不能图验证。
3. **把 hidden locator 写进公开 manifest**：暴露位置与访问边界；hidden evaluator 必须无 locator、无 candidate-side bytes。
4. **接受 author/reviewer 自己 attestation hidden bytes**：形式上不独立；即便 principal 分离通过，仍不把字符串升级为真实身份认证。
5. **CR6 同时接入真实 Agent runner/PromotionDecision**：混合 closure、执行和决策三个风险面，无法保持可审查的证据边界。
