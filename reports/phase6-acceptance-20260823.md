# Phase 6 验收状态：Deep Learning 治理扩展（2026-08-23）

状态：**L1–L4 mainline synthetic engineering PASS；Phase 6 真实执行与发布尚未验收。**
当前证据上限为 synthetic engineering，不支持真实框架/GPU、真实数据、科研、
生产恢复或 Skill 能力声明。

## 分层状态

| 层 | 交付 | 当前状态 |
|---|---|---|
| L1 | `dl-run-manifest/v1`、ADR-0009、configuration-only Gate | commit `4a1b9e6`，已推送 PR #21 |
| L2 | runner 0.1.0、dry-run/CPU fixture、预算与失败终态 | commit `0158c294`，已推送 PR #21 |
| L3 | runner 0.2.0、checkpoint/exact resume/early stopping、selector 0.1.0 | commit `322159b8`，archive 与四项 CI PASS |
| L4 | 10-case catalog、5 个合成 Case Package、study reporter 0.1.0、ablation/scale/compute-matched、DL support matrix | implementation `45047261`；由 merge commit `6c63c0ba` 合入 main，main CI PASS |

L4 的 mainline 证据为 merge commit
`6c63c0bad88f032fb1091cdc5c91242bf22b2087` 与 main push CI run
`32634831816`：Windows/Ubuntu × Python 3.12/3.14 四项成功，两个 Windows
governance 步骤成功。该 run 的 `headSha` 与 merge commit 完全一致；它只证明
该提交的合成平台工程行为。

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
- PR final head `2f5f11dc64c07a5227b58d69c294112f50c5a138` 的真实
  `git archive`：Python 3.14.5 与 Python 3.12.13 均为 971/971 PASS，各 1 个
  预期 Git tracking skip，明确输出 `ARCHIVE GATE: PASS`；
- merge commit `6c63c0bad88f032fb1091cdc5c91242bf22b2087` 与 PR final head
  的 Git tree SHA 均为 `db950181d9c620fff6343659157f9950a6fe4505`，无 merge-time
  内容改写；
- merge commit 的 main push CI run `32634831816` 四项 jobs 全绿，四项
  clean-archive install/demo 成功，两个 Windows PowerShell governance 步骤成功。

## 未完成与发布停止点

- 未执行 PyTorch、TensorFlow、JAX、CUDA、ROCm 或 MPS；
- 未观察真实硬件、显存 OOM、NaN、抢占、分布式/混合精度或外部 store；
- 没有真实数据或真实故障 Case Package；5 个 Case Package 均为合成工程证据，
  没有真实科研/采用证据；
- PR #21 已通过 merge commit `6c63c0bad88f032fb1091cdc5c91242bf22b2087`
  合入 `main`，远端 feature 分支保留；
- 未创建 `v0.7.0` Tag 或 Release，最新正式 Release 仍为 `v0.6.1`。

因此 `v0.7.0` Gate 保持关闭。L4 的 commit-bound synthetic engineering Gate
不能替代真实框架、硬件、数据、跨环境复现、外部采用或生产恢复证据；这些层级
均需独立授权和新证据包。
