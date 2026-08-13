# math-research-solve 1.0.0 baseline 验收

状态：**HOLD**。当前材料足以冻结并复现外部工程基线，但不足以宣称 Windows 全量回归通过，也不得据此创建 `v0.1.0` tag。

验收日期：2026-08-13。结论边界仅为工程完整性与回归状态，不代表数学研究质量、量化有效性、机器学习泛化能力或深度学习实验结论。

## 已通过

- portable ZIP SHA-256：`b1738edf87fed49c2f16f75b08809b1b5cf831038e78ec195e91d2926d4a2ae9`；包内 86 个受控文件校验通过。
- payload 与本机安装副本均为 79 个文件，missing/extra/mismatch 均为 0；双方 tree SHA-256 均为 `28f3dfeaa7edd4899e256106b55dc09b227439497691a953c541bfd6219677f5`。
- 便携安装器 doctor 为 `healthy`，显式外置报告路径后的 dry-run 通过；未使用网络、未执行提权变更、未安装或替换 Skill。
- 仓库自测 4 项通过，Python 脚本 AST 解析通过。
- 权限矩阵已同时提供人类可读版和机器可读版；当前仅为策略层约束，不声称已经实现进程级或主机级隔离。
- 公开材料扫描未发现本机绝对用户路径、用户名、私钥头或原始运行日志。

## Windows 全量回归

机器摘要：15 passed、1 failed、0 timed_out、3 blocked、1 not_run。摘要 SHA-256 为 `1018ccefe518fb517386e03fcbd8ec9f8453308a132f8b8e9a2612d5ce8dcbf5`。

唯一功能性失败为 `test_math_research_v2_bundle_regression`，两次完整执行均在同一语义断言失败：`full SKILL routes startup expected true`。冻结脚本先原样复制 `SKILL.md`，随后把生成的 v1 测试断言机械替换为 v2；但冻结的 `SKILL.md` 明确保留 v1 启动路径，因此生成夹具要求的 v2 路由与被测文档不一致。该问题暂按 baseline regression defect 登记，不修改已安装 Skill 1.0.0。

环境阻塞项：

- 两项兼容/控制路径测试需要已安装的 DPAPI manifest key；当前身份下该 key 不存在。未擅自创建本机密钥状态。
- `skill_quick_validate` 需要 PyYAML；当前可用的两个 Python runtime 均未安装该依赖。未在全局 Python 中安装包。
- `test_math_research_legacy_successor_v8` 要求一个真实、只读且包含至少 600 个工件的历史项目夹具；已检查约定的本地候选根，未找到 `project.json`，因此记为 `not_run`，未用合成数据冒充真实继承验收。

## Release Gate

在以下事项关闭前保持 HOLD：

1. 在外部 Skill 的后续修订中修复或重新定义 v2 bundle differential，并用冻结的新版本重新跑基线；
2. 在用户明确同意后，使用隔离环境补齐 PyYAML 并重跑 validator；
3. 决定是否允许创建 DPAPI 测试状态，或为测试提供不污染生产状态的显式 override；
4. 用户提供符合约束的真实旧项目夹具后补跑继承用例；
5. 用户审核 diff 和验收报告后，才允许 commit、push；只有 Phase 0 Gate 转为 PASS 后才允许 annotated tag `v0.1.0`。

许可证仍维持 `All rights reserved until a LICENSE file is selected.`，不擅自添加开源许可证。
