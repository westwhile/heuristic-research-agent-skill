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

Quant 领域载荷 schema（A4，同样不可发布）：

- `quant-task/v1` → `quant-task-v1.schema.json`（normalize_task 输入；PIT policy 必填显式化：universe/calendar/frequency/pit_policy + caller 注入 created_at）
- `quant-claim/v1` → `quant-claim-v1.schema.json`（validate_claim 输入；claim_class ∈ engineering/data_acceptance/oos_empirical/real_market 四级 Gate）
- `quant-evidence/v1` → `quant-evidence-v1.schema.json`（kind × data_provenance 双词表；kind/provenance 一致性由 adapter 强制，schema 只固定词表）
- `quant-case/v1` → `quant-case-v1.schema.json`（build_evaluation_contract 输入；gates 驱动合同推导，forbidden channels/Q-checkpoints 由 ADR-0005 决策 5 固定）
