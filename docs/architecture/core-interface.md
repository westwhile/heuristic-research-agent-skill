# Core Interface（Phase 1B）

- 版本：Phase 1B（`feat/core-publication-graph-v1`）
- 覆盖 schema：`research-task/v1`、`research-claim/v1`、`research-evidence/v1`（schema 文本相对 Phase 1A 零漂移）
- 代码位置：`src/research_evolution/core/`；schema 文本：`schemas/core/`；fixtures：`tests/fixtures/core/`

## 1. 范围与非目标

Phase 1A 交付了通用记录内核的最小可验证子集（严格 JSON、schema 分派校验、canonical SHA-256、safe relative path）。Phase 1B 在其上增加**写路径**：

- create-new / append-only 发布（`publish_record`）；
- 记录图 manifest 的确定性生成与全图验证（`verify_record_graph`）；
- `supersedes` lineage 校验（悬空/自引用/跨类型引用/cycle）与 Claim/Evidence 双向一致性。

三个 v1 schema 文本、全部 53 个 fixtures 与 golden hash 保持不变。

明确不包含（属于后续批次，不在本接口承诺内）：

- `Run`、`FailureObservation`、`FailureAnalysis`、`ExperiencePacket`、`ResearchCasePackage` 等其余 schema（ExperiencePacket 待 ADR 定性后方可定义）；
- 隐私分级与 redaction 执行器（本批只能发布到调用方显式传入的本地 repository root，不支持跨项目导出）；
- CLI、Adapter、数据库、安装与部署；
- 跨进程并发发布（仅保证进程内按 store root 串行化）；
- 只有单一实现的 Storage Adapter 端口（理由见 `docs/decisions/0002-core-publication-graph-interface.md`）。

## 2. 公共接口

唯一入口模块是 `research_evolution.core`，不向每个 schema 暴露浅层包装：

```python
from research_evolution.core import (
    load_record,                  # (str | bytes | bytearray, *, schema_root=None) -> Record
    Record,                       # .schema_id / .data / .canonical_bytes / .sha256
    canonical_bytes,              # (value) -> bytes
    canonical_sha256,             # (value) -> str, 64 位小写 hex
    load_strict_json,             # 只做严格解析，不做 schema 校验
    validate_safe_relative_path,  # (str) -> str；不做归一化，只接受已规范形式
    publish_record,               # (source, *, root, schema_root=None) -> PublicationReceipt
    verify_record_graph,          # (root, *, schema_root=None) -> GraphVerificationReport
    PublicationReceipt,           # .schema_id / .record_id / .sha256 / .path / .already_present / .manifest_sha256 / .to_dict()
    GraphVerificationReport,      # .ok / .violations / .records_total / .families / .forks / .manifest_sha256 / .to_dict()
)
```

与总体架构 §4.1 三操作的对齐方式由 ADR-0002 固定：保留 `load_record`；新增 `publish_record`、`verify_record_graph`；`validate_and_freeze_task` 暂不实现（它目前只会是 `load_record` 的浅包装，等出现额外冻结语义再引入）。

`Record` 不变量：`record.sha256 == canonical_sha256(record.data)` 恒成立。结构性保证：

- 构造受内部令牌控制，唯一获取途径是先校验的 `load_record`，直接构造抛 `CoreError`；
- 构造时对已校验载荷做迭代式深拷贝（`_copy_json_tree`，不走 `copy.deepcopy`），调用方之后修改自己的对象不会影响记录；
- `.data` 返回同一路径的新鲜深拷贝，调用方无法通过访问器改动被哈希的内容；
- 解析器是自研迭代下降解析器（`_strict_json.py`，显式容器栈、调用级深度预算），**不读取也不修改进程级 `sys.getrecursionlimit()`**——不存在解析期全局状态，因此并发 `load_record` 调用之间无竞态，也不依赖 stdlib `json` 的 scanner 选择（C/纯 Python 行为一致性由 differential parity 回归证明）；解析后检查、深拷贝、canonical 输入域检查、序列化器同样为显式栈迭代实现（共享 `_walk.py` walker）——深度协议不随调用方 `sys.setrecursionlimit()` 设置漂移，深但合法的记录不会在解析、校验、构造、访问或哈希路径上泄漏裸 `RecursionError`。

**数值模型**：JSON 数字是任意精度十进制。整数字面量解析为 Python `int`（任意精度），小数字面量解析为 `decimal.Decimal`——永不解析为二进制 float，因此 `9007199254740992.0` 与 `9007199254740993.0` 是两个可区分的记录，`1e-999` 不会下溢成 `0.0`。数值上限是冻结协议常量（`_limits.py` 的 `MAX_INT_DIGITS` / `MAX_DECIMAL_SCALE` / `MAX_WALK_DEPTH`），不随运行时配置（`PYTHONINTMAXSTRDIGITS` / `sys.set_int_max_str_digits()`）漂移：同一记录在任何机器上合法性与哈希一致。直接调用 canonical 接口时传入的 Python `float` 经 `Decimal(repr(...))` 规范化，与精确十进制路径不分叉；对精度敏感的调用方应使用 `load_strict_json` / `load_record` 的结果或显式 `Decimal`。

