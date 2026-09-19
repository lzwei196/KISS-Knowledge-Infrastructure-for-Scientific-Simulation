# GeoForge Desktop changelog / 桌面版更新日志

This is the human-readable companion to [`release-manifest.json`](release-manifest.json).
Desktop update agents should read the JSON manifest first and use this file to explain the update.

这是 `release-manifest.json` 的用户版说明。Windows、macOS 和 Linux 的更新 Agent
应先读取 JSON，再用本文件向用户解释更新内容。

## v0.6.54 — 2026-09-19

### 中文

- 设置改为带侧边栏的窗口：AI 服务（每个服务商一张卡片，状态、密钥、默认选择一目了然）、GeoForge 数据库
  （连接状态、Token，以及本地目录浏览器：按领域 / 获取方式 / 类型筛选、搜索、查看每个数据集的变量、时段、范围、
  格式、大小）、网络与代理、权限（Kimi 文件访问；MCP 按对话选择）。侧栏的“⌁ 连接”按钮移除。
- 整文件栅格（如 HWSD）服务器拒绝按波段筛选时，Desktop 自动改为不带变量列表重新估算，蒙特利尔案例的 HWSD
  从 1.7 GB 网盘下载变为 14 KB 服务器裁剪。等待网盘文件时，下载卡新增“修改计划”，可直接回到规划。
- 项目状态里“需要你处理”的输入可逐项上传，文件放到 `inputs/user/<输入名>/`，文件到位后该行变为“文件已到位”；
  原“添加源数据”改名为“上传其他文件”并说明用途。
- 仓库清理：约 35 GB 误提交的构建产物、验收数据与发布包移出 git，并加入忽略规则。
- 本地数据库搜索返回覆盖判断（已声明条件满足／不足／待核实），优先显示覆盖满足的候选，
  拒绝无效坐标和日期。备选源不再自动固定为已选数据。项目状态新增数据准备下一步，
  区分手动下载、批准后由 Agent 下载、已有文件检查、上游就绪后准备及重新选择数据。
  覆盖判断仅基于目录元数据，不表示已经验证模型输入或提供了网格裁剪下载。
- 数据到位检查忽略空目录、隐藏缓存和未完成的下载文件；无目标路径时保留等待状态。
  数据面板验证下载 receipt 签名及文件校验和，文件删除或被替换后不再显示为已下载。
- 流程改造第 4 步（进行中）：批准卡与项目状态的数据分为三组，由 Desktop 依据事实判定，不再信任 Agent 的
  status/needs_user：“批准后由 GeoForge 取回”（直接下载、服务器裁剪）、“需要你”（网盘下载、需在方案中选定数据集、
  需你提供文件并给出格式/单位/要求/放置路径）、“运行自行准备”（已在本机、由步骤生成、KI 默认工具并注明工具名）。
  判定来源是 KI 自己的 dag.yaml 输入声明（source_kind、格式、单位、说明）与写出该格式的 KI 工具。项目状态面板压缩为
  三块：需要你、项目进度（含目标与 KI）、本次计划的数据；其余折叠到“更多细节”。手动下载卡按数据集去重并成为项目
  记录的当前阻塞项；对话滚动只在已到底部时跟随；提问卡片会结束 Agent 回合；连接建立失败也重试一次；断线前已提交的方案不再丢失；
  安装修复继续原会话而不是重启。
- 第 3 步复审修复：手动交付在真实客户端下无法签 receipt（目标目录非空检查早于“manual”应答）、
  “文件已放好”消息触发未赋值变量崩溃、旧的取数状态在重新规划后残留导致永远 BLOCKED，三项均已修复并有回归测试。
  另：取数过程与面板轮询互斥；估算临时失败可重试；请求卡片文件对 Agent 不可读；卡片被关掉后可从项目状态重新打开；
  网盘链接只接受 http(s)；`.bc!`/`.crdownload` 等未完成文件与符号链接不进入 receipt；删除已死的 download_observation_data /
  obs-download / fetch_observation 与 inventory-updates.jsonl。
- 流程改造第 3 步：新增 ACQUIRING 状态。计划批准后，Desktop 自己把每个已批准输入取回来（直接下载、
  服务器裁剪、网盘手动交付），每项写签名 receipt，全部到位后才进入执行；进度记录在 `.geoforge/acquisition.json`，
  不再改动已批准的清单。手动交付合并为一张多行卡片；“文件已放好，继续”会对放置的文件做哈希并签名 receipt
  （此前手动数据没有 receipt，会挡住项目完成）。取数失败进入 BLOCKED，卡片提供“重试缺失项 / 修改方案”。
  项目状态面板轮询时也会推进取数，无需在对话里发消息。执行阶段不再提供 download_observation_data /
  obs-download。顺带修复：裁剪预算按每个文件加 64 KB 容器开销（176 个单格 NetCDF 实际 5 MB，估算 0.5 MB）；
  重新规划改名后的条目复用已校验的文件而不重复下载；下载前先检查目标目录非空，不再覆盖并删除原始 zip 证据。
- 流程改造第 2 步：数据清单就是数据建议。Agent 在 write_plan 里只需给出 dataset_id 与研究范围
  （bbox/时段/变量，或直接给 acquisition_id），Desktop 自己把条目对应到已有的裁剪估算、在出卡前重新估算、
  在“批准并开始”时再估算一次；体量或数据源版本变化就退回卡片而不签名。批准计划即创建服务器裁剪任务，
  项目状态里不再有单独的“批准所选取数请求”按钮、数据建议弹窗、刷新与 15 分钟过期。执行阶段若发现任务
  未创建会按已批准计划自行补建。旧的 `search_observation_data` 工具与 `--propose` 已移除。
- 流程改造第 1 步（见 docs/FLOW-TARGET-2026-09-17.md）：GeoForge 数据库工具拆成三个单一职责工具
  `search_catalogue`（含 parent_id 解析）、`describe_dataset`、`estimate_clip`（任务理解阶段最多 5 次），旧的多模式
  `search_observation_data` 标记为弃用、仅保留 subset_proposal。任务理解与规划回合不能以纯文字结束：
  没有 write_plan / request_user_action / 完整 intake 报告时，Desktop 自动追问一次；报告“未就绪、有待问问题”
  但把问题写在文字里也会被追问，要求用卡片提问。API 流中断自动重试一次。
