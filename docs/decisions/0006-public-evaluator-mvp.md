# ADR-0006：Public Evaluator MVP——L0/L1 评测记录、runner/scorer/统计纪律与 meta-test 义务

- 状态：Accepted（Phase 3 第一层）
- 日期：2026-08-16
- 关联：总体计划 Phase 3（12 项任务、验收 Gate、Git/发布 Gate）、ARCHITECTURE §3.8/§4.5/§6、ADR-0002（发布/图校验接口）、ADR-0004（兼容政策与隐私导出）、ADR-0005（Adapter seam 与成立判据）

## 背景

Phase 2 冻结了 Adapter seam 并以双领域合成切片证明其成立。总体计划 Phase 3 要求实现 **L0 协议评测与 L1 artifact replay**，形成可重复的 Champion/Challenger 公开比较，且明确"暂不把离线 runner 说成完整 Agent 评测"。架构 §3.8 把 `EvaluationCase`/`EvaluationResult` 列入通用领域模型（Case 冻结输入、Claim 类型、领域、split、资源、evaluation contract 与污染状态；Result 绑定 candidate、case、runner、环境与评分器）；§4.5 冻结 Evaluation Module 的三操作；§6 冻结 L0–L4 分层与"每份报告必须注明覆盖层级"的纪律。

Phase 3 落地上述边界的 MVP 切片。不实现 L2/L3/L4、hidden 评测服务、Candidate 自动晋级、ResearchPattern 蒸馏（Phase 4）。

## 决策

1. **评测记录的归属**：`evaluation-case/v1`、`suite/v1`、`evaluation-run/v1`、`comparison-report/v1` 四个 v1 schema 作为 **Core 记录 family 的 additive 扩展**注册进 `_families.py`（第 10–13 个 family），可发布、可哈希、进全图验证。理由：它们是 append-only 评测事实（§3.8 通用领域模型成员），不是领域翻译合同——ADR-0005 决策 1 的 seam 类型判据（"交换合同而非 store 事实"）不适用于它们；additive 扩展符合 ADR-0004 兼容政策（同版本号永不承载双语义，新 family 不改既有 family 语义）。既有 9 family、18 项公共面、既有 25 种 violation 语义零变化；新 family 引入的图校验规则在实现层显式列举并逐一有断言。
2. **L0/L1 范围纪律**：本 Phase 只实现 L0（协议评测：schema/hash/权限/状态/导出/污染检查）与 L1（artifact replay：对冻结输出重新评分）。**每份评测与比较报告必须结构化标注覆盖层级**；L0/L1 通过不得表述为 L2/L3/L4 通过（架构 §6 原文）。L2/L3/L4 为显式非目标。
3. **冻结与哈希绑定**：suite snapshot、candidate、envelope（超时/输出上限/retry/环境）以其 canonical sha256 绑定进 `evaluation-run/v1`；复用 Phase 1 store 与只读 CLI，**不新增任何写入面**；candidate 在本 Phase 是哈希引用的不可变工件描述，不实现 CandidateBundle 全模型（Phase 4/6）。
4. **runner 纪律**：runner 只执行确定性离线重放；超时、输出大小上限、结构化错误分类（timeout/output-limit/parse/runner-error 等枚举）与 retry policy（次数、条件、确定性）冻结在 envelope 中并随 run 留痕；runner 不触网络、不读时钟之外的环境状态，种子与配置由调用方注入。
5. **scorer 等级**：评分器分四级显式标注——`oracle`、`deterministic_checker`、`structured_rubric`、`calibrated_judge`；等级记入 evaluation-run 与报告。calibrated judge 的校准证据本 Phase 只留字段与纪律，真实校准属条件能力。
6. **score vector 纪律**：评测产出多维 score vector（按 gate/维度分列），**禁止生成跨领域唯一总分**；报告只能呈现向量与逐维结论。
7. **统计边界**：比较实现 paired exact/McNemar、paired bootstrap、rare-event 上界三类，方法名、参数、种子全部留痕；**20–30 cases 的小样本总准确率不得声称统计显著提升**（计划验收 Gate 原文）；统计结论必须可由留痕参数复现。
8. **hard gates**：完整性、critical safety、回归、资源、隐私、evaluator integrity 六门；任一不过即整体不过，门禁判定与理由结构化进报告。
9. **meta-tests 义务**：known-good / known-bad / evaluator mutation 三类元测试是评测套件的组成部分；mutation 至少覆盖：反转 PASS/FAIL、移除判定条件、放宽资源限制；known-good/known-bad 必须稳定区分，mutation 必须被检出（计划验收 Gate）。
10. **报告三形态一致性**：HTML、Markdown、JSON 三形态从同一结构化数据生成、内容一致；每份报告绑定 suite/candidate/envelope/scorer 等全部必要哈希并标注 L0/L1 覆盖范围。
11. **split 与污染台账**：split 词表冻结为 `smoke`、`development`、`regression`、`metamorphic-public`、`adversarial-public`；contamination ledger 记录已知污染状态，污染 case 不得计入 development 之外的结论文案。
12. **切片与 Git/发布 Gate**：分支 `feat/public-evaluator-mvp`；切片顺序 E1（本 ADR）→ E2（四 schema + fixtures + family 注册 + 图语义）→ E3（runner/envelope）→ E4（scorer 四级 + score vector）→ E5（统计三类）→ E6（hard gates + meta-tests）→ E7（三形态报告）→ E8（首批公开 cases + 验收报告）。runner、scorer、statistics、meta-tests 分提交（计划 Git Gate）；PR 必须附一份可公开 evaluation report；annotated tag `v0.4.0`；Release 明确仅覆盖 L0/L1。首批规模与验收 Gate 按计划原文（Math 10–15、Quant 10–15 cases 等）。
13. **非目标（本 Phase 不交付）**：L2/L3/L4 评测；hidden 评测服务与私有 runner 真实实现（`benchmarks/private-interface/` 只保存协议与假实现）；Candidate 自动晋级或修改 case/scorer/report 的任何通道；ResearchPattern 蒸馏与检索（Phase 4）；真实私有数据进入公开 benchmark。

