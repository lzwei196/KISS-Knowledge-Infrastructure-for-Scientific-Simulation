GeoForge Desktop — 127 Earth-system models with their KISS Knowledge
Infrastructures, driven by the GeoForge agent.

## Install

Download **GeoForge-Desktop-macos-arm64.app.zip** (Apple Silicon) or
**GeoForge-Desktop-macos-x86_64.app.zip** (Intel). Everything is inside.

    unzip GeoForge-Desktop-macos-arm64.app.zip
    xattr -dr com.apple.quarantine "GeoForge Desktop.app"
    open "GeoForge Desktop.app"

Sessions on the left; describe a task and GeoForge picks the right model
(or pin models yourself). The KISS Library holds per-model setup and the
step-by-step environment checks.

## Talking to models

Uses an agent CLI you already have (claude / codex / gemini / kimi / qwen)
or an API key via ⚙ Settings (Anthropic / DeepSeek / OpenAI / OpenRouter);
pick the provider and the LLM per session.

## Also here

`kiss-macos-<arch>.tar.gz` — the KISS engine as a slim terminal command
(`list / info / doctor / init / recipe`). Linux: clone and `pip install -e kiss/`.
