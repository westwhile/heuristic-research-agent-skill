# ADR-0004：隐私/导出/兼容政策——三轴模型、export 记录与只读 CLI

- 状态：Accepted for Phase 1D
- 日期：2026-08-16

## 背景

ADR-0003 决策 8 把 Case v1 的隐私状态收窄为单轴 `pending` 并规定：许可与事实两个正交轴由 ADR-0004 以独立记录表达（建议命名 `export-decision/v1`、`export-receipt/v1`），永不回写 Case。总体计划 Phase 1 交付物同时要求：migration/compatibility policy、machine-readable validation report、只读命令行（`validate`/`hash`/`verify-graph`，不执行外部写入）。ARCHITECTURE.md §7 已冻结四值导出模式词表（`local_full` / `local_redacted` / `benchmark_candidate` / `metrics_only`）。Phase 1D 落地上述边界；不实现 redaction 执行器、导出执行通道或自动 secret/path 扫描器。

## 决策

1. **三轴隐私模型定名，边界为永久合同**：review 轴留在 Case（v1 固定 `pending`，不可变记录不承载状态迁移，扩词表只能走新 schema 版本）；permission 轴 = `export-decision/v1`；fact 轴 = `export-receipt/v1`。两轴正交、不得合并进同一枚举；均以 append-only 记录表达，**永不回写 Case**（Case schema 属性集封闭，物理上也无法回写而不升版本）。
2. **export_mode 词表取架构既有四值**：`local_full / local_redacted / benchmark_candidate / metrics_only`（ARCHITECTURE.md §7）。decision 与 receipt 双必填——deny 决定同样记录被拒绝的请求模式（"拒绝了 local_full 请求"是审计信息）。不引入"outcome=allow 才必填 mode"的条件必填：schema 引擎的条件关键字是数组导向，表达不了"枚举值→标量必填"，扩引擎即重复 `uniqueItems` 拒绝理由（与 `core-interface.md` §3.4 记录的 `fixed_seed`/`seed` 边界同一判据）。
3. **`export-decision/v1`**：identity `decision_id`；`case` 为恰好一个 hash-pin 的 Case 引用（单向、必 pin）；`outcome ∈ {allow, deny}`；`export_mode` 必填（决策 2）；`decided_by` 复用中性执行者结构（`tool`/`version`/可选 `model`，人工决定以 `tool` 标签表达）；`rationale` 必填非空白；`constraints` 必填可空字符串数组——v1 是意图记录而非执行合同（无 redaction 执行器）；`decided_at` RFC3339；`supersedes` ID-only、scope=anchor（锚=`case`），决定链沿同一 Case 展开。同一 Case 的并行决定（fork）只记 `report.forks` 信息位，Core 不提供"当前有效决定"选择语义——`unauthorized_export` 只看 receipt 锚定的那一条 decision；未来导出执行器的链选择策略另行决策。锚定已被 supersede 的 decision 的 receipt **不违规**：store 不含时钟，无法证明 receipt 与后继决定的先后——把该锚定标记为违规属不可证实主张，留待导出执行器的链选择策略处理。
4. **`export-receipt/v1`**：identity `receipt_id`；`decision` 为恰好一个 hash-pin 的 decision 引用（单向、必 pin）——导出事实必须挂在许可链上，不允许绕过 decision 直引 Case；`export_mode` 必填；`artifacts` ≥1 项，每项 `{name, sha256 必填, locator 可选且 x-safe-relative-path}`——离开的字节必须可审计，空 artifacts 拒绝；`destination` 是审计标签（非空白自由字符串），不是 locator——跨项目目的地本就不是仓库内路径，假装可验证是虚假语义，可验证性由 `artifacts` 的内容哈希承担；`exported_at` RFC3339。Receipt 无 `supersedes`：事实不修订，错记由治理流程处理，不引入 Core 语义。
5. **violation 合同 24→25，新增恰一种**：`unauthorized_export`——receipt 锚定的 decision 存在且 `outcome=deny`，或 receipt 的 `export_mode` 与该 decision 不符；每条违规 receipt 报一条，detail 指明哪种条件。decision 缺席由 `dangling_reference` 先行报告（不重复报）。其余全部检查由 registry 通用引用行走与 lineage 机器复用（`decision.case`、`receipt.decision` 的 dangling/cross_type/pin_mismatch；decision `supersedes` 的 self_reference/cycle/scope_mismatch），零新增。候选总数 **25（14 完整性 + 11 图）**，随本语义签署定稿。export 双 family 的引用语义表（表式对齐 ADR-0003 决策 6）：

   | 引用 | 方向 | pin | 违规 kind |
   |---|---|---|---|
   | decision.case → research-case-package/v1 | 单向 | 必须 | dangling_reference / cross_type_reference / pin_mismatch |
   | decision.supersedes → export-decision/v1 | 单向 | 无 | 既有 supersedes 各 kind + lineage_scope_mismatch（锚=case） |
   | receipt.decision → export-decision/v1 | 单向 | 必须 | dangling_reference / cross_type_reference / pin_mismatch + unauthorized_export（见上） |