错误分类（全部继承 `CoreError`，内核失败不会泄漏其他异常类型）：

| 异常 | 触发 |
|---|---|
| `StrictJsonError` | 编码/BOM/语法错误、duplicate key、非有限数、孤立 surrogate、过深嵌套、超冻结协议位数整数、十进制规模超限字面量、顶层非 object、canonical 入口的非 JSON 数据模型值 |
| `UnknownSchemaError` | 缺失或非字符串 `schema` 字段、未注册的 schema id |
| `RecordValidationError` | schema 校验失败；`.violations` 给出全部违规路径 |
| `SchemaDefinitionError` | schema 文件自身非法（关键字值类型/范围/组合约束违规、文件名/$id/const 不一致、重复 id） |
| `UnsafePathError` | 直接调用路径校验时的违规（schema 校验中则记入 violations） |
| `PublicationError` | 发布违反 append-only 合同：同一逻辑 id 以不同内容重复发布（修订必须新 id + `supersedes`）、schema family 无已知身份字段 |
| `StoreIntegrityError` | 发布前在 root 锁内对既有 store 做完整对账，任何完整性发现（manifest 不可解析/非 canonical 字节/条目篡改、条目指向的记录缺失/损坏、未登记记录、重复逻辑 id、records/ 树内异物或 reparse point、保留节点类型异常或 stat 不可判定、records/ 存在而 manifest 缺失）都拒绝发布——在写入任何东西之前抛出；唯一例外是待发布记录自身的同内容崩溃孤儿；写入阶段的全部 OS 失败（存储目录创建、暂存文件打开/写入/fsync、记录硬链接、manifest 替换；如 root 祖先为普通文件、磁盘满、只读 manifest）同样抛此错而非裸 OS 异常，且不产生部分提交；验证路径不抛出，而是逐项记入 violations |

## 3. 记录模型

### 3.1 research-task/v1

冻结研究问题、对象域标签、范围、资源、权限、完成标准与允许的外部影响。`domain` 只是标签；`domain_context` 是唯一扩展点，内核只存储和哈希、从不解释，领域语义由 Adapter 处理。

### 3.2 research-claim/v1

`claim_type` 固定为七类治理值（`engineering_claim / data_claim / mathematical_claim / empirical_claim / predictive_claim / strategy_claim / production_claim`）。Claim 的立场与证据成熟度是**两条独立坐标轴**：

- `disposition`（本条记录的生命周期处置）：`proposed / supported / refuted / inconclusive / superseded / withdrawn`。`inconclusive` 是合法终态，不得被强行归入 supported/refuted；
- `evidence_maturity`（治理证据阶梯，梯级定义见 `docs/governance/RESEARCH_CLAIM_GOVERNANCE.md`）：`draft / engineering_verified / data_accepted / evaluation_eligible / empirically_supported / mathematically_verified / externally_validated / production_observed`。哪些梯级对哪些 `claim_type` 可达是领域 Adapter 策略，内核不规定。

证据绑定是硬约束（object 级扩展关键字 `x-conditional-min-items` 强制）：当 `disposition ∈ {supported, refuted, superseded, withdrawn}` 或 `evidence_maturity ≠ draft` 时，`supporting_evidence` 至少引用一条证据（可选 `sha256` 钉住该证据记录的确切版本）；只有 `proposed`/`inconclusive` 且 `draft` 的组合才允许空证据数组——行政性终态（superseded/withdrawn）同样不豁免证据引用。`limitations` 与 `non_entailments` 允许显式空数组，但字段不可省略。`supersedes` 指向前一版本，append-only 修订。Claim 不会自我晋级：只有被引用的证据与后续审核能支持它。

### 3.3 research-evidence/v1

绑定生产者（工具/版本/可选模型）、输入清单、生成时间、内容哈希（权威）、适用范围、证据等级和已知限制。

- 每个输入必须有 `name` 与 `kind`（code/config/data/case/environment/runner/other），且 `locator` 与 `sha256` **至少存在一个**（`x-at-least-one-of` 强制），不允许完全不可定位、不可验证的输入；
- `evidence_level` 是有意的自由字符串：证据阶梯是领域语义，由各领域 Adapter 约束；内核永远不自动升级证据等级；
- `claim_ids` 与 Claim 的 `supporting_evidence` 之间的一致性由 `verify_record_graph` 在图阶段强制（§10）：单向链接、悬空引用与 pin 不符均为 violation。

## 4. 严格 JSON 规则

