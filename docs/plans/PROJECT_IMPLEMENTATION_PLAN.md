# 通用科研 Agent Heuristic Learning 与 Evaluator 详细实施计划

- 计划版本：v3.0-bootstrap
- 日期：2026-08-13
- 仓库：`westwhile/heuristic-research-agent-skill`
- 本地工作树：`$PROJECT_ROOT`（由操作者在本机配置，不写入公开绝对路径）
- 当前状态：计划与仓库骨架初始化；尚无功能性发布

## 1. 最终目标与非目标

### 1.1 最终目标

建设一套可跨数学、量化、机器学习和深度学习复用的科研 Agent 平台，完成：

1. 研究任务、Claim、Evidence、Run 和 Failure 的版本化留档；
2. 从真实失败中形成可追踪的分析、case 和 Heuristic candidate；
3. 使用公开、私有和滚动 holdout Evaluator 比较 Champion/Challenger；
4. 通过 hard gates、人工审批、canary 和 rollback 受控晋级；
5. 将已晋级 Heuristic 作为不可变、hash-bound snapshot 提供给新运行；
6. 明确区分工程成功、数据验收、科研支持和生产观察。

### 1.2 非目标

首个版本不承诺：

- 自动发现并证明所有数学定理；
- 自动产生可实盘交易策略；
- 自动训练任意规模深度学习模型；
- 一个总分能够比较所有学科；
- Candidate 自动修改、自动上线或自动扩大预算/权限；
- 公共仓库保存私有语料、市场原始数据或 hidden benchmark；
- 用 LLM judge 替代可靠 oracle、实验设计或人工科研判断。

## 2. 成功指标

平台级指标分开报告，不合成唯一总分：

| 维度 | 核心指标 |
|---|---|
| 完整性 | manifest 覆盖率、hash/lineage 验证率、不可变记录违规数 |
| 正确性 | critical false claim、verifier false pass、case accuracy by family |
| 校准 | completion precision、correct abstention、coverage-risk 曲线 |
| 稳健性 | metamorphic consistency、重复运行方差、边界扰动稳定性 |
| 效率 | 工具调用、运行时间、token/cost proxy、验证进展轮数 |
| 可维护性 | Heuristic 数量、冲突、重复、dead rules、schema 兼容性 |
| 治理 | hidden 泄漏、权限扩张、未授权晋级、可回滚率 |

## 3. 阶段与版本总览

工期是单人/小团队估计；case、oracle、GPU 和人工复核可能使工期显著增加。

| Phase | 目标 | 预计 | 目标版本/Tag |
|---|---|---:|---|
| 0 | 仓库与治理基线 | 3—5 天 | `v0.1.0` |
| 1 | 通用记录与证据内核 | 1—2 周 | `v0.2.0` |
| 2 | Math + Quant 双领域垂直切片 | 2—3 周 | `v0.3.0` |
| 3 | Public Evaluator MVP | 2—3 周 | `v0.4.0` |
| 4 | Experience 与 Heuristic Registry | 2—3 周 | `v0.5.0` |
| 5 | Machine Learning Adapter | 2—3 周 | `v0.6.0` |
| 6 | Deep Learning 扩展 | 2—4 周 | `v0.7.0` |
| 7 | Candidate Builder 与公开进化循环 | 2—3 周 | `v0.8.0` |
| 8 | Private/Hidden Evaluator 与 Promotion 演练 | 3—5 周 | `v0.9.0` |
| 9 | 生产快照、Canary、Rollback 与 v1 | 2—4 周 | `v1.0.0` |

总计：约 18—30 周；其中 Phase 0—4 构成可用的 evaluator-first 研究 MVP。

---

## Phase 0：仓库初始化、Baseline Freeze 与治理边界

### 目标

建立可审计的源码仓库，冻结当前数学 Skill 作为外部 baseline，并在任何功能开发前固定权限、结论、发布和隐私规则。

### 输入

