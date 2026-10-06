# Data readers and local fallback / 数据读取工具与本地补充方案

Development note, 2026-10-05. The local fallback below is implemented in the
Desktop source and has passed the two live reader tests below. This is not a claim about an already
published Windows release or a completed live new-site test.

开发说明，2026-10-05。下述本地补充功能已写入 Desktop 源码，并通过以下两个真实读取测试；不代表已发布的 Windows 版本具备此功能，也不代表真实新站点模拟已完成。

## English

### What the Agent should do

Prefer an applicable data KI or reader supplied with the dataset, or one already
installed in the KI library. Check its supported format, variables, version and
output contract before using it. A similarly named reader is not necessarily
compatible with the files that arrived.

When no suitable reader exists, the Agent may prepare a small project-local
reader or converter through the Desktop fallback added in this development
change. It must inspect the actual schema and retain its source code, input
references, transformation choices and validation results in the project. The
reader belongs in the approved plan; preparing code does not itself authorize a
download, model run or calibration. Existing KI execution checks are not relaxed
to admit arbitrary scripts.

The reader should:

1. Preserve the raw files and their hashes. Write extracted or converted data to
   separate project files, and record the dataset ID/version where available.
2. Read the real format: stream large CSV files with an explicit encoding, or
   open SQLite read-only and inspect tables and columns before querying them.
   A truncated text preview helps identify a header; it cannot establish full
   coverage, record counts or data quality.
3. Check station identifiers and coordinates, dates and calendar, time step and
   time zone, variable meaning and units, sensor depth where relevant, missing
   values, duplicates and available quality flags. Preserve unknowns explicitly.
4. Document filtering, unit conversion, resampling and rejected rows. Validate
   the resulting files against the downstream KI's input requirements.

Missing weather, soil parameters, initial states or quality flags remain missing.
The Agent must obtain another documented source or resolve the scientific choice;
it must not invent values to make a model run. A successful download or reader
does not establish that a new-site model has run or agrees with observations.

### Reusable readers included in the development library

The Desktop source also includes two first-party task-workflow packages under
`kiss/data_kis`: `HYDAT_Observations` and `Agrometeo_Quebec_Observations`. They are
data readers, separate from the 127 model KIs. Each includes a format contract,
bilingual instructions, a source-hash-pinned install manifest, a real import/help
preflight, and clearly synthetic regression fixtures. They use Python 3.11+
standard library only; admitted reader installation does not require the shared
scientific package set. Normal approved `check`/`prepare` tool execution records
the data KI identity and `model_executed: false`.

The final readers were also replayed independently against the complete acquired
archives: every exported HYDAT value and native quality symbol for 2018–2020
(1,096 records), and every exported Compton field for 2022 (8,760 records), matched
the raw source. All 80,941 other Compton records were accounted for as exclusions,
and all 13 input hashes matched the download placement audit. This is a standalone
reader verification, separate from the earlier live fallback tests; it is not a
new-site simulation or a claim that a published release already contains these KIs.
The server does not need companion-delivery support for an installed reader to
be used. These packages do not download or fabricate missing observations.

For a source checkout, run these commands from its `kiss` directory using the
Python environment that runs the CLI. Example Windows installation locations:

```powershell
python -m kiss_cli init HYDAT_Observations --workdir C:/GeoForge/data-readers/hydat_observations
python -m kiss_cli init Agrometeo_Quebec_Observations --workdir C:/GeoForge/data-readers/agrometeo_quebec_observations
python -m kiss_cli verify HYDAT_Observations --workdir C:/GeoForge/data-readers --json
python -m kiss_cli verify Agrometeo_Quebec_Observations --workdir C:/GeoForge/data-readers --json
```

Here `init --workdir` names one reader's workspace; `verify --workdir` names the
parent installation root containing the lowercase package folders. Omitting
`verify --workdir` uses the locations registered by `init` in the default index.
Verification checks the installed `ki/` source and workspace Python; it executes
imports and `--help`, not an observation extraction or scientific model. On
Windows, an installed tool is `<workspace>/ki/tools/read_observations.py` and its
interpreter is `<workspace>/venv/Scripts/python.exe` (POSIX: `venv/bin/python`).
Normal Agent extraction still belongs in an approved `check`/`prepare` step.

### Local fallback interface (source implementation)

