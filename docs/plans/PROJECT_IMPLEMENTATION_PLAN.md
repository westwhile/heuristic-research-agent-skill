# 通用科研 Agent Heuristic Learning 与 Evaluator 详细实施计划

- 计划版本：v5.8-o5-trial-launch
- 初次制定日期：2026-08-18
- 状态同步日期：2026-08-23
- 仓库：`westwhile/heuristic-research-agent-skill`
- 本地工作树：`$PROJECT_ROOT`（由操作者在本机配置，不写入公开绝对路径）
- 当前状态：Phase 0—5 已逐层验收发布（`v0.1.0`/`v0.2.0`/`v0.3.0`/`v0.4.0`/`v0.5.0`；`v0.5.1` 为归档缺件 hotfix；Phase 5 为 `v0.6.0`）。Phase 5（ML Adapter）L1–L6 的发布提交为 `c72e31eb4d5dbd367b20f24678e94682b963fed9`。OSS-R0 PR-A—PR-D 已由 PR #14—#17 合入；release-prep PR #18 的 merge commit `5af73595f847702930e0c1966986f3d06d3c1c35` 通过 main CI run `32619619333` 四项 required jobs、Windows governance、双解释器 archive suite 与 archive install Gate。annotated `v0.6.1` Tag object `2cdb9621d05211c779f933836adae476241206c0` 已指向该提交，正式 GitHub Release 的六项 assets 已回下载并通过 SHA-256 对账。O5 外部试用入口进入启动阶段，但尚无外部结果；O6 申请证据包和提交未启动。Phase 6 尚未启动；仍无真实 ML/DL 执行器、真实数据验收、完整 nested-CV 训练、自动晋级闭环、可安装 Skill 或生产发布能力。

### 规划补充（仅计划，不代表已实施）

- [Codex for Open Source 资格申请完整计划](CODEX_FOR_OSS_APPLICATION_PLAN.md)：O1—O4 与 `v0.6.1` source Release Gate 已完成；当前启动 O5 外部 Quick Start 试用，仍按 O5—O6 分离真实采用和申请证据；
- [math-research-solve v13 来源边界与延期说明](MATH_RESEARCH_SOLVE_V13_CROSS_DOMAIN_ADOPTION_PLAN.md)：外部 artifact 本轮不可得且许可未确认，详细表达已排除；v8/1.0.1 不可变，v13 不复制、不安装、不覆盖；
- 补充计划不授权 schema、研究状态机、外部申请或 v13 实施；OSS readiness 变更仍按独立 PR 和证据 Gate 执行。

## 1. 最终目标与非目标

### 1.1 最终目标

建设一套可跨数学、量化、机器学习和深度学习复用的科研 Agent 平台，完成：

1. 研究任务、Claim、Evidence、Run 和 Failure 的版本化留档；
2. 从真实成功、失败和重大项目问题中形成可追踪的 Research Case Package；
3. 从多个案例中蒸馏有适用范围、反例和证据的 Research Pattern，并在困难问题开始前检索为启发；
4. 将满足复用与评测门槛的 Pattern 孵化为候选子 Skill，独立验证后保存到中央库；
5. 使用公开、私有和滚动 holdout Evaluator 比较 Champion/Challenger；
6. 通过 hard gates、人工审批、canary 和 rollback 受控晋级；
7. 将已晋级 Heuristic 作为不可变、hash-bound snapshot 提供给新运行；
8. 明确区分工程成功、数据验收、科研支持、模式启发和生产观察。

### 1.2 非目标

首个版本不承诺：

- 自动发现并证明所有数学定理；
- 自动产生可实盘交易策略；
- 自动训练任意规模深度学习模型；
- 一个总分能够比较所有学科；
- Candidate 自动修改、自动上线或自动扩大预算/权限；
- 把一次项目复盘、聊天总结或未经复核的中间产物自动转成 Skill；
- 检索到旧模式后自动套用、自动安装或自动进入 Default/Preset；
- 公共仓库保存私有语料、市场原始数据或 hidden benchmark；
- 用 LLM judge 替代可靠 oracle、实验设计或人工科研判断；
- 把历史 Pattern、Skill 或相似案例当作当前科研结论的证据。

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
| 研究记忆质量 | Case Package 完整率、Pattern provenance、独立复用成功率、负迁移率、过期率 |
| 检索质量 | relevant@k、适用条件命中率、禁用条件漏报率、无结果时正确 abstain |
| Skill 孵化 | 候选静态通过率、fresh-session 前向通过率、触发冲突率、退役/替代可追踪率 |
| 治理 | hidden 泄漏、权限扩张、未授权晋级、可回滚率 |

## 3. 阶段与版本总览

工期是单人/小团队估计；case、oracle、GPU 和人工复核可能使工期显著增加。

