# Heuristic Research Agent Skill

面向数学、量化研究、机器学习与深度学习科研的可审计 Agent 经验学习、评测和受控进化平台。

本仓库已交付 Phase 1 通用记录与证据内核（v0.2.0）、Phase 2 领域 Adapter 垂直切片（v0.3.0）、Phase 3 Public Evaluator MVP（v0.4.0，仅覆盖 L0/L1）与 Phase 4 研究记忆与 Pattern Registry（v0.5.0，上限 active Pattern + shadow Heuristic；v0.5.1 为归档缺件 hotfix）；**Phase 5 Machine Learning Adapter 的 L1–L6 实现、独立审核与 commit-bound archive 验收已完成，push、PR、合并与 v0.6.0 发布仍待独立动作/审批**。现阶段冻结项目计划、模块职责、治理规则、Core/Adapter seam 与分层验收证据；尚未宣称任何真实研究执行器、Heuristic Learning 闭环、真实 ML 训练/执行能力或生产发布能力已经实现。

## 项目目标

平台把科研工作拆成两层：

- 通用内核只处理 `ResearchTask`、`Claim`、`Evidence`、`Run`、`FailureObservation`、`ResearchCasePackage`、`ResearchPattern`、`EvaluationCase`、`CandidateBundle` 和 `PromotionDecision`；
- 数学、量化、机器学习和深度学习的正确性规则由领域 Adapter 提供。

核心边界：

1. 工程测试通过不等于科研结论成立；
2. 样例或合成数据成功不等于真实数据验收；
3. 回测或样本外结果不等于真实可交易收益；
4. Candidate 无权修改 Evaluator、读取 hidden case 或自行晋级；
5. 生产运行只读取已批准且 hash-bound 的冻结 Heuristic snapshot。

## 研究记忆与子 Skill 生命周期

困难科研问题和重大项目问题可以在收尾时形成 `ResearchCasePackage`，再从多个案例中蒸馏带有适用条件、禁用条件、反例和来源证据的 `ResearchPattern`。遇到新难题时，平台先检索这些 Pattern 作为启发，但不会把历史思路当成当前结论，也不会自动套用。

只有当某个 Pattern 跨案例可复用、触发边界清晰、接口稳定并通过独立 fresh-session 前向测试时，才进入 Skill Incubator。生命周期固定为：

```text
Case Package
→ Research Pattern
→ staged Skill candidate
→ approved canonical Skill
→ controlled installation
→ optional Default/Preset 或 Champion activation
```

中央库中的 Pattern、候选 Skill、正式 Skill 和各安装根相互分离；保存经验、发布 Skill、Git 发版、安装 Skill 和激活能力均需独立 Gate。

## 当前文档

- [详细实施计划](docs/plans/PROJECT_IMPLEMENTATION_PLAN.md)
- [总体架构](docs/architecture/ARCHITECTURE.md)
- [Core Interface（Phase 1D）](docs/architecture/core-interface.md)
- [Phase 2 验收报告：Math/Quant 双 Adapter 垂直切片](reports/phase2-acceptance-20260816.md)
- [Phase 3 验收报告：Public Evaluator MVP](reports/phase3-acceptance-20260817.md)
- [Phase 5 验收报告：Machine Learning Adapter](reports/phase5-acceptance-20260821.md)
- [科研结论治理](docs/governance/RESEARCH_CLAIM_GOVERNANCE.md)
- [Schema 兼容政策](docs/governance/SCHEMA_COMPATIBILITY.md)
- [Git、提交、推送与 Tag 流程](docs/governance/GIT_RELEASE_PROCESS.md)
- [math-research-solve 1.0.1 基线验收](reports/baseline/math-research-solve-1.0.1.md)
- [ADR-0001：采用通用内核和领域 Adapter](docs/decisions/0001-core-and-domain-adapters.md)
- [ADR-0002：Core 发布/图校验接口与架构三操作的对齐](docs/decisions/0002-core-publication-graph-interface.md)
- [ADR-0003：Run/Failure/Case envelope 的 schema、引用与隐私边界](docs/decisions/0003-core-run-failure-case-envelope.md)
- [ADR-0004：三轴隐私模型、export 记录、schema 兼容政策与只读 CLI](docs/decisions/0004-privacy-export-compatibility.md)
- [ADR-0005：Adapter interface v1——seam 三类型、contract suite 与成立判据](docs/decisions/0005-adapter-interface-v1.md)
- [ADR-0006：Public Evaluator MVP——L0/L1 评测记录、runner/scorer/统计纪律与 meta-test 义务](docs/decisions/0006-public-evaluator-mvp.md)
- [ADR-0007：Research Memory 与 Pattern/Heuristic Registry——case-package/v2、生命周期纪律、检索 MVP 与 shadow 边界](docs/decisions/0007-research-memory-pattern-registry.md)
- [ADR-0008：ML Adapter——数据合同、声明式泄漏检查与确定性实验 runner](docs/decisions/0008-ml-adapter.md)

