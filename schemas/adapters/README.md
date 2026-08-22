# Adapter schemas

Math、Quant、ML 和 Deep Learning 的领域扩展。领域字段不得回流到 Core schema。

当前版本化 seam schema（ADR-0005，由同一 Core schema 引擎校验、独立 schema_root）：

- `domain-task/v1` → `domain-task-v1.schema.json`
- `domain-task/v2` → `domain-task-v2.schema.json`（ADR-0008 L2 增补：domain 词表扩为 math/quant/ml；v1 保持冻结并对 math/quant 生产者继续有效，第四领域走下一版本）
- `claim-assessment/v1` → `claim-assessment-v1.schema.json`
- `evaluation-contract/v1` → `evaluation-contract-v1.schema.json`
- `evaluation-contract/v2` → `evaluation-contract-v2.schema.json`（ADR-0008 增补 A3：study_id + assessment_declaration 绑定面；字节冻结并继续注册）
- `evaluation-contract/v3` → `evaluation-contract-v3.schema.json`（ADR-0008 增补 A6：在 v2 绑定面上增加由 case 派生的 selection partition、selection pin 与 split pin；ML Adapter 自 L4 起产出/要求 v3，math/quant 仍使用冻结 v1）

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

ML 领域载荷 schema（Phase 5 L2，同样不可发布）：

- `ml-task/v1` → `ml-task-v1.schema.json`（normalize_task 输入；holdout_policy 必填显式化：task_type/data_spec/holdout_policy + caller 注入 created_at）
- `ml-claim/v1` → `ml-claim-v1.schema.json`（validate_claim 输入；claim_class ∈ engineering/data_acceptance/generalization 三级 Gate）
- `ml-evidence/v1` → `ml-evidence-v1.schema.json`（kind 八值词表 + data_provenance ∈ synthetic/public/real + seeds/frozen_holdout 成熟度驱动字段 + study_id 研究绑定；schema 只固定词表，封顶规则、唯一 seed 计数与 claim↔evidence 绑定强制在 adapter——ADR-0008 增补 A2）
- `ml-evidence/v2` → `ml-evidence-v2.schema.json`（L4/L4.1 final experiment successor：kind 固定 experiment_run，显式携带 case pin、最终评估 partition 与 split pin；case/split mismatch 及 train/validation 不安全值由 adapter 语义层拒绝；非实验 assessment/audit evidence 继续使用冻结 v1）
- `ml-case/v1` → `ml-case-v1.schema.json`（build_evaluation_contract 输入 + 已声明实验拓扑 DAG：dataset/split/preprocessing/sampling/selection 以 {identity, sha256} + input_sha256 上游 pin 互证；必填 assessment 声明段——calibration/subgroup/OOD/drift 四键各含 status ∈ declared/not_performed，声明即证据下限；声明↔结果比对已在 L2 由 adapter 落地——四维恰好各一次的完备性闸（v3 合同侧 dimension 为自由串，完备性由 adapter 强制）+ not_performed 被证据推翻即拒；schema 层允许不安全 scope 值，由语义泄漏规则拒绝（L3 已落地：DAG 结构前置 + 六规则族七谓词 + 三语义下限，见 ADR-0008 增补 A5），保持可证伪）