| Phase | 目标 | 预计 | 目标版本/Tag |
|---|---|---:|---|
| 0 | 仓库与治理基线 | 3—5 天 | `v0.1.0` |
| 1 | 通用记录与证据内核 | 1—2 周 | `v0.2.0` |
| 2 | Math + Quant 双领域垂直切片 | 2—3 周 | `v0.3.0` |
| 3 | Public Evaluator MVP | 2—3 周 | `v0.4.0` |
| 4 | Research Memory、Pattern Library 与 Heuristic Registry | 3—4 周 | `v0.5.0` |
| 5 | Machine Learning Adapter | 2—3 周 | `v0.6.0` |
| 6 | Deep Learning 扩展 | 2—4 周 | `v0.7.0` |
| 7 | Skill Incubator、Candidate Builder 与公开进化循环 | 3—4 周 | `v0.8.0` |
| 8 | Private/Hidden Evaluator 与 Promotion 演练 | 3—5 周 | `v0.9.0` |
| 9 | 生产快照、Canary、Rollback 与 v1 | 2—4 周 | `v1.0.0` |

总计：约 20—34 周；其中 Phase 0—4 构成可用的 evaluator-first 研究记忆 MVP。Phase 4 只允许产生可检索 Pattern 和 shadow Heuristic；正式子 Skill 的生成、安装与激活仍需 Phase 7—9 的独立 Gate。

### 3.1 五类对象与五个独立动作

为防止“保存经验”“生成 Skill”“安装 Skill”和“模型能力提升”被混为一谈，系统固定区分：

| 层级 | 对象 | 用途 | 能否被运行时自动发现 |
|---|---|---|---|
| L1 | Research Case Package | 保存一个项目问题的冻结输入、中间产物、决策、成功/失败与证据 | 否 |
| L2 | Research Pattern | 跨案例蒸馏的策略、适用条件、禁用条件、反例和证据 | 否 |
| L3 | Staged Skill Candidate | 面向明确触发场景的最小 Skill payload 与测试包 | 否 |
| L4 | Canonical Skill | 中央库中已审核、可版本化的权威 Skill | 仅被发布工具读取，不等于已安装 |
| L5 | Installed/Activated Skill | 进入受控安装根并通过 fresh-session 验收的运行时能力 | 是，但仍不等于 Champion |

以下五个动作必须分别产生 decision/receipt，任何一个都不能隐含下一个：

```text
Pattern promotion
→ Canonical Skill publication
→ Git commit / push / annotated tag / Release
→ Skill installation
→ Default/Preset 或 Champion activation
```

中央库的逻辑布局使用可配置 `$SKILL_LIBRARY_ROOT`，不得把本机绝对路径写入公共 schema：

```text
$SKILL_LIBRARY_ROOT/
├── skills/                         # 仅正式、可安装的 canonical Skill
├── research-patterns/
│   ├── math/
│   ├── quant/
│   ├── ml/
│   ├── dl/
│   └── project-engineering/
├── skill-incubator/
│   ├── candidates/
│   ├── evaluations/
│   ├── rejected/
│   └── archived/
└── catalogs/                       # pattern/skill 索引与兼容元数据
```

`research-patterns/` 和 `skill-incubator/` 必须位于自动发现的 `skills/` 之外；否则草稿或历史经验可能被运行时误加载。

该目录正式命名为 **Research Pattern Library（研究模式库）**，不命名为“特征库”，以避免和量化/机器学习中的 feature store、feature registry 混淆。

### 3.2 关键路径与依赖 Gate

| 阶段 | 必须依赖 | 阶段结束时最高允许状态 |
|---|---|---|
| Phase 0 | 无 | repository/governance baseline tag |
| Phase 1 | Phase 0 | 可验证的通用记录与 Case envelope |
| Phase 2 | Phase 1 | Math/Quant Adapter contract |
| Phase 3 | Phase 2 | L0/L1 public evaluation |
| Phase 4 | Phase 1、2、3 | active Pattern + shadow Heuristic；不得生成正式 Skill |
| Phase 5—6 | Phase 2—4 | ML/DL Adapter、Case 与 Pattern 扩充 |
| Phase 7 | Phase 3、4；接入 ML/DL 时再依赖 5—6 | staged Skill Candidate + public/fresh-session evidence |
| Phase 8 | Phase 7 | private/hidden report + publication/promotion decision；不直接激活 |
| Phase 9 | Phase 8 的批准 decision | canonical publication、可选安装、canary/rollback 与 v1 release |

任何后续阶段可以为早期 schema 提交 successor/ADR，但不能通过倒序实现绕过 Evaluator。例如，在 Phase 3 前可以手工保存 Case 草案，却不能把它自动晋级为 Pattern 或 Skill。

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
11. 选择许可证；2026-08-23 权利持有人已选择 Apache-2.0，PR #14 已将许可证与来源 Gate 合入 `main`；
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
   - `research-failure-observation/v1`；
   - `research-failure-analysis/v1`；
   - `research-case-package/v1`（只定义通用 envelope；领域语义由 Adapter 提供）；

   ExperiencePacket 不作为 Core schema——定性为 Experience Exporter 的派生产物（ADR-0003）；
