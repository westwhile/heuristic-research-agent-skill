# Phase 1C 验收摘要（Run/Failure/Case envelope 与闭包图语义）

状态：**C1–C4 已逐层提交并经独立对抗审核（R12–R14 均 PASS）；C5 文档层完成，待 commit 授权**。commit、PR 与合并仍是独立 Gate，未经明确授权不执行。结论边界仅为工程完整性、合同一致性与回归状态，不构成任何数学、量化或机器学习研究结论。

验收日期：2026-08-16。分支：`feat/core-run-failure-case-v1`。

## 交付物（四层 commit 链 + C5 文档层）

| 层 | commit | 内容 |
|---|---|---|
| C1 | `3a7c4b7` | ADR-0003（11 条决策：统一命名、单向引用模型、pin 范围、Run 冻结字段、Observation/Analysis 分离、引用语义表、Case 结构与闭包、隐私单轴、ExperiencePacket 定性、registry 单源、violation 合同 24 种）+ 3 处文档纠偏 |
| C2 | `d8fd29a` | 四个 schema + 34 fixtures + 合同测试更新（七 family sorted 断言、逐 family golden pin dict，task 原值逐字未动）+ fail-closed 发布窗口测试；221/221 双运行时 |
| C3 | `f89a219` | `_families.py` family contract registry（单一私有元数据源）+ `_store` 身份派生 + `_graph` registry 驱动重写 + `lineage_scope_mismatch`；247/247 双运行时 |
| C4 | `42be9b1` | Case 注册并可发布 + 通用 `duplicate_reference` + 闭包 validator（`case_incomplete`）+ 两个垂直样例与公共导出钉选（`PublicInterfaceTest`）；264/264 双运行时 |
| C5 | 待授权 | `core-interface.md` 升 Phase 1C（§3.4–3.7 记录模型、§10 十图种表、§12 计数 264/24/87、§13 边界）+ `schemas/core/README.md` 过期措辞修正 + 根 README 链接与 ADR-0003 索引同步 + 本报告 |

原子性原则（"可发布 ⇄ 图认识"同提交，ADR-0003 拒绝方案 1）逐层保持：C2 四 family 均不可发布、C3 解锁 Run/Observation/Analysis、C4 解锁 Case；registry 成员即发布边界，`_graph.py:181` 的未注册分支经审核确认不可达。

## 验证证据（C5 层自检，全部实测）

- 双运行时全量：PATH Python 3.14.5 与 `.venv` 3.14.5 各 264/264 OK；
- violation 合同 24 种（14 完整性 + 10 图）24/24 在测试中有断言（脚本化核验）；
- 零漂移：`schemas/**/*.json`、`tests/fixtures/`、`tests/contract/` 相对 C4 commit 为空 diff；`git diff --check` clean；`src`/`tests`/`docs`/`schemas` 零 pycache；
- C5 改动仅三个文档文件加本报告；diff 扫描无本机绝对路径、无凭据模式命中。

## 独立对抗审核记录（R12–R14）

- R12（C2）：PASS。一个 P3 观察项——`fixed_seed` 模式下 `seed` 值可缺席，根因为 schema 引擎表达力边界（`x-conditional-min-items` 为数组导向，扩引擎等于重复 `uniqueItems` 拒绝理由）；已写入 `core-interface.md` §3.4 语义（mode 声明即冻结主张，seed 值可选；种子实质上重要时经 inputs/config 哈希捕获；强制 seed 需新 ADR）；
- R13（C3）：PASS，零新发现。确认错锚边保留在 cycle/fork 图中——`lineage_scope_mismatch` 与 `lineage_cycle` 可同时成立属正确双报；既有图测试 275 增 0 删；
- R14（C4）：PASS，零新发现。确认单 Analysis 多断链逐链枚举（一条完全未打包的链最多 3 条 `case_incomplete`）、`duplicate_reference`/`pin_mismatch` 共存、dangling 与 `case_incomplete` 正交互存；24 种 violation kind 全覆盖经独立复核。

## 边界声明

- 全部 fixtures 与两个垂直样例（脱敏 Math failure、合成 Quant leakage）均为合成、脱敏、测试内构造的工程证据，证明闭包与 lineage 语义按合同工作，不构成真实数学研究或真实市场研究证据；
- Case v1 `privacy_review_status ∈ {"pending"}`，本批一律不可导出；导出许可与导出事实是正交状态轴，由 ADR-0004 的独立记录表达，永不回写 Case（ADR-0003 决策 8）；
- 未实现：EvaluationCase / CandidateBundle / PromotionDecision schema、隐私 redaction 执行器、CLI、Adapter、跨进程并发发布；ExperiencePacket 定性为 Exporter 派生产物，不作为 Core schema（ADR-0003 决策 9）。

## Git/Release Gate

C5 commit、审核循环收口、PR、合并与 main 终验均为独立动作，未经用户明确授权不得执行。建议 C5 commit message：`docs(core): upgrade interface contract to Phase 1C (C5)`。
