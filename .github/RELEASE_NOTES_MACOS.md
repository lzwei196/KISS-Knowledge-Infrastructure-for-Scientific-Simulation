kiss — install and drive the 127 KISS model KIs from a desktop app.

## The app (recommended)

Download **KISS-macos-arm64.app.zip** (Apple Silicon) or
**KISS-macos-x86_64.app.zip** (Intel), plus **kiss-ki-packages.tar.gz**:

    unzip KISS-macos-arm64.app.zip
    tar xzf kiss-ki-packages.tar.gz          # models/ next to KISS.app
    xattr -dr com.apple.quarantine KISS.app  # unsigned; macOS quarantines downloads
    open KISS.app

KISS opens in its own window with a Dock icon — no terminal, no browser.

## The CLI

`kiss-macos-<arch>.tar.gz` is the same engine as a terminal command:
`./kiss-macos-arm64 gui` (browser UI), plus `list / info / doctor / init /
recipe` for scripting.

## Talking to models

Chat uses an agent CLI you already have (claude / codex / gemini / kimi /
qwen) or an API key (ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY /
OPENROUTER_API_KEY). The app lists your options if it finds neither.

Linux: clone the repo and `pip install -e kiss/`.
