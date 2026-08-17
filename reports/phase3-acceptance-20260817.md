# Phase 3 验收报告：Public Evaluator MVP（待 R34b 终审）

- 日期：2026-08-17
- 分支：`feat/public-evaluator-mvp`（基 `main` = `3bf5d17`，v0.3.0）
- 范围：ADR-0006 的落地——L0/L1 评测记录四 family、replay envelope 与确定性离线 runner、scorer 四级与 score vector、统计三类、hard gates 六门与 evaluator meta-tests、装配/比较/三形态报告、首批公开 benchmark suites
- 状态：**E1–E8 已逐层提交，R27–R34b 九轮审核全部 PASS，账本清零**（R34b 终审后由本收尾 commit 回填状态行与 E8 哈希，1C/1D/2 先例）

## 层/commit 映射

| 层 | 内容 | commit | 审核 |
|---|---|---|---|
| E1 | ADR-0006（13 决策 + 后果 + 6 拒绝方案） | `e9e8595` | R27 PASS（决策 1 评测记录归属 Core family 经正面裁决） |
| E2 | 四评测 schema + 28 fixtures + family 注册（registry 13 id） | `05e85e9` | R28 PASS |
| E3 | replay envelope + 确定性离线 runner（四错误类） | `c5634b2` | R29 PASS |
| E4 | scorer 四级 + score vector | `64db5de` | R30b PASS（R30-P2 oracle 假匹配族、R30-P3 dimension 收紧、R30-P4 calibration 拒丢弃均已修复回归） |
| E5 | 统计三类（paired exact/McNemar、paired bootstrap、rare-event 上界） | `93d2100` | R31 PASS |
| E6 | hard gates 六门 + verdict 装配 + meta-tests | `e73791d` | R32b PASS（R32-P3 NaN floor fail-open 已修复回归） |
| E7 | `evaluate_case`/`compare` 装配 + 三形态报告 | `ab3838e` | R33b PASS（R33 头条：E2 schema 缺口裁决 fail-closed；R33-P3 装配产物自验已修复回归） |
| E8 | 首批公开 suites（math/quant 各 12 cases）+ 集成测试 + Decimal seam 闭合 + 本报告 | `4df1ad5`（fix）+ `d315abb` | R34b PASS（R34 两项修订并入：Decimal seam 五处闭合、canonical 措辞修正） |

## 首批规模核对（计划 Phase 3「首批规模」原文逐条）

| 要求 | 实测 |
|---|---|
| Math 10–15 cases | **12**（M-01…M-12） |
| Quant 10–15 cases | **12**（Q-01…Q-12） |
| golden successes 每领域至少 3 个 | champion 每领域 **12/12 pass**（regression split 3 个为 golden 基线） |
| metamorphic 每领域至少 3 组 | **G1/G2/G3 三组**，每组 2 例（metamorphic-public split 各 6 例，ledger 逐例注记组号） |
| known-bad evaluator mutations 至少 6 个 | **6 个实例全部检出**：invert_verdict ×1、drop_condition ×3（regression/critical_safety/privacy）、relax_resource_limit ×2（×10、×100） |

split 分布（每领域）：smoke 1、development 2、regression 3、metamorphic-public 6。challenger 在 M-02/M-08/M-12 与 Q-03/Q-09/Q-11 故意答错（设计内回归探针），其余与 champion 相同。

## 验收 Gate 逐条证据（计划 Phase 3「验收 Gate」原文）

| Gate 原文 | 证据（`tests/integration/test_public_benchmark.py`，14 项） |
|---|---|
| known-good/known-bad 稳定区分 | `PublicMetaTest::test_known_good_known_bad_stably_distinguished`：真实树工件 golden→pass、known-bad→fail，`known_pair_check` detected |
| mutation tests 能发现反转 PASS/FAIL、移除条件、放宽资源等故障 | `test_six_known_bad_mutation_instances_are_detected`：六实例全部 detected 且 detail 点名 probe；`test_unmutated_control_is_never_detected` 阴性对照三 mutation 类全不 detected |
| Candidate 不能修改 case、scorer 或 report | `test_candidate_cannot_modify_case_scorer_or_contract`：篡改 case → suite pin 不符 ValueError；调用方指定与合同不同的 scorer level → ValueError；篡改合同 → 与 case 内 contract pin 哈希不符 |
| 相同 seed/config 产生可解释的重现结果 | `test_pipeline_is_deterministic`（同窗格重跑逐位相等）+ `test_compare_is_deterministic_and_rejects_bad_pairings`（同参 compare 两次逐位相等；seed 20260816 随报告留痕） |
| 不以 20—30 cases 的小样本总准确率声称统计显著提升 | `test_small_sample_limitation_present_in_every_report`：24 份报告全部自动携带 `small_sample_limitation` 句（math n=1、quant n=2 共享维度）；无任何显著性声称 |
| 报告绑定全部必要 hash | `test_reports_are_schema_valid_and_hash_bound`：report 的 champion/challenger pin == run 记录哈希；run 绑定 case/suite/candidate/envelope/scorer/output 哈希（E7 装配层）；发布闭环 `PublicationGraphTest` 全图验证 |

