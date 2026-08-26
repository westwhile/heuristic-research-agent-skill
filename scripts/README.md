# Scripts

可重复、非交互的验证、打包、manifest 和 release 辅助脚本。脚本不得自行 push、tag、发布、安装或修改 Champion。

## Phase 0 baseline

- `freeze_external_skill_baseline.py`：校验 portable ZIP 内置 checksums，比较 payload 与已安装 Skill，并生成不含本机绝对路径的 manifest、tree hash 和环境清单。
- `run_math_research_baseline.py`：执行 Windows Python/PowerShell regression、入口 smoke test、benchmark 和可选 Skill validator；原始日志必须放在仓库外，仓库内只保存脱敏摘要与日志哈希。
- `build_external_skill_portable.py`：从已校验的 portable 基包和经过完整回归的候选 Skill 构建确定性更新包，重建 payload、manifest 与 checksums；不会安装或覆盖已有 ZIP。
- `check_github_auth_context.ps1`：识别 Codex 沙箱与真实 Windows 用户的 keyring 边界；不读取、不返回 Token 值，并用不同状态区分上下文隔离和真实认证失败。

`freeze_external_skill_baseline.py` 与 `build_external_skill_portable.py` 要求输出目录位于已安装 Skill 之外。回归编排器以 `0/1/2` 分别表示 `passed/failed/partial`；`blocked` 和 `not_run` 都会阻止全量 PASS。

## OSS-R0 provenance

- `verify_source_provenance.py`：在工作树中使用 Git 的 tracked + 非忽略拟议文件清单，在归档树中使用实际文件清单；按 `docs/governance/SOURCE_PROVENANCE.json` 的 first-match 规则验证全覆盖、固定分类计数、`unknown=0`、Apache-2.0 元数据以及 `LICENSE`/`NOTICE`。使用 `--json` 可输出机器可读报告。
- `verify_archive_suite.py`：从指定 commit 的真实 `git archive` 运行双解释器完整测试；只接受与调用解释器不同的第二解释器，并在结论中绑定 commit SHA。
- `verify_dl_checkpoint_recovery.py`：仅从精确 commit 的归档树运行真实 PyTorch/CUDA checkpoint 恢复 Gate；绑定 Git commit/tree object ID 与 archive SHA-256，使用 source、resume、uninterrupted control 三个独立进程，并只输出不含本机路径的哈希收据。该 Gate 仍只是单主机 bounded synthetic engineering evidence。
- `verify_dl_same_host_reproducibility.py`：仅从精确 commit 的归档树运行同主机 PyTorch/CUDA 复现 Gate；绑定 Git commit/tree object ID 与 archive SHA-256，对 3 个预注册 seed 各启动 2 个新进程，保留失败 seed，并显式记录可用或不可用的 `nvidia-smi` driver 观测。计时与峰值显存不进入精确复现投影；该 Gate 不构成真实数据、跨 GPU、科研、生产或采用证据。
- `verify_dl_controlled_interruption_recovery.py`：仅从精确 commit 的归档树运行受控子进程终止恢复 Gate；父进程必须先验证原子 checkpoint commit signal、nonce、父/子 PID 绑定与权威载荷哈希，随后只通过自己持有的 `Popen` 对象请求终止，再由新进程恢复并与 uninterrupted control 精确对账。该 Gate 不是 scheduler 抢占、真实数据、生产或采用证据。
- `verify_p7c3_math_agent_smoke.py`：只从 exact commit/archive 运行两个公开 Math case 的 baseline/Candidate 四进程 Codex smoke；Candidate 仅投影到仓库外临时 `.agents/skills/`，固定 ephemeral/read-only/no-web/no-retry，公开 evidence 只保留 hash、计数和 verdict，不保存 raw session、JSONL、最终输出或本机路径。