2. 实现 UTF-8 严格 JSON 读取与 duplicate-key 拒绝；
3. 实现 canonical serialization 和 SHA-256 pointer；
4. 实现 safe relative path，拒绝盘符、UNC、`..` 和逃逸；
5. 实现 create-new/append-only 发布；
6. 实现 `supersedes` 和 lineage graph 校验；
7. 实现 manifest 创建与全图验证；
8. 实现隐私分类、绝对路径检测和 redaction interface（Phase 1D 了结方式：redaction interface 以 `decision.constraints` 意图记录交付、执行器显式延期——见 ADR-0004 决策 9）；
9. 建立已知正确/错误 fixtures；
10. 对 schema 进行 backward/forward compatibility contract tests；
11. 输出命令行：`validate`、`hash`、`verify-graph`，但不执行外部写入。

### 交付物

- Core schemas 和 Python module；
- schema fixtures；
- unit/contract tests；
- `core-interface.md`；
- migration/compatibility policy；
- machine-readable validation report；
- ADR-0003：Phase 1C Run/Failure/Case envelope（引用、闭包与隐私边界）；
- ADR-0004：Phase 1D Privacy/Export/Compatibility。

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
- ADR-0005：Adapter interface v1（编号分配见 Phase 1 交付物：ADR-0003 = Phase 1C、ADR-0004 = Phase 1D）。

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

### 交付物

- 四个评测 Core family schema（`evaluation-case/v1`、`suite/v1`、`evaluation-run/v1`、`comparison-report/v1`）与 fixtures；
- replay envelope 与确定性离线 runner、scorer 四级与 score vector、统计三类、hard gates 六门与 evaluator meta-tests；
- `evaluate_case`/`compare` 装配与 HTML/Markdown/JSON 三形态报告；
- 首批公开 benchmark suites（Math/Quant 各 12 cases，全合成）与 Phase 3 验收报告；
- ADR-0006：Public Evaluator MVP（编号续接：ADR-0005 = Phase 2）。

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

## Phase 4：Research Memory、Pattern Library 与 Heuristic Registry

### 目标

把成功、失败和重大项目问题转为可复核、可检索的案例与模式候选，而不是让单次 LLM 总结直接修改生产规则或生成已安装 Skill。

### 实施任务

1. 建立通用一级 taxonomy 与 Math/Quant 二级 taxonomy；
2. 定义 `ResearchCasePackage`，至少冻结：问题签名、任务与边界、输入/输出 hash、中间产物清单、决策时间线、成功与失败观察、未决问题、环境、隐私/版权、导出模式和来源 lineage；
3. 建立 case eligibility gate；无法复现、来源不明、包含未授权敏感信息或只剩结论摘要的案例不得进入可共享 Pattern；
4. 实现 observation、analysis、cluster 和 counterfactual test registry；
5. exact fingerprint → 结构字段 → taxonomy → 语义 proposal 分层聚类；语义相似度只提出候选，不作合并或晋级裁决；
6. cluster merge/split 使用 append-only event，原始案例与旧索引不可被覆盖；
7. 定义 `ResearchPattern` schema，至少包含 `pattern_id`、problem signature、scope、preconditions、contraindications、successful tactics、failed tactics、evidence、confidence、source case IDs、last validated、successor、status 和 promoted Skill pointer；
8. Pattern 生命周期：captured → distilled → candidate-pattern → validated-pattern → active-pattern → deprecated/retired/rejected；
9. Pattern 晋级默认需要多个独立案例；高价值单例只能在可重现、反事实修复和独立复核齐全时例外进入 candidate-pattern，不得直接 active；
10. 实现确定性 metadata/text 检索 MVP：困难问题进入执行前先冻结 problem signature，再返回 3—5 个候选 Pattern 及其适用条件、禁用条件、来源证据和差异；无合适结果时明确 abstain；
11. 检索结果只作为 hypothesis/inspiration；操作者必须显式选择、拒绝或改写，当前 Run 记录所用 Pattern snapshot 及实际结果；
12. 定义 Heuristic schema、scope、mode、evidence、exception、risk 和 rollback；
13. Heuristic 生命周期：lesson hypothesis → candidate → shadow → validated → promoted/deprecated/retired/rejected；
14. 实现 duplicate、conflict、precedence cycle、dead/always-triggered rule linter；
15. 每个 Heuristic candidate 强制关联 regression case；
16. 实现 complexity budget、compression review、staleness review 和 successor 关系；
17. 只允许确定性全局不变量成为 global hard gate；
18. 运行 3—8 条 shadow Heuristic，不接入生产；
19. 建立中央库的 sibling layout：正式 `skills/`、`research-patterns/`、`skill-incubator/` 和 `catalogs/` 分离；Phase 4 只写隔离暂存区，不安装 Skill；
20. 为 Math、Quant 各建立至少 3 个合格 Case Package、2 个候选 Pattern，并记录至少 1 个“未找到适用模式”的正确 abstain 案例；
21. （E8/R33 审核登记的 backlog 候选）评估 `evaluation-run/v2` successor：v1 的 required 含 `output` 与 `score_vector`，致 `error`/`inconclusive` verdict 结构性不可装配（Phase 3 以 fail-closed 处理并留 `unpublishable_reason`）；v2 须按 verdict 条件化 required（或调整枚举/required 组合），由真实发布需求驱动，按 ADR-0004 兼容政策走 successor 义务。

