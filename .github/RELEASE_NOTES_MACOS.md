GeoForge Desktop — 127 Earth-system models with their KISS Knowledge
Infrastructures, driven by the GeoForge agent.

## What is new in v0.6.25

- Every KI input requirement can now be opened independently. Each item shows
  its purpose, unit, format, source, destination, preparation method, defaults,
  valid range, and evidence on disk.
- Every input item has a read-only “Ask Agent: what is this?” action and a
  separate action for asking the agent to prepare, find, or decide that item.
- Setup requests now appear immediately while an agent is still working.
  Claude, Codex, Kimi, and API tool events are reduced to readable progress
  instead of exposing raw `GEOF_TOOL` markers.
- Downloaded build runtimes inside a model's own workspace—such as APSIM's
  local .NET SDK—receive model-scoped execution permission. No global Claude
  permission edit is needed.
- Permission cards show one clear action with expandable technical details;
  they no longer show an irrelevant file upload control.
- Includes the complete project-folder, dynamic-data, calibration, bilingual
  interface, file attachment, and inline-result work from the 0.6.24 source.

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
