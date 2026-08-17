# Public benchmark（首批公开 suites，E8）

**全部内容为 SYNTHETIC 公开数据**：case 标题带 `[SYNTHETIC]` 前缀，`contamination-ledger.json` 逐例登记污染状态（24 条全 clean，均无公开语料来源）。这里没有任何真实市场数据、真实 legacy archive 或收益主张。

## 布局

```text
registry.json                 # Benchmark Registry：两个 suite 的路径 + 记录哈希 pin
contamination-ledger.json     # 污染台账（ADR-0006 决策 11），逐 case 状态与注记
candidates/
  champion.json               # candidate_id + outputs：24 个工件的原始字节哈希 pin
  challenger.json             # 同上；在 M-02/M-08/M-12 与 Q-03/Q-09/Q-11 故意答错（设计内回归探针）
math/  quant/                 # 每领域 12 个 case
  cases/                      # evaluation-case/v1 载荷（split、claim_type、合同 pin、输入 pin）
  inputs/                     # 冻结输入；case 以 content_sha256（原始字节）+ locator 绑定
  contracts/                  # 评分合同（oracle 答案 / numeric_tolerance 参数）；case 以 canonical 哈希绑定
  artifacts/champion/         # champion 冻结输出工件
  artifacts/challenger/       # challenger 冻结输出工件
  suite.json                  # suite/v1 载荷，12 个 case 以记录哈希 pin
```

split 分布（每领域）：smoke 1、development 2、regression 3（golden）、metamorphic-public 6（G1/G2/G3 三组 ×2）。pin 语义分三层：suite/case 记录字节即 core canonical 形式（集成测试逐文件钉死）；contracts 按 canonical 内容哈希钉入 case；inputs/artifacts 按 raw 字节钉（candidate manifests 逐工件 pin）。任何 pin 漂移都会被集成测试当场捕获。

## 验证入口

`tests/integration/test_public_benchmark.py` 驱动整棵树：pin 链完整性 → 双领域 × 双候选 × 12 case 全管线（`evaluate_case`）→ 临时 store 发布 98 条记录 + `verify_record_graph` 全图验证 → 24 份 `comparison-report/v1` 三形态渲染 → evaluator meta-tests（known-pair + 6 个 mutation 实例 + 阴性对照）。运行：

```bash
PYTHONPATH=src python -B -m unittest discover -s tests -p "test_public_benchmark.py"
```