### 交付物

- `research-case-package/v1` 与 `research-pattern/v1` schema；
- Case Package builder、redactor、validator 和 manifest；
- Pattern Registry、append-only lifecycle events 与 deterministic retrieval MVP；
- 检索结果中的 applicability/contraindication/evidence contract；
- Heuristic Registry、linter 与 shadow report；
- 中央库 layout contract 和 migration/retirement policy；
- ADR-0007：Research Memory 与 Pattern/Heuristic Registry（case package 以 `research-case-package/v2` successor 落地、生命周期走 supersedes 链——与本计划交付物行文的偏差见该 ADR 背景事实①）。

### 验收 Gate

- 单例失败不能自动生成 global rule；
- 单个项目复盘不能自动生成、安装或激活 Skill；
- root cause 在无反事实证据时保持 hypothesis；
- Observation 历史不因分析更新而变化；
- Case、Pattern、Skill Candidate 三类对象可通过 ID/hash 追踪，但互不冒充；
- Pattern 检索能够说明“为什么可能适用”和“何时不要用”，且允许返回空结果；
- 使用旧 Pattern 的 Run 记录实际帮助、无效或负迁移结果，反馈不覆盖原记录；
- 冲突、循环和无回滚的 blocking rule 被拒绝；
- shadow 只记录决策，不改变生产行为；
- `research-patterns/` 与 `skill-incubator/` 不在任何自动发现 Skill 根内；
- 公开 suite 无 critical regression。

### Git/发布 Gate

- 分支：`feat/research-memory-pattern-registry`；
- schema、case builder、pattern registry、retrieval、linter、shadow runner 分提交；
- PR 中列出每个 active Pattern/规则的来源案例、适用边界、反例和 regression case；
- annotated tag：`v0.5.0`；
- 不创建正式子 Skill、不安装 Skill、不创建 production Champion。

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
12. 增加 ML Heuristic shadow cases；
13. 将 ML 实验的完整协议、负结果、泄漏修复和复现差异采集为 Case Package；只有跨案例稳定模式才能进入 Pattern Registry。

### 交付物

- ADR-0008：ML Adapter——数据合同、声明式泄漏检查与确定性实验 runner（本 Phase 决策合同）；
- 四个 `ml-*` v1 adapter schema（`ml-task/v1`、`ml-case/v1`、`ml-claim/v1`、`ml-evidence/v1`）及 L4 successor（`evaluation-contract/v3`、`ml-evidence/v2`）与 fixtures——零新 Core family，Core 保持 17 family；
- 对已声明实验拓扑的确定性泄漏检查（split/preprocessing/采样/target-encoding/tuning/selection 规则面，"声明即证据下限" fail-closed；拓扑声明以 {identity, sha256} + 上游 input pin 构成 DAG，保证 lineage 可重建；语义规则的正例一律 schema 合法、mutation 可证伪）；
- 标准库纯函数合成实验 runner（baseline/resource parity、seed 重复研究、确定性规范产物；零 I/O、零第三方依赖；L5 runner 0.3.0 支持 contract-bound IID/group/time-series/nested assignment 验证，仍为 no-transform/no-search 显式内存合成数据，nested 不执行逐折训练）；
- 15—25 个公开/合成 cases、两条垂直切片（非时间序列 + 时间序列）与 leakage fixture/重复实验报告；
- ML Heuristic shadow cases、ML Case Packages（复用 Phase 4 机器）、ML/Quant 重合分析（下沉判据三条件，结论先于动作）与 Phase 5 验收报告。

实施状态（2026-08-21）：L1–L6 工作树验收 PASS。L6 复用 Phase 4
experience interface 生成 4 个 ML Case Package、1 条两版本 candidate Pattern
链、3 条三版本 shadow Heuristic 链与 1 份 hypothetical-only shadow report；
32-record 临时 store 图闭包通过，双 Python 环境全量均为 865/865，PowerShell
治理 33 assertions / 6 cases。独立审核将 reproduction comparison 拆为 A1/A2/B
三条 hash-bound Run，显式记录 master-seed 派生；将 Pattern facet 改为跨案例
`protocol-evidence-comparison`；并使三条 shadow observation 具有独立决策与预期
差异。ML/Quant 重合分析未发现同时满足三项下沉判据
且具有足够 module depth 的新逻辑，因此零 Core/schema/interface 改动。最高
证据等级仍为 engineering-only；真实 `git archive` 已绑定独立审核修复
commit `a0dfc7d389adc46070ba6ec35a1daaeeff098310` 双解释器通过 865/865
（各 1 个预期 Git tracking skip）。

