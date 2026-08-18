KISS — the 127 model Knowledge Infrastructures as a desktop app.

## Install

Download **KISS-macos-arm64.app.zip** (Apple Silicon) or
**KISS-macos-x86_64.app.zip** (Intel). Everything is inside — the app, the
127 KI packages, the shared library. No other downloads.

    unzip KISS-macos-arm64.app.zip
    xattr -dr com.apple.quarantine KISS.app   # unsigned; macOS quarantines downloads
    open KISS.app

KISS opens in its own window with a Dock icon. Pick a model, install it, chat.

## Talking to models

Chat uses an agent CLI you already have (claude / codex / gemini / kimi /
qwen) or an API key (ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY /
OPENROUTER_API_KEY). The app lists your options if it finds neither.

## Also here

`kiss-macos-<arch>.tar.gz` — the same engine as a slim terminal command for
scripting (`list / info / doctor / init / recipe`); point it at a models/
directory. `kiss-ki-packages.tar.gz` — the KI content on its own, for the CLI
or for Linux (`pip install -e kiss/`).
