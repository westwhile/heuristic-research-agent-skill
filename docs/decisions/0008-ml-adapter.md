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

10. **切片与 Git Gate 映射**：L1 = 本 ADR（+根 README 索引行）；L2 = 数据合同（四 ml-* schema + fixtures + Adapter 三操作实现 + contract suite 注册 ML harness）；L3 = 泄漏检查（决策 3/4 的规则面与封顶，含 leakage fixture 正负例）；L4 = runner（决策 5 + parity/seed 研究）；L5 = cases + 双垂直切片 + leakage fixture 报告 + 重复实验报告；L6 = ML shadow cases + case packages + ML/Quant 重合分析（决策 7）+ 验收报告 → v0.6.0。每层验收含全量套件双环境绿——**原有 Math/Quant 测试零 critical regression** 是 L2–L6 的逐层验收账本项（gate 原文），非仅终验义务。分支 `feat/ml-adapter`；数据合同、泄漏检查、runner、cases 分提交（Git Gate 原文）；PR 附重复实验与 leakage fixture 报告；annotated tag `v0.6.0`。

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