PR 代码集成基线证据（2026-08-22，合并前历史时点）：合入公共 CI baseline 后的集成提交
`3b35ca5b2770fcff4d7fb6b02fe014c1f7cb7f99` 在工作树与真实 `git archive`
双解释器均为 870/870（archive 各 1 个预期 Git tracking skip）；PR #11
在该集成提交上的 Windows/Ubuntu × Python 3.12/3.14 四项 required checks 也各为 870/870，
两个 Windows job 另过 PowerShell 33 assertions / 6 cases。以上为 PR 合并前的代码集成基线证据；
前段 865/865 与 `a0dfc7d` 继续保留为 L6 独立审核时点的历史验收证据。

Post-merge 验收证据（2026-08-22）：PR #11 已通过 merge commit
`216ec216af385a3b585fc1c6505d25ac67eac585` 合入 `main`；该提交的 main push CI
run `32574399179` 在 Windows/Ubuntu × Python 3.12/3.14 四项 job 全部成功，
两个 Windows governance 步骤成功。真实 `git archive` 双解释器均为 870/870
（各 1 个预期 Git tracking skip），verdict 与 commit SHA 一致。以上为 Phase 5
功能 PR 的 post-merge 历史验收点。

发布终态证据（2026-08-22）：PR #12 将 post-merge 状态文档通过 merge commit
`c72e31eb4d5dbd367b20f24678e94682b963fed9` 合入 `main`；main push CI run
`32579211332` 的 Windows/Ubuntu × Python 3.12/3.14 四项 job 与两个 Windows
governance 步骤全部成功，真实 `git archive` 双解释器均为 870/870（各 1 个预期
Git tracking skip）。annotated tag object
`3f109b3e0c1366b93f780be21447e229aa3c3b3e` 指向该提交；`v0.6.0` GitHub Release
以正式、非 prerelease、latest 状态发布六项 evidence assets，GitHub digest 与逐项
回下载 SHA-256 对账均一致。该发布仍只是 engineering-only source milestone，
不产生 Python package、OSS、Skill 安装或 Champion promotion 事实。

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
- 切片与提交映射（ADR-0008 决策 10）：L1 = ADR → L2 = 数据合同 → L3 = 泄漏检查 → L4 = runner → L5 = cases/垂直切片 → L6 = shadow/Case Package/重合分析/验收报告；
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
12. 发布 DL Adapter 已验证的硬件/框架矩阵；
13. 将 OOM、NaN、失败 seed、恢复失败和 compute-matched 结论纳入 Case Package，禁止只保存最佳 checkpoint 的成功叙事；
14. 为 DL Pattern 增加硬件、框架、规模和预算适用边界，防止跨环境负迁移。

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

## Phase 7：Skill Incubator、Candidate Builder 与公开受控进化循环

### 目标

从 validated Pattern 生成可审计的 Heuristic/代码/子 Skill Candidate，但保持 Candidate 无中央正式库写权限、无安装根写权限、无 hidden 权限、无自晋级权限。

### 实施任务

1. 定义 immutable candidate manifest；bundle 包含 baseline hash、patch、Heuristic/Pattern snapshot、tests、风险、rollback 和来源 Case/Pattern IDs；
2. 为子 Skill 定义 promotion eligibility：至少跨两个独立问题可复用，具有清晰触发与排除条件、稳定输入/输出、失败/暂停边界、可移植资源和可测量增益；仅项目专用脚本、一次性答案或仍在快速变化的知识不得升为 Skill；
3. 使用官方 Skill 初始化器建立最小候选目录，`SKILL.md` 只保留必要工作流，详细 schema、示例和领域资料按 progressive disclosure 放入 `references/`、`scripts/` 或 `assets/`；
4. `agents/openai.yaml` 等平台元数据与 Skill payload 分层校验；Skill description 同时描述正触发与重要排除场景，并加入 Router 负例；
5. Candidate 只读公开/获授权 experience、Case Package 和 Pattern；来源证据保存在外部 candidate manifest，不把私有路径、原始记录或冗长 provenance 塞入可安装 payload；
6. patch 与 regression case 原子生成；固定模型、reasoning、工具、预算、迭代次数、并发和成本；
7. 运行静态验证、路径/密钥/引用扫描、trigger collision、重复 Skill、payload diff、公开 regression 和公开 dev A/B；
8. 建立 independent fresh-session forward test：由未参与候选编写的会话，从原始问题/工件开始，验证显式调用、隐式触发、Router 实际选择、边界判定和最终 artifact；测试输入不得泄漏期望答案或作者自检结论；
9. Skill lifecycle 固定为：pattern-backed proposal → staged candidate → static validated → independent forward-tested → private/hidden evaluated → publication-approved → canonical → installed/archived/rejected；失败分支保留原因和 successor；Phase 7 最多到 independent forward-tested/ready-for-private-review；
10. 生成中央库 publication plan：staged mirror、目标文件预写 SHA-256 guard、逐文件 diff、验证、人工审批和同步步骤；真正 canonical 写入及安装根对账推迟到 Phase 8 decision 通过后；
11. Kimi 或其他 receiver-owned frontmatter/metadata 由接收方重新生成，或在比较器中规范化排除；不得用中央候选覆盖删除接收方配置；
12. 防止 Candidate 修改 evaluator、报告、baseline、中央正式库、安装根或 Default/Preset；
13. 生成 comparison report、publication plan、installation plan 和拒绝原因；publication/installation 只输出计划，除非分别获得授权；
14. 实现 candidate archive、去重、compression review、deprecation、replacement 和 orphan cleanup 检查；
15. 自动化等级最多到 E2：自动 candidate + public suite，人工决定 canonical publication、Git 发布、安装和激活；
16. 为 Candidate/Case/Experiment bundle 定义 `Artifact Closure Receipt`：manifest 成员、字节 hash、DAG、排除清单和 receipt-last 规则；明确闭包不等于科研正确；
17. 生成 manifest 驱动的 `ContextBundle`（normal/compact/minimal-safe），保留 objective、权威 head、未解决义务、来源失效与省略清单；安全最小集超预算时 fail closed；
18. 建立来源 lifecycle 与 impacted closure：correction/retraction/license-blocked 不改写历史，但阻塞受影响 Candidate 的 publication/promotion；
19. 独立语义审查绑定 exact candidate hash，author/reviewer principal 分离；structural PASS、semantic PASS 与 ready-for-private-review 分开；
20. 至少用 Math 与一个经验领域实现运行 seam/deletion test；只有两域字段语义与消费者均成立时才提通用 Core successor。

