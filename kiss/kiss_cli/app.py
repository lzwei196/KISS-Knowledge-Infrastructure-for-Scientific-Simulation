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
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path


class _DesktopApi:
    """Small native-only helpers exposed to the local GeoForge page."""

    def __init__(self, webview_module):
        self.webview = webview_module
        self.window = None

    def choose_project_parent(self, initial: str = "") -> str | None:
        """Show the operating system's folder picker and return one folder."""
        if self.window is None:
            return None
        start = Path(initial).expanduser() if initial else Path.home()
        # Native folder pickers need an existing directory to start in.  If
        # the user typed a new path, open at its closest existing ancestor;
        # GeoForge will create the full typed path when the session is saved.
        if not start.is_dir():
            candidate = start
            while candidate != candidate.parent and not candidate.is_dir():
                candidate = candidate.parent
            start = candidate if candidate.is_dir() else Path.home()
        try:
            picked = self.window.create_file_dialog(
                self.webview.FOLDER_DIALOG,
                directory=str(start),
                allow_multiple=False,
            )
        except Exception:
            return None
        if not picked:
            return None
        if isinstance(picked, (list, tuple)):
            return str(picked[0]) if picked else None
        return str(picked)

    def choose_file(self, initial: str = "") -> str | None:
        """Show the operating system's file picker and return one file."""
        if self.window is None:
            return None
        start = Path(initial).expanduser() if initial else Path.home()
        if start.is_file():
            start = start.parent
        if not start.is_dir():
            candidate = start
            while candidate != candidate.parent and not candidate.is_dir():
                candidate = candidate.parent
            start = candidate if candidate.is_dir() else Path.home()
        try:
            picked = self.window.create_file_dialog(
                self.webview.OPEN_DIALOG,
                directory=str(start),
                allow_multiple=False,
            )
        except Exception:
            return None
        if not picked:
            return None
        if isinstance(picked, (list, tuple)):
            return str(picked[0]) if picked else None
        return str(picked)


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
            win = webview.create_window("GeoForge Desktop", html=firstrun.SETUP_HTML,
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
            webview.start()
            # returns when the setup window closes

    resolved, err = _ensure_models(models_dir)
    if err:
        if webview is not None:
            # Built fresh rather than string-replacing SETUP_HTML: the replace
            # targeted wording that a later rename changed, so the error window
            # silently kept the spinner text instead of showing the error.
            import html as _html
            page = ("<!doctype html><html><body style='margin:0;height:100vh;display:flex;"
                    "align-items:center;justify-content:center;background:#111215;color:#EEF0F2;"
                    "font:15px/1.6 -apple-system,system-ui,sans-serif'><div style='max-width:460px;"
                    "padding:24px;text-align:center;white-space:pre-wrap'>"
                    + _html.escape(err) + "</div></body></html>")
            webview.create_window("GeoForge Desktop", html=page, width=560, height=360)
            webview.start()
        else:
            print(err)
        return 1
    if resolved is not None:
        models_dir = resolved

    if sys.platform == "win32" and getattr(sys, "frozen", False):
        # The WinForms/WebView2 host has proved unstable across current
        # pythonnet and WebView2 runtime combinations.  Keep the Windows EXE
        # self-contained as the local backend, but render its identical web UI
        # in the user's default browser, as the Linux launcher already does.
        port = _free_port()
        from . import windows_tray
        # Tray Exit leaves through os._exit, which skips serve()'s cleanup:
        # hand it the same stop that ends live turns and launched workers.
        windows_tray.start(f"http://127.0.0.1:{port}/", on_exit=gui._stop_everything)
        return gui.serve(
            models_dir=models_dir, port=port, open_browser=True,
            workroot=workroot, auto_update=True,
        )

    port = _free_port()
    url = f"http://127.0.0.1:{port}/"

    server_process = None
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        # pythonnet's WinForms message loop can hold the frozen interpreter's
        # GIL, leaving an in-process HTTP thread able to accept sockets but
        # unable to run a handler.  Re-enter this same self-contained EXE as a
        # hidden server process so WebView2 and the backend cannot deadlock.
        argv = [sys.executable]
        if models_dir is not None:
            argv.extend(["--models", str(models_dir)])
        argv.extend(["gui", "--no-browser", "--desktop-server", "--port", str(port)])
        if workroot is not None:
            argv.extend(["--workroot", str(workroot)])
        server_process = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        server = server_process
    else:
        server = threading.Thread(
            target=gui.serve,
            kwargs=dict(models_dir=models_dir, port=port, open_browser=False,
                        workroot=workroot, auto_update=True),
            daemon=True,       # window closing ends the process, server included
        )
        server.start()
    if not _wait_up(url):
        if server_process is not None:
            server_process.terminate()
        print("kiss: the local server did not come up; run `kiss gui` for details")
        return 1

    if webview is None:
        import webbrowser
        print("kiss: pywebview not bundled — opening in your browser instead")
        webbrowser.open(url)
        if server_process is not None:
            server_process.wait()
        else:
            server.join()
        return 0

    # Keep pywebview's native Edit menu and also serve the JS/native clipboard
    # bridge. The old callback edited AppKit from pywebview's worker thread;
    # depending on timing, Cocoa discarded the menu and Cmd+V still did nothing.
    # This setting exists for Cocoa's native Edit menu.  Enabling it on the
    # pythonnet WinForms backend can deadlock the visible Windows message loop;
    # Windows clipboard actions use the JS/native clipboard bridge below.
    if sys.platform == "darwin":
        webview.settings['SHOW_DEFAULT_MENUS'] = True
    desktop_api = _DesktopApi(webview)
    window = webview.create_window(
        "GeoForge Desktop", url, width=1200, height=800, min_size=(800, 560),
        js_api=desktop_api,
    )
    desktop_api.window = window
    try:
        webview.start()
        # blocks until the window is closed
    finally:
        if server_process is not None:
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
    return 0
