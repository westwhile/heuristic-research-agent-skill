# ADR-0007：Research Memory 与 Pattern/Heuristic Registry——case-package/v2、生命周期纪律、检索 MVP 与 shadow 边界

- 状态：Accepted（Phase 4 第一层）
- 日期：2026-08-17
- 关联：ARCHITECTURE §3.5–3.10/§4.3/§7、总体计划 Phase 4（任务 1–21、验收 Gate 11 条、Git/发布 Gate）、ADR-0001（Core/Adapter 分层）、ADR-0003（记录模型与 supersedes 机器）、ADR-0004（三轴隐私模型与兼容政策）、ADR-0006（additive family 注册判据）

## 背景

Phase 1–3 交付了 13 个 Core 记录 family（research 七族、export 两族、evaluation 四族）、Adapter interface v1 与 L0/L1 公开评测器。总体计划 Phase 4 要求把成功、失败与重大项目问题转为可复核、可检索的案例与模式候选，**而不是让单次 LLM 总结直接修改生产规则或生成已安装 Skill**；架构 §4.3 冻结 Research Memory 四操作（`capture_case` / `distill_patterns` / `retrieve_patterns` / `record_reuse_outcome`）与"首版只确定性检索"边界；总体计划 §3.2 规定 Phase 4 结束时的最高状态为 active Pattern + shadow Heuristic。

两项背景事实直接塑造本 ADR：

1. 计划 Phase 4 交付物行文写"`research-case-package/v1` 与 `research-pattern/v1` schema"，但 case-package v1 自 Phase 1 已冻结（11 属性、`additionalProperties: false`、`privacy_review_status` 固定 `pending`），不含任务 2 要求的问题签名、决策时间线、未决问题、环境、导出模式、中间产物 manifest 与来源 lineage。按 ADR-0004 兼容政策（无兼容模式 flag、同一版本号永不承载双语义），该需求只能以 successor 落地（决策 2）。
2. 计划任务 6 与交付物要求 "append-only lifecycle events"，任务 7/13 同时要求 Pattern/Heuristic 记录自带 `status` 与 successor 字段。生命周期表达机制因此是本子系统的核心设计抉择（决策 3）。

Phase 4 不交付 L3–L5 对象与任何晋级/安装能力（决策 1）。

## 决策

1. **范围与非目标**：Phase 4 交付 L1 Case Package（v2）、L2 Research Pattern、shadow 级 Heuristic 及其注册、检索与 lint 机器；结束上限 = active Pattern + shadow Heuristic（总体计划 §3.2）。Case、Pattern、Heuristic 以各自 family 与 identity 字段区分，可通过 ID/hash 追踪但互不冒充（gate 5）。显式非目标：L3 Staged Skill Candidate、L4 Canonical Skill、L5 Installed 对象；创建或安装任何 Skill；production Champion；PromotionDecision；ML/DL 接入（Phase 5/6）；embedding/向量检索；任何自动晋级通道；`evaluation-run/v2`（保持计划任务 21 的 backlog 状态，由真实发布需求驱动）。

2. **`research-case-package/v2` successor**（任务 2、§3.6）：新 $id、新 schema 文件、新 fixtures、全套 valid+invalid 合同测试；v1 schema、fixtures 与既有测试字节零修改；registry additive 注册为第 14 个 family（identity=`case_id`，无 supersedes——case 是不可变 episode，后继案例是引用关系而非修订）。v1 的六个成员引用（task/runs/claims/evidence/observations/analyses，全 pin）原样保留、语义不变；新增字段组：
   - `problem_signature`：{summary, signature_sha256, 可选结构化 facets}——signature_sha256 即决策 4 分层聚类的 exact fingerprint；
   - `io_manifest` / `intermediate_manifest`：输入/输出 hash 与中间产物清单，条目复用 export-receipt 的 {name, sha256, 可选 locator} 形态（locator 走 §6 safe-relative-path 约束）；
   - `decision_timeline`（{at, entry} 条目，minItems 1）与 `open_questions`（可为显式空数组）；
   - `environment`：{tool, version, 可选 details}；
   - `privacy_review_status`：review 轴扩词表（决策 9）；`export_mode`：§7 四值词表原样引用；`rights`：可选版权/许可注记；
   - `eligibility`：{status, reasons[]}——任务 3 门禁结果的留痕位置（决策 9）；
   - `source`：{project, 可选 external_manifest_sha256}——外部来源只留标签与内容哈希，不复制字节（ADR-0005 决策 9 先例）；
   - `derived_from`：指向前序 case 的 pinned 引用数组（可为空，只指向 v2——v1 无 lineage 字段，Phase 4 自 v2 新建案例起链，v1↔v2 互链非需求）。
   确切枚举词表与条件性约束在 M2 schema 评审定稿。本 Phase 四个新 family 的引用全部落在既有通用图机制形状内（dangling/pin/duplicate/self/cycle），**预期零新 violation kind**；若 M2 发现组合语义需求，回本 ADR 增补，不静默加 validator。

