# staging/research-memory/ — Phase 4 隔离暂存区

定稿名（ADR-0007 决策 10 拟名，M6 定稿）：本仓 Phase 4 的唯一写入区。

## 隔离纪律

- 本目录**不是** Skill 根，也不在任何自动发现 Skill 根内：子树中不存在
  `SKILL.md`，路径任一组件都不是 `skills/`（集成测试钉住）。
- Phase 4 在此**只暂存、不安装**：不创建正式子 Skill，不执行 Skills
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
- `manifest.json`：逐文件 SHA-256 与生成参数的哈希绑定清单。

## 重建与验证

`tests/integration/test_experience_evidence_pack.py` 通过公共
experience 面逐字节重建全部 artifact 并复核 manifest——树上任何字节
漂移都会使该测试失败。artifact 一律为 core canonical 字节形态，可
直接发布入 append-only store。
