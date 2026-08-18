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


def _ensure_models(models_dir: Path | None):
    """Resolve the KI packages, downloading them on first run if needed.

    Returns (models_dir, error_text). Never raises: a windowed app has no
    stderr anyone can see, so every failure has to end up in the window.
    """
    from . import firstrun
    from .catalog import Catalog

    if models_dir is not None:
        return models_dir, None
    try:
        Catalog.discover()
        return None, None            # discover() will find it again in serve()
    except FileNotFoundError:
        pass
    if firstrun.models_present():
        return firstrun.models_present(), None
    try:
        return firstrun.download_ki(), None
    except Exception as e:
        return None, (f"KISS could not set itself up: {e}\n\n"
                      f"Manual fix: download kiss-ki-packages.tar.gz from the "
                      f"GitHub release and extract it into {firstrun.data_dir()}")


def run_app(models_dir: Path | None, workroot: Path | None = None) -> int:
    """Serve on an ephemeral loopback port and open a native window on it."""
    from . import firstrun, gui

    try:
        import webview
    except ImportError:
        webview = None

    # First-run bootstrap. With a window available the download happens behind
    # the setup screen; without one it happens in the terminal, with prints.
    if webview is not None and models_dir is None:
        need = False
        try:
            from .catalog import Catalog
            Catalog.discover()
        except FileNotFoundError:
            need = firstrun.models_present() is None
        if need:
            win = webview.create_window("KISS", html=firstrun.SETUP_HTML,
                                        width=520, height=340)

            def _bootstrap():
                def note(stage, frac):
                    pct = f"{frac:.0%}" if frac >= 0 else "…"
                    win.evaluate_js(
                        f"document.getElementById('pct').textContent={pct!r}")
                try:
                    firstrun.download_ki(note)
                except Exception as e:
                    win.evaluate_js(
                        "document.querySelector('.ring').style.display='none';"
                        f"document.getElementById('msg').textContent={str(e)!r}")
                    return
                win.destroy()

            import threading as _th
            _th.Thread(target=_bootstrap, daemon=True).start()
            webview.start()          # returns when the setup window closes

    resolved, err = _ensure_models(models_dir)
    if err:
        if webview is not None:
            w = webview.create_window("KISS", html=firstrun.SETUP_HTML.replace(
                "Setting up KISS — downloading the 127 model packages "
                '<span id="pct"></span>', err).replace('class="ring"', 'style="display:none"'))
            webview.start()
        else:
            print(err)
        return 1
    if resolved is not None:
        models_dir = resolved

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

    if webview is None:
        import webbrowser
        print("kiss: pywebview not bundled — opening in your browser instead")
        webbrowser.open(url)
        server.join()
        return 0

    webview.create_window("KISS", url, width=1200, height=800, min_size=(800, 560))
    webview.start()            # blocks until the window is closed
    return 0
