# ADR-0008：ML Adapter——数据合同、声明式泄漏检查与确定性实验 runner

- 状态：Accepted（Phase 5 第一层）
- 日期：2026-08-18
- 关联：ARCHITECTURE §4.2/§5.3、总体计划 Phase 5、ADR-0001（Core/Adapter 分层）、ADR-0004（兼容政策）、ADR-0005（Adapter interface v1 冻结）、ADR-0006（评测记录与 runner 先例）、ADR-0007（研究记忆与 shadow 边界）

## 背景

Phase 2 冻结了 Adapter interface v1：三 seam 操作（`normalize_task`/`validate_claim`/`build_evaluation_contract`）为纯函数，seam 三类型是 Adapter 层交换合同而非 Core family，领域内容只经哈希绑定进入 Core 留痕（ADR-0005 决策 1/2/5/10）。Phase 3 交付了确定性离线 replay runner 与评测纪律（ADR-0006）；Phase 4 交付了研究记忆与 shadow 上限（ADR-0007，最高态 active Pattern + shadow Heuristic）。

总体计划 Phase 5 要求：ML 领域记录（dataset/split/preprocessing/feature/model/metric/selection，任务 1）、四类 validation contract（IID/group/time-series/nested，任务 2）、泄漏与 holdout 用途检查（任务 3/4）、baseline/resource parity 与种子重复（任务 5/6）、calibration/subgroup/OOD/drift 评估支持（任务 7）、模型选择与最终报告分离（任务 8）、15–25 个公开/合成 cases 与两条垂直切片（任务 9/10）、ML 与 Quant 重合逻辑比较并下沉 Core（任务 11）、ML heuristic shadow cases（任务 12）、ML 实验 Case Package 采集（任务 13）。架构 §5.3 冻结了 ML Adapter 的六项领域职责（含"不用测试集选择最终模型"）。

两项塑造性事实：

1. **Quant 先例的边界**：Phase 2 的泄漏/PIT 纪律是**声明式**的——禁用通道 + 证据双词表 + 成熟度封顶，Adapter 纯度纪律禁止其触碰数据本身（ADR-0005 决策 2；`quant/adapter.py` 无任何可执行数据检查）。Phase 5 任务 3/4 要求的"检查泄漏/用途"必须在这一边界内找到可执行形态，或显式扩张边界。
2. **Runner 的归属**：Git Gate 要求"数据合同、泄漏检查、runner、cases 分提交"，但 interface v1 三操作无 runner 职责；Phase 3 的 replay runner 是 evaluation 包的确定性离线机器（调用方做 I/O、runner 纯内存），这是本 Phase runner 的形态先例。

## 决策

1. **ML 领域记录全部留在 Adapter 层，零新 Core family**（任务 1；ADR-0005 决策 1 同判据）：dataset/split/preprocessing/feature/model/metric/selection 是 ML 领域语义，不是跨领域交换合同——它们以四个新 adapter schema 承载（`ml-task/v1`、`ml-case/v1`、`ml-claim/v1`、`ml-evidence/v1`，对照 math/quant 各四个的既有布局），由同一 Core schema 引擎在独立 `schemas/adapters/` root 下校验，不可发布入 store；进入 Core 留痕只经既有哈希绑定通道（evidence `inputs`，`kind="config"`/`"data"`）。Core 保持 17 family、`core.__all__` 18 项不动。拒绝项见"拒绝的方案 1"。

2. **Interface v1 原样遵守，不触发 v2**（ADR-0005 决策 10）：ML Adapter 实现既有三操作签名，不请求任何 interface 变更；若实现期发现 v1 无法承载的真实需求，回本 ADR 增补并启动 v2 successor 义务（ADR-0004 政策），不静默绕过。seam 对第三领域的成立证据 = ML 加入**同一参数化 contract suite**（ADR-0005 决策 6 的三判据原样适用：同套件通过、Core 静态纯净、删除测试通过——删除分区随之扩展）。

3. **泄漏检查 = 对"已声明实验拓扑"的确定性结构检查**（任务 3/4；塑造事实 1 的边界内可执行形态）：Adapter 永不读取数据；它检查**声明载荷**中的结构化字段——split 声明（kind: `iid`/`group`/`time_series`/`nested`，group 键、时间序 gap/embargo、嵌套内外层）、preprocessing 声明（每步的 `fit_scope`：`train_only`/`full_data`/`per_fold`）、采样/重采样声明（oversampling/undersampling/合成少数类等手段及其 `scope`：`train_only`/`per_fold`/`full_data`/`pre_split`——**schema 层允许声明不安全值**，语义层拒绝；`scope` 必填，缺省在 schema 层即拒，fail-closed）、特征选择与 target encoding 声明（fold 内/外）、tuning 声明（搜索空间、所用 split、重复种子数）。泄漏判定是这些声明上的确定性规则：fit_scope=`full_data` 且先于 split → 泄漏；采样 `scope` 为 `full_data` 或 `pre_split` → 泄漏（任务 3 的采样泄漏条款）；target encoding 未声明 per-fold → 泄漏；tuning 引用 test/future holdout → 违规（gate：test/holdout 不参与调参）；selection record 引用 test 指标 → 违规（gate：不用测试集选择最终模型；任务 8）。**scope 标签与 DAG 位置的一致性规则**（scope 与上游 pin 是两个声明面，必须互证而非任信其一）：声明 `train_only`/`per_fold` 的采样或预处理节点，其 `input_sha256` 必须指向对应 split/fold 的输出 pin；`input_sha256` 指向 dataset 或任何 pre-split 节点时按 scope 标签分流判定：节点声明的 scope 本身是 `full_data`/`pre_split` 的，由**直接 scope 规则**拒绝（不安全声明值本身即泄漏）；仅当节点声明安全标签 `train_only`/`per_fold` 而上游 pin 指向 dataset/pre-split 输出时，由**一致性规则**判拓扑不一致（语义违规，防止"安全标签 + split 前上游"的假 PASS）——每条不安全 fixture 只被一条规则拒绝，两规则职责不重叠（R42 对原句内部冲突的裁定，见增补 A2）。**可 mutation 性是合同的一部分**：每条语义泄漏规则（含一致性规则）的不安全正例必须**schema 合法**、仅被该语义规则拒绝——删除规则的 mutation 必须使正例假 PASS，此为 L3 测试义务（安全值白名单式的 schema 会把正例在结构层杀掉，使语义规则不可证伪——故 scope 枚举含不安全值）。**声明即证据下限**：未声明的维度按 fail-closed 视为不满足合同，而非静默放行——与 Quant"缺席 PIT 政策即无法排除泄漏"（`quant-task/v1` 设计注记）同一判据。拓扑声明的可重现性（gate：split 和 preprocessing lineage 可重现）：每个声明段以 `{identity, sha256}` 钉定自身版本，并携带**上游 pin（`input_sha256`）**——split→dataset、preprocessing/sampling→其上游（dataset 或 split 输出）、selection→上游阶段输出——声明间构成显式有向无环引用，lineage 由该 DAG 重建而非仅版本同一；同 identity 必同哈希，修订即新声明版本；引用成环 = 拓扑非法（确定性检查）。数据级可执行验证由决策 5 的 runner 在合成 fixture 上承担。

