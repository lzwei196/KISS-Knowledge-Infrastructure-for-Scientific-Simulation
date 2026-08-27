GeoForge Desktop — 127 Earth-system models with their KISS Knowledge
Infrastructures, driven by the GeoForge agent.

## What is new in v0.6.45

- One configurable network route now covers the selected AI provider and the
  Git, pip, curl, and model-download commands its Agent launches. Auto, manual
  HTTP/SOCKS, and off modes can be enabled separately for Claude, Codex, and Kimi.
- Provider DNS, VPN, proxy, and sign-in failures now create a clear Needs You
  request instead of an unexplained `Load failed`.
- Users can choose or create each model installation folder. GeoForge records
  the path in both `kiss.toml` and `.geoforge-install.json`.
- The complete KI library was refreshed from canonical revision
  `90a9163bd696fa6d42a471fc0c5ac2b347156d64`; all 127 packages catalogue and
  server-only VIC, CaMa-Flood, and Lohmann Routing links are now portable files.
- The full KI harness contract is import-checked. Calibration dependencies and
  numerical backends are checked from current imports, not a stale cached state.
- macOS, Windows, and CLI packages use one version source. See
  `release-manifest.json` for the machine-readable update contract and
  `DESKTOP_CHANGELOG.md` for bilingual details.

Validation: 156/156 GeoForge tests passed, 127/127 KIs catalogued, and no broken
KI symbolic links remain.

## Install

**macOS** (Apple Silicon — M1 through M4)

    unzip GeoForge-Desktop-macos-arm64.app.zip
    xattr -dr com.apple.quarantine "GeoForge Desktop.app"
    open "GeoForge Desktop.app"

The `xattr` line is required: the build is not signed by Apple, and without it
macOS refuses to open the app.

**Windows** (Intel or AMD, 64-bit)

Unzip `GeoForge-Desktop-windows-x86_64.zip` and double-click
`GeoForge Desktop.exe`. SmartScreen will warn that the publisher is unknown —
**More info** then **Run anyway**. Same cause as the macOS step above.

**Linux** (Intel or AMD, 64-bit, glibc 2.35+)

    tar xzf GeoForge-Desktop-linux-x86_64.tar.gz
    ./GeoForge-Desktop

The UI opens in your default browser rather than its own window: pywebview's
Linux backend needs WebKit2GTK from the system and cannot be frozen into a
portable binary. Same engine, same interface.

Everything is inside the download — all 127 KI packages, the engine, the UI.
No Python installation and no first-run network access.

## Talking to models

Uses an agent CLI you already have (claude / codex / gemini / kimi / qwen) or
an API key via ⚙ Settings (Anthropic / DeepSeek / OpenAI / OpenRouter). Switch
between the two with the CLI / API button in the menu bar; provider and model
are per session.

## Also here

`kiss-<platform>` — the engine as a terminal command (`list`, `info`, `init`,
`verify`, `papers`, `doctor`). `kiss-ki-packages.tar.gz` is the KI content on
its own, for running from source; the desktop downloads already contain it.

## Not in this release

Intel Macs (x86_64) — GitHub's Intel runners have been unavailable for hours
at a time, so that build is best-effort and the release ships without it
rather than waiting. Linux and Windows on ARM are not built. Build from source
for either: `pip install -e kiss/`.