### 子 Skill 晋级最小证据包

- problem signature 与正/负触发案例；
- 至少两个相互独立的来源 Case，或经特批的高价值单例及其复现、反事实和独立复核；
- 关联 Pattern 的 scope、contraindications、证据等级和最后验证时间；
- 静态验证、回归、触发冲突和 fresh-session forward test 报告；
- payload manifest、依赖/许可/隐私审查、rollback/retirement 计划；
- 与无 Skill baseline 在相同资源 envelope 下的配对比较；
- 人工 reviewer 的 approve/reject decision。

### 验收 Gate

- bundle 可由 manifest 重现；
- 每个 patch 有目标 failure class 和 regression case；
- Candidate 没有 evaluator/private/central-library/installed-root/production 写权限；
- 资源扩大不能伪装为能力提升；
- public 改善但 critical regression 时自动拒绝；
- 作者自检不能替代独立 fresh-session 动态验收；目录存在和静态发现不能替代真实运行时加载；
- 新 Skill 的正触发、排除、Router 选择和相邻 Skill 冲突均有测试；
- Phase 7 结束时 Candidate 仅可标记 `READY_FOR_PRIVATE_REVIEW`，不得标记 canonical、installed 或 active；
- closure receipt 后任一成员字节变化都会使 receipt 失效；byte closure 不得满足 semantic Gate；
- ContextBundle 的 minimal-safe 模式不会静默省略 objective、PIT/split/holdout、失效来源或 blocker；
- 来源失效只改变证据可用性/复核状态，不自动断言 Claim 为假，也不重写历史；
- 一个领域的实现或名字相似不能证明 Core seam；两域实现与 deletion test 是下沉前置条件；
- canonical publication、Git push/tag、安装和 Default/Preset/Champion activation 四类操作分别审批；
- 不执行自动 push/tag/publication/installation/promotion。

### Git/发布 Gate

- 分支：`feat/skill-incubator-candidate-builder`；
- PR 附至少一个接受和一个拒绝 Candidate 的完整证据，以及一组 fresh-session forward test；
- annotated tag：`v0.8.0`；
- Candidate bundle、canonical Skill 版本、仓库 Release 和安装版本分别记录。

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
9. 建立独立的 manual `PublicationDecision` 与 `PromotionDecision`；前者只批准进入 canonical library，后者只批准 Champion/canary，二者不得复用；
10. 故障注入：hidden read、report tamper、resource cap change、judge reversal；
11. 演练 reject、canary plan 和 rollback plan；
12. 对已批准 Skill Candidate 补做独立运行时验收：dynamic discovery、隐式触发、Router 实际选择、fresh-session verdict、相邻 Skill 负例和接收方元数据保留；
13. 将 Pattern/Skill 检索的负迁移、过度触发和上下文污染纳入 hidden/future holdout；
14. 记录最小化的公开 Release evidence，不泄漏 hidden 内容；
15. 故障注入 receipt 后 byte mutation、成员遗漏/DAG 成环、旧 semantic verdict 复用和 reviewer principal 复用；
16. 故障注入 stale/retracted/license-blocked source，证明其阻塞 publication/promotion 且不修改历史记录；
17. 故障注入派生 Research Map/ContextBundle 携带 hidden 路线、答案或自动 route decision，验证派生层拒绝；
18. 对 support matrix 注入同平台 `expected`/`verified` 矛盾，确保单一事实源 meta-test 拒绝。

### 验收 Gate