- 空的 GitHub 仓库；
- 空的本地目标目录；
- `math-research-solve-portable-1.0.0.zip`；
- 当前安装的 `math-research-solve`；
- HL/Evaluator v2.0 审核方案；
- 本计划和仓库级 `AGENTS.md`。

### 实施任务

1. 初始化 `main`，配置只读核对后的 `origin`；
2. 写入 README、AGENTS、pyproject、目录契约、PR/Issue 模板；
3. 记录远程仓库、Python、PowerShell、Git 和 OS 环境；
4. 为 portable ZIP 生成文件清单、package SHA-256 和 payload tree hash；
5. 比较 portable payload 与当前安装副本，记录 missing/extra/mismatch；
6. 在 Windows 补跑全部 Python 与 PowerShell regression；
7. 将测试区分为 passed、failed、skipped、not-run；
8. 定义 Candidate/Evaluator/Promotion/Hidden 权限矩阵；
9. 定义私有数据、hidden case、checkpoint、凭据的 Git 排除规则；
10. 建立版本、分支、commit、PR、push、annotated tag 和 Release 流程；
11. 选择许可证；在选择前保持 all rights reserved，不擅自假定开源许可；
12. 建立 ADR 机制并接受 ADR-0001。

### 交付物

- `docs/plans/PROJECT_IMPLEMENTATION_PLAN.md`；
- `docs/architecture/ARCHITECTURE.md`；
- `docs/governance/*`；
- `baselines/math-research-solve-1.0.0/manifest.json`（后续创建，不复制私有运行）；
- `reports/baseline/math-research-solve-1.0.0.md`；
- 权限矩阵、环境清单和回归结果；
- 首个可复现的 repository bootstrap。

### 验收 Gate

实施状态（2026-08-13）：1.0.0 冻结证据保持不变；修复候选以 1.0.1 重新打包并部署。portable、candidate 和安装树 79 文件一致，Windows 回归为 19 passed、0 failed、0 blocked、0 timeout、1 not-run。唯一 not-run 需要真实 600+ 工件 legacy archive，本机约定根及全盘候选搜索未发现该夹具；因此 v0.1.0 不声明 legacy successor 端到端能力，该用例作为能力启用前的延期 Gate，而不是以合成数据补齐。

- 本地与远程身份无歧义；
- `git status` 只包含预期 bootstrap 文件；
- 无凭据、绝对用户路径、私有 case 或原始数据；
- baseline 包和安装树逐文件差异已报告；
- 全量回归有机器可读结果；任何跳过项明确记录；
- README 不声称未实现能力；
- Release policy 已包含 commit、push 和 tag 的明确审批点。

### 停止条件

- baseline 文件不一致且无法解释；
- 测试写入生产/安装目录；
- 远程非空或本地存在未识别文件；
- 许可证、私有数据或发布权限存在实质歧义。

### Git/发布 Gate

- 分支：`bootstrap/repository-foundation` 或首次空仓库直接 `main`；
- 建议提交：`chore(repo): initialize research evolution project`；
- 用户审核 diff 和测试后才 push；
- push 后核对远端 commit SHA；
- Phase 0 全部验收后创建 annotated tag `v0.1.0`；
- Tag push 与 GitHub Release 单独执行并核对 SHA；
- Tag 不触发 Skill 安装或 Champion promotion。

---

## Phase 1：通用记录、Schema 与证据内核

### 目标

建立不包含领域词汇的通用 Core，使事实、分析、Claim、Evidence 和 Run 能被严格校验、版本化和追踪。

### 实施任务

1. 定义并评审：
   - `research-task/v1`；
   - `research-claim/v1`；
   - `research-evidence/v1`；
   - `research-run/v1`；
   - `failure-observation/v1`；
   - `failure-analysis/v1`；
   - `experience-packet/v1`；