4. **成熟度封顶与 claim 映射**（计划验收 Gate 的落地，ADR-0005 决策 4 先例）：ML claim 映射治理词表——`engineering_claim`（工程正确性，`engineering_verified` 封顶）、`data_claim`（数据验收，`data_accepted` 封顶）、`empirical_claim`/`predictive_claim`（样本外泛化，`empirically_supported` 需真实或公开数据 + 冻结留出 + 重复种子）。封顶规则（`validate_claim` 输出上限、非授予值）：
   - 全合成证据上限 `data_accepted`（合成不得冒充真实发现，Quant 同则）；
   - 单 seed 结果上限 `engineering_verified`——**单 seed 最佳值不能支撑稳定 Claim**（gate 原文），`empirically_supported` 要求多 seed 聚合证据（任务 6）；
   - 缺少 OOD/subgroup 评估**不下压成熟度封顶**（gate 原文：缺失时报告限制，不补造结论）——限制句写入 `ml-claim/v1` 的 limitations 字段与报告层 limitations 面，`validate_claim` 经 `reasons`/`triggered_rules` 点名而**不动 `evidence_maturity_ceiling`**；calibration/drift 缺失同路如实标注"未评估"；
   - 任务 7 四类评估的承载面（本 Phase 对"支持"的落法，与声明式检查同一哲学）：**声明与结果落 `ml-case/v1` 的 assessment 声明段（calibration 校准方法、subgroup 分组键、OOD 探针、drift 检测的声明）与 `ml-evidence/v1` 的评估结果记录（四类结果各为一条评估证据）**——字段承载与留痕即支持，检测执行属 runner 合成 fixture 与显式非目标的真实执行。**`claim-assessment/v1` 冻结面零触碰**：`validate_claim` 的判断只经既有五字段表达（`suggested_claim_type`/`suggested_disposition`/`evidence_maturity_ceiling`/`reasons`/`triggered_rules`——如缺 OOD/subgroup 时经 `reasons`/`triggered_rules` 点名，**不动 `evidence_maturity_ceiling`**），不新增 assessment/limitations 字段；若实现期证成需要字段扩张，只能走决策 2 的 v2 successor 路径，本 Phase 不触发。限制句落 **`ml-claim/v1` 的 limitations 字段与报告层 limitations 面**（ADR-0006 决策 7 先例的机器半自动句）：OOD/subgroup 缺失必写（上条规则），calibration/drift 缺失如实标注"未评估"，不补造。

5. **确定性合成实验 runner**（Git Gate 的 runner 提交项；塑造事实 2）：`adapters/ml/runner.py` 为**纯函数机器**——输入为内存中的合成数据集载荷与实验合同（ml-case），输出为结果载荷（指标、逐 seed 重复、parity 对照）；无 I/O、无时钟、随机性由种子参数注入（ADR-0005 决策 2 纯度纪律原样延伸；I/O 属调用方/测试）。实现只用 Python 标准库（闭式/迭代式小算法），**不引入 numpy 等第三方依赖**——仓库保持零依赖纪律，合成 fixture 的规模本就不需要数值库。runner 的职责是产生任务 5/6 的证据形态：baseline parity（同数据同预算下基线与候选的确定性对照）、resource parity（step/样本预算声明与实测）、seed 重复研究（均值/方差/区间而非 best-only）。分层归因纪律（gate：模型/资源变更与 Heuristic 变更分层）：每次 parity 对照一次只变更一个轴（模型、资源预算、seed 集、heuristic 集四轴之一），其余轴冻结并随 runner 输出留痕；Heuristic 变更永不与模型/资源变更混入同一次对照。

6. **Case 采集与 heuristic shadow 复用 Phase 4 机器，零改动**（任务 12/13；ADR-0007 决策 12 先例）：ML 实验的协议、负结果、泄漏修复与复现差异经 `capture_case` 采为 `research-case-package/v2`；跨案例稳定模式经 `distill_patterns` 进 Pattern Registry（单例天花板与晋级纪律原样）；ML heuristic 走 `propose_heuristic`→shadow runner（3–8 条、只记假设性决策、上限 shadow）。证据落 `staging/research-memory/` 既有隔离暂存区（layout 合同不变），全合成标注。

7. **ML/Quant 重合逻辑的下沉判据**（任务 11）：重合分析作为验收报告的一节交付；**下沉 Core 的判据**=同时满足 ①逻辑无任何领域词汇（过 `_BANNED_TERMS` 纪律）、②两个 Adapter 以相同语义调用、③有双领域合同测试钉选。满足才以下沉 commit 进行（Core 公共面任何扩张走既有钉选与合同测试更新）；不满足或只单领域需要，留在 Adapter。本 ADR 不预定任何下沉结论——分析先于动作。

