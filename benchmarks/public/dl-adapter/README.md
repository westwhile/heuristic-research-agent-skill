# DL Adapter synthetic acceptance catalog

`catalog.json` 固定 Phase 6 L4 的 10 个 **SYNTHETIC** 验收场景。它不是
Phase 3 evaluator 的 `suite/v1`，不进入 `benchmarks/public/registry.json`，也不
报告真实模型质量、GPU 可用性或科研结论。

目录覆盖三类注入终态（OOM、NaN、中断/抢占代理）、失败 seed 与 best-only
selection、checkpoint 篡改、单因素 early-stopping ablation、hidden-unit scale、
FLOP proxy 等算力比较，以及 checkpoint payload 不进入报告。`interrupt` 只是
进程内合成 preemption proxy；当前未观察真实调度器抢占、进程重启或外部存储恢复。

所有 comparison 均以 seed 为复现单位，固定数据形状、case pin 和 runner pin。
scale 报告只做描述；compute-matched 仅在每 seed 的样本、token、FLOP proxy 与
相关 cap 对齐后允许工程性描述比较。即使 Gate 通过，报告仍禁止因果、稳定性、
模型能力、框架或 GPU 结论。

PowerShell 7 验证入口：

```powershell
$env:PYTHONPATH = 'src'
python -B -m unittest tests.e2e.test_dl_l4_acceptance -v
```