2. 实现 UTF-8 严格 JSON 读取与 duplicate-key 拒绝；
3. 实现 canonical serialization 和 SHA-256 pointer；
4. 实现 safe relative path，拒绝盘符、UNC、`..` 和逃逸；
5. 实现 create-new/append-only 发布；
6. 实现 `supersedes` 和 lineage graph 校验；
7. 实现 manifest 创建与全图验证；
8. 实现隐私分类、绝对路径检测和 redaction interface；
9. 建立已知正确/错误 fixtures；
10. 对 schema 进行 backward/forward compatibility contract tests；
11. 输出命令行：`validate`、`hash`、`verify-graph`，但不执行外部写入。

### 交付物

- Core schemas 和 Python module；
- schema fixtures；
- unit/contract tests；
- `core-interface.md`；
- migration/compatibility policy；
- machine-readable validation report。

### 验收 Gate

- duplicate key、路径逃逸、hash mismatch、循环 lineage 全部 fail closed；
- Observation 不能被 Analysis 覆盖；
- 同一输入得到稳定 canonical hash；
- Windows 路径/编码 tests 通过；
- 核心 interface 不出现 proof、factor、model architecture 等领域字段；
- 代码覆盖关键失败分支，而不仅是 happy path。

### Git/发布 Gate

- 分支：`feat/core-records-v1`；
- 提交按 schema、implementation、tests、docs 分层；
- push 后开 draft PR，所有 contract tests 通过再 ready；
- 合并后生成 candidate manifest；
- annotated tag：`v0.2.0`；Release notes 列出 schema compatibility 和已知限制。

---

## Phase 2：Math + Quant 双领域垂直切片

### 目标

使用两个差异显著的真实 Adapter 验证 Core seam；不允许只实现 Math 后宣称平台通用。

### Math 任务

1. 只读导入 `math-research-solve` 的 Attempt/Failure/Evidence/Audit；
2. 将 proof/disproof/partial/inconclusive 映射为 Claim；
3. 映射量词、对象域、假设、failed step、non-entailment 和 reopen condition；
4. 实现 scope expansion、theorem precondition、false completion 三类 evaluator contract；
5. 准备 3—5 个脱敏历史案例；
6. importer 保证旧项目零写入并绑定源 hash。

### Quant 任务

1. 定义研究数据、因子、模型、回测和策略 Claim 的映射；
2. 实现数据 schema/PIT/coverage audit contract；
3. 实现 signal/execution/label 时间对齐检查；
4. 实现成本、停牌、涨跌停、流动性和基准口径检查；
5. 区分 engineering、data acceptance、OOS empirical 和 real-market Claim；
6. 准备 3—5 个脱敏或合成的已知泄漏/已知正确案例；
7. 禁止用现有真实项目的私有数据直接进入公开 benchmark。

### 共用任务

1. 使用同一个 Adapter interface 完成两条端到端链路；
2. 记录为了适配第二领域而修改 interface 的所有理由；
3. 建立 Adapter contract tests；
4. 形成 `DomainTask`、`ClaimAssessment` 和 `EvaluationContract` 的冻结 v1；
5. 验证删除 Adapter 后领域复杂度不会泄漏回 Core。

### 交付物

- Math/Quant Adapter v1；
- 两条垂直切片报告；
- 共 6—10 个公开/合成 cases；
- importer 的零写入证据；
- ADR-0002：Adapter interface v1。

### 验收 Gate

- 两个 Adapter 同时通过相同 contract suite；
- Core 无领域专用条件分支；
- Math 数值证据不能晋级全局 proof；
- Quant synthetic/sample 输出不能晋级真实研究；
- 旧数学 archive 和真实量化数据均未被修改或公开；
- 每个 case 有 evaluation contract、lineage 和 privacy 状态。

### Git/发布 Gate

- 分支：`feat/math-quant-vertical-slices`；
- Math 与 Quant 可分 PR，但 Adapter interface 冻结必须在整合 PR 完成；
- push 前运行全部 Core 和双 Adapter tests；
- annotated tag：`v0.3.0`；
- Release 标为 research preview，不宣称 Evaluator 已完整实现。

---

## Phase 3：Public Evaluator MVP

