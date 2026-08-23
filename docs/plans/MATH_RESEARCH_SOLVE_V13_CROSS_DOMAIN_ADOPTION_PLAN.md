# math-research-solve v13 跨领域吸收与升级计划

- 计划状态：`PLANNING_ONLY / DEFERRED_AFTER_V0.6.0`
- 计划版本：v1.1-post-v0.6.0
- 初次评估日期：2026-08-20
- 状态同步日期：2026-08-22
- 适用范围：Math、Quant、ML、DL Adapter；Research Memory；Evaluator；Skill Incubator；未来 Executor
- 当前动作：只登记设计与验收方案；未导入外部 payload，未采用 v13 schema/代码/状态机，未改变 v8/1.0.1 基线

> 本计划吸收的是经独立审核后成立的设计不变量，不是对外部 Skill 的复制、安装或兼容性承诺。任何实际实现仍须单独 ADR、版本与测试 Gate。

项目状态同步（2026-08-22）：Phase 5 已以 `v0.6.0` 发布，但该版本没有实现或复制本计划中的 v13 机制；它只提供现有 ML experiment DAG、final-evaluation pin、Case/Pattern/shadow Heuristic 等可供未来 seam 评估的本项目证据。外部 v13 包的许可仍未确认，因此本计划继续保持 planning-only，并延后到独立来源/许可决策与后续 Phase ADR。

## 1. 来源快照与权利边界

审查输入为用户提供的 `pika_math_learning_toolkit-1.11.zip`：

- 工具包版本：1.11；其中 `math-research-solve` 标记为 v13；
- 工具包共 493 个文件，其中 `math-research-solve` 子树 249 个文件；相对当前本机 79 文件基线，该子树有 170 个新文件、18 个同路径文件发生变化；
- 审核文件 SHA-256：`D8E15E62CD7CC84F292382A1C00CA1E75995B273EB0F26A96828D70A94FB5D12`；
- 审核方式：只读静态检查；未安装、未执行、未同步到项目；
- 附件内未发现明确 `LICENSE`；因此不得复制源码、schema、fixture、测试、模板或长段说明；
- 包内 support matrix 对 Linux 1.11 的 `expected`/`verified` 表述存在不一致，不能把包内自述直接当作独立验收。

当前项目的 `math-research-solve` v8/1.0.1 portable 基线继续只读。v13 只能作为独立来源登记的候选设计基线；若未来需要代码级集成，必须先解决许可与来源问题，并使用显式 successor/protocol version，不能覆盖 v8。

## 2. 总裁定

v13 最有价值的不是“数学工作流步骤更多”，而是把长期研究拆成了若干可审计边界：目标承诺、权威事实与执行状态分离、因果记忆、来源失效传播、派生研究图、受限上下文、包闭包收据、独立语义审查和守护式提交。这些机制中，一部分可跨 Math/Quant/ML/DL 共用；另一部分只能在各领域 Adapter/Executor 内同构实现；少数 Math 专属规则必须拒绝泛化。

因此采用三层策略：

| 层 | 定义 | 处置 |
|---|---|---|
| A：跨领域不变量 | 四领域都需要，且语义可稳定描述 | 先用现有对象和私有实现验证；至少两个领域证明后才考虑下沉 |
| B：领域同构机制 | 目的相同，但字段、判据、窗口或审计内容不同 | 留在 Adapter/Executor，用参数化 contract suite 对齐形态 |
| C：Math 专属机制 | 依赖证明逻辑、量词或定理结构 | 只升级 Math，不进入通用 Core，也不强迫经验领域模仿 |

## 3. 不可违反的设计原则