1. 只接受 UTF-8（`str` 或 UTF-8 `bytes`）；BOM 一律拒绝；
2. 任意嵌套层级的 duplicate object key 一律拒绝（即使值相同）；
3. `NaN`/`Infinity`/`-Infinity` 字面量拒绝；小数解析为精确 `Decimal`（任意精度十进制），不存在"溢出为 inf"或"下溢为 0.0"的静默折叠；但十进制规模（最高有效位指数的绝对值）达到冻结协议上限 `MAX_DECIMAL_SCALE = 4300` 的字面量（如 `1e4300`、`1e9999`）一律拒绝，防止天文指数在 canonical 化时放大成巨型字符串；数字位严格限定 ASCII `0-9`（RFC 8259 §6）——整数尾部、小数部分、指数部分出现 Unicode 十进制数字（Arabic-Indic、full-width 等，如 `1٢`、`0.١`、`1e２`）一律以 `invalid number literal` 拒绝，绝不允许非法文本与合法文本（如 `12`）解析为同值同哈希；字符串内容不受此限，Unicode 数字在字符串中合法；
4. 含孤立 surrogate 的字符串和 object 键拒绝（它们无法进入 canonical UTF-8）；
5. 顶层必须是 object；
6. 嵌套深度预算为冻结协议常量 `MAX_WALK_DEPTH = 500`：解析由自研迭代下降解析器完成（显式容器栈，解析期即拒绝超预算容器），解析后检查与 canonical 输入域检查由共享迭代 walker（`_walk.py`）执行；整条路径不读取、不修改进程级 recursion limit，与 stdlib `json` 的 scanner 实现无关——同一预算内记录在 recursion limit 100/300/2000 及双线程受控交叠下结论一致（子进程回归验证）；超限以 `StrictJsonError` 失败，不泄漏裸 `RecursionError`；
7. 超过冻结协议位数上限 `MAX_INT_DIGITS = 4300` 的整数字面量以 `StrictJsonError` 失败，不泄漏裸 `ValueError`；整数解析经 `Decimal` 转换，上限与运行时 `PYTHONINTMAXSTRDIGITS` 配置无关——同一记录在 cap=0 或更小非零值的机器上得到相同结论。

## 5. Canonical 形式与哈希

**输入域限制**：`canonical_bytes` / `canonical_sha256` 只接受严格 JSON 数据模型——`None`、`bool`、`int`、有限 `Decimal`、有限 `float`（经 `Decimal(repr(...))` 规范化）、`str`（无孤立 surrogate）、`list`、键为 `str` 的 `dict`。其他一切（非字符串 object 键、tuple、set、bytes 等）以 `StrictJsonError` 拒绝，绝不在哈希前静默强制转换；这保证两个不同的已接受输入永远不会折叠为相同的 canonical 字节（例如 `{1: "x"}` 不会被折叠成 `{"1": "x"}`，`(1, 2)` 不会被折叠成 `[1, 2]`）。

Canonical 形式（v1）：

- UTF-8 字节，无 BOM，无结尾换行；
- object 键按码位排序；
- 无多余空白（separators 为 `,` 与 `:`）；
- 非 ASCII 以 UTF-8 原样输出，不使用 `\uXXXX` 转义；
- 非有限数与孤立 surrogate 拒绝序列化；
- 数字按精确数学值序列化：整数值输出整数字面量（`1.0` → `1`、`1E+2` → `100`、`-0.0` → `0`），否则输出去掉尾随零的 plain 十进制（`0.10` → `0.1`、`1E-7` → `0.0000001`）；数学值相等的数字必然产生相同字节，数学值不同的数字必然产生不同字节。

实现性质：序列化器是迭代式的（显式栈 + 结构哨兵），输入域检查与解析后检查共享 `_walk.py` 的同一迭代 walker，深度预算 `MAX_WALK_DEPTH` 是数据属性而非解释器栈函数；canonical 公共入口保留最终 `RecursionError → StrictJsonError` 兜底，深但合法的输入不会泄漏裸 `RecursionError`；整数输出经 `Decimal` 格式化（`format(Decimal(value), "f")`），不经过运行时 `int↔str` 转换上限，因此序列化结果不随 `PYTHONINTMAXSTRDIGITS` 变化。canonical 入口的输入域检查与解析层共享 `_limits.py` 的同一组冻结常量。

`Record` 的 `canonical_bytes` 与 `sha256` 在加载时一次性冻结（见 §2 不变量）。

确定性边界：数字格式按上述精确十进制规范化定义；跨语言 canonical 互操作（其他运行时的十进制实现差异）是已知开放点，留给后续 schema 版本，不属于本合同。

## 6. Safe relative path

存储的 locator 只接受 POSIX 形式；校验不做任何归一化，被接受的值本身就是 canonical 形式，因此同一路径的两种写法不会都合法却哈希不同。

拒绝：反斜杠分隔符（连带消灭 UNC `\\server\share`）、POSIX 根路径（`/x`）、盘符绝对路径（`C:/x`）、盘符相对路径（`C:x`）、`..` 与 `.` 组件、空组件（`a//b`）、组件首尾空白或尾随点、Windows 保留设备名（`CON`、`PRN`、`AUX`、`NUL`、`COM1`–`COM9`、`LPT1`–`LPT9`，含带扩展名形式）、Windows 禁用字符（`<>:"|?*`）、控制字符（`0x00`–`0x1F`、`0x7F`）、路径首尾空白。