3. **生命周期机制 = 不可变版本化记录 + supersedes 链**（任务 7/8/13，核心设计点）：Pattern 与 Heuristic 的每次生命周期迁移都是一条新记录版本——新 id、`supersedes` 指向前驱（ID-only）、新 `status` 快照、必填 `transition_rationale`——复用 ADR-0003 的 lineage 机器（`SupersedesContract(scope="family")`，与 claim 同一先例），零新机制。`status` 是该版本的快照字段而非独立事实源；任务 7 的 successor 不落存储字段——append-only 下前向指针不可维护，successor 由 supersedes 链反向导出。状态迁移纪律：晋级默认需要多个独立案例；高价值单例只能在可重现、反事实修复、独立复核三要素齐全时例外进入 candidate-pattern，永不直达 active（任务 9）。cluster merge/split（任务 6）的 append-only event **不是 Core family**：cluster 是 registry 层派生索引（catalogs/ 可重建原则），merge/split 事件写入 registry 层 append-only 日志（确定性、可重放），原始案例与旧索引永不覆盖。交付物 "append-only lifecycle events" 由版本链（对象级）与 registry 事件日志（索引级）共同满足。

4. **分层聚类与 registry 层边界**（任务 1/4/5/6）：exact fingerprint（`problem_signature.signature_sha256`）→ 结构字段 → taxonomy 路径 → 语义 proposal 四层递进；语义相似度只提出候选，不作合并或晋级裁决（§4.3："相似度不得成为自动执行或晋级依据"）。taxonomy 是**版本化数据**而非代码：通用一级 + Math/Quant 二级 overlay 以数据文件承载，按内容哈希钉入 registry（在决策 11 的静态扫描面之外）。observation/analysis 复用 Phase 1 family，零改动（gate 4：Observation 历史不因分析更新而变化，schema 层本就无假设字段）；counterfactual test registry = registry 层对既有 run/evidence 记录的索引，无新 family。根因晋级纪律（§3.5、gate 3）的本 Phase 执行形式：analysis 链（supersedes）承载演进中的 hypothesis，任何"已确认根因"表述必须在新版本 analysis 中引用复现、反事实修复与独立复核三要素；schema 层不存在任何 "confirmed" 标志位。

5. **检索 MVP contract**（任务 10/11、§4.3）：只实现确定性 metadata/text 检索，禁止 embedding；困难问题进入执行前先冻结 problem signature 再查询；返回至多 3–5 个候选 Pattern，每个候选必须携带 applicability、contraindications、evidence（等级 + 摘要）、source（来源 case 引用）、last-validated 与差异说明六要素；空结果是合法 abstain，必须显式标注而非静默缺席。检索结果只作为 hypothesis/inspiration：操作者必须显式选择、拒绝或改写（任务 11）。检索会话日志是 registry 层哈希绑定 artifact——查询不是事实，不入 store；只有实际复用结果落记录（决策 6）。last-validated 随检索合同暴露，staleness 在使用时可见；registry 层另出确定性 staleness 报告（决策 7）。