- 以 OS/CI/ACL 证据证明隔离，不以目录名证明；
- Evolution 环境无法获取 hidden 原文；
- 输出泄漏测试通过；
- meta-tests 检测全部故障注入；
- 任一 hard gate 失败不能晋级；
- Promotion 仍要求人工批准；
- Phase 8 只形成 hash-bound publication/promotion decision；canonical 写入、安装和激活仍由 Phase 9 分别执行；
- 静态 `quick_validate`、作者自检和 staged payload 一致性不被表述为运行时验收；
- structural PASS、independent semantic PASS、private/hidden PASS 三层 verdict 不可互相替代；
- source invalidation 和 receipt mutation 的 fault injection 全部被 meta-tests 杀死；
- 未安装 Candidate 不得声称完成 dynamic discovery 或隐式路由验证；
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
5. 当前 `math-research-solve` v8/1.0.1 基线保持只读；外部工具包 1.11 中的 v13 只可作为单独登记、hash-bound 的候选设计基线，先过来源/许可和独立动态验收，再以显式 Math executor successor/protocol version 接入，绝不覆盖 v8；
6. 第一批只 canary advisory/verifier checks，不自动 hard-block 高不确定规则；
7. 观察 false block、false completion、成本和人工接管；
8. 实现 one-step rollback，并验证新增文件 hash 后再移除；
9. 冻结 `v1` schema、Adapter compatibility 和 support matrix；
10. 完成安全、隐私、统计、文档和恢复审计；
11. 准备 changelog、migration、release notes 和 artifact manifest；
12. 发布 approved canonical Skill 时生成中央库 publication receipt、逐文件 manifest 和安装前 comparison report；
13. 用户批准后提交、push、tag、Release；Skill 安装和 Champion activation 再单独批准；
14. 每次研究项目 closeout 生成 Case Package，经过 eligibility/redaction 后进入 Pattern 队列；不得因项目结束而自动创建新 Skill；
15. Math executor successor 将已验证 research-authority 与可恢复 execution-state 分头保存；先写不可变对象，再 validate/compare expected head，最后 guarded commit head 并 read-back；
16. 并发失败只允许 conditional rollback：仅当 current head 仍等于本次写入值时回退，不覆盖其他 writer 的成功提交；
17. publication 采用 prepare/validate/commit 与 completion receipt 两阶段；完成声明不能先于 exact snapshot、语义 verdict、receipt 和回读验证；
18. Math 的 exactly-three attempts 与逻辑充分条件不推广为全域规则；Quant/ML/DL 只采用领域化 bounded portfolio 与 claim obligation graph。

### v1.0 Definition of Done

- 四领域 Adapter 均有 contract tests 和公开验证边界；
- L0/L1 稳定，至少一类任务完成 L2；
- private/hidden 物理隔离与输出泄漏防护通过；
- promoted Heuristic 有 evidence、scope、case、risk、exception 和 rollback；
- Candidate 无 hidden/evaluator/production 写权限；
- Champion/Challenger 使用相同资源 envelope；
- canary 与 rollback 至少真实演练一次；
- v8 baseline 可按原 hash 回放；Math successor 的 authority/execution 双头、并发提交和 conditional rollback 已通过故障注入；
- Math/Quant/ML/DL 的 bounded portfolio、ContextBundle 与 semantic reviewer 均保留领域语义，没有被 Core 统一状态机抹平；
- Release artifact、Git tag、commit 和 manifest hash 一致；
- Pattern promotion、canonical Skill publication、Git/Release、Skill 安装和 Champion promotion 有五类独立 decision/receipt；
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

### 4.5 重大问题与项目收尾的知识采集

```text
冻结困难问题与边界
→ 执行并持续保存中间产物
→ 形成 Research Case Package
→ 隐私/版权/可复现/完整性 Gate
→ 聚类与反事实分析
→ 蒸馏 Research Pattern
→ reviewer 决定 active / revise / archive / reject
→ 更新可检索索引
```

- 中间产物按 manifest 引用，不默认复制大型数据、模型、论文正文或私密工作区；
- 同时保留成功路径、失败路径、被否定假设、停止条件和未解决问题，防止只记录“成功故事”；
- 项目特有知识优先保留为 Case 或 Pattern；只有出现稳定、跨项目、可触发、可测试的工作流时才进入 Skill Incubator；
- 项目删除、归档或结束不删除其 lineage；私有源不可导出时只发布脱敏模式或 metrics-only 记录。

### 4.6 困难问题开始前的启发检索

```text
ResearchTask 冻结
→ 生成 problem signature
→ 检索 active Pattern / approved Skill metadata
→ 返回候选、差异、适用条件、禁用条件和证据
→ 人工选择 / 改写 / 全部拒绝
→ 将选定 snapshot 绑定当前 Run
→ 运行后记录 helped / neutral / harmed / not-applicable
```

- 首版使用确定性元数据和全文检索；只有在 corpus 规模和评测证明需要时才引入 embedding/vector store；
- 检索器不得只返回相似度，必须暴露来源、时间、适用边界、反例和 stale 状态；
- 旧思路用于提出假设、检查遗漏和选择工具，不替代当前问题的验证、证明、实验或风险审查；
- 未命中或全部不适用是合法结果，不以强行召回充当“智能”。

