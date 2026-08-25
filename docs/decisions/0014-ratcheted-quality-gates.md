# ADR-0014: Ratcheted quality gates

- 状态：Accepted（Correctness Reset CR7）
- 日期：2026-08-25
- 范围：CI engineering quality gates
- 关联：`pyproject.toml`、`.github/workflows/ci.yml`、`docs/governance/SUPPORT_MATRIX.json`

## 背景

仓库已有 1067 项标准库测试和 Windows/Ubuntu × Python 3.12/3.14 required
lanes，但 Ruff 配置从未进入 CI，类型检查与覆盖率也没有可执行门槛。直接把现有
完整 Ruff 规则和 mypy 一次性扩到所有历史 Adapter、脚本与测试会产生大范围、难以
审查的机械 diff；不执行任何 Gate 则无法阻止关键 Core/Evaluation/Evolution seam
继续积累缺陷。

## 决策

1. 质量工具只进入固定版本的 `quality` optional dependency，不进入运行时依赖：
   `ruff==0.16.3`、`mypy==2.3.1`、`coverage==7.15.4`。
2. Ruff 采用显式 ratchet：全仓 `src tests scripts` 阻断 E9/F63/F7/F82 高置信
   语法与 Pyflakes 致命项；Core、Evaluation、Evolution 三个关键 seam 额外执行
   `pyproject.toml` 中完整 E/F/I/UP/B 规则。嵌入长 HTML 模板的
   `evaluation/reports.py` 只豁免 E501，不豁免其他规则。
   两条 Ruff 命令均使用 `--no-cache`，避免在 exact archive 树中制造未跟踪
   `.ruff_cache` 并污染后续 provenance/test Gate。
3. mypy 以 Python 3.12 为最低语言合同，对相同三个关键 seam 执行
   `check_untyped_defs` 且关闭增量读取；mypy 2.3.1 仍会写 AST cache，因此 CI 将
   `cache-dir` 定向到 `runner.temp`，不污染 exact archive 树。其他目录尚未被类型
   Gate 覆盖，不得表述为全仓类型安全。
4. 原完整 unittest 步骤改由 coverage.py 驱动，仍执行同一 discovery 命令并开启
   branch coverage；`research_evolution` 的最低总覆盖率固定为 80%。覆盖率是回归
   门槛，不是语义正确性证明。
5. 三类 Gate 均在四个 required lanes 执行；版本、命令、scope 与限制同时固化在
   machine-readable support matrix，并由 contract test 对账。
6. 后续只允许扩大严格路径、规则或覆盖率 floor；缩小 scope 或降低 floor 必须提交
   新 ADR、说明基线证据并接受独立 review。

## 结果与限制

CR7 关闭的是“质量配置存在但不执行”的工程缺口，并修复关键 seam 当前可复现的
类型、异常链、显式配对长度和导入纪律问题。它不证明全仓 Ruff 清零、全仓静态类型
安全、100% 覆盖、真实 Agent 执行、科研有效性、hidden evaluator 独立性或晋级安全。
质量依赖均从上游包索引获取且不 vendoring；来源与许可证记录见
`SOURCE_PROVENANCE.json`。
