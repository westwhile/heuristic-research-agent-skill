# Phase 5 验收报告：Machine Learning Adapter（2026-08-21）

状态：**L1–L6 工作树验收 PASS；commit-bound `git archive` Release Gate 待 Git
收尾授权。** 当前结论支持 Phase 5 的合成工程实现完成，不支持真实数据、
预测、市场、生产或 Skill 能力声明。

- 分支：`feat/ml-adapter`
- 验收基线：`812029fee0759bd11c2d8bc0eaeb3cc5ac1b2e54`
- 当前工作树：L6 未提交实现（完成独立复核后再 commit）
- Python：PATH 与 `.venv` 两个不同解释器入口，均为 Python 3.14.5
- L6 manifest SHA-256：
  `37c6645c2b777396ba0ab10e37037751405098e424abc703cdb791e2510ec98d`

## L 层交付映射

| 层 | 交付 | 状态 |
|---|---|---|
| L1 | ADR-0008 与实施分层 | PASS |
| L2 | 四个 ML Adapter schema、三操作实现、contract harness | PASS |
| L3 | DAG topology、七 leakage predicates、三 semantic floors | PASS |
| L4/L4.1 | evaluation-contract/v3、ml-evidence/v2、final-evaluation Gate、runner 加固 | PASS |
| L5 | 20-case catalog、四 split assignment Gate、非时间/时间双切片、两份报告 | PASS |
| L6 | 4 Case Packages、candidate Pattern、3 shadow Heuristics、重合分析、验收报告 | PASS（工作树） |

## Phase 5 验收 Gate

| Gate | 证据 | 结果 |
|---|---|---|
| test/holdout 不参与调参或选择 | L3 topology predicates + L4 final partition cross-binding + L5 catalog + L6 leakage-repair Case | PASS |
| split/preprocessing lineage 可重建 | identity/SHA/input pins 构成 DAG；L5 data assignment/context pins；L6 capture 绑定完整 protocol | PASS |
| 单 seed 最佳值不支撑稳定 Claim | unique-seed floor、repeated-seed artifact、best-only 不进入 L6 evidence | PASS |
| 模型/资源/seed/Heuristic 变更分层 | runner parity changed_axes；L6 reproduction Case 把 seed-policy 漂移显式作为不同 protocol | PASS |
| OOD/subgroup/calibration/drift 缺失写限制 | ML claim assessment 与 L5 E2E 逐项钉选，L6 bundle 保留 limitations | PASS |
| Math/Quant 零 critical regression | 双环境全量 864/864；Core family 仍 17 | PASS |

## L6 Research Memory 证据

- 新增 38 个 ML 文件；staging 全树 54 个 JSON，逐字节可重建；
- 32 个 Core records 发布到临时 store 后 graph verification 0 violations；
- 4 个 eligible Case 覆盖完整协议、负结果、泄漏修复、复现差异；
- 唯一 Pattern 由两个独立 Case 蒸馏，只到 `candidate_pattern`；
- 3 条 Heuristic 各有 regression Case，最终只到 `shadow`；
- linter 0 reject，shadow report 恰好 3 条且不含 Core schema；
- 无 `SKILL.md`、Skill candidate、installation、activation 或 Champion 变更。

## ML/Quant 重合分析

ADR-0008 的三项下沉判据没有对任何新候选同时成立：task normalization、
promotion bar 与 evidence loading 语义不同；gate→required-evidence 去重逻辑虽
近似相同，但缺双域行为合同且 module 过浅。因此本 Phase **零 Core 下沉**，
没有修改 `src/research_evolution/core/`、Core schema、family registry 或 Adapter
interface。既有 canonical/schema/exchange 共享面保持不变。

## 动态与机械验证

| 检查 | 结果 |
|---|---|
| L6 + Phase 4 evidence-pack 定向电池 | 19/19 PASS |
| `.venv` 全量 unittest | 864/864 PASS |
| PATH Python 全量 unittest | 864/864 PASS |
| PowerShell GitHub auth-context governance | 33 assertions / 6 cases PASS |
| tracking Gate | 38 个 ML 内容文件已进入 index；`captures/` 不受 ignore 规则影响 |
| `git diff --check` / 链接 / 凭据 / archive | 见最终独立审核与 Git 收尾回执 |

## 未完成与证据上限

以下能力仍明确未实现：

- 真实或第三方 ML 框架执行器；
- 真实数据许可、PIT/coverage 验收或冻结真实 snapshot；
- 完整 nested-CV 逐折训练、超参搜索、重训与 trial registry；
- 真实 OOD/subgroup/calibration/drift 执行；
- 真实预测、经济、市场或生产证据；
- 自动 Case→Pattern→Skill 晋级、安装、激活或生产 Agent 闭环。

因此最高证据等级保持 `engineering-only`。`v0.6.0` annotated tag、GitHub
Release、Skill 安装与任何 Champion promotion 都是独立动作，仍需分别审批。

## Release Gate 与回滚

真实 `git archive` 必须绑定一个 commit，不能在未提交工作树上伪造。本报告
先记录工作树验收；独立审核通过且获得 Git 收尾授权后：

1. 精确提交 L6 diff；
2. 对该 commit 运行 `scripts/verify_archive_suite.py` 双解释器 Gate；
3. 只有 archive 通过才允许 push，并在操作回执记录 commit/remote SHA；
4. PR、merge、annotated tag 与 Release 均不由 push 隐含。

L6 只新增测试、报告和 staging evidence，并修改状态文档；无 schema/store
迁移、外部写入或安装动作。若需回滚，revert L6 commit 即恢复 L5 状态，
Phase 4 Math/Quant 证据文件字节不变。