This addition is available to **direct API providers, including DeepSeek**.
CLI agent adapters are unchanged and have no new reader-authoring/execution
surface from this change. A separate data KI is not required for the fallback.

| Tool | When and how it is used |
|---|---|
| `write_project_data_tool({ki, name, source, purpose})` | During `PLANNING` or `REPLAN_REQUIRED` only. `ki` explicitly names a selected KI; `purpose` is `reader`, `converter` or `check`. Writes Python source to `project_tools/<KI-slug-hash>/<name>.py`, checks syntax and returns its exact path and binding. Executes nothing. |
| `run_project_data_tool({ki, tool_path, plan_step_id, arguments?, cwd?, timeout_seconds?})` | During execution of an approved `check` or `prepare` step. Omitted invocation fields use the reviewed values; supplied differences are rejected. Reuses the approved source hash and signed execution-receipt flow. |

Use the returned absolute `tool` path in the plan step. Its `project_data_tool`
metadata contains exactly `version: 1`, `purpose`, `source_sha256`, `arguments`,
project-relative `cwd`, and `timeout_seconds` (1–600 seconds). Declare acquired
local inputs and the inspection report or converted outputs in that step. The
approval card shows the invocation settings, source hash and a source preview
(marked when truncated). Source or invocation changes require replan and review.

Reader code must keep its inputs unchanged and write fresh files under
`outputs/` or `artifacts/`. SQLite readers use a `file:` URI with `mode=ro`,
`uri=True` and `PRAGMA query_only=ON`. This runtime is for reviewed, trusted data
code, with guards against accidental file changes, network access and native
process execution; **it is not an OS security sandbox**. It does not authorize
model execution or calibration. The live DeepSeek tests extracted 1,096 HYDAT
daily records and 8,760 Compton hourly records. Independent comparison verified
every exported value against the raw files after draft corrections. This verifies
these two observation extractions, not a new-site model simulation or a generally
validated reusable reader. See the [test report](issues/CANADIAN-NEW-SITE-READINESS-2026-10-05.md).

### Actual examples from the Canadian tests

| Delivered data | Appropriate reader work | Remaining scientific requirements |
|---|---|---|
| HYDAT: one approximately 1.28 GB SQLite file | Inspect the database schema in read-only mode; select the requested station and period; expand the actual daily-flow fields, preserving missing values and flags. Verify discharge units before comparison. | CRHM still needs suitable meteorological forcing, basin configuration and an explicit comparison between its output and the observed discharge. |
| Agrometeo Québec: 12 yearly `soilTemp10cm_*.csv` files, 2012–2023, approximately 361 MB | Parse the five delivered columns: station, date, latitude, longitude and soil temperature in °C. Handle the observed encoding/header differences between files and audit each selected station's continuity. | These delivered files contain soil temperature, not the catalogue's broader advertised weather variables. They contain no explicit time-zone or QC columns. SHAW still needs weather, site/soil/vegetation parameters and initial conditions; model temperature must be matched to the observation depth and time convention. |

These are observations about the downloaded files. They do not claim a completed
CRHM–HYDAT or SHAW–Québec new-site simulation. Independent inspection found a
complete hourly Compton series for 2022, but the raw timestamps do not establish
UTC, and absence of a QC column is not evidence that all measurements passed QC.

### Current interfaces and proposed companion delivery

The local reader fallback is a Desktop development feature. **A server protocol
that supplies a companion data KI with each download is a separate proposal.**
The inspected deliveries did not include such a KI, and no deployed server
support for a companion-reader descriptor has been verified.

Current source extension points are:

| Area | Existing behavior | Addition needed for a server-provided companion |
|---|---|---|
| `kiss/kiss_cli/obs_access.py` | Catalogue and describe responses use explicit public-field allowlists; inventory metadata is copied through `STAMP_FIELDS`. None currently includes companion KI identity, version or entrypoint. | Define and explicitly retain an optional structured companion descriptor in the public metadata and approved inventory. Unknown server fields are currently dropped, so their absence in a Desktop result alone cannot prove server absence. |
| Dataset download | Served downloads verify their content hash; ZIP members are extracted with path checks. Manual placement is recorded through Desktop's acquisition flow. | Include the companion files and their hashes in the delivered package, then identify them explicitly. Downloading a Python file must not automatically make it an executable KI tool. |
| KI import and execution | `gui.py` validates imported KI packages; the catalogue discovers installed packages. `api.py` and `ki_tools_common/ki_tools_common/flow/tools.py` limit KI execution to admitted tools and the approved step. | Reuse package validation, tool admission, approval and execution evidence for an applicable companion, rather than silently executing downloaded code. |
| `kiss/kiss_cli/obs_prepare.py` | Requests read-only model-input preparation estimates. | This estimate interface is not a companion-reader delivery or execution interface. |

