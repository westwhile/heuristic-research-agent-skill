# Phase 5 L5 leakage fixture 报告（2026-08-21）

状态：**合成工程证据**。本报告只证明声明式 ML 泄漏 Gate 与 runner split assignment Gate 在冻结 fixtures 上按合同工作；不构成真实数据验收、模型泛化证据或科研结论。

## Case 集合

`benchmarks/public/ml-adapter/catalog.json` 固定 20 个 `ml-case/v1`：4 个合同正例、12 个泄漏负例、4 个语义下限负例。全部 locator 指向仓库内 synthetic fixture，并以 repository-normalized raw SHA-256 绑定（CRLF→LF 后计算，其他格式字节不归一）。目录与 Phase 3 evaluator `suite/v1` 分离，不修改 Core family、public benchmark registry 或 contamination ledger。

| 规则面 | 安全对照 | 必须拒绝的目录 case | 公共入口结果 |
|---|---|---|---|
| fit-before-split | `full.json` 的 train-only/per-fold preprocessing 与 per-fold feature selection | MLC-005、MLC-006 | `preprocessing-fit-full-data` / `feature-selection-fit-full-data` |
| sampling scope | `full.json` 的 train-only/per-fold sampling | MLC-007、MLC-008 | `sampling-scope-unsafe` |
| scope/upstream 一致性 | `full.json` 的安全 scope 均 pin split | MLC-009—MLC-012 | `scope-upstream-mismatch` |
| target encoding | `full.json` 的 per-fold target encoding | MLC-013 | `target-encoding-not-per-fold` |
| tuning 不用保护分区 | 四个正例只用 train/validation | MLC-014、MLC-015 | `tuning-uses-protected-split` |
| selection 不用 test | 四个正例只用 train/validation | MLC-016 | `selection-uses-test` |
| split/seed 语义下限 | IID/group/time-series/nested 四正例 | MLC-017—MLC-020 | `split-parameters-kind-contract` / `tuning-seed-count-floor` |

以上负例本身 schema 合法，均通过 `MLAdapter.build_evaluation_contract` 公共入口触发预期 rule ID。L3 的 drop-rule/branch mutation 测试继续承担“删除或弱化真实谓词会假 PASS”的可证伪义务；L5 catalog 没有复制一套私有 validator。

## 数据级 split assignment Gate

`tests/unit/test_ml_split_execution.py` 经唯一 runner 入口验证：

- IID 只允许 assignment pin，且全部行恰分配一次；
- group 要求每行一个非空 group label，同一 group 不得跨 partition；
- time-series 要求连续递增 session ordinal，排除行恰为 gap/embargo 区间，声明 gap/embargo 不得大于实测隔离；存在 future holdout 时还必须严格晚于 test；
- nested 要求每个 outer fold 划分完整 development 集，每个 inner fold 只能划分对应 outer-train，且 validation folds 各覆盖一次；test 不进入任何 fold。

两条 E2E 还逐项钉住 `ood-assessment-missing`、`subgroup-assessment-missing`、`calibration-not-assessed` 与 `drift-not-assessed`，缺失 assessment 只形成限制报告，不会被补造或抬高成熟度。

独立审核后的 L5.1 又补充 early-future 拒止与 after-test future 正例、IID 漏行、nested outer/inner validation 轮转回归，并把静态纯度扫描扩展到 runner 私有 implementation 闭包。

本轮定向电池为 split 17 项 + catalog/E2E 4 项，共 21/21 通过；runner/split/E2E 合并电池 46/46。工作树双环境全量 **851/851 ×2**；无 `.git`、无 `.venv`、只含 Git 跟踪/非忽略文件的 775-file clean snapshot 双环境同为 **851/851 ×2**，各有 1 个预期 skip（归档中无法执行 Git tracking 检查）；PowerShell 治理 **33 assertions / 6 cases** 通过。

发布 Gate 补充：首个 L5 commit `39d5a88` 的真实 `git archive` 暴露 9 个 CRLF/LF raw pin 漂移，说明上述手工 clean snapshot 不是 release 证据。L5.2 将 pin 改为 repository-normalized raw SHA-256，保留格式敏感性并使工作树、Git blob 与 archive 语义一致；最终 push 仍以修复提交的真实 archive verdict 为准。

## 未覆盖边界

- runner 仍不执行 preprocessing、sampling、feature selection、target encoding 或超参数搜索；
- nested 只执行 fold assignment 隔离验证，模型拟合仍使用顶层 train partition，不声称完成 nested-CV 训练循环；
- 所有数据均为小型合成内存载荷，没有真实 ML 数据、公开 benchmark 性能或外部执行器证据。
