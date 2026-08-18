# Git、提交、推送、Tag 与 Release 流程

## 1. 核心原则

- `commit`、`push`、`merge`、`tag`、`GitHub Release`、`Skill 部署` 和 `Champion promotion` 是不同动作；
- 每个动作分别验收，后一个动作不能反向证明前一个动作正确；
- 未经用户明确批准，不执行 commit、push、merge、tag、Release 或部署；
- 不 force-push `main`、release branch 或任何已共享分支；
- 不移动、覆盖或删除已推送 Tag 来掩盖发布错误。

## 2. 分支模型

```text
main                         已验收、可发布的历史
bootstrap/*                  初始仓库建设
feat/<scope>                 功能
fix/<scope>                  缺陷修复
docs/<scope>                 文档
test/<scope>                 测试/benchmark
release/vX.Y.Z               发布冻结
hotfix/vX.Y.Z-<scope>        已发布版本紧急修复
```

分支必须从最新已验证 `main` 创建，禁止在 dirty worktree 切换分支。并行工作使用不同 worktree/分支，不共享同一 staging 目录。

### Windows/Codex 凭据边界

GitHub CLI 默认把 OAuth Token 保存到 Windows Credential Manager/keyring。Codex 沙箱进程即使继承了同一个 `USERPROFILE`、`APPDATA` 和 GitHub CLI `hosts.yml`，也使用独立 Windows 身份，因此不能读取真实用户的 keyring 条目。此时沙箱内的 `gh auth status` 可能显示 Token 无效，而真实 Windows 用户上下文仍然有效。

发布前运行：

```powershell
pwsh -NoProfile -File scripts/check_github_auth_context.ps1 -Json
```

- `authenticated`：当前真实用户 keyring 可用且账户符合预期；
- `requires_windows_user_context`（退出码 3）：当前是 Codex 沙箱，应在受控真实用户上下文重跑；这不是 Token 过期；
- `authentication_failed_in_user_context`（退出码 1）：真实用户认证确实失效，此时才执行 `gh auth login -h github.com`；
- `environment_token_refused`（退出码 4）：检测到环境变量 Token 覆盖，先清除覆盖再使用 keyring；
- `github_api_verification_failed`（退出码 6）：keyring 账号可读，但 GitHub API 验证失败；先检查网络并重试，不据此重新登录；
- `unexpected_authenticated_account`（退出码 2）：认证有效但登录账号与预期不符，先切换 active 账号再发布；
- `gh_cli_missing`（退出码 5）：未安装 GitHub CLI，先安装再运行发布流程。

禁止使用 `--insecure-storage`、在 `hosts.yml` 中保存明文 Token、把 `GH_TOKEN`/`GITHUB_TOKEN` 固化到用户环境、仓库、日志或自动化脚本。Codex 发起需要 keyring 的 GitHub 操作时，应由执行层切换到真实 Windows 用户上下文，而不是把凭据复制进沙箱。

## 3. Commit 规范

采用 Conventional Commits 子集：

```text
feat(core): add versioned claim records
fix(quant): reject post-signal fundamentals
test(evaluator): add false-completion mutation cases
docs(plan): define phase 3 acceptance gates
chore(repo): initialize research evolution project
refactor(adapter): deepen evaluation contract seam
```

要求：

- 每个 commit 只有一个可解释目的；
- schema 与 migration/compatibility tests 同时提交；
- Heuristic patch 与 regression case 同一 PR，必要时同一 commit；
- 不提交生成报告、私有数据或大型 artifact；
- commit message 不声称未被验收的科研能力。

## 4. 本地提交 Gate

提交前：

```powershell
git status --short --branch
git diff --check
git diff --stat
git diff
```

然后运行当前 Phase 规定的验证，并保存机器可读报告。确认：

- 变更仅包含 Issue/Phase 范围；
- 没有凭据、绝对用户路径、private/hidden 内容；
- 没有用户无关修改；
- generated artifacts 被排除；
- 测试、跳过和未运行项均被准确报告。

只有在用户批准后执行：

```powershell
git add -- <reviewed paths>
git diff --cached --check
git diff --cached
git commit -m "<type>(<scope>): <summary>"
```

禁止使用 `git add -A` 代替路径级审核。

## 5. Push 与 PR Gate

Push 前核对：

```powershell
git status --short --branch
git log --oneline --decorate -n 10
git remote -v
git fetch --prune origin
git rev-list --left-right --count origin/main...HEAD
```

用户批准后首次 push：

```powershell
git push -u origin <branch>
```

后续仅推当前分支：

```powershell
git push origin <branch>
```

然后：

1. 核对远端 branch head SHA 等于本地 `HEAD`；
2. 使用仓库 PR 模板创建 draft PR；
3. 附测试、manifest、科研结论边界和回滚；
4. CI 通过后才转 ready；
5. 评审改动不重写共享历史，追加 commit；
6. 合并方式在仓库策略确定后固定，避免混用造成 lineage 混乱。

## 6. Phase Tag 规则

使用 SemVer annotated tag：