1. **吸收不变量，不复制实现**：外部包只提供设计线索；项目使用自身术语、schema、代码和测试重新证明。
2. **Core 不承载领域状态机**：证明搜索、回测执行、ML 试验和 DL 训练状态均不进入 generic Core。
3. **先复用现有深接口**：优先用现有 `ResearchTask`、`Run`、Case/Pattern、Adapter 三操作、Evaluator 和 Publication/Promotion 接口；不为每个新概念增加公共方法。
4. **一个领域只是猜想，两个领域才是 seam 证据**：任何下沉 Core 的候选必须至少在两个独立 Adapter/Executor 中出现，并通过 deletion test。
5. **结构 PASS 不等于语义 PASS**：hash、manifest、DAG、schema 和 receipt 只证明闭包/一致性，不证明数学正确、回测有效或模型泛化。
6. **权威事实与运行中状态分离**：不可变已验记录和可重试执行进度不能共享一个可变事实源。
7. **派生视图不是证据**：Research Map/ContextBundle 只帮助阅读和检查覆盖，不决定路线，不支撑 Claim。
8. **经验领域没有数学式充分条件**：Quant/ML/DL 只能定义 claim eligibility、证据义务和停止条件，不能把 checklist 宣称为结果为真。
9. **范围门控不是生命周期状态**：`review_required`、`needs_data_audit` 等是 scoped gate；不可与 candidate/canonical/active 状态混用。
10. **所有写动作仍守权限边界**：计划、candidate publication、canonical write、安装、激活和 Git Release 分别批准。

## 4. 机制吸收总表

| v13 机制 | 分层 | 跨领域抽象 | 首个落点 | 明确禁止 |
|---|---|---|---|---|
| Immutable objective core | A/B | Objective Commitment | 现有 Task + Run hash pin + Adapter 校验 | 再造重复 Core family |
| Research-authority / execution-state 双头 | B，待 A | Authority/Execution Split | 各 Executor 私有状态 | 立即修改 Core publication graph |
| Prepare→validate→commit | A | Guarded Commit | Publication/Promotion 与 future executor head | 无校验原地覆盖 |
| 因果记忆 v2 | A/B | Causal Research Memory | Case Package/Pattern successor 候选 | 只记“做了什么”不记为何有效/无效 |
| Source lifecycle/invalidation | A/B | Source Integrity Closure | Memory/Registry + Adapter 来源规则 | 修改历史记录或静默删除 |
| Research Map | A/B | Derived Program Map | Memory 的派生只读视图 | 充当证据或自动 Router |
| Bounded project cognition | A/B | ContextBundle | Retriever/Executor 输入 | 静默截断关键限制或权威事实 |
| Exact candidate semantic review | A/B | Independent Semantic Review | Evaluator/Incubator | 作者自检或结构验证替代语义验收 |
| Attempt package preflight receipt | A | Artifact Closure Receipt | Candidate/Case/Experiment bundle | 把 byte closure 写成科研正确性 |
| Cheap decisive gates first | A | Phase-gated Materialization | 全部 runner/exporter | 在 P0 失败前生成昂贵产物 |
| Terminal audits | B | Domain Audit Triad | 各 Adapter 的 reviewer profile | 用统一泛化 judge 掩盖领域风险 |
| Completion publication pair | A | Commit + Completion Receipt | Publication/Promotion | 先宣称完成后补证据 |
| Exactly three atomic attempts | C/B | Bounded Portfolio，基数领域化 | Math 保留 3；其他领域自行预注册 | 全领域固定 3 次/3 路线 |
| Terminal sufficient conditions | C/B | Claim obligation graph | Math 可用逻辑充分条件；经验域仅门槛 | 把实验 checklist 叫“充分证明” |

## 5. 跨领域升级设计

### 5.1 Objective Commitment：目标核心冻结

通用目标不是共享一套领域字段，而是共享“语义变化必须产生新 commitment”的纪律。

| 领域 | 必须冻结的 objective core | 语义变更示例 |
|---|---|---|
| Math | 精确命题、论域、量词、假设、允许证据、完成判据 | 从存在性改成分类；增加紧致性假设 |
| Quant | 研究问题、资产池、PIT 数据、时间范围、基准、成本/执行模型、Claim 标准 | 改 universe、数据可得时点或交易价格 |
| ML | dataset pin、split policy、预处理/采样作用域、目标、模型比较、指标、selection 与 holdout policy | 在看过 test 后改 metric 或模型族 |
| DL | ML 字段 + hardware/runtime/framework、compute budget、checkpoint/恢复与选择协议 | 改 GPU 数、训练预算或 checkpoint 选择 |