## 后果

优点：

- 评测事实进入 append-only store，"谁用什么 suite/envelope/scorer 评的"全程哈希可追溯；Champion/Challenger 比较获得可复现的统计纪律；
- 层级标注与 score vector 纪律把"L0/L1 通过"与"完整 Agent 能力"在数据结构上永久隔离；
- meta-test 义务使 evaluator 自身故障（反转、漏判、放宽）成为可检出对象而非信任假设；
- 切片与分提交纪律保持 Phase 1/2 的逐层审核节奏。

代价：

- 四个新 Core family 扩展了冻结面，每个都要承担 ADR-0004 的 successor 义务与合同测试维护；
- 统计与 meta-test 的诚实纪律意味着首批报告只能说有限的话（小样本不声称显著）；
- L1 replay 依赖冻结 artifact 的存在，真实 Agent 产出链（L2）缺席时切片仍以合成 artifact 为证据级。

## 拒绝的方案

1. **评测记录做成 evaluator 本地类型不入 store**：评测事实是跨时间可复核的结论证据，不是翻译合同；不入 store 则哈希绑定与 append-only 审计链断裂，ADR-0005 决策 1 的判据（交换合同）在此不成立。
2. **生成跨领域唯一总分**：违反计划任务 8；单一标量会把不同 gate 维度的失败平均掉，正是治理要防的误读。
3. **把 L1 replay 表述为完整 Agent 评测**：计划 Phase 3 目标原文禁止；架构 §6 的层级标注纪律在报告 schema 层面强制执行。
4. **calibrated judge 无校准证据即启用**：judge 等级只是标注；无校准证据的 judge 产出不得高于 structured rubric 的证据等级，否则污染比较结论。
5. **hidden/private split 进入公开仓库**：架构 §7 隐私边界；`benchmarks/private-interface/` 只保存协议与假实现。
6. **单一 PR 交付全部 12 项任务**：runner/scorer/statistics/meta-tests 分提交是计划 Git Gate 原文；大块合并使逐层对抗审核不可行。
