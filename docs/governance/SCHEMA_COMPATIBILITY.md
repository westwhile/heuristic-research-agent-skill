# Schema 兼容性政策 v1

权威决策记录：[`docs/decisions/0004-privacy-export-compatibility.md`](../decisions/0004-privacy-export-compatibility.md) 决策 7。本文件是操作文本；冲突时以 ADR 为准。v0.2.0 Release notes 引用本政策。

## 规则

1. **已发布 schema 永不原地改变语义或字节。** 合同测试为每个 schema 文本持有 golden SHA-256 pin（自 Phase 1D/D2 起，在既有 minimal-fixture pin 之外）；任何对 `schemas/core/*.schema.json` 既有文件的改动必然破测试。pin 基准为 schema 文件的原始字节，换行稳定性由 `.gitattributes` 的 `*.json text eol=lf` 承担；与 minimal-fixture 的 canonical 内容 pin 基准不同，两者并存。需要变更时走规则 2。
2. **演进的唯一通道是新版本。** 新 `$id`（如 `research-claim/v2`）、新目录、新 fixtures、registry 新条目。旧版本 family 永久保留注册、可发布、可验证——append-only store 可能永远含有旧版本记录，内核不得在原地"升级"它们。
3. **successor 测试义务。** `/v(N+1)` 落地时必须自带全套 valid/invalid fixtures 与 golden pin（minimal/full + 按失败类别命名的 invalid），且全部 vN 测试零修改通过。缺失 successor 测试的 schema 版本不得合并。
4. **无兼容模式 flag。** 同一 `$id` 永不承载双语义；内核不提供 "lenient v1" 之类的开关。
5. **退役需新 ADR。** 从 registry 移除旧版本支持（不再可发布/可验证）要求新 ADR 与迁移路径。其 fail-closed 表现已文档化：未注册 family 发布抛 `PublicationError`，全图验证报 `record_invalid`——绝不静默误读。

## 检查清单（新 schema 版本落地时）

- [ ] 新 `$id` 与目录 `schemas/core/research-x-v2/`（文件名 == `$id` + `.schema.json`）；
- [ ] 全套 fixtures + golden pin 进入合同测试清单；
- [ ] registry 新条目与图语义同 commit（"可发布 ⇄ 图认识"）；
- [ ] 既有全部测试零修改通过；既有 schema 文本与 fixtures 字节零漂移；
- [ ] `core-interface.md` 与测试计数同步；
- [ ] 若退役旧版本：新 ADR 链接与迁移路径已就位。

## 适用范围

本政策覆盖 `schemas/core/` 全部已发布 schema。`schemas/adapters/` 的领域扩展遵循同一规则，版本节奏由各领域 Adapter 自行决定。