### 目标

实现 L0 协议评测和 L1 artifact replay，形成可重复的 Champion/Challenger 公开比较；暂不把离线 runner 说成完整 Agent 评测。

### 实施任务

1. 定义 `evaluation-case/v1`、`suite/v1`、`evaluation-run/v1` 和 `comparison-report/v1`；
2. 建立 Benchmark Registry、suite snapshot 和 contamination ledger；
3. 支持 oracle、deterministic checker、structured rubric 和 calibrated judge 的明确等级；
4. 建立 smoke、development、regression、metamorphic-public 和 adversarial-public split；
5. 实现 candidate/suite/envelope 冻结；
6. 实现 runner 超时、输出大小、错误分类和 retry policy；
7. 实现 hard gates：完整性、critical safety、回归、资源、隐私和 evaluator integrity；
8. 实现 score vector，不生成跨领域唯一总分；
9. 实现 paired exact/McNemar、paired bootstrap、rare-event 上界；
10. 实现 known-good、known-bad 和 evaluator mutation meta-tests；
11. 生成 HTML/Markdown/JSON 三种一致报告；
12. 每份报告标注 L0/L1 覆盖范围。

### 首批规模

- Math：10—15 cases；
- Quant：10—15 cases；
- golden successes：每领域至少 3 个；
- metamorphic：每领域至少 3 组；
- known-bad evaluator mutations：至少 6 个。

### 验收 Gate

- known-good/known-bad 稳定区分；
- mutation tests 能发现反转 PASS/FAIL、移除条件、放宽资源等故障；
- Candidate 不能修改 case、scorer 或 report；
- 相同 seed/config 产生可解释的重现结果；
- 不以 20—30 cases 的小样本总准确率声称统计显著提升；
- 报告绑定全部必要 hash。

### Git/发布 Gate

- 分支：`feat/public-evaluator-mvp`；
- runner、scorer、statistics 和 meta-tests 分提交；
- PR 必须附一份可公开 evaluation report；
- annotated tag：`v0.4.0`；
- Release 明确仅覆盖 L0/L1。

---

## Phase 4：Experience Intelligence 与 Heuristic Registry

### 目标

把失败记录转为可复核的经验候选，而不是让单次 LLM 总结直接修改生产规则。

### 实施任务

1. 建立通用一级 taxonomy 与 Math/Quant 二级 taxonomy；
2. 实现 observation、analysis、cluster 和 counterfactual test registry；
3. exact fingerprint → 结构字段 → taxonomy → 语义 proposal 分层聚类；
4. cluster merge/split 使用 append-only event；
5. 定义 Heuristic schema、scope、mode、evidence、exception、risk 和 rollback；
6. 生命周期：lesson hypothesis → candidate → shadow → validated → promoted/deprecated/retired/rejected；
7. 实现 duplicate、conflict、precedence cycle、dead/always-triggered rule linter；
8. 实现 case eligibility gate；
9. 每个 Heuristic candidate 强制关联 regression case；
10. 实现 complexity budget 和 compression review；
11. 只允许确定性全局不变量成为 global hard gate；
12. 运行 3—8 条 shadow Heuristic，不接入生产。

### 验收 Gate

- 单例失败不能自动生成 global rule；
- root cause 在无反事实证据时保持 hypothesis；
- Observation 历史不因分析更新而变化；
- 冲突、循环和无回滚的 blocking rule 被拒绝；
- shadow 只记录决策，不改变生产行为；
- 公开 suite 无 critical regression。

### Git/发布 Gate

- 分支：`feat/experience-heuristic-registry`；
- taxonomy、registry、linter、shadow runner 分提交；
- PR 中列出每条规则的 evidence 和 regression case；
- annotated tag：`v0.5.0`；
- 不创建 production Champion。

---

## Phase 5：Machine Learning Adapter

### 目标

让平台支持监督/无监督/时间序列 ML 研究的可重复实验与泛化 Claim，同时验证 Adapter interface 不依赖数学或量化特例。

