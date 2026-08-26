# ADR-0023：Phase 7 P7D1A public real-failure capture

- 状态：Accepted
- 日期：2026-08-26
- 适用范围：Phase 7 P7D1A public Math baseline failure capture
- 前置：ADR-0011、ADR-0022

## 背景

P7C3 能证明一次受限 Codex 进程启动和临时 Candidate bytes 的运行时读取，但它只运行预制
smoke，不会把真实 baseline 数学失败整理成可进入 Case/Pattern/Candidate 链的证据。失败执行还
必须继续遵守 CR4 的 attempt-always/result-optional 语义，且不得把 raw output、session id、
stderr、JSONL 或本机路径写入 Core。

## 决策

### 1. 一个 deep Module interface

P7D1A 只新增：

```text
capture_public_agent_failure(plan, executor) -> PublicFailureCaptureOutcome
```

Module 在 Interface 后完成预注册 pin、单次执行、临时工作区、隐私扫描、attempt/result 组装、
真实失败资格判断、ResearchRun/FailureObservation/FailureAnalysis/CasePackage 链和安全清理。
删除该 Module 会把这些约束重新散落到 pilot caller，因此通过 deletion test。

### 2. 一个真实 seam、两个 Adapter

- `DeterministicPublicFailureAdapter` 只服务 Math/Quant synthetic contract、mutation、privacy 与
  fail-closed 测试；
- `CodexCliPublicFailureAdapter` 复用 ADR-0022 已验证的 Codex CLI process Adapter，因此继承
  ephemeral、read-only、approval never、web disabled、环境变量 allowlist、trace/output cap
  和 structured output 契约。

每个 plan 恰好启动一次 baseline；`Envelope.seed=None` 且 `retry_attempts=0`，不允许选择性重试。

### 3. 不新增 schema

字段映射证明如下：

| 事实 | 既有表达 |
| --- | --- |
| 所有启动后的执行，包括 timeout/parse/runner error | `evaluation-attempt/v1` |
| 完成评分后的非空 score | `evaluation-result/v1` |
| 一次真实科研任务执行及冻结输入 | `research-run/v1` |
| 直接观察事实 | `research-failure-observation/v1` |
| 可修订且不冒充事实的根因假设 | `research-failure-analysis/v1` |
| task/run/observation/analysis、lineage 与隐私状态闭包 | `research-case-package/v2` |

因此缺口是编排与隐私封装，不是 Core family 的不可表达缺口。

### 4. qualified failure Gate

只有同时满足以下条件才返回 `qualified_failure` 并构造失败链：

1. 工作区清理成功；
2. 真实 Adapter 观察到 `thread.started` 与 `turn.completed`；
3. 输出通过 restricted-content scan；
4. deterministic scorer 产生 `evaluation-result/v1`；
5. verdict 精确为 `fail`。

pass 返回 `no_failure`；timeout、runner/parse/scorer error、缺 session/turn 或 cleanup failure 返回
`capture_inconclusive`。二者都不会伪造 Research Case。Deterministic Adapter 的 synthetic
结果只能证明 Interface contract，不得升级为真实 Agent 失败。

### 5. 隐私与证据上限

公开记录只保留 case/prompt/schema/envelope、session/trace/stderr 的 SHA-256、usage 和固定清洗
事实。raw output 只在进程内完成评分，不进入 observation、analysis 或 case；外部异常消息被
抑制。Case 的 lineage 标签仍是协议声明，不是外部身份验证。

P7D1A 的证据上限固定为：

```text
PUBLIC_REAL_FAILURE_CAPTURE_READY
/ ZERO_REAL_FAILURE_CASES_UNTIL_P7D2
/ ZERO_REAL_SKILL_CANDIDATES
/ ZERO_HIDDEN_EVALUATIONS
/ ZERO_PROMOTIONS
```
