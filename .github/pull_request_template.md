## 目标

说明本 PR 解决的单一问题，以及它对应的 Phase/Milestone。

- 关联 Issue：
- Base/head commit：

## 变更范围

- [ ] 通用内核
- [ ] Experience
- [ ] Evaluator
- [ ] Evolution/Promotion
- [ ] Math Adapter
- [ ] Quant Adapter
- [ ] ML Adapter
- [ ] DL Adapter
- [ ] Skill payload
- [ ] 文档/治理

## 科研结论边界

列出本 PR 可以支持和明确不能支持的 claim。不得用工程测试代替数据或科研验收。

## 验证证据

- 测试命令：
- 结果：
- Manifest/报告路径：
- SHA-256 或版本：
- 跳过项及原因：
- clean archive install/demo（如适用）：

## 来源、许可证与第三方内容

- [ ] 变更由贡献者独立创作，或所有外部来源、版本、许可证和复制范围均已列出
- [ ] 新增/变更外部来源、模板、生成物或兼容性 fixture 时，已同步两份 provenance 文件
- [ ] `scripts/verify_source_provenance.py` 通过且 `unknown=0`
- 外部来源与处理决定：

## 数据、隐私与污染检查

- [ ] 未提交私有语料、hidden cases、凭据、原始数据或绝对用户路径
- [ ] 本 PR 不公开未修复漏洞或行为准则报告中的敏感细节
- [ ] Candidate 无 Evaluator/hidden 写读权限
- [ ] 新 case 的 lineage、split 和 contamination 状态已记录

## 回滚

说明恢复到哪个提交、schema 或 Champion；新增文件的删除必须再次核对当前 hash。

## 兼容性与治理

- [ ] 不改变公共合同
- [ ] successor schema、迁移、fixtures 与 golden pins 已提供
- [ ] 需要的 ADR 已新增/更新
- [ ] 支持矩阵与 `pyproject.toml`/CI 保持一致

## 发布

- [ ] 本 PR 不发布
- [ ] 合并后计划 Tag：`v...`
- [ ] Release notes 已准备
- [ ] Skill 安装/Champion promotion 需要独立批准
- [ ] PyPI、Tag、Release 和外部协调均未被本 PR 隐式授权