6. **registry 扩展与原子性**：`export-decision/v1` 与 `export-receipt/v1` 是一个原子层——同一 commit 注册、可发布且图认识（receipt 的检查依赖 decision family，不可分层）。"可发布 ⇄ 图认识"原则与 `PublicInterfaceTest` 导出钉选不变；`duplicate_id` 全局唯一性自动覆盖九个 family。
7. **schema compatibility policy（正式合同，v0.2.0 Release notes 引用）**：① 已发布 schema 永不原地改变语义或字节——D2 起合同测试为每个 schema 文本加 golden SHA-256 pin（在既有 minimal-fixture pin 之外），任何 schema 文本改动必然破测试；pin 基准为 schema 文件的**原始字节**，跨平台换行稳定性由 `.gitattributes` 的 `*.json text eol=lf` 承担——与 minimal-fixture 的 canonical 内容 pin 属不同基准，两者并存；② 演进唯一通道是新 `$id`（`/v2`）+ 新目录 + 新 fixtures + registry 新条目，旧版本 family 永久保留注册、可发布、可验证（append-only store 可能永远含旧版本记录）；③ successor 测试义务：`/v(N+1)` 落地必须自带全套 valid/invalid fixtures 与 golden pin，且全部 vN 测试零修改通过；④ 无兼容模式 flag——同一 `$id` 永不承载双语义；⑤ 退役旧版本支持需新 ADR 与迁移路径，其 fail-closed 表现（未注册 family 发布抛 `PublicationError`、验证报 `record_invalid`）已文档化。操作文本落地为 `docs/governance/SCHEMA_COMPATIBILITY.md`，随本 ADR 同 commit 签署。
8. **CLI 边界**：`python -m research_evolution` 提供 `validate` / `hash` / `verify-graph` 三个子命令。**只读**：不创建、修改或删除任何文件，不做网络访问，不暴露 publish（写路径仅库 API）——1D 仍不能以纯命令行建 store，这是有意的误用面收缩。`--json` 输出 machine-readable report：严格 JSON、canonical 字节原样输出（report 自身可被 `load_strict_json` 消费、哈希稳定，dogfood 内核合同）；默认输出人类可读行。退出码：0 = ok；1 = 校验失败或存在 violation（结构化报告照常输出）；2 = 用法错误（argparse 自然返回）与**输入错误**——CLI 自身读取输入文件的 OS 失败（文件缺失/不可读/非普通文件）发生在进入内核之前，按输入错误结构化输出、退出码 2，不属于内核异常面。`CoreError` 子类一律转为结构化错误输出（退出码 1），绝不向终端泄漏裸异常；"非 `CoreError` 即内核 bug、任其崩溃"仅指内核库调用返回之后的异常面（内核合同保证不发生）。
9. **总体计划 Phase 1 任务 8 的 1D 了结方式**：隐私分类 = review 轴 + `export_mode` 词表（本 ADR）；绝对路径检测 = §6 safe relative path（1A 已交付，export 记录的 locator 复用之）；redaction interface = `decision.constraints` 意图记录 + 决策 1 边界，执行器显式延期；自动 secret/path 扫描器延期——半实现的扫描器制造虚假安全感，v1 的导出安全由"无导出通道 + 显式 decision 门禁 + 人工审查"构成。
10. **machine-readable validation report**：`verify-graph --json` 输出 `GraphVerificationReport.to_dict()`；`validate --json` 输出 `{schema_id, record_id, sha256}` 或结构化 violations 列表。两者均为严格 JSON 并以 canonical 字节输出。

## 后果

优点：

- 许可与事实都 hash-bound 且可全图验证：拒绝许可下的导出、模式不符的导出在 verify 中无所遁形；
- registry 单源的扩展成本再次验证为"加数据 + 一个私有 validator"；
- compatibility policy 使 v0.2.0 有可引用的演进合同，successor 义务被合同测试物理强制。

代价：

- violation 合同扩展（24→25）要求接口文档与测试计数同步（D5）；
- decision 无"当前有效"语义，把链选择推给未来的导出执行器；
- CLI 无 publish，1D 不能纯命令行建 store；
- decision 的 `export_mode` 对 deny 是"被拒绝的请求模式"，读者需理解该语义而非视为许可内容。

## 拒绝的方案

1. **回写 Case 的状态字段**：破坏不可变性与 ADR-0003 决策 8；属性集封闭使回写本就需升版本。
2. **`outcome` 三值含 `allow_with_redaction`**：无执行器的许可承诺是虚假语义；条件许可由 `allow` + `constraints` 表达。
3. **receipt 直引 Case 绕过 decision**：许可链不可追溯，"凭哪条许可导出"无法回答。
4. **CLI 暴露 publish 或执行导出**：只读边界是 1D 的误用面收缩；导出通道与 redaction 执行器同属后续批次。
5. **artifacts 可空、`destination` 用 safe-relative-path**：空 artifacts 的"导出事实"不可审计；跨项目目的地不是仓库内 locator。
6. **为条件必填扩展 schema 引擎**：同 `core-interface.md` §3.4 的判据（ADR-0003 拒绝方案 3）；以双端必填替代。
