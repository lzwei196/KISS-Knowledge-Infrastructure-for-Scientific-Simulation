# GeoForge Desktop user manual

## 0.6.55 guide edition, bundled with Windows 0.6.56 / Windows 0.6.56 内置手册

Windows [0.6.56](https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/releases/tag/windows-v0.6.56) includes the October 2 illustrated quickstarts in both the installer and portable app. The guide edition remains 0.6.55 because the documented application workflow is unchanged.

The app's **Guide / 使用指南** menu includes three offline guides, each in English and Simplified Chinese:

| Guide / 文档 | English | 简体中文 |
|---|---|---|
| Quickstart — exactly three pages / 快速上手，恰好三页 | [PDF](./0.6.55/GeoForge-Desktop-Quickstart-EN-v0.6.55.pdf) | [PDF](./0.6.55/GeoForge-Desktop-Quickstart-ZH-CN-v0.6.55.pdf) |
| Full user manual / 完整使用手册 | [PDF](./0.6.55/GeoForge-Desktop-Manual-EN-v0.6.55.pdf) | [PDF](./0.6.55/GeoForge-Desktop-Manual-ZH-CN-v0.6.55.pdf) |
| Calibration guide / 参数校准指南 | [PDF](./0.6.55/GeoForge-Desktop-Calibration-EN-v0.6.55.pdf) | [PDF](./0.6.55/GeoForge-Desktop-Calibration-ZH-CN-v0.6.55.pdf) |

The three quickstart pages cover agent setup, KI setup, and a real SHAW example using public official inputs. The full manual preserves the detailed FSM2 walkthrough and adds verified Windows SHAW, VIC and CRHM runs. The calibration guide explains model adapters, defensible train/holdout protocols and the tested native SHAW reference-recovery benchmark. Reference recovery is not field-observation validation.

三页快速指南分别介绍 Agent 配置、KI 配置及使用公开官方输入完成真实 SHAW 运行。完整手册保留详细 FSM2 实例，补充 Windows 上已验证的 SHAW、VIC 和 CRHM 运行。校准指南说明适配器、训练/留出方案及真实原生 SHAW 参考恢复测试；参考恢复不等同于实测观测验证。

See [sources, build instructions and scope](./0.6.55/README.md). Current Windows release: [`windows-v0.6.56`](https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/releases/tag/windows-v0.6.56).

## 0.6.54 (previous Windows edition)

A new A4 manual for GeoForge Desktop 0.6.54, written against the Windows build
`windows-v0.6.54` with notes for macOS, with screenshots from the real app.
It covers installation, connecting an AI, the GeoForge Database, installing a
scientific model, a complete worked example (FSM2, Alptal) from request to
**Completed**, project files, the other tools, and troubleshooting with the
known issues of 0.6.54.

- [English manual (PDF)](./0.6.54/GeoForge-Desktop-Manual-EN-v0.6.54.pdf)
- [简体中文手册（PDF）](./0.6.54/GeoForge-Desktop-Manual-ZH-CN-v0.6.54.pdf)

Source, screenshots and the build and capture tools: [0.6.54/README.md](./0.6.54/README.md).

## 0.6.54（上一 Windows 版本）

全新的 A4 手册，按 Windows 版 `windows-v0.6.54` 编写，并说明 macOS 上的差异，截图全部来自真实应用。
内容包括安装、连接 AI、GeoForge 数据库、安装科学模型、一个从提出请求到 **Completed** 的完整示例
（FSM2，Alptal）、项目文件、其他工具，以及故障排除和 0.6.54 的已知问题。

## Older editions

The complete GeoForge Desktop manual is available as an A4 PDF in three
editions. It follows one scientific-model case from project creation through
KI selection, data preparation, user handoffs, model execution, results, and
calibration.

- [English manual](./GeoForge-Desktop-Manual-EN-v0.6.47.pdf)
- [简体中文手册](./GeoForge-Desktop-Manual-ZH-CN-v0.6.47.pdf)
- [Bilingual / 中英合订版](./GeoForge-Desktop-Manual-Bilingual-v0.6.47.pdf)

These PDFs document the historical v0.6.47 interface and workflow.
They include provider-specific proxy routing, Kimi project permissions, automatic
KI updates from main, selectable model installation folders, KI Studio/KDT gates,
live agent states, dynamic Project View, calibration, and the detailed APEX case.

## GeoForge 桌面版使用手册

