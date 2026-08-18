# Phase 4 验收报告：研究记忆与 Pattern Registry（待 R40 终审）

- 日期：2026-08-18
- 分支：`feat/research-memory-pattern-registry`（基 `main` = `b459854`，v0.4.0）
- 范围：ADR-0007 的落地——research memory 四 family（case-package/v2、pattern/v1、heuristic/v1、reuse-event/v1）、case builder/redactor/eligibility、Pattern Registry + 分层聚类 + 检索 MVP + reuse 记录、Heuristic Registry + linter + shadow runner、中央库 layout 合同 + 隔离暂存区 + 合格证据包
- 状态：**M1–M5 已逐层提交并经 R35–R39 审核全部 PASS；M6 随本报告交付，待 R40 终审**（R40 后由收尾 commit 回填状态行与 M6 哈希，1C/1D/2/E8 先例）

## 层/commit 映射

| 层 | 内容 | commit | 审核 |
|---|---|---|---|
| M1 | ADR-0007（13 决策 + 后果 + 拒绝方案） | `074b8dc` | R35 PASS（一处引文修正经 amend 落入） |
| M2 | 四新 schema + 61 fixtures + family 注册 13→17 + 图语义 | `0618021` | R36 PASS |
| M3 | case builder + 默认拒 redactor + eligibility gate | `cd4144f` | R37b PASS（R37-P3 三通道周界缺口已修复回归） |
| M4 | pattern registry + 分层聚类 + reuse 记录 | `9598ebc` | R38 PASS（裁拆双 commit） |
| M4 | 检索 MVP（显式 abstain） | `bb6342e` | R38 PASS |
| M5 | heuristic registry + 确定性 linter | `7f15632` | R39 PASS（裁拆双 commit） |
| M5 | shadow runner（3–8 条、假设性决策） | `9d01d6c` | R39 PASS |
| M6 | layout 合同 + 隔离暂存区 + 合格证据包 + 本报告 + 文档批 | 待回填 | 待 R40 |

## 任务 20 证据规模核对（ADR-0007 决策 12）

| 要求 | 实测（`staging/research-memory/`，全合成脱敏） |
|---|---|
| Math ≥3 合格 case package（v2） | **3**（`case-math-1/2/3`，builder 捕获，`eligibility.status=eligible`） |
| Quant ≥3 合格 case package（v2） | **3**（`case-quant-1/2/3`，同上） |
| Math ≥2 candidate pattern | **2 条链**（`pat-math-a/b`，各 distilled→candidate_pattern 双版本在树） |
| Quant ≥2 candidate pattern | **2 条链**（`pat-quant-a/b`，同上） |
| ≥1 正确 abstain | **1**（`evidence/abstain/retrieval-session.json`：冻结签名与全部在册 pattern 零指纹/facet/token 交集，显式 `abstained`，session 哈希绑定） |
| 全部合成/脱敏并如实标注 | manifest `synthetic: true`；案例标题与证据等级均标 synthetic；零真实项目内容（redaction 扫描在 builder 内强制） |
| Phase 3 公开 suite 保持全绿 | 全量 **700/700 OK × 双环境**（含 E8 benchmark 集成 14 项原样在套） |

树完整性：`tests/integration/test_experience_evidence_pack.py` 经公共 experience 面**逐字节重建**全部 16 份 artifact 并复核 manifest 哈希——任何漂移即失败。

## 验收 Gate 逐条证据（计划 Phase 4「验收 Gate」原文 11 条）

