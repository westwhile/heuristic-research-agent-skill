# ADR-0025：P7D3 外部 Agent 进程树执行隔离加固

- 状态：Accepted
- 日期：2026-08-29
- 范围：Phase 7 P7D3 external-process engineering seam

## 背景

P7D3 的一个 Windows 校准会话在冻结的 1800 秒执行上限到达后，直接 launcher
已被终止，但继承 stdout/stderr handle 的后代进程继续存活，使外层
`subprocess.run()` 等待管道关闭。该结果只能记为 `capture_inconclusive`；它不构成
模型失败，也证明原实现没有闭合“超时即结束整个受控执行树”的隔离合同。

## 决策

1. 保持唯一公开行为接口 `run_agent_skill_forward_trial` 不变；新增包内深模块
   `_process_containment.run_process_contained`，独占外部进程的 spawn、communicate、
   timeout、tree termination、reap 和清理核验。
2. POSIX 使用独立 session/process group；超时后先向整个 group 发送 `SIGTERM`，
   在有限 grace window 后向仍存活的 group 发送 `SIGKILL`，最后 reap owned root
   并核验 group 消失。
3. Windows 使用新的 process group；超时前通过 Toolhelp snapshot 固定 root 的递归
   descendants，执行 `taskkill /T /F`，再对仍存活的已固定 PID 逐个执行受控终止和
   handle wait，最后 reap owned `Popen`。直接 launcher 已退出不能使已记录 descendants
   失去清理责任。
4. 执行与清理事实只能形成以下精确配对：

   | execution status | cleanup status | cleanup verified |
   | --- | --- | --- |
   | `not_applicable` | `not_applicable` | true |
   | `completed` | `not_required` | true |
   | `timeout` | `verified` | true |
   | `launch_failed` | `not_started` | true |
   | `cleanup_failed` | `failed` | false |
   | `executor_failed` | `unverified` | false |

   任何交叉组合均 fail closed。
5. timeout 只有在整个进程树清理已验证时才映射为现有 `timeout`；清理不能闭合时，
   以现有 schema 合法的 `runner_error` 留档，并使用固定、脱敏诊断
   `Codex CLI process-tree cleanup failed`。不得把 cleanup failure 降级为普通模型超时。
6. P7D1A 和 P7D1B 透传三项事实。`process_tree_cleanup_verified=false` 分别阻断
   qualified failure 与 Candidate proposal；workspace 字节删除与进程树清理是两个
   独立 Gate，不能相互替代。

## Schema 映射证明

本批不新增 Core schema。执行 attempt 仍由 `evaluation-attempt/v1` 的 `timeout` 或
`runner_error` 表达；三项 containment 事实进入既有 environment 或非发布 outcome。
它们描述执行器治理，不是新的科研结果、Candidate 内容或 lifecycle authority。

## Evidence ceiling

进程树测试证明 Windows/Ubuntu 上的 deterministic timeout cleanup 工程合同；它不证明
Codex 解题质量、科研有效性、独立审查、Skill 改善、hidden evaluation 或 Promotion。
本批不安装、激活、发布 Skill，不生成 Tag/Release，也不改变 P7D3 的
`ZERO_QUALIFIED_FAILURES / ZERO_REAL_CANDIDATES` 结论。

## 验证

- Windows/Ubuntu 父→子→孙三层真实进程树超时后全部 PID 消失；
- 直接 launcher 退出或 `taskkill` 不完整时，已固定 descendants 仍被逐一清理；
- cleanup failure 与 timeout 的语义、诊断和 blocker 不可互换；
- 矛盾 execution/cleanup facts 被 mutation tests 拒绝；
- P7D1A 不生成 qualified failure，P7D1B 不生成 Candidate；
- 既有 deterministic/Codex Adapter、Math/Quant contract 和隐私不回显测试保持通过。
