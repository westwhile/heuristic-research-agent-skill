# ADR-0027：P7F collaborative autonomy foundation

- 状态：Accepted
- 日期：2026-09-04
- 范围：Phase 7 P7F0–P7F2 contract、deep Module 与 deterministic Adapter

## 背景

此前的长程研究编排容易把主控端的路线偏好固化成子任务步骤。这样虽然便于检查，却会
把合法的方法切换误判为漂移，迫使工作单元频繁等待重派，增加空转和重复计算。相反，
完全开放的委派又会模糊目标、证据门槛、权限、预算与发布责任。

本设计受用户提供的 `pika_math_learning_toolkit-2.1.0.zip` 中
`math-research-solve v2.31` 所体现的抽象“稳定外层约束、提高执行单元方法自主性”思路
启发。审查时记录的 ZIP SHA-256 为
`b2f50874398c079f7dc083feae62b9cbae4b774f9fb96d15199d7bf3ce0c5480`，包内
SOURCE_VERSIONS 所列 source-tree SHA-256 为
`9f9bd3b09c0a2a0f2be825db69e246a644a53b438c702a88e54635fc12208461`，inventory
SHA-256 为
`2a9d1f0fe89a2b04455bccac56494f06539698d0a2f2fd0a26055fc54b73cdf7`。审查未在该
archive 中观察到可支持复制 payload 的 LICENSE/COPYING/NOTICE，因此本批只采用抽象
设计启发；不复制其中源码、schema、fixture、模板、提示词或说明表达。

## 决策

1. 新增单一高杠杆 interface：
   `run_collaboration_window(plan, adapter) -> CollaborationWindowOutcome`。
   Module 在任何 Adapter 调用前验证完整计划并一次性派生所有 tickets。
2. 主控端冻结的是语义与安全 envelope：active target、claim scope、completion/evidence
   standard、输入 artifact pins、权限、工具集合、总预算和停止信号；不得冻结 worker 的
   方法序列。
3. 每个 window 恰有 A/B/C 三个中性槽位，映射为 `explorer_a`、`explorer_b`、
   `explorer_c`。至少两个路线为 `direct` 或 `enabling`，最多一个为 `hedge`。角色名不
   暗示身份独立性、证明责任或模型能力。
4. ticket 明确授权 worker 在同一目标与 envelope 内选择、组合、放弃、替换方法，创建
   辅助工作，调用获准工具并提前停止。方法改变只写入
   `substantive_method_changes`，不要求重派 ticket。
5. 改变 active target、扩张 claim scope、降低 evidence standard、扩权、超预算或发布
   权威状态均不属于方法自主性。任一 scope-compliance 失败必须生成稳定的
   `scope_validation/scope_violation` outcome 并停止后续 dispatch。
6. 新机会可以触发至多一次预算扩展，但必须同时有 hash-bound evidence 与明确的
   expected gain，且仍受预留上限及 window hard totals 约束。仅“运行时间不足”不是扩展
   理由。
7. 跨目标机会只能形成 `future_route_proposal`，供下一轮规划决定；当前 window 不得据此
   改写 active target。
8. 增加三类可发布、领域无关 Core records：
   `collaboration-window-plan/v1`、`collaboration-ticket/v1`、
   `collaboration-worker-outcome/v1`。图关系固定为
   `research-task -> window -> ticket -> outcome`，所有边均要求 SHA-256 pin。
9. P7F2 只实现 `DeterministicCollaborationAdapter`。它不创建进程、不访问网络、不写文件，
   只回放冻结 synthetic observations。按照两实现规则，该 Adapter seam 仍为 provisional，
   不能宣称稳定。

## Fail-closed 与隐私

- 计划、tickets 与 outcomes 在构建时执行 restricted-content 扫描；错误只返回字段位置与
  模式类别，不回显匹配值。
- 未知字段（包括试图预设具体方法族的字段）由 schema `additionalProperties=false`
  拒绝。
- route/role 错配、缺失资源或 scope 声明、非法终态、无证据扩展及资源越界均拒绝。
- `candidate`、`verified_partial`、`bounded_negative` 与 failed/inconclusive 各有不同的
  最小证据合同，禁止用空 artifact 或伪造分数填充失败。
- Adapter 异常只暴露异常类型，不持久化原始消息；P7F2 不记录 transcript、session id、
  本机路径或模型输出。

## Evidence ceiling

P7F0–P7F2 只证明合同、图引用、预算与失败语义能在 deterministic in-process fixture 中
工作。它不证明真实多 Agent 协作、Agent 身份分离、研究质量、算力节约、独立验证、
Candidate 改善、Hidden Evaluation、PromotionDecision、Skill 发布、安装或激活。
P7F3/P7F4 必须获得独立授权并使用新的预注册与真实会话证据。

## 拒绝的替代方案

- **由主控端列出逐步方法脚本**：会把探索决策上移，重现过度约束与等待重派。
- **只给自然语言自由度、不冻结合同**：无法区分方法变化与语义漂移，也不能审计预算。
- **当前直接接入真实多 Agent Adapter**：会在合同尚未完成 deterministic 校准前消耗真实
  会话并扩大失败面。
- **把 future proposal 自动变成当前路线**：会绕过目标冻结与主控责任。

## 验证要求

- Math/Quant synthetic plans 穿过同一领域无关 interface；
- A/B/C、direct/enabling/hedge 组合、总预算和额外预算证据均 fail-closed；
- 方法替换在同一 ticket 内通过，语义漂移在首个违规 outcome 后停止；
- task/window/ticket/outcome 图完整时通过，pin mutation 时失败；
- fixture/schema golden hashes、restricted-content、mutation/deletion 和 evidence-ceiling
  claims 通过合同测试；
- 不调用真实 Agent，不物化或安装 Skill，不触碰 `skills/staging/`。
