"""Adopt the user's login-shell environment.

A macOS app launched from Finder or the Dock does not inherit the user's shell
environment. launchd hands it PATH=/usr/bin:/bin:/usr/sbin:/sbin — so every
agent CLI the user has installed (Homebrew's /opt/homebrew/bin, npm's prefix,
~/.local/bin) is invisible, and so are API keys exported in ~/.zshrc. The
symptom that surfaced this: a Mac with all five agent CLIs installed, and the
app showing "no agent CLI found".

The terminal and the app disagree about the world because only one of them ran
the shell's startup files. The fix is the one editors use (VS Code calls it
shell environment resolution): run the user's login shell once, ask it for its
environment, and adopt what we lack.

Adoption is additive — nothing already set in our environment is overridden,
so an explicitly-passed variable still wins over a shell default.
"""

from __future__ import annotations

import os
import platform
import subprocess

_done = False

#: Fallback bin dirs appended even if the shell probe fails — the usual homes
#: of node-based CLIs and pipx installs.
_KNOWN_BINDIRS = (
    "/opt/homebrew/bin", "/usr/local/bin",
    "~/.local/bin", "~/bin", "~/.npm-global/bin",
    "~/.volta/bin", "~/.bun/bin", "~/.deno/bin",
)


def adopt() -> None:
    """Merge the login shell's environment into ours. Idempotent, best-effort."""
    global _done
    if _done:
        return
    _done = True

    shell = os.environ.get("SHELL") or ("/bin/zsh" if platform.system() == "Darwin"
                                        else "/bin/bash")
    try:
        # -l runs the login startup files (~/.zprofile, ~/.zshrc via zsh's
        # login+interactive chain differs per shell — -lic would be fuller but
        # interactive shells can hang on prompts, so login-only is the safe cut).
        out = subprocess.run(
            [shell, "-l", "-c", "env"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""

    shell_env: dict[str, str] = {}
    for line in out.splitlines():
        k, sep, v = line.partition("=")
        if sep and k and not k.startswith("BASH_FUNC"):
            shell_env[k] = v

    # PATH merges; everything else fills gaps only.
    merged = list(dict.fromkeys(
        (shell_env.get("PATH", "").split(os.pathsep) if shell_env.get("PATH") else [])
        + os.environ.get("PATH", "").split(os.pathsep)
        + [os.path.expanduser(d) for d in _KNOWN_BINDIRS]
    ))
    os.environ["PATH"] = os.pathsep.join(p for p in merged if p)

    for k, v in shell_env.items():
        if k not in os.environ and k != "PATH":
            os.environ[k] = v
