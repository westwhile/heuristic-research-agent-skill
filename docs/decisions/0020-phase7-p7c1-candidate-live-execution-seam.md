# ADR-0020：Phase 7 P7C1 Candidate live-execution seam

- 状态：Accepted
- 日期：2026-08-26
- 适用范围：Phase 7 P7C1 synthetic execution conformance
- 前置：ADR-0010、ADR-0013、ADR-0017、ADR-0018、ADR-0019

## 背景

P7B2—P7B4 已能冻结 Candidate Skill payload 描述、执行静态验证，并对语义审查提交执行协议级 byte binding；这些能力都不执行 Candidate。Phase 3/CR4 的 evaluator 只 replay 已冻结输出，因此也不能说明某个 runner 实际生成了输出。

P7C1 需要在不物化 Skill、不调用真实 Agent、不引入外部凭据的前提下，先证明一条 live-output engineering path：同一个冻结计划驱动 baseline 与 Candidate 两个 arm，通过可替换 adapter 获得输出或失败事实，再复用既有 scorer、hard gates 和 attempt/result 记录。

## 决策

### 1. 一个 deep module interface

P7C1 只新增一个行为入口：

```text
run_skill_forward_test(plan, executor) -> SkillForwardTestOutcome
```

该 module 在 interface 后隐藏以下 implementation：

1. 校验 exact Candidate Manifest、P7B2 Bundle、P7B3 receipt、P7B4 attestation 与 CR6 envelope closure 引用链；
2. 重新核对 Candidate payload bytes、case input bytes 和 envelope artifact pins；
3. 在 runner 启动前冻结 model、reasoning、tools、budget、data、evaluator、generator、statistical plan、rollback、case、suite、trigger mode 和 scorer；
4. 只让 baseline/Candidate 的 Skill candidate pin 不同；
5. 要求 scorer oracle 显式绑定本 case 的预期 Router outcome；
6. 执行两个 arm，并把成功、失败、重试、评分和 hard gates 组装为已有 Core records；
7. 返回非 publishable 的聚合 outcome，不产生 lifecycle decision。

删除这个 module 后，引用链校验、两 arm 冻结、adapter 重试、诊断抑制和 attempt/result 编排会重新散落到每个 caller，因此该 module 通过 deletion test。

### 2. 一个内部 adapter seam、两个 adapter

内部 `SkillForwardTestAdapter` port 由两个 adapter 满足：

- `DeterministicInProcessAdapter`：无 I/O 的冻结 synthetic output adapter；
- `ConstrainedLocalProcessAdapter`：使用固定 repository worker、固定 Python executable、临时 cwd、环境 allowlist、stdin/stdout 和 `shell=False` 的本地进程 adapter。

local-process adapter 不接受任意 command，不接收 Candidate payload bytes，不写候选目录。它用于验证真实 process seam、timeout、非零退出、output cap 和 parse failure；它不是安全 sandbox，也不构成 Agent runtime。

### 3. 复用已有 Core family，不新增 P7C1 schema

字段映射结果如下：

| P7C1 事实 | 既有承载 | 结论 |
|---|---|---|
| 每次执行开始、失败、重试、runner/environment | `evaluation-attempt/v1` | 可完整表达 |
| 只有成功评分才存在的 score vector | `evaluation-result/v1` | 可完整表达 |
| 成功兼容 projection | `evaluation-run/v1` | 保持既有语义 |
| case × seed × frozen envelope 比较 | `suite-comparison/v1` | 后续 suite 聚合复用 |
| tools/budget/data/evaluator/generator/stat plan/rollback | `artifact-record/v1` + `evaluation-envelope-closure-receipt/v1` | 可完整绑定 |
| P7B Candidate/static/semantic exact pins | attempt 的开放 `environment` descriptor + module preflight | P7C1 工程留档足够 |
| 真实 fresh-session、Router 行为和独立验收结论 | 当前无可授权记录 | P7C1 禁止生成，不以 synthetic receipt 伪造 |

因此 P7C1 不新增 `skill-forward-test-receipt/v1`。真实 observed evidence 到来前，再基于实际字段而不是合成假设决定是否需要 successor family。

### 4. attempt-always/result-optional 保持不变

Replay 与 live adapter 共享 evaluation pipeline 的内部 preparation/assembly seam。runner 一旦开始，timeout、output limit、parse error 或 runner error 都生成 schema-valid attempt；未获得可评分完整输出时不生成 result 或 legacy run，不伪造空 hash、空 score 或 pass/fail。

### 5. P7C1 只允许 synthetic conformance

`run_skill_forward_test` 只接受 `synthetic_conformance` adapter，并要求 P7B4 attestation 明确为 synthetic fixture。P7B4 `protocol_reject` / `protocol_inconclusive` 是合法前置拒绝，两个 arm 均不得启动。

Candidate payload bytes 只在内存中重新对账，不传给 adapter、不写文件、不放入 Skill 根。所有 P7C1 outcome 固定保持以下 claims 为 false：

```text
real_agent_execution_observed
real_independent_semantic_review_completed
fresh_session_validated
runtime_loaded
promotion_authorized
publication_authorized
installation_authorized
activation_authorized
```

## 失败与隐私语义

- plan、引用链、case/suite、input、payload、artifact 或 adapter identity 漂移在执行前抛出 fail-closed error；
- 合法 semantic rejection 返回 `prerequisite_rejected`，不是异常，也不生成虚假 attempt；
- adapter 异常消息不直接进入 append-only payload；只记录异常类型，消息被抑制；
- 已分类 diagnostic 再经过 restricted-content scanner；命中时以固定说明替换；
- subprocess stderr 不进入 Core record；
- 本批不读取外部凭据、不调用网络、不运行 Codex/模型。

## 被拒绝的方案

1. **同时新增 plan/attempt/result/receipt 四个 family**：与 CR4/CR5/CR6 重复，形成浅层协议栈；拒绝。
2. **把 runner output 伪装成 replay artifact**：会丢失真实 runner identity 和执行失败事实；拒绝。
3. **允许 caller 提供任意 subprocess command**：无法维持 P7C1 的受控执行和无外部凭据范围；拒绝。
4. **让 synthetic accept 声称 fresh-session 或 runtime-loaded**：越过证据边界；拒绝。
5. **在 P7C1 接入 Codex、Inspect 或其他外部 Agent**：需要模型、预算、凭据、隔离和真实证据的单独授权；延期。

## 验收

- Math synthetic `protocol_accept` 穿过两个 arm，并生成 existing attempt/result/run records；
- Quant synthetic `protocol_reject` 在 adapter 调用前停止；
- 两个 adapter 穿过同一个 module interface；
- Candidate/envelope/non-Skill-axis mutation 在执行前失败；
- timeout、output limit、parse error、runner error 保留 attempt 且不生成 result；
- restricted diagnostic 不回显原值；
- 工作树、exact archive 双解释器、clean-install、既有 CUDA regression 与 GitHub required checks 全部通过后才允许合并。

P7C1 合并后的证据上限固定为：

```text
P7C1_EXECUTION_SEAM_READY
/ ZERO_REAL_AGENT_EXECUTIONS
/ ZERO_REAL_INDEPENDENT_REVIEWS
/ ZERO_PROMOTIONS
```
