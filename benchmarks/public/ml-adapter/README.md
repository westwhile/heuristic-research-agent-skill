# ML Adapter synthetic case catalog

`catalog.json` 是 Phase 5 L5 的 **SYNTHETIC** ML Adapter 合同目录，不是 Phase 3 evaluator 的 `suite/v1`，也不进入 `benchmarks/public/registry.json`。它不使用真实或私有数据，不报告模型质量、真实泛化或科研结论。

目录固定收录 20 个 hash-pinned cases：

- 4 个合同正例：IID、group、time-series、nested 各 1 个；
- 12 个声明式泄漏负例：覆盖六规则族、七个独立谓词；
- 4 个语义下限负例：split 参数外形与 seed 数下限。

每个 locator 指向 `tests/fixtures/adapters/ml-case/v1/valid/` 中 schema 合法的 `ml-case/v1`。这里的“负例”指必须被 Adapter 语义 Gate 拒绝的载荷，而不是结构非法 JSON。目录记录 repository-normalized raw SHA-256：文本先按 `.gitattributes` 的 `eol=lf` 将 CRLF 规范为 LF，再计算原始字节 hash；除换行外的格式、空白和键顺序仍受 pin 约束。E2E 测试同时验证 locator 边界、hash、预期接受/拒绝结果和 rule ID。

两条 L5 垂直切片不伪装成 catalog case：它们由 `tests/e2e/test_ml_vertical_slices.py` 构造小型内存数据，分别执行 group 非时间切分与带 gap/embargo 的 time-series 切分，并走完 task normalization、Core task、contract、runner evidence 与 claim assessment 公共链。

PowerShell 7 验证入口：

```powershell
$env:PYTHONPATH = 'src'
.venv\Scripts\python.exe -B -m unittest tests.e2e.test_ml_vertical_slices -v
```
