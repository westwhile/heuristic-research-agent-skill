# ADR-0005：Adapter interface v1——seam 三类型、contract suite 与成立判据

- 状态：Accepted（Phase 2 第一层）
- 日期：2026-08-16
- 关联：ARCHITECTURE §4.2/§5、总体计划 Phase 2、ADR-0001（Core/Adapter 分层）、ADR-0003（记录模型与隐私边界）、ADR-0004（兼容政策）

## 背景

Phase 1 交付了领域中立内核：九个 v1 schema、25 种 violation 合同、append-only store、只读 CLI。架构 §4.2 冻结了 Domain Adapter seam 的三个职责（`normalize_task` / `validate_claim` / `build_evaluation_contract`）并规定"该 seam 只有在 Math 和 Quant 两个 Adapter 的 contract tests 同时通过后才视为成立"；总体计划 Phase 2 要求两个差异显著的真实 Adapter 各完成一条端到端垂直切片，**不允许只实现 Math 后宣称平台通用**；`schemas/adapters/README.md` 冻结"领域字段不得回流到 Core schema"；Core 的 `domain_context` 是唯一扩展点（内核只存储和哈希、从不解释，`core-interface.md` §3.1）。

Phase 2 落地上述边界：冻结 Adapter interface v1 并对 Math/Quant 各交付一条垂直切片。不实现完整 Evaluator（Phase 3 起）、ResearchPattern 蒸馏（Research Memory 模块）、ML/DL Adapter（Phase 5/6）。

## 决策

1. **seam 类型的归属与形态**：`DomainTask`、`ClaimAssessment`、`EvaluationContract` 是 **Adapter 层的冻结 v1 交换类型**，不是 Core 记录 family——不进 `_families.py` registry、不可发布到 Core store、不改变 `core.__all__`（仍 18 项，`PublicInterfaceTest` 钉选）。它们以 frozen dataclass 定义于 `research_evolution.adapters` 包（新的公共面，与 Core 公共面并列而非扩张之）；其 JSON 线形态由 `schemas/adapters/` 下的版本化 adapter schema（`domain-task/v1`、`claim-assessment/v1`、`evaluation-contract/v1`）冻结，由同一 Core schema 引擎校验（独立 schema_root）。理由：这三个类型是"领域语义进出 Core 的翻译合同"，不是 store 事实；store 事实仍是九个 Core family，领域内容经哈希绑定进入（决策 5）。

2. **三操作的签名与纯度纪律**（对齐架构 §4.2，补全参数与副作用纪律）：

   ```text
   normalize_task(domain_input) -> DomainTask
   validate_claim(claim, evidence, contract) -> ClaimAssessment
   build_evaluation_contract(case) -> EvaluationContract
   ```

   签名变更认领：架构 §4.2 原文为 `validate_claim(claim, evidence)`；v1 增补 `contract` 参数并记为 interface 变更理由之一——评估封顶与禁用通道来自 EvaluationContract，无此参数则决策 4/5 的纪律在签名层面不可执行。

   三个操作都是**纯函数**：无文件 I/O、无网络、无时钟/随机源读取（时间戳与随机性由调用方以参数注入）、同输入恒同输出。读取 archive/数据文件属于 importer/collector 层（决策 9），不在 seam 操作内。非法领域输入以 Adapter 层结构化错误（`AdapterError`，非 `CoreError` 子类）失败关闭——Adapter 的错误面与 Core 的错误面分列，互不冒充。

3. **DomainTask v1**：承载一次领域任务的规范化结果——`domain` 标签（`math`/`quant`）、`domain_schema_id`（输入载荷所符合的 adapter schema 版本引用）、`domain_payload`（已校验的领域输入）、以及映射产出的 Core `research-task/v1` 载荷草案。`DomainTask.to_core_task_payload() -> dict` 产出可直接交给 `load_record`/`publish_record` 的字典，其中领域细节只进入 `domain` 标签与 `domain_context`（Core 从不解释）。**Adapter → Core 只有这一个方向**；Core 类型不出现在 Adapter 的判定逻辑里（Adapter 可以构造 Core 载荷，但不得读取 store、不得调用 verify 来"自查"——验证是 Core 的事）。

