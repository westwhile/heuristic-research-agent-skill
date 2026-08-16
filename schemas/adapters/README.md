# Adapter schemas

Math、Quant、ML 和 Deep Learning 的领域扩展。领域字段不得回流到 Core schema。

当前版本化 seam schema（ADR-0005，由同一 Core schema 引擎校验、独立 schema_root）：

- `domain-task/v1` → `domain-task-v1.schema.json`
- `claim-assessment/v1` → `claim-assessment-v1.schema.json`
- `evaluation-contract/v1` → `evaluation-contract-v1.schema.json`

Seam 类型是 Adapter 层交换合同，不是 Core 记录 family：不进 `_families.py` registry、不可发布到 Core store；默认 Core schema_root 拒绝这些 id（`SeamBoundaryTest` 钉选）。

Math 领域载荷 schema（A3，同样不可发布）：

- `math-task/v1` → `math-task-v1.schema.json`（normalize_task 输入；M0 冻结：statement/object_domain/quantifiers + caller 注入 created_at）
- `math-claim/v1` → `math-claim-v1.schema.json`（validate_claim 输入；result ∈ proof/disproof/partial/inconclusive）
- `math-evidence/v1` → `math-evidence-v1.schema.json`（证书类 proof_certificate/formal_verification vs 计算类，决定成熟度封顶）
- `math-case/v1` → `math-case-v1.schema.json`（build_evaluation_contract 输入；sought 驱动梯级要求）