A minimal proposed descriptor would identify the companion package/reader and
version, its compatible data schema, an archive-relative manifest or approved
package identity, entrypoint and hashes. The selected reader and raw/derived
file hashes should be recorded together. Field names and the service contract
still need agreement with the server; they are not implemented API guarantees.
The existing `KISSPATH_DATA_KI` role is a compatibility path mapped to project
inputs, not a registry of data KIs supplied by the database.

## 简体中文

### Agent 应怎样处理

优先使用随数据提供或已安装在 KI 库中的适用数据 KI／读取工具。先核对它支持的格式、变量、版本和输出约定，不能仅凭名称相近就认为兼容。

如果没有适用工具，Agent 可以通过本次增加的 Desktop 本地补充功能，为当前项目编写小型读取器或转换器。必须先检查真实文件结构，并在项目内保存代码、输入来源、转换方法和验证结果。读取步骤应纳入批准的计划；准备代码本身不等于批准下载、模型运行或校准，也不会放宽已有 KI 的工具执行限制。

读取器应完成以下工作：

1. 保留原始文件及其哈希值。提取或转换结果另存，记录可获取的数据集 ID 和版本。
2. 按真实格式读取：大 CSV 分块或逐行处理，明确编码；SQLite 以只读方式打开，先查看表和字段。截断的文本预览只能帮助识别表头，不能证明完整覆盖、总记录数或数据质量。
3. 检查站点、坐标、日期与日历、时间步长和时区、变量含义与单位、必要的传感器深度、缺失值、重复记录和现有质量标记；未知信息要明确保留为未知。
4. 记录筛选、单位换算、重采样及剔除记录的方法，并按下游 KI 的输入要求验证结果。

缺少的气象、土壤参数、初始状态或质量标记仍然是缺项。Agent 应寻找有依据的其他来源，或明确需要确定的科学选择，不能为了让模型运行而编造数据。下载或读取成功不代表新站点模拟已经完成，更不代表通过了观测验证。

### 开发版库中包含的可复用数据 KI

Desktop 源码的 `kiss/data_kis` 中增加了 `HYDAT_Observations` 和
`Agrometeo_Quebec_Observations` 两个第一方数据读取包，与 127 个模型 KI 分开。
每个包包含格式约定、双语说明、绑定源码哈希的安装清单、真实导入／帮助预检和明确标注的
合成回归样例。运行只需 Python 3.11+ 标准库，已验证身份和源码的读取器无需安装整套共享
科学计算依赖。读取过程仍通过正常批准的 `check`／`prepare` 步骤执行，回执标明数据 KI
身份及 `model_executed: false`。

最终读取器另外使用完整已下载档案进行独立重放：HYDAT 2018–2020 年的 1,096 条输出
值及原始质量符号、Compton 2022 年的 8,760 条输出字段均逐条匹配原始数据；其余
80,941 条 Compton 记录明确归入时段外记录，13 个输入文件哈希均与下载放置审计一致。
这是独立读取器验证，与前述真实 Agent 本地补充测试分别记录，不代表新站点模拟完成，
也不代表已发布版本包含这些 KI。使用已安装读取器不依赖服务器实现配套交付；这些包不
下载或编造缺失观测。

源码使用者在仓库的 `kiss` 目录中，用运行 CLI 的 Python 执行以上四条命令即可安装和
验证两个读取器，示例 Windows 目录可替换。注意 `init --workdir` 指向单个读取器工作目录，
`verify --workdir` 指向包含小写包名目录的父安装目录；省略后者时使用 `init` 登记的默认
索引位置。验证检查实际安装在 `ki/` 下的源文件及工作区 Python，只运行导入和 `--help`，
不读取观测，也不运行模型。Windows 安装后的入口为 `<工作目录>/ki/tools/read_observations.py`，
解释器为 `<工作目录>/venv/Scripts/python.exe`；POSIX 为 `venv/bin/python`。Agent 正式提取数据
仍须使用批准的 `check`／`prepare` 步骤。

### 本地补充接口（源码实现）

