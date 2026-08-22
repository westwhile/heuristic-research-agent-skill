# Phase 5 L5 重复实验报告（2026-08-21）

状态：**合成工程证据**。执行器为标准库纯函数 `synthetic-ml-runner/0.3.0`；结果只用于验证确定性、seed 记录、baseline/resource parity 与证据链，不用于声称真实模型效果。

## 两条垂直切片

两条切片均走完 `ml-task/v1 → normalize_task → research-task/v1 → evaluation-contract/v3 → runner → ml-evidence/v2 → validate_claim`。每条实验使用 seed `[3, 5, 7]`；E2E 在同一进程独立调用三次，三份 canonical artifact 字节 hash 完全相同。

| 切片 | split 执行摘要 | artifact SHA-256 | candidate accuracy/F1（逐 seed） | baseline accuracy/F1（逐 seed） |
|---|---|---|---|---|
| 非时间 group | 6 groups，group key=`site`，零跨 partition group | `5b07533d64911b8926fe4d875970f6f70b5226d22d0354f380bf07455fe7ccc3` | `1/1` × 3 | `0.5/0` × 3 |
| time-series | gap=2、embargo=2、4 个排除行 | `0d89dbcb56333c7a1ebb6cdafb362bff8e1821aaeea1681b47d794ae9aff5ea9` | `1/1` × 3 | `0.5/0` × 3 |

两条切片的 candidate/baseline 均使用 20 epochs、每 seed 120 sample visits；`resource_parity=true`，唯一 changed axis 为 model，dataset/split/assignment/resource/seeds/heuristics 均记录为 frozen axes。均值、population variance 与 observed range 全部落 artifact；本例三个 seed 的指标相同，故方差为 0。

## 解释边界

指标完全一致是刻意可分的小型合成 fixture 的结果，不是稳健性或真实泛化证据。runner 虽完整记录三个 seed，但这些记录的 provenance 是 synthetic，不能满足 public/real 重复实验 Gate；`validate_claim` 因此仍登记 `synthetic-evidence-cap`、`single-seed-cap`、`frozen-holdout-missing`，并点名 OOD/subgroup/calibration/drift 缺口，最终返回 `inconclusive`。artifact hash 只绑定当前输入与 runner 规范结果，不把合成分数提升为数据验收。

本轮定向重复/E2E 电池 4/4 通过；L5.1 独立审核修复还确认 time-series 的 future holdout 必须晚于 test，既有两条切片 artifact hash 未漂移。工作树双环境全量 **851/851 ×2**；无 `.git`、无 `.venv`、只含 Git 跟踪/非忽略文件的 775-file clean snapshot 双环境同为 **851/851 ×2**，各有 1 个预期 skip（归档中无法执行 Git tracking 检查）；PowerShell 治理 **33 assertions / 6 cases** 通过。