6. **`reuse-event/v1` family**（任务 11、gate 7、§3.7/§4.3）：事实轴记录（无 supersedes，export-receipt 先例），identity=`reuse_event_id`；引用两个 pinned 对象：`run`（→ research-run/v1）与 `pattern`（→ research-pattern/v1，钉住实际使用的那个快照版本）；`outcome` 枚举 = helped / neutral / harmed / not_applicable（§3.7 四值，schema 枚举沿既有下划线风格）；可选 `note`；`recorded_at`。复用反馈永不覆盖原 Pattern 记录（gate 7）——helped/harmed 聚合统计是 registry 层可重建派生物，不是 Pattern 记录的字段。

7. **`heuristic/v1` family 与 linter**（任务 12–17）：字段 = statement、scope、mode、evidence 摘要、exception、risk、rollback（任务 12）+ `status`（任务 13 生命周期：lesson-hypothesis → candidate → shadow → validated → promoted/deprecated/retired/rejected，schema 枚举沿下划线风格；**Phase 4 上限 = shadow**，后续状态词表存在但本 Phase 不可达）；supersedes scope=family（决策 3）；`regression_cases` 为 pinned 引用数组（→ research-case-package/v2，minItems 1）——任务 15 的强制关联在 schema 层 fail-closed。linter 实现四类确定性检查（任务 14）：duplicate、conflict、precedence cycle、dead/always-triggered；冲突、循环和无回滚的 blocking rule 一律拒绝（gate 8）；只有确定性全局不变量可成为 global hard gate（任务 17）。complexity budget、compression review、staleness review（任务 16）= registry 层确定性检查 + 报告 artifact；successor 关系由 supersedes 链承载（决策 3）。

8. **shadow 纪律**（任务 18、gate 9）：运行 3–8 条 shadow Heuristic，只记录假设性决策与预期差异，不改变任何生产行为；shadow report 是暂存区 artifact（哈希绑定 heuristic 记录与被 shadow 的 run），**不是 Core family**——promotion 超出本 Phase，无发布需求，不预建记录面。

9. **隐私与导出复用 ADR-0004 三轴**（任务 3、§3.6/§7）：review 轴留在 case——v2 按 ADR-0004 决策 1 预留的"扩词表只能走新 schema 版本"路径扩展 `privacy_review_status` 枚举（拟 pending/passed/rejected，M2 定稿）；permission 轴与 fact 轴仍由 export-decision/export-receipt 承载，**永不回写 case**。eligibility gate 四拒（任务 3）：不可复现、来源不明、含未授权敏感信息、只剩结论摘要的案例不得进入可共享 Pattern；门禁结果落 v2 `eligibility` 字段，`distill_patterns` 对 ineligible case fail-closed。Case 默认留在项目私有域；绝对路径、身份、受限正文默认拒绝（§7）；大型数据、模型与受限正文只保存 locator/hash，不复制进仓库（§3.6）。

10. **中央库 sibling layout contract**（任务 19、gate 10）：以文档合同规定 `$SKILL_LIBRARY_ROOT` 布局——`skills/`（仅正式 canonical Skill）、`research-patterns/{math,quant,ml,dl,project-engineering}`、`skill-incubator/{candidates,evaluations,rejected,archived}`、`catalogs/`（可重建，非事实源）；正式命名 **Research Pattern Library（研究模式库）**。Phase 4 在本仓只写隔离暂存区（拟 `staging/research-memory/`，M6 定稿），不安装 Skill、不执行任何 Skills Manager 写操作；`research-patterns/` 与 `skill-incubator/` 不在任何自动发现 Skill 根内（gate 10）；migration/retirement policy 以合同文档交付。

11. **域中立纪律扩展**（ADR-0005 决策 6/8 同一判据）：`_BANNED_TERMS` 静态扫描扩展至 `src/research_evolution/experience/` 与四个新 core schema；taxonomy overlay、案例正文与模式内容中的领域词汇是**数据**（决策 4），不在扫描面内；Core 与 experience 代码不得出现领域条件分支。实现落点 = 既有 `experience/` 占位包（§4.3："复用现有 experience 边界，不另建一组只转发的浅层服务"），成为与 core/evaluation 并列的公共面；`core.__all__` 保持 18 项不动。