8. **15–25 公开/合成 cases 与两条垂直切片**（任务 9/10）：全部合成/脱敏并如实标注（ADR-0005 决策 9 先例），零真实私有数据。cases 覆盖：IID 与 group 与 time-series split、六类泄漏 fixture（fit-before-split、sampling-out-of-scope（`scope` 声明为 `full_data`/`pre_split`）、scope-upstream-mismatch（安全标签 `train_only`/`per_fold` + 指向 dataset/pre-split 的错误 `input_sha256`）、target-encoding 出 fold、tuning-on-test、selection-on-test——**每类至少一个正例被拒、一个负例通过；正例一律 schema 合法、仅被语义规则拒绝，mutation 测试必须证明删除对应语义判定会使正例假 PASS**，L3 Gate 逐类覆盖含采样与一致性）、seed 重复、baseline parity、OOD/subgroup 缺失时的限制报告。两条垂直切片：一条非时间序列（表格型合成实验端到端）、一条时间序列（带 gap/embargo 声明的端到端），各走 domain payload → `normalize_task` → Core task → contract → claim assessment → runner 证据链（Phase 2 垂直切片先例）。

9. **模型选择与最终报告分离**（任务 8）：selection record 是 ml-case 内的独立声明段（`selection`：所用 split、指标、搜索预算、seed 集），与最终报告证据（test/holdout 指标）分字段承载；合同检查禁止二者引用同一 split（决策 3 的规则面）。报告文案纪律复用 evaluation 包的 limitations 半自动机制（ADR-0006 决策 7 先例）：小样本/单 seed/缺 OOD 的限制句由机器半自动生成，结论由人给。

10. **切片与 Git Gate 映射**：L1 = 本 ADR（+根 README 索引行）；L2 = 数据合同（四 ml-* schema + fixtures + Adapter 三操作实现 + contract suite 注册 ML harness）；L3 = 泄漏检查（决策 3 的规则面，含 leakage fixture 正负例；决策 4 的封顶已在 L2 落地——A5 修订）；L4 = runner（决策 5 + parity/seed 研究）；L5 = cases + 双垂直切片 + leakage fixture 报告 + 重复实验报告；L6 = ML shadow cases + case packages + ML/Quant 重合分析（决策 7）+ 验收报告 → v0.6.0。每层验收含全量套件双环境绿——**原有 Math/Quant 测试零 critical regression** 是 L2–L6 的逐层验收账本项（gate 原文），非仅终验义务。分支 `feat/ml-adapter`；数据合同、泄漏检查、runner、cases 分提交（Git Gate 原文）；PR 附重复实验与 leakage fixture 报告；annotated tag `v0.6.0`。

11. **非目标（本 Phase 不交付）**：DL 扩展（Phase 6：checkpoint/硬件/算力治理）；真实数据集接入与真实训练执行；超参优化执行器（平台检查纪律，不执行真实训练）；embedding/向量检索；任何真实私有数据入仓；新 Core family；Adapter interface v2（除非决策 2 的增补路径被触发）；`evaluation-run/v2`（backlog 任务 21，独立评估）。

## 后果

优点：

- 泄漏/调参纪律获得**可执行**形态而不破坏 Adapter 纯度——结构检查作用于声明载荷，数据级验证由纯 runner 在合成 fixture 承担，边界声明诚实；
- "声明即证据下限"把四类 validation contract 与 holdout 纪律变成 fail-closed 合同，单 seed 封顶直接落实验收 Gate 原文；
- 零新 Core family、零 interface 变更、零第三方依赖——三个冻结面全部不动，Phase 5 的增量全部可回滚；
- runner 与 evaluation 包形态对齐（纯内存、调用方 I/O），未来 DL 的算力治理有同一先例可循。

代价：

- 结构检查只能验证"声明了什么"，声明与真实代码的偏离超出本 Phase 职权（与 Quant 声明式 PIT 同级诚实；runner 的合成证据缓解但不消除）；
- 四个新 adapter schema 是新的冻结面，合同测试维护面随之扩大；
- 标准库自实现的小算法只服务合成 fixture，不构成真实 ML 能力声明（与"平台检查纪律、不执行真实训练"的非目标一致）。

## 拒绝的方案

1. **ML 记录注册为 Core family**：领域语义入 append-only 事实层方向错误（ADR-0005 拒绝项 1 同判据）；17 family 面保持。
2. **Adapter 内做数据级泄漏检查**（读取真实数据文件）：违反纯度纪律（ADR-0005 决策 2），且把 importer/runner 职责混进 seam。
3. **引入 numpy/pandas 跑"更真"的合成实验**：破坏零依赖纪律，合成 fixture 的判定力不依赖数值库；真实数值能力属 Phase 6+ 的显式决策。
4. **为 ML 修改 interface v1**（如加第四个 seam 操作）：冻结面只在真实需求证成后经 v2 successor 演进；当前三操作足以承载（决策 2）。
5. **重合逻辑预先下沉 Core**（先下沉后验证）：无第二领域同语义调用证据的下沉是投机抽象；判据先行（决策 7）。
6. **ML shadow cases 落 store 新 family**：ADR-0007 决策 8 已定 shadow report 是暂存区 artifact 而非 Core family，本 Phase 沿用，不为 ML 单开记录面。

## 增补 A1（2026-08-18，L2 实现期）：决策 2 逃逸舱触发——`domain-task/v2`

**发现**：`domain-task/v1` 的 `domain` 字段是封闭枚举 `["math", "quant"]`，其 description 自述"Frozen to the two v1 domains; a third domain requires a new adapter schema version (ADR-0005 decision 10)"。L1 起草时未核到这一处（本 ADR 决策 2 只核对了三操作签名与 exchange 类型结构），L2 实现 `normalize_task` 时被 seam 校验拒绝而暴露。

**裁定**（按决策 2 预定路径执行，提交 R42 审核）：这正是决策 2 的"实现期发现 v1 无法承载的真实需求"情形，但该需求**不要求 interface v2**——三操作签名与 exchange 类型结构零变更，需要的只是 seam schema 的版本演进，恰为 v1 description 与 ADR-0005 决策 10 预设的通道。处置：

