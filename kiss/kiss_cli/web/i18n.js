/* GeoForge's small, dependency-free UI locale layer.
 *
 * Scientific names, paths, commands, model output, and chat bubbles are left
 * untouched.  This file translates only the application chrome.  New DOM
 * fragments are handled by the observer because most of the UI is rendered by
 * the page's JavaScript after startup.
 */
(() => {
  "use strict";

  const ZH = {
    "New chat": "新建对话",
    "＋ New chat": "＋ 新建对话",
    "KI Library": "KI 库",
    "KI updates": "KI 更新",
    "View automatic KI update report": "查看自动 KI 更新报告",
    "KI library updates": "KI 库更新",
    "Checking update status…": "正在检查更新状态……",
    "GeoForge updates only KI definitions and their install manifests from the official repository. It does not change chat projects, input data, installed model binaries, verification history, or KIs you imported yourself. A downloaded snapshot becomes active only after deterministic package checks pass.": "GeoForge 只会从官方仓库更新 KI 定义及其安装清单，不会修改对话项目、输入数据、已安装的模型程序、验证记录或你自己导入的 KI。下载的快照只有通过确定性软件包检查后才会启用。",
    "Check again": "再次检查",
    "Open source repository": "打开源码仓库",
    "View report": "查看报告",
    "Dismiss": "关闭",
    "KI Studio": "KI 工作室",
    "Create a KI for your own model": "为你自己的模型或工作流创建 KI",
    "New KI workspace": "新建 KI 工作区",
    "What are you turning into a KI?": "你希望把什么转换成 KI？",
    "Process-based model": "过程模型",
    "A simulator such as CRHM, APEX or DSSAT": "例如 CRHM、APEX 或 DSSAT 这样的模拟器",
    "Task or workflow": "任务或工作流",
    "A repeatable preparation, analysis or plotting procedure": "可重复的数据准备、分析或绘图流程",
    "Name": "名称",
    "Scientific domain": "科学领域",
    "Other — enter your own": "其他 — 自行输入",
    "e.g. GIS, ecology, materials science": "例如：GIS、生态学、材料科学",
    "Use the repository root, not a GitHub file or folder page.": "请使用仓库根地址，不要使用 GitHub 的单个文件或子文件夹页面。",
    "Source": "来源",
    "Public Git repository": "公开 Git 仓库",
    "Local source folder": "本地源码文件夹",
    "Workspace parent folder": "工作区父文件夹",
    "AI agent": "AI Agent",
    "Agent model": "Agent 模型",
    "Agent for the next build or repair": "下一次构建或修复使用的 Agent",
    "You can switch providers between build or repair passes. The selected provider is saved with this workspace.": "每次构建或修复之间都可以切换服务商；所选服务商会保存在这个工作区中。",
    "Create workspace": "创建工作区",
    "KI creation run": "KI 创建流程",
    "process model": "过程模型",
    "task workflow": "任务工作流",
    "Connections": "连接",
    "⌁ Connections": "⌁ 连接",
    "Guide": "使用指南",
    "AI Settings": "AI 设置",
    "GeoForge Desktop": "GeoForge 桌面版",
    "Auto KI": "自动选择 KI",
    "Chooses for each task": "按任务自动选择",
    "Folder": "文件夹",
    "▣ Folder": "▣ 文件夹",
    "Project status": "项目状态",
    "Project view": "项目视图",
    "Build or update with Agent": "让 Agent 创建或更新",
    "Open project folder": "打开项目文件夹",
    "Refresh": "刷新",
    "AI CONNECTION": "AI 连接",
    "Local": "本地",
    "API": "API",
    "Skills": "技能",
    "✦ Skills": "✦ 技能",
    "Files": "文件",
    "＋ Files": "＋ 文件",
    "Add files or drag them here": "添加文件，或将文件拖到这里",
    "Remove from this message; the file remains in the project": "从本条消息移除；文件仍保留在项目中",
    "Send": "发送",
    "Choose how to continue": "选择如何继续",
    "Select one option so GeoForge can continue.": "选择一项后，GeoForge 就可以继续。",
    "Continue with this choice": "按此选择继续",
    "Ask about these choices": "询问这些选项",
    "Not now": "暂不处理",
    "Choose one option first.": "请先选择一项。",
    "Return to the chat that asked this question.": "请返回提出此问题的对话。",
    "Add context only if needed…": "仅在需要时补充说明…",
    "AI connections": "AI 连接",
    "Local agent CLIs": "本地 Agent CLI",
    "Recheck local CLIs": "重新检查本地 CLI",
    "Default provider": "默认服务商",
    "AI network proxy": "AI 网络代理",
    "Use Mac system proxy (recommended)": "使用 Mac 系统代理（推荐）",
    "Enter proxy manually": "手动输入代理",
    "Do not use a proxy": "不使用代理",
    "GeoForge passes this proxy only to the providers selected below.": "GeoForge 只会把代理传给下方选中的服务。",
    "Test AI connection": "测试 AI 连接",
    "Use proxy for": "以下服务使用代理",
    "Claude Code and Codex are enabled by default. Kimi and DeepSeek use their normal connection unless you enable them.": "默认只为 Claude Code 和 Codex 启用代理。Kimi 和 DeepSeek 默认使用自身的普通连接，除非你在这里启用。",
    "Kimi Code file access": "Kimi Code 文件访问权限",
    "Project scoped (recommended)": "仅限项目范围（推荐）",
    "Full computer access": "完整电脑访问权限",
    "Project scoped lets Kimi use this project, its KI, approved data, and its own login state. Other personal files are blocked by macOS.": "项目范围模式允许 Kimi 使用当前项目、KI、已批准的数据及其自身登录状态；macOS 会阻止其访问其他个人文件。",
    "Kimi can read and change any file your macOS account can access. Use this only for a task that cannot run in project-scoped mode.": "Kimi 可以读取和修改你的 macOS 账户能够访问的任何文件。仅当任务无法在项目范围模式下运行时才使用此选项。",
    "handled in each project": "在每个项目中处理",
    "Anthropic API key": "Anthropic API 密钥",
    "DeepSeek API key": "DeepSeek API 密钥",
    "OpenAI API key": "OpenAI API 密钥",
    "OpenRouter API key": "OpenRouter API 密钥",
    "Save": "保存",
    "Close": "关闭",
    "Apply": "应用",
    "Clear": "清除",
    "Use Auto KI": "使用自动 KI",
    "Knowledge Infrastructures for this chat": "本对话使用的知识基础设施",
    "Skills for this chat": "本对话使用的技能",
    "MCP connections": "MCP 连接",
    "How GeoForge works": "GeoForge 如何工作",
    "Chat first. KIs provide the scientific capability.": "先聊天。KI 提供科学能力。",
    "Describe the task": "描述任务",
    "Start with the scientific question, not software setup.": "从科学问题开始，不必先处理软件安装。",
    "Use Auto KI or choose one": "自动选择或指定一个 KI",
    "GeoForge announces which KI it uses and whether it is verified here.": "GeoForge 会说明正在使用哪个 KI，以及它是否已在本机验证。",
    "Let the agent set it up": "让 Agent 完成设置",
    "The agent uses the KI and KDT diagnostics until preflight passes, pausing only when it genuinely needs you.": "Agent 会使用 KI 和 KDT 诊断持续修复，直到预检通过；只有确实需要你时才会暂停。",
    "Open KI Library": "打开 KI 库",
    "Continue in chat": "在对话中继续",
    "Add source data": "添加源数据",
    "What would you like to model?": "你想模拟什么？",
    "Describe the scientific task. GeoForge can choose a KI automatically, or you can pin one for this chat.": "描述你的科学任务。GeoForge 可以自动选择 KI，也可以为本对话指定一个。",
    "Start chatting": "开始对话",
    "Ask a question or describe a simulation.": "提出问题或描述一个模拟任务。",
    "Choose a KI": "选择 KI",
    "Pin scientific software to this chat.": "为本对话指定科学软件。",
    "Browse & verify": "浏览并验证",
    "Import KIs and check what can run.": "导入 KI，并检查哪些可在本机运行。",
    "Create a KI": "创建 KI",
    "Turn your own model workflow into a checked KI.": "把你自己的模型工作流转换成经过检查的 KI。",
    "You": "你",
    "Copy": "复制",
    "Copied": "已复制",
    "Copy failed": "复制失败",
    "Working": "正在处理",
    "Needs you": "需要你",
    "Complete": "已完成",
    "Needs attention": "需要处理",
    "Ready": "就绪",
    "Project progress": "项目进度",
    "Goal": "目标",
    "Ready to continue": "可以继续",
    "Ready when you are": "随时可以开始",
    "GeoForge is working": "GeoForge 正在处理",
    "Project complete": "项目已完成",
    "Project needs attention": "项目需要处理",
    "Understand": "理解任务",
    "Prepare": "准备",
    "Validate": "验证",
    "Run": "运行",
    "Results": "结果",
    "Understand the goal and choose a general KI": "理解目标并选择合适的通用 KI",
    "Check software and prepare suitable data": "检查软件并准备适合的数据",
    "Check the prepared model inputs": "检查已准备的模型输入",
    "Run the real scientific model": "运行真实的科学模型",
    "Save and explain the results": "保存并解释结果",
    "Data for this run": "本次运行的数据",
    "Data sources & download record": "数据来源与下载记录",
    "What the agent downloaded, copied, or reused—and the record that makes it reproducible.": "Agent 下载、复制或复用的数据，以及用于复现的记录。",
    "Recorded": "已记录",
    "Recorded data source": "已记录的数据来源",
    "Open public source ↗": "打开公开来源 ↗",
    "Downloaded from a public source repository": "从公开源代码仓库下载",
    "Downloaded from a public data API": "从公开数据 API 下载",
    "Reused a checksum-verified reference archive": "复用了经过校验和验证的参考数据档案",
    "Copied from the installed KI reference data": "从已安装 KI 的参考数据复制",
    "Saved by the agent for reproducibility": "由 Agent 保存以便复现",
    "Saved for reproducibility": "已保存用于复现",
    "Installed KI reference data": "已安装 KI 的参考数据",
    "A simple view of what the model needs. GeoForge handles the technical fields and asks only when a real decision or private file is missing.": "这里只显示模型需要的数据类别。技术字段由 GeoForge 处理；只有确实缺少决定或私有文件时才会询问你。",
    "Ready to use": "已经就绪",
    "Being checked": "正在检查",
    "Agent is preparing": "Agent 正在准备",
    "Agent will prepare": "Agent 将会准备",
    "Review needed": "需要检查",
    "Not ready": "尚未就绪",
    "Present": "已找到",
    "Optional": "可选",
    "Path not configured": "尚未配置路径",
    "Checked data paths": "已检查的数据路径",
    "These marks come from real paths declared by the KI setup manifest, not from an AI guess.": "这些标记来自 KI 设置清单声明的真实路径，并非 AI 猜测。",
    "The data groups will appear after a KI is selected.": "选择 KI 后会显示数据类别。",
    "Model data appears after the conversation chooses a KI.": "对话选择 KI 后，这里会显示该模型的数据。",
    "Data categories are rebuilt from the active KI as the conversation changes.": "数据类别会随着对话中的当前 KI 动态重建。",
    "Open all inputs": "打开全部输入",
    "Open folder": "打开文件夹",
    "No local files in this category yet.": "这个类别目前还没有本地文件。",
    "Could not open data folder": "无法打开数据文件夹",
    "Only confirmed gaps appear as “Needs you.” The complete KI data contract is still available below.": "只有已经确认的缺口才会显示“需要你”。完整的 KI 数据合同仍保留在下方。",
    "Resolve with agent": "让 Agent 解决",
    "Prepare with agent": "让 Agent 准备",
    "Find with agent": "让 Agent 查找",
    "Decide with agent": "与 Agent 一起决定",
    "Source data": "源数据",
    "Spatial & grid parameters": "空间与网格参数",
    "Model choices & calibration": "模型选择与校准",
    "Initial & boundary conditions": "初始与边界条件",
    "Weather, observations, maps, and other raw material. Add your own data or let the agent help find a suitable source.": "天气、观测、地图和其他原始资料。可以添加自己的数据，也可以让 Agent 寻找合适来源。",
    "Values that must be prepared for cells, layers, reaches, basins, or other spatial units. The agent builds these from source data.": "网格、分层、河段、流域等空间单元所需的参数，由 Agent 根据源数据构建。",
    "Scientific choices, defaults, and calibration values. GeoForge asks only for decisions it cannot safely make.": "科学选择、默认值和校准参数。GeoForge 只询问无法安全代替你决定的事项。",
    "The state at the beginning and edges of the simulation. Defaults can be used when the KI allows them.": "模拟开始时及边界处的状态；KI 允许时可使用默认值。",
    "One thing needs you": "有一件事需要你",
    "Help needed": "需要协助",
    "Open official page": "打开官方页面",
    "No action needed from you": "现在不需要你操作",
    "Keep working in chat. GeoForge will interrupt only for an important decision, private data, a login, licence, or system permission.": "继续在对话中操作即可。只有遇到重要决定、私有数据、登录、许可证或系统权限时，GeoForge 才会请你处理。",
    "Calibration": "模型校准",
    "Choose a KI first": "请先选择 KI",
    "Engine unavailable": "校准引擎不可用",
    "Adapter needed": "需要校准适配器",
    "Holdout passed": "留出验证已通过",
    "Holdout not passed": "留出验证未通过",
    "Run needs review": "本次运行需要检查",
    "Ready when needed": "需要时可以开始",
    "Calibrate with agent": "让 Agent 校准",
    "Continue calibration": "继续校准",
    "Add observations": "添加观测数据",
    "Validated": "已验证",
    "Not promoted": "未通过推广门槛",
    "No KI selected yet": "尚未选择 KI",
    "GeoForge uses the real KI model, keeps observations and runs in this project, and accepts a result only after held-out validation.": "GeoForge 会运行真实的 KI 模型，把观测数据和校准记录保存在本项目中；只有通过独立留出验证后才接受结果。",
    "Choose a model in chat. GeoForge will then connect its calibration adapter when one is available.": "请先在对话中选择模型；如果该 KI 有校准适配器，GeoForge 会自动连接。",
    "This build cannot load the shared calibration engine. The agent can inspect the problem, but must not claim that optimization ran.": "当前版本无法加载共享校准引擎。Agent 可以检查问题，但不能声称优化已经运行。",
    "The model is selected, but its project calibration adapter still needs to be prepared.": "模型已经选择，但仍需准备本项目的校准适配器。",
    "The latest real-model calibration passed its held-out validation gate.": "最近一次真实模型校准已经通过独立留出验证。",
    "The latest attempt is saved, but GeoForge does not treat it as a validated calibration.": "最近一次尝试已经保存，但 GeoForge 不会把它视为已验证的校准结果。",
    "Calibration is available for this model. Start it only when observations and a scientific goal require it.": "该模型支持校准。只有科学目标和观测数据确实需要时才开始。",
    "Project files": "项目文件",
    "Optional model reading": "可选的模型资料",
    "Add paper PDF": "添加论文 PDF",
    "Advanced details": "高级详情",
    "See technical data details": "查看技术数据明细",
    "Search KIs…": "搜索 KI…",
    "Search skills…": "搜索技能…",
    "Browse all installed skills": "浏览所有已安装技能",
    "No matching skills found.": "没有找到匹配的技能。",
    "No MCP servers are configured for the local agents yet.": "本地 Agent 尚未配置 MCP 服务器。",
    "GitHub MCP": "GitHub MCP",
    "Configure for Codex": "为 Codex 配置",
    "Official setup guide": "官方设置指南",
    "Settings": "设置",
    "Check & Import": "检查并导入",
    "Create KI": "创建 KI",
    "Create a KI from your own model": "从你自己的模型创建 KI",
    "Back to KI Library": "返回 KI 库",
    "Create a KI for your own model": "为你自己的模型或工作流创建 KI",
    "Give GeoForge a model source. KDT maps the code, your chosen agent builds the KI, and a deterministic gate checks the package before it can enter the KI Library.": "把模型或工作流源码交给 GeoForge。KDT 会分析代码，你选择的 Agent 会构建 KI；只有通过确定性验收的软件包才能进入 KI 库。",
    "Checking KDT…": "正在检查 KDT…",
    "New KI workspace": "新建 KI 工作区",
    "Reviewed KDT engine": "经过审计的 KDT 引擎",
    "Checking the local engine…": "正在检查本地引擎…",
    "KDT is installed from its own repository and is not redistributed inside GeoForge. The upstream repository does not currently declare a licence.": "KDT 会从它自己的仓库安装，不会重新打包进 GeoForge。上游仓库目前没有声明许可证。",
    "Install KDT engine": "安装 KDT 引擎",
    "Model name": "模型名称",
    "Scientific domain": "科学领域",
    "Model source": "模型源码",
    "Public Git repository": "公开 Git 仓库",
    "Local source folder": "本地源码文件夹",
    "Choose folder": "选择文件夹",
    "Workspace parent folder": "工作区上级文件夹",
    "GeoForge creates a new self-contained folder here; it never edits the original source.": "GeoForge 会在这里新建独立文件夹，绝不会修改原始源码。",
    "AI agent": "AI Agent",
    "Agent model": "Agent 模型",
    "Create workspace": "创建工作区",
    "KI creation run": "KI 创建流程",
    "Map the model source": "分析模型源码",
    "KDT reads the source, build system, documentation and input/output paths.": "KDT 会读取源码、构建系统、文档以及输入输出路径。",
    "Run KDT probe": "运行 KDT 探测",
    "Build with your agent": "使用 Agent 构建",
    "The agent uses the KDT contract to author tools, docs, diagnostics, DAG and preflight.": "Agent 会依据 KDT 合同创建工具、文档、诊断、DAG 和预检。",
    "Build KI": "构建 KI",
    "Run the acceptance gate": "运行验收门禁",
    "KDT checks structure and consistency. Unknown generated code is not executed here.": "KDT 会检查结构与一致性；这里不会执行尚未信任的生成代码。",
    "Verify again": "再次验证",
    "Add to KI Library": "添加到 KI 库",
    "GeoForge runs its own package doctor, then imports the unchanged accepted candidate.": "GeoForge 会运行自己的软件包检查，再导入未经修改且已通过验收的候选 KI。",
    "Import KI": "导入 KI",
    "Your KI workspaces": "你的 KI 工作区",
    "No KI workspaces yet.": "还没有 KI 工作区。",
    "What “accepted” means": "“已接受”是什么意思",
    "Accepted package:": "已接受的软件包：",
    "KDT's file and consistency gate passed.": "已经通过 KDT 文件与一致性门禁。",
    "Imported KI:": "已导入的 KI：",
    "GeoForge's package checks passed and it is visible in the library.": "已经通过 GeoForge 软件包检查，并显示在 KI 库中。",
    "Verified software:": "已验证的软件：",
    "later, the Setup Agent runs the KI's real preflight on this Mac. Creating a KI does not pretend the scientific model already runs.": "之后，设置 Agent 会在这台 Mac 上运行 KI 的真实预检。创建 KI 并不代表科学模型已经可以运行。",
    "Open folder": "打开文件夹",
    "Knowledge Infrastructures": "知识基础设施",
    "Browse, import, and verify KIs": "浏览、导入并验证 KI",
    "Software setup & verification": "软件设置与验证",
    "Check AI connection": "检查 AI 连接",
    "KI package check": "KI 软件包检查",
    "Import valid KI": "导入有效 KI",
    "Cancel": "取消",
    "Run data": "运行数据",
    "Inputs": "输入",
    "Outputs": "输出",
    "Coupled KIs": "耦合 KI",
    "Declared input groups": "已声明的输入组",
    "Need this in simple words?": "需要更简单的说明吗？",
    "Explain my data": "说明我的数据",
    "Connect AI first": "请先连接 AI",
    "Scientific software": "科学软件",
    "Last checked on this machine": "本机上次检查时间",
    "Language & licence": "语言与许可证",
    "Source": "来源",
    "Open project website": "打开项目网站",
    "Use in a new chat": "在新对话中使用",
    "Set up with agent": "使用 Agent 设置",
    "Open setup & verification": "打开设置与验证",
    "Not yet": "尚未检查",
    "Not declared": "未声明",
    "Setup needed": "需要设置",
    "Verification failed": "验证失败",
    "Verified on this machine": "已在本机验证",
    "Bundled KI": "内置 KI",
    "Valid imported package": "有效的已导入软件包",
    "Package not checked": "软件包尚未检查",
    "Agent setup": "Agent 设置",
    "Loading…": "正在加载…",
    "Checking": "正在检查",
    "Setup agent": "设置 Agent",
    "Start agent setup": "开始 Agent 设置",
    "Continue agent": "继续 Agent",
    "Re-check with agent": "让 Agent 重新检查",
    "Use KI in chat": "在对话中使用 KI",
    "Needs you now": "现在需要你",
    "None": "无",
    "Verification": "验证",
    "How this works": "工作方式",
    "Open the official page ↗": "打开官方页面 ↗",
    "Give file to agent": "把文件交给 Agent",
    "I've done this — continue": "我已完成 — 继续",
    "I can't do this — help me": "我无法完成 — 帮帮我",
    "Action needed": "需要操作",
    "Continue repair": "继续修复",
    "Ask what went wrong": "询问哪里出了问题",
    "Ready to resume": "可以继续",
    "No action needed": "无需操作",
    "The software passed its check.": "软件已通过检查。",
    "Files supplied": "已提供的文件",
    "Not checked yet. The agent will run the KI preflight.": "尚未检查。Agent 将运行 KI 预检。",
    "No KI selected": "未选择 KI",
    "Agent default": "Agent 默认设置",
    "CLI default": "CLI 默认设置",
    "Available": "可用",
    "Ready": "就绪",
    "Installed": "已安装",
    "saved": "已保存",
    "error": "错误",
    "checking…": "正在检查…",
    "checked": "检查完成",
    "could not recheck": "无法重新检查",
    "running…": "正在运行…",
    "Explaining": "正在说明",
    "Explain again": "再次说明",
    "reading project status…": "正在读取项目状态…",
    "uploading…": "正在上传…",
    "adding paper…": "正在添加论文…",
    "working…": "正在处理…",
    "This chat is still working. The data request is in the composer and can be sent when it finishes.": "本对话仍在处理。数据请求已放入输入框，本轮完成后即可发送。",
    "This chat is working. Add the files to a new chat, or wait for this turn to finish.": "本对话正在处理。请将文件添加到新对话，或等待本轮完成。",
    "This chat stopped. You can retry the message or check AI Settings.": "本对话已停止。你可以重试消息或检查 AI 设置。",
    "(no output)": "（没有输出）",
    "(first usable)": "（第一个可用连接）",
    "(none)": "（无）",
    "default": "默认",
    "theme": "主题",
    "Toggle theme": "切换主题",
    "Back to chat": "返回对话",
    "Back to KI Library": "返回 KI 库",
    "Settings": "设置",
    "AI provider": "AI 服务商",
    "AI model": "AI 模型",
    "Fixed for this chat — start a new chat to switch AI": "本对话已锁定 AI，请新建对话后更换",
    "Fixed for this chat — start a new chat to switch model": "本对话已锁定模型，请新建对话后更换",
    "the agent and model are fixed once a chat has started — start a new chat to use a different one": "对话开始后 AI 与模型即已锁定，如需更换请新建对话",
    "Choose skills for this chat": "选择本对话使用的技能",
    "Search KIs…": "搜索 KI…",
    "Search skills…": "搜索技能…",
    "Optional note for the agent": "给 Agent 的可选说明"
    ,"New project chat": "新建项目对话"
    ,"Each chat has its own project folder for memory, inputs, model runs, outputs, and plots.": "每个对话都有独立的项目文件夹，用来保存记忆、输入、模型运行、输出和图表。"
    ,"Create the project inside": "在此位置创建项目"
    ,"Choose…": "选择…"
    ,"GeoForge creates a new named folder inside this location. Existing files are not changed.": "GeoForge 会在这里新建一个项目文件夹，不会更改已有文件。"
    ,"Create chat": "创建对话"
    ,"Use default location": "使用默认位置"
    ,"Choose or enter a folder.": "请选择或输入一个文件夹。"
    ,"Browser mode: type the folder path here. The desktop build opens the system folder picker.": "当前在浏览器模式。请直接输入文件夹路径；桌面版会打开系统文件夹选择器。"
    ,"Could not open the folder picker; enter the path directly.": "无法打开文件夹选择器，请直接输入路径。"
    ,"Ask a scientific question or describe a modelling task…": "提出科学问题或描述一个建模任务…"
    ,"Use an installed agent or a direct API key": "使用已安装的 Agent 或直接 API 密钥"
    ,"Open this chat's local project folder in Finder": "在访达中打开本对话的本地项目文件夹"
    ,"See what GeoForge is doing in this project": "查看 GeoForge 在本项目中的工作状态"
    ,"AI used for guided setup": "用于引导式设置的 AI"
    ,"Check and import a KI package": "检查并导入 KI 软件包"
    ,"Ready to set up": "可以开始设置"
    ,"Manual setup": "需要手动设置"
    ,"Software setup needed": "需要设置软件"
    ,"Built from this KI's declarations and the files visible on this machine—not invented by AI.": "根据该 KI 的声明和本机可见文件生成，不由 AI 猜测。"
    ,"Forcing": "驱动数据"
    ,"Parameters": "参数"
    ,"Initial conditions": "初始条件"
    ,"Boundary & controls": "边界与控制"
    ,"Local data check": "本地数据检查"
    ,"Dataset locations not declared": "尚未声明数据集位置"
    ,"Local files are not machine-checkable yet.": "本地文件暂时无法自动检查。"
    ,"This KI has no dataset paths in its setup manifest. The declared input groups below still show the model interface, but GeoForge will not guess whether your files satisfy it.": "该 KI 的设置清单中没有数据集路径。下方声明的输入组仍会显示模型接口，但 GeoForge 不会猜测你的文件是否满足要求。"
    ,"Time-changing drivers such as weather or inflow": "随时间变化的驱动数据，例如天气或入流"
    ,"Properties that describe the site or system": "描述地点或系统的属性"
    ,"The model state at the start of a run": "模型开始运行时的状态"
    ,"Run window, edges, controls, and management": "运行时段、边界、控制和管理条件"
    ,"Declared model inputs": "模型声明的输入"
    ,"None declared": "未声明"
    ,"The selected AI can explain this exact plan and the next missing step. It cannot change the requirements or verification marks.": "所选 AI 可以解释这份确定的计划和下一项缺失步骤，但不能更改要求或验证结果。"
    ,"Local files are not machine-checkable yet. This KI has no dataset paths in its setup manifest. The declared input groups below still show the model interface, but GeoForge will not guess whether your files satisfy it.": "本地文件暂时无法自动检查。该 KI 的设置清单中没有数据集路径。下方仍会显示模型接口，但 GeoForge 不会猜测你的文件是否满足要求。"
    ,"Dataset locations not declared": "尚未声明数据集位置"
    ,"Not checked": "尚未检查"
    ,"Review inputs": "检查输入"
    ,"Declared input groups": "已声明的输入组"
    ,"Open": "打开"
    ,"Agent working": "Agent 正在工作"
    ,"The agent's work will appear here. It may build software for several minutes.": "Agent 的工作会显示在这里。软件构建可能需要几分钟。"
    ,"The agent will pause here only for something it cannot safely complete itself.": "只有遇到无法安全自行完成的操作时，Agent 才会在这里暂停。"
    ,"The agent reads the KI before touching the software.": "Agent 会先读取 KI，再处理软件。"
    ,"It tries, checks the actual error, repairs, and retries.": "它会尝试运行、检查真实错误、修复并重试。"
    ,"Licence gates, protected downloads, login, and system privileges come back to you here.": "许可证限制、受保护下载、登录和系统权限会在这里交给你处理。"
    ,"“Verified” appears only after the KI's real preflight passes.": "只有 KI 的真实预检通过后，才会显示“已验证”。"
    ,"The agent reads this KI and its KDT diagnostics, installs inside the model workspace, checks the real software, and repairs failures until it passes or needs you.": "Agent 会读取该 KI 及其 KDT 诊断，在模型工作区内安装，检查真实软件，并持续修复，直到通过或确实需要你。"
    ,"Nothing is waiting on you. The agent can continue working autonomously.": "目前没有需要你处理的事项。Agent 可以继续自主工作。"
  };

  const PATTERNS = [
    [/^(\d+) AI ready$/, "$1 个 AI 已就绪"],
    [/^AI setup needed$/, "需要设置 AI"],
    [/^(\d+) messages?$/, "$1 条消息"],
    [/^(\d+) skills?$/, "$1 个技能"],
    [/^(\d+) KIs$/, "$1 个 KI"],
    [/^(\d+) verified$/, "$1 个已验证"],
    [/^(\d+)\/(\d+) verified on this machine$/, "$1/$2 已在本机验证"],
    [/^(\d+) of (\d+) KIs · (\d+) verified here$/, "$1 / $2 个 KI · $3 个已在本机验证"],
    [/^Working · (\d+) steps?$/, "正在处理 · $1 步"],
    [/^Work details · (\d+) steps?$/, "工作详情 · $1 步"],
    [/^Project files · (\d+)$/, "项目文件 · $1"],
    [/^(\d+) \/ (\d+) software verified$/, "$1 / $2 个软件已验证"],
    [/^(\d+) files? added$/, "已添加 $1 个文件"],
    [/^(\d+) recorded$/, "已记录 $1 项"],
    [/^Version or commit: (.+)$/, "版本或提交：$1"],
    [/^Audit record: (.+)$/, "审计记录：$1"],
    [/^(\d+) files? ready to send$/, "$1 个文件可以发送"],
    [/^Uploading (\d+) files?…$/, "正在上传 $1 个文件…"],
    [/^(\d+) papers? added to this project$/, "已向本项目添加 $1 篇论文"],
    [/^(\d+) internal KI requirements?$/, "$1 项 KI 内部要求"],
    [/^Advanced details · (\d+) internal KI requirements?$/, "高级详情 · $1 项 KI 内部要求"],
    [/^Full KI contract · (\d+) declared fields and files\. These details are for audit, reproducibility, and debugging; the agent handles them during normal use\.$/, "完整 KI 数据合同 · $1 个字段和文件。这些明细用于审计、复现和调试；正常使用时由 Agent 处理。"],
    [/^(\d+) local source file is available\.$/, "已有 $1 个本地源文件。"],
    [/^(\d+) local source files are available\.$/, "已有 $1 个本地源文件。"],
    [/^(\d+) \/ (\d+) required data paths are ready\.$/, "$1 / $2 个必需数据路径已经就绪。"],
    [/^(\d+) not ready yet$/, "还有 $1 项尚未就绪"],
    [/^Checked data paths · (\d+)$/, "已检查的数据路径 · $1"],
    [/^(.+) · Optional$/, "$1 · 可选"],
    [/^Needed at: (.+)$/, "需要放在：$1"],
    [/^Configured for (.+)$/, "已为 $1 配置"],
    [/^General KI: (.+)$/, "通用 KI：$1"]
    ,[/^(\d+) ready adapters? · (\d+) case files? · (\d+) runs?$/, "$1 个可用适配器 · $2 个案例文件 · $3 次运行"]
    ,[/^Latest calibration · (.+)$/, "最近一次校准 · $1"]
    ,[/^(.+) · adapter ready$/, "$1 · 适配器就绪"]
    ,[/^(.+) · adapter needed$/, "$1 · 需要适配器"]
    ,[/^Report: (.+)$/, "报告：$1"]
    ,[/^(.+) — not installed$/, "$1 — 未安装"]
    ,[/^(.+) — update needed$/, "$1 — 需要更新"]
    ,[/^(.+) — sign-in needed$/, "$1 — 需要登录"]
    ,[/^(.+) — check needed$/, "$1 — 需要检查"]
    ,[/^(.+) — unavailable$/, "$1 — 不可用"]
    ,[/^(.+) — needs setup$/, "$1 — 需要设置"]
    ,[/^(\d+) declared$/, "已声明 $1 项"]
    ,[/^(\d+) items? · open$/, "$1 项 · 展开"]
    ,[/^\+(\d+) more$/, "另有 $1 项"]
    ,[/^Local data check · (.+)$/, "本地数据检查 · $1"]
  ];

  const normalize = value => String(value || "").toLowerCase().startsWith("zh") ? "zh-CN" : "en";
  let language = normalize(localStorage.getItem("kiss.lang") || navigator.language || "en");
  let scheduled = false;

  function translate(value) {
    if (language !== "zh-CN") return value;
    const match = String(value).match(/^(\s*)([\s\S]*?)(\s*)$/);
    if (!match || !match[2]) return value;
    let core = match[2];
    core = ZH[core] || core;
    if (core === match[2]) {
      for (const [pattern, replacement] of PATTERNS) {
        if (pattern.test(core)) { core = core.replace(pattern, replacement); break; }
      }
    }
    return match[1] + core + match[3];
  }

  function ignored(node) {
    const parent = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    return !parent || !!parent.closest("script,style,pre,code,textarea,.bubble,.log,[data-i18n-ignore]");
  }

  function apply(root = document) {
    document.documentElement.lang = language === "zh-CN" ? "zh-CN" : "en";
    if (language === "zh-CN") {
      if (root.nodeType === Node.TEXT_NODE && !ignored(root)) {
        const next = translate(root.nodeValue);
        if (next !== root.nodeValue) root.nodeValue = next;
      }
      else {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) if (!ignored(node)) {
          const next = translate(node.nodeValue);
          if (next !== node.nodeValue) node.nodeValue = next;
        }
        const elements = root.querySelectorAll ? [root, ...root.querySelectorAll("[placeholder],[title],[aria-label]")] : [];
        for (const el of elements) {
          if (!el.getAttribute || el.closest("script,style,pre,code,.bubble,.log,[data-i18n-ignore]")) continue;
          for (const attr of ["placeholder", "title", "aria-label"]) {
            if (el.hasAttribute(attr)) {
              const current = el.getAttribute(attr), next = translate(current);
              if (next !== current) el.setAttribute(attr, next);
            }
          }
        }
      }
    }
    document.querySelectorAll("[data-language-toggle]").forEach(button => {
      const label = language === "zh-CN" ? "English" : "简体中文";
      const title = language === "zh-CN" ? "Switch to English" : "切换到简体中文";
      if (button.textContent !== label) button.textContent = label;
      if (button.title !== title) button.title = title;
    });
    document.querySelectorAll(".emptylog").forEach(node => {
      const next = translate(node.textContent);
      if (next !== node.textContent) node.textContent = next;
    });
  }

  function schedule() {
    if (scheduled || language !== "zh-CN") return;
    scheduled = true;
    // One render commonly inserts dozens of sibling nodes. Translating only
    // the first mutation's node left the rest of that newly-rendered panel in
    // English, so coalesce the batch and apply to the whole small document.
    queueMicrotask(() => { scheduled = false; apply(document); });
  }

  function setLanguage(next, options = {}) {
    const normalized = normalize(next);
    if (normalized === language) return;
    language = normalized;
    localStorage.setItem("kiss.lang", language);
    if (options.reload) location.reload();
    else {
      apply(document);
      window.dispatchEvent(new CustomEvent("geoforge:language", {detail: {language}}));
    }
  }

  function bind() {
    document.querySelectorAll("[data-language-toggle]").forEach(button => {
      if (button.dataset.languageBound) return;
      button.dataset.languageBound = "1";
      button.addEventListener("click", () => setLanguage(language === "zh-CN" ? "en" : "zh-CN", {reload: true}));
    });
    apply(document);
    new MutationObserver(records => {
      for (const record of records) {
        if (record.type === "characterData") schedule();
        else if (record.addedNodes.length) schedule();
      }
      bindTogglesOnly();
    }).observe(document.body, {childList: true, subtree: true, characterData: true});
  }

  function bindTogglesOnly() {
    document.querySelectorAll("[data-language-toggle]").forEach(button => {
      if (button.dataset.languageBound) return;
      button.dataset.languageBound = "1";
      button.addEventListener("click", () => setLanguage(language === "zh-CN" ? "en" : "zh-CN", {reload: true}));
    });
  }

  window.GeoForgeI18n = {
    apply,
    get language() { return language; },
    isChineseText: text => /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/.test(String(text || "")),
    setLanguage,
    t: (english, fallback) => language === "zh-CN" ? (ZH[english] || fallback || translate(english)) : english
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind, {once: true});
  else bind();
})();