### 实施任务

1. 定义 dataset、split、preprocessing、feature、model、metric 和 selection record；
2. 实现 IID、group、time-series 和 nested validation contract；
3. 检查预处理、特征选择、采样和 target encoding 泄漏；
4. 检查 validation/test/future holdout 的用途；
5. 实现 baseline parity 和 resource parity；
6. 记录随机种子与重复实验；
7. 支持 calibration、subgroup、OOD 和 drift assessment；
8. 明确模型选择和最终报告的分离；
9. 构建 15—25 个公开/合成 cases；
10. 建立至少一个非时间序列和一个时间序列垂直切片；
11. 比较 ML Adapter 与 Quant Adapter 的重合逻辑，公共部分下沉 Core，领域部分保留 Adapter；
12. 增加 ML Heuristic shadow cases。

### 验收 Gate

- test/holdout 不参与调参；
- split 和 preprocessing lineage 可重现；
- 单 seed 最佳值不能支撑稳定 Claim；
- 模型/资源变更与 Heuristic 变更分层；
- OOD/subgroup 缺失时报告限制，不补造结论；
- 原有 Math/Quant tests 零 critical regression。

### Git/发布 Gate

- 分支：`feat/ml-adapter`；
- 数据合同、泄漏检查、runner、cases 分提交；
- PR 附重复实验和 leakage fixture 报告；
- annotated tag：`v0.6.0`。

---

## Phase 6：Deep Learning 扩展

### 目标

在 ML Adapter 上增加 DL 的算力、训练状态和 checkpoint 治理；不复制一套平行 Core。

### 实施任务

1. 定义 hardware/runtime/container/framework/CUDA manifest；
2. 定义 training budget：数据量、step、epoch、token、FLOP/cost proxy；
3. 记录 checkpoint lineage、optimizer/scheduler 和恢复点；
4. 建立 early stopping 与 checkpoint selection protocol；
5. 记录 OOM、NaN、preemption 和 failed seeds；
6. 支持多 seed、均值/方差/区间而非 best-only；
7. 支持 ablation、scale study 和 compute-matched baseline；
8. runner 支持 dry-run/small fixture；真实 GPU 运行独立标记；
9. 加入 checkpoint 污染、挑选偏差和算力不公平 cases；
10. 设计 artifact retention，Git 不保存大型模型文件；
11. 评估 reproducibility envelope 在不同 GPU 上的限制；
12. 发布 DL Adapter 已验证的硬件/框架矩阵。

### 验收 Gate

- CPU/small fixture success 不等于 GPU full training success；
- 失败 seed 和训练中断纳入报告；
- best checkpoint 不代表总体稳定性；
- compute/resource 不一致时不直接比较能力；
- checkpoint 仅通过 locator/hash 引用，不进入 Git；
- 恢复测试不会重复计费或覆盖权威 artifact。

### Git/发布 Gate

- 分支：`feat/deep-learning-adapter`；
- manifest、runner、selection、cases 分提交；
- PR 明确实际运行与未运行的硬件；
- annotated tag：`v0.7.0`。

---

## Phase 7：Candidate Builder 与公开受控进化循环

### 目标

自动生成可审计 Candidate，但保持 Candidate 无生产写权限、无 hidden 权限、无自晋级权限。

### 实施任务

1. 定义 immutable candidate manifest；
2. bundle 包含 baseline hash、patch、Heuristic snapshot、tests、风险和 rollback；
3. Candidate 生成只读公开 experience/cases；
4. patch 与 regression case 原子生成；
5. 静态验证、公开 regression、公开 dev A/B；
6. 固定模型、reasoning、工具和预算；
7. 限制迭代次数、并发、输出和成本；
8. 防止 Candidate 修改 evaluator、报告或 baseline；
9. 生成 comparison report 和拒绝原因；
10. 实现 candidate archive 和去重；
11. 建立 Heuristic compression review；
12. 自动化等级最多到 E2：自动 candidate + public suite，人工决定后续。