12. **合格证据规模**（任务 20、gate 11）：Math、Quant 各 ≥3 个合格 case package（v2）、≥2 个 candidate pattern，并记录 ≥1 个"未找到适用模式"的正确 abstain 案例；Phase 3 公开 suite 保持全绿（公开 suite 无 critical regression）；全部证据为合成/脱敏级并如实标注（ADR-0005 决策 9 先例），真实私有数据零进入仓库。

13. **切片与 Git Gate 映射**：M1 = 本 ADR（+根 README 索引行）；M2 = schema 层（四个新 schema + fixtures + family 注册 13→17 + 图语义测试）；M3 = case builder/redactor/validator + manifest + eligibility gate；M4 = Pattern Registry + 分层聚类 + 检索 MVP + reuse 记录；M5 = Heuristic Registry + linter + shadow runner；M6 = layout 合同 + 隔离暂存区 + 合格证据包 + 验收报告。分支 `feat/research-memory-pattern-registry`；schema、case builder、pattern registry、retrieval、linter、shadow runner 分提交；PR 列出每个 active Pattern/规则的来源案例、适用边界、反例与 regression case；annotated tag `v0.5.0`；不创建正式子 Skill、不安装 Skill、不创建 production Champion。

## 后果

优点：

- 生命周期表达零新机制（复用 supersedes 机器），四个新 family 全部 additive 注册，图语义与 violation 合同零扩张；
- case v2 把任务 2 的冻结要求落成封闭属性集，eligibility、review、export mode 三事分字段留痕，Case/Pattern/Heuristic 互不冒充；
- 查询与派生索引（检索会话、cluster 事件、聚合统计）同事实记录（case/pattern/heuristic/reuse-event）分层清楚，store 不被非事实洪泛，catalogs/ 可重建原则保持；
- shadow 上限、linter 拒绝面、单例晋级纪律与合法 abstain 把验收 gate 1/2/3/6/8/9 落成可执行检查。

代价：

- case-package 出现 v1/v2 两版并存，successor 义务随之而来（v2 文档声明替代关系；既有 v1 记录永久有效、v1 测试永不修改）；
- status 快照 + supersedes 链要求消费方沿链解析最新版本，registry 层须提供确定性链解析；
- 检索 MVP 只有确定性 metadata/text 实现，召回能力受限——这是 §4.3 的刻意选择，不是缺陷；
- Phase 4 全部证据为合成/脱敏级，Pattern 的证据等级上限随之受限，须在 evidence 字段如实标注。

## 拒绝的方案

1. **独立 lifecycle-event Core family**：与任务 7/13 要求的 status 字段构成双事实源，漂移风险高；现有 supersedes 机器已提供 append-only 语义；"事件"需求由版本链（对象级）+ registry 日志（索引级）双层满足。
2. **case-package v1 原地扩字段或引入兼容模式 flag**：直接违反 ADR-0004——v1 属性集封闭，同一版本号永不承载双语义。
3. **检索会话、cluster 事件或聚合统计注册为 Core family**：查询与派生索引不是事实；§3.1 的 catalogs/ 可重建原则要求它们可从事实层确定性重放，入 store 只会洪泛事实层。
4. **单例直接晋级 active pattern，或复盘自动生成/安装 Skill**：验收 gate 1/2 明文禁止；任务 9 的单条例外只到 candidate-pattern 且三要素齐全，永不直达 active。
5. **首版引入 embedding/向量检索**：§4.3 明文避免过早形成浅层端口；待 corpus 规模与评测证明需要时以新 ADR 增加 adapter。
6. **shadow Heuristic 接入生产执行通道**：gate 9 与总体计划 §3.2 上限禁止；shadow 的全部价值在于"假设采用了会怎样"的可复核记录，接入生产即自我否定。
7. **在 Pattern/Heuristic 记录中存储前向 successor 指针**：append-only 下版本 N 无法预知 N+1，前向指针必然失效或要求回写；successor 关系由 supersedes 链反向导出。
