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

## 增补 A2（2026-08-23，L3）：checkpoint/recovery、early stopping 与多 seed selection

L3 保持 L1 manifest schema 和 Core 公共面不变，在显式 runner/selection 子模块内闭合合成执行状态治理。

1. **runner interface 向后兼容而不扩大根 Adapter seam**：唯一执行入口仍是 `run_fixture(manifest, fixture_payload, *, checkpoint_payload=None)`。runner 0.1.0 + fixture v1 继续走逐字节兼容路径，L2 golden artifact SHA 不变；runner 0.2.0 + `synthetic-dl-fixture/v2` 才启用验证集、checkpoint 和 early stopping。`deep_learning.__all__` 仍只暴露 `DLRunManifest`。
2. **checkpoint payload 与审计 artifact 分离**：0.2 runner 返回的 canonical result 只记录 `checkpoint://` locator、content/ledger/optimizer SHA-256、source run、step/epoch 和 validation metric；bounded synthetic model payload 仅通过 `DLRunResult.checkpoint_payloads` 在内存中交给调用方。本实现不创建目录、不写 checkpoint、不声称 locator 已持久化；真实或大型 payload 仍禁止进入 Git。
3. **exact resume 逐面交叉绑定**：恢复同时验证 manifest 声明、checkpoint 全量 content hash、study/case/runner、training identity、模型形状、validation metric、optimizer state 和既有 consumption ledger。training identity 排除“本段目标 step”与合成故障注入，使同一训练问题可从较短目标继续到较长目标；累计 budget 以 prior ledger 为基准，只扣新增 segment，样本数保持唯一行计数。篡改、错 case/fixture、漏 payload、fresh 带 payload 均 fail-closed。
4. **early stopping 只看合成 validation partition**：fixture v2 显式分离 train/validation，0.2 只支持 `validation_loss/minimize`。patience、min-delta 和 warmup 均进入 canonical fixture；启用时 retention 必须为 `best_and_last` 或 `all`，result 同时记录 best 与 last，避免把停止时状态伪装成被选择状态。
5. **selection 是独立深模块**：`select_fixture_runs(results, selection_payload) -> DLSelectionResult` 是唯一 selector interface。计划必须预登记至少两个互异 `run_id/seed` 和最低成功数；missing、budget-exhausted、OOM/NaN/interruption 与其他失败都保留为逐 seed 记录。达到 minimum Gate 后才允许选择 checkpoint，同时报告成功 seed 的 mean、population variance 与 observed range；observed range 明确不是置信区间，best checkpoint 不代表稳定性。
6. **诚实能力包络**：0.2 仍只执行标准库 CPU tiny-MLP 和 synthetic validation；optimizer 只实现 deterministic synthetic SGD，scheduler 必须为 `none`。框架/GPU、真实数据、真实外部 artifact store、scheduler recovery、真实 OOM/preemption、ablation/scale/compute-matched 报告和硬件矩阵继续 fail-closed 或留给 L4。

L3 仍只构成 synthetic engineering evidence；它证明 checkpoint/恢复/选择协议机器的确定性工程行为，不证明真实训练框架、GPU 可复现性、数据验收、科研结论或生产恢复能力。

## 增补 A3（2026-08-23，L4）：失败 case、比较公平性与支持矩阵

L4 在 L3 canonical runner/selection artifacts 之上增加一个显式 study 子模块，
不修改 manifest schema、Core family、根 Adapter seam 或 L2/L3 artifact bytes。

