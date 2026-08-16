# Phase 1D 验收摘要（三轴隐私模型、export 记录、schema 兼容政策与只读 CLI）

状态：**Phase 1D 五层全部提交并经独立对抗审核（R16–R20 均 PASS，R20 为全包终审），账本清零**。PR、合并、main 终验与 v0.2.0 tag 仍是独立 Gate，未经明确授权不执行。结论边界仅为工程完整性、合同一致性与回归状态，不构成任何数学、量化或机器学习研究结论。

验收日期：2026-08-16。分支：`feat/core-privacy-cli-v1`。

## 交付物（五层 commit 链）

| 层 | commit | 内容 |
|---|---|---|
| D1 | `d475477` | ADR-0004（10 条决策：三轴模型定名、export_mode 四值词表双端必填、decision/receipt 记录模型、violation 24→25、registry 原子性、schema 兼容政策、CLI 边界、计划任务 8 了结、扫描器延期、machine-readable report）+ `docs/governance/SCHEMA_COMPATIBILITY.md`（5 规则）+ 计划文档任务 8 注记 |
| D2 | `5fc8989` | `export-decision/v1` 与 `export-receipt/v1` 双 schema + 19 fixtures（9+10）+ 合同测试同 commit（family 断言 7→9、minimal pin +2 原七项逐字未动、**全部九个 schema 文本 golden SHA-256 pin** `SCHEMA_TEXT_SHA256` 含磁盘反向比对）+ fail-closed 发布窗口测试；266/266 双运行时 |
| D3 | `178032b` | `_families.py` 注册双 export family + 发布身份（`_store.py` 零改动，单源设计兑现）+ `_graph.py` 唯一新增 validator `unauthorized_export`（每条违规 receipt 恰一条、detail 枚举条件、decision 缺席跳过不双计）+ `ExportGraphTest` 14 项 + 窗口测试收缩为发布链测试；280/280 双运行时 |
| D4 | `e61d948` | 只读 CLI `python -m research_evolution`（`validate`/`hash`/`verify-graph`）：`--json` canonical 字节逐字节输出并可 `load_strict_json` 回灌、退出码 0/1/2（输入错误分句在内核之前）、不暴露 publish、全树快照只读断言；`core.__all__` 仍 18 项；296/296 双运行时 |
| D5 | `4965e19` | `core-interface.md` 升 Phase 1D（§3.8–3.9 记录模型、§7 文件名规则修复与 schema 文本 pin、§10 图侧表 11 行共 25 种、§11 新增只读 CLI 节、§12/§13 计数与清单、§14 边界）+ `schemas/core/README.md` 与根 `README.md`（含 ADR-0004 索引）同步 + 本报告 |
| R20 收尾 | 本 commit | 本报告状态行、D5 commit 哈希与 R20 终审记录定稿 |

原子性原则（"可发布 ⇄ 图认识"同提交）逐层保持：D2 两 family 均不可发布（窗口测试实证零写入 fail-closed），D3 同 commit 注册 + 发布身份 + 图语义 + 窗口收缩。

## 验证证据（D5 自检 + R20 终态独立复验，全部实测）

- 双运行时全量：PATH Python 3.14.5 与 `.venv` 3.14.5 各 296/296 OK（R20 在 HEAD `4965e19` 的 clean tree 终态复跑确认）；
- violation 合同 25 种（14 完整性 + 11 图）25/25 在测试中有断言（脚本化核验：`_store.py` problems 元组字面量 + `_graph.py` `GraphViolation` 字面量提取后对测试全文检索，`missing: []`）；
- 零漂移：Phase 1A 既有 3 schema 与 53 fixtures、Phase 1C 新增 4 schema 与 34 fixtures 全部字节零漂移（各层 pathspec 复验 0 行 diff）；D2–D4 未触碰任何既有源码文件（D3 图测试对既有类 +257/−0 纯增）；
- `git diff --check` clean；`src`/`tests`/`docs`/`schemas` 零 pycache；全分支 diff 扫描无本机绝对路径、无凭据模式命中。

## 独立对抗审核记录（R16–R19）

