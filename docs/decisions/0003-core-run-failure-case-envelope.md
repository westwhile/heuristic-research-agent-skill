# ADR-0003：Run/Failure/Case envelope 的 schema、引用与隐私边界

- 状态：Accepted for Phase 1C
- 日期：2026-08-16

## 背景

ADR-0002 交付了 `load_record`/`publish_record`/`verify_record_graph` 三个公共操作、三个 v1 schema 与全局逻辑 id 唯一性合同（`duplicate_id`）。总体计划 Phase 1 尚余 Run、FailureObservation、FailureAnalysis、ResearchCasePackage 与 ExperiencePacket 五类对象。Phase 1C 补齐前四者的通用 envelope；不实现 Adapter、Evaluator、Pattern、Skill Candidate 或自动进化，也不实现隐私 redaction 与 CLI（Phase 1D，ADR-0004）。实施切分遵循一个原则：**一个 family 一旦可发布，同一提交中的图校验必须完整认识它**（Run/Observation/Analysis 一层，Case 一层），不存在"已发布但图校验不认识"的假 PASS 中间态。

## 决策

1. **新增四个 schema，统一 `research-` 前缀**：`research-run/v1`、`research-failure-observation/v1`、`research-failure-analysis/v1`、`research-case-package/v1`。拒绝 `failure-*` 双前缀：单一命名空间使 dispatch、存储布局与 fixture 结构保持均匀。
2. **引用方向性为单向模型**：Run→Task、Observation→Run、Analysis→Observation、Case→成员均为单向引用，不触发 `one_way_link`；双向一致性仅保留 Claim↔Evidence。理由：层级/打包引用若要求双向，发布新 Run 即需修订既有 Task，与 append-only 不相容。
3. **pin 范围**：层级/打包引用必须携带 hash pin（pin 缺失属 schema 层必填报错，pin 不符属图阶段 `pin_mismatch`）；`supersedes`（Claim 与 FailureAnalysis）是 lineage 引用，不在此范围，维持 ID-only；Claim↔Evidence 的可选 pin 维持 Phase 1B 语义。
4. **Run 冻结字段**：executor、environment、inputs、随机性与版本信息采用中性结构，必填项绑定 SHA-256/版本标识；字段词汇为未来 Candidate/Champion 冻结比较预留，不含领域语义。
5. **Observation/Analysis 分离**：FailureObservation 只保存当时可观察事实，schema 层拒绝任何根因推断字段；FailureAnalysis 保存可修订假设，锚定恰好一个 Observation（必填 `{observation_id, sha256}`），经 `supersedes` 构成 append-only 链。Observation 不可被 Analysis 覆盖或冒充——两者是不同 family，跨类型引用由图校验拒绝。
6. **引用语义表**（图校验由决策 10 的 family contract registry 驱动展开）：

   | 引用 | 方向 | pin | 违规 kind |
   |---|---|---|---|
   | claim.supporting_evidence → research-evidence/v1 | 双向 | 可选 | dangling_reference / cross_type_reference / pin_mismatch / one_way_link / duplicate_reference |
   | claim.supersedes → research-claim/v1 | 单向 | 无 | dangling_reference / cross_type_reference / self_reference / lineage_cycle |
   | run.task → research-task/v1 | 单向 | 必须 | dangling_reference / cross_type_reference / pin_mismatch |
   | observation.run → research-run/v1 | 单向 | 必须 | dangling_reference / cross_type_reference / pin_mismatch |
   | analysis.observation → research-failure-observation/v1 | 单向 | 必须 | dangling_reference / cross_type_reference / pin_mismatch |
   | analysis.supersedes → research-failure-analysis/v1 | 单向 | 无 | 既有 supersedes 各 kind + lineage_scope_mismatch |
   | case.{task, runs, claims, evidence, observations, analyses} → 各对应 family | 单向 | 必须 | dangling_reference / cross_type_reference / pin_mismatch / duplicate_reference；闭包见决策 7 |