## 目录

```text
heuristic-research-agent-skill/
├── .github/                  # PR 与 Issue 协作模板
├── docs/                     # 计划、架构、治理和 ADR
├── src/research_evolution/   # 通用内核与领域 Adapter
├── schemas/                  # 版本化 JSON Schema
├── benchmarks/               # 公开 benchmark 与私有 runner 接口
├── baselines/                # 外部 baseline 的 manifest，不保存私有运行数据
├── policies/                 # Promotion、隐私、资源与污染策略
├── skills/                   # 仓库内 Skill payload；Pattern/孵化草稿不得混入运行时发现根
├── scripts/                  # 可重复的验证、打包与发布脚本
├── tests/                    # unit、contract、integration、e2e 和 fixtures
└── reports/                  # 仅保留经过筛选的可发布报告或模板
```

## 本地验证

项目使用标准库 `unittest`；无需 `pytest`。在仓库根目录使用 PowerShell 7：

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONDONTWRITEBYTECODE = "1"
python -B -m unittest discover -s tests -p "test_*.py" -v
```

发布形态必须从当前提交的 `git archive` 再跑两条不同 Python 路径：

```powershell
python -B scripts/verify_archive_suite.py 'C:\path\to\second\python.exe'
```

成功判据是两套测试均退出 0，且归档中的 fixture 跟踪检查仅因不存在 `.git` 而出现一个预期 skip。

## 当前状态

- 远程仓库：`https://github.com/westwhile/heuristic-research-agent-skill.git`
- 默认开发分支：`main`
- 当前仓库 Tag：`v0.5.1`（Phase 4 验收发布为 `v0.5.0`，`v0.5.1` 为其归档缺件 hotfix——源码归档缺两 fixture，已修复并新增 archive 发布 Gate；不代表功能平台已经发布）
- Phase 0 工程基线：`math-research-solve 1.0.1` portable、candidate 与安装树 79 文件一致；Windows 回归 19 passed、1 个真实 legacy fixture 用例延期
- Phase 1 已完成：九个 v1 Core schema、25 种 violation 合同、append-only 发布与全图验证、只读 CLI（详见 v0.2.0 tag 与 Phase 1C/1D 验收报告）
- Phase 2 已完成：Math/Quant 双 Adapter、seam 成立三判据、Adapter interface v1 冻结（详见 v0.3.0 tag 与 Phase 2 验收报告）
- Phase 3 已完成：Public Evaluator MVP——L0/L1 评测记录四 family、replay runner、scorer 四级、统计三类、六门 hard gates、meta-tests、首批公开 benchmark suites（详见 v0.4.0 tag 与 Phase 3 验收报告；已知限制含 evaluation-run/v1 schema 缺口，v2 候选已登记 Phase 4 backlog 任务 21）
- Phase 4 已完成：研究记忆与 Pattern Registry——case package v2、pattern/heuristic registry、检索 MVP、shadow runner、隔离暂存区与合格证据包（详见 v0.5.0 tag 与 Phase 4 验收报告；上限 active Pattern + shadow Heuristic，零安装零晋级）
- Phase 5 实现已完成：Machine Learning Adapter——L1（ADR-0008）、L2（四个 `ml-*` v1 schema + 三操作实现 + contract suite）、L3（DAG 拓扑合同 + 七 leakage predicates + 三 semantic floors）、L4/L4.1（`evaluation-contract/v3`、带 case pin 的 `ml-evidence/v2`、final-evaluation Gate）、L5（runner 0.3.0 的四 split assignment Gate、20-case 合成目录、双垂直切片）与 L6（4 个 ML Case Package、1 条 cross-case candidate Pattern、3 条 shadow Heuristic、ML/Quant 重合分析与验收报告）均已交付；工作树双环境 864/864，commit `82d62e9bdbed9c4d05c7c986f6a6a4c46a71dd57` 的真实 `git archive` 双环境同为 864/864（各 1 个预期 Git tracking skip）。L6 未新增 Core/schema/公共接口，证据上限仍为 engineering-only；push、PR/merge 与 v0.6.0 Tag/Release 尚未执行。runner 仍是显式内存、no-transform/no-search 的标准库协议机器；nested 只验证 fold assignment，未执行逐折训练。DL Adapter（Phase 6）未启动；不宣称真实 ML 训练/执行、数据验收或科研 Agent 能力

提交、推送、打 Tag 和创建 Release 均按治理文档中的 Gate 执行；不得仅因脚本退出码为零便宣称阶段完成。