完整手册提供英文、简体中文和中英合订三个 A4 PDF 版本。手册通过一个
完整科学模型案例，逐步说明如何创建项目、选择 KI、准备数据、处理需要用户
参与的步骤、运行模型、查看结果以及建立校准流程。

这些 PDF 记录 v0.6.47 界面及当前 mac-version 工作流，新增了按服务商配置
代理、Kimi 项目权限、从 main 自动更新 KI、模型安装目录、KI Studio/KDT
三级门槛、实时 Agent 状态、动态项目视图、校准流程，以及完整 APEX 案例。

## v0.6.50 addendum — governed Agent runs

GeoForge now enforces the KI harness as a desktop workflow, not only as instructions in a prompt.
Start with a natural scientific goal. The Agent first identifies the intended KI, study area, period,
processes, outputs and material gaps. It then writes a data inventory and an executable plan. Downloads
and model tools stay disabled until you review and approve that plan. Each approved tool or model run is
recorded with its command, inputs, changed outputs, approval identity and validation result. Internal
`GEOFORGE_INTAKE` metadata is not shown in chat. **Environment Check** reports whether both the bundled
harness and the complete Flow runtime loaded from the installed application.

## v0.6.50 补充说明——受控 Agent 运行

GeoForge 现在把 KI harness 作为 Desktop 工作流真正执行，而不只是放进提示词。用户仍然可以
直接描述自然语言科研目标；Agent 会先识别 KI、研究区、时段、过程、输出和关键缺口，再生成
数据清单与可执行计划。只有用户审阅并批准计划后，下载和模型工具才会开放。每一次批准后的
工具或模型运行都会记录命令、输入、变化的输出、批准标识和验证结果。内部
`GEOFORGE_INTAKE` 元数据不会显示在聊天中。“环境检查”会同时报告当前 App 中的 harness
与完整 Flow 运行时是否成功加载。

## v0.6.49 addendum — KI Observatory

Open **KI Observatory** from the Chat sidebar or the KI Library header. The atlas presents the
local KI library using the 14 Earth-science domains in the KISS KI paper
([arXiv:2605.17856](https://arxiv.org/abs/2605.17856)). The first view shows only the 14 domains;
open a domain and select a KI to enter its animated scientific production line directly. Data moves
from intake through the core processing stations and verification gate into results. Long descriptions,
optional modules, and implementation helpers stay folded under **Full technical DAG**. Cross-KI
relationships are optional and hidden by default. Choose **Ask Agent** on the KI
or an individual node to create a new project chat pinned to that KI. GeoForge opens the new chat and
sends the prepared question automatically; it never inserts an Observatory question into an old chat.
The **Live project** tab reads the
selected chat's recorded Agent and run state. The default workflow uses plain scientific phases rather
than source-code identifiers. Open a phase to see its explanation; exact DAG terms are kept under
**Technical evidence** and **Full technical DAG**. Chat activity now distinguishes a live process from
confirmed tool events and growing project files, so a heartbeat alone is never described as a download
or active computation. For structured Kimi Code and Claude Code events, the status card shows the latest
redacted command, script, or file path rather than only `Bash`. Observatory views are read-only and never
execute KI code.

## v0.6.49 补充说明——KI 观测台

从聊天侧栏或 KI 库顶部进入 **KI 观测台**。星图按照 KISS KI 论文
（[arXiv:2605.17856](https://arxiv.org/abs/2605.17856)）的 14 个地球科学领域组织本地 KI。
初始页面只显示 14 个领域；进入领域并选择 KI 后，会直接进入动态科学生产线。数据从入口
流经核心处理站和验证闸门，再进入结果出口；处理站会依次点亮。长说明、可选模块和技术
辅助节点默认折叠在“完整技术 DAG”中。跨 KI 关系是默认关闭的辅助视图。点击 KI 或单个
节点的“询问 Agent”，会自动创建一个绑定当前 KI 的新项目对话、跳转并发送准备好的问题；
不会把观测台的问题塞进旧对话。“实时项目”读取所选对话已经记录的 Agent
与运行状态。默认工作流使用容易理解的科学阶段，不再把源码模块名当成主内容；点击阶段可看
解释，原始 DAG 名称保留在“技术依据”和“完整技术 DAG”中。聊天状态也会区分“进程存活”、
“真实工具事件”和“项目文件变化”，不会因为只有心跳就声称正在下载或计算。对于 Kimi Code
和 Claude Code 的结构化工具事件，状态卡会显示经过脱敏的具体命令、脚本或文件路径，而不是
只显示 `Bash`。观测台是只读界面，不会执行或导入 KI 代码。