1. 新增 `domain-task/v2`（domain 枚举 `["math", "quant", "ml"]`，仍封闭；第四领域走下一版本），v1 字节零改动、保持冻结并对 math/quant 生产者继续有效——无迁移义务，两版本并行有效；
2. `types.py` 的 `DomainTask` 接受且仅接受 v1/v2 两个 live 版本（`_load_seam_record_one_of` 收紧列举，未知未来版本 fail-closed）；`ClaimAssessment`/`EvaluationContract` 仍只接受 v1；
3. ML Adapter 的 `normalize_task` 产出 `domain-task/v2`；Math/Quant Adapter 零改动；
4. 本条构成决策 2 的 v2 successor 义务履行记录：无静默绕过（schema 层强制），无 interface 变更，演进面以合同测试钉选（registry 恰 16 schema、v2 fixtures、membership pin）。

## 增补 A2（2026-08-19，R42 驱动）：声明面补齐与成熟度驱动收窄

R42 审核在 L2 首版裁定 5 项 P1 与 4 项 P2；本增补记录其处置，全部经 R42b 回归测试钉选（`tests/unit/test_ml_adapter.py` 的 R42b 回归类）：

1. **assessment 声明面落地**（决策 4 原承诺的实现遗漏）：`ml-case/v1` 新增必填 `assessment` 段——calibration（校准方法 `method`）/subgroup（分组键 `group_key`）/ood（探针 `probe`）/drift（检测 `method`）四键必填，各含 `status ∈ {declared, not_performed}` 与可选细节字段；四键必填使沉默不可能（声明即证据下限）。"declared 必有细节"与声明↔结果比对属 L3 语义层义务，schema 层不设条件关键字。
2. **成熟度只由 `experiment_run` 驱动**：四类 assessment 证据只进 gap 点名集，不再充当主实验证据（R42 实测：单份 `ood_assessment` 曾把 generalization 抬到 empirically_supported 的假 PASS 已关闭）；多 seed 判定改为**唯一 seed 计数**（`seeds=[7,7]` 不再冒充重复实验）；并发违规各自独立记账、取最严 ceiling（single-seed + unfrozen 同时记 `single-seed-cap` 与 `frozen-holdout-missing`，违反账本完整性的 if/elif 封顶链已拆除）。
3. **研究绑定 fail-closed + 支撑矩阵**：`ml-evidence/v1` 新增必填 `study_id`；claim 与任一 evidence 的 `study_id` 不等即 AdapterError。case↔claim 绑定经 contract 的 `case_sha256` 哈希承担，**同研究输入由调用方保证**——adapter 见不到 case 的 `study_id`（冻结的 `evaluation-contract/v1` 无此字段），此信任边界在此明示。claim class → 支撑 evidence kind 矩阵：engineering ← {unit_test_run, experiment_run}，data_acceptance ← {data_audit_report}，generalization ← experiment_run 封顶路径；`other` 永不支撑；pass + 有证据但无支撑 kind → inconclusive + `no-supporting-evidence`（`data_audit_report` 词表从此承重）。
4. **generalization 收窄为 empirical-only**：实现期确认 `predictive_claim` 在 v1 词表下无可达生成路径（无 empirical/predictive 判别字段），按"收窄而非保留死路径"处置——`_ML_CLAIM_TYPES` 移除 `predictive_claim`（contract 中的 predictive_claim 条目变为非本族条目静默跳过，与 mathematical_claim 同路），ml-claim/ml-case schema description 同步收窄；真出现 empirical/predictive 区分需求时走显式 subtype 的演进路径（ADR-0004 政策）。
5. **limitations 路由承重**：gap 点名去掉"有证据才点名"门槛（无证据同样点名四缺口）；generalization claim 在任一 gap 规则触发时声明空 `limitations` 数组 → AdapterError fail-closed（"无限制"声明与已检出缺口矛盾，机器可判定范围内闭合）。
6. **决策 3 正文修正**（R42 P2-1）：scope/DAG 一致性段原句"指向 dataset 无论 scope 标签如何均违规"与"每条 unsafe fixture 只被一条规则拒绝"不能同立；正文已改为分流表述（直接 scope 规则管 `full_data`/`pre_split` 声明值；一致性规则只管安全标签 `train_only`/`per_fold` + 错误上游 pin）。
7. **L3 落点裁定备案**（R42）：泄漏拓扑检查落在 `build_evaluation_contract` 内部私有深实现——它是唯一消费 ml-case 的公共操作，可一次封装 DAG/scope/kind-specific parameters/mutation 规则而不新增第四个浅公共操作。

## 增补 A3（2026-08-19，R42b 驱动）：绑定面落地与 disposition 双向承重

R42b 审核裁定 4 项 P1，本增补记录处置，全部经 R42c 回归测试钉选（`tests/unit/test_ml_adapter.py` 的 R42c 回归类）。A2 第 3 条的"case↔claim 绑定由调用方保证"信任边界由本条第 2 项升级为结构绑定。

