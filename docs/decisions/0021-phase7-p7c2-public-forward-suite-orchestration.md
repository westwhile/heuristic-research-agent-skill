# ADR-0021：Phase 7 P7C2 public forward-suite orchestration

- 状态：Accepted
- 日期：2026-08-26
- 适用范围：Phase 7 P7C2 synthetic public forward-suite engineering
- 前置：ADR-0012、ADR-0013、ADR-0020

## 背景

P7C1 已建立单个 case 的 baseline/Candidate paired execution seam，并能把每个 arm 的成功或失败写入既有 attempt/result/run 结构。它尚不负责完整 suite 调度：caller 若自行循环，很容易遗漏 case/seed、只保留成功结果、在执行后才发现指标或预算未冻结，或重新发明一套统计与 receipt schema。

P7C2 需要把公开 synthetic suite 的完整调度收进一个 deep Module，同时保持 P7C1 Adapter seam、CR4 attempt/result、CR5 suite comparison 和 CR6 envelope closure 的既有语义。

## 决策

### 1. 单一 suite interface

P7C2 只新增一个行为入口：

```text
run_skill_forward_suite(plan, adapter) -> SkillForwardSuiteOutcome
```

该 Module 在 interface 后完成：

1. 校验 exact frozen suite membership；
2. 把 `SuiteComparePolicy.expected_seeds` 展开为完整 `case × seed` 网格；
3. 为每格生成带唯一 seed 的 P7C1 plan；
4. 在任何 Adapter 调用前，对所有格执行 P7C1 preflight；
5. 按稳定 case/seed 顺序执行每格的 baseline 与 Candidate；
6. 保留所有 attempt，包括失败和重试，不接受 caller 选择结果；
7. 只有完整网格全部产生 result/run 后，才调用既有 `compare_suite()`。

删除本 Module 后，网格覆盖、全量预检、预算上界、失败保留和比较组装会重新散落到 caller，因此通过 deletion test。

### 2. observation unit 与 seed 只有一个权威来源

观测单位固定为：

```text
case × seed × frozen evaluation envelope
```

suite template 的 `Envelope.seed` 必须为空；全部 seed 只能来自预注册的 `SuiteComparePolicy.expected_seeds`。每个 case 的 oracle score dimensions 必须与预注册 metrics 完全相等，且 policy 必须包含恰好一个 primary 和至少一个 guardrail。不同 metric 继续分别分析，不把 dimensions 当作样本。

### 3. 启动前冻结最坏预算

在 Adapter 启动前计算：

```text
worst_case_attempts
= cases × seeds × 2 arms × (1 + retry_attempts)
```

该值不得超过 `max_total_attempts`。预算、suite membership、metric set、runner/scorer identity 或任一 P7C1 引用链不闭合时，全 suite 零执行、fail closed。

### 4. 禁止选择性排除

一旦全量 preflight 通过并开始执行，某一格 timeout、output limit、parse error 或 runner error 不会中止其余网格。每格仍生成 attempt；任何格缺少 result/run 时，suite outcome 为 `execution_inconclusive`，不生成 `suite-comparison/v1`，也不补造 score 或删除失败格。

合法 P7B prerequisite rejection 会覆盖完整规划网格，但不会启动 Adapter，也不会生成虚假 attempt。

### 5. 复用现有 Port、Adapter 与 Core family

P7C2 直接复用 P7C1 `SkillForwardTestAdapter` Port、`DeterministicInProcessAdapter`、`ConstrainedLocalProcessAdapter` 和 `run_skill_forward_test`。不新增 suite executor Port，不改变两个 Adapter 的权限边界。

字段映射不存在表达缺口：

| P7C2 事实 | 既有承载 |
|---|---|
| 每次 arm 启动、失败、重试 | `evaluation-attempt/v1` |
| 可评分输出 | `evaluation-result/v1` |
| 完整成功 observation | `evaluation-run/v1` |
| 完整 case/seed 配对与分指标统计 | `suite-comparison/v1` |
| 候选与非 Skill 轴闭包 | `artifact-record/v1` + `evaluation-envelope-closure-receipt/v1` |

因此不新增 P7C2 schema 或 receipt family。

### 6. 证据边界

所有 adapter output、Math accept 和 Quant reject 都是 repository-native synthetic fixtures。P7C2 outcome 固定不授权或证明：

```text
real_agent_execution
real_independent_semantic_review
hidden_evaluation
candidate_materialization_or_runtime_load
publication_or_promotion
Skill_installation_or_activation
external_adoption
```

`suite-comparison/v1` 的统计状态不是 `PromotionDecision`。本批不调用 Codex/模型，不接触外部凭据，不物化 Candidate，不接触 `skills/staging/`。

## 被拒绝的方案

1. **caller 自行循环 P7C1**：无法统一证明完整网格和非选择性失败保留；拒绝。
2. **为 P7C2 新增另一套 executor Adapter**：与 P7C1 Port 重复；拒绝。
3. **失败即停止并比较剩余格**：形成选择性结果排除；拒绝。
4. **允许 Envelope 和 compare policy 同时声明 seed**：产生双重权威与漂移；拒绝。
5. **新增 forward-suite receipt schema**：现有 records 足以表达，新增 family 只会复制字段；拒绝。
6. **把公开 synthetic 比较称为 Hidden Evaluation 或 Promotion**：超出证据；拒绝。

## 验收

- Math synthetic accept 覆盖完整 `2 cases × 2 seeds × 2 arms` 网格并生成既有 suite comparison；
- Quant synthetic protocol reject 在 Adapter 调用前覆盖完整规划网格；
- 单格 execution failure 仍保留全部八次 arm attempt，且比较 fail closed；
- budget、case deletion、metric mutation 和 seed 双重来源在零执行时拒绝；
- 两个既有 Adapter 穿过同一个 suite interface；
- 工作树、exact archive 双解释器、clean-install、既有 CUDA regression 与 GitHub required checks 全绿后才允许合并。

P7C2 合并后的证据上限固定为：

```text
P7C2_PUBLIC_FORWARD_SUITE_READY
/ ZERO_REAL_AGENT_EXECUTIONS
/ ZERO_HIDDEN_EVALUATIONS
/ ZERO_PROMOTIONS
```