1. **唯一 study interface**：`build_fixture_study_report(plan_payload, evidence_by_arm) -> DLStudyReport`。每个 arm 以 `DLStudyArmEvidence` 同时提供 selector artifact、它引用的 exact runner results、原 manifest 与 fixture；reporter 交叉绑定 selection/result、manifest/fixture hash、study/case、run/seed 与 runner pin，并从输入验证数据、learning rate、optimizer/scheduler、硬件/运行时/框架声明等冻结轴。它不训练、不打开 checkpoint payload、不探测硬件、不读时钟或文件系统。
2. **复现单位与失败保留**：expected seed 是比较单位；失败、缺失或不足最低成功数的任一 arm 进入 `incomplete_evidence`，所有失败记录进入 `failure_inventory`。selected checkpoint 不能替代 expected-seed 完整性，也不能建立稳定性。
3. **三类比较合同**：ablation 只允许 early-stopping policy 一个声明因素变化，并要求所有 consumed 维度与 caps 相等；scale 只允许 hidden units 变化、固定 steps/caps，结果始终是描述性 scale 记录；compute-matched 允许 hidden units 与用于配平的 steps 联动，但逐 seed 的 samples/tokens/FLOP proxy 和相关 caps 必须相同。资源不匹配返回可审计 verdict，不抛弃结果，也不允许直接比较。
4. **解释上限固定**：即使公平性 Gate 通过，也只有 `eligible_descriptive_comparison`；`capability_claim_allowed=false` 恒成立。population mean/variance/observed range 来自 L3 selector，observed range 不是置信区间，合成 metric 差异不是模型质量、因果或科研结论。
5. **公开 case 与 Case Package**：`benchmarks/public/dl-adapter/catalog.json` 固定 10 个合成场景，覆盖 OOM/NaN/interrupt 注入、failed seed、best-only selection、checkpoint tamper、ablation、scale、compute-matched 与 payload 隔离。集成测试通过既有 `capture_case` seam 为 OOM、NaN、interrupt、recovery rejection 与 compute-matched 构建 5 个可重建 `research-case-package/v2`；不新增 Pattern、Heuristic 或 Skill 晋级。
6. **artifact retention**：report 与 Case Package 只绑定 locator、SHA-256、lineage 和输出 manifest；模型/optimizer/checkpoint payload 不写入 Git。真实外部 store 的持久性、权限和恢复仍未观察。
7. **硬件矩阵诚实分层**：`DL_SUPPORT_MATRIX.json` 将标准库 synthetic CPU protocol、声明但未观察的硬件、未加载的框架与完全未执行的 CUDA/ROCm/MPS 分开。Windows/Ubuntu CI 只能证明对应 commit 的 Python 工程测试，不能证明 GPU 存在。跨 GPU reproducibility envelope 保持未验证。

L4 本地通过不等于 Phase 6 完成。只有 L4 exact commit 的真实 `git archive`
双解释器 Gate 与该提交的四项 CI 成功后，才形成平台工程验收；真实框架/GPU、
真实数据与外部 checkpoint store 证据仍需独立授权和新层级，`v0.7.0` Gate
继续关闭。

## 增补 A4（2026-08-24，R1）：真实 PyTorch/CUDA small-fixture 观测

R1 在不改变 L2/L3 合成 runner 字节和根 Adapter seam 的前提下，增加一个
显式、可选的 PyTorch/CUDA 观测子模块。它是单一真实实现的深模块，不预先抽象
通用 framework plug-in；只有出现第二个真实框架实现并通过同一 contract 后，
才重新评估稳定 seam。

1. **唯一 R1 执行入口**：`run_pytorch_gpu_fixture(manifest, fixture_payload) -> DLObservedRun`。调用方显式导入 `deep_learning.pytorch_observation`；`deep_learning.__all__` 仍只暴露 `DLRunManifest`。PyTorch 由调用方管理并在函数内部 lazy import，基础包依赖保持为空，不自动下载框架或 CUDA payload。
2. **配置与来源绑定先于执行**：runner 只接受 `gpu_fixture`、CUDA、PyTorch、strict determinism、host execution、fresh/no-checkpoint、SGD/empty-scheduler 和小型有界 fixture；manifest runner pin 必须等于当前模块文件的原始字节 SHA-256，case、learning rate、样本、step 与预算逐项互证。严格 CUDA 路径要求显式 `CUBLAS_WORKSPACE_CONFIG`。
3. **观测而不是声明**：运行前通过 PyTorch 读取框架版本、CUDA backend、device model/count/memory 和 compute capability，并与 manifest 的 OS、architecture、Python、框架和硬件声明逐项比较。模块不把 manifest 的可选 driver version 回填成观测；PyTorch 无可靠 driver probe，因此限制项明确记录“未由本模块复探”。
4. **正式结果合同**：`dl-run-observation/v1` 是 Adapter 层 schema，不是 Core family。记录绑定 manifest、case/study/run、runner source、fixture、观测时间、运行时、硬件、metrics、资源、预算 ledger、failure 与 limitations。成功记录必须恰有 initial/final/delta loss；合法执行阶段异常返回失败 observation，且只保留稳定的非敏感错误类别，不复制本机路径或原始异常正文。
5. **能力与失败上限**：fixture 最多 256 samples、128 input features、256 hidden units、32 outputs 和 10 steps，只在 `cuda:0` 执行。无框架、无 CUDA、声明与观测不一致或输入越界时 fail closed，不产生伪 observation；已绑定运行时后的 runtime/numerical/budget failure 必须保留。checkpoint、外部 store、恢复、分布式、mixed precision 和真实数据仍不执行。
6. **验收分层**：默认 Windows/Ubuntu × Python 3.12/3.14 CI 只验证 schema、接口、lazy import、失败保存和无 PyTorch 基础依赖；真实 CUDA 用例必须通过 opt-in 环境变量在已安装且版本受控的 PyTorch 环境执行，并绑定 exact archive commit/tree 与 runner source SHA。单主机单 GPU 成功只构成 real-framework/hardware engineering observation，不构成真实数据、科研、预测、生产、外部采用或跨 GPU 可复现证据。