接受：干净的 POSIX 相对路径，如 `artifacts/run-001/out.json`。

## 7. Schema 子集与注册

- schema 是数据而不是代码：`schemas/core/*.schema.json`；
- 支持的关键字：`type / properties / required / additionalProperties / items / enum / const / minItems / maxItems / minLength / maxLength / pattern / x-safe-relative-path / x-rfc3339-datetime / x-at-least-one-of / x-conditional-min-items`（外加 `$schema / $id / title / description` 元数据）；出现其他关键字即 `SchemaDefinitionError`，防止“声明了却从未执行”的约束；
- 注册时对每个关键字的值类型、非负范围、组合约束做完整元校验并失败关闭：`additionalProperties` 必须是布尔；`x-safe-relative-path` / `x-rfc3339-datetime` 必须是 `true`；`items` 必须是 schema 对象；`properties`/`required`/`additionalProperties`/`x-at-least-one-of`/`x-conditional-min-items` 只许配 `type: object`，`items`/`minItems`/`maxItems` 只许配 `type: array`，`minLength`/`maxLength`/`pattern`/两个布尔 `x-*` 标记只许配 `type: string`；边界关键字（`minLength`/`maxLength`/`minItems`/`maxItems` 与规则的 `min_items`）按 Draft 2020-12 `integer` 语义接受任何零小数 number——`1.0` 合法并在注册时归一化为 `int`，`1.5`、负数、boolean 失败关闭；`min*` 不得大于 `max*`；`x-at-least-one-of` 引用的属性必须已声明；
- `x-conditional-min-items` 的规则结构同样在注册时完整校验：每条规则必须恰好含 `when_property / when_equals / then_property / min_items` 四键；`when_property` 与 `then_property` 必须在该 object 的 `properties` 中已声明，且 `then_property` 必须声明为 `type: array`；`when_equals` 是非空列表；`min_items` 是正整数；
- `const` / `enum` / `x-conditional-min-items` 的 `when_equals` 按 Draft 2020-12 递归 JSON 等价比较，数值比较使用与解析层相同的精确十进制模型：boolean 与 number 严格分离（`true ≠ 1`），数字按精确十进制值等价（`1 ≡ 1.0 ≡ 1e0`，`10**24 ≡ 1e24`），数组逐元素、对象逐键递归。因此数值判别器上的条件门不会因为 `1` 与 `1.0`、或 `10**24` 与 `1e24` 的表示差异而漏触发；
- `type: integer` 按 Draft 2020-12 匹配所有小数部分为零的 number（`1`、`1.0`、`1e2`、`-0.0` 通过；`1.5`、`true`、`"1"` 拒绝）；
- `pattern` 保持原生 JSON Schema Draft 2020-12 语义：非锚定的 `re.search`，**不是**全串匹配。需要精确长度/全串约束的字段以 `pattern` 与 `minLength`/`maxLength` 组合表达（如 sha256 字段用 `minLength = maxLength = 64`）；`$` 锚点自身会在结尾换行前匹配，不单独承担长度合同；
- `x-rfc3339-datetime: true` 是**自包含**约束：自身完成 RFC 3339 完整形状（日期、`T`、带秒的时间、显式 `Z`/offset）与真实日历/时钟/UTC offset 语义校验，不依赖额外的 `pattern`。纯日期（`2026-08-14`）、空格分隔、不可能值（`2026-99-99T99:99:99+99:99`、`02-30`）、闰秒（`23:59:60`）、`+24:00` 一律拒绝；
- 注册完整性：文件名必须等于 `$id` 的 `research-x-v1.schema.json` 形式，`properties.schema.const` 必须等于 `$id`，重复 `$id` 拒绝；
- 默认 schema 根按仓库布局解析为 `<repo>/schemas/core`；嵌入其他环境时必须显式传 `schema_root`。本阶段无打包/安装步骤，pip 安装形态下的 schema 分发是已知延期项。

## 8. 发布合同（append-only）

`publish_record(source, *, root, schema_root=None)` 是记录进入 store 的唯一途径。冻结行为（全部 fail-closed）：

1. 新记录**原子创建**：先在 `<root>/.tmp/` 完整写入临时文件并 fsync，再以同卷硬链接提交到最终路径——已存在字节永不被覆盖，中断不会留下可见的半记录；
2. 同一逻辑 id、同一 hash 的重试只返回 `already_present=True`，**磁盘零变化**（含 manifest），exact replay 不产生任何写入；
3. 同一逻辑 id、不同 hash 抛 `PublicationError`；修订只能使用新 id 并在记录内以 `supersedes` 指向前驱（当前仅 `research-claim/v1` 声明该字段）；
4. schema family 无已知身份字段（`_ID_FIELDS` 之外的 family）抛 `PublicationError`，不得发布；
5. 发布前在 root 锁内对既有 store 做**完整对账**（与验证同一套 reconcile）：任何完整性发现——manifest 不可解析/非 canonical 字节/条目篡改、条目指向的记录缺失或字节不符、records/ 存在而 manifest 缺失、未登记的额外记录、重复逻辑 id、records/ 树内异物或 reparse point、保留节点类型异常——均抛 `StoreIntegrityError`，且**尚未写入任何字节**。唯一例外：findings 集合**严格等于**待发布记录自身的 `extra_record` 一条（上次崩溃留下的同内容孤儿）时，按 §9 收养路径自愈、不重写字节；manifest 确定性检查与其他 findings 相互独立，任何篡改都不得借孤儿例外掩盖；
6. 发布只执行单记录身份不变量，不做图校验——跨记录一致性是 `verify_record_graph` 的职责（允许以任意顺序发布相互引用的记录）。

