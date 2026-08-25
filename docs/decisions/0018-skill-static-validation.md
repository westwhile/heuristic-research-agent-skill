# ADR-0018：Candidate Skill 静态验证与平台元数据分层

- 状态：Accepted（Phase 7 P7B3）
- 日期：2026-08-26
- 范围：P7B2 byte-closed Skill candidate 的纯 in-process 静态验证

## 背景

P7B2 只证明 payload 与 eligibility evidence 的结构和字节闭包。它不要求
`agents/openai.yaml`，不检查候选与 registry snapshot 的名称/触发碰撞，也没有把正负
Router 样例、平台元数据和 descriptor-only payload diff 绑定进可发布结果。直接进入运行时
会混淆结构草拟、静态验证与语义/行为验证。

## 决策

1. 新增 `skill-static-validation-receipt/v1`，直接 pin exact
   `skill-candidate-bundle/v1`；`static_pass` 与 `static_fail` 都是可发布终态。
2. 单一 interface 为
   `validate_skill_candidate(candidate_bundle, payload_bytes,
   validation_contract, validated_at)`；它纯 in-process、无文件系统或进程 I/O。
3. payload byte set、SHA-256、大小和 strict UTF-8 必须与 P7B2 精确一致；无法完整扫描的
   payload 同时关闭 integrity 与 restricted-content Gate。
4. P7B3 最小平台 profile 必须包含 exact `agents/openai.yaml`：只允许
   `display_name`、25—64 字符 `short_description`、显式 `$skill-name` 的
   `default_prompt`，并固定 `allow_implicit_invocation: false`。它不代表 receiver 已加载该元数据。
5. Skill description 必须覆盖声明的正触发与排除字符串；registry 只执行 Unicode NFKC、
   casefold 与空白归一化后的 exact name/trigger collision，不宣称语义检索。
6. Router 样例至少各有一个 `select_candidate` 与 `reject_candidate`，并必须精确对应声明的
   trigger/exclusion；本批不运行 Router 或 Agent。
7. payload diff 只比较 baseline descriptor 与 candidate descriptor；baseline bytes 未闭包时
   不得把 diff 升级为行为或来源证明。
8. receipt 中 semantic/fresh-session/private/publication/installation/activation/runtime claims
   永远为 false；P7B3 不物化、不安装、不加载 Skill。

## 结果与保留风险

Math/Quant 合成 fixtures 证明同一 interface 能产生静态通过和可审计拒绝记录。平台 metadata
仍是候选字节，registry 和 Router 样例仍是调用方提供的静态 snapshot；真实语义质量、reviewer
独立性、运行时发现、隐式触发、Agent 行为与负迁移均未验证。

## 拒绝方案

1. 原地修改 P7B2 family：违反冻结 family 与事实轴分离。
2. 调用官方初始化器或 `quick_validate.py`：需要物化真实 Skill 目录，越过 P7B3 授权边界。
3. 用字符串碰撞结果声称 Router 正确：静态声明不能替代 fresh-session 行为证据。
4. 把 receiver-owned metadata 当成可覆盖的 canonical payload：会破坏接收方配置所有权。
