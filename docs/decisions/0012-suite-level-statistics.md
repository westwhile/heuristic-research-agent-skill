# ADR-0012：Suite-level statistics——以 case × seed × frozen envelope 为观测单位

- 状态：Accepted（Correctness Reset CR5）
- 日期：2026-08-25
- 关联：ADR-0006（Public Evaluator MVP）、ADR-0011（attempt/result 拆分）、`comparison-report/v1`、`suite-comparison/v1`

## 背景

历史 `compare()` 把同一 `evaluation-run/v1` 的不同 score dimensions 拼成 paired samples。accuracy、absolute error、latency 等指标含义和量纲不同，不能互相充当独立观测；由此得到的 bootstrap、McNemar、样本量和显著性没有可解释的统计单位。既有 `comparison-report/v1` 已经冻结，不能原地改变字节或语义。

CR5 只修复可直接复现的统计合同缺陷。它不接入真实 Agent runner、不实现 hidden evaluator、不生成 `PromotionDecision`，也不把合成 benchmark 升级为真实科研或外部采用证据。

## 决策

1. **additive successor**：新增 `suite-comparison/v1`；历史 `comparison-report/v1` 继续可读取、渲染、发布和图验证，但公开 `compare()` 构造入口立即 fail-closed，并指向 `compare_suite()`。
2. **观测单位**：每个观测严格等于 `case × seed × frozen envelope`。champion 与 challenger 都必须完整覆盖 suite cases 与预注册 seeds 的笛卡尔积；缺失、额外或重复观测一律拒绝。
3. **candidate-only 轴**：每一对运行必须 pin 同一 case/suite，并逐字相等地回显 envelope、runner、scorer、environment 与 levels。candidate manifest identity/hash 与每个 case 的 candidate output artifact hash 分开建模；同一 candidate manifest 字节不得伪装成两组候选。
4. **逐指标分析**：指标集合必须与预注册 policy 完全相等，不做交集或静默丢弃；方向、primary/guardrail 角色、ROPE、unit 与 guardrail 非劣效界值均在分析前冻结。一个 metric 是一个独立分析，不是一个样本。
5. **推断与效应量**：每个 metric 运行 paired sign-flip permutation、paired bootstrap confidence interval 与 rank-biserial effect size；多指标 p-value 采用 Holm family-wise adjustment。小样本不借助正态近似制造精确性。
6. **最小样本 Gate**：默认至少 30 个完整 pair；不足时每个 metric 的 `inference_status=insufficient_pairs`，即使点估计方向有利也不得升级为 improvement。公开 Math/Quant 合成 benchmark 当前各只有 12 对，因此只验证合同和报告链。
7. **结果语义**：primary 可为 `improvement_supported`、`regression_supported`、`inconclusive` 或 `insufficient_pairs`；guardrail 还可为 `noninferior`。这些是工程统计报告状态，不是安装、激活、发布或晋级决定。
8. **Core 图合同**：suite comparison pin suite 及全部 champion/challenger runs；通用图验证负责 dangling、cross-type、pin、duplicate 与 cycle。候选 manifest 目前只是外部 hash descriptor，待完整 ArtifactRef/实验闭包批次接入 Core 可解析 pin。
9. **报告兼容**：JSON 继续使用 canonical 输出；Markdown/HTML 根据 schema 分派，历史 report 与新 suite report 均可渲染。公开 benchmark 改为每个 domain 一份 suite comparison，而不是每 case 一份伪统计报告。
10. **证据边界**：CR5 的 tests、fixtures 和 synthetic benchmark 只证明统计与图合同按设计 fail-closed。没有真实 Candidate Agent 执行、blind holdout、独立 reviewer、外部采用或科研有效性证据；`PromotionDecision` Gate 继续关闭。

## 后果

### 合并后 PR-B 加固（2026-09-05）

公开 `compare_suite()` 入口现在必须先验证每侧所有 run 的
`(candidate_id, sha256)` 完全相等，再核对报告提供的引用；仅 ID 相同不足以比较。
任一摘要混入、整组摘要替换或缺失 pin 都在统计计算前拒绝。上层 forward-suite
已有的引用校验不能替代直接入口自己的合同；两者必须给出一致结果。

旧 per-case replay 把单题输出用作 candidate artifact，与 suite manifest 是不同
对象。历史记录不修改；此类混合输出引用不能继续构造新的 suite comparison。
公开 synthetic benchmark 的新运行改为 pin 既有完整 manifest，先验证 manifest 的
case→raw-output 摘要映射，再交给 replay 验证实际输入字节，评分输出仍单独保留
canonical hash。没有改变题目、答案、scorer、统计方法、冻结 schema 或历史 fixture。
这只补齐比较对象绑定，不证明 Candidate 改善、独立性或科研有效性。

优点：样本量终于对应可审计的运行对；不同量纲指标不会再被拼接；候选以外的比较轴被冻结；小样本、单位漂移、coverage 漂移和 metric 漂移都会显式失败或 abstain。

代价：调用方必须提供完整 suite grid 和候选 manifest descriptor；历史 `compare()` 调用必须迁移；当前公开 benchmark 因只有 12 对而不会给出 improvement 结论；后续仍需完整 ArtifactRef closure、真实执行器和独立 evaluator。

## 拒绝的方案

1. **原地修改 `comparison-report/v1`**：违反冻结 schema 的兼容政策。
2. **继续按 score dimension 重采样**：观测单位错误，不因增加检验方法而变得有效。
3. **对缺失 pair 做 listwise deletion**：会在分析时改变预注册 suite，且候选失败可能被静默排除。
4. **把全部 metric 标准化后合成样本**：仍混淆观测与测量维度，并隐藏 primary/guardrail 语义。
5. **CR5 直接产出 PromotionDecision**：在完整闭包、真实 runner、hidden suite 和独立评审缺席时制造超出证据的自动晋级面。
