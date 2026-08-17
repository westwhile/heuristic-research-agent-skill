# Phase 2 验收报告：Math/Quant 双 Adapter 垂直切片（待 R26 全包终审）

- 日期：2026-08-16
- 分支：`feat/math-quant-vertical-slices`（基 `main` = `4e6d79d`，v0.2.0）
- 范围：ADR-0005 的落地——seam 三类型、双领域 Adapter、contract suite 三项成立判据、垂直切片证据、Adapter interface v1 冻结说明
- 状态：**A1–A5 已逐层提交并经 R22–R25 逐层审核通过；本报告待 R26 全包终审**（终审通过后按 1C/1D 先例以收尾 commit 回填状态行与本 commit 哈希）

## 层/commit 映射

| 层 | 内容 | commit | 审核 |
|---|---|---|---|
| A1 | ADR-0005（11 决策 + 后果 + 6 拒绝方案）+ 决策索引 | `7b29abe` | R22 PASS（签名变更认领已入决策 2） |
| A2 | seam 三类型 + 3 adapter schema + 27 fixtures + 套件骨架（空注册窗口） | `6a05167` | R23 PASS |
| A3 | Math adapter + 4 math schema + 29 fixtures + 只读 archive importer | `22efdb9` | R24 PASS（R24-P2 非数学梯级 bar 误报已修复并回归钉死） |
| A4 | Quant adapter + 4 quant schema + 29 fixtures + 套件双注册 | `5c1a5d1` | R25 PASS |
| A5 | 判据②③探针 + 成员断言收口 + 垂直切片 + 本报告 + README 同步 | 本 commit | 待 R26 |

## seam 成立三判据（ADR-0005 决策 6/8）

| 判据 | 证据 |
|---|---|
| ① 双 Adapter 同套件 | `tests/adapter_contract/test_adapter_contract_suite.py` 同一参数化套件对 Math/Quant 各跑一遍；`test_registry_membership_is_exactly_math_and_quant` 永久钉选恰 `{"math", "quant"}` 两个 harness |
| ② Core 静态纯净 | `CoreStaticPurityTest`：`src/research_evolution/core/**` 全部 `.py` 无 `\badapters\b` 命中、无 `_BANNED_TERMS` 领域词汇命中（与 schema 领域中性扫描同一词表，复用自 `tests/contract/test_core_schemas_contract.py`） |
| ③ 删除测试 | `CoreDeletionTest`：静态分区 `tests/unit` + `tests/contract`（adapter 耦合文件钉选为恰 4 个已知集合），子进程以 meta-path blocker 使 `research_evolution.adapters` 不可导入（自证 `BLOCKER-ACTIVE`），Core 全套 **306 项**测试零修改通过、退出码 0 |

306 的构成：296 项 Phase 1 冻结 Core 套件 + 10 项 adapter schema 合同测试（`test_adapter_schemas_contract.py` 只 import 核心引擎——测的是 schema 不是 adapter 代码，故属 Core 分区；这是比决策字面更强的结果）。

判据②的一项连带披露：`core/publication.py` 的 `PublicationReceipt` docstring 原用 "Proof of one publish_record call"（一般英语义"凭据"），在 `_BANNED_TERMS` 扩展至 Core 源码后会命中 "proof" 一词。按判据②的绝对语义将该词改为 "Attestation"——纯散文一词改动，零行为变化，无 import/逻辑触碰。

## 垂直切片（8 例，全部合成级证据）

| # | slice | case → contract | 证据 | 实测 ceiling | 实测 disposition |
|---|---|---|---|---|---|
| 1 | math-bounded-numeric | bounded_verification → bar `engineering_verified` | 纯数值 | `engineering_verified` | inconclusive |
| 2 | math-decide-certificate-proof | decide → bar `mathematically_verified` | 证明证书 | `mathematically_verified` | supported |
| 3 | math-decide-certificate-disproof | 同上 | 证明证书（否证） | `mathematically_verified` | refuted |
| 4 | math-decide-certificate-partial | 同上 | 证明证书（partial 终态） | `mathematically_verified` | inconclusive |
| 5 | quant-engineering-synthetic | 四门全开 case | 合成回测 | `engineering_verified` | supported |
| 6 | quant-oos-synthetic-cap | 同上（empirical bar `empirically_supported`） | 仅合成 | `data_accepted`（合成封顶） | inconclusive |
| 7 | quant-oos-real-pit | 同上 | 真实 PIT | `empirically_supported` | supported |
| 8 | quant-real-market-production | 同上（strategy bar `externally_validated`） | production 日志 | `externally_validated` | supported |