### 验收 Gate

- bundle 可由 manifest 重现；
- 每个 patch 有目标 failure class 和 regression case；
- Candidate 没有 evaluator/private/production 写权限；
- 资源扩大不能伪装为能力提升；
- public 改善但 critical regression 时自动拒绝；
- 不执行自动 push/tag/promotion。

### Git/发布 Gate

- 分支：`feat/candidate-builder`；
- PR 附至少一个接受和一个拒绝 Candidate 的完整证据；
- annotated tag：`v0.8.0`；
- Candidate bundle 自身版本与仓库 Release 分开。

---

## Phase 8：Private/Hidden Evaluator 与 Promotion 演练

### 目标

建立真正的独立权限域、aggregate-only 输出和人工 Promotion Gate；完成泄漏与回滚故障演练。

### 实施任务

1. 建立独立 private repo/CI/账户或等价 ACL；
2. Evolution Agent 不能列出、读取或网络获取 hidden cases；
3. Private runner 只接收 immutable bundle；
4. 禁止自由 shell/网络，限制输出 channel、大小和格式；
5. 扫描 prompt、trace、错误消息和 artifact 的泄漏；
6. 实现 private validation、hidden 和 rolling future holdout；
7. hidden 公开后降级为 regression 并补充新 holdout；
8. report 绑定 candidate、suite、runner、environment 和 policy hash；
9. 建立 manual PromotionDecision；
10. 故障注入：hidden read、report tamper、resource cap change、judge reversal；
11. 演练 reject、canary plan 和 rollback plan；
12. 记录最小化的公开 Release evidence，不泄漏 hidden 内容。

### 验收 Gate

- 以 OS/CI/ACL 证据证明隔离，不以目录名证明；
- Evolution 环境无法获取 hidden 原文；
- 输出泄漏测试通过；
- meta-tests 检测全部故障注入；
- 任一 hard gate 失败不能晋级；
- Promotion 仍要求人工批准；
- 回滚演练恢复 baseline hash 且不修改历史报告。

### Git/发布 Gate

- 公共仓库分支：`feat/private-evaluator-interface`；
- private 实现单独提交到受限仓库；
- 公共 PR 只包含 interface、fake 和脱敏验收证明；
- annotated tag：`v0.9.0`；
- private suite 不打入公共 Release artifact。

---

## Phase 9：生产快照、Canary、Rollback 与 v1.0

### 目标

把经批准的 Heuristic snapshot 安全提供给新研究 run，完成低风险 canary 和可恢复的正式版本。

### 实施任务

1. 定义 promoted snapshot、promotion manifest 和 activation receipt；
2. snapshot 在 run 创建时复制为 immutable input 并 hash-bound；
3. 已运行任务不动态读取 Registry；
4. 为 Math、Quant、ML/DL executor 分别定义接入协议；
5. 当前 `math-research-solve` v8 保持只读；新接入使用显式 successor/protocol version；
6. 第一批只 canary advisory/verifier checks，不自动 hard-block 高不确定规则；
7. 观察 false block、false completion、成本和人工接管；
8. 实现 one-step rollback，并验证新增文件 hash 后再移除；
9. 冻结 `v1` schema、Adapter compatibility 和 support matrix；
10. 完成安全、隐私、统计、文档和恢复审计；
11. 准备 changelog、migration、release notes 和 artifact manifest；
12. 用户批准后提交、push、tag、Release；Skill 安装和 Champion activation 再单独批准。

### v1.0 Definition of Done

- 四领域 Adapter 均有 contract tests 和公开验证边界；
- L0/L1 稳定，至少一类任务完成 L2；
- private/hidden 物理隔离与输出泄漏防护通过；
- promoted Heuristic 有 evidence、scope、case、risk、exception 和 rollback；
- Candidate 无 hidden/evaluator/production 写权限；
- Champion/Challenger 使用相同资源 envelope；
- canary 与 rollback 至少真实演练一次；
- Release artifact、Git tag、commit 和 manifest hash 一致；
- Tag、Release、Skill 安装和 Champion promotion 有四份独立 receipt；
- 文档没有把工程、合成、样本外或 canary 结果夸大为更强 Claim。

