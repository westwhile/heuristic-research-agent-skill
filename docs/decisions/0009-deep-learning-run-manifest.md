# ADR-0009：Deep Learning 执行 manifest、预算与 checkpoint 恢复边界

- 状态：Accepted（Phase 6 第一层）
- 日期：2026-08-23
- 关联：ARCHITECTURE §4.2/§5.3、总体计划 Phase 6、ADR-0005（Adapter interface v1）、ADR-0008（ML Adapter 与合成 runner）

## 背景

Phase 5 已建立 `ml` 领域的任务、case、claim、evidence 合同和标准库合成 runner，但明确不提供真实 ML/DL 框架执行。Phase 6 要增加硬件、运行时、框架/CUDA、训练预算、checkpoint lineage、恢复、early stopping、失败 seed、消融和 scale study 治理；这些内容是 ML 执行路径的 DL 特有复杂度，不应复制 Core 或再造一套平行的科研状态机。

在启动 runner 前必须先冻结两个事实边界：

1. 运行配置声明不等于机器实际执行，更不等于 GPU 全量训练成功；
2. checkpoint 不得把大型模型文件写入 Git，只能以外部 locator、内容哈希和状态 lineage 进入可审计合同。

## 决策

1. **DL 是 ML 执行治理扩展，不是第四个 `DomainAdapter`**。Phase 6 不新增 `domain-task/v3`，不把 `dl` 注册进参数化三操作 suite，也不新增 Core family。DL manifest 直接绑定既有 `ml-case/v1` 的 canonical SHA-256；任务、claim 与成熟度判断仍经过 ML Adapter。若未来出现不属于 ML 语义的独立 DL 领域需求，再单独证明新 domain seam，而不是预先抽象。

2. **第一层只有一个公开 interface：`DLRunManifest`**。调用方通过 `from_payload`/`from_json` 构造不可变、hash-bound manifest，并可读取 payload、case pin、GPU 请求标记与 resume mode。实现集中隐藏 schema 加载和跨字段语义 Gate；`deep_learning.__all__` 只暴露该类型，根 `research_evolution.adapters` 公共面不变。

3. **新增 `dl-run-manifest/v1` Adapter schema，零新 Core schema**。manifest 必须绑定 manifest/run/study/case、runner name/version/source hash、execution mode、hardware、OS/Python runtime、framework/backend、container、budget、optimizer、scheduler、checkpoint policy 和 caller-injected timestamp。schema 与 fixture 延续 ADR-0004 的 raw-byte/canonical-hash pin，仍由独立 `schemas/adapters/` root 校验，不可发布到 Core store。

4. **manifest 的证据上限固定为 `configuration_only`**。字段 `evidence_scope` 只能取该值。`gpu_training + cuda` 仅表达请求的运行包络；它不证明硬件存在、框架可导入、训练发生或结果有效。真实 runner 后续必须另产观察记录，并反向绑定 manifest SHA-256；CPU/small fixture 与 GPU full training 的状态不可共用。

5. **执行 mode、accelerator、OS 与 backend 必须互证**。`cpu_fixture` 只接受 CPU；`gpu_fixture`/`gpu_training` 只接受 CUDA/ROCm/MPS。CUDA/ROCm 必须声明 backend version，CPU/MPS 禁止伪填该字段；ROCm 仅 Linux、MPS 仅 macOS、CUDA 仅 Windows/Linux。以上是声明一致性 Gate，不是硬件探测。

6. **训练预算使用显式硬上限**。样本数必须为正；step、epoch、token、FLOP 与 cost proxy 均非负，且至少一个工作/成本维度为正。v1 只冻结上限，不记实际消耗；后续 runner 的 ledger 必须绑定 manifest，恢复时携带 prior-consumption hash，并按 `cumulative_no_double_charge` 累计，禁止恢复后清零或重复扣账。

7. **checkpoint 只允许外部 locator + SHA-256**。locator 只能是 opaque `artifact://`/`checkpoint://` 引用，不接受文件路径、HTTP URL 或仓库相对路径。retention 与 `max_retained` 必须一致；`exact_checkpoint` 恢复必须携带 source run、checkpoint content、已完成 step/epoch、既有预算 ledger、optimizer state，以及启用 scheduler 时的 scheduler state。`fresh` 禁止携带任何恢复字段。模型、optimizer 或 scheduler payload 本身均不进入 Git。

8. **manifest module 是纯声明深模块**。除既有 Adapter schema loader 读取包内只读 schema 定义外，构造过程不读取调用方数据或 artifact，不探测硬件、不读时钟、不访问网络、不启动子进程、不加载训练框架，也不产生 checkpoint。所有运行事实由调用方注入；测试仅通过公开 interface 观察结果与失败规则。

9. **版本与冻结纪律**。`dl-run-manifest/v1` 一旦发布即字节冻结；新增观察事实、训练结果或 checkpoint selection 结果使用 successor schema，不向 v1 偷加字段。只有两个真实 runner 实现共享同一执行 seam 后，才可宣称该 runner seam 稳定；当前 manifest interface 不作此声明。

