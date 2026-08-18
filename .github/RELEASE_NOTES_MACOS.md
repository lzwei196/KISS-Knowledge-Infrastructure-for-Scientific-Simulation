kiss — install and drive the 127 KISS model KIs from a local app.

**macOS**: download the tarball for your chip, then:

    tar xzf kiss-macos-arm64.tar.gz         # Apple Silicon (M1/M2/M3/M4)
    tar xzf kiss-macos-x86_64.tar.gz        # Intel
    xattr -d com.apple.quarantine kiss-macos-*   # unsigned binary; macOS quarantines downloads
    tar xzf kiss-ki-packages.tar.gz         # the 127 KI packages
    ./kiss-macos-arm64 --models models gui

Then pick a model, install it, and chat — using an agent CLI you already have
(claude / codex / gemini / kimi / qwen) or an API key (ANTHROPIC_API_KEY /
DEEPSEEK_API_KEY / OPENAI_API_KEY / OPENROUTER_API_KEY).

Linux users: clone the repo and `pip install -e kiss/`.

Path-relocation sandboxing (bubblewrap) is Linux-only; on macOS the app runs
without it — installs write real paths, so nothing depends on it.
