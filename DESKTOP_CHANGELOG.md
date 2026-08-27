# GeoForge Desktop changelog / 桌面版更新日志

This is the human-readable companion to [`release-manifest.json`](release-manifest.json).
Desktop update agents should read the JSON manifest first and use this file to explain the update.

这是 `release-manifest.json` 的用户版说明。Windows、macOS 和 Linux 的更新 Agent
应先读取 JSON，再用本文件向用户解释更新内容。

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