```text
v0.1.0  repository/governance baseline
v0.2.0  core records
v0.3.0  math+quant vertical slices
v0.4.0  public evaluator
v0.5.0  experience/heuristic registry
v0.6.0  ML adapter
v0.7.0  DL adapter
v0.8.0  candidate builder
v0.9.0  private evaluator interface/promotion rehearsal
v1.0.0  controlled production-ready governance baseline
```

预发布使用：

```text
v0.4.0-rc.1
v1.0.0-rc.1
```

Tag 必须指向已合并到 `main` 的精确提交。创建前：

```powershell
git switch main
git pull --ff-only origin main
git status --short --branch
git log -1 --format=fuller
git tag --list "vX.Y.Z"
```

重新从 **`git archive HEAD` 导出树**（或全新 clone）运行 release tests——工作树内测试不构成发布证据：未跟踪/被忽略的文件在工作树中存在、在导出树中缺席，只有导出树运行能杀死这类缺件（v0.5.0 教训）。使用：

```powershell
python scripts/verify_archive_suite.py <第二 Python 解释器路径>
```

再生成：

- source tree manifest；
- SHA-256 checksums；
- test/evaluation summary；
- dependency/environment manifest；
- changelog 与 known limitations。

用户批准后创建 annotated tag。**tag 目标必须等于 archive Gate 输出的被测提交**——把 `ARCHIVE_COMMIT` 作为显式 target，而非给执行时的当前 HEAD 打 tag：

```powershell
$testedCommit = "<ARCHIVE_COMMIT 输出的完整 SHA>"

if ((git rev-parse HEAD).Trim() -ne $testedCommit) {
    throw "HEAD 已偏离 archive Gate 验证提交"
}

git tag -a vX.Y.Z $testedCommit -m "Release vX.Y.Z: <verified capability>"

if ((git rev-list -n 1 vX.Y.Z).Trim() -ne $testedCommit) {
    throw "Tag 目标与 archive Gate 提交不一致"
}

git show --stat --decorate vX.Y.Z
```

若本机配置了可信签名，可使用 `git tag -s`；不得因为没有签名而伪称 tag 已签名。

Tag push 仍需单独批准：

```powershell
git push origin refs/tags/vX.Y.Z
```

Push 后通过 GitHub API/connector 核对远端 tag target SHA。

## 7. GitHub Release

Release 只从已核对的 Tag 创建。Release notes 至少包含：

- 已实现能力；
- 明确未实现/未验证能力；
- schema/Adapter compatibility；
- 测试与 evaluation 层级；
- 数据、模型、硬件和平台限制；
- breaking changes 和 migration；
- checksums/manifest；
- rollback target。

公共 Release 不上传：

- private/hidden cases；
- 原始研究数据；
- checkpoint；
- 凭据或内部路径；
- 未脱敏运行 trace。

## 8. Skill 发布与安装

如果某一版本包含可安装 Skill：

1. 从 Tag checkout 创建 staged payload；
2. 排除 repo metadata、tests cache、reports、backups 和 receiver config；
3. 运行 Skill 自身 tests、`quick_validate.py` 和 `check_skill_install.ps1`；
4. 对将覆盖的安装文件做备份和 pre-write hash；
5. 用户批准后从同一 staging payload 同步到授权 roots；
6. 从安装 root 重跑 tests 和 install check；
7. 生成 installation receipt。

GitHub Release 成功不等于 Skill 安装成功。

## 9. Champion Promotion

Champion promotion 需要：

- Candidate bundle hash；
- Champion baseline hash；
- public/private/hidden report hash；
- Promotion policy version；
- 人工批准；
- canary/rollback plan；
- activation receipt。

Git Tag 或 Skill 安装均不能自动修改 Champion pointer。

## 10. 发布失败与修复

- Tag 未 push：可删除本地错误 Tag，但须记录原因；
- Tag 已 push：不移动 Tag；修复代码后发布新 patch，如 `v0.4.1`；
- Release artifact 错误：先撤下错误 artifact/标记 Release，保留审计记录，再发新版本；
- 部署失败：使用安装前备份，仅恢复本次覆盖文件；
- Champion 退化：执行 Promotion receipt 对应 rollback，不删除历史评测和决策。

## 11. 每阶段发布清单

- [ ] Phase 验收项全部有证据
- [ ] `main` clean，HEAD 与远端一致
- [ ] 测试从 `git archive HEAD` 导出树（或全新 clone）运行，双解释器通过——工作树内运行不算数
- [ ] annotated tag target == `ARCHIVE_COMMIT`（创建后以 `git rev-list` 核对相等）
- [ ] 没有 private/hidden/secret/path 泄漏
- [ ] Manifest 与 checksums 生成并验证
- [ ] Changelog/known limitations 完成
- [ ] 用户批准 commit（若尚未提交）
- [ ] 用户批准 push
- [ ] PR/CI/review 完成
- [ ] 用户批准 annotated tag
- [ ] 远端 Tag SHA 已核对
- [ ] 用户批准 GitHub Release
- [ ] Skill 安装另行批准
- [ ] Champion promotion 另行批准
