# Adapter schemas

Math、Quant、ML 和 Deep Learning 的领域扩展。领域字段不得回流到 Core schema。

当前版本化 seam schema（ADR-0005，由同一 Core schema 引擎校验、独立 schema_root）：

- `domain-task/v1` → `domain-task-v1.schema.json`
- `claim-assessment/v1` → `claim-assessment-v1.schema.json`
- `evaluation-contract/v1` → `evaluation-contract-v1.schema.json`

Seam 类型是 Adapter 层交换合同，不是 Core 记录 family：不进 `_families.py` registry、不可发布到 Core store；默认 Core schema_root 拒绝这些 id（`SeamBoundaryTest` 钉选）。
