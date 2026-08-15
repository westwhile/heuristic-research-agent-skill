# Core Interface（Phase 1A）

- 版本：Phase 1A（`feat/core-records-v1`）
- 覆盖 schema：`research-task/v1`、`research-claim/v1`、`research-evidence/v1`
- 代码位置：`src/research_evolution/core/`；schema 文本：`schemas/core/`；fixtures：`tests/fixtures/core/`

## 1. 范围与非目标

本阶段只交付通用记录内核的最小可验证子集：

- 严格 JSON 解析（UTF-8、duplicate-key 拒绝、非有限数拒绝、孤立 surrogate 拒绝）；
- 按记录 `schema` 字段分派并校验三个 v1 schema；
- canonical serialization 与确定性 SHA-256；
- safe relative path 校验。

明确不包含（属于后续批次，不在本接口承诺内）：

- `Run`、`FailureObservation`、`FailureAnalysis`、`ResearchCasePackage` 等其余 schema；
- create-new/append-only 发布、`supersedes` lineage 图校验、manifest 生成；
- 隐私分级与 redaction 执行器；
- CLI、Adapter、数据库、安装与部署。

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
)
```

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
- `claim_ids` 与 Claim 的 `supporting_evidence` 之间的一致性属于图校验，不在本阶段。

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

## 8. 失败关闭清单

以下输入必须失败且不得降级为警告：duplicate key（任意层级）、非有限数、数字任何位置的 Unicode 十进制数字（如 `1٢`、`0.١`、`1e２`；字符串内容除外）、孤立 surrogate、超冻结协议位数整数、十进制规模超限字面量（如 `1e9999`）、进入 canonical 入口的非 JSON 数据模型值（非字符串 object 键、tuple、set、bytes）、路径逃逸与路径别名（盘符/UNC/根/`..`/尾随点/设备名/控制字符/反斜杠）、未知 schema id、缺失必填字段、额外字段、枚举越界、哈希尾随字符（长度合同拒绝）、语义或形状非法时间戳（含纯日期）、纯空白语义字符串（`title`/`statement`/`scope`/`applicability`/`evidence_level` 等）、无绑定的 evidence 输入、`proposed`/`inconclusive` 之外的 disposition（含 `supported`/`refuted`/`superseded`/`withdrawn`）或非 `draft` 成熟度却没有证据引用的 Claim、schema 文件使用未支持关键字或非法关键字值。

## 9. 测试与 fixtures

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONDONTWRITEBYTECODE = "1"
python -B -m unittest discover -s tests -p "test_*.py" -v
```

- `tests/unit/`：strict JSON（含精确十进制数值模型与冻结协议上限、数字三位置 Unicode 数字拒绝——整数尾部/小数部分/指数部分 × Arabic-Indic/full-width、字符串内 Unicode 数字合法）、safe path、canonical/hash（含 Decimal 规范化与 float 一致性、迭代式序列化器与公共接口深度边界——498 层合法记录走完整 `load_record` 管线、600 层拒绝、`10**5000` 整数拒绝）、record facade（含迭代深拷贝的深层变异隔离）、schema 定义 mutation（52 个变异全部要求 `SchemaDefinitionError`）、schema 边界关键字数学整数语义（`1.0` 接受且归一化后真实生效、`1.5`/负数/boolean 拒绝，覆盖 `minLength`/`maxLength`/`minItems`/`maxItems`/`min_items`）、JSON 等价语义（const/enum/条件门的 bool-number 分离与精确十进制等价，含 `10**24`/`1e24` 大数回归）、冻结数值协议子进程回归（`FrozenNumericProtocolTest` 以 `PYTHONINTMAXSTRDIGITS=0/640` 启动子进程运行 `tests/unit/_frozen_protocol_probe.py`——该文件是四模式探针脚本、不匹配 `test_*.py` 故不被 discover 收集——验证 cap=0 时 `0.1`/`1e999`/700 位整数仍按冻结常量精确接受，且含大指数小数的记录在默认解释器与 cap=0 子进程中产生相同 SHA-256）、确定性根因回归（`NoGlobalRecursionStateTest` 以 `noglobal` 模式在内核导入前把 `sys.getrecursionlimit`/`sys.setrecursionlimit` 替换为调用即失败探针、真实限制钉在 100——任何对进程级 recursion limit 的读/写都确定性失败；solo 与双线程并发判定全部通过且零调用、零漂移）、并发压力子进程回归（`RecursionLimitStressTest` 以 `stress 300`/`stress 2000` 调用探针：400 层预算内输入在两条公共路径单独与双线程 barrier 夹逼下接受且哈希一致，600 层始终 `StrictJsonError`——barrier 不能确定性强制解析区重叠，此项仅为 stress 证据）、stdlib scanner parity 回归（`StdlibScannerParityTest` 以 `parity` 模式对 valid/invalid 语料在 C scanner 与纯 Python scanner 下做 differential 比对，语料含数字三位置 Unicode 数字拒绝案例：内核解析器不调用 stdlib json，scanner 选择对判定无影响）；
- `tests/contract/test_core_schemas_contract.py`：fixture 树与清单双向精确相等（目录级发现，清单外新 family/version 或游离文件即失败）、valid/invalid 行为逐项断言预期错误类别与原因、golden hash、schema 完整性与领域中性扫描；
- `tests/fixtures/core/<family>/<version>/{valid,invalid}/`：合成、脱敏、明确标记的样例（当前 6 valid + 47 invalid，共 53 个）。invalid 文件按失败类别命名，新增或删除文件都会使合同测试失败。

## 10. 证据边界

本阶段的全部测试与 fixtures 只构成 engineering 级证据：它们证明内核按合同拒绝与接受输入，不证明任何数据、实证、策略或生产结论。三个 schema 不包含任何领域字段；`proof`、`factor`、`model architecture` 等领域词汇由合同测试主动扫描拒绝。
