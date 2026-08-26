"""Small native clipboard bridge for the desktop webview.

WKWebView normally handles Cmd+C/V itself, but pywebview intentionally removes
its right-click menu and some macOS versions fail to route the keyboard action
to an HTML textarea.  The UI therefore has a same-origin fallback endpoint.
On macOS the frozen app already bundles PyObjC for WKWebView, so the bridge uses
``NSPasteboard`` directly.  This matters when a GUI launch has a restricted or
minimal shell environment: ``pbcopy``/``pbpaste`` may fail even though the
native pasteboard is available.  The commands remain a fallback for source
installs that do not include PyObjC.
"""

from __future__ import annotations

import platform
import shutil
import subprocess

MAX_CHARS = 2_000_000


def _mac_read() -> str | None:
    try:
        import AppKit
        value = AppKit.NSPasteboard.generalPasteboard().stringForType_(
            AppKit.NSPasteboardTypeString)
        return str(value or "")[:MAX_CHARS]
    except (ImportError, AttributeError, OSError):
        return None


def _mac_write(text: str) -> bool | None:
    try:
        import AppKit
        board = AppKit.NSPasteboard.generalPasteboard()
        board.clearContents()
        return bool(board.setString_forType_(text, AppKit.NSPasteboardTypeString))
    except (ImportError, AttributeError, OSError):
        return None


def read_text() -> str:
    system = platform.system()
    if system == "Darwin":
        native = _mac_read()
        if native is not None:
            return native
        cmd = ["/usr/bin/pbpaste"]
    elif system == "Linux" and shutil.which("wl-paste"):
        cmd = ["wl-paste", "--no-newline"]
    elif system == "Linux" and shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard", "-o"]
    else:
        return ""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout[:MAX_CHARS] if result.returncode == 0 else ""


def write_text(text: str) -> bool:
    text = str(text)[:MAX_CHARS]
    system = platform.system()
    if system == "Darwin":
        native = _mac_write(text)
        if native is not None:
            return native
        cmd = ["/usr/bin/pbcopy"]
    elif system == "Linux" and shutil.which("wl-copy"):
        cmd = ["wl-copy"]
    elif system == "Linux" and shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard"]
    else:
        return False
    try:
        result = subprocess.run(
            cmd, input=text, capture_output=True, text=True,
            errors="replace", timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
