# 1 安装与首次启动

本章带你下载 Windows GeoForge Desktop 0.6.55（macOS 说明对应 0.6.54），校验文件，在 Windows 或 macOS 上安装，第一次启动，并熟悉主界面。你还会了解 GeoForge 把文件存在哪里，以及怎样升级和卸载。

本章中 Windows 和 macOS 系统自带的按钮和菜单按中文系统写出；第一次出现时，括号里给出英文系统中的名称。

## 准备工作

| | Windows | macOS |
|---|---|---|
| 电脑 | 64 位（x64）Windows 电脑。本版本在 Windows 11 上测试过。 | Apple 芯片（M 系列）的 Mac。本版本不支持 Intel 芯片的 Mac。 |
| 要用的发布版本 | `windows-v0.6.55` | `v0.6.54` |
| 下载大小 | 以当前发布页 Assets 的准确字节数为准 | 以 macOS 发布页为准 |
| 程序占用的磁盘空间 | 约 400 MB | 几百 MB |
| 管理员权限 | 不需要 | 不需要；允许打开应用时，macOS 可能会要你输入密码 |
| 包含的内容 | 应用本身、自带的 Python，以及全部 127 个 KI | 应用本身和全部 127 个 KI |

KI（Knowledge Infrastructure，知识基础设施）是 GeoForge 为某个科学模型整理好的一套知识：怎样安装、准备、运行和检查这个模型。有了 KI，不代表你的电脑上已经有这个模型的软件。

安装 GeoForge **不会**安装任何科学模型，也不附带 AI。你要在第 2 章连接 AI，在第 4 章安装模型软件。之后安装的每个模型都要单独占用磁盘空间，常常要几个 GB。

## 选择正确的下载文件

GeoForge 发布在 GitHub 上。Windows 和 macOS 用的是**不同的发布页面**，虽然两个页面的版本号都是 0.6.54。

1. 打开与你的系统对应的发布页面：

    - **Windows：**<https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/releases/tag/windows-v0.6.55>（页面标题为 "GeoForge Desktop 0.6.55 for Windows"）。
    - **macOS：**<https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/releases/tag/v0.6.54>（页面标题为 "GeoForge Desktop v0.6.54 — macOS Apple Silicon"）。

2. 向下滚动到 **Assets**（文件列表）。如果列表是折叠的，点 **Assets** 展开。
3. 点你的系统对应的程序文件（见下面的表格），浏览器会开始下载。
4. 再点校验文件，把它也下载下来：Windows 用 `SHA256SUMS-Windows.txt`，macOS 用 `SHA256SUMS.txt`。

确认页面标题是 "GeoForge Desktop 0.6.55 for Windows"，文件名里含有 `v0.6.55-Windows-x64`。

**Windows 文件（`windows-v0.6.55`）**

| 文件 | 是什么 | 需要吗？ |
|---|---|---|
| `GeoForge-Desktop-Setup-v0.6.55-Windows-x64.exe` | 安装程序 | 需要，推荐大多数人使用 |
| `GeoForge-Desktop-v0.6.55-Windows-x64.zip` | 便携版，不用安装 | 只在你不能或不想安装软件时使用 |
| `SHA256SUMS-Windows.txt` | 上面两个文件的校验值 | 需要，用来校验下载的文件 |
| `Windows-release-validation.json`、`release-manifest.json`、`DESKTOP_CHANGELOG.md` | 测试记录和发布说明 | 不需要 |

**macOS 文件（`v0.6.54`）**

| 文件 | 是什么 | 需要吗？ |
|---|---|---|
| `GeoForge-Desktop-macos-arm64.app.zip` | 应用本身 | 需要 |
| `SHA256SUMS.txt` | 校验值 | 需要，用来校验下载的文件 |
| `kiss-macos-arm64.tar.gz` | 可选的命令行工具 | 不需要 |
| `kiss-ki-packages.tar.gz` | 单独打包的 KI | 不需要，应用里已经包含 |
| `release-manifest.json`、`DESKTOP_CHANGELOG.md` | 发布说明 | 不需要 |