4. **ClaimAssessment v1**：对一条领域 claim 载荷与一组证据载荷的**领域评估建议**——建议的 `claim_type`（七治理值之一）、建议的 `disposition`、证据成熟度**上限**（非授予值）、逐条理由、触发的领域规则清单。关键纪律：assessment 是建议而非事实签发——晋级仍由 Core 的证据绑定（`x-conditional-min-items`）与治理阶梯裁决，Adapter 永不直接写 Core 记录、永不自封成熟度。两个领域的封顶规则（计划验收 Gate 的落地）：
   - Math：纯数值/计算证据（数值验证、随机采样、符号代入）在缺少证明证书类证据时，成熟度上限为 `engineering_verified`——**数值证据不得冒充全局证明**；只有证明证书/形式化核查类证据才能把 `mathematical_claim` 抬到 `mathematically_verified`；
   - Quant：合成或 sample 数据的产出上限为 `data_accepted`——不得晋级 `empirically_supported` 及以上；`production_observed` 不由 Adapter 评估授予（属真实部署观察，超出 Adapter 职权）。

5. **EvaluationContract v1**：从 case 载荷推导的领域评测合同——该 case 中各 claim 晋级所需的证据类别与梯级、**禁用通道**（Math：纯数值外推不得充当证明；Quant：未来函数、非 PIT 数据、无前导对齐的 label 一律不得作为证据）、case-specific 检查点清单。合同内容哈希可经 Core evidence 的 `inputs`（`kind="config"`，sha256 必填）进入留痕，使"按什么合同评的"可审计；合同本身是交换类型，不入 store（决策 1）。

6. **Contract suite 机制**：`tests/adapter_contract/` 放置**单一参数化套件**——同一组测试对两个 Adapter 实例各跑一遍（`unittest` 子测试按 adapter 参数化），覆盖：三操作签名与返回类型、纯度（同输入双跑字节一致、快照零副作用）、错误纪律（非法输入结构化失败而非裸异常）、assessment 封顶规则、contract 禁用通道枚举完整。**seam 成立判据**（架构 §4.2 的可操作化，三项同时满足）：① 两个 Adapter 同时通过同一套件；② Core 无领域专用条件分支（静态扫描：`src/research_evolution/core/` 无 adapters import、无领域词汇，复用并扩展现有领域中性扫描）；③ 删除测试通过（决策 8）。只通过一个 Adapter 不构成 seam 证据。

7. **领域映射表冻结**：Math——`proof / disproof / partial / inconclusive` 映射为 `mathematical_claim` 的 disposition 语义（partial/inconclusive 是合法终态，不得强行归入证明成立/否证）；量词、对象域、假设、failed step、non-entailment、reopen condition 映射进 Core claim 的 `statement`/`scope`/`limitations`/`non_entailments` 与 FailureObservation/FailureAnalysis 链。Quant——工程/数据验收/样本外实证/真实市场四级 Gate 分别对应 `engineering_claim`（`engineering_verified` 封顶）、`data_claim`（`data_accepted` 封顶）、`empirical_claim` / `predictive_claim`（`empirically_supported` 需真实数据 + 冻结留出协议）、`strategy_claim`（production 纪律）；成本、停牌、涨跌停、流动性与基准口径检查属数据/实证合同内容（决策 5 的禁用通道与检查点），不是 Core 概念。

8. **删除测试（seam 不泄漏的可执行证明）**：contract suite 含两项静态/动态探针——(a) 静态：`src/research_evolution/core/` 全文扫描无 `adapters` import、无领域词汇命中（与 schema 领域中性扫描同一 `_BANNED_TERMS` 纪律扩展至 Core 源码）；(b) 动态：以子进程在 `sys.path` 剔除 adapters 包的形态下跑 Core 全套测试，零修改通过——删除 Adapter 后 Core 行为不变，领域复杂度未回流。既有 Core 套件（296 项）本身在 Adapter 落地前后必须字节级零修改通过。