计划落点：

- 继续使用 Core `ResearchTask` 的 identity/hash 和 `Run` 对 task hash 的 pin；
- 各 Adapter 把领域 objective 规范化为已版本化 envelope；
- 同一 identity 对应同一 canonical hash；任何语义变化产生新 task/version/successor；
- 不把运行中调参反写到已冻结 objective；偏离必须形成显式 deviation record；
- L2/L3 contract 测试加入“变更一个塑造性字段必须改变 hash/版本”的 mutation。

### 5.2 Authority/Execution Split：权威与执行状态分离

建议通用语义：

```text
authority head → 已验证、可引用、append-only 的研究事实
execution head → 可重试、可失败、可恢复的当前工作进度
```

领域映射：

- Math：已验证 lemma/依赖/反例 vs 当前 proof attempts/tool jobs；
- Quant：已接受数据快照/协议/报告 vs 下载、清洗、回测和敏感性运行；
- ML：已验证 experiment contract/evidence vs trial/search/seed 运行；
- DL：已接受 checkpoint/report vs job、preemption、OOM 与恢复进度。

采用策略：先在 Math Executor successor 和另一个经验领域 Executor 以私有实现证明；公共接口只暴露“读取指定 authority snapshot”和“提交经验证的 transition”。若删除任一领域后抽象失去独立价值，则不下沉 Core。

### 5.3 Guarded Commit：守护式头更新

所有权威指针更新采用：

```text
prepare immutable objects
→ validate references / schema / scope / policy
→ compare expected old head
→ commit new head last
→ read back and verify
→ append receipt/journal
→ failure uses conditional rollback or leaves recoverable orphan
```

计划约束：

- 不依赖“写文件顺序大概正确”；
- commit 前锁定 tested hash、old head、policy version 和 writer identity；
- rollback 只在 current head 仍等于本次写入值时执行，避免覆盖并发成功写入；
- orphan immutable objects 可被审计/清理，但不可假装未发生；
- 该机制优先放入 Future Executor/Publication 私有实现，不能扩张现有 Core 三操作签名，除非 contract 证明确需公共 seam。

### 5.4 Bounded Portfolio：有界研究组合，而非全域固定“三次”

Math 的 exactly three atomic attempts 是一个领域策略，不是跨领域真理。可吸收的是：在行动前预注册一个**有限、彼此可区分、可停止**的组合，防止无限漂移与同义重复。

| 领域 | 区分 fingerprint | 基数/预算策略 |
|---|---|---|
| Math | proof object、mechanism、quantifier pattern | v13 successor 可保留 exactly 3 |
| Quant | signal family、data regime、execution model、validation regime | 由预注册预算/多重检验约束，不固定 3 |
| ML | representation、model family、split/validation regime、selection protocol | 由 search budget 与 frozen holdout 约束 |
| DL | architecture、scale/compute budget、training strategy、checkpoint policy | 由算力/成本 envelope 约束 |

公共候选只应是 `BoundedPortfolioPolicy` 的概念合同：最大预算、差异 fingerprint、停止/扩容审批、重复判定。基数和字段留在 Adapter。至少 Math+ML 或 Math+Quant 的 deletion test 通过前，不新增 Core schema。

### 5.5 Causal Research Memory：从时间日志升级为因果记忆

Case/Pattern 的 successor 候选应能回答下列语义问题。以下名称是本项目的候选术语，不复制外部 schema；最终字段须由 ADR 和 fixture 证明：