- 对接 GeoForge 数据库裁剪服务 obs_subset/3：估算、清单和数据源描述中的处理版本、数据源版本、
  格网约定（cell_edges / 格心范围 / 形状 / 间距）、单位来源与覆盖范围说明现在都被保留并写入签名 receipt；
  清单版本与已批准估算不一致时拒绝下载。多成员数据（作物日历）少交付时，项目状态会标注
  “部分交付：承诺 N 个成员，收到 M 个”，不再当作完整；`variable_selection_unsupported` 会提示 Agent
  查看 schema 后用空变量列表重新估算。已用 DeepSeek 在编译版 App 中复测 CMFD、Sacks、GGCMI、DEM、HWSD 五类数据。
- 新增 GeoForge Database 数据目录搜索：项目数据面板可按变量、地区、时期或数据 ID
  查询服务器的真实记录，并把候选数据交给 Agent 对照当前 KI 合同检查。
- 激活 token 在 macOS 使用 0600 私密文件（从 Keychain 迁移），Windows 使用 Credential Manager，Linux 使用 Secret Service；
  不写入设置文件、Agent 提示词或对话记录；设置页保留后端的精确错误说明。
- KI Harness 在规划阶段只能搜索并固定精确数据 ID。用户批准后才能下载；
  Desktop 校验 SHA-256、安全解压到项目 `inputs/`，并写入签名 receipt 和数据来源记录。
- 超过直接下载限制的数据会以私有用户弹窗显示百度网盘链接、提取码和
  项目目标路径，不把这些内容回显给 Agent。
- 数据库接入现在也是一个由 KDT-single 验证的 `task_workflow` KI。CLI Agent
  只获得当前 Desktop 进程签发的临时只读 capability；真实激活 token 始终留在 Desktop。
- 修复 Kimi 调用数据库或 Flow 工具时反复弹出 macOS“文稿”权限的问题。
  稳定 launcher 不再二次执行 Documents 中的 App Bundle，而是通过带随机 capability
  的 loopback bridge 调回已运行的 Desktop；命令仍由计划、批准和 receipt 闸门检查。
- 数据库 token 在单次 Desktop 进程中只读取一次钥匙串；如果用户拒绝或取消授权，自动
  查询不会再次触发系统窗口。只有用户在设置中主动点击“保存并测试数据库”才会重试。
  未使用稳定 Apple 签名的本地开发包在每次重新编译后仍可能需要一次首次授权。
- API 服务商（DeepSeek、OpenAI、OpenRouter、Anthropic）改为流式响应。此前一次超过 5 分钟的
  规划回合会被当作断线重试三次，每次从头生成，因此永远无法完成；现在长回合正常完成，
  且超时只针对“连续 5 分钟没有任何数据”。
- 活动面板新增“停止”按钮：可中止正在进行的 API 回合或本地 CLI Agent。
- GeoForge 数据库目录改为应用级本地副本：保存 Token 后自动下载完整目录（仅元数据，约 1,100 条），
  启动时和每 6 小时按 ETag 刷新，服务器不可达时保留上一份并标注过期。数据面板、API Agent 工具
  和 CLI 的 `obs-search` 都在本地按范围（bbox）、时段、变量、类别、交付方式筛选，不再逐次请求服务器。
- 修复 API 回合在计算过程中被显示为“已结束，正在保存”的状态误报；
  计划自动修复回合现在标注轮次。
- “项目状态”按钮名称固定不变，状态改用彩色圆点和悬停提示表示；项目视图的面板数量在面板关闭时也会每 5 秒更新。
- AI 设置和项目状态面板中的 GeoForge 数据库卡片现在显示：本地目录条数、可直接下载条数、上次同步时间，
  以及 API Agent（search_observation_data 工具）和 CLI Agent（geoforge-db 命令）各自的检索方式。
  Agent 访问方式简化为“直接查询”和“关闭”两项。活动栏会明确显示“正在检索 GeoForge 数据库”。
- 计划提交时，Desktop 会把数据清单中每个指向 GeoForge 数据库的条目核对到本地目录：写入 `dataset_id`、
  交付方式、大小、范围与时段；未知 ID 会作为校验错误退回 Agent；整库级父产品（如 242 GB 的全国 CMFD）
  不允许作为下载单元，必须选区域子集或按变量×年份的子文件。批准卡按“GeoForge 自动下载 / 需你手动下载
  （含大小）/ 由运行生成 / 缺失”分组显示；含手动下载数据的计划不再自动批准。
- 手动下载提示会给出网盘分享内应下载的具体文件路径；直接下载上限对齐服务器的 100 MB。
- 修复 DeepSeek 等 API 提交计划反复失败的根因：请求未设置输出 token 上限（DeepSeek 默认 4K），
  计划加数据清单的工具调用参数被截断，Desktop 只报“must be JSON objects”。现在两种接口都请求 8K 输出；
  被截断的工具调用会明确告知 Agent；`write_plan` 支持分两次提交（先 plan，再 data_inventory）并接受 JSON 字符串。
- 单次流式响应设 15 分钟硬上限，代理的 keep-alive 行不再被当作进展。
- Agent 的 intake 提问被用户回答后，Desktop 直接进入规划，不再等待 Agent 再报一次 intake（避免连问两轮）。
- KI 在 `knowledge_infrastructure.yaml` 中声明的模型可执行文件（如 VIC 的 `vic_classic.exe`）现在可以
  作为计划步骤的 tool：计划校验、CLI `run-tool` 和 API `run_ki_tool` 都接受它，并写入签名 receipt。
  此前编译型模型的运行步骤无法指定合法 tool，导致新加入的“model_run 必须有 tool”门禁无法通过。
- 手动下载请求在文件真正放到指定路径之前保持打开：在对话中提问不会再让链接和提取码消失。
- 项目状态面板新增“本次计划的数据”卡片：列出计划数据清单中的每一项及其真实状态（已就绪 / 等你下载 /
  待处理 / 缺失），状态来自 receipt 和本地文件而非 Agent 的说法。手动下载请求卡片现在带“打开下载链接”、
  放置路径复制和“文件已放好，继续”按钮；对话中同时出现一条提醒，指向项目状态（链接和提取码不进入对话）。
- Desktop 在任务理解和规划阶段自动从本地目录匹配与研究描述相关的记录（站号、流域/河流名及其英文别名、
  关键词），以“本研究可用的 GeoForge 数据库数据”块注入 Agent 提示；Agent 必须向用户说明这些数据存在、
  哪些可自动下载、哪些需手动下载。用户不再需要主动想起“用 CMFD”。