9. **Importer 合同（零写入证据）**：Math importer 以只读方式打开 math-research-solve archive，导入前后对源树做全量哈希快照比对——**快照不变即零写入证据**；导入的每个源工件以其内容哈希绑定进对应 Core 记录的 inputs，使导入事实可追溯。真实 legacy archive 缺席时按基线先例处理（`reports/baseline/math-research-solve-1.0.1.md`）：不用合成文件伪造真实导入验收，contract suite 与垂直切片使用明确标记的合成 archive fixtures，真实 archive 导入属条件能力。Quant 侧无 legacy importer——合成/脱敏数据生成器是测试资产；**禁止**现有真实项目的私有数据直接进入公开 benchmark（计划 Gate）。

10. **版本化与演进**：Adapter interface v1 在整合 PR 冻结（计划 Git Gate：Math 与 Quant 可分 PR，interface 冻结必须在整合 PR 完成）；冻结后修改走 v2 新类型/新 adapter schema（与 ADR-0004 兼容政策同一判据：无兼容模式 flag，同一版本号永不承载双语义），旧 Adapter 不静默破坏；ML/DL 接入前（Phase 5/6 之前）允许以新 ADR 修改未冻结部分。

11. **非目标（本 Phase 不交付）**：完整 Evaluator 实现与 L0/L1 公开评测（Phase 3 起）；ResearchPattern 蒸馏与检索（Research Memory 模块）；ML/DL Adapter（Phase 5/6）；embedding/向量检索；任何真实私有数据进入仓库或公开 benchmark；Adapter 直接写 Core store 的通道。

## 后果

优点：

- seam 成立从口号变为三项可执行判据（双 Adapter 同套件、Core 静态纯净、删除测试），单领域实现无法冒充通用性证明；
- Adapter 错误面与 Core 错误面分列、assessment 只建议不签发，Core 的 18 项公共面与 25 种 violation 合同零扩张；
- importer 的哈希快照纪律把"只读导入"变成可出示证据，legacy 缺席不阻塞 seam 验证；
- 架构 §4.2 的三职责补全纯度与参数纪律后，未来 ML/DL Adapter 的接入成本可预期。

代价：

- 三个 seam 类型与三个 adapter schema 是一组新的冻结面，需要与 Core 同级的合同测试维护；
- 成熟度封顶规则把部分领域判断硬编码进 Adapter 合同（可接受：它们是计划验收 Gate 的原文落地）；
- 真实 legacy archive 导入与真实量化数据验收被推为条件能力，Phase 2 的垂直切片证据均为合成/脱敏级。

## 拒绝的方案

1. **seam 类型注册为 Core 记录 family**：它们不是 store 事实而是翻译合同；注册会扩张刚冻结的内核面（ADR-0004 决策 7 后任何扩张都要 successor 义务），且把领域交换语义引入 append-only 事实层，方向错误。
2. **只实现 Math 即冻结 interface**：架构 §4.2 与计划均禁止——单领域无法暴露"为适配第二领域而必须修改 interface"的全部理由，冻结会变成伪冻结。
3. **Adapter 直接发布 Core 记录或直接读 store 自查**：Adapter 只产出载荷与建议；写 store 是调用方（未来的 runner/Evaluator）经 Core 公共 API 的事。Adapter 持写通道会把评估权与事实权混淆。
4. **在 Core 内为领域特例加条件分支**（如 claim schema 认识 `proof` 一词）：直接违反 schemas/adapters 的冻结边界与 Phase 1 的领域中性扫描纪律。
5. **importer 复制 archive 进仓库后改写**：复制即失真且可能夹带私有内容；哈希快照 + 内容哈希绑定提供同等可追溯性而不复制字节。
6. **contract suite 为每个 Adapter 各写一份**：两份套件会在维护中漂移，"同一套件双跑"才构成同一合同的证据。
