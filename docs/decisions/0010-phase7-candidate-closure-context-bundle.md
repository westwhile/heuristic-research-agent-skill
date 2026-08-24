# ADR-0010：Phase 7 候选清单、字节闭包与 ContextBundle

- 状态：Accepted
- 日期：2026-08-24
- 范围：Phase 7 P7A 基础工程

## 背景

Phase 6 已建立可重放执行与外部试验协议，但 R6B 仍冻结在
`TARGET_FROZEN / ZERO_EXTERNAL_SUBMISSIONS`。Phase 7 不能把“已有候选文件”直接
升级成可安装 Skill，也不能以通过工程测试代替语义复核。进入私有候选评测前，
首先需要三个可独立验证的事实：候选比较对象已经不可变地钉住、候选成员形成
完整字节闭包、交给后续会话的上下文在预算约束下没有丢失安全最小集。

本批只建立这些基础合同，不生成真实 Skill payload，不安装或激活候选，不处理
R6B 参与者材料，也不作任何晋级或发布决定。

## 决策

1. **新增三个 domain-neutral Core family**：`candidate-manifest/v1`、
   `artifact-closure-receipt/v1`、`context-bundle/v1`。三者与图 registry 同提交注册：
   manifest 以 SHA-256 pin 引用至少两个 `research-case-package/v2` 和至少一个
   `research-pattern/v1`；receipt/context 各 pin 一个 manifest。通用图层只验证
   identity、引用存在性与 pin 一致性，不吸收 P7A 组合语义。
2. **Candidate Manifest 是不可变比较声明，不是 payload**：manifest 必须绑定
   baseline、patch、评测 model/reasoning/tools/budget/data/evaluator envelope、成员
   名称/角色/哈希/大小/DAG、明确排除项、风险、rollback、author/reviewer principal、
   authoritative head、未结 obligation、来源 lifecycle 与 context materials。
   author 和 reviewer 必须是不同 principal；source lifecycle 必须逐项、等集合地
   绑定所有 source case/pattern，不能多、不能少、不能换 pin。
3. **字节闭包只有一个纯进程入口**：
   `close_candidate_bundle(manifest, member_bytes, *, closed_at)`。调用方提供精确 bytes；
   Module 不读取文件系统。输入成员集合必须与 manifest 完全相等，逐项 SHA-256 和
   size 一致，baseline/patch/tests 角色齐备，依赖存在、无重复、自环或环，排除项与
   成员不重叠。`artifact-closure-receipt.json` 名称保留给最后生成的 receipt，不能
   预先进入成员集合；receipt 自身再次绑定 candidate、排序后的成员、确定性拓扑序、
   exclusions 与 closure root。
4. **Receipt 的主张上限固定**：`receipt_last=true` 与 `byte_closed=true` 只证明本次
   in-process 输入的字节闭包；`semantic_review_completed=false` 恒成立。它不证明
   内容正确、候选优于 baseline、作者与 reviewer 身份已外部核验，也不授权安装、
   激活或发布。
5. **ContextBundle 只有一个纯进程入口**：
   `build_context_bundle(manifest, *, mode, max_bytes, built_at)`。保留层级固定为：
   `normal` 包含全部 materials，`compact` 包含 compact + minimal-safe，
   `minimal_safe` 只包含 minimal-safe。objective、authoritative head、全部未结
   obligations、全部 invalidated source 声明、omission 清单与四项 false claim 永不
   省略。Module 不因预算压力静默切换模式；所选模式的 canonical bundle 超预算即
   fail closed，尤其 minimal-safe 超预算也必须拒绝。
6. **来源失效同时作用于闭包和上下文**：`corrected`、`retracted`、
   `license_blocked` 任一状态都会阻止 Artifact Closure Receipt；ContextBundle 仍可
   构建，但必须无遗漏地携带这些 invalidated source，供后续会话停止晋级或回溯。
7. **不预造 Adapter seam**：当前只有一套 in-process 实现，因此没有 port、plugin、
   repository 或 I/O service 抽象。公开面只暴露上述两个函数及其 immutable result/
   error 类型；未来只有出现第二种真实实现且合同测试成立时才重新评估 seam。
8. **跨域证据只证明 seam**：Math 与 Quant 使用两份合成 fixture 穿过完全相同的两个
   interface，覆盖正常、compact、minimal-safe、字节/哈希变异、DAG 环、principal
   重合、来源失效、预算不足和 wrapper mutation。fixture 不构成数学结论、市场证据、
   真实采用或候选晋级证据；domain 词汇不进入三个 Core schema。
9. **本批状态上限**：P7A 合并最多证明 artifact-closure/context 基础工程可用。
   `installation_authorized`、`activation_authorized`、`publication_authorized`、
   `semantic_review_completed` 在 manifest/context 中全部固定为 false。本批不生成真实
   Skill payload，不触碰 `skills/staging/`，不实施 fresh-session 评测或 Phase 8。

## 结果

收益：

- 候选输入、评测 envelope、来源和回滚条件成为严格、hash-bound 的机器合同；
- member mutation、遗漏、额外字节、DAG 环与来源失效都在签发 receipt 前失败；
- 上下文压缩是调用方显式选择的可审计模式，omission 可见且安全最小集不会被预算
  压力悄悄删除；
- Module 无文件系统、网络、安装或 activation 副作用，便于 exact archive 重放。

代价与保留风险：

- byte closure 不等于 semantic closure；author/reviewer principal 是协议标识，不是
  身份认证；
- v1 将成员角色、三档 retention 和 source lifecycle 枚举冻结，扩展必须走 successor
  schema 与新 ADR；
- ContextBundle 的预算针对 canonical record bytes，不是未来模型的 token 估算；
- 真实候选 payload、独立 reviewer、fresh-session 评测、中央库隔离与晋级状态机仍属
  后续批次，不能由 P7A 结果推断。

## 拒绝的方案

1. **直接把候选目录打 ZIP 后视为闭包**：无法证明成员声明、依赖、排除项和 receipt
   生成顺序，且 ZIP 成功不代表语义完整。
2. **预算不足时从 normal 自动退化到 compact/minimal-safe**：会把调用方请求悄悄
   改写成更弱上下文，掩盖遗漏；改为明确模式或失败。
3. **只记录当前有效来源，删除失效来源**：会让后续会话失去停止晋级的关键证据；
   invalidation 必须保留。
4. **现在引入 ArtifactStore/ContextProvider Adapter**：当前没有第二个实现，抽象只会
   暴露更多表面并制造虚假可替换性。
5. **让 closure receipt 表示评审完成**：字节一致性无法推出语义正确性或独立评审，
   因而该 claim 在 v1 固定为 false。