- 数据库检索工具说明和任务理解阶段的规则也写明 manual 交付可用；以数据集 ID 命名的数据清单条目
  在计划提交时会自动固定该 ID，执行阶段的下载也接受这种写法。
- 规划与执行合同明确说明：`delivery: manual` 的数据集是正常选项——规划时固定其 ID，批准后
  `download_observation_data` 会向用户显示网盘链接、提取码和放置路径并等待文件；Agent 不应把人工交付当作走不通。
- 执行回合结束时，若该回合没有产生任何签名 receipt（既没运行工具也没下载），对话中会追加一条
  “GeoForge 校验”说明：本回合无受 receipt 记录的步骤，Agent 文字中描述的产物在有 receipt 之前不算存在。
  此前 Agent 可以在对话里声称已完成步骤而界面不作纠正。
- API Agent 在执行中发现计划无法照办时，可调用新的 `request_replan(reason)`：Desktop 立即把项目切换到
  REPLAN_REQUIRED、撤销批准并开放 `write_plan`，Agent 在同一回合内写出修正后的计划；用户随后重新批准。
  此前 Agent 只能停下来请用户“把会话退回规划”。
- Agent 在执行中报告 REPLAN_REQUIRED 后，Desktop 会自动以其说明启动重新规划回合并写出修正后的计划，
  不再需要用户重复提出修改请求；修正后的计划仍需用户批准。
- 会话列表不再在列出时打开位于外部文件夹（如“文稿”或云盘）中的项目，只在用户打开该会话时读取；
  此前每个新构建的 App 都会在启动时触发一次 macOS 文件夹访问授权。
- 页面启动时的请求会重试（后台可能刚被系统授权窗口阻塞），失败横幅提供“重新加载”按钮。
- macOS 上数据库 Token 不再存入登录钥匙串，改为保存在仅当前用户可读的私密文件
  （`~/Library/Application Support/KISS/secrets/`，权限 0600）。钥匙串条目的访问权与 App 的代码签名绑定，
  而 GeoForge Desktop 每次构建/更新都是新的签名身份，导致每次都弹出授权；现在只在首次启动时从钥匙串
  迁移一次，之后不再询问。
- 目录刷新在等待钥匙串授权或网络时不再阻塞其他调用：搜索、设置页和状态查询直接使用现有本地副本，
  由单个后台线程完成刷新。
- 运行验证失败后，用户的下一条消息会在同一已批准计划下重新进入执行回合（此前会话会卡在
  FAILED_VALIDATION，既不能重跑也不能重新规划）。
- 重新规划后，已校验通过的下载不再作废：只要同一数据条目仍在计划中且文件校验和未变，
  其 receipt 继续有效，不必重复下载。
- 取消计划的自动批准：任何计划都必须由用户在批准卡上点击“批准并开始”后才会执行，
  批准卡不再是可以被跳过的提示。此前当计划没有待定选项时，Desktop 会自动批准并直接开始运行。
- 批准卡改为分区结构化展示：任务理解（KI、耦合、区域、时段）、数据（已在本机 / 自动下载 / 需手动下载含大小 /
  由运行生成 / 缺失）、步骤（工具与环境变量数）、科学决定、等待你处理的事项；文字版摘要折叠在底部。
- 由前序步骤生成的中间产物不再被判定为“缺失输入”，多步骤流水线的计划可以正常通过执行就绪检查。
- 用户在任务中要求“先规划、批准后再执行”时，该要求对整个项目生效：修改计划或自动修复的回合
  不会再因为说明文字不含该要求而被自动批准。
- 数据库状态查询不再触发钥匙串读取；只有真正需要联网的刷新和“保存并测试数据库”才会读取 Token。
- 桌面端草案不再沿用服务器时代的数据来源（`cmfd_v1`、`mswx_v1` 等 provider id 和服务器路径）：
  这些输入在草案中标为待 Agent 从 GeoForge 数据库检索并固定 `dataset_id`，批准卡上也不再出现
  provider id 选项。Agent 写的展示名（如 `AVHRR_1km_LANDCOVER_1981_1994`）在唯一匹配时会自动对应到目录 ID。

### English

- Settings is now a window with a sidebar: AI services (one card per provider with status, key and default
  choice), GeoForge Database (connection state, token, and a browser of the local catalogue by domain / delivery /
  kind with search and per-dataset variables, period, extent, format and size), Network & proxy, Permissions
  (Kimi file access; MCP servers stay per chat). The sidebar "⌁ Connections" button is gone.
- Whole-file rasters (HWSD) that refuse band selection are re-estimated without a variable list, so the Montreal
  case gets a 14 KB server clip instead of a 1.7 GB Baidu download. While waiting for Baidu files the download
  card offers "Change the plan", which returns to planning directly.
- Inputs under "needs you" in Project status can be uploaded one by one into `inputs/user/<input>/`; the row turns
  to "files available" once real files are there. "Add source data" is now "Upload other files" with its purpose stated.
- Repository cleanup: ~35 GB of accidentally committed build output, acceptance data and release bundles removed
  from git and ignored.
- Flow rework step 4 (in progress): the approval card and Project status sort data into three groups
  decided by the desktop from facts, never from the agent's status/needs_user: "GeoForge fetches after
  approval" (served, server clip), "You" (Baidu download, pick a dataset in the plan, or provide a file with
  format / unit / rules / target path), "The run prepares itself" (on disk, made by a step, KI default tool
  named). The source is the KI's own dag.yaml input declaration (source_kind, format, unit, notes) plus the KI
  tool that writes that format. Project status is reduced to three blocks: Needs you, Progress (goal + KI),
  Data in this plan; everything else under "Details". The manual download card dedupes by dataset and is the
  run's current blocker; chat scroll follows only at the bottom; a question card ends the agent's turn; a
  failed connect is retried once; a plan submitted before a dropped connection is kept; setup repair
  continues the agent's own session instead of restarting.
- Step 3 review fixes: manual delivery could not be receipted with the real client (destination check ran
  before the "manual" answer), the "Files are in place" message crashed on an unassigned local, and stale
  acquisition entries survived a replan and kept the project BLOCKED; all three fixed with regression tests.
  Also: acquisition passes and the panel poll are mutually exclusive; a transient estimate failure is retried;
  request-card files are unreadable to agents; a dismissed card reopens from Project status; Baidu links must be
  http(s); partial downloads and symlinks never enter a receipt; dead download_observation_data / obs-download /
  fetch_observation and inventory-updates.jsonl removed.