- `method_summary`：方法是什么；
- `parameter_semantics`：哪些可调量及其含义；
- `critical_path`：不可删除的关键步骤/依赖；
- `transferable_structures`：可迁移的结构；
- `bottleneck_delta`：解决或暴露了哪个瓶颈；
- `non_entailments`：结果明确不能推出什么。

跨领域解释：

| 字段 | Math | Quant | ML | DL |
|---|---|---|---|---|
| critical path | lemma chain/变换主干 | data→signal→portfolio→execution | split→fit→select→holdout | data→architecture→train→checkpoint |
| parameter semantics | 常数、指数、边界条件 | lookback、rebalance、cost、capacity | model/search/seed/threshold | batch、LR、steps、compute、checkpoint |
| transferable structures | reduction/invariant | PIT join、neutralization、execution guard | fold-local pipeline、negative control | recovery、compute-matched ablation |
| bottleneck delta | 消除哪个证明障碍 | 修复何种 bias/leakage | 关闭哪条 leakage/generalization 缺口 | 关闭 OOM/selection/recovery 缺口 |
| non-entailments | 未覆盖量词/条件 | 非真实可交易收益/非因果 | 非生产泛化/非外部验证 | 非跨硬件复现/非稳定规模律 |

计划：先在各域 Case fixture 中用现有扩展面或私有派生对象验证。只有字段在至少两域都有独立查询/评测消费者时，才提 `research-case-package/v3` 或 `research-pattern/v2` ADR；否则保留 Adapter extension，避免为描述性字段制造 Core 膨胀。

### 5.6 Source Integrity Closure：来源生命周期与失效传播

通用来源状态应至少能表达 `active`、`superseded`、`corrected`、`retracted`、`license_blocked`、`unavailable`，但具体触发规则领域化：

- Math：定理引用纠正、前提误引、论文撤稿、版本替换；
- Quant：供应商修订、复权/公司行动修正、交易日历或 PIT 时间戳修正；
- ML：标签修正、数据集版本/许可变化、训练测试污染；
- DL：checkpoint 损坏、框架/CUDA 变更、硬件复现限制、上游数据失效。

失效语义：

1. 不重写历史 Case/Claim/Evidence；
2. 追加 source event 与 successor；
3. 沿显式依赖边计算 impacted closure；
4. 把受影响 Claim/Pattern/Candidate 标为需重验或阻塞 publication/promotion；
5. 已发布 artifact 保留原 receipt，同时新增撤回/替代说明；
6. 失效本身不自动证明结论为假，只改变证据可用性与审核状态。

初步落点在 Research Memory/Registry，不扩展 Adapter 三操作。只有跨域 dependency closure 的身份/边语义稳定后才考虑 Core successor。

### 5.7 Derived Program Map：派生研究程序图

Research Map 可下沉为一个通用**只读派生产品**，但内容必须由 Adapter 提供：

- Math：目标、lemma、route、依赖、已覆盖/未覆盖量词与反例；
- Quant：data→signal→portfolio→execution→risk/bias；
- ML：data→split→preprocess/sample→model→selection→generalization；
- DL：data→architecture→training→checkpoint→resource→stability/recovery。

共同约束：

- 每个节点/边回指权威记录 hash；
- 可丢弃并重建，不作为唯一事实源；
- 不包含下一步自动 route decision，不向 Candidate 泄漏 hidden 结论；
- “覆盖”是图上的声明/证据状态，不等于科研结论为真；
- stale/unknown 必须显式显示，不用摘要文字抹平；
- Map builder 的删除不影响底层记录可验证性。

### 5.8 ContextBundle：受限但语义安全的项目认知

ContextBundle 应由 manifest 构成，而不是直接截断日志。建议通用段：

1. objective commitment；
2. current authority head；
3. unresolved obligations/risks；
4. active sources + invalidations；
5. recent causal memory；
6. domain-specific safe minimum；
7. omitted inventory（省略了什么及原因）；
8. exact token/byte budget 与生成器版本。

