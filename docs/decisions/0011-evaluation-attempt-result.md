# ADR-0011：EvaluationAttempt / EvaluationResult——失败尝试必留档、评分结果可缺席

- 状态：Accepted（Correctness Reset CR4）
- 日期：2026-08-24
- 关联：ADR-0004（schema 兼容政策）、ADR-0006（Public Evaluator MVP）、`evaluation-run/v1`、总体计划 backlog 任务 21

## 背景

`evaluation-run/v1` 同时强制 `output.output_sha256` 与非空 `score_vector`，但 verdict 又允许 `error` 与 `inconclusive`。timeout、output-limit、parse error、runner error 或 scorer error 通常没有完整 output 和合法 score，因此旧 pipeline 只能返回 `run_payload=None`。最需要审计的失败尝试反而不能进入 append-only store；伪造空分数、哨兵 hash 或虚构 output 又会破坏证据语义。

该缺口不能原地修改已冻结的 `evaluation-run/v1`。CR4 只关闭失败尝试的工程审计缺口，不处理 suite-level 统计、真实 Candidate Agent 执行、hidden evaluator、PromotionDecision 或 Skill 生命周期。

## 决策

1. **additive family，不改旧字节**：新增 `evaluation-attempt/v1` 与 `evaluation-result/v1` 两个 Core family；`evaluation-run/v1` 的 schema、fixtures、golden hash、注册与成功路径兼容面保持不变。这里是把“执行事实”和“评分结果”拆成两个对象，不是给旧 family 原地换语义。
2. **attempt-always 的起点**：case/suite pin、scorer level、coverage level 等调用前合同校验仍可在 replay 开始前失败并抛出异常；一旦 replay 开始，正常、失败、timeout、重试耗尽和预期 scorer 输入错误都必须返回 schema-valid `attempt_payload`。内部编程错误不伪装成业务 attempt。
3. **result-optional 与单一事实源**：只有 replay 得到唯一完整 output 且 scorer 生成非空 score vector 时才组装 `result_payload`。result 必须 hash-pin 对应 attempt，并且只保存 score vector；output、scorer、gate、verdict 与 coverage 由 attempt 单一保存，不能在 result 中出现第二份可能冲突的声明。失败 attempt 的 result 合法缺席，不生成空分数、哨兵 hash 或空 output。
4. **失败语义**：attempt 的 `execution.status` 冻结为 `completed`、`timeout`、`output_limit`、`parse_error`、`runner_error`、`scorer_error`。`completed` 与 `scorer_error` 必须至少绑定一个真实 output；所有 error status 必须至少含一项结构化 diagnostic。attempt 同时保存 scorer identity、gate results、verdict 与实际 retry attempts。
5. **artifact 留痕边界**：完整/部分 output、log 与 trace 只以 SHA-256 和可选安全相对 locator 进入记录；当前离线 replay runner 不产生 log/trace 工件，因此 `artifacts=[]` 是诚实状态。scorer diagnostic 不回显 caller-controlled 配置或 output 内容；详细 trace 若未来存在，必须作为另行治理的 hash-bound artifact。
6. **公开 Interface 兼容**：`PipelineOutcome` 新增必有的 `attempt_payload` 与可空的 `result_payload`；既有 `run_payload` 继续作为 pass/fail 的 legacy projection，旧 compare/report 路径不在 CR4 改写。由 `run_id` 确定性派生 `-attempt` 与 `-result` ID，避免跨 family 逻辑 ID 碰撞。
7. **图语义**：attempt 必须 pin case 与 suite；result 必须 pin attempt。两个 family 与引用合同在同一提交注册，沿用通用 dangling/cross-type/pin/duplicate/cycle 验证，不新增 violation kind。
8. **证据上限**：本切片仍是 L0/L1 的确定性离线 artifact replay。它证明失败执行可以按合同留档，不证明真实 Agent 被执行、Skill 改变行为、hidden suite 独立、统计晋级有效、真实科研能力或外部采用。
9. **统计边界不变**：旧 `compare()` 继续使用旧 `evaluation-run/v1`，其 metric-dimension 观测单位缺陷仍是后续独立 CR；在 suite-level case × seed 比较完成前，PromotionDecision Gate 保持关闭。
10. **测试义务**：两个新 family 各有 minimal/full 与至少五项 invalid fixtures、minimal canonical hash、schema 原始字节 hash、领域中性扫描、registry 精确枚举、发布/图 round-trip 和 pin mismatch 测试；pipeline 通过公开 interface 覆盖 success、gate fail、四类 replay error 与 scorer error。

## 后果

优点：失败、timeout 和 scorer error 不再从正式审计链消失；成功结果与失败尝试不再被一个同时要求 output/score 的对象强行混合；旧发布记录和现有报告消费者保持兼容。

代价：成功路径暂时同时提供 attempt/result 与 legacy run projection；log/trace 只定义引用合同，当前 runner 没有对应工件；suite-level 比较仍必须在后续批次重新设计。

## 拒绝的方案

1. **原地放宽 `evaluation-run/v1` required**：违反 schema 字节与语义不可变政策。
2. **失败时填空 score 或固定零 hash**：制造不存在的证据，破坏内容寻址与统计解释。
3. **只返回内存异常对象、不进入 Core**：失败仍无法 append-only 发布和图追踪，未关闭缺口。
4. **CR4 同时重写统计与接入真实 Agent runner**：混合三个独立风险面，无法保持可审查的接口和证据上限。