- Flow rework step 3: ACQUIRING state. After plan approval the desktop fetches every approved input
  itself (served download, server clip, Baidu manual delivery), signs a receipt per item, and only
  then enters execution; progress lives in `.geoforge/acquisition.json`, the approved inventory is
  never edited. Manual deliveries share one multi-row card; "Files are in place, continue" hashes the
  placed files and signs a receipt (manual data had none before and blocked completion). A failed
  fetch lands in BLOCKED with a Retry / Modify card. Project status polling advances acquisition
  without a chat message. download_observation_data / obs-download are gone from execution. Also
  fixed: clip budget allows 64 KB container overhead per part (176 single-cell NetCDFs were 5 MB
  against a 0.5 MB estimate); renamed items after a replan reuse verified files; downloads check the
  destination before touching the archive, so a retry can no longer delete raw zip evidence.
- Flow rework step 2: the data inventory is the proposal. In write_plan the agent gives a dataset_id
  and the study scope (bbox/period/variables, or an acquisition_id); the desktop joins the item to the
  matching clip estimate, re-estimates before the card and again at "Approve and start", and re-issues
  the card unsigned if size or source version changed. Approving the plan creates the server clip jobs.
  Project status loses the separate "Approve selected acquisitions" button, the proposal popup, Refresh
  and the 15-minute expiry. Execution creates a missed job under the approved plan. The old
  `search_observation_data` tool and `--propose` are removed.
- Flow rework step 1 (docs/FLOW-TARGET-2026-09-17.md): the GeoForge Database tool is split into
  `search_catalogue` (with parent_id resolution), `describe_dataset` and `estimate_clip` (capped at 5 during
  intake); the multi-mode `search_observation_data` is deprecated and kept only for subset_proposal.
  Intake and planning turns may no longer end in prose: without write_plan, request_user_action or a
  ready intake report the desktop nudges the agent once; a "not ready" report whose question is written
  in prose is nudged to ask through the card. A dropped API stream is retried once.
- Support the GeoForge Database subset service obs_subset/3: processing/source versions, grid
  convention (cell_edges, cell-centre bounds, shape, spacing), units authority and coverage scope
  from estimate, manifest and describe are kept and signed into the acquisition receipt; a manifest
  whose version differs from the approved estimate is refused. Short multi-member deliveries (crop
  calendars) are shown in Project status as "partial delivery: promised N, received M" instead of
  complete; `variable_selection_unsupported` tells the agent to describe the schema and re-estimate
  with an empty variable list. Retested CMFD, Sacks, GGCMI, DEM and HWSD through the compiled app with DeepSeek.
- Add live GeoForge Database catalogue search to the project data panel by variable, place, period or
  exact dataset id, with a handoff that asks the Agent to validate a candidate against the active
  KI contract.
- Store the activation token only in Keychain, Credential Manager or Secret Service. It is absent
  from settings JSON, prompts and chat transcripts, and backend authentication errors remain
  distinct and actionable in Settings.
- During planning, the KI Harness can search metadata and pin an exact dataset id but cannot
  download it. After approval, Desktop verifies SHA-256, safely extracts below project `inputs/`,
  and records a signed receipt plus provenance.
- Large manual datasets open a private user handoff containing the Baidu link, extraction code and
  exact target path without echoing those details back to the Agent.
- Package database discovery as a KDT-single-verified `task_workflow` KI. CLI Agents receive only a
  short-lived read-only capability for the current Desktop process; the persistent activation token
  never enters their environment or prompt.
- Stop Kimi's repeated macOS Documents permission prompts during database and Flow calls. Stable
  launchers now use a capability-authenticated loopback bridge to the already-running Desktop instead
  of executing the App Bundle a second time; plan, approval and receipt gates remain authoritative.
- Read the database token from the native password store only once per Desktop process. A denied or
  cancelled Keychain request is not retried by automatic Agent searches; only the user's explicit
  **Save & test database** action reopens it. Locally rebuilt apps without a stable Apple signing
  identity may still require one first-use authorization after each rebuild.
- Stream API provider responses (DeepSeek, OpenAI, OpenRouter, Anthropic). A planning turn longer
  than five minutes was previously treated as a dropped connection and retried three times, each
  restarting the generation, so it could never finish. Long turns now complete; the timeout only
  covers five minutes of complete silence.
- Add a **Stop** button to the activity panel that ends the running API turn or local CLI agent.
- Keep one app-level copy of the GeoForge Database catalogue: downloaded when the token is saved
  (metadata only, about 1,100 records), refreshed at start and every six hours by ETag, kept and
  marked stale when the server is unreachable. The data panel, the API agent tool and the CLI
  `obs-search` command all filter that copy locally by bbox, period, variable, category and
  delivery instead of querying the server per search.
- Fix API turns being shown as "finished; saving" while the model was still computing, and label
  automatic plan-repair rounds with their round number.
- The **Project status** button keeps one fixed name; its state is a colored dot plus tooltip. The
  Project view panel count now refreshes every 5 s even while the panel is closed.
- The GeoForge Database card in AI Settings and in the Project status panel shows the local
  catalogue size, how many records download directly, when it was last synced, and how each kind
  of agent reaches it (API providers through the search_observation_data tool, CLI agents through
  the geoforge-db command). Agent access is now a two-way choice: direct or off. The activity bar
  says "Searching GeoForge Database" while a search runs.
- When a plan is submitted, the desktop checks every inventory item that names a GeoForge Database
  record against the local catalogue and records `dataset_id`, delivery, size, coverage and period
  on it. Unknown ids go back to the agent as validation errors. A whole-product parent (such as the
  242 GB national CMFD) is refused as a download unit: the agent must pin the regional subset or
  per-variable-year children. The approval card groups inputs as GeoForge downloads, you must
  download (with sizes), generated by the run, and missing. Plans with manual downloads are never
  auto-approved.
- Manual download handoffs name the exact file inside the Baidu share; the direct-download cap
  matches the server's 100 MB.
- Fix the root cause of repeated plan-submission failures with DeepSeek and other API providers:
  requests set no output token limit (DeepSeek defaults to 4K), so the write_plan tool call carrying
  plan plus inventory was truncated and the desktop only said "must be JSON objects". Both wires now
  request 8K output tokens, a truncated tool call is reported to the agent as such, and write_plan
  accepts two calls (plan first, then data_inventory) as well as JSON strings.
