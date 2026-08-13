# ADR-0001：通用内核与领域 Adapter

- 状态：Accepted for bootstrap
- 日期：2026-08-13

## 背景

项目最初从 `math-research-solve` 的 Heuristic Learning 与 Evaluator 升级出发，但未来需要支持量化、机器学习和深度学习科研。数学证明具有较强 oracle 和特有的 Goal/Verifier/Audit 状态机，而实证研究依赖数据、实验设计、不确定性和样本外验证。

## 决策

建立不包含领域术语的通用科研治理内核，并通过 Math、Quant、ML 和 DL Adapter 接入领域规则。现有 `math-research-solve` 作为 Math executor/baseline，而不是 Core。

Adapter seam 只有在 Math 与 Quant 两个真实 Adapter 的 contract tests 同时通过后才视为稳定。

## 后果

优点：

- 防止数学状态机绑死其他科研工作流；
- 同一套证据、case、candidate 和 promotion 治理可跨领域复用；
- 领域规则集中在 Adapter，便于测试和升级；
- Hidden Evaluator 与 Candidate 权限隔离可以统一实现。

代价：

- 初期必须同时建设两个 Adapter，开发量高于单一数学方案；
- Core interface 需要经过双领域垂直切片才能冻结；
- 不同领域的评价不能压缩成一个总分。

## 拒绝的方案

1. 直接扩展 `math-research-solve`：会把 proof/quantifier/Goal 语义扩散到所有领域；
2. 为四个领域复制四套平台：会造成 schema、权限和 Promotion 规则漂移；
3. 一开始建立大量 Adapter interface：在只有一个实现时属于假想 seam，接口容易浅而复杂。