`PublicationReceipt` 绑定：`schema`、`id`、`sha256`、store 相对 `path`、`already_present`、发布后 manifest 的 `manifest_sha256`。

并发边界：同一 store root 的发布与验证在进程内按锁串行化；跨进程并发发布不在本批承诺内。两个公共操作在入口**只捕获一次**进程 cwd 快照（`cwd_snapshot()`），store root 与非空 `schema_root` 由**同一快照**经纯词法拼接钉死（`absolutize_lexical`，绝不 resolve；Windows drive-relative 形式 `C:x` 无法由单快照无歧义钉死，fail-closed——publish 抛 `StoreIntegrityError`、verify 降级为 `store_unreadable` violation），且钉死发生在 `load_record` 及任何可回调工作之前；此后 preflight、锁键、对账、schema registry 查找与全部 I/O 均使用钉死值，不再读取进程 cwd——调用中途的进程内 cwd 变更（另一线程 `os.chdir`）既无法使被检查对象与被写入/验证对象分离，也无法把记录校验重定向到另一套 schema registry，更无法利用两次钉死之间的窗口把 root 与 schema_root 绑定到不同基准目录；外部进程在检查后替换祖先组件的竞态不在本批承诺内（`_store.py` 模块 docstring 已声明）。

## 9. 存储布局与原子性

```text
<root>/
    manifest.json     # 派生索引；canonical 字节；原子替换
    records/
        research-task/v1/<sha256>.json
        research-claim/v1/<sha256>.json
        research-evidence/v1/<sha256>.json
    .tmp/             # 写入暂存区；不属于被验证表面
```

- **内容寻址**：文件名是记录的 canonical SHA-256，不是逻辑 id。schema 允许任意非空白 id（可含 `/`、Windows 设备名、仅大小写不同的变体），以 id 作文件名会把路径逃逸与文件系统别名风险引入存储层；
- 磁盘上的记录字节恒等于 canonical 字节（发布时写入的就是 `record.canonical_bytes`），任何重格式化都会被 `record_not_canonical` 检出；
- **reparse point 全表面拒绝**：store root 本身**及其每个现存词法祖先组件**（相对 root 先对单一入口 cwd 快照做纯词法绝对化——绝不 resolve——因此 cwd 自身位于 junction 之下同样检出）、`manifest.json`、`records/`、`.tmp/` 及 records 树内每个节点都不得是 symlink/junction/其他 reparse point；词法 root 即 containment 边界，绝不跟随 resolved target（ADR-0002 决策 7）。检测基于 lstat：Windows 上检查 `FILE_ATTRIBUTE_REPARSE_POINT`，因此覆盖**全部** reparse tag（不只是 symlink 和 junction），损坏或悬空的目标同样检出；stat 因"不存在"以外的原因失败时节点视为**不可判定**并 fail-closed（verify 报 `store_unreadable`、publish 抛 `StoreIntegrityError`）——"无法判定"绝不当作"安全"。磁盘遍历以 `os.scandir` 迭代实现、发现 reparse 即报 violation 且不跟随，写入前逐父组件检查——store 不会向 root 之外写入，也不会为 root 之外的字节作证（Windows junction 无需管理员权限即可创建，必须活在合同内）；
- manifest 经"临时文件 + fsync + `os.replace`"原子替换；它是派生索引，可整体重建，覆盖式替换不违反 append-only（事实源是记录本身）；
- 崩溃窗口：记录已链接、manifest 未更新 → 验证报 `extra_record`，重新发布同一条记录按"同内容收养"路径自愈（不重写字节）；首次发布即崩溃（records/ 存在、manifest 不存在）→ 验证报 `manifest_missing`，发布拒绝写入，需人工清理残留；暂存写入/fsync 失败（磁盘满、配额）→ 临时文件本身已清理，但可能留下 `records/` 空目录树而无 manifest，同样落入上述 `manifest_missing` 语义，需人工清理空目录；
- `.tmp/` 中的孤儿暂存文件不属于被验证表面，不影响验证结论；暂存清理是**尽力而为**——清理失败（如 Windows 反病毒瞬时锁文件）被吞掉，既不泄漏裸 OS 异常也不掩盖已包装的主错误，残留归入本句语义。

## 10. Manifest 与全图验证

`verify_record_graph(root, *, schema_root=None) -> GraphVerificationReport` 永不因损坏抛异常；一切发现都是 `GraphViolation`（`kind` + `detail`），`report.ok` 仅在零违规时为 True。

