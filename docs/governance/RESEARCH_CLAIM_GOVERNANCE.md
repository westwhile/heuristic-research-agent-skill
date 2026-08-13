# 科研结论与证据治理

## 1. Claim 晋级梯子

```text
draft
→ engineering_verified
→ data_accepted
→ evaluation_eligible
→ empirically_supported / mathematically_verified
→ externally_validated
→ production_observed
```

不是每个 Claim 都需要经过全部阶段。例如数学 Claim 走证明/反例路线；量化策略 Claim 必须经过数据、样本外和交易现实检查。任何阶段只能晋级到直接证据支持的层级。

## 2. 通用硬规则

1. 没有 frozen task 和 evaluation contract，不发布比较性结论；
2. 没有 lineage/hash 的 artifact 不能支撑关键晋级；
3. Candidate 与 Champion 资源 envelope 不一致时分层报告，不直接归因于 Heuristic；
4. 未通过数据验收，不运行或不解释下游研究指标；
5. 没有可靠 oracle/evaluation contract 的 case 可用于诊断，不用于关键 Promotion；
6. private/hidden 泄漏、权限扩张或报告篡改直接拒绝 Candidate；
7. `INCONCLUSIVE` 是合法结果，不得为提高完成率强制转为 PASS/FAIL。

## 3. 领域 Gate

### 数学

- M0：问题、定义域和量词冻结；
- M1：Candidate 与证据 hash 绑定；
- M2：独立 verifier 检查；
- M3：局部结果到全局 Claim 有 coverage bridge；
- M4：完成 Claim 具有证明/反例证书及审计结果。

### 量化

- Q0：schema、主键、覆盖率、单位和时间字段通过；
- Q1：PIT、修订、历史样本池和可得时间通过；
- Q2：signal、execution、label 与收益窗口无泄漏；
- Q3：成本、成交限制、仓位、流动性和基准口径通过；
- Q4：时间顺序样本外和 future holdout 通过；
- Q5：才允许形成受限的 empirical/strategy Claim；不得写成真实可获得收益。

### ML

- L0：数据 provenance、重复和 split 冻结；
- L1：预处理、特征选择和调参只使用允许数据；
- L2：基线、指标和模型选择协议预注册；
- L3：重复种子、置信区间、校准和 subgroup/OOD 结果；
- L4：测试集只用于最终确认，失败后不得继续调参并保持同一 holdout 身份。

### DL

- D0：继承全部 ML Gate；
- D1：硬件、驱动、框架、数据和 checkpoint manifest；
- D2：算力、token/sample、训练步数与调参预算公平；
- D3：checkpoint/early stopping 选择无 hidden/test 污染；
- D4：多种子、消融、恢复和失败运行均报告；
- D5：单次最好 checkpoint 不得代表稳定能力。

## 4. 报告最低字段

- Claim ID、类型、状态和范围；
- 数据/case 的版本、split 和 hash；
- 模型、代码、配置、随机种子和环境；
- 主指标、次指标、不确定性和样本量；
- hard gates；
- 与 Champion 的配对差异；
- 失败、缺失和未覆盖范围；
- 明确 non-entailments；
- reviewer/promotion 决策及时间。

## 5. 禁止表达

- 以 `tests passed` 表达研究有效；
- 以 sample/synthetic 结果表达真实数据有效；
- 以回测表现表达未来或实盘收益；
- 以单次训练最佳值表达稳定泛化；
- 以多个 LLM 一致表达数学证明成立；
- 以目录名 `hidden` 表达已经物理隔离。
