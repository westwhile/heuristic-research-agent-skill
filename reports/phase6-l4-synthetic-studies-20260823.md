# Phase 6 L4 合成失败与比较报告（2026-08-23）

状态：**commit-bound 合成工程证据**。本报告只证明 L4 case、study-report 与
resource-parity Gate 在标准库 tiny-MLP fixture 上按合同工作；不构成真实 OOM、
真实抢占、框架/GPU 执行、数据验收、模型能力或科研结论。

## 10 个公开合成 case

`benchmarks/public/dl-adapter/catalog.json` 固定 10 个场景：3 个注入失败终态、
2 个 selection 完整性场景、1 个 checkpoint 篡改场景、3 个比较公平性场景和
1 个 artifact retention 场景。目录由 E2E 公共入口逐项执行，不进入 Phase 3
evaluator registry。

- OOM、NaN 与 `interrupt` 分别落为 `resource_exhausted`、
  `numerical_failure` 与 `interrupted`，且均带 `synthetic_injection=true`；
- 失败 expected seed 会使 study comparison 进入 `incomplete_evidence`，最低成功
  数不足时 selector 返回 `insufficient_successful_runs`，不会生成 best-only 结论；
- checkpoint 内容篡改由 content-hash Gate 拒绝；report 仅保存
  `checkpoint://` locator、SHA-256 与 lineage，不读取或保存模型 payload。

`interrupt` 只是确定性进程内 preemption proxy。本轮没有真实调度器抢占、进程
重启、外部 checkpoint store 或 scheduler recovery 证据。

## 三种比较设计

复现单位是 seed，固定 seed `[1, 2, 3]`。每条 evidence 同时提交 exact manifest、
fixture、runner result 与 selector artifact；reporter 先用 manifest/fixture SHA 与
result/selection 交叉绑定，再比较数据内容、learning rate、optimizer/scheduler、
硬件/运行时/框架声明等冻结轴。任一失败/缺失 seed 都阻止比较。报告的 observed
range 不是置信区间。

| 设计 | 唯一声明因素/配平方式 | report SHA-256 | Gate | 解释边界 |
|---|---|---|---|---|
| early-stopping ablation | 仅切换 early-stopping policy；所有 consumed 维度与 cap 相同 | `93b8cf4afa9370a13c5e51e160924f17271ca454b6d5309e24f4bae287a68f99` | `eligible_descriptive_comparison` | 仅合成工程描述 |
| hidden-unit scale | hidden units 2→4，steps/cap 不变 | `5afaea71f0fe27a1f0487c3e9abb03549755d1539c38aaff3783a52e82fbc01b` | `descriptive_scale_only`；每个 seed 的 FLOP proxy 不匹配，跨 arm mean difference 留空 | 禁止直接能力比较 |
| FLOP-proxy compute-matched | hidden units 2→4；steps 8→4；每 seed samples/tokens/FLOP proxy 与相关 cap 相同 | `b0ab85d04a3288d9d5256253ca176bcf75efe5801dfae678151d57314e5e854e` | `eligible_descriptive_comparison` | FLOP proxy 相同不等于时延、成本、显存或能耗相同 |

三组报告中的 metric 差异来自刻意构造的小型合成 fixture，不用于判断模型优劣；
`capability_claim_allowed=false` 在所有 Gate 状态下固定成立。

## Case Package

集成测试通过既有 `capture_case` 公共入口，分别为 OOM、NaN、interrupt、
checkpoint recovery rejection 与 compute-matched comparison 构建 5 个确定性的
`research-case-package/v2`。每个 package 绑定 Task、Run、engineering Claim、
engineering-only Evidence 与 output hash，且通过 privacy/eligibility Gate；package
只保存输出 manifest/hash，不嵌入 checkpoint model/optimizer payload。这些 package
在测试内重建并验证，不是实际故障、真实数据或 Pattern/Skill 晋级证据。

## 硬件与复现包络

机器可读矩阵见 `docs/governance/DL_SUPPORT_MATRIX.json`。当前实际实现是 Python
标准库 CPU tiny-MLP；runner artifact 明确写入 `hardware=declared_not_observed`
与 `framework=not_loaded`。PR #21 的 L4 implementation commit `45047261...`
已通过真实 `git archive` 双解释器 971/971（各 1 个预期 Git tracking skip）与
exact-head CI run `32633282906` 的四项 required jobs；两个 Windows PowerShell
governance 步骤成功。以上只形成 L4 合成平台工程证据，跨 GPU 数值复现性仍
全部未验证。