本次功能面向 **DeepSeek 等直接 API 服务商**。CLI Agent 适配器没有变化，本次没有为其增加读取器编写或执行接口。本地补充方案不要求另装一个数据 KI。

- `write_project_data_tool({ki, name, source, purpose})`：仅在 `PLANNING` 或 `REPLAN_REQUIRED` 阶段使用。明确指定已选 KI；用途为 `reader`、`converter` 或 `check`。代码写入 `project_tools/<KI-slug-hash>/<name>.py`，检查语法并返回路径和绑定信息，尚不执行。
- `run_project_data_tool({ki, tool_path, plan_step_id, arguments?, cwd?, timeout_seconds?})`：仅执行已批准的 `check` 或 `prepare` 步骤。省略的运行参数使用已审阅值；与批准值不同的参数会被拒绝。执行沿用源代码哈希绑定和签名回执流程。

计划步骤使用返回的绝对 `tool` 路径，并包含 `project_data_tool` 元数据：`version: 1`、`purpose`、`source_sha256`、`arguments`、项目内相对工作目录 `cwd` 和 1–600 秒的 `timeout_seconds`。同时声明本地已获取输入和报告／转换输出。批准卡展示运行设置、代码哈希及代码预览，截断时明确提示。修改代码或运行参数需要重新规划并审阅。

输入保持不变，结果写到 `outputs/` 或 `artifacts/` 下的新文件。SQLite 使用带 `mode=ro` 的 `file:` URI、`uri=True` 和 `PRAGMA query_only=ON`。这些是针对可信、已审阅代码的误操作防护，包括文件修改、网络和原生进程限制，**不是操作系统安全沙箱**，也不授权模型运行或校准。

真实 DeepSeek 测试在修正初稿后，已提取 1,096 条 HYDAT 逐日记录和 8,760 条 Compton 逐小时记录；独立逐条比较与原始数据完全一致。这证明本次两个观测数据提取案例通过，不代表新站点模型模拟已完成，也不代表读取器已经成为通用验证工具。参见[测试报告](issues/CANADIAN-NEW-SITE-READINESS-2026-10-05.md)。

### 加拿大测试中的真实例子

- **HYDAT**：实际交付约 1.28 GB 的 SQLite 文件。读取器应只读检查数据库，提取目标站点与时段的逐日流量，保留缺失值和标记，并核实流量单位。CRHM 所需的气象驱动、流域配置及模拟输出与实测流量的对应关系仍需单独建立。
- **魁北克 Agrometeo**：实际交付 2012–2023 年的 12 个 `soilTemp10cm_*.csv`，合计约 361 MB。每个文件有站点、日期、纬度、经度和摄氏土壤温度五列，文件之间存在编码和表头差异。交付内容没有目录中另外列出的气象变量，也没有明确的时区或 QC 字段。SHAW 仍需气象驱动、场地／土壤／植被参数和初始条件，并按深度及时间约定与观测对应。

上述事实来自真实下载文件，并不表示 CRHM–HYDAT 或 SHAW–魁北克的新站点模拟已完成。独立检查发现 Compton 的 2022 年逐小时记录完整，但原始时间戳不能证明是 UTC；没有 QC 列也不等于全部观测已通过质量审核。

### 已有接口与服务器配套交付建议

本地读取器补充功能属于 Desktop 开发内容。**服务器下载时同时提供配套数据 KI，是另一项建议。** 本次检查的交付文件没有这样的 KI，尚未验证服务器已实现相应元数据协议。

目前 `obs_access.py` 只保留明确允许的目录、结构描述和清单字段，其中没有配套 KI 的身份、版本或入口。下载过程会保存、校验和解包数据，但不会自动把其中的 Python 文件注册成可执行工具。现有 KI 导入验证和批准执行流程可以作为后续集成基础；`obs_prepare.py` 的模型输入准备估算并不是数据读取器交付接口。

最小建议是：服务器有适用读取器时，将其说明与文件一同交付，并提供可选的结构化描述，记录身份、版本、兼容的数据结构、包内清单位置或已认可的包身份、工具入口和哈希。Desktop 明确保留这些信息，经验证并纳入计划后使用，同时记录读取器与原始／派生文件的哈希。具体字段需与服务器约定，不能当作现有 API 保证。现有 `KISSPATH_DATA_KI` 只是映射到项目输入目录的兼容路径，不代表数据库已提供数据 KI 注册机制。