1. **承载面：`evaluation-contract/v2`**（决策 2 预定通道第二次触发，A1 同路径；不触发 interface v2——三操作签名与类型身份零变更，仅 seam schema 版本演进）：v2 新增 `study_id` 与 `assessment_declaration` 两个结构字段；seam 层面保持领域中立——dimension 是自由字符串，schema 不固定任何领域词表。v1 字节冻结、对 math/quant 生产者继续有效（`EvaluationContract` 接受且仅接受 v1/v2，未知未来版本 fail-closed）。ML Adapter 的 `build_evaluation_contract` 产出 v2——case 的 assessment 声明段随 contract 抵达 `validate_claim`，L3 声明↔结果比对由此获得可实现的数据通道；`validate_claim` 对非 v2 contract fail-closed。
2. **三方绑定 fail-closed**：`ml-claim/v1` 新增必填 `case_sha256`；claim.case_sha256 ≠ contract.case_sha256、claim.study_id ≠ contract.study_id、evidence.study_id ≠ claim.study_id（A2 已有）三向任一不等即 AdapterError。R42b 探针（foreign claim + foreign evidence + 原 case contract → supported）由此关闭。
3. **声明↔结果正反比对**：contract 携带的 assessment_declaration 与 evidence 实际 kind 集比对——declared + 结果缺失 = gap（点名，规则同前）；not_performed + 证据在场 = 声明被推翻，AdapterError fail-closed；declared + 在场 = 一致。携带本 adapter 不可解释 dimension 的 contract fail-closed。
4. **逐 gap 承重的 limitations 通道**：`ml-claim/v1` 新增必填 `declared_assessment_gaps`（四 dimension 枚举数组）；generalization claim 的检出 gap 集必须是其声明集的子集，缺任一即 AdapterError（每维独立 mutation 钉选）；A2 的空 limitations 拒绝保留。R42b 探针（任意非空 limitation 句绕过四 gap）由此关闭。prose limitations 仍是报告层义务（ADR-0006 决策 7 机制不变）。
5. **disposition 双向承重**：`_SUPPORTING_KINDS` 更名并扩为 `_RELEVANT_KINDS`（engineering ← {unit_test_run, experiment_run}、data_acceptance ← {data_audit_report}、generalization ← {experiment_run}）；`fail` 方向同样要求 relevant evidence，否则 inconclusive + `no-relevant-evidence`（规则更名自 A2 的 `no-supporting-evidence`，语义覆盖正反两向）；`other` 与四类 assessment kind 永不产生终局 disposition。R42b 三条 fail 探针（data/engineering + other、generalization + 仅 assessment）由此关闭。
6. **contract 适用性 fail-closed**：`validate_claim` 要求当前 suggested claim type 恰有一个适用 bar——零匹配（含 foreign-only contract，如 predictive_claim-only）与重复匹配均 AdapterError；`build_evaluation_contract` 侧继续按 claim_type 去重。R42b 两条探针（无 generalization gate 的 contract、predictive-only contract 均返回 supported）由此关闭。

## 增补 A4（2026-08-20，R42c 驱动）：声明完备性闸与封顶约束全独立记账

R42c 审核裁定 2 项 P1，本增补记录处置，全部经 R42d 回归测试钉选（`tests/unit/test_ml_adapter.py` 的 R42d 回归类）。

1. **声明完备性由 adapter 强制**：v2 schema 保持领域中立（`dimension` 自由串、无 minItems），因此 "calibration/subgroup/ood/drift 四维恰好各出现一次" 的下限在 `MLAdapter` 私有实现强制——`_require_complete_assessment_declaration` 同时钉在两个入口：`build_evaluation_contract`（防 ml-case schema 未来漂移的绊线；当前 schema 已要求恰四键且 additionalProperties=false）与 `validate_claim`（手写 contract 的空/子集/重复/未知 dimension 声明一律 AdapterError，先于一切 claim 绑定检查）。R42c 探针（空声明仍 supported、只声明 calibration 使其余三个 gap 从账本消失）由此关闭；A3 第 3 条循环内的未知 dimension 拒止被本闸覆盖（消息并入完备性错误）。诊断纪律（R42d/R42e 复审）：单遍实现、计数快速拒绝先行，重复/未知维度只报数量与截断预览（`_preview`），调用方自由字符串永不完整回显进错误文本。
2. **封顶三约束去嵌套、真空记录**：provenance（synthetic-evidence-cap）、唯一 seed 数（single-seed-cap）、frozen holdout（frozen-holdout-missing）是对 public/real 实验记录的三个独立谓词，不再嵌于 provenance 的 else 分支——无 eligible 实验时 seed/holdout 约束真空成立并照常登记，最严者（engineering_verified）胜出。行为变化（全部向更严方向，经 R42c 裁定认可）：synthetic-only、纯支撑 kind、纯 assessment、零证据四类 generalization 场景的 ceiling 由 data_accepted 降为 engineering_verified（合同 suite probe 与三处既有测试期望同步翻转并在提交包列名）。R42c 探针（synthetic + 单 seed + unfrozen 只登记 synthetic-evidence-cap、假高 ceiling data_accepted）由此关闭；恢复 else 嵌套会被 R42d 组合回归检测到。

## 增补 A5（2026-08-20，L3 前置冻结）：泄漏谓词分解、DAG 合同、语义下限与不可表达边界

L3 编码前冻结语义合同，防"测试全绿但少实现分支"的假闭合。本增补是 L3 的验收合同：实现与 mutation 测试按谓词逐条对账，决策 3 的"六类泄漏"表述精确化为**六规则族 × 七独立谓词**（mutation 杀灭单元是谓词；集合成员谓词的枚举分支逐一杀灭）。

1. **六规则族 × 七谓词**（fixture 现状已逐件实测）：

   | # | 规则族 | 谓词（rule_id） | 判定（对 schema 合法载荷） | 正例 fixture |
   |---|---|---|---|---|
   | P1 | learned fit 越界 | `preprocessing-fit-full-data` | `preprocessing[*].fit_scope == full_data` | `unsafe-fit-scope-full-data.json`（在仓） |
   | P2 | learned fit 越界 | `feature-selection-fit-full-data` | `feature.selection_scope == full_data` | `unsafe-feature-selection.json`（在仓，实测 selection_scope=full_data / target_encoding=none） |
   | P3 | sampling 越界 | `sampling-scope-unsafe` | `sampling[*].scope ∈ {full_data, pre_split}`——两枚举分支各自 mutation | 派生两枚单违规（第 5 条）；原件含双违规 |
   | P4 | scope/upstream 不一致 | `scope-upstream-mismatch` | 节点声明安全标签 `train_only`/`per_fold` 而 `input_sha256` 解析为 dataset 段（现行 DAG 中唯一的 split 前节点）——覆盖 preprocessing/sampling × train_only/per_fold 四组合 | 现 1 件（preprocessing+train_only）+ 派生 3 件 |
   | P5 | target encoding 越界 | `target-encoding-not-per-fold` | `feature.target_encoding_scope ∉ {per_fold, none}` | `unsafe-target-encoding.json`（在仓） |
   | P6 | tuning 使用保护分区 | `tuning-uses-protected-split` | `tuning.split_used ∈ {test, future_holdout}`——两枚举分支各自有正例 | `unsafe-tuning-split-test.json` + `unsafe-tuning-split-future-holdout.json`（均在仓） |
   | P7 | selection 使用测试集 | `selection-uses-test` | `selection.split_used == test` | `unsafe-selection-split-test.json`（在仓） |

   与决策 3 的 scope 分流裁决一致：声明值本身不安全（`full_data`/`pre_split`）由 P1–P3/P5 直接拒绝；安全标签 + 错误上游 pin 才由 P4 判拓扑不一致——每条正例只被一条谓词拒绝，职责不重叠。

