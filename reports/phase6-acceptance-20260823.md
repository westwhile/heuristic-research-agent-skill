# Phase 6 验收状态：Deep Learning 治理扩展（2026-08-23）

状态：**L1–L3 commit-bound PASS；L4 本地工作树定向 PASS；Phase 6 尚未最终验收。**
当前证据上限为 synthetic engineering，不支持真实框架/GPU、真实数据、科研、
生产恢复或 Skill 能力声明。

## 分层状态

| 层 | 交付 | 当前状态 |
|---|---|---|
| L1 | `dl-run-manifest/v1`、ADR-0009、configuration-only Gate | commit `4a1b9e6`，已推送 PR #21 |
| L2 | runner 0.1.0、dry-run/CPU fixture、预算与失败终态 | commit `0158c294`，已推送 PR #21 |
| L3 | runner 0.2.0、checkpoint/exact resume/early stopping、selector 0.1.0 | commit `322159b8`，archive 与四项 CI PASS |
| L4 | 10-case catalog、5 个合成 Case Package、study reporter 0.1.0、ablation/scale/compute-matched、DL support matrix | 本地工作树；尚无 commit-bound Gate |

L3 的 mainline 证据为 Draft PR #21 run `32630395189`：Windows/Ubuntu ×
Python 3.12/3.14 四项成功，两个 Windows governance 步骤成功。该 run 的
`headSha=322159b8bc0abe5dcbca74b22d5cc1fd4545802f`，不得拿来证明尚未提交的 L4。

## L4 Gate 对账

| Gate | 本地证据 | 状态 |
|---|---|---|
| CPU/small fixture 不等于 GPU full training | report 与矩阵固定 `declared_not_observed` / `not_loaded` / `not_performed` | PASS（声明边界） |
| 失败 seed 与训练中断进入报告 | OOM/NaN/interrupt catalog + `failure_inventory` + `incomplete_evidence` | PASS（合成注入） |
| best checkpoint 不代表总体稳定 | expected-seed 完整性 Gate、mean/variance/observed range、固定 limitations | PASS |
| 资源不一致时不直接比较 | scale case 保留逐 seed FLOP mismatch；`comparison_allowed=false` | PASS |
| compute-matched baseline | samples/tokens/FLOP proxy 与相关 caps 逐 seed 对齐 | PASS（proxy only） |
| checkpoint 只用 locator/hash | report 不含 model/optimizer payload；篡改 fail-closed | PASS |
| resume 不重复计费 | L3 uninterrupted/resume 对账继续覆盖 cumulative/segment ledger | PASS（合成内存） |
| 跨 GPU reproducibility envelope | 明确列为未验证 | PASS（未补造） |

## 当前动态验证

- study + catalog + Case Package 定向电池：17/17 PASS；
- 三份 canonical study report 可重复获得相同 SHA-256；
- staged 工作树全量 suite：Python 3.14.5 为 971/971 PASS，Python 3.12.13
  为 971/971 PASS；
- 尚未运行 L4 exact commit 的真实 `git archive` 或 push CI；工作树结果不能替代
  后续获授权的 commit-bound Gate。

## 未完成与发布停止点

- 未执行 PyTorch、TensorFlow、JAX、CUDA、ROCm 或 MPS；
- 未观察真实硬件、显存 OOM、NaN、抢占、分布式/混合精度或外部 store；
- 没有真实数据或真实故障 Case Package；5 个 Case Package 均为合成工程证据，
  没有真实科研/采用证据；
- L4 尚未 commit/push，PR #21 保持 Draft；
- 未创建/合并 PR、未创建 `v0.7.0` Tag 或 Release。

因此 `v0.7.0` Gate 保持关闭。下一机械 Gate 是在单独授权后创建 L4 commit，
随后对该 exact commit 运行真实 `git archive` 双解释器验证；push 与 CI 仍需下一次
独立授权。
