# ADR-0028：P7F3A real collaboration adapter

- 状态：Accepted
- 日期：2026-09-05
- 范围：Phase 7 P7F3A constrained local-process Adapter 与可审计执行事实

## 背景

P7F0–P7F2 已冻结 collaboration window、三张 ticket、方法自主性与安全/语义
envelope，但唯一实现是 in-process deterministic Adapter。要在不增加第二个编排入口的
前提下进行真实协作校准，必须让一个真实本地进程实现穿过相同
`run_collaboration_window(plan, adapter)` seam，并把超时、token、进程树与临时工作区
清理作为失败关闭的事实，而不是依赖自然语言自报。

冻结的 `collaboration-worker-outcome/v1` 把 adapter identity 固定为 deterministic
实现，且无法表达 session/turn、非重叠 token 计量或清理状态。修改 v1 会破坏已发布
schema 的字节合同，因此需要 successor。

## 决策

1. 保持唯一公共编排 interface `run_collaboration_window(plan, adapter)`；新增
   `CodexCliCollaborationAdapter` 只是同一 Protocol 的第二个实现，不暴露新的 workflow
   API。
2. Adapter 复用 P7D3 `run_process_contained`，以新进程组运行本地 PowerShell launcher；
   命令冻结 `--ephemeral`、`--sandbox read-only`、`approval_policy=never`、
   `web_search=disabled`、模型与 reasoning effort。
3. 新增 `collaboration-worker-outcome/v2`。v1 保持逐字节不变；v2 继续 pin 原 ticket，
   并增加 sanitized work product、launcher/session/turn facts、session/trace/stderr hashes、
   execution/cleanup pair、workspace cleanup 与 usage closure。
4. token 只以 `input_tokens + output_tokens` 计算并闭合 `total_tokens`；
   `cached_input_tokens` 是 input 子集，绝不再次相加，且不得大于 input。CLI 若额外报告
   `total_tokens`，其值必须与计算值相同；必要字段缺失、负数或不一致均产生
   `usage_validation/usage_incomplete_or_inconsistent`。
5. Module 只接受两种 v2 evidence class：`deterministic_fake_launcher_contract` 与
   `real_codex_cli`。fake launcher 即使完整通过也不能产生真实执行 claim；真实模式还
   必须具备 launcher 启动、session、turn completion、闭合 usage、进程树与工作区清理，
   且 worker outcome 无 failure。
6. 原始 session id、JSONL trace、stderr、prompt、本机路径和模型输出不进入 record；只
   保存 SHA-256、大小、枚举状态及通过 restricted-content 扫描的结构化 work product。
   受限输出被 hash 后丢弃并生成 `output_validation/restricted_output`。
7. 任一 execution、cleanup、usage、binding、结构或隐私失败都生成一个 v2 失败 receipt
   并停止后续 ticket；不能因异常而丢掉最需要审计的失败尝试。
8. P7F3B 首次真实 seam smoke 暴露两个实现缺口：launcher parent 非零退出后仍有 owned
   Codex descendant 存活，且 workspace cleanup failure 覆盖了较早的启动失败。修复后，
   containment 在 parent 完成后再次核验并清理 process tree；workspace 删除使用有限次
   指数退避。`failure` 始终保留最先出现的可行动失败（非零退出稳定映射为
   `launcher_exit_nonzero`），而 `execution.process_cleanup_status=failed` 和
   `execution.workspace_cleanup_verified=false` 独立记录随后两层清理失败。只有没有更早
   失败时，cleanup 才成为主 `failure`。

## Deep Module 边界

调用方只提交冻结 plan 与 Adapter。Module 独占 ticket 派生、prompt/response contract、
进程生命周期、usage 归一化、输出净化、预算检查、receipt 组装及后续 dispatch 停止。
launcher 是注入依赖：工程测试只使用 tracked deterministic fake launcher；真实 CLI
会话必须等工程 PR 合入并锚定 exact main archive 后另行执行。

## Evidence ceiling

P7F3A 工程测试证明同一 seam 能承载受约束的本地进程，并能对结构、资源、隐私和清理
失败关闭。fake launcher 不是真实 Agent。即使后续 P7F3B 使用 authenticated Codex CLI，
也只证明六个有界 worker sessions 的执行事实，不证明身份独立、研究质量提升、算力
节约、独立审查、Hidden Evaluation、Promotion、Skill 安装/激活或 P7F4 稳定性。

## 拒绝的替代方案

- 修改 v1 adapter 常量或追加字段：违反 immutable schema policy。
- 新增 `run_real_collaboration`：形成第二个浅层 workflow seam，分叉预算和失败语义。
- 在 record 中保存 transcript 或 session id：扩大隐私与本机信息暴露面。
- 由 worker 自报 timeout、token 或 cleanup：无法作为进程级工程证据。
- 工程 PR 中直接消耗真实多 Agent 会话：会在 contract 未合入前混合代码与校准证据。

## 验证要求

- Math/Quant 通过同一公共 interface 与 deterministic fake launcher；
- success、ticket-binding mutation、required-field deletion、usage 缺失、受限输出、
  execution/cleanup failure 均有 contract/mutation/deletion/fail-closed 测试；
- completed parent 遗留的真实测试子进程必须被回收；瞬态目录句柄错误必须经有界重试
  恢复，双失败必须同时保留 primary failure 与 workspace cleanup fact；
- fake evidence 的真实执行 claim 恒为 false，原始敏感值与本机路径不进入 receipt；
- v2 schema 有 valid/invalid fixtures、canonical fixture pin、schema byte pin、family graph
  与 publication restricted scan；
- exact archive 双解释器、clean-archive install 与既有 CUDA regression 全部通过后才能
  push/PR；真实 P7F3B 会话须等待 exact merge SHA 的 main CI 全绿。