10. **Phase 6 分层交付**：L1 = 本 ADR + manifest schema/fixtures/深模块；L2 = dry-run 与 small-fixture runner、预算 ledger、失败状态；L3 = checkpoint emission/recovery、early stopping、selection 与多 seed 聚合；L4 = OOM/NaN/preemption cases、ablation/scale/compute-matched reports、硬件矩阵和验收。manifest、runner、selection、cases 保持独立 commit；只有最终 `git archive` 双解释器 Gate、平台 CI 与声明过的真实硬件证据全部满足后，才进入 `v0.7.0` 发布 Gate。

## 后果

优点：

- 删除该模块时，DL 的硬件/预算/checkpoint 复杂度集中回到一个调用点，不会散落进 Core 或 ML Adapter；
- manifest hash 可成为后续 runner、checkpoint 和报告的统一配置 pin；
- `configuration_only` 从合同层阻断“声明了 GPU”到“GPU 已执行”的证据升级；
- 外部 locator 与累计预算 pin 为大型 artifact 隔离和恢复记账预留了可验证入口。

代价：

- v1 字段较严格，框架或硬件包络扩张必须走 successor；
- 当前仅能证明合同与语义 Gate 的工程行为，不能证明任何训练框架、GPU 或真实数据路径；
- exact resume 的完整性仍需后续 runner 对实际 checkpoint/ledger 做交叉绑定，本层只验证声明形状与一致性。

## 拒绝的方案

1. **把 DL 注册为第四个 DomainAdapter**：DL 当前是 ML 执行方式，不是独立的任务/claim 语义；新 domain 只会复制三操作和成熟度逻辑。
2. **直接把硬件/预算字段塞进 `ml-case/v1`**：已发布 schema 应保持冻结，且 case 描述实验设计，运行 manifest 描述一次具体执行配置，两者生命周期不同。
3. **只写自由格式 YAML/Markdown manifest**：无法获得 schema Gate、canonical hash 与 archive 中的确定性合同。
4. **在 manifest 构造时自动探测 CUDA/GPU**：破坏纯度与可重放性，也会把“当前机器状态”混成调用方可移植配置。
5. **把 checkpoint 文件提交到 Git**：违反 Phase 6 artifact retention Gate，并给仓库体积、隐私和权利审计带来不可接受风险。

## 增补 A1（2026-08-23，L2）：dry-run、CPU small fixture 与预算/失败终态

L2 在 L1 manifest 上增加一个显式 runner 子模块，不扩张根 Adapter interface，也不新增 schema/Core family。

1. **唯一 runner interface**：`run_fixture(manifest, fixture_payload) -> DLRunResult`。runner 同时拥有 fixture 校验、确定性 tiny-MLP、预算规划/记账和终态分类；调用方不需要分别调用 validator、trainer、ledger 或 failure mapper。`deep_learning.__all__` 仍只暴露 `DLRunManifest`，runner 通过显式子模块导入。
2. **能力包络**：runner 0.1.0 仅接受 `dry_run` 与 `cpu_fixture`。前者验证完整声明并预测首个预算 Gate，但不训练、不消耗预算；后者使用 Python 标准库对最多 32 行、8 个 feature、8 个 hidden unit、100 step 的合成标量回归 fixture 执行确定性 tiny-MLP。`gpu_fixture`/`gpu_training` 和 `exact_checkpoint` 一律 fail-closed；无 PyTorch/TensorFlow/JAX/CUDA import、GPU 探测或 checkpoint I/O。
3. **结果是 canonical artifact，不是新事实 family**：`DLRunResult` 包装 `synthetic-dl-run-result/v1` canonical bytes，并绑定 manifest SHA-256、case/study/run、runner source pin、fixture content hash、execution observation、预算 ledger、metrics、failure 和 limitations。它不可进入 Core store，也不是 GPU/真实数据/科研 Claim。
4. **预算 ledger 语义**：`max_samples` 在 L2 表示参与训练的唯一 fixture 行数上限；每个 full-batch step 计一个 epoch；token 消耗恒为 0；FLOP 是公开固定公式的确定性 proxy。wall-clock 和货币成本不读取时钟，固定为 `not_observed`，不得把 cost limit 假装成已执行 Gate。若 manifest 只给 cost cap、没有 L2 能执行的 step/epoch/FLOP cap，runner 拒绝执行。恢复尚未开放，故 `prior_consumption_sha256=null`，同时保留 `cumulative_no_double_charge` 记账标签供 L3 交叉绑定。
5. **终态而非异常吞失**：合法但超预算的运行返回 `budget_exhausted`；fixture 声明的 `nan`/`interrupt`/`oom` 注入分别返回 `numerical_failure`/`interrupted`/`resource_exhausted`，并记录失败前已消费的 step。注入故障必须带 `synthetic_injection=true` 和限制句，不能表述为实际 OOM、中断或框架故障。结构非法、runner pin 不匹配、能力未实现继续抛 `DLRunnerError`。
6. **确定性与测试面**：初始化只由 SHA-256(seed,label) 派生；无全局随机状态。相同 manifest/fixture 在 Python 3.12/3.14 上必须得到 byte-identical artifact hash。测试只穿过公开 runner interface，覆盖 dry-run、正常 CPU fixture、四类预算 Gate、三类注入失败、预算前停止、输入/runner/resume/GPU fail-closed、依赖 allowlist 和零文件系统副作用。

L2 仍只构成 synthetic engineering evidence。checkpoint emission/recovery、early stopping/selection、多 seed 聚合、真实框架/GPU 观察、OOM/NaN/preemption 真实 case 与硬件矩阵继续属于 L3/L4。