7. **Case 结构与闭包**：`task` 恰好一个；`runs` ≥1；`claims`/`evidence`/`observations`/`analyses` 为可空数组，各自独立可空。空集纪律：Evidence 非空时其关联 Claim 必须被 Case 收录；Claim 非空而 Evidence 为空仅受既有 draft/proposed/inconclusive schema 约束；两者都空的 Run/Failure trace 只是工程留档，不得表述为科研证据或支持任何 Claim。闭包检查五条：① 成员 Analysis 的锚定 Observation、该 Observation 的 Run、该 Run 的 Task 必须都是 Case 成员；② 成员 Claim 的 `supporting_evidence` ⊆ Case.evidence；③ 成员 Evidence 的 `claim_ids` ⊆ Case.claims；④ 全部成员 pin 与存储记录逐条一致；⑤ 同一 Case 内成员 id 重复出现报 `duplicate_reference`。①–③ 违反报 `case_incomplete`。
8. **隐私两阶段、单轴状态**：Case v1 仅含 `privacy_review_status`，枚举收窄为 `{"pending"}`。"是否允许导出"与"是否已发生导出"是正交状态轴，不得合并进同一枚举；不可变 Case 也不承载状态迁移。Phase 1C 的 Case **一律不可导出**——本批不提供任何导出通道；允许/拒绝决定与导出事实全部由 ADR-0004 的记录表达（建议命名 `export-decision/v1`、`export-receipt/v1`，避免与核心类 `PublicationReceipt` 混淆），永不回写 Case。
9. **ExperiencePacket 不作为 Core schema**：定性为 Experience Exporter 的派生产物；升格条件是 deletion test 证明其拥有独立于 Case/Analysis 的不变量，且需新 ADR 论证。
10. **family contract registry 是单一私有元数据源**：新增纯数据模块描述每 family 的 identity field、supersedes 能力与 lineage scope（claim 为 family 级、failure-analysis 为 Observation 锚）、引用（字段 → 目标 family、方向、pin 要求）；`_store` 与 `_graph` 共同读取，消除 `_ID_FIELDS` 与图侧两张表的漂移源。registry 不进化为规则语言——Case 闭包、lineage scope 等高级语义是读表的私有 validator。公共 interface（三个操作）零变化。
11. **violation 合同**：新引用复用既有 kind，仅新增三个——`lineage_scope_mismatch`（Analysis 的 supersedes 目标锚定不同 Observation）、`case_incomplete`（闭包缺员）、`duplicate_reference`（通用：同一记录的引用数组内同 id 重复出现，适用于 Case 五类成员数组、`claim.supporting_evidence` 与 `evidence.claim_ids`；后者使 1B 语义下静默的重复引用成为违规，属有意的合同收紧，1B store 无生产存量）。候选总数 **24（14 完整性 + 10 图）**，随本语义表签署定稿。

## 后果

优点：

- 事实（Observation）与推断（Analysis）在 schema 层不可混淆，证据链可全图验证；
- 单向 + 必须 pin 使层级引用在 append-only 下语义完备，且引用完整性不依赖被引用方的修订；
- registry 单源使新增 family 的成本从"改两处并保持同步"降为"加一条数据"；
- 隐私单轴 + 1C 一律不可导出，避免预支 ADR-0004 的词表决策（消除倒序冻结）。

代价：

- Case 闭包是首个跨 family 的复合检查，validator 复杂度高于表驱动检查；
- `duplicate_reference` 对既有 1B store 是合同收紧（重复 supporting_evidence 从静默变违规）；
- Analysis 单锚意味着跨 Observation 的综合分析需要更高层对象表达，留待后续批次。

## 拒绝的方案

1. **C3 先可发布、C4 再图校验的切分**：制造悬空 Run→Task 被判 `ok=True` 的假 PASS 窗口；改为"可发布 ⇄ 图认识"同提交原子化。
2. **`blocked | not_exported` 混合枚举**：混合许可与事实两个正交轴，且不可变记录无法承载状态迁移。
3. **扩展 schema 引擎支持 `uniqueItems`**：`_schema.py` 是 Phase 1A 冻结表面（52 个 mutation 测试守卫的关键词合同），为单一需求扩关键词是高爆炸半径窄收益，且 `uniqueItems` 无法表达"不同 pin 的重复"这一真实矛盾（`pin_mismatch` 的职责）。
4. **层级引用双向化**：破坏 append-only 人机工程（见决策 2）。
5. **`failure-*` 双前缀命名**：破坏 schema 单一命名空间的均匀性。