- One streamed response is capped at 15 minutes; proxy keep-alive lines no longer count as progress.
- When the user answers the agent's intake question, the desktop enters planning directly instead
  of waiting for the agent to report intake a second time.
- The model executable a KI declares in `knowledge_infrastructure.yaml` (for VIC, `vic_classic.exe`)
  is now a valid plan-step tool: plan validation, the CLI `run-tool` and the API `run_ki_tool` all
  accept it and write a signed receipt. Before this, a compiled model's run step could not name any
  legal tool, so the new "model_run must have a tool" gate could never pass.
- A manual download request stays open until files actually exist at the expected path; asking a
  question in the chat no longer makes the link and code disappear.
- Project status gains a "Data in this plan" card listing every inventory item with its real
  state (ready, waiting for you, pending, missing), taken from receipts and files on disk rather
  than the agent's words. The manual-download request card now has an "Open download link"
  button, a copyable target path and a "Files are in place, continue" button, and the chat shows a
  reminder pointing at Project status (the link and code never enter the chat).
- At intake and planning the desktop itself matches the study description against the local
  catalogue (station numbers, basin and river names with their English aliases, keywords) and
  injects an "available for this study" block into the agent's prompt. The agent must tell the
  user which records exist, which download automatically and which are manual. Users no longer
  have to remember that a dataset such as CMFD exists.
- The database search tool's description and the intake rules also say manual delivery is usable.
  An inventory item named after a catalogue dataset is pinned to it automatically at plan
  submission, and the execution-time download accepts that form.
- The planning and execution contracts now say that a manual-delivery dataset is a normal choice:
  pin it, and after approval download_observation_data shows the user the link, code and target
  folder and waits for the files. Agents must not present manual delivery as a dead end.
- When an execution turn ends without a single signed receipt (no tool run, no download), the chat
  now carries a "GeoForge verification" line saying so: anything the agent described as produced
  does not exist until a receipt records it. Before, the agent's prose stood uncontradicted.
- An API agent that finds the approved plan cannot be carried out can call the new
  `request_replan(reason)` tool: the desktop moves the project to REPLAN_REQUIRED, revokes the
  approval and offers `write_plan` at once, so the corrected plan is written in the same turn and
  the user re-approves it. Before, the agent had to stop and ask for the session to be moved back.
- When the agent reports REPLAN_REQUIRED during execution, the desktop starts the re-planning turn
  with the agent's reason and lets it write the corrected plan, instead of waiting for the user to
  repeat the request. The corrected plan still needs approval.
- The session list no longer opens projects that live in external folders (Documents, a cloud
  drive) while listing; they are read only when opened. Every new build used to trigger a macOS
  folder-permission dialog at start-up because of this.
- The page retries its start-up requests (the backend may have been stalled by a system permission
  dialog) and the failure banner offers a Reload button.
- On macOS the database token now lives in a private file readable only by the current user
  (`~/Library/Application Support/KISS/secrets/`, mode 0600) instead of the login Keychain. A
  Keychain item's access list is bound to the app's code signature, and every GeoForge build or
  update is a new ad-hoc identity, so the consent dialog reappeared on every version. The token
  is migrated from the Keychain once on first start and never asked for again.
- A catalogue refresh that is waiting on the Keychain or the network no longer blocks other
  callers: searches, the settings page and the status line answer from the current local copy
  while a single background thread does the refresh.
- After a failed validation the user's next message resumes execution of the same approved plan
  (the session used to be stuck in FAILED_VALIDATION with no way to rerun or replan).
- Verified downloads survive a replan: a download receipt stays bound while the same inventory
  item is pinned and the file's checksum is unchanged, so data is not fetched twice.
- No more automatic plan approval: every plan waits for the user to click **Approve and start**
  on the approval card. Previously a plan with nothing left to decide was approved by the desktop
  and execution began without a click.
- The approval card is now sectioned: what was understood (KI, coupling, area, period), data
  grouped as on disk / automatic download / manual download with sizes / generated by the run /
  missing, steps with their tool and environment count, scientific decisions, and what is waiting
  on you. The text summary folds away at the bottom.
- Inputs produced by an earlier step of the same plan no longer count as missing, so multi-step
  pipelines pass the execution-readiness check.
- A request to review the plan before anything runs now holds for the whole project: modify and
  repair rounds are no longer auto-approved just because the note text lacks that request.
- The database status query no longer touches the Keychain; only a real network refresh and
  "Save & test database" read the token.
- Desktop drafts no longer carry server-era data sources (`cmfd_v1`, `mswx_v1` provider ids and
  server paths). Those inputs are marked for the agent to resolve from the GeoForge Database with
  an exact dataset_id, and the provider-id choice no longer appears on the approval card. Display
  names the agent writes, such as `AVHRR_1km_LANDCOVER_1981_1994`, are matched to a catalogue id
  when exactly one fits.

## v0.6.52 — 2026-09-03

### 中文

- 修复干净 Linux/Windows 环境没有安装 GeoPandas 时，可选地理空间能力名称未初始化，
  导致发布测试无法注入替身的问题。运行时仍由显式能力标志控制，不会假装依赖可用。
- 延续 v0.6.51 的失败关闭发布闸门和 v0.6.50 的完整 Desktop 功能集。

### English

- Define optional geospatial dependency handles consistently when GeoPandas is absent, allowing
  clean Linux/Windows environments to probe and test the capability without pretending it is
  installed.
- Retains v0.6.51's fail-closed release gate and the complete v0.6.50 Desktop feature set.

## v0.6.51 — 2026-09-03

### 中文

- **完整重发 v0.6.50 的功能**：首次 `v0.6.50` CI 因两项依赖开发机环境的测试而停止，
  但旧发布脚本仍错误地公开了一个只有 KI 包、没有 Desktop App 的不完整 Release。
- **发布闸门已修复**：只有 macOS Apple Silicon、Windows x86_64 和 Linux x86_64
  三个平台均构建、冻结运行检查并上传成功，GitHub 才能公开 Release；精确文件检查不再
  使用会把不存在文件误判为存在的 Bash 数组长度。
- **测试可跨机器复现**：Kimi 路径权限测试不再依赖开发机的安全模式或用户主目录。

除上述发布工程修复外，Desktop 功能与下面完整记录的 v0.6.50 相同。

### English