## 发布闭环与图验证

`PublicationGraphTest::test_publish_all_records_and_verify_graph`：临时 store 发布 **98 条记录**（suite 2 + case 24 + run 48 + report 24，全部 `already_present=False`），`verify_record_graph` **ok=true、零 violation**，families 精确为 `{suite/v1: 2, evaluation-case/v1: 24, evaluation-run/v1: 48, comparison-report/v1: 24}`。无新写入面——发布全部经 core 既有 `publish_record`（决策 3）。

## 已知限制（随 v0.4.0 Release notes 声明）

1. **仅覆盖 L0/L1**：协议评测与冻结工件 replay；不把离线 runner 说成完整 Agent 评测（Phase 3 目标原文）；L2–L4 不在本 Phase。
2. **E2 schema 缺口（R33 头条裁决 (E)）**：`evaluation-run/v1` 的 required 含 `output` 与 `score_vector`，而 verdict 枚举含 `error`/`inconclusive`——两态结构性不可装配。处置为 fail-closed：`evaluate_case` 对该类结果返回 `run_payload=None` + 显式 `unpublishable_reason`，不编造分数、不设哨兵哈希；error run 既不可发布也进不了 `compare`（双向围堵）。**v2 successor 候选已登记计划 Phase 4 backlog**（按 verdict 条件化 required，由真实发布需求驱动，不在 Phase 3 中途开 v2，不动 ADR-0006）。
3. 统计复现性绑定运行时：报告 `environment` 字段记录解释器实现与版本（CPython 3.14.5）；跨环境复核需同版本解释器（R31 账本）。
4. structured_rubric / calibrated_judge 两级本 Phase 只打包外部评分、不在仓内发明分数；首批公开 suites 使用 oracle 与 deterministic_checker 两级。

## E8 集成测试的两个真实捕获（本层核心价值，如实记录）

1. **Decimal seam bug（P2，跨层，五处闭合）**：core 严格 JSON 解析器按 Phase 1 冻结设计把 JSON 分数解析为 `Decimal`，而 E4–E7 的若干数值哨卫只认 `int`/`float`。E8 集成首跑命中评分层三处（`_require_finite_number`、`_json_equal` 数值分支、`_numeric_tolerance` 输出值类型检查——第三处由新回归测试当场捕获）；**R34 审核探针再捕获两处**：`pipeline._record_sha256` 用裸 `json.dumps`（store 载回的 run 其 score_vector 含 Decimal 即不可序列化——「从 append-only store 载回 champion run 与新 challenger 再 compare」这条设计工作流在两种统计方法下双双断裂）与 `statistics.paired_bootstrap` 元素校验。五处全部修复：接受 `Decimal`、bool 仍先拒、`Decimal('NaN')`/`Infinity` 仍拒；statistics 入口早转 float；装配层改走 core canonical 机器（store 自身往返本就依赖它）。回归测试 7 项：scorers `StrictJsonDecimalTest` 4 项、statistics `DecimalInputTest` 2 项、pipeline `StoreRoundTripTest` 端到端 publish→load→compare 1 项。此前 474 项单测漏网原因：E3–E7 单测全部在 Python 内直接构造 float/int，从未经 `load_strict_json` 真实往返；E8 首次以真实 JSON 驱动全管线即命中。benchmark 数据与全部 pin 零改动（修复在评分/统计/装配层）。跨型精确语义边界记录在案：`Decimal('0.1') == 0.1` 为 `False`（benchmark 流两侧同为 JSON 加载故内部一致；混写手构 float oracle 与 Decimal 输出会假阴性，known-good meta-test 兜底）。
2. **Q-05 stale pin（数据树缺陷）**：生成器留下的 `quant/cases/Q-05.json` 合同 pin 与实际合同文件不符（`09e321ae…` → 实为 `566d8210…`）。管线测试不会捕获（合同哈希只是字段），树完整性测试当场捕获。修复沿 pin 链重算三文件（case → suite → registry，全部 core canonical 字节写回）：case 新哈希 `6c0a3188…`，quant suite 新哈希 `7bbcda41…`。