2. **DAG 合同**（结构错误优先于泄漏推导，全部 fail-closed）：
   - **节点集恰为 schema 中有真实 pin 的段**：dataset（根，无 `input_sha256`）、split、`preprocessing[*]`、`sampling[*]`、selection。feature/tuning/assessment 不是 DAG 节点，不补造。
   - **边方向**：split→dataset；`preprocessing[*]`/`sampling[*]`→dataset 或 split；selection→split 或某一 preprocessing/sampling 步。步间互指（pre→pre、sampling→sampling、pre↔sampling）不被现行合同承认——现有合法 fixture（minimal/full/group-split/nested-split 已逐件实测）全部直接指向 split，无链式 pin。
   - **结构违规**：dangling pin（`input_sha256` 不匹配任何段 `sha256`）、自引用、非法方向、歧义寻址（多段同 `sha256`）、identity 冲突（同 identity 不同 `sha256`，或同 `sha256` 不同 identity）、引用成环——均为 AdapterError。
   - **非义务**：并行 preprocessing/sampling 不必都通向 selection（连通性不是合同）；跨 case 的"同 identity 必同 hash"超出无状态入口能力，本轮不验证，只保证单 case 内一致。
   - **实现形态**：迭代三色标记/Kahn，确定性 O(V+E)，无递归、无祖先反复扫描。

3. **三项非泄漏语义下限**（schema 描述已明文下放到语义层，fail-closed）：
   - **split kind → parameters 合同**（按在仓 fixture 形态冻结；schema 层要求 `parameters` 本身是 object，但**对象内各自由键的值**不受类型约束——`false`/`[]`/`null`/浮点等 JSON 值出现在键值位置均 schema 合法，故"键缺失或空白值即拒"不足——类型判定先行）：
     - `iid`：无必填键；额外参数允许但本层不解释；
     - `group.group_key`：必填，且为含非空白字符的 string；
     - `time_series.gap` / `time_series.embargo`：必填，各为含非空白字符的 string（保持 `"5 sessions"` / `"20 sessions"` 形态，不解析为数值）；
     - `nested.outer_folds` / `nested.inner_folds`：必填，各为非 bool 的 JSON integer 且分别 `>= 2`；
     - 键缺失、类型不符（bool/数组/null/浮点等规定类型外形态）、空白 string、越界整数一律 AdapterError。
   - **`tuning.seed_count >= 1`**（schema 层已限定 `integer` 类型；schema 描述原文："The schema engine has no numeric-floor keyword; the >=1 floor is a semantic-layer obligation"——下限由语义层 fail-closed 执行）。
   - **assessment 双向 detail 纪律**：四维中任一 `status == declared`，对应 detail 字段（calibration.method / subgroup.group_key / ood.probe / drift.method）必须存在且为非空白 string；`status == not_performed` 时**禁止携带对应 detail**——"未执行但声明方法"的双义载荷 fail-closed（schema 层 detail 可选且各段 additionalProperties=false，detail 键集封闭，双向判定均可执行）。

4. **不可表达边界（决策 9 降级声明）**：决策 9"selection 与最终报告不得引用同一 split"的**记录内半侧**由 P7/P6 执行；**跨记录半侧**（最终报告证据引用哪个 split）在 L3 时不可表达——`ml-evidence/v1` 无 final-report 的 split/partition pin。L3 不用 `frozen_holdout` 猜测、不声称该 gate 已验证；该边界已由 L4 增补 A6 的 `evaluation-contract/v3` + `ml-evidence/v2` 交叉绑定闭合。

5. **fixture 派生与 mutation 义务**：
   - 现 `unsafe-sampling-scope.json` 实测含 `full_data`+`pre_split` 双违规（两步 input 均指向 split，纯 P3）：派生两枚单违规 probe（`unsafe-sampling-scope-full-data.json`、`unsafe-sampling-scope-pre-split.json`）；原件保留，钉选"两条违规都上账"。
   - P4 现仅覆盖 preprocessing+train_only：补齐 preprocessing+per_fold、sampling+train_only、sampling+per_fold 三枚派生（四组合闭合）。
   - 全部泄漏正例 schema 合法、仅被对应谓词拒绝；负例集（minimal/full/group-split/nested-split 及安全变体）全通过。
   - **第 3 条语义下限的正反例义务**：四种 split kind 的安全正例由在仓 minimal（iid）/group-split（group，`group_key="patient_id"`）/full（time_series，`"5 sessions"`/`"20 sessions"`）/nested-split（nested，5/3）承担；**group/time_series/nested 各自适用**的参数负例（缺键、错误类型、空白 string、bool 或越界整数；iid 无必填键，只承担安全正例与"额外参数在场但本层不解释"的正例）、`seed_count=0`、四类 assessment 的 declared-缺-detail 与 not_performed-带-detail，各派生独立语义负例——全部 schema 合法、经公共入口仅被对应下限拒绝；这些下限判定同样在 mutation 面内，弱化/删除对应判定须使负例假 PASS。
   - **真实 mutation，整谓词与分支两级**：①drop-rule——运行时从私有 registry 删除一个谓词，经公共 `build_evaluation_contract` 调用，对应正例假 PASS 即杀灭成功，七谓词逐一执行；②分支 mutation——P3（`full_data`/`pre_split`）、P6（`test`/`future_holdout`）的枚举分支与 P4 的四组合仅 drop-rule 不足证伪（删除整谓词不能证明分支各自承重），须以**弱化后的真实 predicate**（如 P3 弱化至只匹配 `full_data`、P4 弱化至只覆盖 preprocessing+train_only）替换并经公共入口验证对应单分支正例假 PASS。
   - 新增 fixture 只更新 `ADAPTER_FIXTURE_MANIFEST`（双向钉选）；`MINIMAL_FIXTURE_SHA256` 与四份 schema 的 byte pins **保持原值**——minimal 与 schema 字节未改，重算即漂移。枚举矩阵复跑。