三档：`normal`、`compact`、`minimal_safe`。任何档位都不能省略 objective hash、关键假设/数据时点、holdout/selection 边界、invalidations、授权边界和未解决 blockers。若最小安全集合仍超预算，fail closed 并请求扩容；不得静默截断。

领域最小安全集：

- Math：命题、量词、假设、未证义务、关键反例；
- Quant：universe、PIT/data version、交易时点、成本、未解决 bias；
- ML：dataset/split、fit scope、selection/holdout、seed、assessment gaps；
- DL：ML 字段 + hardware/runtime、budget、checkpoint、失败 seeds/recovery。

### 5.9 Artifact Closure Receipt：包闭包而非真理证书

统一 preflight receipt 可以覆盖：

- Math attempt/proof package；
- Quant dataset/backtest package；
- ML experiment bundle；
- DL checkpoint/training bundle；
- Research Case/Pattern/Skill Candidate bundle。

最小字段：root manifest hash、成员路径/sha256/size/media type、DAG edges、schema/policy version、created_at、producer、excluded inventory、preflight result、receipt 自身 hash。receipt 必须最后生成；生成后任何成员字节变化都使其失效。

边界：closure receipt 只能证明“指定字节构成自洽闭包”，不能证明 proof 正确、数据无泄漏、收益可交易、模型泛化或 Skill 有效。语义 verdict 必须由独立 reviewer/report 另行给出。

### 5.10 Independent Semantic Review：精确候选的独立语义审查

适用于所有域的协议：

1. 绑定 exact candidate/receipt hash；
2. reviewer 不读取作者 verdict 或期望答案；
3. fresh context，从原始目标和获授权材料开始；
4. reviewer identity/principal 与 author 不得复用；
5. 预注册有限审查轮次；Math successor 可把三轮作为候选默认值，其他域按风险/成本另定，达到上限也不自动 PASS；
6. 修改候选会使旧 verdict 失效；
7. structural PASS 与 semantic PASS 分开记录；
8. 无法判断是 `HOLD/INCONCLUSIVE`，不能降格为 PASS。

领域 reviewer profile：

| 领域 | 独立审查核心 |
|---|---|
| Math | 逻辑正确性、量词/定义、依赖闭合、反例 |
| Quant | PIT、执行可达性、成本/容量、bias、经济解释边界 |
| ML | split/preprocessing/selection 泄漏、统计稳定性、generalization gaps |
| DL | ML 项 + 资源公平、checkpoint 选择、失败 seed、恢复与硬件边界 |

### 5.11 Audit Triad：三角色形态统一，问题领域化

建议三个独立视角：

1. **Coverage/Validity**：输入、依赖、样本/命题覆盖和遗漏；
2. **Soundness/Selection**：推理、统计、模型/路线选择与反事实；
3. **Reproducibility/Operations**：环境、资源、artifact、恢复和运行边界。

三角色不是三个相同 prompt。每个 Adapter 提供自己的 checklist、negative fixtures 和 `non_entailments` 规则；聚合器只负责 principal 分离、hash 绑定、状态合成和 blocker 传播。

### 5.12 Claim Obligation Graph：终局条件的领域化

Math 可以为精确命题建立“若这些可验证逻辑义务全部成立，则目标成立”的 sufficient-condition graph。经验领域只能建立：

- Claim 想达到某 maturity 需要哪些证据；
- 哪些 hard gate 会封顶/拒绝；
- 哪些 assessment 未执行；
- 哪些结论明确不能推出；
- 何时停止当前实验、重新定义 objective 或请求新数据。

Quant/ML/DL 的 obligation graph 完成只说明“满足当前预注册合同下的报告/晋级资格”，不说明策略赚钱、模型普遍有效或系统可生产使用。

### 5.13 Cheap Gates First：阶段化物化

全域统一顺序：

```text
P0 rights/privacy/scope
→ P1 schema/hash/reference closure
→ P2 domain static semantics
→ P3 cheap deterministic/mutation checks
→ P4 bounded runner
→ P5 independent semantic review
→ P6 package/publication materialization
```