- **Complete reissue of the v0.6.50 feature set:** the first v0.6.50 CI run stopped on two
  tests that accidentally depended on the developer machine, while the old release job still
  published an incomplete metadata/KI-only release with no Desktop application.
- **Fail-closed release gate:** a public release now requires successful builds, frozen-runtime
  smoke tests and uploaded Desktop archives for macOS Apple Silicon, Windows x86_64 and Linux
  x86_64. Exact file checks replace the Bash-array test that misclassified a missing file.
- **Host-independent tests:** Kimi path-permission tests no longer depend on a developer's security
  setting or home-directory layout.

Desktop behavior is otherwise the v0.6.50 feature set documented in full below.

## v0.6.50 — 2026-09-03

### 中文

- **KI harness 从提示词升级为执行闸门**：Desktop 现在正式执行“理解任务 → 盘点数据 →
  生成计划 → 用户批准 → 下载/运行 → 证据验证”。批准前 Agent 只能读取、查询和规划；
  模型工具、下载和结果声明必须对应已批准的步骤与可检查的运行凭据。
- **冻结版完整性修复**：harness 及 Flow 的 9 个运行模块都作为 Python 模块打包。
  启动检查和跨平台 CI 会验证真实合同、工具信任模块及数据构建模块均来自当前 App，
  不再悄悄退回四行弱化提示。
- **内部 intake 标记不再显示**：`GEOFORGE_INTAKE` JSON 仍用于可靠地传递研究区、
  时段、过程、输出和缺失数据，但 Desktop 会在展示消息前将其消费并移除。
- **本地服务安全加固**：所有写操作要求本次 App 随机生成的 SameSite token 与本地同源
  请求；恶意网页不能再跨站请求 localhost 来创建会话或修改设置。
- **设置并发保存修复**：API key、代理和服务商设置改用加锁、原子替换及仅用户可读写权限，
  避免同时保存时丢失字段或产生损坏 JSON。
- **科学数据空间选择修复**：NetCDF 工具支持降序坐标、0–360 经度及跨日期变更线范围；
  流域矢量会按 CRS 转换到经纬度。曲线网格、空选择、全缺测结果会明确失败，避免返回
  看似正常但实际错误的数据。
- **可移植安装修复随 KI 发布**：CRHM、Alpine3D 与 WRF-Hydro 的已有安装路径、编译产物
  和预检位置保持一致，不再依赖作者机器上的绝对目录。
- **发布过程统一**：macOS、Windows、Linux 均由已纳入版本控制的 spec 构建；release
  同时包含源码、更新清单、更新日志、校验和与完整 KI 安装包。

本地验证：Desktop/Flow **311 通过、3 跳过**；KI 工具 **98 通过、2 跳过**；
气候与单位 **83 通过**；诊断框架 **46 通过**。真实本地接口回归中，同源写入返回 200，
跨域写入返回 403。最终冻结 App 与 GitHub 跨平台构建结果记录在 release 中。

### English

- **The KI harness is now an execution gate:** Desktop enforces task intake, data inventory,
  planning, explicit user approval, execution and evidence verification. Before approval, the Agent
  can inspect and plan but cannot download data or run model tools. Runs are bound to approved steps
  and produce checkable receipts.
- **Frozen-runtime integrity:** the harness and all nine Flow runtime modules are collected as Python
  modules. Startup and cross-platform CI prove that the full contract, tool-trust module and data
  builder load from the current app; a packaged build cannot silently fall back to weaker guidance.
- **Internal intake metadata stays internal:** GeoForge still consumes the structured
  `GEOFORGE_INTAKE` record for deterministic model selection and readiness, but removes it from the
  message shown to the user.
- **Local-service hardening:** every state-changing request requires a random process-local SameSite
  token and matching loopback origin, blocking cross-site pages from writing to GeoForge's localhost API.
- **Atomic settings:** API keys, provider and proxy settings use a locked transaction, restrictive
  permissions and atomic replacement so concurrent saves cannot lose fields or leave malformed JSON.
- **Scientific spatial correctness:** NetCDF helpers now handle descending coordinates, 0–360
  longitudes and antimeridian windows; basin vectors are reprojected from their declared CRS. Curvilinear
  grids, empty selections and all-missing means fail explicitly instead of returning plausible bad data.
- **Portable KI installation repairs:** CRHM, Alpine3D and WRF-Hydro use the selected existing-install
  location consistently across setup, compilation and preflight.
- **One release build contract:** macOS, Windows and Linux builds use version-controlled specs, and the
  release carries source history, a machine-readable manifest, human changelog, checksums and the full
  KI installation pack.

Local validation: **311 passed / 3 skipped** Desktop and Flow tests; **98 passed / 2 skipped** KI-tool
tests; **83 passed** climate/unit tests; and **46 passed** diagnostic checks. A live localhost regression
returned HTTP 200 for a token-bearing same-origin write and HTTP 403 for a simulated cross-origin write.
The final frozen-app and GitHub cross-platform results are recorded with the release.

## v0.6.49 — 2026-08-28

### 中文

- **Auto-KI 任务理解成为独立入口阶段**：未预选 KI 时，自然语言科研目标先交给 Agent 完整理解，再由 Desktop
  校验结构化的研究区、时段、物理过程、输出、关键缺口和候选 KI；不会再由正则先把整句话
  当成模型名，也不会仅凭选择了 KI 就跳进规划。API 与 Claude、Codex、Kimi CLI 使用同一
  intake 合同，缺口未清空时不能开始规划、下载或运行。
- **新增分层 KI 观测台**：从聊天主页或 KI 库进入，先查看 14 个科学领域，再进入
  领域查看 KI；点击 KI 后直接进入它的内部科学流程。跨 KI 关系降为可选辅助视图，
  默认不绘制关系线。图谱采用 KISS 论文
  `arXiv:2605.17856` 的 14 个地球科学领域框架，并明确区分论文的 119 个 KI
  基线与本地后来新增的 KI。
- **关系有实际依据且可筛选**：跨 KI 连线来自各自 `dag.yaml` 声明的输入和输出语义，
  可以分别查看科学耦合、共享数据或全部证据；不会用名称相似度伪造科学关系。
- **动态 KI 科学生产线**：数据入口、核心处理引擎、验证闸门和结果出口组成一条持续流动的
  主线；数据包沿连线移动，处理站依次点亮。长说明、可选模块和技术辅助节点默认折叠到
  “完整技术 DAG”，每个节点仍可单独查看并询问聊天 Agent。