6. **实现纪律**（复审批准结构，冻结）：
   - 新增私有模块 `src/research_evolution/adapters/ml/_topology.py` 与 `tests/unit/test_ml_topology.py`；`MLAdapter.build_evaluation_contract` 在 schema load 后、构造 contract 前**单一接入**。
   - 零新公共操作、零公开 validator、零新 Core 类型、无 `LeakageReport`；`ml.__all__` 仍只暴露 `MLAdapter`。
   - 规则存于**两个**运行时读取的模块级私有 registry：`_LEAKAGE_PREDICATES`（§1 的七条泄漏谓词）与 `_SEMANTIC_FLOORS`（§3 的三项下限——split parameters 合同、`seed_count` 下限、assessment 双向 detail）；两者由同一私有 validator 在 build 遍历时读取，**均不得以默认参数捕获**（否则 patch 不生效）；DAG 结构检查保持为独立前置阶段，不入 registry。mutation 测试删除/弱化真实 registry 条目后仍经公共 `build_evaluation_contract` 调用；禁止只测私有 helper。
   - 诊断复用 AdapterError：固定 rule ID + 可信 JSON 路径（如 `preprocessing[0].fit_scope`，路径片段由 schema 结构生成）；DAG/结构错误优先于泄漏推导；多违规按 registry 序稳定聚合一次抛出。**诊断条数有界**：preprocessing/sampling 数组无 `maxItems`，违规集合本身可无界——最多保留前 64 条稳定诊断，继续线性扫描统计违规总数，末尾追加固定格式 `N additional violations omitted`；省略信息不含任何调用方字符串。**`_preview` 不进拓扑模块**：`_preview` 位于 `adapter.py`，`_topology.py` 反向导入会产生循环依赖——拓扑诊断只输出固定 rule ID、路径与数量，不预览调用方值，`_topology.py` 不导入 `_preview`（R42g 截断纪律在本层无适用对象）。

7. **L2/L3 职责分界确认**（本条取代决策 10 关于 L3 范围的原括注"决策 3/4 的规则面与封顶"；决策 10 正文已同步修订并留下"A5 修订"标记）：L2（已交付并 push 至 `a28cbba`）= seam 数据合同、声明↔结果比对、成熟度封顶（决策 4）、三方绑定；L3 = 本条 1–3，**不重做决策 4 的封顶**。L3 落地 commit 的状态同步面（**不触碰四份 ml-* schema**——其 description 已兼容 L3 落地，无须修改，byte pins 保持原值）：`adapter.py` docstring 的 "those semantic checks land in L3" 前向注记、`schemas/adapters/README.md` 的对应行、**根 README 的 L 层状态行（:86）与 `docs/plans/PROJECT_IMPLEMENTATION_PLAN.md` 状态行（:7）**——后两处现仍写"L2–L6 未实施"，列入 L3 commit 同步范围（或经独立 docs commit 先行，由 L3 审核包二选一报备）。

**L3 实施清单（随本增补复核）**：新增 `_topology.py`、`test_ml_topology.py`、5 枚泄漏派生 fixture + 第 3 条语义下限负例集（group/time_series/nested 参数负例——iid 无参数负例、`seed_count=0`、assessment 双向 detail 负例，逐条独立）；修改 `adapter.py`（单接入点 + docstring 注记）、`ADAPTER_FIXTURE_MANIFEST`（仅此一处——`MINIMAL_FIXTURE_SHA256` 与 schema byte pins 不动）、`schemas/adapters/README.md`（L3 状态）、根 README 与 `docs/plans/PROJECT_IMPLEMENTATION_PLAN.md` 状态行、本 ADR；电池 = 双环境全套件 + 参数化 suite + matrix 复跑 + 规范删除探针 + 冻结面/禁依赖/缓存检查；单层 commit `feat(adapters): add deterministic ML leakage checks (L3)`。后续协调项：`docs/phase5-planning@5cfab81` 含旧"L2 未实施"状态，L3 收口后 rebase/协调，不直接合并。

## 增补 A6（2026-08-21，L4 冻结）：final-evaluation 交叉绑定与标准库合成 runner

L4 开工前复核发现：若只在 `ml-evidence/v2` 复制 `selection.split_used`，`validate_claim` 只能相信 evidence 对 case 事实的自报，无法证明该值来自 contract 所绑定的原 case。故选择事实留在 case 派生合同侧，运行结果事实留在 evidence 侧，由既有 `validate_claim(claim, evidence, contract)` interface 完成交叉验证；不增加第四个 Adapter 公共操作。

