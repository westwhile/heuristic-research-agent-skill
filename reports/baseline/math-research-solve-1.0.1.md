# math-research-solve 1.0.1 baseline 验收

状态：**PASS WITH DEFERRED CAPABILITY**。Phase 0 的仓库基础、可复现外部工程基线和 Windows 可执行回归已达到提交前审查条件；真实 legacy successor 端到端能力不包含在本次发布声明中。

验收日期：2026-08-13。结论边界仅为工程完整性与回归状态，不代表数学研究质量、量化有效性、机器学习泛化能力或深度学习实验结论。

## 1.0.0 到 1.0.1

只修改三个回归文件，生产控制器、状态机、Skill 文档和研究协议均未改变：

1. `test_math_research_control_path_amendment_v2.ps1` 使用测试临时目录中的 DPAPI CurrentUser key，并在 `finally` 清除 override 和临时目录；
2. `test_math_research_legacy_v1_compat.ps1` 使用同样的 test-only key 隔离；
3. `test_math_research_v2_bundle_regression.ps1` 在构建 v2 differential fixture 时同步转换 fixture `SKILL.md` 的 startup route，避免“测试已转 v2、文档仍复制 v1”的自相矛盾。

两项 DPAPI 测试分别通过 12 和 10 个断言；真实 LocalAppData manifest key 在测试前后均不存在。v2 bundle 通过 68 个 startup assertions、14 个 project cases、17 个 cycle cases 和 command provenance。

## 环境与包验收

- 项目本地 `.venv` 固定安装 PyYAML 6.0.3；`quick_validate` 通过，未修改全局 Python。
- portable ZIP 内 86 个受控文件 checksums 通过；doctor 为 `healthy`，dry-run 通过。
- portable、candidate 与安装树均为 79 个文件，missing/extra/mismatch 均为 0。
- portable SHA-256：`2f6cb8760dcfdcbf7e7f9b016b035dd9f4fab63dd021c5a024053face6b54273`。
- payload/installed tree SHA-256：`1dbf2849550afc311602a388ad5ee888b23b7c73da1d2e44e1a67f53fb8f0a25`。

## Windows 回归

candidate 与已安装根各完成一次全量回归。安装态机器摘要为 19 passed、0 failed、0 timed_out、0 blocked、1 not_run，摘要 SHA-256 为 `58f26ebc1adc1fe0ff0431b15debe4dba240db8c0427128b31608dd1bb9fa0c5`。

唯一 `not_run` 为 `test_math_research_legacy_successor_v8`。该测试要求一个真实、只读、包含至少 600 个继承工件的兼容历史项目。本轮搜索覆盖整个用户资料根、同步盘与代码根，未找到 `project.json`，因此没有用合成文件伪造验收。

处理决定：v0.1.0 只声明 repository foundation 和可复现数学执行器工程基线；不声明真实 legacy successor 端到端能力。该能力启用前必须提供真实夹具并通过源树前后哈希不变的完整测试。

## 部署与回滚

- 唯一安装根已从同一 candidate 更新，最终 `check_skill_install` 为 79 文件、0 missing/extra/mismatch。
- 部署前 79 文件完整备份保留在任务 staging；仅覆盖上述三个文件。
- 回滚时只允许在已安装文件仍等于 1.0.1 部署哈希时恢复三个旧文件；不得删除或重建整个安装根。

## Git/Release Gate

当前状态只表示“可以进入用户 diff 审核”。commit、push、annotated tag `v0.1.0` 和 GitHub Release 仍是独立动作，未经用户明确授权不得执行。许可证仍维持 `All rights reserved until a LICENSE file is selected.`。
