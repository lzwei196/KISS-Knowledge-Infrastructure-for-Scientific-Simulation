"""Native-window mode: KISS as a desktop application.

The engine stays what it is — an HTTP server and a web UI — but the user-facing
shape changes: instead of a terminal command that opens a browser tab, this
starts the server on a loopback ephemeral port and puts the UI in a native
window (WKWebView on macOS, WebKitGTK on Linux, EdgeWebView2 on Windows) with
the app's own icon in the Dock.

Why not Electron/Tauri: the UI is one HTML file and the backend is Python.
pywebview reuses the OS's own web engine, so the whole app stays a single
PyInstaller bundle instead of shipping a browser. Why not "just the browser":
because the first thing a real user did with the binary was double-click it,
and a desktop app that opens Terminal + Safari does not read as an app.

Fallback order: native window if pywebview is importable, else the default
browser, saying which and why. The GUI itself is identical in all three cases.
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.request
from pathlib import Path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_up(url: str, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except OSError:
            time.sleep(0.2)
    return False


def run_app(models_dir: Path | None, workroot: Path | None = None) -> int:
    """Serve on an ephemeral loopback port and open a native window on it."""
    from . import gui

    port = _free_port()
    url = f"http://127.0.0.1:{port}/"

    server = threading.Thread(
        target=gui.serve,
        kwargs=dict(models_dir=models_dir, port=port, open_browser=False,
                    workroot=workroot),
        daemon=True,           # window closing ends the process, server included
    )
    server.start()
    if not _wait_up(url):
        print("kiss: the local server did not come up; run `kiss gui` for details")
        return 1

    try:
        import webview  # pywebview
    except ImportError:
        import webbrowser
        print("kiss: pywebview not bundled — opening in your browser instead")
        webbrowser.open(url)
        server.join()
        return 0

    webview.create_window("KISS", url, width=1200, height=800, min_size=(800, 560))
    webview.start()            # blocks until the window is closed
    return 0