R1 不打开 `gpu_training`、真实数据验收、driver/多 GPU 矩阵、外部 checkpoint
store、scheduler recovery 或 `v0.7.0` Tag/Release Gate。

## 增补 A5（2026-08-24，R5）：可移植 CUDA 试用回执与跨环境比较

R5 在 R3/R4 已验证的公开 interface 之上增加一个可离线运行、公开安全的
trial Module 和一个纯比较 Module。它准备不同环境的 exact-commit 回执，但在
外部回执真正到达前只标记 `TRIAL_READY / ZERO_EXTERNAL_RECEIPTS`。

1. **唯一 trial interface**：`run_pytorch_portability_trial(plan_payload, *, artifact_root) -> DLPortabilityTrialReceipt`。plan 只携带 clean commit/tree/archive SHA-256；三 seed、fixture、manifest、R3/R4 调用、环境探测和回执投影全部隐藏在 Module 内。PyTorch 继续由调用方管理并 lazy import，不安装框架、不上传数据。
2. **固定执行包络**：同一调用先执行 seeds 7/11/13、每 seed 两个 fresh process 的 R3 Gate，再执行 checkpoint 确认后 exact-owned-child 受控终止的 R4 Gate。任一 seed、身份、恢复或累计预算 Gate 失败都不签发 completed receipt。
3. **artifact seam**：`artifact_root` 必须是仓库外、已存在且为空的调用方目录。checkpoint payload 只留在该目录；正式 receipt 仅保留 locator-free 状态哈希、执行环境、commit/tree/archive、runner identity 和限制项。
4. **公开安全合同**：`dl-portability-trial-receipt/v1` 拒绝本机绝对路径、常见凭据形态和邮箱；不包含用户名、主机名、GPU UUID/MAC/序列号、环境变量全集或原始异常。privacy flags 不能覆盖字符串级扫描结果。
5. **唯一 comparison interface**：`build_cross_environment_report(receipts, comparison_policy) -> DLCrossEnvironmentReport`。它要求至少两份非重复、同 commit/tree/archive/plan 的 receipt，按环境事实和预注册 seed 比较 exact state hashes 与 final-loss delta；同环境多回执只能得到 `single_environment_only`。
6. **不推断身份或采用**：`dl-cross-environment-reproducibility-report/v1` 将 independent hosts、independent participants、external adoption 和 production reliability 四项固定为 false。环境元数据不同只表示观察到不同配置，参与者独立性与公开同意仍由 O5 单独验收。
7. **脚本边界**：`verify_dl_portability_trial.py` 和 `compare_dl_portability_receipts.py` 仅在本地运行，可选择把 canonical JSON 写到显式仓库外新路径；不访问网络、不邀请参与者、不代提交、不安装 PyTorch/Skill。
8. **seam 延期**：R5 不引入 `CheckpointStore` port。当前仍只有 caller-managed local directory；只有真实远端 store 被选择并形成第二个 Adapter 后，才重新评估该 seam。

R5 本机 CUDA Gate 仍只证明单一记录环境的 bounded synthetic engineering
behavior。没有合格外部 receipt 时，不支持跨 host/GPU/driver、外部采用或 O5
完成结论；真实数据、外部 checkpoint store、scheduler-managed involuntary
preemption、分布式/混合精度、生产和 `v0.7.0` Tag/Release Gate 继续关闭。