### Git/发布 Gate

- release branch：`release/v1.0.0`；
- 只允许版本、changelog、manifest 和 release fixes；
- PR 合并到 `main` 后重新跑 clean-room tests；
- 创建 annotated tag `v1.0.0`，签名能力可用时使用 signed tag；
- push 精确 tag，核对远端 SHA；
- 创建 GitHub Release，上传 checksums/manifest；
- 任一核对失败停止发布，不移动 Tag，以新 patch version 修复。

---

## 4. 横向工作流

### 4.1 每个 Phase 的固定节奏

```text
Issue/Contract
→ Branch
→ Small commits
→ Local validation
→ Push
→ Draft PR
→ Review + CI
→ Merge
→ Clean checkout acceptance
→ Annotated Tag
→ Tag push
→ GitHub Release
→ 可选部署/Promotion（独立批准）
```

### 4.2 文档与 ADR

- interface、schema、权限、评测统计和发布语义改变必须写 ADR；
- 阶段完成时更新计划状态而不改写历史验收报告；
- 失败的 Candidate 和 rejected Decision 保留，可归档不可伪装为未发生。

### 4.3 Case 治理

- case 进入 registry 前经过 reproducibility、oracle/evaluation contract、privacy、copyright 和 contamination Gate；
- 已暴露给 Evolution 的 case 永不再是 hidden；
- case 修改产生新 version，旧 report 仍引用旧 hash；
- 合成 case 明确标识，不冒充真实历史失败。

### 4.4 统计预注册

- 每次版本比较在运行前冻结 primary endpoint、non-inferiority margin、重复次数和预算；
- rare critical failure 使用零容忍 hard gate 和单侧上界；
- 多领域按层报告，不用 Simpson's paradox 式总分遮蔽退化；
- 模型版本变化与 Heuristic 变化使用分层实验。

## 5. 风险登记

| 风险 | 影响 | 主要控制 |
|---|---|---|
| Core 被数学语义绑死 | 无法支持实证研究 | Math+Quant 双 Adapter 才冻结 seam |
| LLM 根因幻觉 | 错误规则扩散 | Observation/Analysis 分离、反事实和人工复核 |
| 未来函数/数据泄漏 | 虚假量化/ML 结果 | PIT、split、lineage 和 negative fixtures |
| Benchmark overfitting | public 提高、真实退化 | private、hidden、future holdout、rotation |
| Hidden 泄漏 | Evaluator 失效 | 物理隔离、无网络、输出约束和扫描 |
| 拒答刷安全 | 能力归零 | coverage-risk 和 correct abstention |
| 资源扩张刷分 | 无法归因 | 固定 envelope 和 Pareto comparison |
| Heuristic bloat | 维护性下降 | conflict linter、complexity budget、compression review |
| DL 成本/随机性 | 无法复现 | compute manifest、多 seed、small fixture 与 full run 分离 |
| 错误自动上线 | 生产退化 | 人工 Promotion、canary、rollback、独立 receipts |
| Git/Tag 漂移 | 发布不可追踪 | annotated immutable tags、SHA 校验、无 force push |
| 私有科研泄漏 | 隐私/版权损失 | explicit exporter、Git ignore、secret/path scan |

## 6. 首个执行批次建议

完成当前仓库初始化后，只启动以下批次：

1. Phase 0 baseline manifest 与 Windows 全量回归；
2. Phase 1 的三个最小 schema：Task、Claim、Evidence；
3. 一个 Math failure 与一个 Quant leakage case 的设计草案；
4. 在双垂直切片证明 seam 前，不开发自动 Candidate 或 Hidden 服务。

该收缩能尽早验证平台是否真正跨领域，而不是先积累大量尚未被实际使用的 schema。
