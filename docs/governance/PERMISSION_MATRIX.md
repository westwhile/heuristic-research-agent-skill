# 权限矩阵 v1

机器可读权威文件：[`policies/permission-matrix-v1.json`](../../policies/permission-matrix-v1.json)。

## 角色分离

| 角色 | 可以做 | 明确禁止 |
|---|---|---|
| Production Executor | 读取冻结任务和 promoted snapshot；写自己的 staging/archive | 读取 hidden、改 Candidate/Skill、修改 Champion |
| Experience Miner | 读取显式导出的 packet；写经验和分析候选 | 回写权威项目、读取 hidden、修改生产 Skill |
| Candidate Builder | 读取公开语料/case/baseline；写 immutable candidate | 读取 private/hidden、修改 Evaluator、安装或晋级 |
| Public Evaluator | 读取 Candidate 和公开 suite；写公开报告 | 修改 Candidate、读取 hidden、晋级 |
| Private Evaluator | 在独立权限域读取 Candidate/hidden；写聚合报告 | 返回 hidden 原文、修改 Candidate、晋级 |
| Promotion Controller | 读取报告和策略；写决策、激活和回滚 receipt | 修改评测结果、读取 hidden 原文 |
| Release Maintainer | 经批准执行 branch/commit/push/tag/Release | 以 Tag 替代 PromotionDecision |

## 当前执行状态

- 公共仓库：由仓库规则、PR review 和后续 CI 实施；
- Private Evaluator：尚未实现，当前仅为策略，不声称物理隔离；
- Champion activation：尚未实现；
- 本矩阵不会授权 commit、push、Tag、Release、Skill 安装或生产晋级。
