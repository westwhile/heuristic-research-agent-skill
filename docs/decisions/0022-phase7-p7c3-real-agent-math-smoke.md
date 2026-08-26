# ADR-0022：Phase 7 P7C3 real-Agent Math smoke

- 状态：Accepted
- 日期：2026-08-26
- 适用范围：Phase 7 P7C3 single-operator public Math smoke
- 前置：ADR-0013、ADR-0017—ADR-0021

## 背景

P7C1/P7C2 已把 exact Candidate chain、Skill-only axis、attempt-always/result-optional 和
完整 synthetic `case × seed` 网格收进两个 deep Module，但两个 Adapter 都只产生仓库冻结
输出。它们不能证明真实 Agent 进程启动、Candidate bytes 被运行时读取或临时工作区被清理。

P7C3 只关闭这个最小缺口：在不安装 Skill、不使用 hidden case、不生成 PromotionDecision 的
前提下，以两个公开 Math case 和最多四个真实 Codex 进程记录一次 single-operator smoke。

## 决策

### 1. 一个 successor Module interface

P7C3 新增一个行为入口：

```text
run_agent_skill_forward_trial(plan, executor) -> AgentForwardTrialOutcome
```

Module 在 Interface 后统一完成：

1. 复核 P7A Manifest、P7B2 Bundle、P7B3 receipt、P7B4 protocol attestation 与 CR6
   envelope closure 的 exact pins；
2. 冻结 model、reasoning、tools、budget、case、oracle、runner 与工作区策略；
3. 在系统临时目录分别创建 baseline/Candidate 工作区；
4. 只在 Candidate 工作区的 `.agents/skills/<exact-name>` 投影 byte-closed payload；
5. 通过同一 Adapter seam 启动两臂；
6. 以未暴露给 prompt/output schema 的 `SKILL.md` SHA-256 作为 runtime-load oracle；
7. 复用 `evaluation-attempt/result/run` 组装执行事实；
8. 清理本批自建临时目录并返回非 publishable aggregate。

删除本 Module 后，引用链复核、临时投影、双臂隔离、runtime digest、进程净化、attempt 组装与
安全清理会重新散落到 caller，因此通过 deletion test。

### 2. 一个真实外部 seam、两个 Adapter

内部 `AgentForwardExecutor` Port 由两个 Adapter 满足：

- `DeterministicAgentForwardAdapter`：CI contract/mutation/fail-closed 测试；
- `CodexCliAgentAdapter`：真实 Windows 用户认证上下文中的 Codex CLI。

真实 Adapter 固定：

```text
codex exec
+ --ephemeral
+ --ignore-user-config
+ --ignore-rules
+ --sandbox read-only
+ --config approval_policy="never"
+ --config web_search="disabled"
+ output-schema + output-last-message + JSONL
```

PowerShell `-File` 启动器必须接收完整的 `--config` 参数名，不得使用可被启动器参数绑定解释为
`CodexArgs` 缩写的 `-c`。这是 launcher seam 的可执行契约，并由 command contract test 固化。

进程环境使用 allowlist，`GH_TOKEN`、`GITHUB_TOKEN`、`OPENAI_API_KEY`、`CODEX_API_KEY`
及其他 Token/Secret 变量不传入。raw stderr 与原始 JSONL 不进入 Core 或公开 evidence；仅允许
保留其 SHA-256，以便对失败 attempt 去重和对账。

### 3. 不新增 Core family

现有 `evaluation-attempt/v1.environment` 可记录 exact Candidate/static/semantic/closure pins、
ephemeral/sandbox/approval/web-search policy、session ID hash、transcript hash、usage、Candidate
materialized/runtime-loaded 和 workspace cleanup。fresh-session/independent-review claims 仍为 false。

因此 P7C3 不新增 `agent-forward-session-attestation/v1`。原始 session ID、路径和 transcript 属于
仓库外临时事实；公开证据只保存 hash 和计数。

### 4. provider-unseeded smoke 不进入 suite comparison

Codex CLI smoke 没有可声明为随机数控制的 provider seed。P7C3 要求 `Envelope.seed=None`、
`retry_attempts=0`，不把执行序号伪装成 seed，也不生成 `suite-comparison/v1`。每个失败进程仍
形成 attempt；失败结果不得删除或自动重跑到通过。

### 5. 两个公开 Math case、四次进程上限

exact commit Gate 只执行：

```text
explicit-load × baseline/Candidate
+ declared-exclusion × baseline/Candidate
= 4 fresh processes
```

explicit case 要求 Candidate 读取 `SKILL.md` 并回报 exact digest；baseline 必须报告未加载。
declared exclusion 两臂都必须报告未加载，即使 Candidate bytes 在候选工作区可用。

这只验证 bounded runtime behavior；不测统计改善、隐式 Router、真实科研质量或外部采用。

## 安全与失败语义

- Candidate 只写入 Module 创建的系统临时目录，不写 `skills/`、`skills/staging/` 或用户安装根；
- payload 路径必须安全相对，临时目录及父目录不得是 symlink/junction/reparse point；
- runtime digest 不写入 prompt 或 output schema，避免模型直接照抄；
- 非零退出、timeout、parse/output/trace cap、runtime mismatch 和 cleanup failure 均 fail closed；
- raw session、stderr、JSONL、最终输出和本机路径不进入仓库；
- `launcher_process_started` 只表示 wrapper 已启动；只有 JSONL `thread.started` 才能证明
  `agent_session_started`，只有同一有界 trace 中的 `turn.completed` 才能证明
  `agent_turn_completed`；
- wrapper 参数绑定失败仍保留 attempt 与 stderr hash，但计为零个真实 Agent session、零个完成
  turn，不得升级为 real-Agent smoke；
- 四次 Gate 只有在四个 session 均启动、四个 turn 均完成、session hash 互异且两项 runtime
  oracle 均通过时才可 PASS；
- ephemeral session 与 independent fresh-session acceptance 是不同事实，后者保持 false。

## 被拒绝的方案

1. **放宽 P7C1 synthetic-only Adapter**：会改变已验收 Interface 语义；拒绝，使用 successor Module。
2. **新增 attempt/result/session 三套 Schema**：现有 environment 足够承载本批事实；拒绝。
3. **把进程序号写入 seed**：伪造随机性控制；拒绝。
4. **把 Candidate SHA 写入 prompt/schema**：无法证明运行时读取；拒绝。
5. **把 Candidate 安装到用户 Skill 根**：越过本批授权且污染后续 baseline；拒绝。
6. **失败后自动重试**：会引入选择性结果；拒绝。

## 验收与证据上限

- contract/mutation/deletion/fail-closed tests 通过；
- exact archive Python 3.12/3.14、clean-install、CUDA regression 与 GitHub required checks
  全绿；
- 四个真实进程均产生互异 ephemeral session hash；
- explicit-load 与 declared-exclusion 两项 runtime oracle 通过；
- Candidate 未安装、未激活，临时工作区清理成功。

P7C3 的最高状态固定为：

```text
P7C3_REAL_AGENT_SMOKE_RECORDED
/ ZERO_INDEPENDENT_FORWARD_ACCEPTANCES
/ ZERO_HIDDEN_EVALUATIONS
/ ZERO_PROMOTIONS
```
