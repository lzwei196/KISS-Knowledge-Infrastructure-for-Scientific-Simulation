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
    "AI CONNECTION": "AI 连接",
    "Local": "本地",
    "API": "API",
    "Skills": "技能",
    "✦ Skills": "✦ 技能",
    "Send": "发送",
    "AI connections": "AI 连接",
    "Local agent CLIs": "本地 Agent CLI",
    "Recheck local CLIs": "重新检查本地 CLI",
    "Default provider": "默认服务商",
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
    "Understand": "理解任务",
    "Prepare": "准备",
    "Validate": "验证",
    "Run": "运行",
    "Results": "结果",
    "One thing needs you": "有一件事需要你",
    "Help needed": "需要协助",
    "Open official page": "打开官方页面",
    "No action needed from you": "现在不需要你操作",
    "Project files": "项目文件",
    "Optional model reading": "可选的模型资料",
    "Add paper PDF": "添加论文 PDF",
    "Advanced details": "高级详情",
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
    "Last checked on this Mac": "本机上次检查时间",
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
    "Verified on this Mac": "已在本机验证",
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
    "Choose skills for this chat": "选择本对话使用的技能",
    "Search KIs…": "搜索 KI…",
    "Search skills…": "搜索技能…",
    "Optional note for the agent": "给 Agent 的可选说明"
    ,"Ask a scientific question or describe a modelling task…": "提出科学问题或描述一个建模任务…"
    ,"Use an installed agent or a direct API key": "使用已安装的 Agent 或直接 API 密钥"
    ,"Open this chat's local project folder in Finder": "在访达中打开本对话的本地项目文件夹"
    ,"See what GeoForge is doing in this project": "查看 GeoForge 在本项目中的工作状态"
    ,"AI used for guided setup": "用于引导式设置的 AI"
    ,"Check and import a KI package": "检查并导入 KI 软件包"
    ,"Ready to set up": "可以开始设置"
    ,"Manual setup": "需要手动设置"
    ,"Software setup needed": "需要设置软件"
    ,"Built from this KI's declarations and the files visible on this Mac—not invented by AI.": "根据该 KI 的声明和本机可见文件生成，不由 AI 猜测。"
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
    [/^(\d+)\/(\d+) verified on this Mac$/, "$1/$2 已在本机验证"],
    [/^(\d+) of (\d+) KIs · (\d+) verified here$/, "$1 / $2 个 KI · $3 个已在本机验证"],
    [/^Working · (\d+) steps?$/, "正在处理 · $1 步"],
    [/^Work details · (\d+) steps?$/, "工作详情 · $1 步"],
    [/^Project files · (\d+)$/, "项目文件 · $1"],
    [/^(\d+) \/ (\d+) software verified$/, "$1 / $2 个软件已验证"],
    [/^(\d+) files? added$/, "已添加 $1 个文件"],
    [/^(\d+) papers? added to this project$/, "已向本项目添加 $1 篇论文"],
    [/^(\d+) internal KI requirements?$/, "$1 项 KI 内部要求"],
    [/^Advanced details · (\d+) internal KI requirements?$/, "高级详情 · $1 项 KI 内部要求"],
    [/^Needed at: (.+)$/, "需要放在：$1"],
    [/^Configured for (.+)$/, "已为 $1 配置"],
    [/^General KI: (.+)$/, "通用 KI：$1"]
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