前一阶段失败时，后续昂贵输出不得生成；尤其不能先训练/回测/打包，再补 objective、license 或 holdout 声明。每阶段记录 `not_run_because`，避免“缺报告”被误解为通过。

### 5.14 Support Matrix 单一事实源

外部包 `expected`/`verified` 冲突暴露了普遍风险。未来各域 support matrix 必须由一个机器可读源生成或校验：

- 状态封闭为 `verified`、`expected`、`unsupported`、`unknown`；
- `verified` 绑定 OS/runtime/hardware、commit、run、日期和结果；
- README、Release notes、报告和 manifest 不得手工维护互相独立的状态；
- 缺证据只能是 `expected/unknown`，不能因本机成功推断其他平台；
- contradiction meta-test 必须故意制造双状态并被杀死。

## 6. 模块落点与深模块纪律

| 模块 | 计划吸收 | 不吸收 |
|---|---|---|
| Core | 继续承载 task/hash/append-only/图验证；仅在两域证明后考虑通用 invalidation/receipt identity | 证明搜索、回测/训练状态、固定 attempt 数、领域 verdict |
| Math Adapter/Executor | objective 语义、exact-three、proof map、logic obligations、Math audit | Quant/ML/DL 字段 |
| Quant Adapter/Executor | PIT objective、bounded experiment portfolio、data/source invalidation、execution audit | 数学 sufficient condition |
| ML Adapter/Executor | experiment DAG、selection/holdout、bounded search、assessment gaps、semantic reviewer | 自动训练/真实泛化声明 |
| DL Adapter/Executor | resource/checkpoint/recovery、compute-matched audit、training context | 大型 checkpoint 进 Git |
| Research Memory | causal memory、derived map、ContextBundle、source impact view | 自动 route/promotion、权威状态机 |
| Evaluator | exact-hash semantic review、audit triad、claim obligation aggregation | 作者自证、通用 judge 替代 oracle |
| Skill Incubator | closure receipt、source/license Gate、fresh reviewer、bounded context | 复制无许可证 baseline、自动 canonical/install |
| Publication/Promotion | guarded commit、completion receipt、conditional rollback | 合并 publication/promotion/install/activation |

公共接口预算：实施前默认不新增 Core 公共操作，Adapter 仍保持三操作，Research Memory/Evaluator/Incubator/Publication 各自现有小接口保持不变。若私有实现无法在现有接口后隐藏，必须以调用方重复、信息泄漏和 deletion test 证明新 seam，而不是凭概念数量增加方法。

## 7. 与现有 Phase 的映射

### Phase 5（ML，已完成并发布为 `v0.6.0`）

Phase 5 已按 ADR-0008 独立完成 L1—L6；本计划没有进入其实现提交或 Release。可复用的现状观察仅限：

- experiment DAG 与 final-evaluation partition/split pin 提供 Objective/Lineage 的经验域证据；
- runner 使用已有 search/seed/resource budget 与四类 split assignment Gate，没有引入 Math exactly-three；
- Case Package、candidate Pattern 与 shadow Heuristic 仍停留在 engineering-only/shadow 边界；
- ML/Quant 重合分析没有发现满足两域 seam 与 module-depth Gate 的新 Core 下沉；
- ContextBundle、source invalidation、closure receipt、independent semantic review 与 v13 executor successor 均未实现；
- `v0.6.0` 的完成不能替代 v13 来源许可、ADR、两域实现或 deletion test，任何采用仍需后续独立裁决。

### Phase 6（DL）

- 证明 Objective Commitment 扩展到 hardware/runtime/compute/checkpoint；
- 证明 Authority/Execution Split 是否在训练恢复中有独立价值；
- 实现领域化 source invalidation 与 minimal-safe context fixture；
- 验证 bounded portfolio 的基数不能复用 Math exactly-three；
- 产出 Math/ML/DL 三域概念矩阵，但仍不自动下沉 Core。

### Phase 7（Skill Incubator）