**完整性阶段**（manifest 与磁盘逐字节对账）：

| violation kind | 含义 |
|---|---|
| `store_root_missing` | root 不是已存在的目录 |
| `manifest_missing` | records/ 存在但 manifest.json 缺失 |
| `manifest_malformed` | manifest 非严格 JSON、结构/键集合/`manifest` 常量错误、条目字段非法、条目 path 与 family+sha256 推导不符、重复 `(family, id)` 或重复 path |
| `missing_record` | manifest 条目指向的文件不存在 |
| `extra_record` | 磁盘上形状合法的记录文件不在 manifest 中 |
| `foreign_object` | records/ 树内形状不合法的对象（非 `<sha256>.json`、目录层级错误） |
| `record_invalid` | 记录文件无法通过严格解析/schema 校验 |
| `record_identity_mismatch` | 文件目录 family、文件名 hash 或记录身份字段与声明不符 |
| `record_not_canonical` | 记录字节与 canonical 形式不符 |
| `duplicate_record` | 同一 `(family, id)` 出现在多个文件中 |
| `manifest_not_deterministic` | manifest 可干净解析时独立于其他 finding 执行（可与其他完整性 finding 同时报出）：存储的 manifest 字节与其确定性 canonical 重建不一致 |
| `reparse_point` | 存储表面（store root 的任一现存词法组件、manifest.json、records/、.tmp/ 或 records 树内任意节点）出现 symlink/junction/任何其他 reparse tag；检测基于 lstat 与 `FILE_ATTRIBUTE_REPARSE_POINT`，遍历不跟随，写入不穿越 |
| `unexpected_node_type` | 保留节点类型异常（如 manifest.json 是目录、records/ 是普通文件） |
| `store_unreadable` | records 树内目录无法列举、manifest 或记录文件无法读取、节点 stat 因"不存在"以外的原因失败而不可判定（权限或 I/O 错误） |

**图阶段**（仅对干净识别的记录运行）：

| violation kind | 含义 |
|---|---|
| `duplicate_id` | 同一逻辑 id 出现在两个及以上 family——逻辑 id 必须全局唯一，碰撞永远不承载合法语义（区别于 fork：fork 是合法分歧，只作信息位）；每个碰撞 id 报一条，detail 按序列出全部涉及 family。同 family 同 id 出现在多个文件属完整性阶段的 `duplicate_record` |
| `dangling_reference` | 引用指向任何 family 中都不存在的 id |
| `cross_type_reference` | 引用指向存在但类型错误的 id（如 `supporting_evidence` 指向 task id、`supersedes` 指向 evidence id） |
| `self_reference` | claim 的 `supersedes` 指向自身 |
| `pin_mismatch` | claim 钉住的 evidence SHA-256 与存储记录实际 hash 不符 |
| `one_way_link` | claim 与 evidence 之间只有单向引用 |
| `lineage_cycle` | claim 的 `supersedes` 边构成环；supersedes 是函数图，环互不相交，逐环各报一条、枚举全部 |

**fork 不判错**：多条 claim supersedes 同一前驱只记入 `report.forks` 信息位；Core 不提供"自动选择最新版本"的语义。Task 与 Evidence 在 v1 没有 `supersedes` 字段，其"修订"语义是新 id 新记录。

`report` 另含 `records_total`、`families`（各 family 计数）、`manifest_sha256`（磁盘 manifest 实际字节的哈希；manifest 缺失或不可读时为 `None`），全部可经 `to_dict()` 序列化为严格 JSON。

## 11. 失败关闭清单

以下输入必须失败且不得降级为警告：duplicate key（任意层级）、非有限数、数字任何位置的 Unicode 十进制数字（如 `1٢`、`0.١`、`1e２`；字符串内容除外）、孤立 surrogate、超冻结协议位数整数、十进制规模超限字面量（如 `1e9999`）、进入 canonical 入口的非 JSON 数据模型值（非字符串 object 键、tuple、set、bytes）、路径逃逸与路径别名（盘符/UNC/根/`..`/尾随点/设备名/控制字符/反斜杠）、未知 schema id、缺失必填字段、额外字段、枚举越界、哈希尾随字符（长度合同拒绝）、语义或形状非法时间戳（含纯日期）、纯空白语义字符串（`title`/`statement`/`scope`/`applicability`/`evidence_level` 等）、无绑定的 evidence 输入、`proposed`/`inconclusive` 之外的 disposition（含 `supported`/`refuted`/`superseded`/`withdrawn`）或非 `draft` 成熟度却没有证据引用的 Claim、schema 文件使用未支持关键字或非法关键字值。

