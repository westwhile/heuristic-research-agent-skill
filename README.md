# Heuristic Research Agent Skill

面向数学、量化研究、机器学习与深度学习科研的可审计 Agent 经验学习、评测和受控进化平台。

本仓库已交付 Phase 1 通用记录与证据内核（v0.2.0）、Phase 2 领域 Adapter 垂直切片（v0.3.0）、Phase 3 Public Evaluator MVP（v0.4.0，仅覆盖 L0/L1）与 Phase 4 研究记忆与 Pattern Registry（v0.5.0，上限 active Pattern + shadow Heuristic；v0.5.1 为归档缺件 hotfix）；**Phase 5 Machine Learning Adapter 的 L1–L6 已以 annotated `v0.6.0` Tag 发布，随后 Apache-2.0、来源治理、source-install Quick Start、双平台 archive Gate 与公共协作入口又以 annotated [`v0.6.1` source Release](https://github.com/westwhile/heuristic-research-agent-skill/releases/tag/v0.6.1) 发布。`v0.6.1` tag object `2cdb9621d05211c779f933836adae476241206c0` 指向提交 `5af73595f847702930e0c1966986f3d06d3c1c35`；六项 Release assets 已回下载并与 GitHub digest、发布前 SHA-256 三方对账**。O5 外部 Quick Start 试用入口已公开，当前等待维护者选择参与者且仍无外部结果；O6 只建立公开证据草案，不代表已提交申请。这不是 PyPI 发布、Skill 安装、真实 ML 执行、真实科研验收或生产能力证明。

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
- [Codex for Open Source 资格申请计划](docs/plans/CODEX_FOR_OSS_APPLICATION_PLAN.md)
- [O5 外部 Quick Start 试用协议](docs/governance/EXTERNAL_TRIAL_PROTOCOL.md)
- [O6 公开申请证据与逐句核证草案](docs/governance/codex-for-oss/application-claims.md)
- [math-research-solve v13 来源边界与延期说明](docs/plans/MATH_RESEARCH_SOLVE_V13_CROSS_DOMAIN_ADOPTION_PLAN.md)
- [来源、权利与第三方边界](docs/governance/SOURCE_PROVENANCE.md)
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

## 五分钟 Quick Start

当前安装入口来自 GitHub source checkout，不代表已经发布到 PyPI。需要 Python
3.12 或更高版本；demo 只使用包内合成 `ResearchTask`，不读取真实科研或市场数据，
也不写入项目文件。

独立试用请固定到 annotated `v0.6.1` tag，并按
[O5 试用协议](docs/governance/EXTERNAL_TRIAL_PROTOCOL.md)记录真实环境和结果；维护者
自测、机器人活动和没有可核尝试记录的下载不计作外部采用。

Windows PowerShell 7：

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install .
& .\.venv\Scripts\research-evolution.exe demo --json
& .\.venv\Scripts\research-evolution.exe demo --tamper --json
if ($LASTEXITCODE -ne 1) { throw "tampered demo must be rejected with exit 1" }
```

Ubuntu：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/research-evolution demo --json
set +e
.venv/bin/research-evolution demo --tamper --json
status=$?
set -e
test "$status" -eq 1
```

成功路径输出 schema、record ID 和 canonical SHA-256；`--tamper` 路径使用
whitespace-only title，必须被 `research-task/v1` 拒绝。两条路径都会明确输出：

- 工程验证结果；
- 输入只属于合成证据；
- 未执行真实数据验收、科研/市场验证、外部采用验证或 Skill 安装/激活。

每个 required CI job 都会从当前 commit 的真实 `git archive` 新建隔离 venv，
安装 source tree，并从归档目录外执行 console、成功 demo 与预期拒绝路径。某个
commit 只有在对应 required check 成功后，才具有该 lane 的 clean-archive 证据。

## 支持与验证矩阵

[机器可读支持矩阵](docs/governance/SUPPORT_MATRIX.json) 是包版本、Python 声明与
required CI lanes 的权威清单；合同测试阻止它与 `pyproject.toml` 或 workflow 漂移。

| Runner | Python | 安装与 smoke | Required check |
|---|---:|---|---|
| Ubuntu `ubuntu-latest` | 3.12 | exact-commit archive → venv → console/demo | `Python 3.12 / ubuntu-latest` |
| Ubuntu `ubuntu-latest` | 3.14 | exact-commit archive → venv → console/demo | `Python 3.14 / ubuntu-latest` |
| Windows `windows-latest` | 3.12 | exact-commit archive → venv → console/demo | `Python 3.12 / windows-latest` |
| Windows `windows-latest` | 3.14 | exact-commit archive → venv → console/demo | `Python 3.14 / windows-latest` |

包元数据声明 Python `>=3.12`；3.12 与 3.14 是 required 验证 lanes，3.13 没有独立
required lane。本矩阵不宣称 macOS、PyPI 安装、Skill 安装/激活或生产科研支持。

## 参与、治理与安全

- 从 [CONTRIBUTING.md](CONTRIBUTING.md) 开始准备环境、测试、来源说明和最小 PR；
- [GOVERNANCE.md](GOVERNANCE.md) 记录当前 maintainer、review、ADR、版本和发布权限；
- 所有参与者遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)；
- 漏洞按 [SECURITY.md](SECURITY.md) 私下报告，不要把细节写进公开 Issue；
- 公开里程碑见 [CHANGELOG.md](CHANGELOG.md)，引用元数据见 [CITATION.cff](CITATION.cff)；
- bug、schema/contract、文档和 evidence-boundary 问题使用仓库 Issue forms；
- 独立用户可使用 [Quick Start 试用反馈表](https://github.com/westwhile/heuristic-research-agent-skill/issues/new?template=quick_start_trial.yml)记录 `v0.6.1` 的真实尝试；安全问题仍必须私下报告。

## 开发者全量验证

项目使用标准库 `unittest`；无需 `pytest`。在仓库根目录使用 PowerShell 7：

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONDONTWRITEBYTECODE = "1"
python -B -m unittest discover -s tests -p "test_*.py" -v
```

发布形态必须从当前提交的 `git archive` 再跑两条不同 Python 路径：

```powershell
python -B scripts/verify_archive_suite.py 'C:\path\to\second\python.exe'
python -B scripts/verify_archive_install.py
```

第一条命令的成功判据是两套测试均退出 0，且归档中的 fixture 跟踪检查仅因不存在
`.git` 而出现一个预期 skip；第二条必须输出绑定当前 commit、OS、Python 和包版本的
`ARCHIVE INSTALL GATE: PASS`。

真实 PyTorch/CUDA small-fixture 观测是显式可选路径，不属于基础安装依赖。
调用方需自行提供版本受控、CUDA 可用的 PyTorch 环境，并显式导入
`research_evolution.adapters.deep_learning.pytorch_observation`。该入口只接受
严格绑定 manifest 的有界合成 fixture；成功结果的证据上限是单次真实
framework/hardware engineering observation，不是数据验收、科研/预测结论、
生产能力或跨 GPU 可复现性。

## 当前状态

- 远程仓库：`https://github.com/westwhile/heuristic-research-agent-skill.git`
- 默认开发分支：`main`
- 当前仓库许可证：Apache License 2.0（见 [LICENSE](LICENSE)、[NOTICE](NOTICE) 与[来源登记](docs/governance/SOURCE_PROVENANCE.md)）；PR #14 已通过 merge commit `f47a0307a4ac7cf52603aa9d3da8aa3852af19ae` 合入，GitHub 已识别该许可证。包元数据 `0.6.1` 与 annotated `v0.6.1` source Release 一致；该 Release 不代表 PyPI/wheel、可安装 Skill 或生产部署已经发布
- Phase 0 工程基线：`math-research-solve 1.0.1` portable、candidate 与安装树 79 文件一致；Windows 回归 19 passed、1 个真实 legacy fixture 用例延期
- Phase 1 已完成：九个 v1 Core schema、25 种 violation 合同、append-only 发布与全图验证、只读 CLI（详见 v0.2.0 tag 与 Phase 1C/1D 验收报告）
- Phase 2 已完成：Math/Quant 双 Adapter、seam 成立三判据、Adapter interface v1 冻结（详见 v0.3.0 tag 与 Phase 2 验收报告）
- Phase 3 已完成：Public Evaluator MVP——L0/L1 评测记录四 family、replay runner、scorer 四级、统计三类、六门 hard gates、meta-tests、首批公开 benchmark suites（详见 v0.4.0 tag 与 Phase 3 验收报告；已知限制含 evaluation-run/v1 schema 缺口，v2 候选已登记 Phase 4 backlog 任务 21）
- Phase 4 已完成：研究记忆与 Pattern Registry——case package v2、pattern/heuristic registry、检索 MVP、shadow runner、隔离暂存区与合格证据包（详见 v0.5.0 tag 与 Phase 4 验收报告；上限 active Pattern + shadow Heuristic，零安装零晋级）
- Phase 5 实现与发布已完成：Machine Learning Adapter——L1（ADR-0008）、L2（四个 `ml-*` v1 schema + 三操作实现 + contract suite）、L3（DAG 拓扑合同 + 七 leakage predicates + 三 semantic floors）、L4/L4.1（`evaluation-contract/v3`、带 case pin 的 `ml-evidence/v2`、final-evaluation Gate）、L5（runner 0.3.0 的四 split assignment Gate、20-case 合成目录、双垂直切片）与 L6（4 个 ML Case Package、1 条 cross-case candidate Pattern、3 条 shadow Heuristic、ML/Quant 重合分析与验收报告）均已交付。PR #11 通过 merge commit `216ec216af385a3b585fc1c6505d25ac67eac585` 合入功能实现，PR #12 通过 merge commit `c72e31eb4d5dbd367b20f24678e94682b963fed9` 同步发布前状态；最终 main CI run `32579211332` 四项 job 全部成功，两个 Windows governance 步骤成功，真实 `git archive` 双解释器均为 870/870（各 1 个预期 Git tracking skip）。annotated tag object `3f109b3e0c1366b93f780be21447e229aa3c3b3e` 指向 `c72e31eb`，正式 Release 的六项 assets 与本地 evidence bundle 逐项 SHA-256 一致。L6 未新增 Core/schema/公共接口，证据上限仍为 engineering-only；runner 仍是显式内存、no-transform/no-search 的标准库协议机器；nested 只验证 fold assignment，未执行逐折训练。OSS-R0 的 Apache-2.0 许可证与来源清单已进入 main；PR #15—#17 已依次合入 `0.6.1` 元数据与 Quick Start、支持矩阵与 archive install Gate、公共协作与安全治理入口。release-prep PR #18 的 merge commit `5af73595f847702930e0c1966986f3d06d3c1c35` 通过 main CI run `32619619333` 四项 required jobs、Windows governance、双解释器 archive suite 与 archive install Gate；annotated `v0.6.1` Tag 和六项 checksum-bound Release assets 已发布并回下载验证。O5 外部试用入口已准备，但尚无独立外部用户结果。Phase 6 L1–L4 已通过 PR #21 的 merge commit `6c63c0bad88f032fb1091cdc5c91242bf22b2087` 合入 `main`；其 Git tree 与通过真实 archive 双解释器 971/971（各 1 个预期 Git tracking skip）的 PR final head `2f5f11dc64c07a5227b58d69c294112f50c5a138` 完全一致，main push CI run `32634831816` 的 Windows/Ubuntu × Python 3.12/3.14 四项 jobs、四项 clean-archive install/demo 与两个 Windows governance 步骤全绿。L4 的 study reporter 0.1.0 对单因素 ablation、scale 与 FLOP-proxy compute-matched 报告执行 expected-seed、冻结轴与资源公平性 Gate；10-case 合成目录覆盖 OOM/NaN/interrupt、selection、checkpoint 篡改和 payload 隔离，并通过既有公共入口构造 5 个合成 Case Package。R1 新增显式可选的 PyTorch/CUDA small-fixture runner 与 `dl-run-observation/v1`，但只有 exact-commit archive 的 opt-in CUDA Gate 才能形成单主机真实框架/硬件工程观测；既有 L1–L4 证据仍是 synthetic engineering。真实 ML 数据验收、driver/跨 GPU 复现、外部 checkpoint store、scheduler recovery、Skill 安装和生产能力仍不存在。未创建 `v0.7.0` Tag 或 Release，发布 Gate 未开启。

提交、推送、打 Tag 和创建 Release 均按治理文档中的 Gate 执行；不得仅因脚本退出码为零便宣称阶段完成。
