# Scripts

可重复、非交互的验证、打包、manifest 和 release 辅助脚本。脚本不得自行 push、tag、发布、安装或修改 Champion。

## Phase 0 baseline

- `freeze_external_skill_baseline.py`：校验 portable ZIP 内置 checksums，比较 payload 与已安装 Skill，并生成不含本机绝对路径的 manifest、tree hash 和环境清单。
- `run_math_research_baseline.py`：执行 Windows Python/PowerShell regression、入口 smoke test、benchmark 和可选 Skill validator；原始日志必须放在仓库外，仓库内只保存脱敏摘要与日志哈希。
- `build_external_skill_portable.py`：从已校验的 portable 基包和经过完整回归的候选 Skill 构建确定性更新包，重建 payload、manifest 与 checksums；不会安装或覆盖已有 ZIP。
- `check_github_auth_context.ps1`：识别 Codex 沙箱与真实 Windows 用户的 keyring 边界；不读取、不返回 Token 值，并用不同状态区分上下文隔离和真实认证失败。

`freeze_external_skill_baseline.py` 与 `build_external_skill_portable.py` 要求输出目录位于已安装 Skill 之外。回归编排器以 `0/1/2` 分别表示 `passed/failed/partial`；`blocked` 和 `not_run` 都会阻止全量 PASS。