| Gate 原文 | 证据 |
|---|---|
| 单例失败不能自动生成 global rule | 任务 9 天花板：单例只到 `candidate_pattern` 且需三要素 attestation（`patterns.py` 守卫 + R38 实测）；linter `always_triggered` 对 blocking 一律 reject（"deterministic global invariant" 行文，R39 实测） |
| 单个项目复盘不能自动生成、安装或激活 Skill | `assert_no_promoted_skill` 拒绝任何 populated `promoted_skill`（R39 实测）；本 Phase 无任何安装/激活动作（Git Gate 同文） |
| root cause 在无反事实证据时保持 hypothesis | schema 层无 "confirmed" 标志位（ADR-0007 决策 4）；晋级表述须在新版本 analysis 中引用三要素 |
| Observation 历史不因分析更新而变化 | Phase 1 observation/analysis family 零改动（M2 diff 实证） |
| Case、Pattern、Skill Candidate 三类对象可通过 ID/hash 追踪，但互不冒充 | 三 family 分离 + pinned 引用按家族断言（R36/R37 探针：异族引用 `cross_type_reference`/`declares` 拒）；Skill Candidate 本 Phase 不存在（决策 8） |
| Pattern 检索说明"为什么可能适用"和"何时不要用"，且允许空结果 | 检索六要素（applicability/contraindications/evidence/source/last-validated/差异说明，R38 实测逐项在场）；显式 abstain（本报告证据包 + M4 测试） |
| 使用旧 Pattern 的 Run 记录实际帮助、无效或负迁移，反馈不覆盖原记录 | `reuse-event/v1` 事实轴 family（无 supersedes）；聚合是 registry 层可重建派生物（M4 reuse 模块 + R38 实测） |
| 冲突、循环和无回滚的 blocking rule 被拒绝 | linter reject 级：conflict/precedence_cycle/vacuous_rollback(blocking)（R39 逐项实证） |
| shadow 只记录决策，不改变生产行为 | shadow runner 只装配假设性决策 artifact（无 `schema` 键、非 core family、纯函数零 I/O；R39 实测八种坏形态全拒） |
| `research-patterns/` 与 `skill-incubator/` 不在任何自动发现 Skill 根内 | `docs/governance/RESEARCH_PATTERN_LIBRARY_LAYOUT.md` §2 + 集成测试钉选（暂存区无 SKILL.md、路径不经 `skills/`） |
| 公开 suite 无 critical regression | 双环境 700/700 OK；E8 集成 14 项在套 |

## Git/发布 Gate 核对

- 分支 `feat/research-memory-pattern-registry` ✓；schema/case builder/pattern registry/retrieval/linter/shadow runner **分提交** ✓（七 commit，见映射表；M4/M5 各按审核裁决拆二）
- 不创建正式子 Skill、不安装 Skill、不创建 production Champion ✓（零安装动作；暂存区隔离钉选在套）
- PR 将列出每个 active Pattern/规则的来源案例、适用边界、反例与 regression case（本 Phase 上限：无 active pattern——证据包最高态为 candidate_pattern；PR 附件用证据包 manifest）
- annotated tag `v0.5.0`：待 PR 合并后按发布流程执行

## 已知限制

1. `evaluation-run/v1` schema 缺口（error/inconclusive 结构性不可装配）：Phase 3 以 fail-closed 处理并留 `unpublishable_reason`；v2 successor 候选已登记任务 21，由真实发布需求驱动（ADR-0004 政策）。
2. linter 九 kind 为**必要条件筛查**（窄约定、冻结词表），人类评审仍是语义权威（模块 docstring 明示；R39 P4-2 记录边界实例）。
3. 检索 semantic 层阈值为硬编码 `>0`（R38 P4-1）：stopword-only 交集即浮出诚实标注的最末位候选；后续触碰时暴露阈值参数。
4. 多案例 `distilled→active_pattern` 跳级被 forward-only 守卫放行（R38 P4-2）：任务 9 唯一硬规则是单例天花板；如需更严阶梯属后续 registry policy。
5. Phase 4 上限 = active Pattern + shadow Heuristic（总体计划 §3.2）：`validated`/`promoted`/`deprecated`/`retired` 词表存在但本 Phase 不可达（双向硬拒在套）。

## 回滚说明

revert 本分支全部 commit（`074b8dc..HEAD`）即回到 v0.4.0；无 schema 迁移、无 store 数据、无安装动作，回滚无副作用。staging/research-memory/ 为纯新增目录，删除即净。

## 卫生与机械证据

- 双环境全量 **700/700 OK**（694 + 6 证据包集成测试）
- 删除探针：28 模块 **595/595**、BLOCKER-ACTIVE 恰一次、exit 0（M5 基线；M6 新测试在 integration 分区，不入删除探针面）
- `git diff --check` clean；pycache 0；新代码（仅集成测试 1 文件）禁词预扫零命中
- 冻结面零漂移：schemas/fixtures/合同 pin/core `__all__`/experience 面（38 项）/evaluation/adapters 全部未触碰
- 证据包领域词汇为数据（taxonomy JSON 先例），且自觉避开全部 `_BANNED_TERMS` 词元