> **注意：**在 Windows 上，只使用 `windows-v0.6.55` 里的文件。macOS 的 `v0.6.54` 页面上没有 Windows 文件。一些较早的发布页面也列有 Windows 文件（例如 `v0.6.52`，它的标题写的是 macOS），那些是旧 Windows 版本，不是 0.6.55。

`v0.6.54` 上的 macOS 应用构建于 2026 年 9 月 19 日。Windows 0.6.55 包含之后对规划、原生模型和校准的修复。本手册以 Windows 版为准，所以后面几章里的一些规划界面在 Mac 上可能不太一样。

## 用 SHA-256 校验下载文件

GeoForge 没有 Windows 或 Apple 认可的发布者签名，所以你的电脑没法替你担保这个文件。校验值（SHA-256）是文件的“指纹”，由 64 个字符组成：文件哪怕只改了一个字节，指纹也会变。把它和公布的值对比，就能确认文件完整、没有被改动。运行任何文件之前，先做这一步。

### 在 Windows 上

1. 打开文件资源管理器，进入下载文件所在的文件夹（通常是 **下载**（Downloads））。
2. 在文件资源管理器的地址栏里输入 `powershell`，按 Enter。PowerShell 会在这个文件夹中打开。
3. 输入与你的文件对应的命令，按 Enter：

    ```powershell
    Get-FileHash .\GeoForge-Desktop-Setup-v0.6.55-Windows-x64.exe -Algorithm SHA256
    ```

    如果是便携版，把文件名换成 `.\GeoForge-Desktop-v0.6.55-Windows-x64.zip`。

4. 用记事本打开 `SHA256SUMS-Windows.txt`。
5. 把 PowerShell 输出的 **Hash** 和文件里同一个文件名那一行对比。大小写不影响结果，但每个字符都必须一致。

确认两个 64 个字符的值完全相同。

### 在 macOS 上

1. 打开 **终端**（Terminal）（应用程序 → 实用工具 → 终端）。
2. 输入下面的命令，按 Return：

    ```bash
    shasum -a 256 ~/Downloads/GeoForge-Desktop-macos-arm64.app.zip
    ```

3. 打开 `SHA256SUMS.txt`，把输出的值和 `GeoForge-Desktop-macos-arm64.app.zip` 那一行对比。每个字符都必须一致。

### 取得当前版本的校验值

安装程序或便携压缩包必须与**同一个 `windows-v0.6.55` 发布页面**中的 `SHA256SUMS-Windows.txt` 对比。不同版本的文件具有不同哈希，不要拿当前下载与旧手册中的校验值比较。Windows 校验文件地址：

<https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/releases/download/windows-v0.6.55/SHA256SUMS-Windows.txt>

独立发布的 macOS 0.6.54 应使用其发布页面中的 `SHA256SUMS.txt`。

如果两个值不同，删除这个文件，重新下载。校验值不一致的文件不要运行。

## 在 Windows 上用安装程序安装

安装程序会把 GeoForge 装在你自己的用户文件夹里，所以不需要管理员权限。安装向导只有英文界面，下面在英文标签后面的括号里给出中文意思。

1. 双击 `GeoForge-Desktop-Setup-v0.6.55-Windows-x64.exe`。Windows 通常会弹出一个蓝色窗口：**Windows 已保护你的电脑**（Windows protected your PC）。这是 Microsoft Defender SmartScreen，Windows 用它检查下载的程序。它出现是因为安装程序没有发布者签名。只有校验值一致时才继续。
2. 点 **更多信息**（More info）。
3. 确认应用是 `GeoForge-Desktop-Setup-v0.6.55-Windows-x64.exe`，发布者是 **未知发布者**（Unknown publisher）。
4. 点 **仍要运行**（Run anyway）。

5. 在 **Select Destination Location**（选择安装位置）页面，点 **Next**（下一步），保留建议的文件夹。默认位置是 `C:\Users\you\AppData\Local\Programs\GeoForge Desktop`（也写作 `%LOCALAPPDATA%\Programs\GeoForge Desktop`）。如果想装到另一个你有写入权限的文件夹，先在框里输入路径，再点 **Next**。

    确认路径在你自己的用户文件夹里（`C:\Users\you\…`）。

6. 在 **Select Additional Tasks**（选择附加任务）页面，如果想要桌面图标，勾选 **Create a desktop shortcut**（创建桌面快捷方式）。这一项默认不勾选。
7. 点 **Next**。

