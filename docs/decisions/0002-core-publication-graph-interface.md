# ADR-0002：Core 发布/图校验接口与架构三操作的对齐

- 状态：Accepted for Phase 1B
- 日期：2026-08-15

## 背景

总体架构 §4.1 把 Core interface 描绘为三个高杠杆操作：`validate_and_freeze_task`、`publish_record`、`verify_record_graph`，schema 分派、hash、lineage、append-only 与 manifest 隐藏在实现内。Phase 1A 实际交付的是 `load_record`（解析 + 分派 + 校验 + hash 绑定）与 `Record`，没有写路径。Phase 1B 引入 create-new/append-only 发布、supersedes/lineage 校验与 manifest 全图验证，需要固定两个接口集合的对齐方式，避免 interface 漂移。

## 决策

1. 保留 `load_record` 与 `Record` 的 Phase 1A 公共合同，不改名、不改语义；架构的 `validate_and_freeze_task` 暂不实现——若它只是 `load_record` 的 Task 限定包装，就是浅层 interface；等出现真正的额外冻结语义（如冻结时绑定外部资源快照）再以新版本引入。
2. 新增 `publish_record(source, *, root, schema_root=None)` 与 `verify_record_graph(root, *, schema_root=None)` 两个公共操作，覆盖架构的同名操作；发布只接受调用方显式传入的本地 repository root，本批不支持跨项目导出。
3. 存储为**内容寻址**：记录文件名为 canonical SHA-256，逻辑 id 只出现在 manifest 索引中。schema 允许任意非空白 id（含 `/`、Windows 设备名、仅大小写不同的变体），用 id 直接作文件名会把路径逃逸与文件系统别名风险引入存储层。
4. manifest 是**派生索引**而不是事实源：确定性 canonical 序列化，可由磁盘记录集完整重建；验证时重建并逐字节比对，任何缺失、额外、重复、hash 不符或非 canonical 改写均 fail-closed。
5. lineage 以记录内嵌 `supersedes` 字段为准（当前仅 `research-claim/v1` 声明该字段），不复制进 manifest；否则谱系不再 hash-bound 进记录本身，manifest 篡改将不可检出。fork（多条记录 supersedes 同一前驱）不判错，Core 不提供"自动选择最新版本"语义。
6. 本批只有本地文件系统一种存储实现，经临时目录测试；不公开只有单一实现的 Storage Adapter 端口。
7. **containment 边界是调用方传入的词法 root 本身**：root 的每个现存词法组件（含全部祖先；相对 root 先对单一入口 cwd 快照做纯词法绝对化（绝不 resolve；Windows drive-relative 形式 fail-closed）——cwd 自身位于 junction 之下同样检出）及存储表面每个节点（`manifest.json`、`records/`、`.tmp/`、records 树内一切）都不得是 symlink/junction/其他 reparse point，发现即拒绝（verify 报 `reparse_point`，publish 抛 `StoreIntegrityError`）；绝不跟随 resolved target 写入或作证。检测基于 lstat，Windows 上检查 `FILE_ATTRIBUTE_REPARSE_POINT`，覆盖全部 reparse tag；stat 因"不存在"以外的原因失败时节点视为不可判定并 fail-closed——"无法判定"绝不当"安全"。verify 的 root preflight 在任何加锁之前完成，进程内锁键为钉死路径的纯词法 `normcase`、绝不 resolve、不再读取进程 cwd，因此敌对或损坏的 root 得到的是 violation 而不是泄漏的 I/O 异常。两个公共操作在入口（任何校验、registry 查找或其他可回调工作之前）**只捕获一次**进程 cwd 快照，并由该同一快照把 root 与非空 `schema_root` 同时**钉死**为词法绝对路径（Windows drive-relative 形式无法由单快照无歧义钉死，fail-closed），之后 preflight、锁键、对账、`load_record` 与全部 I/O 均使用钉死路径、不再读取进程 cwd——调用中途的进程内 cwd 变更既无法分离被检查对象与被写入/验证对象，也无法把记录校验重定向到另一套 schema registry，亦无法利用两次钉死之间的窗口使两者绑定不同基准目录（cwd 是进程级全局状态，与冻结数值协议拒读 `sys.setrecursionlimit` 同类）。发布前的写前对账要求 findings 集合严格等于"待发布记录自身的 `extra_record`"才允许收养——manifest 确定性检查与其他 findings 相互独立，任何篡改都不能借孤儿例外掩盖。
8. **逻辑 id 的唯一性合同是全局的**：同一 id 出现在两个及以上 family 是 fail-closed 的 `duplicate_id` violation（图阶段；每个碰撞 id 一条，detail 按序列出全部涉及 family，输出按 id 排序保证确定性）。判据与 fork 对称：fork 是合法的科研分歧、承载意义，所以只作信息位；而跨 family id 碰撞永远不承载合法语义——只能是命名事故或篡改。引用字段虽带类型、机器解析不会解错，但 id 是人类与审计跨 family 引用记录的方式（"参见 x-1"），碰撞时无法消歧。现在固化该合同成本最低：store 是全新的、无存量数据，violation 合同的消费者只有本仓库的 contract 测试。若未来确有 per-family 命名空间的正当需求，需新 ADR 论证。同 family 同 id 出现在多个文件属完整性阶段的 `duplicate_record`，两者 detail 文案互相点名边界以防混淆。

## 后果

优点：

- Phase 1A 合同零破坏，已有 53 个 fixtures 与 golden hash 不变；
- 写路径、lineage 与全图验证集中在一个深 module 内，调用方只看到两个新操作；
- 内容寻址免除 id→文件名的一切规范化与别名问题，原子创建（临时文件 + 同卷硬链接）天然禁止覆盖；
- manifest 可重建、可逐字节核对，满足 append-only 审计；
- 逻辑 id 全局唯一性在图阶段 fail-closed（`duplicate_id`），身份歧义进不了证据图。

代价：

- 文件名不可读，需要经 manifest 或记录内容反查逻辑 id；
- 跨进程并发发布不在本批保证范围内（仅进程内按 root 串行化）；
- Task/Evidence 无 `supersedes` 字段，其"修订"语义是新 id 新记录，是否在未来版本补充该字段留待后续 ADR。

## 拒绝的方案

1. 立即实现架构三操作全套：`validate_and_freeze_task` 目前只会是浅包装，违反深模块原则；
2. 抽象 Storage Adapter 端口：单一实现时是假想 seam，与 ADR-0001 拒绝方案 3 同一原则；
3. 以逻辑 id 作文件名：把 `^\S+$` id 空间的全部文件系统危害引入存储层；
4. 把 `supersedes` 移入 manifest 而非记录：谱系脱离 hash 绑定，违背 append-only 事实记录原则；
5. 以 `root.resolve()` 的结果为实际 containment root：调用方审阅与授权的是词法路径，跟随 junction 会把写入静默重定位到另一棵目录树；词法 root 必须本身就是可信边界。
