# staging/research-memory/ — Research Memory 隔离暂存区

定稿名（ADR-0007 决策 10 拟名，M6 定稿）：本仓 Research Memory
合成资格证据的唯一写入区。Phase 5 L6 继续复用该隔离区，不新增 ML store
family，也不改变 Phase 4 的发布、安装与激活边界。

## 隔离纪律

- 本目录**不是** Skill 根，也不在任何自动发现 Skill 根内：子树中不存在
  `SKILL.md`，路径任一组件都不是 `skills/`（集成测试钉住）。
- 本目录始终**只暂存、不安装**：不创建正式子 Skill，不执行 Skills
  Manager 写操作，不激活 Default/Preset/Champion（计划 Phase 4 Git/发布
  Gate；ADR-0007 决策 10）。
- 这里的一切都是**合成/脱敏**资格证据（ADR-0005 决策 9 先例）：无真实
  项目内容、路径或身份。真实私有数据零进入仓库。

## 内容

- `evidence/math/`、`evidence/quant/`：各 3 个合格
  `research-case-package/v2`（builder 捕获、eligibility=eligible）与各 2
  条 candidate pattern 链（`distilled` 根版本 + `candidate_pattern` 末梢
  版本，逐版本一份文件）。
- `evidence/abstain/retrieval-session.json`：一次正确 abstain 的检索会话
  artifact（冻结签名与全部在册 pattern 零交集，显式 `abstained`）。
- `evidence/ml/`：Phase 5 L6 的 4 个合成 ML Case Package（完整协议、负
  结果、泄漏修复、复现差异）、1 条两版本 candidate Pattern 链、3 条
  `lesson_hypothesis → candidate → shadow` Heuristic 链、1 份 linter
  artifact 与 1 份 shadow report。全部 Case/Pattern/Heuristic 通过 Phase 4
  公共 experience interface 重建；Pattern 只由两个独立 eligible Case
  蒸馏，Heuristic 最高态为 shadow。
- `manifest.json`：逐文件 SHA-256 与生成参数的哈希绑定清单。

## 重建与验证

`tests/integration/test_experience_evidence_pack.py` 与
`tests/integration/test_ml_research_memory_pack.py` 通过公共 experience 面
逐字节重建全部 artifact 并复核 manifest——树上任何字节漂移都会使测试
失败。Core record 使用 canonical 字节并通过 32-record 临时 store 图闭包；
ML capture、lint 和 shadow report 是明确的 registry/staging artifact，
不是 Core family，也不可冒充可安装 Skill。

Phase 5 L6 的全部结果仍只属于 **synthetic engineering evidence**：不构成
真实数据验收、预测/市场证据、真实 ML 执行器或生产科研 Agent 证据。
