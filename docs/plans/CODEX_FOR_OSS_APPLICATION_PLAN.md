# Codex for Open Source 资格申请完整计划

- 计划状态：`O1_O2_COMPLETE / O3_ENGINEERING_COMPLETE_RELEASE_PENDING / O4_IMPLEMENTATION_DRAFT / HOLD_FOR_READINESS`
- 计划版本：v1.5-oss-r0-pr-d
- 初次评估日期：2026-08-20
- 状态同步日期：2026-08-23
- 适用仓库：`westwhile/heuristic-research-agent-skill`
- 已完成前置：`v0.6.0` GitHub source milestone 已发布；PR #14—#16 已完成 Apache-2.0/来源治理、Quick Start/合成 demo 与 archive install 支持矩阵；OSS 外部动作仍为未申请、未提交表单

> 本文件主要定义申请前的建设、证据和审批 Gate。O1—O2 与 O3 工程 Gate 已合入 `main`；当前 PR-D 只实施 O4 的贡献、安全、行为准则、治理、变更记录、引用与 Issue/PR 入口。Tag、Release、外部试用及填写/提交申请表仍是独立 Gate。

## 1. 裁定摘要

该项目在方向上可以申请 Codex for Open Source：它有持续发布记录、明确的科研软件治理问题、可把 Codex 用于 PR 审核、测试生成、发布验证和维护自动化。PR #14 已把 Apache-2.0 与 `unknown=0` 来源 Gate 合入 `main`；PR #15 已合入未发布的 `0.6.1` 候选、source-install CLI、合成 demo 与 Quick Start；PR #16 又以 merge commit `b6b2b9aff27b054b1e4324d1dba308873e5b394a` 合入权威支持矩阵、diff hygiene 与四 lane clean-archive install/demo Gate，main CI run `32617521658` 全绿。当前 PR-D 正在补充公共贡献、安全和治理入口。项目仍不宜直接提交申请，因为 O4 尚待验证合入，`v0.6.1` 尚未发布，真实外部采用证据也尚未形成。

推荐路线：在已完成 O1—O2 的基础上，依次完成 O3—O4，随后开放 2—4 周真实外部试用并积累可核验证据，最后执行 O5—O6。更稳妥的申请窗口仍是 O1—O5 全绿并形成外部使用证据之后；许可证、内部测试或合成 demo 本身不构成项目资格或采用证明。

## 2. 官方项目要求与表单字段