发布与图校验路径同样全部 fail-closed：同一逻辑 id 以不同内容重复发布（`PublicationError`）、无身份字段的 family 发布（`PublicationError`）、已损坏或被篡改 store 上的任何发布（`StoreIntegrityError`，未写入字节）、写入路径全部 OS 失败（存储目录创建、暂存文件打开/写入/fsync、记录硬链接、manifest 替换；`StoreIntegrityError`，无部分提交，绝不泄漏裸 OS 异常）、记录被改写/删除/额外插入/重复 id/非 canonical 字节、manifest 缺失/畸形/非确定性/条目篡改、records/ 树内异物或 reparse point、保留节点类型异常、records 树不可读、悬空引用、跨类型引用、跨 family 重复逻辑 id（`duplicate_id`）、自引用、pin 不符、单向链接、lineage cycle（均为验证 violation，`ok=False`）。

## 12. 测试与 fixtures

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONDONTWRITEBYTECODE = "1"
python -B -m unittest discover -s tests -p "test_*.py" -v
```

- `tests/unit/`：strict JSON（含精确十进制数值模型与冻结协议上限、数字三位置 Unicode 数字拒绝——整数尾部/小数部分/指数部分 × Arabic-Indic/full-width、字符串内 Unicode 数字合法）、safe path、canonical/hash（含 Decimal 规范化与 float 一致性、迭代式序列化器与公共接口深度边界——498 层合法记录走完整 `load_record` 管线、600 层拒绝、`10**5000` 整数拒绝）、record facade（含迭代深拷贝的深层变异隔离）、schema 定义 mutation（52 个变异全部要求 `SchemaDefinitionError`）、schema 边界关键字数学整数语义（`1.0` 接受且归一化后真实生效、`1.5`/负数/boolean 拒绝，覆盖 `minLength`/`maxLength`/`minItems`/`maxItems`/`min_items`）、JSON 等价语义（const/enum/条件门的 bool-number 分离与精确十进制等价，含 `10**24`/`1e24` 大数回归）、冻结数值协议子进程回归（`FrozenNumericProtocolTest` 以 `PYTHONINTMAXSTRDIGITS=0/640` 启动子进程运行 `tests/unit/_frozen_protocol_probe.py`——该文件是四模式探针脚本、不匹配 `test_*.py` 故不被 discover 收集——验证 cap=0 时 `0.1`/`1e999`/700 位整数仍按冻结常量精确接受，且含大指数小数的记录在默认解释器与 cap=0 子进程中产生相同 SHA-256）、确定性根因回归（`NoGlobalRecursionStateTest` 以 `noglobal` 模式在内核导入前把 `sys.getrecursionlimit`/`sys.setrecursionlimit` 替换为调用即失败探针、真实限制钉在 100——任何对进程级 recursion limit 的读/写都确定性失败；solo 与双线程并发判定全部通过且零调用、零漂移）、并发压力子进程回归（`RecursionLimitStressTest` 以 `stress 300`/`stress 2000` 调用探针：400 层预算内输入在两条公共路径单独与双线程 barrier 夹逼下接受且哈希一致，600 层始终 `StrictJsonError`——barrier 不能确定性强制解析区重叠，此项仅为 stress 证据）、stdlib scanner parity 回归（`StdlibScannerParityTest` 以 `parity` 模式对 valid/invalid 语料在 C scanner 与纯 Python scanner 下做 differential 比对，语料含数字三位置 Unicode 数字拒绝案例：内核解析器不调用 stdlib json，scanner 选择对判定无影响）；
- `tests/contract/test_core_schemas_contract.py`：fixture 树与清单双向精确相等（目录级发现，清单外新 family/version 或游离文件即失败）、valid/invalid 行为逐项断言预期错误类别与原因、golden hash、schema 完整性与领域中性扫描；
- `tests/unit/test_publication.py`：发布路径——内容寻址创建、receipt 绑定 manifest hash、exact replay 磁盘零变化（全树快照对比，含 `.tmp`）、同 id 异内容 `PublicationError` 且磁盘不变、新 id + `supersedes` 修订流程、中断发布两个崩溃窗口（记录已链接 manifest 未更新 → `extra_record` 检出并按同内容收养自愈、字节不重写；首次发布即崩溃 → `manifest_missing` + 发布拒绝写入）、`.tmp` 残留对验证不可见、manifest 篡改（重格式化/垃圾字节）拒绝后续发布、`already_present` 先核实磁盘字节再返回、同记录与不同记录的并发发布串行化、无身份字段 family fail-closed、发布守卫（`PublishGuardTest`：四种脏 store 变体——既有记录删除/损坏、manifest 条目篡改、未登记记录——下一条发布均抛 `StoreIntegrityError` 且全树快照零变化、待发布记录自身的同内容崩溃孤儿收养、records 根与 family version 两级 junction 拒绝且 root 外目录零写入（仅 Windows，`mklink /J`）、manifest.json 为目录与 records/ 为普通文件两类保留节点类型异常——verify 报 `unexpected_node_type`、publish 抛 `StoreIntegrityError` 而非裸 OS 异常；孤儿例外不掩盖组合篡改——目标 orphan 与非 canonical manifest 或条目乱序 manifest 同时存在时发布阻断且全树快照零变化；store root 本身为 junction 同样拒绝，且 root 位于 junction 之下的嵌套路径（nested-store 尚不存在/已存在于 junction target 两种形态）也拒绝、junction target 零写入——词法 root 即 containment 边界，其全部现存祖先组件不得含 reparse point；相对 root 在 junction 内的 cwd 下同样拒绝（词法绝对化后逐组件检查）；root 在操作入口钉死为词法绝对路径、preflight/锁键/对账/写盘全程使用钉死值，进程内 cwd 中途变更无法分离检查与写入对象（确定性回归：mock reconcile 调用中 chdir，未钉死变体稳定失败为 `store_root_missing`）；钉死发生在 `load_record` 之前的入口首步（回归：mock load_record 内 chdir，晚钉死变体把 store 写进 dir-b 被杀灭），相对 `schema_root` 同样钉死（回归：mock 逐条 load 内 chdir 到弱 schema 目录，未钉死变体把严格 `record_invalid` 翻转成假 `ok=True` 被杀灭）；root 与 `schema_root` 由**同一次**入口 cwd 快照钉死（确定性回归：mock `os.path.abspath` 仅在转换 schema 参数时 chdir 到弱 schema 目录——修复后实现不调用 `os.path.abspath`，hook 惰性，严格 schema 仍拒绝发布且 dir-a/dir-b 零写入；恢复逐参数 `abspath` 的 mutation 形态下 hook 在第二次转换点火、弱 schema 放行，测试确定性失败，已实测杀灭）；进程内锁键为钉死路径的纯词法 normcase，绝不 resolve、不再读取进程 cwd；写入路径 I/O 失败不泄漏裸 OS 异常（root 祖先为普通文件——真实文件系统、跨平台均 `StoreIntegrityError`；目录创建被拒与暂存 `mkstemp` 被拒——mock 注入，三者均断言零写入/无部分提交；暂存写入/fsync 失败（磁盘满）与记录硬链接失败——mock 注入，包装为 `StoreIntegrityError` 且 `.tmp` 无残留、无 record/manifest；manifest 替换被拒——mock 注入，包装且 manifest 字节不变、已链接记录按崩溃窗口成为 `extra_record` 孤儿；暂存清理为尽力而为——清理 `unlink` 失败（反病毒瞬时锁，mock 注入）既不掩盖已包装的主错误（仍抛写失败的 `StoreIntegrityError`）也不破坏正常提交（残留 `.tmp` 孤儿对验证不可见））；
- `tests/unit/test_graph_verification.py`：全图验证——空 store/缺失 root、三类合法链接（含 pin 与无 pin）、三类悬空引用、三类跨类型引用、自引用、pin 不符、双向单向链接、2/3 节点 lineage cycle、合法链、fork 仅信息位，以及篡改类：记录改写/损坏/删除/额外插入/非 canonical 字节、manifest 条目删除/hash 篡改/重复条目/删除、异物、误放文件、跨文件重复逻辑 id、manifest 非确定性重写（`manifest_not_deterministic` 且仅此一条）、两个互不相交 lineage cycle 各报一条全枚举、records 树不可读（`store_unreadable`，mock 注入列举失败，发布同被阻断）、manifest 与记录文件不可读（`store_unreadable`，mock 注入读取失败，verify 与 publish 双路径均不泄漏裸 OS 异常）、非 symlink/junction 的其他 reparse tag（白盒：对保留节点注入 `FILE_ATTRIBUTE_REPARSE_POINT`，verify 报 `reparse_point`、publish 阻断）、保留节点与 root 组件 lstat 失败 fail-closed（`store_unreadable`/`StoreIntegrityError`，"不可判定"绝不当"安全"）、store 路径 resolve 失败时 verify 仍返回 violation 而不泄漏异常（preflight 纯词法且先于加锁）；跨 family 重复逻辑 id（两 family 碰撞单条 `duplicate_id` 且为唯一 violation、三 family 全互链形态仍仅一条且 detail 列出全部 family、id 全局唯一时零误报）；manifest 条目字段非字符串（`manifest_malformed`，detail 含 "must be a string"，且阻断下一条发布）；
- `tests/fixtures/core/<family>/<version>/{valid,invalid}/`：合成、脱敏、明确标记的样例（当前 6 valid + 47 invalid，共 53 个，与 Phase 1A 完全相同）。invalid 文件按失败类别命名，新增或删除文件都会使合同测试失败。

当前全量测试数：**220**（PATH Python 3.14.5 与 `.venv` 双运行时均通过），其中 136 个为 Phase 1A 既有测试，零修改、零漂移。violation 合同共 **21 种**（14 完整性 + 7 图），§10 两表逐项对应测试断言。

## 13. 证据边界

本阶段的全部测试与 fixtures 只构成 engineering 级证据：它们证明内核按合同拒绝与接受输入、发布路径按 append-only 合同落盘、验证按清单检出篡改与图违规，不证明任何数据、实证、策略或生产结论。三个 schema 不包含任何领域字段；`proof`、`factor`、`model architecture` 等领域词汇由合同测试主动扫描拒绝。发布目标仅限调用方显式传入的本地 repository root；跨项目导出、隐私分级与 redaction 属后续批次。
