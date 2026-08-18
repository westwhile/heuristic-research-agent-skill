# Research Pattern Library Layout Contract

- 状态：合同文档（计划 Phase 4 任务 19 交付物；ADR-0007 决策 10；gate 10）
- 定稿：M6（`feat/research-memory-pattern-registry`）
- 适用范围：`$SKILL_LIBRARY_ROOT` 指向的中央库与本仓 Phase 4 暂存区

## 1. 布局

中央库逻辑布局以可配置 `$SKILL_LIBRARY_ROOT` 为根；任何记录、schema
或公共文档都不得写入本机绝对路径（计划 §3.1）。

```text
$SKILL_LIBRARY_ROOT/
├── skills/                         # 仅正式、可安装的 canonical Skill
├── research-patterns/
│   ├── math/
│   ├── quant/
│   ├── ml/
│   ├── dl/
│   └── project-engineering/
├── skill-incubator/
│   ├── candidates/
│   ├── evaluations/
│   ├── rejected/
│   └── archived/
└── catalogs/                       # pattern/skill 索引与兼容元数据
```

该目录正式命名为 **Research Pattern Library（研究模式库）**，不命名为
"特征库"，以避免与量化/机器学习语境的 feature store / feature registry
混淆（计划 §3.1 原文）。

## 2. 隔离规则（gate 10）

- `research-patterns/` 与 `skill-incubator/` **必须位于**自动发现的
  `skills/` 之外；否则草稿或历史经验可能被运行时误加载（计划 §3.1）。
- `skills/` 只承载正式 canonical Skill；候选、评估、拒绝、归档四态全部
  在 `skill-incubator/` 内，永不直接进入 `skills/`。
- 本合同在仓内的可执行钉选：`staging/research-memory/` 子树无
  `SKILL.md`、路径不经过任何 `skills/` 组件
  （`tests/integration/test_experience_evidence_pack.py`）。

## 3. catalogs/ 可重建原则

`catalogs/` 是 pattern/skill 索引与兼容元数据的**派生层**，不是事实源：
事实源是 append-only store 中的记录本体；任何 catalog 都可由记录全量
重建（ADR-0007 决策 4 的 registry 层边界同原则）。catalog 与记录冲突时
以记录为准，catalog 重建后必须一致。

## 4. Phase 4 暂存纪律

- 本仓 Phase 4 只写隔离暂存区 `staging/research-memory/`（定稿名，
  ADR-0007 决策 10 拟名的 M6 落实），不安装 Skill、不执行任何 Skills
  Manager 写操作、不创建 production Champion。
- 暂存证据全部为合成/脱敏级并如实标注（ADR-0005 决策 9 先例）。
- 暂存区 artifact 进入中央库的唯一路径：经未来 Phase 的显式迁移动作，
  逐记录验证哈希后 append 入 store；不存在静默同步。

## 5. Migration policy

- **记录不可变**：已发布记录永不原地修改；内容演进走 successor 版本
  （schema 家族扩词表或字段变更只能走新 schema 版本，ADR-0004 决策 1；
  对象级演进走 `supersedes` 链新版本，ADR-0007 决策 3，successor 由链
  反向导出，不落前向指针）。
- **哈希绑内容不绑位置**：记录 pin 是 canonical 内容哈希；库根迁移或
  目录重组不改变任何哈希。引用一律用相对 locator，禁止绝对路径。
- **迁移后重建**：任何 layout 迁移完成后，`catalogs/` 与 registry 层
  索引（pattern/heuristic index、cluster 事件重放）必须从记录全量重建
  并与迁移前逐位一致；不一致即迁移失败，回滚目录动作。

## 6. Retirement policy

- **退休是可见性语义，不是删除**：pattern/heuristic 的
  `deprecated`/`retired` 终态使其退出检索可见面（retrieval 只见
  candidate 及以上非终态末梢），记录本体在 append-only store 中永久
  保留，历史 run 对旧版本的 pin 永不失效。
- **incubator 去向**：`rejected/` 收被拒草稿，`archived/` 收撤回草稿；
  两者都不是 store 记录，移动属 registry 层草稿操作，须留操作注记。
- **隐私退役**（删除内容本体而非仅改状态）超出 Phase 4 范围，需要时以
  新 ADR 单独决策；本合同不预建该机制。