切片同时演示两条 Core 绑定链：Math 侧合成 archive → 只读 import → 9 个工件哈希 + 合同哈希经 `inputs` 绑定进 `research-evidence/v1` 载荷并过 Core 校验；Quant 侧合同哈希（`kind="config"`）+ 证据工件哈希（`kind="data"`）同样绑定。`production_observed` 在全部切片与探针中从未被 Adapter 授予（决策 4）。

## Importer 零写入证据（决策 9）

- `tests/unit/test_math_importer.py::test_zero_write_evidence`：导入前后 `snapshot_tree` 全量哈希快照相等；
- `tests/integration/test_vertical_slices.py::MathVerticalSliceTest::test_archive_import_is_zero_write_and_hash_bound`：切片链路上同一断言再次成立；
- 全部切片使用明确标记的合成 archive fixture（`tests/fixtures/math-archives/minimal-v8`）；真实 legacy archive 导入为条件能力，基线先例见 `reports/baseline/math-research-solve-1.0.1.md`——**无合成文件冒充真实导入**。

## Adapter interface v1 冻结说明（决策 10）

冻结面：三个 seam 交换类型（`DomainTask`/`ClaimAssessment`/`EvaluationContract`，frozen dataclass）、三个 seam schema（`domain-task/v1`、`claim-assessment/v1`、`evaluation-contract/v1`）、三操作签名（决策 2）、八个领域 schema（math/quant 各四）。冻结后修改走 v2，判据与 ADR-0004 兼容政策同源。

冻结时**超出 ADR 字面的增量**（按 R22 签名认领纪律逐条记录）：

1. `validate_claim(claim, evidence, contract)` 相对架构 §4.2 原文增补 `contract` 参数——已认领并记录于 ADR-0005 决策 2（R22 审核发现）；
2. `evaluation-contract/v1` 的 `case_sha256` 字段是决策 5 描述性清单之外的 v1 增量——合同与所评 case 的哈希绑定（R23 审核附注 1），审计价值：回答"按哪个 case 的合同评的"。

无其他增量。

## 边界声明

- 全部 Phase 2 证据为**合成/脱敏级**：合成 archive fixture、合成 quant fixture；无真实 legacy archive、无真实市场数据、无任何真实收益主张；
- Adapter 不发布 Core 记录、不读 store、不自查 verify；seam 三类型不可发布、不进 `_families.py`、`core.__all__` 仍 18 项；
- `production_observed` 永不由 Adapter 授予；合成/sample 证据永不晋级 `empirically_supported` 及以上；
- ML/DL Adapter、完整 Evaluator、ResearchPattern 蒸馏均不在本 Phase（决策 11 非目标）。

## 全程 Gate 证据

- 双运行时（PATH 3.14.5 与 `.venv`）全量 **391/391 OK**（A4 态 381 + 判据②③探针 4 + 切片 6）；
- 零漂移：Core schema 9 个、Core fixtures 106 个、Core 合同测试、Math adapter/importer/types/base 相对各自冻结点 0 行（精确 pathspec 复验）；
- 卫生：`git diff --check` clean、pycache 0、新 JSON 全部 LF；
- R22–R25 四轮审核发现全部闭合（R22 签名认领、R23 六设计点、R24-P2 bar 误报、R25 零发现）；本层待 R26。

## Git/Release Gate 备注（供合并时点使用）

- 变更清单：五层 commit 逐层对应 A1–A5（见上表）；
- 回滚说明：revert 五个 commit 即可，无 schema 迁移；注意点——回滚后 `schemas/adapters/` 与 `research_evolution.adapters` 包不存在，Core 行为不变（删除测试即此性质的证据）；
- 合并后 main 终验：双运行时全量 + Phase 1A 表面漂移三项 + 删除测试复跑；
- v0.3.0 annotated tag 指向 main 已验收合并提交；tag 与 GitHub Release 两个动作分别留证；Release notes 引用本报告与 ADR-0005，已知限制须含：无 ML/DL Adapter、无完整 Evaluator、切片证据为合成级。