- **科学叙事取代源码清单**：观测台默认把 DAG 投影为“汇集研究信息、构建模型对象、
  推演系统、连接组件、可信检查、形成结果”等科学阶段。程序模块名、变量名和文件位置
  只在每个阶段的“技术依据”或“完整技术 DAG”中显示。
- **Agent 状态具有证据等级**：聊天现在分别显示子进程、工具事件、项目阶段和项目文件变化。
  只有检测到下载工具或输入文件增长时才会显示“数据传输”；仅有进程心跳而长时间没有事件时，
  会明确提示“当前动作未确认/可能卡住”，并提供重新检查和新建对话按钮。Kimi Code 与
  Claude Code 的结构化工具事件还会显示经过脱敏的具体命令、脚本或文件路径，不再只写 `Bash`。
- **“询问 Agent”自动使用新对话**：从 KI、科学阶段或技术节点提问时，观测台会创建一个
  绑定当前 KI 的全新项目会话、跳转到聊天页并自动发送问题；不会再复用任意旧对话。
- **实时项目观察**：从观测台选择一个聊天项目，可查看当前 Agent、KI、准备、验证、运行、
  等待用户和结果状态。界面只读取桌面端已经记录的事件，不运行或导入 KI 代码。
- **通用与专用展示分层**：所有 KI 都有从 DAG 自动生成的通用视图；声明
  `visualization_contract.yaml` 的 KI 可继续加载地图、动画、三维模型、剖面或仪表盘。
- **中英文完整适配**：观测台跟随 GeoForge 语言设置，中文会话不再出现半中文半英文的导航。

验证结果：GeoForge 正式测试 **179/179 通过**；127 个本地 KI 均成功生成动态流程数据，
JavaScript 语法检查、冻结 App 启动检查与 macOS 签名验证通过。

### English

- **Task understanding is now a separate Auto-KI entry phase:** when no KI is preselected, a natural-language scientific goal reaches
  the Agent intact before the Desktop validates a structured study area, period, process, outputs,
  material gaps, and proposed KIs. Choosing a KI alone cannot start planning. Direct APIs and the
  Claude, Codex, and Kimi CLIs share the same read-only intake contract; unresolved gaps block
  planning, downloads, and execution.
- **Hierarchical KI Observatory:** open it from Chat or the KI Library, begin with 14 scientific
  domains, enter one domain to see its KIs, then open a KI directly into its internal scientific
  workflow. Cross-KI relationships are now an optional secondary view and are hidden by default.
  Its 14-domain frame follows the KISS KI paper
  (`arXiv:2605.17856`) while distinguishing the paper's 119-KI baseline from newer local packages.
- **Evidence-backed relationship filters:** links come from input and output semantics declared in
  each `dag.yaml`; users can switch between scientific coupling, shared data, and all evidence.
- **Animated scientific production line:** data intake, core processing engine, verification gate,
  and result outlet form one flowing story. Packets move along the line and processing stations light
  in sequence. Long descriptions and technical helpers remain in **Full technical DAG**.
- **Scientific narrative instead of a source listing:** the default view projects DAG semantics into
  human stages such as gathering evidence, building the model world, evolving the system, connecting
  components, passing a trust gate, and making results usable. Exact identifiers stay under
  **Technical evidence** and **Full technical DAG**.
- **Evidence-graded Agent state:** Chat separates process life, tool events, project reports, and
  project-file changes. It claims a data transfer only when a download tool or growing input is
  observed; a quiet heartbeat is shown as unconfirmed work and may be flagged as stalled. Structured
  Kimi Code and Claude Code tool events also show a redacted command, script, or path summary instead
  of the generic word `Bash`.
- **Ask Agent always starts a new chat:** asking about a KI, scientific phase, or technical node now
  creates a fresh project chat pinned to that KI, navigates to it, and sends the question automatically.
  No existing conversation is reused.
- **Live project observation:** selecting a chat project shows recorded Agent, KI, preparation,
  validation, execution, user-wait, and result state. The Observatory never imports or executes KI code.
- **Generic plus specialized rendering:** every KI receives a safe DAG-derived view; KIs with a
  `visualization_contract.yaml` may add maps, animation, 3D models, sections, or dashboards.
- **Bilingual behavior:** the Observatory follows the shared GeoForge language preference.

Validation: **179/179 GeoForge tests passed**. All 127 local KIs produced valid animated-flow
data; JavaScript syntax, frozen-app startup, and macOS bundle signing checks passed.

## v0.6.48 — 2026-08-27

### 中文

- **验证已经安装的软件**：Agent 设置页新增“使用已经安装的软件”。用户可以选择安装
  文件夹或可执行文件，也可以让 Agent 在系统标准位置与索引中查找。外部安装只允许
  读取和运行；链接、配置、日志和验证记录仍写入 GeoForge 自己的模型工作区。
- **DeepSeek API 路径规则补全**：用户明确选择的已有安装路径会作为受控的只读/可执行
  路径交给 API Agent，同时继续禁止它写入项目以外的个人文件。
- **验证徽章即时刷新**：聊天中的 Agent 修好模型并通过预检后，页面会立即重新读取机器
  状态，不再出现回复已经说“通过”、顶部仍显示红色“验证失败”的情况。
- **WRF-Hydro 安装路径修复**：兼容当前 CMake 的旧项目策略，并把完整 `Run` 目录放到
  KI 预检和运行工具共同使用的位置，避免二进制已经编译却被报告为找不到。

### English

- **Verify software already installed:** Agent setup can use a selected installation folder or
  executable, or search standard indexed locations. External software is read/executed only;
  GeoForge keeps links, configuration, logs, and verification evidence in its own workspace.
- **DeepSeek API path contract:** explicitly approved existing installations are available to the
  restricted API tool runner without opening unrelated personal files for writing.
- **Immediate verification refresh:** a successful repair and preflight now refreshes the chat
  header, removing stale red failure badges.
- **WRF-Hydro path repair:** current CMake policy handling and a shared complete `Run` directory
  prevent a successfully compiled executable from being mistaken for a missing installation.

## v0.6.47 — 2026-08-27

### 中文

- **所有桌面平台统一从 `main` 更新 KI**：Mac 和 Windows 的平台分支只承载各自的
  App 代码与发布工作；共享的 `models/` KI 定义和安装清单始终从规范 `main` 分支读取。