权威来源为 OpenAI 的 [Codex for Open Source 申请页](https://openai.com/form/codex-for-oss/)。2026-08-23 OSS-R0 审计时已实时复核官方项目页、申请页和 Program Terms；以下核心字段与限制仍须在正式申请前再次核验：

- 申请人应是 active open-source project 的 primary 或 core maintainer；
- 项目应有 meaningful usage、broad adoption，或对软件生态具有清晰重要性；
- 会考察仓库使用、生态重要性与持续维护证据，包括 PR review、issue triage、release management 等；
- 申请滚动审核；不完全符合典型指标但具有重要生态作用的项目仍可解释后申请；
- 开发者可以为自己的项目申请，也可以 nominate 另一位 maintainer；本仓若由用户本人申请，仍须如实确认 primary/core maintainer 角色；
- 表单要求公开的 GitHub 个人资料与仓库、maintainer 角色、OpenAI Organization ID；
- “为什么项目符合资格”“如何使用 API credits”“其他说明”各最多 500 characters；
- 被选中者可能获得六个月 ChatGPT Pro、API credits，并可能获得有条件的 Codex Security 访问。

申请时必须再次打开官方页面复核字段与条款；本文件不把当前页面视为永久冻结合同。

## 3. 2026-08-23 状态同步快照

| 维度 | 已核事实 | 申请含义 |
|---|---|---|
| 可见性 | GitHub public，默认分支 `main` | 满足“仓库公开”的表单前提，但不等于已开源 |
| 许可证 | PR #14 已以 merge commit `f47a0307a4ac7cf52603aa9d3da8aa3852af19ae` 把 Apache-2.0、`NOTICE`、包元数据和 `unknown=0` 来源登记合入 `main`；GitHub 已识别 Apache-2.0 | O1 已完成；后续仍须保持来源 Gate，且不得把仓库许可证外推为第三方内容授权 |
| 采用度 | 1 star、0 fork、1 contributor、0 issue | 采用度信号仍弱，需依靠生态价值说明和真实试用证据补强 |
| 维护活动 | 16 个已合并 PR、6 个 GitHub Release，最近发布 `v0.6.0` | 有持续维护基础，但社区参与仍主要来自单一维护者；该内部活动不等于外部采用 |
| 发布版本 | annotated `v0.6.0` 与六项 evidence assets 已发布；PR #15 已把包元数据改为未发布的 `0.6.1` 候选 | GitHub source milestone 已闭环；发布 Gate 仍须核对 package、Tag、Release 和 support matrix 语义 |
| CI | PR #16 已把 Windows/Ubuntu × Python 3.12/3.14 的 provenance、diff、full suite 与 archive install/demo 接入四项 required checks；merge SHA 的 main run 全绿 | O3 工程 Gate 完成；Tag/Release/包版本一致性仍在 `v0.6.1` 发布 Gate |
| 协作治理 | 当前 PR-D 候选增加 CONTRIBUTING、SECURITY、Code of Conduct、GOVERNANCE、CHANGELOG、CITATION 与 Issue/PR forms；用户已确认邮箱私密报告路线 | O4 仍须完成来源 Gate、review、merge 与 main CI |
| 安装/演示 | PR #15 已提供 source-install Quick Start，PR #16 已在四 required lanes 从 exact commit archive 安装并运行成功/拒绝 demo | O2 与 O3 archive install 子项已完成；仍不构成真实研究或采用证据 |
| 架构与测试 | Phase 5 的 870-test 基线已形成；PR #15 为 878 tests，另有隔离 source-install smoke | 是差异化优势，但仍须通过 PR-C 公共 Gate 与真实外部使用转化为采用证据 |

所有会变化的 GitHub 数字只作为此日期的快照；填写申请表前必须重新获取，不得复制旧数字。

## 4. 申请边界与非目标

本计划不做以下事情：

- 不因“代码公开”而绕过许可证与权利审计；
- 不直接复制、翻译或改写来源不明/无许可证的 Pika Skill 源码、schema、测试、模板或长段文字；
- 不伪造 star、fork、download、issue、贡献者或用户反馈；
- 不把内部测试数量、合成 case 或 shadow runner 写成真实科研能力或外部采用；
- 不在申请中披露私有路径、密钥、hidden case、私人对话或第三方受限材料；
- 不为申请临时制造空壳 Issue/PR，也不以机器人自产互动冒充社区活动；
- 不在本计划阶段提交表单、勾选 Codex Security、承诺预算或代表其他维护者发言；
- 不把获得支持写成确定结果；是否入选由 OpenAI 决定。

## 5. 工作包与 Gate

### O1：权利、许可证与来源治理（阻塞）

目标：证明“有权以 Apache-2.0 发布什么”，并让该判断可审计、可在归档树自动验证。

完成状态（2026-08-23）：权利持有人已确认授权范围并选择 Apache-2.0；PR #14 已通过完整测试、commit-bound archive Gate、review、merge 与 main push CI。合入树覆盖 828 个文件，其中 `independently_authored=696`、`generated=118`、`design_inspired=13`、`third_party_reused=1`（仅标准 Apache-2.0 文本）、`unknown=0`。GitHub 已识别 Apache-2.0。

任务：

1. 生成全部 tracked files 清单，按 `independently_authored`、`design_inspired`、`third_party_reused`、`generated`、`unknown` 分类；
2. 对外部 baseline、附件、fixtures、文档引文、工具生成物逐项记录来源 URL/文件、版本、获取日期、许可证、允许的使用方式和本仓处理方式；
3. 对 `unknown` 或无明确再许可权的内容执行“隔离、重写或删除”决策，不能用“非商业/研究用途”自行补足许可；
4. 把 Pika 工具包只当作设计审查输入；在未取得兼容许可前，不导入其 payload；
5. 由权利持有人选择项目许可证；2026-08-23 用户已明确选择 Apache-2.0；
6. 新增 `LICENSE`、必要的 `NOTICE`、第三方来源登记与 AI/工具辅助开发披露；同步 `pyproject.toml` license 元数据；
7. 对源码归档执行许可证存在性、NOTICE 完整性与未知来源为零的自动 Gate。

验收：

- 每个 tracked file 都有明确来源类别；
- `unknown=0`，或每个例外都有公开排除说明和 owner 决策；
- 许可证文本、包元数据、README 徽标与 Release artifact 一致；
- 干净 `git archive` 中包含许可证与必要 NOTICE；
- 独立 reviewer 能从登记表重建关键来源判断。

停止条件：任何核心文件权属无法确认，或第三方条款禁止目标许可证时，申请保持 HOLD。

### O2：陌生用户五分钟成功路径

目标：让未参与项目的人能理解、安装、运行并正确解读结果。

完成状态（2026-08-23）：PR #15 已把包版本设为未发布的 `0.6.1`，增加 `research-evolution` console entry point、包内合成 `demo`、`demo --tamper` 预期拒绝路径及 Windows/Ubuntu source-install Quick Start；merge commit `6096ca719502baa1d88a35a5501dfeb0616afcae` 的 main CI run `32616812612` 四项全绿。该证据仍不构成真实研究、外部采用或 Skill 安装。

任务：

1. 重写 README 首屏：一句话价值、当前成熟度、明确非声明、支持平台、许可证；
2. 提供独立于开发工作树的安装说明，明确最低 Python 版本与 Windows/Ubuntu 命令；
3. 提供一个仅用公开合成数据的五分钟 Quick Start；
4. 把 Phase 4 的最小垂直切片包装为 `examples/` 或 CLI demo：输入 ResearchTask/Case，输出经 hash 绑定的验证报告；
5. demo 必须把“工程验证”“合成证据”“真实科研结论”分栏显示；
6. 为失败路径提供至少一个示例：篡改 artifact、无效 lineage 或泄漏声明被拒；
7. 在干净归档或全新 clone 中按文档逐字执行，不借用未跟踪文件或本机绝对路径。

验收：

- 新用户从 clone 到首个成功输出不超过五分钟（不计 Python 下载）；
- Quick Start 在 Windows 与 Ubuntu CI 均通过；
- 成功和失败示例都有固定预期输出及解释；
- 文档没有宣称真实 ML 训练、真实量化收益或自动 Skill 晋级。

### O3：公共 CI、版本与发布可复现性

目标：把本地强 Gate 变成外部维护者可见、可复跑的公共证据。

当前进度（2026-08-23）：PR #16 的机器可读 support matrix、PR/main diff whitespace Gate 和每个 required lane 的 exact-commit clean-archive install/Quick Start smoke 已通过 PR 与 merge SHA main push CI。O3 工程 Gate 已完成；Tag/Release 一致性仍留在单独的 `v0.6.1` 发布 Gate。

任务：

1. 增加 GitHub Actions：Windows + Ubuntu，项目最低支持 Python + 当前验证 Python；
2. CI 依次执行 schema/contract/unit/integration tests、`git diff --check` 等卫生检查和归档 Gate；
3. 在归档树执行安装/导入/Quick Start smoke test，禁止使用工作树遗留物；
4. 建立单一 support matrix 权威源，README、Release notes、测试矩阵由其生成或校验；
5. 修正 `pyproject.toml` 的 `0.0.0` 与实际 Tag/Release 语义；明确是否发布 PyPI，未发布时不制造下载量；
6. 为 release artifact、Tag、commit、manifest 和测试 commit 建立相等性 Gate；
7. 失败日志完整可诊断，成功输出绑定 commit SHA。

验收：

- 受保护 PR 的必需检查全部公开可见；
- archive/clone 双平台通过；
- support matrix 无相互矛盾状态；
- Release artifact 可由指定 commit 重建，且 checksum 一致。

### O4：OSS 协作与安全入口

目标：证明该仓库能接收、审查并维护外部贡献，而非只作为个人展示页。

当前实现状态（2026-08-23）：PR-D 候选正在增加贡献指南、支持版本与私密漏洞入口、Contributor Covenant 3.0（CC BY-SA 4.0 单独归属）、maintainer-led 治理、里程碑 changelog、CFF 1.2.0 引用元数据，以及 bug/schema/docs/research-boundary Issue forms。GitHub Private Vulnerability Reporting 仍关闭；用户已确认由 `SECURITY.md` 与 `CODE_OF_CONDUCT.md` 公布的邮箱作为私密报告路线。O4 仍须通过来源 Gate、review、merge 与 merge SHA 的 main CI。

后续实施清单：

- `CONTRIBUTING.md`：环境、测试、schema version、ADR、claim discipline、PR 粒度；
- `SECURITY.md`：私下报告渠道、支持版本、响应边界；
- `CODE_OF_CONDUCT.md`：采用公认模板并记录版本；
- `CHANGELOG.md`：从现有 Release 反向建立简明历史，不改写验收报告；
- `CITATION.cff`：仅在作者、标题、版本信息经用户确认后创建；
- Issue templates：bug、schema/contract proposal、documentation、research-boundary concern；
- PR template：变更范围、测试、来源/许可证、回滚、科研结论边界；
- `GOVERNANCE.md` 或 README 段落：primary maintainer、reviewer independence、版本与弃用规则。

验收：一个陌生贡献者无需私人消息即可知道如何提问、报告漏洞、运行测试和提交最小 PR。

### O5：真实采用与维护证据

目标：补足当前 1 star/0 fork/单贡献者的弱采用信号，不追求虚假增长。

任务：

1. 邀请 2—3 位真实目标用户完成 Quick Start；优先数学研究、量化/ML 审计或研究软件维护者；
2. 使用 issue/discussion 模板记录真实失败、概念不清或安装摩擦；
3. 对每条反馈给出 triage、修复/拒绝理由和关闭证据；
4. 至少接收一项外部文档、case 或 bug 反馈；不要求必须合并代码；
5. 记录使用场景、平台、是否成功、耗时和问题类型；未经同意不公开身份；
6. 若存在真实下游项目，记录可公开链接；否则诚实写“early-stage adoption”。

推荐申请 Gate：

- 至少 2 个独立外部用户完成或认真尝试 Quick Start；
- 至少 3 条真实反馈进入公开或脱敏 triage；
- 至少一次外部反馈驱动的文档/测试改进；
- 连续 2—4 周有可验证维护活动；
- 申请时重新记录 star/fork/contributor/download 等实时数据，缺失项明确写无。

### O6：申请证据包与提交 Gate

目标：用可追踪事实完成表单，不靠夸张叙事。

证据包：

1. `application-evidence.json`：申请日期、repo SHA、Release、CI runs、实时仓库指标、Quick Start 结果；
2. `application-claims.md`：表单每句话 → 支撑 URL/文件/commit；
3. maintainer role 说明与公开 GitHub profile 检查；
4. OpenAI Organization ID 由用户从其账户确认，不写入仓库；
5. 计划使用 credits 的预算与用途，不包含真实交易、敏感数据或未经授权的第三方内容；
6. 三个 500-character 字段的字符计数与事实审查；
7. 最终截图或 PDF 仅存放在用户指定的私有位置，不进入公共仓库。

提交前四人称 Gate（同一人可执行不同角色，但证据要分开）：

- Author：起草；
- Fact checker：逐句核证；
- Privacy/license reviewer：检查泄漏与权利；
- User/maintainer：批准最终文本并亲自提交或明确授权提交。

## 6. 建议的 credits 使用方案

申请时应把 credits 用途绑定到维护工作，不写成“帮我完成所有研究”。建议预算结构：

| 用途 | 比例上限 | 可核交付物 |
|---|---:|---|
| PR/差异独立审核 | 30% | review reports、发现/修复映射、regression tests |
| 合同与 mutation 测试生成 | 25% | negative fixtures、mutation kill receipts |
| 发布与归档验证 | 15% | archive/clean-clone Gate、release manifest |
| Issue triage 与文档维护 | 15% | issue 分类、可复现步骤、文档 PR |
| 安全/依赖/来源审查 | 10% | scan reports、provenance decisions |
| 预留与失败重跑 | 5% | 预算差异和重跑原因 |

硬边界：API credits 不用于伪造社区互动、生成 hidden benchmark 答案、自动批准自身改动、真实交易决策或绕过人工 Promotion Gate。

## 7. 表单文案构建框架

以下只定义结构，不提前编造最终文案。申请时所有 `{{...}}` 必须由 O6 证据替换。

### 7.1 Why does this repository qualify?（≤500 characters）

结构：

```text
{{maintainer_role}} of {{project_name}}, an open-source, audit-first research-agent
governance toolkit for Math/Quant/ML/DL. It provides {{verified_capabilities}}
with {{tests/releases/adoption facts}}. Its ecosystem value is {{specific value}},
and current adoption is honestly {{stage}}.
```

禁止词替换：若没有证据，不写 `widely used`、`production-grade`、`proven`、`autonomous research` 或任何下载量。

### 7.2 How will you use API credits?（≤500 characters）

结构：

```text
Use credits for bounded OSS maintenance: independent PR review, adversarial and
mutation test generation, issue triage, documentation, archive/release checks,
and security/provenance scans. Every run is commit-bound and human-reviewed;
credits will not auto-promote skills or turn synthetic tests into research claims.
```

### 7.3 Anything else we should know?（≤500 characters）

只写：早期采用的诚实边界、为何该治理基础设施对生态有价值、公开 roadmap、可复现 demo 与支持矩阵。不要重复前两栏。

## 8. 执行顺序、分支与提交切分

Phase 5 已通过 `v0.6.0` 发布收口。O1 已由 PR #14、O2 已由 PR #15、O3 工程 Gate 已由 PR #16 合入 `main`。当前 `docs/oss-governance-entrypoints` 分支只实施 O4 公共协作与安全治理；v13/Pika payload 与详细表达继续排除。

建议提交层：

1. O1：来源清单 + 用户批准的 LICENSE/NOTICE；
2. O2：README/Quick Start/demo；
3. O3：CI/support matrix/version/archive smoke；
4. O4：协作与安全治理文件；
5. O5：仅提交可公开的反馈驱动改进，不提交私人证据；
6. O6：公共申请证据模板；含私密字段的最终包留在仓库外。

每层均单独 review；当前执行授权仅覆盖依次实施 OSS readiness PR。Tag、Release、外部协调和表单提交仍分别保留独立 Gate。

## 9. 时间表与决策点

| 周期 | 工作 | 出口 |
|---|---|---|
| 第 1—2 天 | O1 权利清单与 Apache-2.0 实现 | 来源 Gate、review、archive 与 main 合入全绿 |
| 第 2—4 天 | O2 Quick Start/demo | 双平台陌生用户路径可跑 |
| 第 3—5 天 | O3 CI/version/release Gate | public checks 绿且 archive 可复现 |
| 第 4—7 天 | O4 协作治理 | 外部贡献入口完整 |
| 第 2—4 周 | O5 外部试用和反馈闭环 | 真实采用证据成立 |
| 最后 1—2 天 | O6 证据包与 500-character 文案 | 用户批准后才提交 |

申请时机：

- **最早可提交**：O1—O4 全绿，能诚实解释项目早期阶段；
- **推荐提交**：`v0.6.0` 已发布，继续等待 O1—O5 全绿和 2—4 周维护证据形成；
- **必须延后**：许可证/来源 Gate 回归、Quick Start 不能在归档树运行、CI 不可复现，或申请文本只能靠未验证的能力/采用度支撑。

## 10. 最终 Go/No-Go 清单

- [ ] 用户确认自己是 primary/core maintainer，并有权代表该仓库申请；
- [ ] GitHub 个人资料和仓库在提交时为 public；
- [x] OSI 兼容许可证已由权利持有人批准并进入 archive；
- [x] 来源/第三方/AI 辅助开发登记完整，无未知权属文件；
- [x] README 有五分钟 Quick Start 和诚实能力边界；
- [x] Windows/Ubuntu public CI 与 archive install/demo Gate 通过；
- [ ] 包版本、Tag、Release、support matrix 一致；
- [ ] CONTRIBUTING/SECURITY/Code of Conduct/CHANGELOG 在位；
- [ ] 至少两名独立外部用户的真实试用证据已获得；
- [ ] 实时 GitHub 指标在申请日重取，未虚报 downloads 或 adoption；
- [ ] OpenAI Organization ID 由用户核对，未进入公共文件；
- [ ] 三个字段均 ≤500 characters 且逐句绑定证据；
- [ ] 无私密路径、hidden case、密钥或第三方受限内容；
- [ ] 用户已审阅最新官方条件与 Program Terms；
- [ ] 用户对“提交申请”另行明确授权。

任一阻塞项未满足时，状态保持 `HOLD_FOR_READINESS`；不得把计划完成本身当作资格通过。
