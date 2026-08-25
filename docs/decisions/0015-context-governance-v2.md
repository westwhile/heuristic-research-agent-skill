# ADR-0015：Context material 治理与双预算 successor

- 状态：Accepted（Correctness Reset CR8）
- 日期：2026-08-25
- 范围：Phase 7 Context transfer 的隐私、taint、生命周期与模型输入预算

## 背景

P7A 的 `context-bundle/v1` 已冻结三档 retention、canonical byte budget 与
minimal-safe fail-closed，但它没有表达 material classification、taint、redaction
receipt、export disposition、retention expiry、encryption 或模型 token 估算。CR1
的 restricted-content scanner 关闭了可直接复现的 secret/PII/path 入口，不能替代
完整治理判断。v1 已发布，不能原地扩大语义。

## 决策

1. **additive successor**：保持 `context-bundle/v1` schema、fixture、golden hash
   和 `build_context_bundle` 行为逐字节不变；新增
   `context-material-assessment/v1` 与 `context-bundle/v2`。
2. **单一深模块 interface**：调用方只通过
   `prepare_context(candidate, material_policies, mode, byte/token budget, built_at)`
   获得全部 immutable assessments 与一个 v2 bundle。扫描、hash、mode partition、
   lifecycle 和预算计算隐藏在 implementation 内，不暴露浅层 helper。
3. **assessment 无明文**：assessment 只保存 source content hash/size、分类、source
   与 residual taint、scanner identity/policy hash、redaction output/receipt hash、export
   outcome、retention、encryption 和可选 tombstone descriptor。它不保存 source 或
   redacted plaintext。
4. **四种 disposition**：`include_original` 只允许 public/internal-safe 且零 taint；
   `include_redacted` 要求安全 output classification、零 residual taint、output hash 与
   receipt hash；`protected_hash_only` 只保留 confidential/restricted 的加密外部 artifact
   descriptor；`reject` 不保留内容。任一组合不闭合都 fail closed。
5. **builder 与 wrapper 同时扫描**：candidate、policy metadata、redacted output、
   assessment wrapper 和 bundle wrapper 均执行 restricted-content scan；错误只返回字段与
   pattern class，不回显命中值。调用方不能绕过 builder 直接构造可发布 wrapper。
6. **两个预算独立**：v2 继续约束 canonical record bytes，并记录 tokenizer id/revision、
   `text_utf8_bytes_upper_bound/v1` 估算与 `max_tokens`。估算只作 preflight hard gate，明确
   不声称模型 runtime token usage；未来 execution attempt 必须另记实际 usage。
7. **图合同原子落地**：assessment pin candidate；v2 bundle pin candidate 和全部
   assessments。两个 family 与 schema 在同一提交进入 family registry。
8. **证据上限**：CR8 只证明合成 contract 下的 context governance fail-closed；principal、
   classification 和外部 artifact metadata 仍是协议声明。它不执行 Candidate Agent、
   不完成 semantic review，不授权 Skill 安装、激活、发布或 Promotion。

## 拒绝方案

1. 修改 `context-bundle/v1`：破坏已发布 schema 与历史记录的字节合同。
2. 仅在 builder 扫描：调用方可通过 `from_payload` 绕过 restricted-content Gate。
3. 把 confidential/restricted plaintext 放进 append-only bundle 后再标记加密：标签不能
   撤销已经发生的明文持久化。
4. 把 UTF-8 byte estimate 表述为模型实际 token 数：tokenizer 与 runtime usage 未执行，
   会制造超出证据的精确性主张。

## 后果

调用方必须对 candidate 中每个 material 提供一行治理 policy，缺失或额外 policy 均失败。
CR8 增加 schema/fixture/graph/contract 面，但保持 v1 完整兼容。受限 material 的外部 artifact
descriptor 只由供应的 hash 绑定，尚不是 Core 可解析 artifact family，也不证明其 storage、
加密或 tombstone 真实存在；该限制必须保留到后续 artifact lifecycle successor。