- R16（D1）：修订后 PASS。五项修订全部落实——决策 8 输入错误分句（CLI 自身读文件 OS 失败结构化 + exit 2，"非 CoreError 即 bug" 仅限内核调用返回后）、决策 7 pin 基准（原始字节 + `.gitattributes` 换行承担，与 canonical pin 两基准并存）、政策规则 1 同步、计划任务 8 注记、决策 3 时间序理由 + 决策 5 引用语义表；增量复核曾发现决策 8 退出码分句编辑残留（同一行重复两遍），机械修复后实证归零；
- R17（D2）：修订后 PASS。唯一裁定：删除我方交付的 `SCHEMA_CANONICAL_SHA256` 第二 pin 基准——ADR-0004 决策 7 只签署原始字节一种基准，文本 pin 检测面严格包含 canonical pin，第二基准属超出合同的冗余断言面；其余全部声明经独立实测（走私 fixture 双职证明 receipt 不可直引 case、正斜杠盘符形态、窗口测试零写入、pin 真实性独立重算）；
- R18（D3）：PASS，零新发现。五组证伪探针覆盖包内未直接测试的角度——fork 双分支挂 receipt 独立判定、双 receipt 同锚双报、时间序边界（锚定被 supersede 的 allow decision 不违规）、case pin 错误时门禁静默（正交性）、单条件模式不符；`duplicate_id` 跨 9 family 警戒线在探针自伤中被无意实证；
- R19（D4）：PASS，零发现。独立 11 点命令行对抗矩阵全过（退出码、canonical 逐字节、跨进程回灌、只读快照 extra=∅、LF-only 字节写）；两个自由裁量点获批准——`hash` = 先校验再报 canonical 内容哈希（附 §11 注记义务，已落）与 `identity_of` 包内私有引用（不破坏 registry 单源的唯一选项）；
- R20（全包终态）：PASS，零新发现。§7 文件名规则修复与 `_schema.py:157` 实现规则逐字吻合；章节 1–14 连续、计数 296/25/106 自洽；收官 e2e 探针——10 记录 9-family 全形态 store 经公共 CLI `verify-graph` exit 0、stdout 与库调用 canonical 输出逐字节一致，篡改 manifest 后 exit 1 恰报 `manifest_malformed`。

账本终态：空（R16/R17 修订项均已在对应层闭合；R18–R20 零发现）。

## 边界声明

- 全部 19 个新 fixtures 均为合成、脱敏、测试内构造的工程证据，证明 schema 校验与导出门禁语义按合同工作，不构成真实数学研究或真实市场研究证据；
- 导出安全三件套：**无导出执行通道**（内核与 CLI 均不搬字节）+ **decision 门禁**（`unauthorized_export`）+ **人工审查**；自动 secret/path 扫描器显式延期（半实现的扫描器制造虚假安全感，ADR-0004 决策 9），redaction 执行器延期（`decision.constraints` v1 只记录意图）；
- CLI 为只读外壳：不暴露 publish、无网络、无任何文件写入（快照断言钉死）；store root 缺失归内核验证发现（exit 1）而非 CLI 输入错误（exit 2）的边界已钉选；
- `hash` 输出 canonical 内容哈希（与 store 内容寻址同一语义），不是文件字节哈希；
- 未实现：EvaluationCase / CandidateBundle / PromotionDecision schema、redaction 与导出执行器、Adapter、跨进程并发发布；
- schema 演进唯一通道是新 `$id`（`docs/governance/SCHEMA_COMPATIBILITY.md`），successor 测试义务由合同测试物理强制。

## Git/Release Gate

PR、合并授权、main 终验与 v0.2.0 annotated tag 均为独立动作，未经用户明确授权不得执行。PR 描述需附：清洁测试证据（双运行时 296/296 与 R16–R19 探针记录）、变更清单（五层映射）与回滚说明（revert 五个 commit 即可，无 schema 迁移；注意点：回滚后含 export 记录的 store 在 main 代码下 verify 会报 `record_invalid`，属预期 fail-closed）。tag 指向 main 已验收提交，tag 与 GitHub Release 是两个动作分别留证；Release notes 引用 `SCHEMA_COMPATIBILITY.md` 与已知限制（CLI 无 publish、无 redaction 执行器）。