- 引入 candidate Artifact Closure Receipt；
- 引入来源/许可 preflight 和失效依赖闭包；
- 引入 manifest 驱动 ContextBundle 与 omitted inventory；
- 引入 exact-candidate independent semantic review；
- 用两个 Adapter 实现执行 deletion test，裁定是否出现真正通用 seam；
- Phase 7 仍止于 `READY_FOR_PRIVATE_REVIEW`。

### Phase 8（Private/Hidden Evaluator）

- 将 receipt 后字节变更、stale source、reviewer principal 复用、support matrix 矛盾加入 fault injection；
- 验证派生 Map/Context 不泄漏 hidden 路线或答案；
- 独立区分 structural、semantic、private/hidden verdict；
- 验证 invalidation 能阻塞 publication/promotion 而不修改历史报告。

### Phase 9（生产接入）

- v8/1.0.1 baseline 只读；v13 仅作为独立 candidate baseline 登记；
- 通过 provenance、独立动态验收和 license Gate 后，才可设计 Math executor successor；
- 实现 authority/execution split、guarded head commit、conditional rollback；
- canonical publication 与 completion publication pair 分开；
- 安装、激活、Git Release 各自保持独立授权。

## 8. 建议实施层（未来，不在本轮执行）

### A0：来源与基线冻结

- 记录 v8 baseline、v13 artifact hash、文件清单、许可状态和不执行声明；
- 建立 byte pin 和差异分类；
- 出口：可证明没有用 v13 覆盖 v8，也没有复制无许可 payload。

### A1：跨领域吸收 ADR

- 决定术语、对象归属、接口预算、版本策略、错误/violation contract；
- 明确哪些是 derived object、哪些是 authority；
- 出口：ADR Accepted，不等于实现批准。

### A2：纯 fixture 概念矩阵

- 为 Math/Quant/ML/DL 构造 objective、bounded portfolio、causal memory、invalidation、context、receipt 的正/负例；
- 先不改 Core；以 Adapter test doubles 证明差异；
- 出口：至少两域消费者与 deletion test 证据。

### A3：派生认知层

- 实现可丢弃的 Program Map 与 ContextBundle；
- 测试 stale、omitted inventory、minimal-safe 和预算不足 fail closed；
- 出口：删除派生物不影响权威记录验证。

### A4：闭包与来源完整性

- 实现 closure receipt、post-receipt mutation kill、source events 与 impacted closure；
- 出口：结构完整性与语义 verdict 仍分离。

### A5：语义审核层

- 实现 reviewer principal 分离、exact hash 绑定、各域 audit triad；
- 出口：作者自检、旧 candidate verdict、通用 judge 均不能越权 PASS。

### A6：Math Executor successor

- 在独立协议版本实现 exact-three、authority/execution heads 与 guarded commit；
- v8 基线保持可回放；
- 出口：成功/崩溃/并发/rollback fault injection 全部通过。

### A7：跨域收口

- 选择至少一个经验域实现同形机制；
- 运行 seam/deletion test；
- 只把真实共享部分下沉；
- 出口：验收报告明确 adopted/deferred/rejected 与剩余边界。

## 9. 必须落地的 mutation 与故障注入

1. receipt 后修改任一成员 1 byte → receipt 失效；
2. manifest 漏成员、重复路径、DAG 成环或 receipt 非最后生成 → preflight 拒绝；
3. 来源状态改为 retracted/license_blocked → impacted Candidate publication 被阻塞，历史记录不变；
4. Map/Context 注入 route decision 或无 authority hash 的结论 → 派生层拒绝；
5. minimal-safe 删除 objective/holdout/PIT/invalidations 任一塑造字段 → fail closed；
6. reviewer 与 author principal 相同 → semantic review 无效；
7. candidate 字节变化后复用旧 semantic PASS → 拒绝；
8. structural PASS 单独尝试满足 semantic Gate → 拒绝；
9. Math audit 套到 Quant、或 Quant PIT audit 套到纯 Math → scope mismatch；
10. 把 exactly-three 应用于 ML/DL → contract test 拒绝全域固定基数；
11. support matrix 同一平台同时 `expected` 与 `verified` → meta-test 报矛盾；
12. P0 license/privacy 失败后仍生成昂贵 runner artifact → phase-order violation；
13. 并发 writer 在 conditional rollback 前已推进 head → rollback 不得覆盖新 head；
14. source invalidation 误推断“Claim 必为假” → 语义测试拒绝，只允许证据状态变化；
15. 删除候选通用模块后只有一个域受影响 → 不满足下沉 Core 的 deletion test。