1. **`evaluation-contract/v3` 是 case 侧 successor**：在 v2 的 `study_id` 与 `assessment_declaration` 上增加 `selection_partition`、`selection_sha256`、`split_sha256`。三字段均由 `build_evaluation_contract` 从已通过 schema + L3 topology 检查的 `ml-case/v1` 派生；v1/v2 schema 字节冻结并继续注册，Math/Quant 生产者仍使用 v1。`EvaluationContract` 接受 v1/v2/v3，但 ML Adapter 自 L4 起产出并要求 v3。
2. **`ml-evidence/v2` 是结果侧窄 successor**：只承载 `kind=experiment_run`，在 v1 实验字段上增加必填 `final_evaluation={partition, split_sha256}`；assessment/audit/unit-test evidence 继续使用 v1。为保持语义规则可证伪，partition schema 允许 train/validation/test/future_holdout，train/validation 由语义层拒绝，而非在结构层提前杀掉。L4.1 增补 A7 又将 `case_sha256` 加入同一未发布 successor，以闭合 evidence→case 绑定。
3. **最终评估 hard gate**：generalization 路径要求 experiment evidence 为 v2；v1 experiment 因缺 final partition/split pin 而 fail-closed。消费 v3 contract 时依次验证：selection 不得使用 test；final evaluation 只能使用 test/future_holdout；final split pin 必须等于 contract 的 case-derived split pin。前两条共同推出 selection 与 final partition 不同，不增设逻辑冗余谓词。规则集中在私有 `_evidence.py` registry，删除任一真实谓词后必须经公共 `validate_claim` 产生假 PASS，mutation test 据此杀灭。
4. **Runner interface 与能力边界**：`run_synthetic_experiment(dataset_payload, case, *, contract, final_partition) -> SyntheticExperimentResult` 是 `adapters/ml/runner.py` 唯一执行入口（A7 修订：contract 必须匹配 case）；`ml.__all__` 仍只暴露 `MLAdapter`，runner 作为显式子模块使用。首版只支持小型 numeric `binary_classification + logistic-regression` 与 `regression + ridge-regression` 参考路径，基线固定为 intercept-only；不支持任意 estimator、真实训练框架或超参搜索执行。
5. **数据与 split 的可执行 pin**：dataset payload 恰含 task_type/features/targets/partitions；`{task_type,features,targets}` canonical hash 必须等于 `case.dataset.sha256`。A7 修订原先把 `case.split.sha256` 同时解释为声明 pin 与 partition pin 的过载：`case.split.sha256` 只钉 split 声明，`case.split.parameters.assignment_sha256` 单独钉 `{partitions}`。partition indices 全局不重叠并恰覆盖全部行；runner 不把纯声明 hash 当成已执行数据检查。
6. **确定性与资源纪律**：无 I/O、时钟、环境、网络、子进程或第三方数值依赖；runner 不调用会读取 schema 文件的 Adapter loader，只对内存 strict-JSON 快照及其实际消费字段做本地校验，完整 schema/topology/claim Gate 由 Adapter 公共入口集成测试承担。seed 排序与初始权重由 SHA-256 派生，不依赖进程级随机状态。候选与 baseline 使用相同数据、seed、epoch、sample_limit 与 row order；输出只变 model 一轴，冻结 resource/seed/data/heuristic 四轴。逐 seed 指标与 mean/population variance/observed range 全部落 artifact，不选择 best-only；行数、特征数、seed、epoch 与 sample-visits 均有显式上限。
7. **输出证据链**：runner 返回 immutable canonical artifact 与 `ml-evidence/v2`；evidence `content_sha256` 等于 artifact canonical bytes 的 SHA-256，case/final-evaluation 字段与 artifact 同源，并在返回前通过 strict-JSON 与 A6/A7 hard gate。为保持零 I/O，runner 本身不读取 schema 文件；完整 evidence schema 由随后同一公共链上的 `MLAdapter.validate_claim` 集成测试验证（A7 修正文案）。`data_provenance=synthetic`，limitations 明示只能证明协议/runner 工程行为，不构成真实 ML 数据验收或科研结论。
8. **L4 完成边界**：A6 successor schemas、golden fixtures、contract/final-evaluation mutation tests、classification/regression reference paths 与静态纯度门组成 L4 实现面。15–25 cases、非时间序列/时间序列双垂直切片、报告 artifact、ML shadow/Case Package 与 ML/Quant 重合分析仍分别属于 L5/L6；不得因 L4 runner 全绿宣称真实 ML 执行器或完整科研 Agent。

## 增补 A7（2026-08-21，L4.1 加固）：证据 case 绑定与诚实执行子集

L4 独立复核发现三项会削弱 L5 端到端证据的缺口：experiment evidence 只绑定 study/split 而未绑定 case；runner 接受原始 case 却不能证明调用方先走过 Adapter topology Gate；`split.sha256` 同时承担声明 pin 与 partition assignment pin，导致 group/time-series/nested 的声明看似可执行而载荷没有 group、timestamp 或 fold 结构。本增补在不引入真实 ML 执行器的前提下先 fail-closed。

1. **Evidence→case 第四向绑定**：未发布的 `ml-evidence/v2` 增加必填 `case_sha256`；generalization 的每条 experiment evidence 必须等于 `evaluation-contract/v3.case_sha256`。case mismatch 是独立 mutation 谓词；删除它必须使 foreign-case evidence 假 PASS。
2. **Runner 入口要求 case-derived contract**：runner 0.2.0 的唯一执行入口增加 keyword-only `contract`；逐项核对 contract schema、case/study、selection partition/pin 与 split pin。runner 仍不把 contract 当签名凭据：它同时校验完整 case 顶层形状、受保护 tuning partition、split/selection 声明的 canonical projection，防手写 v3 contract 绕过实际消费字段。
3. **声明 pin 与执行 pin 分离**：IID 合成子集的 `case.split.sha256` = canonical `{identity,input_sha256,kind,parameters}`；实际 `{partitions}` hash 写入自由参数 `split.parameters.assignment_sha256`。artifact 同时记录两者；final evidence 的 `split_sha256` 继续引用声明 pin，`case_sha256` 间接绑定 assignment pin。
4. **诚实执行包络**：L4.1 只执行 `iid`，且 preprocessing/sampling 必须为空、feature selection/target encoding 必须为 none、tuning search_space 必须为空、tuning.seed_count 必须等于唯一 seed 数、selection.metric 必须属于执行指标集。group/time_series/nested（含真实 gap/embargo/fold 验证）明确 fail-closed，必须在 L5 先定义带 group/timestamp/fold/purge 信息的执行合同后才能称端到端。
5. **数值与 oracle 纪律**：非有限中间结果统一收敛为 `SyntheticRunnerError`；classification/regression 已知样例钉住独立 literal 指标值与实际 sample-visits，避免仅断言输出形状的自证。
6. **版本与兼容**：runner interface 破坏性变化使内部版本升至 0.2.0；Adapter 三 seam 操作与 Core 公共面不变。`ml-evidence/v2`、A6/A7 仍只存在于未合并的 Phase 5 功能分支，故在首次发布前原地收紧并同步 schema byte pin、minimal fixture pin、valid/invalid fixtures；v1 字节保持冻结。