8. 在 **Ready to Install**（可以安装）页面，点 **Install**（安装）。
9. 在 **Completing the GeoForge Desktop Setup Wizard**（安装完成）页面，点 **Finish**（完成）。让 **Launch GeoForge Desktop**（启动 GeoForge Desktop）保持勾选，GeoForge 就会启动。然后接着看 [Windows 首次启动](#windows-首次启动)。

以后要启动 GeoForge，打开“开始”菜单，输入 `GeoForge`，点 **GeoForge Desktop**。也可以在 **所有应用**（All apps）里的 **GeoForge Desktop** 文件夹中找到它。如果你在第 6 步勾选了那个选项，也可以用桌面快捷方式启动。

## 在 Windows 上使用便携版 zip

便携版不用安装就能运行。如果你不能安装软件，或者想先试用 GeoForge、不改动电脑上的任何东西，就用它。

1. 在文件资源管理器里，右键点 `GeoForge-Desktop-v0.6.55-Windows-x64.zip`，选 **全部解压缩…**（Extract All…）。
2. 在目标位置框里输入一个短路径，例如 `D:\GeoForge-Manual\App`。
3. 点 **提取**（Extract）。
4. 打开解压出来的文件夹 `GeoForge Desktop 0.6.55 Windows`（在 `D:\GeoForge-Manual\App` 里）。里面有 `GeoForge Desktop.exe`、`geoforge-agent-bridge.exe` 和 `_internal` 文件夹。
5. 双击 `GeoForge Desktop.exe`。如果 SmartScreen 弹出警告，和安装程序一样，先点 **更多信息**，再点 **仍要运行**。

确认 `GeoForge Desktop.exe` 和 `_internal` 在同一个文件夹里。

> **注意：**先把整个 zip 解压出来。不要在 zip 窗口里直接启动应用，也不要把 `GeoForge Desktop.exe` 从 `_internal` 旁边移走；程序需要这个文件夹里的每一个文件。想要桌面图标，可以右键点 `GeoForge Desktop.exe` → **发送到**（Send to）→ **桌面快捷方式**（Desktop (create shortcut)）（Windows 11 要先点 **显示更多选项**（Show more options））。

便携版和安装版使用同样的设置和项目文件夹（见 [GeoForge 把文件放在哪里](#geoforge-把文件放在哪里)）。不要同时运行两者。

## 在 macOS 上安装

1. 在 **下载**（Downloads）文件夹里双击 `GeoForge-Desktop-macos-arm64.app.zip`。访达会解压出 `GeoForge Desktop.app`。
2. 把 `GeoForge Desktop.app` 拖到 **应用程序**（Applications）文件夹。

这个应用没有经过 Apple 公证（也就是 Apple 没有检查和批准过它），所以 macOS 会阻止它第一次打开。用下面两种方法中的任一种允许一次即可。

### 用终端允许应用打开

这是发布说明里给出的方法。

1. 打开 **终端**（应用程序 → 实用工具 → 终端）。
2. 运行这条命令：

    ```bash
    xattr -dr com.apple.quarantine "/Applications/GeoForge Desktop.app"
    ```

3. 从 **应用程序** 打开 **GeoForge Desktop**。然后接着看 [macOS 首次启动](#macos-首次启动)。

### 不用终端允许应用打开

1. 在 **应用程序** 里双击 **GeoForge Desktop**。macOS 会提示无法验证这个应用。
2. 点 **完成**（Done）（较旧的 macOS 上是 **好**（OK））。不要点 **移到废纸篓**（Move to Trash）。

3. 打开 **系统设置**（System Settings）→ **隐私与安全性**（Privacy & Security）。
4. 向下滚动到“安全性”部分，找到“GeoForge Desktop”已被阻止的提示。

5. 点 **仍要打开**（Open Anyway）。
6. macOS 询问时，再点一次 **仍要打开**，并输入你的密码。GeoForge 会打开。然后接着看 [macOS 首次启动](#macos-首次启动)。

每次更新后都要重新允许一次，因为每个新版本都是一次新的下载。macOS 也可能再次询问能否访问 **文稿**、**桌面** 或 **下载** 文件夹。把项目放在这些文件夹和 iCloud 之外，可以减少这类询问。

## Windows 首次启动

在 Windows 上，GeoForge 没有自己的窗口。它启动后会运行一个小型本地服务器（只向你自己的电脑提供页面的程序），并在你的**默认浏览器**里显示页面。屏幕右下角的通知区域（系统托盘）里也会出现一个 GeoForge 图标。

1. 启动 GeoForge（安装程序完成页面、“开始”菜单、桌面快捷方式，或便携版文件夹里的 `GeoForge Desktop.exe`）。
2. 等几秒钟。浏览器会打开一个标题为 **GeoForge 桌面版** 的标签页（界面为英文时显示 GeoForge Desktop），地址类似 `http://127.0.0.1:52814/`。这个标签页**就是**应用本身。
3. 找到托盘图标。如果看不到，点时钟旁边的 **^** 箭头。鼠标停在图标上会显示 "GeoForge Desktop — double-click to open"（双击打开）。
4. 可选：把图标从 **^** 区域拖到任务栏上，让它一直显示。

确认菜单里正好有两项：**Open GeoForge**（打开 GeoForge）和 **Exit GeoForge**（退出 GeoForge）。

确认地址以 `http://127.0.0.1:` 开头，侧栏显示 **需要设置 AI**。此时出现这两条横幅是正常的（见 [第一个界面上的提示](#第一个界面上的提示)）。

### 打开、关闭和退出

| 你的操作 | 结果 |
|---|---|
| 关闭浏览器标签页或浏览器 | GeoForge 继续在托盘里运行。正在进行的工作（Agent、下载、模型运行）会继续。 |
| 双击托盘图标，或右键点它 → **Open GeoForge** | GeoForge 页面会在浏览器里重新打开。 |
| 右键点托盘图标 → **Exit GeoForge** | GeoForge 先停止它启动的所有工作（Agent、下载、校准，以及它们启动的模型或编译器），然后退出。正在进行的模型运行会被中断。 |
| GeoForge 正在运行时，又从“开始”菜单启动一次 | 会启动**第二个实例**，托盘里出现第二个图标，地址也不同。请避免这样做：两个实例共用同样的设置和项目。要重新打开页面，用托盘图标。 |

一定要用 **Exit GeoForge** 退出，不要用任务管理器结束，这样正在运行的工作才能正常停止。托盘菜单只有英文。

> **注意：**0.6.54 的已知问题：AI Agent 通过 Git Bash（Claude Code 等 Agent 在 Windows 上使用的命令窗口）在后台启动的长时间任务，在 **Exit GeoForge** 之后可能还在运行。如果你在长时间运行中途退出后，电脑还是很忙，打开任务管理器（Ctrl+Shift+Esc），结束残留的模型或编译器程序。

### 每次启动都会变化的内容

- **地址会变。** `127.0.0.1:` 后面的数字每次启动都不一样。不要把它加入书签，请用托盘图标打开。上一次启动留下的旧标签页会失效，关掉即可。
- **部分偏好设置会重置。** 浏览器把每个新地址都当成一个新网站。界面语言会回到浏览器的语言，主题（**◐**）会回到系统的浅色或深色设置，**本地** | **API** 开关会回到 **本地**。如果你只用 API 密钥（例如 DeepSeek），在新对话里发第一条消息之前，先在 **AI 连接** 下点 **API**。见第 8 章“语言、外观和键盘”。

你的对话、项目、API 密钥和 **设置** 由 GeoForge 自己保存，所以不会丢失。

## macOS 首次启动

- GeoForge 会在自己的窗口中打开，窗口标题为 **GeoForge Desktop**，程序坞里有它的图标。主界面的布局和 Windows 上一样。
- **关闭窗口就会退出 GeoForge**，和 **退出**（Quit，Command-Q）效果一样。正在运行的 Agent、软件设置或模型运行都会停止。长时间安装和运行期间，请保持窗口打开，或者把它最小化。
- 每次启动时，Mac 版会检查官方 KI 库，右下角可能会出现一个小提示（例如 **KI 库检查完成**）。点 **关闭** 即可关掉它。第 7 章介绍 KI 更新。
- 和 Windows 一样，语言、主题以及 **本地** | **API** 的选择在每次启动时都可能重置（第 8 章）。

## 第一个界面上的提示

在你连接 AI 之前，起始界面会显示两个提示。新安装的 GeoForge 出现这两个提示都是正常的：

- 侧栏顶部 **GeoForge** 旁边显示 **需要设置 AI**。
- 起始界面上方有一条横幅：**Connect an AI to begin.**（连接 AI 后即可开始）"Open AI Settings to add a key or configure a local agent."（打开 AI 设置，添加密钥或配置本地 Agent）。这条横幅在中文界面里也显示为英文。横幅里写的是 "AI Settings"，但你要点的是侧栏底部的 **设置** 按钮。

起始界面上方可能还会出现第二条提示，内容取决于 **AI 连接** 下的 **本地** | **API** 开关。**本地** 指本地 Agent：已经安装在这台电脑上并登录好的 AI 命令行程序，例如 Claude Code 或 Codex。**API** 指 AI 服务商提供的密钥，例如 DeepSeek 的密钥。

这些提示在中文界面里大部分也是英文，只有 "AI 设置" 几个字显示为中文。

| 提示 | 含义 |
|---|---|
| "No local agent CLI is installed. Open AI 设置 for setup details."，带 **Recheck**（重新检查）按钮 | 选的是 **本地**，但这台电脑上没有安装本地 Agent 程序。 |
| "Local CLIs are installed but not ready — …"，带 **Recheck** 按钮 | 选的是 **本地**。已经安装了 Agent 程序，但还没登录，或者需要更新。提示里会写出是哪个程序。 |
| "No API connection yet. Open AI 设置 and add a key." | 选的是 **API**，但还没有保存任何 API 密钥。 |

所选的一侧有一个可用的 AI 后，这些提示就会消失。如果你只用 API 密钥，先添加密钥（第 2 章），再点 **API**。

连接 AI 后，侧栏会显示例如 **1 个 AI 已就绪**，**Connect an AI to begin.** 横幅也会消失。具体做法见第 2 章“连接 AI”。

## 主界面导览

这是你最常用的界面。下图中已经连接了四个 AI，并新建了一个还没有消息的对话（Alptal snow example），所以中间是空的。没有打开对话时中间显示什么，见下文“中间区域”。

![GeoForge 主界面：左侧为侧栏，顶部为“自动选择 KI”和“AI 连接”，中间是一个还没有消息的新对话，底部为消息框](../../images/zh-CN/01-home.png)

确认侧栏显示 **N 个 AI 已就绪**（这里是 **4 个 AI 已就绪**），并且 **AI 连接** 显示的是你预期的服务商和模型（这里是 **API**、**DeepSeek (API)** 和 **deepseek-chat**）。

### 侧栏（左侧）

| 控件 | 作用 |
|---|---|
| **GeoForge** 和 **N 个 AI 已就绪** / **需要设置 AI** | 显示有几个 AI 连接可以使用。 |
| **＋ 新建对话** | 开始一个新的项目对话。会弹出 **新建项目对话** 对话框，让你填写项目名称和文件夹（第 6 章）。 |
| 对话列表 | 你的对话，位于 **＋ 新建对话** 下方（一开始是空的）。每个对话就是一个项目，有自己的文件夹。鼠标停在对话上会出现 **✕**，确认后会归档这个对话：项目文件夹会移到它旁边的 `_archived` 文件夹里，不会删除任何内容。 |
| **KI 观测台**、**KI 库**、**KI 工作室** | 打开 GeoForge 的其他页面（第 7 章）。要返回，用页面左上角的箭头或浏览器的“后退”按钮。在 **KI 工作室** 里，这个箭头会回到 **KI 库**。 |
| **使用指南** | 打开 **GeoForge 如何工作**，用三步概括基本用法，带有 **打开 KI 库** 按钮。本手册的内容要详细得多。 |
| **设置** | 打开“设置”窗口：**AI 服务**、**GeoForge 数据库**、**网络与代理**、**权限**（第 2 章和第 3 章）。 |
| **English** | 把界面切换为英文并重新加载页面。在英文界面中，同一个按钮显示为 **简体中文**。 |
| **◐** | 在浅色和深色之间切换。 |

### 顶栏

| 控件 | 作用 |
|---|---|
| 标题 | 对话的名称；没有打开对话时显示 **GeoForge 桌面版**。 |
| **自动选择 KI**（带 **KI** 标记） | 为这个对话选择 KI（也就是模型）。**自动选择 KI** 表示由 GeoForge 为每个任务自己选（第 4 章）。对话发出第一条消息后就不能再改。 |
| 状态标签 | 使用自动选择 KI 时显示 **按任务自动选择**。指定了 KI 时，显示这个模型的软件是否已在本机验证。 |
| **▣ 文件夹** | 在文件资源管理器（macOS 上是访达）中打开这个对话的项目文件夹。 |
| **◇ 项目状态** | 显示 GeoForge 在这个项目里正在做什么，以及需要你做什么（第 6 章）。 |
| **▤ 项目视图** | 打开这个对话的结果面板（第 6 章）。 |
| **AI 连接**：**本地** \| **API**、服务商列表、模型列表 | 为新对话选择 AI：先选本地 Agent 程序还是 API 密钥，再选服务商和模型。对话发出第一条消息后就固定了（第 2 章）。 |

**▣ 文件夹**、**◇ 项目状态** 和 **▤ 项目视图** 在打开对话之前是灰色的。

### 中间区域

没有打开对话时，中间显示 **你想模拟什么？** 和五张起始卡片：

| 卡片 | 打开的内容 |
|---|---|
| **开始对话** | 把光标放到消息框里。 |
| **选择 KI** | KI 选择窗口，用来为这个对话指定模型。 |
| **浏览并验证** | **KI 库**。 |
| **观察 KI** | **KI 观测台**。 |
| **创建 KI** | **KI 工作室**。 |

打开对话后，中间显示对话内容。

### 消息区（底部）

| 控件 | 作用 |
|---|---|
| **＋ 文件** | 给下一条消息附加文件。 |
| **✦ 技能** | 为这个对话选择额外的技能。 |
| 消息框（“提出科学问题或描述一个建模任务…”） | 在这里输入。按 Enter 发送；按 Shift+Enter 换行。 |
| **发送** | 发送消息。所选 AI 就绪之前，这个按钮是灰色的。 |

> **提示：**界面是英文时，如果你发送的消息里有中文，界面会自动切换为中文。想换回英文，点侧栏里的 **English**。

## GeoForge 把文件放在哪里

默认情况下，GeoForge 把你的项目放在程序文件夹之外。所以更新或卸载程序都不会动到你的工作。

| 内容 | Windows | macOS |
|---|---|---|
| 程序 | `%LOCALAPPDATA%\Programs\GeoForge Desktop`（或你解压便携版 zip 的文件夹） | `/Applications/GeoForge Desktop.app` |
| 设置：API 密钥、代理、默认 AI | `%APPDATA%\KISS\settings.json` | `~/Library/Application Support/KISS/settings.json` |
| 其他应用数据：KI 更新（`ki-updates`）、你导入的 KI（`user_models`）、数据库目录副本（`database`）、KI 工作室的工作内容（`ki-studio`） | `%APPDATA%\KISS\` | `~/Library/Application Support/KISS/` |
| GeoForge 数据库激活 Token | Windows 凭据管理器 → **Windows 凭据** → 普通凭据 → `com.geoforge.desktop:observation-activation-token` | `~/Library/Application Support/KISS/secrets/` 下的一个私有文件 |
| 工作文件夹：项目和模型安装 | `C:\Users\you\kiss` | `~/kiss` |

`%APPDATA%` 就是 `C:\Users\you\AppData\Roaming`，`%LOCALAPPDATA%` 就是 `C:\Users\you\AppData\Local`。这两个都可以直接输入到文件资源管理器的地址栏里。

工作文件夹（`C:\Users\you\kiss` 或 `~/kiss`）里有：

| 名称 | 内容 |
|---|---|
| `projects\` | 每个对话一个文件夹，命名为 `<date>-<project name>--<id>`，例如 `2026-10-01-Alptal-snow-example--<id>`。归档的对话在 `projects\_archived\` 里。 |
| 每个已安装的模型一个文件夹，名称为小写 | 每个模型的默认安装位置，例如 `C:\Users\you\kiss\fsm2`。 |
| `_install-locations.json` | 记录你装到其他文件夹的模型。 |
| `sessions\` 和其他小文件夹 | GeoForge 自己的记录，包括你在其他位置创建的项目在哪里。不要改动它们。 |

你可以在别的位置创建项目（在 **新建项目对话** 对话框里），也可以把模型装到别的文件夹（在 **Agent 设置** 页面上）。GeoForge 会记下这些位置，以后还能找到。在 Windows 上，请选不含空格的短路径，例如 `D:\GeoForge-Manual\models\fsm2`，并放在还有几个 GB 剩余空间的磁盘上。不要用 OneDrive 和 iCloud 文件夹。

> **注意：**`settings.json` 以未加密的明文保存你的 API 密钥。它在你自己的用户文件夹里，但用你的账户运行的其他程序，以及这台电脑的管理员，都能读取它。不要分享、同步或发送这个文件及其所在的文件夹。

> **提示：**以下内容仅供高级用户参考：应用里没有移动整个工作文件夹的设置。你可以新建一个快捷方式，目标设为 `"C:\Users\you\AppData\Local\Programs\GeoForge Desktop\GeoForge Desktop.exe" app --workroot D:\GeoForge-Manual\work`。用这个快捷方式启动时，默认工作文件夹里的对话不会出现在侧栏中；它们的文件仍留在磁盘上。

## 升级 GeoForge

升级时，你的项目、对话、模型安装、API 密钥、代理设置、默认 AI 和数据库 Token 都会保留，不需要移动任何东西。

> **提示：**如果你之前在中文 Windows 上用过较旧的 Windows 版本，遇到过规划卡片缺失、运行记录保存失败，或者用户名是中文时 AI Agent 无法启动，请升级到 0.6.54。这个版本已经修复了这些问题。

### Windows 安装版

1. 等正在运行的工作结束，或者接受它会被停止。
2. 右键点托盘图标 → **Exit GeoForge**。
3. 下载新的安装程序，并校验 SHA-256（见 [用 SHA-256 校验下载文件](#用-sha-256-校验下载文件)）。
4. 运行新的安装程序。它会装到同一个文件夹，所以可能会跳过选择文件夹的页面。
5. 让 **Launch GeoForge Desktop** 保持勾选，点 **Finish**。

如果安装程序显示 **Preparing to Install**（正在准备安装）页面，并在占用文件的应用里列出 GeoForge，说明 GeoForge 还在运行。先从托盘退出它，再点 **Next**。

### Windows 便携版

1. 右键点托盘图标 → **Exit GeoForge**。
2. 把新的 zip 解压到一个**新**文件夹。
3. 启动新的 `GeoForge Desktop.exe`。
4. 确认新版本能正常使用后，删除旧文件夹。你的数据不在里面。

### macOS

1. 关闭 GeoForge 窗口，退出应用。
2. 解压新下载的文件。
3. 把新的 `GeoForge Desktop.app` 拖到 **应用程序** 文件夹。
4. 访达询问时，点 **替换**（Replace）。
5. 按 [在 macOS 上安装](#在-macos-上安装) 中的方法，再次允许新应用打开。

## 卸载 GeoForge

### Windows 安装版

1. 右键点托盘图标 → **Exit GeoForge**。
2. 打开 Windows **设置**（Settings）→ **应用**（Apps）→ **安装的应用**（Installed apps）（Windows 10 上是 **应用和功能**（Apps & features））。
3. 在列表里找到 **GeoForge Desktop 0.6.54**。
4. 点它旁边的 **…**（Windows 10 上直接点这一项）。
5. 选 **卸载**（Uninstall）。
6. 在接下来的对话框中确认卸载。

### Windows 便携版

1. 右键点托盘图标 → **Exit GeoForge**。
2. 删除解压出来的文件夹。

### macOS

1. 关闭 GeoForge 窗口，退出应用。
2. 把 `GeoForge Desktop.app` 从 **应用程序** 拖到废纸篓。

### 卸载后保留的内容

卸载只会删除程序本身。下面这些内容会一直留在你的电脑上，直到你自己删除。

| 保留的内容 | Windows | macOS | 什么情况下可以删除 |
|---|---|---|---|
| 设置和 API 密钥 | `%APPDATA%\KISS` | `~/Library/Application Support/KISS` | 你想清除密钥和设置 |
| 所有项目和已安装的模型 | `C:\Users\you\kiss` | `~/kiss` | 你不再需要任何结果或模型安装 |
| 放在你自选文件夹里的项目和模型 | 你放的位置 | 你放的位置 | 同上 |
| 数据库 Token | 凭据管理器中的条目 `com.geoforge.desktop:observation-activation-token` | 在 `~/Library/Application Support/KISS` 里 | 你想清除这个 Token |

> **注意：**删除工作文件夹（`C:\Users\you\kiss` 或 `~/kiss`）会永久删除其中的所有项目、结果和已安装的模型。请先把需要的结果复制出来。这一操作无法撤销。

在 macOS 上，可以在访达中选 **前往**（Go）→ **前往文件夹…**（Go to Folder…）（Shift-Command-G），输入 `~/Library/Application Support/KISS`，打开 `Library` 下的这个文件夹。

## 如果出了问题

| 你看到的情况 | 处理方法 |
|---|---|
| 浏览器提示这个文件“通常不会被下载”，或者拦下了下载 | 这是浏览器对未签名文件的检查。选择保留文件（在 Edge 中：**…** → **保留**（Keep），然后 **显示更多**（Show more）→ **仍然保留**（Keep anyway））。然后校验 SHA-256。 |
| SHA-256 不一致 | 删除这个文件，从发布页面重新下载。不要运行它。 |
| SmartScreen 里没有 **仍要运行** 按钮 | 先点 **更多信息**。如果还是没有这个按钮，说明你的单位禁止运行未知应用，请联系 IT 支持人员。 |
| Windows 提示 **智能应用控制**（Smart App Control）阻止了这个应用 | Windows 对此不提供绕过的办法。是否关闭智能应用控制，是你或你单位的 IT 支持人员要做的安全决定。 |
| 启动 GeoForge 后好像没有反应（Windows） | 等 10–20 秒。找托盘图标（点 **^**），双击它。检查托盘之前不要再次启动 GeoForge，否则会出现第二个实例。 |
| 页面提示无法访问此网站 | 这个标签页属于上一次启动，或者 GeoForge 已经退出。关掉这个标签页。启动 GeoForge，或双击它的托盘图标，然后使用新打开的标签页。 |
| **GeoForge could not start.**（GeoForge 无法启动，这句显示为英文），带 **重新加载** 按钮 | 点 **重新加载**。如果再次出现，用托盘 → **Exit GeoForge** 退出，再启动一次 GeoForge。 |
| 托盘里有两个 GeoForge 图标 | GeoForge 被启动了两次。分别右键点每个图标 → **Exit GeoForge**，然后只启动一次。 |
| 语言、主题或 **本地** \| **API** 的选择变回去了 | 重启后出现这种情况是正常的，因为本地地址变了。重新设置即可。见第 8 章。 |
| **Connect an AI to begin.** | 连接 AI 之前出现这条提示是正常的。见第 2 章。 |
| 你用的是 API 密钥，却看到 "No local agent CLI is installed." | 在 **AI 连接** 下点 **API**。 |
| 在 Mac 上，**下载** 文件夹里的 `.zip` 不见了，只剩 `GeoForge Desktop.app` | Safari 已经替你解压了，所以没法再校验 zip。换一个浏览器重新下载，或者先在 Safari 设置里关闭 **下载后打开“安全的”文件**（Open "safe" files after downloading），再重新下载。 |
| macOS 提示无法打开这个应用，或者说它已损坏 | 运行 [用终端允许应用打开](#用终端允许应用打开) 中的 `xattr` 命令，然后再打开应用。 |
| 在 macOS 上，正在进行的软件设置或模型运行停止了 | 关闭 GeoForge 窗口会退出应用，并停止它正在做的工作。重新打开 GeoForge，在同一个对话中继续。 |
| 卸载后程序文件夹还在 | 手动删除 `%LOCALAPPDATA%\Programs\GeoForge Desktop`。你的项目不在里面。 |

其他问题见第 9 章“故障排除与已知问题”。