## 10. 新 Core seam 的成立 Gate

候选概念必须同时满足：

1. 至少两个独立领域已有工作实现与消费者；
2. 字段语义相同，而非仅名字相似；
3. 放在 Adapter 会导致可量化的重复、不一致或权限泄漏；
4. 公共接口比隐藏复杂度小，且不暴露领域状态机；
5. 删除该通用模块会同时破坏两个领域的必要不变量；
6. 负例证明不会误吸 Math 专属/经验专属语义；
7. 兼容、迁移、failure/violation、并发和 rollback 合同完整；
8. ADR、schema successor、contract suite、mutation 和文档在同一交付层闭合。

未满足任一条：保留 Adapter/Executor 私有实现，不因“未来可能复用”提前抽象。

## 11. 明确拒绝或延期的设计

- 拒绝直接导入附件源码或把 v13 安装到当前 skill root；
- 拒绝用 v13 覆盖/重命名 v8 基线；
- 拒绝把 proof attempt 状态机放进 Core；
- 拒绝全领域固定三个 attempts/trials/models；
- 拒绝把 Research Map 当 Evidence、Router 或下一步动作授权；
- 拒绝用 closure receipt 证明数学/统计/市场结论；
- 拒绝把 empirical obligation graph 称为充分证明；
- 拒绝因单领域使用就新增 Core family/公共方法；
- 拒绝自动 canonical publication、安装、激活或 Champion promotion；
- 延期 vector database、复杂知识图谱与长期服务，直到 corpus/延迟/评测证明需要；
- 延期跨进程/分布式 CAS 到 Executor 原型证明单机模型不够之后；
- 延期真实 Quant/ML/DL 能力声明到各自数据、执行、holdout、资源和外部验证 Gate 通过之后。

## 12. 文档、ADR 与验收产物

未来实施至少需要：

- 一份跨领域吸收 ADR（编号在开工时按仓库现状分配）；
- 一份 Math Executor successor ADR；
- 概念矩阵与 adopted/deferred/rejected 决策表；
- source/provenance manifest；
- public fixtures 与 mutation receipts；
- independent semantic review reports；
- seam/deletion-test 报告；
- support matrix 单源及 contradiction test；
- phase acceptance report 与 rollback 说明。

任何计划条目只有在对应 ADR Accepted、实现提交、测试、独立审核和阶段验收全部完成后，才能从 `PLANNING_ONLY` 改成 implemented。

## 13. 开工前需用户逐项拍板

- [ ] 是否取得/确认 v13 的许可证与可重用范围；
- [ ] 是否接受“v8 不可变、v13 只作独立 candidate baseline”；
- [ ] 是否接受 exactly-three 只属于 Math，其他域采用有界但领域化组合；
- [ ] 是否接受 empirical domains 只使用 claim obligation graph，不使用“充分条件”表述；
- [ ] 是否接受新 Core seam 必须先有两域实现 + deletion test；
- [ ] 是否批准在 Phase 7 前只做 fixtures/ADR，不实现通用状态机；
- [ ] 是否批准未来单独分支、提交层与独立审核预算；
- [ ] 是否批准任何 actual write/commit/push/install/activation 的单独 Gate。

在上述决策获得批准前，本计划的唯一效果是提供可审计路线图，不改变项目能力或外部状态。
