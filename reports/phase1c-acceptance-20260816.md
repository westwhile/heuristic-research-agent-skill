# Phase 1C 验收摘要（Run/Failure/Case envelope 与闭包图语义）

状态：**Phase 1C 五层全部提交并经独立对抗审核（R12–R15 均 PASS），账本清零**。PR、合并与 main 终验仍是独立 Gate，未经明确授权不执行。结论边界仅为工程完整性、合同一致性与回归状态，不构成任何数学、量化或机器学习研究结论。

验收日期：2026-08-16。分支：`feat/core-run-failure-case-v1`。

## 交付物（五层 commit 链 + R15 收尾）

| 层 | commit | 内容 |
|---|---|---|
| C1 | `3a7c4b7` | ADR-0003（11 条决策：统一命名、单向引用模型、pin 范围、Run 冻结字段、Observation/Analysis 分离、引用语义表、Case 结构与闭包、隐私单轴、ExperiencePacket 定性、registry 单源、violation 合同 24 种）+ 3 处文档纠偏 |
| C2 | `d8fd29a` | 四个 schema + 34 fixtures + 合同测试更新（七 family sorted 断言、逐 family golden pin dict，task 原值逐字未动）+ fail-closed 发布窗口测试；221/221 双运行时 |
| C3 | `f89a219` | `_families.py` family contract registry（单一私有元数据源）+ `_store` 身份派生 + `_graph` registry 驱动重写 + `lineage_scope_mismatch`；247/247 双运行时 |
| C4 | `42be9b1` | Case 注册并可发布 + 通用 `duplicate_reference` + 闭包 validator（`case_incomplete`）+ 两个垂直样例与公共导出钉选（`PublicInterfaceTest`）；264/264 双运行时 |
| C5 | `e7d484e` | `core-interface.md` 升 Phase 1C（§3.4–3.7 记录模型、§10 十图种表、§12 计数 264/24/87、§13 边界）+ `schemas/core/README.md` 过期措辞修正 + 根 README 链接与 ADR-0003 索引同步 + 本报告 |
| R15 收尾 | 本 commit | 本报告状态行、C5 commit 哈希与审核记录定稿（R15-P3 闭合） |

原子性原则（"可发布 ⇄ 图认识"同提交，ADR-0003 拒绝方案 1）逐层保持：C2 四 family 均不可发布、C3 解锁 Run/Observation/Analysis、C4 解锁 Case；registry 成员即发布边界，`_graph.py:181` 的未注册分支经审核确认不可达。

## 验证证据（C5 自检 + R15 终态独立复验，全部实测）

- 双运行时全量：PATH Python 3.14.5 与 `.venv` 3.14.5 各 264/264 OK（R15 在 HEAD `e7d484e` 的 clean tree 终态复跑确认）；
- violation 合同 24 种（14 完整性 + 10 图）24/24 在测试中有断言（脚本化核验，终态保持）；
- 零漂移：Phase 1A 既有 3 个 schema 与 53 个 fixtures 精确 pathspec 复验为 0 行 diff；`schemas/**/*.json`、`tests/fixtures/`、`tests/contract/` 相对 C4 commit 为空 diff；`git diff --check` clean；`src`/`tests`/`docs`/`schemas` 零 pycache；
- C5 改动仅三个文档文件加本报告；全分支 diff 扫描无本机绝对路径、无凭据模式命中。

## 独立对抗审核记录（R12–R15）

- R12（C2）：PASS。一个 P3 观察项——`fixed_seed` 模式下 `seed` 值可缺席，根因为 schema 引擎表达力边界（`x-conditional-min-items` 为数组导向，扩引擎等于重复 `uniqueItems` 拒绝理由）；已写入 `core-interface.md` §3.4 语义（mode 声明即冻结主张，seed 值可选；种子实质上重要时经 inputs/config 哈希捕获；强制 seed 需新 ADR）；
- R13（C3）：PASS，零新发现。确认错锚边保留在 cycle/fork 图中——`lineage_scope_mismatch` 与 `lineage_cycle` 可同时成立属正确双报；既有图测试 275 增 0 删；
- R14（C4）：PASS，零新发现。确认单 Analysis 多断链逐链枚举（一条完全未打包的链最多 3 条 `case_incomplete`）、`duplicate_reference`/`pin_mismatch` 共存、dangling 与 `case_incomplete` 正交互存；24 种 violation kind 全覆盖经独立复核；
- R15（全包终态）：PASS。两组新探针补 R12–R14 未覆盖角度——发布顺序无关性（先发布 Case、成员引用全悬空，中间态 verify 恰为纯 `dangling_reference` 集合，补齐成员后收敛 ok=True、5 records/5 families，为"任意顺序发布相互引用记录"合同的首次端到端实证；闭包 skip 语义在真实收敛场景正确工作）；新 family 间 `duplicate_id`（同一 id 作 run 与 case）精确触发。唯一发现 R15-P3：本报告自指"待授权"陈旧（报告随 C5 入库的时序问题），由本收尾 commit 闭合。

账本终态：R12-P3 闭合于 §3.4 语义定论；R15-P3 闭合于本 commit；其余为空。

## 边界声明

- 全部 fixtures 与两个垂直样例（脱敏 Math failure、合成 Quant leakage）均为合成、脱敏、测试内构造的工程证据，证明闭包与 lineage 语义按合同工作，不构成真实数学研究或真实市场研究证据；
- Case v1 `privacy_review_status ∈ {"pending"}`，本批一律不可导出；导出许可与导出事实是正交状态轴，由 ADR-0004 的独立记录表达，永不回写 Case（ADR-0003 决策 8）；
- 未实现：EvaluationCase / CandidateBundle / PromotionDecision schema、隐私 redaction 执行器、CLI、Adapter、跨进程并发发布；ExperiencePacket 定性为 Exporter 派生产物，不作为 Core schema（ADR-0003 决策 9）。

## Git/Release Gate

PR、合并授权与 main 终验均为独立动作，未经用户明确授权不得执行。PR 描述需附：清洁测试证据（双运行时 264/264 与 R12–R15 探针记录）、变更清单（五层映射）与回滚说明（revert 六个 commit 即可，无 schema 迁移；注意点：回滚后含 Phase 1C 记录的 store 在 main 代码下 verify 会报 `record_invalid`，属预期 fail-closed）。