## 边界声明

- 首批公开 suites 全部 **SYNTHETIC**：case 标题带 `[SYNTHETIC]`，`contamination-ledger.json` 24 条全 clean 并注明"Synthetic case authored for this benchmark; no public-corpus source"；无任何真实市场/真实 archive 证据，无收益主张；
- 集成测试不打网络、不读时钟（runner 唯一时钟为注入式单调时钟）、不写临时 store 以外的任何路径；
- meta-test 的 oversize probe 为测试内派生工件（标注），树驱动主管线不变。

## 全程 Gate 证据

- 双环境（PATH `python` 与 `.venv/Scripts/python.exe`，均 CPython 3.14.5——R29 起如实记录为「双环境同版本」）全量 **520/520 OK**（E7 基线 499 + E8 集成 14 + Decimal 回归 7：scorers 4、statistics 2、pipeline 端到端往返 1）；
- 零漂移：`schemas/`、`tests/fixtures/`、`src/research_evolution/core/`、`src/research_evolution/adapters/`、`tests/contract/`、`tests/adapter_contract/` 相对 `ab3838e` **0 行**（精确 pathspec）；本层 src 改动仅 evaluation 包的 Decimal 闭合——`scorers.py`、`statistics.py`、`pipeline.py` 共五处（上文已披露）；
- 卫生：`git diff --check` clean、pycache 0、新 JSON 全部 LF；pin 链三层语义如实——suite/case 记录字节 canonical（集成测试逐文件钉死）、contracts 按 canonical 内容哈希钉、inputs/artifacts 按 raw 字节钉（candidate manifests 48 个 pin 全对）；恰 3 个 Q-05 文件字节非 canonical（`0.0` token，canonical 模型归一为 `0`），与各自 pin 语义相容（R34 独立重算确认）；
- R27–R33b 七轮审核发现全部闭合；R33 三项附加条件中「验收报告记录缺口」「Phase 4 backlog 登记」由本报告与本层兑现，「v0.4.0 Release notes 声明」待发布时点执行。

## Git/Release Gate 备注（供合并/发布时点使用）

- 变更清单：八层 commit 逐层对应 E1–E8（见上表）；
- 回滚说明：revert 八个 commit 即可，无 schema 迁移；注意点——回滚后 `evaluation` 包与四评测 family 不存在，core/adapters 行为不变；
- 合并后 main 终验：双环境全量 + 冻结面漂移核查 + 删除测试复跑；
- v0.4.0 annotated tag 指向 main 已验收合并提交；tag 与 GitHub Release 两个动作分别留证；Release notes 引用本报告与 ADR-0006，**必须声明「仅覆盖 L0/L1」与上文已知限制第 2 条（E2 schema 缺口）**；四动作（Tag/Release/Skill 安装/Champion promotion）按计划 §3.1 分别留证；
- PR 附件：一份可公开 evaluation report 由 `benchmarks/public/` 树经 `render_json/render_markdown/render_html` 生成（集成测试三形态断言保证同源）。

## R34 收尾记录

- R34 终审：REVISION_REQUIRED——Decimal seam 第四/五处（store 载回 run 再 compare 的设计工作流断裂）与 canonical 措辞失实两处；
- R34b 增量复核：PASS——修复全部落地并经审核方独立复现（含超出回归覆盖的额外探针：全方法组合 policy、store 载回 case/suite + Decimal rubric 端到端装配）；
- commit 拆分按批准方案执行：Decimal seam 修复 `4df1ad5`、E8 `d315abb`；本收尾 commit 仅动本报告状态行、映射表与本段（无法含自身未来哈希，与 1C/1D/2 同一形态）；
- 连带捕获（E8 提交时点）：`.gitignore` 的裸 `artifacts/` 规则曾静默吞掉 48 个 pin 工件——已加 scoped 反规则 `!benchmarks/public/*/artifacts/` 并随 E8 commit 入树（若漏网：克隆后集成测试全红、candidate manifest pin 指向不存在的字节）。