- 仍支持 `GEOFORGE_KI_UPDATE_BRANCH`，仅用于开发、暂存或故障恢复时明确覆盖来源。
- 实际联网确认：更新器选择 `main`，固定到 commit
  `2c11d79cff662b57a28e8aaec34896a24a8ae47f`；当前 KI tree 与已验证快照一致。

验证结果：GeoForge 测试 **160/160 通过**。

### English

- **Every desktop platform now updates KIs from `main`:** Mac and Windows branches carry their
  platform app code and releases only. Shared `models/` definitions and install manifests always
  come from canonical `main`.
- `GEOFORGE_KI_UPDATE_BRANCH` remains as an explicit development, staging, or recovery override.
- A real routed check resolved `main` to commit
  `2c11d79cff662b57a28e8aaec34896a24a8ae47f`; its KI trees match the validated snapshot.

Validation: **160/160 GeoForge tests passed**.

## v0.6.46 — 2026-08-27

### 中文

- **KI 库页面现在能直接设置代理**：点击右上角 `⚙ → 网络与代理`，选择系统代理或
  手动输入本地 HTTP/mixed 端口，再勾选“GitHub 与 KI 更新”。更新失败窗口也新增了
  “网络设置”快捷按钮。
- **内置 KI 更新器正式使用独立代理线路**：不再依赖当前选中的 Claude、Codex 或 Kimi。
  老版本已经保存的代理设置会自动为新线路启用一次，用户仍可随时关闭。
- **避免 GitHub 分支缓存错配**：先读取分支的精确 commit，再下载该 commit 的归档；
  API 与压缩包不会再分别指向新旧两个版本。更新报告会显示实际线路和 commit。
- **实机验证**：通过 `http://127.0.0.1:7897` 连接 GitHub，锁定 commit
  `d3751874f6be277003fed19a3a1aa2dde612d166`，下载并安全解包 88,618,886 字节、
  127 个 KI，绝对符号链接为 0。

验证结果：GeoForge 测试 **159/159 通过**。

### English

- **Proxy settings are available in the KI Library:** use `⚙ > Network & proxy`, choose the
  system route or a local HTTP/mixed proxy port, and enable “GitHub & KI updates”. The update
  report now also offers a direct Network settings button.
- **The built-in updater has its own proxy target:** it no longer borrows the currently selected
  Claude, Codex, or Kimi route. Existing saved proxy settings adopt the new target once and remain
  user-controllable.
- **Commit-pinned downloads prevent branch-cache mismatches:** GeoForge resolves the exact branch
  commit first and downloads that immutable archive. Reports include the route and source commit.
- **Real-path validation:** the configured `http://127.0.0.1:7897` route reached GitHub, pinned
  commit `d3751874f6be277003fed19a3a1aa2dde612d166`, and safely extracted 88,618,886 bytes containing
  127 KIs with zero absolute symbolic links.

Validation: **159/159 GeoForge tests passed**.

## v0.6.45 — 2026-08-27

### 中文

- **通用网络配置**：AI 设置中的同一条代理线路现在同时覆盖所选 Agent 以及 Agent
  发起的 Git、pip、curl 和模型下载。支持自动检测、手动 HTTP/SOCKS 地址和关闭代理；
  Claude、Codex、Kimi 可以分别开关，不需要代理的 provider 不受影响。
- **连接失败不再只是 `Load failed`**：DNS、VPN、代理、登录服务不可达等问题会进入
  “需要你”弹窗，告诉用户具体失败位置并允许修改线路后重试。
- **模型安装位置可选**：在 Agent 设置页选择安装目录；目录不存在时 GeoForge 会创建。
  路径同时记录到 `kiss.toml` 和 `.geoforge-install.json`，之后的聊天和预检都能找到它。
- **旧 KI 路径自动兼容**：第一次预检前自动建立当前便携 KI 布局与旧模型脚本路径之间的
  映射，减少“已经安装但 Agent 找不到”的问题。
- **127 个 KI 全量更新**：来自主分支 KI 快照
  `90a9163bd696fa6d42a471fc0c5ac2b347156d64`。VIC、CaMa-Flood 和 Lohmann Routing
  中指向私有服务器的软链接已替换为真实文件，桌面包不再依赖作者机器路径。
- **KI harness 与校准检查加强**：正式加载完整 harness 合同；校准依赖与算法后端通过
  实际 import 重新检查，不再保留过期的“未就绪”结果。
- **版本与发布记录统一**：Mac、Windows、CLI 使用同一个版本源。发布包同时提供
  `release-manifest.json`、本更新日志和 `SHA256SUMS.txt`，方便 Agent 自动判断更新内容。

验证结果：GeoForge 测试 **156/156 通过**；KI 目录 **127/127 可读取**；失效 KI 软链接 **0**。

### English

- **Universal network route:** one configurable route now covers selected AI providers and the
  Git, pip, curl, and model-download commands they launch. Auto, manual HTTP/SOCKS, and off modes
  are available, with a separate switch for Claude, Codex, and Kimi.
- **Actionable connection failures:** DNS, VPN, proxy, and sign-in service failures now open a
  specific Needs You request instead of ending as an unexplained `Load failed`.
- **Selectable model installation:** users may choose or create the model folder. GeoForge records
  it in `kiss.toml` and `.geoforge-install.json` so later chats and preflights use the same location.
- **Legacy KI layout bridge:** portable KI paths are mapped before the first preflight, preventing
  already-installed tools from being mistaken for missing files.
- **All 127 KIs refreshed:** canonical KI snapshot
  `90a9163bd696fa6d42a471fc0c5ac2b347156d64` is included. Server-only VIC, CaMa-Flood, and Lohmann
  Routing links were replaced with real portable files.
- **Harness and calibration proof:** the full KI harness contract is loaded; calibration dependencies
  and numerical backends are proved by current imports rather than a stale cached result.
- **Auditable releases:** macOS, Windows, and CLI builds share one version source. Every release ships
  this changelog, a machine-readable manifest, and checksums.

Validation: **156/156 GeoForge tests passed**, **127/127 KIs catalogued**, **0 broken KI links**.

## v0.6.44 — 2026-08-27

- Added user-selectable and persistent KI model installation locations.
- 增加用户可选、可持久保存的 KI 模型安装目录。

## v0.6.43 and earlier / 更早版本

See the Git history and the GitHub release notes for earlier beta changes.
更早的 beta 更新请查看 Git 历史和 GitHub Release 页面。
