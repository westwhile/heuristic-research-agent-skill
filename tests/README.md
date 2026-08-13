# Tests

- `unit/`：单个 module 的实现细节；
- `contract/`：Core 与 Adapter 的稳定 interface；
- `integration/`：多个 module 的端到端 artifact 流；
- `e2e/`：受控 Agent/runner 工作流；
- `fixtures/`：脱敏、合成且明确标记的已知正确/错误样例。

测试通过只支持对应的工程 Claim，不自动支持科研 Claim。
