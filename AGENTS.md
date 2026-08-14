# Repository Working Rules

本文件适用于本仓库全部目录。更深目录可增加 `AGENTS.md`，但不得削弱这里的科研、隐私和发布约束。

## 1. 项目定位

- 本仓库建设通用科研 Agent 的经验治理、评测与受控进化平台。
- 数学、量化、机器学习和深度学习通过领域 Adapter 接入；不得把任一领域的状态机当成通用内核。
- 通用内核不得直接编码 theorem、factor、backtest、neural network 等领域语义。

## 2. 科研结论边界

- 明确区分 `engineering_claim`、`data_claim`、`mathematical_claim`、`empirical_claim`、`predictive_claim`、`strategy_claim` 和 `production_claim`。
- 工程测试、合成数据或短样本成功不得升级为真实科研结论。
- 量化研究默认检查 PIT 可得性、未来函数、幸存者偏差、复权、交易成本、可交易性和样本外污染。
- ML/DL 默认检查数据切分、预处理泄漏、测试集调参、随机种子、重复实验、资源公平和 checkpoint 选择偏差。
- 数学研究默认区分已验证证明、反例、部分结果、数值证据和待核验推测。

## 3. 修改方式

- 修改前读取磁盘当前版本并检查 `git status --short --branch`。
- 非平凡 Skill 修改必须在 `skills/staging/` 或任务专用 staging 中完成，再按 `skill-dev` 规则验证和部署。
- 不覆盖用户未提交修改，不从 Git HEAD、缓存或旧安装副本重建 dirty 文件。
- 不提交私有研究语料、hidden cases、凭据、绝对用户路径、模型密钥、原始市场数据或大型 checkpoint。
- Schema 采用显式版本；已发布事实记录 append-only，分析修订使用 supersedes 链。

## 4. 验证要求

- 核心 interface 必须有 contract tests；领域 Adapter 至少有两个真实实现后才能称 seam 稳定。
- Candidate 与 Champion 比较必须冻结模型、reasoning、工具、预算、数据和 Evaluator snapshot。
- 每个修复必须附带 regression case；关键晋级必须通过 hard gates，不能由总分抵消。
- 结果报告必须绑定代码、配置、数据或 case、环境和 runner 的 SHA-256/版本标识。

## 5. Git 与发布

- 未经用户明确授权，不执行 commit、push、merge、tag、GitHub Release 或部署。
- Windows Credential Manager/keyring 绑定真实用户身份；Codex 沙箱中的 `gh auth status` 可能因无法读取 keyring 而假报 Token 无效。GitHub 认证检查及需要认证的 `gh`/Git 写操作必须在真实 Windows 用户上下文执行，Codex 中应使用受控提权上下文。
- 使用 `scripts/check_github_auth_context.ps1 -Json` 区分 `requires_windows_user_context` 与真实的 `authentication_failed_in_user_context`。前者不是 Token 过期，不得通过 `GH_TOKEN`、`GITHUB_TOKEN`、`--insecure-storage` 或把 Token 写入仓库/配置文件来绕过。
- 功能工作使用短生命周期分支；PR 合并前必须有清洁测试、变更清单和回滚说明。
- 发布 Tag 必须是 annotated tag，并指向已在 `main` 上验收的提交。
- 不移动或重写已推送 Tag；修复使用新版本。
- Tag、Release、Skill 安装和 Champion promotion 是四个不同动作，分别记录证据。

## 6. 默认工具链

- Windows 默认 PowerShell 7。
- Python 项目使用 `src/` layout、UTF-8、类型友好代码和可固定依赖。
- 文件搜索优先 `rg`/`rg --files`，文件修改优先小范围 patch。
