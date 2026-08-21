# Phase 5 L6：ML Research Memory 与 Shadow 证据（2026-08-21）

状态：**合成工程证据**。本报告证明 Phase 4 的 Case/Pattern/Heuristic/shadow
机器能够承载 ML 协议治理案例；不构成真实数据验收、预测性能、市场证据、
真实 ML 执行器或完整科研 Agent 证据。

## 证据包规模

`staging/research-memory/evidence/ml/` 由
`tests/integration/_ml_research_memory_pack.py` 通过既有公共 interface
确定性构建：

| 类别 | 数量 | 边界 |
|---|---:|---|
| ML capture artifact | 4 | 完整协议、负结果、泄漏修复、复现差异，各 1 |
| Core record | 32 | 临时 store 全图闭包；不新增 Core family |
| `research-case-package/v2` | 4 | 全部 eligible、privacy passed、synthetic |
| Pattern record | 2 | 1 条 distilled→candidate_pattern 链 |
| Heuristic record | 9 | 3 条 lesson_hypothesis→candidate→shadow 链 |
| registry artifact | 2 | linter report + hypothetical-only shadow report |

新增 ML 文件共 **38**；与原 Phase 4 的 15 个证据文件及根 manifest 合并后，
`staging/research-memory/` 共 **54 个 JSON 文件**。根 manifest SHA-256：
`37c6645c2b777396ba0ab10e37037751405098e424abc703cdb791e2510ec98d`。

## 四类 Case Package

| Case | 捕获内容 | 工程结论 |
|---|---|---|
| `case-ml-protocol` | dataset、ml-case、evaluation-contract/v3、三 seed runner artifact、ml claim assessment | 完整合成协议可 hash-bound 重建；assessment 仍 inconclusive |
| `case-ml-negative-result` | 全零标签的明确非获胜对照 | candidate-minus-baseline 为零仍被保留，不做 winner-only 叙事 |
| `case-ml-leakage-repair` | selection-on-test 违规载荷、`selection-uses-test` 拒止、validation-only 修复和新 pins | 违规与修复以不同 case hash 记录，历史不覆盖 |
| `case-ml-reproduction-difference` | 同协议 A 两次重放 + 改 seed policy 的协议 B | A 字节 hash 一致；A/B 差异归因于显式协议漂移，不冒充 nondeterminism |

每个 Case 同时包含一个 Core `engineering_claim` 与
`research-evidence/v1(evidence_level=engineering-only)`，并明确列出：不支持
real-data、predictive/market、production 或 Skill publication/installation
结论。泄漏修复与复现差异另有 Observation/Analysis 分离记录；Analysis 保持
hypothesis 表述。

## Pattern 与 Heuristic 边界

唯一 ML Pattern `pattern-ml-pinned-comparison` 只从两个独立 eligible Case
（泄漏修复、复现差异）蒸馏，最高状态为 `candidate_pattern`，confidence=low，
evidence grade=`synthetic engineering evidence`。不存在 active Pattern、
`promoted_skill`、Skill candidate 或安装动作。

三条 Heuristic 分别覆盖：

1. selection 不得使用受保护的最终 partition；
2. 非获胜/负结果必须保留；
3. replay 比较前必须核对全部 protocol/evidence pins。

每条均绑定 regression Case 并走完整三版本链，最终只到 `shadow`。linter 对
三个 chain tip 无 reject；shadow report 恰好引用 3 条 shadow Heuristic，
只写 `would ...` 假设性决策，不含 Core `schema`，不改变任何运行行为。

## 定向验证

首轮定向电池：

- `tests.integration.test_ml_research_memory_pack`：13/13；
- `tests.integration.test_experience_evidence_pack`：6/6；
- 合计 **19/19**；
- 32-record 临时 store `verify_record_graph`：0 violations；
- manifest 与整个 ML 子树逐字节重建一致。

双环境全量、PowerShell 治理与 Phase 5 最终验收结果另见
`phase5-acceptance-20260821.md`。implementation commit
`82d62e9bdbed9c4d05c7c986f6a6a4c46a71dd57` 的真实 `git archive` 双解释器
同为 864/864（各 1 个预期 Git tracking skip）；该全绿结果最多支持工程
证据，不改变上述科研边界。
