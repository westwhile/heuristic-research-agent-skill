# Phase 5 L6：ML/Quant 重合逻辑分析（2026-08-21）

状态：**结论先于动作；本轮不下沉 Core。** 本报告比较的是当前
`MLAdapter` 与 `QuantAdapter` 的实际实现，不把接口形状相似误写为语义一致。

## 下沉判据

ADR-0008 决策 7 要求三个条件同时成立：

1. 逻辑不含领域词汇并通过 Core `_BANNED_TERMS` 纪律；
2. ML 与 Quant 以完全相同的语义调用；
3. 双领域合同测试钉住该共同语义。

任一条件不成立，逻辑继续留在 Adapter。即使三项形式上成立，仍需通过
module depth 检查：移动后必须减少调用方需要理解的复杂度，而不是把几行
映射包装成浅层转发接口。

## 候选逐项裁定

| 候选逻辑 | 无领域词汇 | 两域语义相同 | 双域合同钉选 | 裁定 |
|---|---:|---:|---:|---|
| Task normalization 外壳 | 是 | 否：domain context 与 domain-task schema 版本不同 | 现有套件只钉 interface 形状与纯度 | 留在 Adapter |
| case gate → required evidence 的有序去重 | 是 | 当前实现基本相同 | 否：未跨 ML/Quant 钉住顺序与重复 gate 语义 | 暂不下沉 |
| promotion-bar 比较 | 是 | 否：ML 要求恰好一个适用 bar；Quant 的匹配与错误面不同 | 否 | 留在 Adapter |
| evidence sequence 加载与 no-evidence 处理 | 部分 | 否：可接受版本、study/case/final split 绑定和 provenance 纪律不同 | 否 | 留在 Adapter |
| canonical hash、schema load 与 exchange types | 是 | 是 | 是 | 已由既有 Core/Adapter 公共机器共享，无新增动作 |

## 结论

本轮 **不修改** `src/research_evolution/core/`、Core schema、Core family registry
或 Adapter interface。`case gate → required evidence` 是唯一可能的后续候选，
但当前缺少第三项证据，而且抽取后的 interface 相对十余行实现过浅；在出现
第三个同语义调用方、重复缺陷或明确维护成本前，不建立新 seam。

本结论不妨碍既有三 Adapter 继续通过同一参数化 contract suite。该套件证明
三操作 interface 成立，不证明每个 Adapter 的内部政策应合并。

## 复核触发条件

只有出现以下任一事实时重新打开下沉判断：

- ML 与 Quant 在相同 gate 去重/排序行为上发生重复缺陷；
- 第三个领域 Adapter 需要完全相同的逻辑；
- 新双域 contract test 能在不读取领域词汇的情况下表达完整语义；
- 删除候选 module 会让同一复杂逻辑重新散落到至少两个调用方。

在此之前，保留少量重复优于把领域政策带入 Core。