### 4.7 中央库与安装根同步

```text
approved staged candidate
→ canonical publication plan
→ pre-write target hash guard
→ staged mirror + validation + diff
→ human approval
→ canonical Skill publication
→ optional Git release
→ optional installed-root sync
→ fresh-session acceptance
→ optional activation
```

- 中央库是权威源码库，安装根是派生副本；不得在多个安装根手工并行编辑；
- 同步前后记录 hash manifest、目标不存在/add-only 状态、receiver-owned metadata 处理和 rollback 位置；
- 真实安装、提交、push、tag、Release 和激活均按各自授权边界执行。

### 4.8 外部基线与跨领域设计吸收

- 外部 Skill/工具包先登记 artifact hash、版本、来源、许可、获取日期和只读审查状态；无明确兼容许可时只允许抽象层设计评审，不复制 payload；
- 当前 Math v8/1.0.1 基线不可变；v13 不与其并列登记、不覆盖、不静默升级；
- v13/Pika 处理遵循 [来源边界与延期说明](MATH_RESEARCH_SOLVE_V13_CROSS_DOMAIN_ADOPTION_PLAN.md)：原始 artifact 与许可不可核验时排除 payload 和详细表达；
- 任何未来设计必须从本项目自身需求独立形成 ADR，并先满足来源、许可、隔离审查和用户单独授权 Gate；
- 新 Core seam 必须有至少两个领域的实际消费者、字段语义一致性和 deletion test；单领域实现只能留在 Adapter/Executor；
- Research Map/ContextBundle 是可重建派生物，既不作为 Evidence，也不授予 route、publication、installation 或 activation 权限。

### 4.9 开源资格与外部申请

- Codex for Open Source 的建设与申请按 [资格申请完整计划](CODEX_FOR_OSS_APPLICATION_PLAN.md) 执行；
- `v0.6.0` Phase 5 milestone 与 `v0.6.1` OSS-readiness source Release 均已完成；Apache-2.0、NOTICE、来源清单与 `unknown=0` Gate 已进入 `main`，GitHub 已识别 Apache-2.0；
- PR #15—#17 已完成 source-install Quick Start、support matrix、四项 exact-commit archive install/demo required checks 与公共协作治理；PR #18、annotated `v0.6.1` Tag、六项 Release assets 和回下载校验已完成。当前按 [O5 外部试用协议](../governance/EXTERNAL_TRIAL_PROTOCOL.md)启动真实试用入口，但尚无外部结果；
- star、fork、download、contributor 等指标只在申请日实时读取，不制造或夸大采用；
- 表单文案逐句绑定公开证据，私密字段不进入仓库；填写和提交申请仍需用户单独授权。

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
| Skill 爆炸与触发冲突 | 上下文膨胀、路由不稳定 | Case/Pattern 优先、promotion eligibility、负触发和 Router collision tests |
| 历史模式负迁移 | 旧经验误导新问题 | applicability/contraindication、staleness、空结果、forward/hidden tests |
| 自证式评测污染 | 候选按作者期望答案通过 | 独立 fresh-session、原始输入、holdout、作者自检与验收分离 |
| 中间产物泄漏 | 隐私、版权、密钥或大文件外泄 | redaction/export mode、许可审查、manifest pointer、secret/path scan |
| Pattern 过期 | 环境变化后仍被检索 | last-validated、successor、expiry review、helped/neutral/harmed 反馈 |
| DL 成本/随机性 | 无法复现 | compute manifest、多 seed、small fixture 与 full run 分离 |
| 错误自动上线 | 生产退化 | 人工 Promotion、canary、rollback、独立 receipts |
| Git/Tag 漂移 | 发布不可追踪 | annotated immutable tags、SHA 校验、无 force push |
| 私有科研泄漏 | 隐私/版权损失 | explicit exporter、Git ignore、secret/path scan |

## 6. 初始执行批次建议（历史基线，制定于 Phase 0 后）

> 本节为 Phase 0 后的收缩建议存档，不反映当前进度；当前执行入口以文件头部「当前状态」与对应 Phase 节为准。其中第 4/5 条的克制原则（seam 证明前不自动晋级、检索评测证明前不引入向量库）继续有效。

Phase 0 已形成仓库治理基线；下一批只启动：

1. 固化 Phase 0 延期 Gate 与 `v0.1.0` 基线收据，不重复改写历史验收；
2. Phase 1 的三个最小 schema：Task、Claim、Evidence；
3. 只设计 `ResearchCasePackage` envelope，并用一个 Math failure 与一个 Quant leakage case 做手工草案；
4. 在 Phase 3 Evaluator 和双垂直切片证明 seam 前，不实现 Pattern 自动晋级、Skill Incubator 或 Hidden 服务；
5. 在 Phase 4 检索评测证明 corpus 和延迟需求前，不引入向量数据库、embedding 服务或复杂知识图谱。

该收缩能尽早验证平台是否真正跨领域，并防止在评测器尚未可信时先积累大量不可证伪的“经验”和过早生成子 Skill。
