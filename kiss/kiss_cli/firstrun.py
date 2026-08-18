"""First-run bootstrap: the app fetches its own KI packages.

The first real double-click of KISS.app died invisibly: no models/ directory
next to the app, so the server thread raised FileNotFoundError — visible only
by running the inner Contents/MacOS binary from a terminal, which no app user
will ever do. Requiring a sidecar tarball extracted "next to the app" was CLI
thinking; an application installed into /Applications does not even have a
writable "next to".

So: on first launch, download kiss-ki-packages.tar.gz from the release into the
platform's per-user data directory and extract it there. ~74 MB, once ever.
Catalog.discover treats that directory as a root, so every later launch finds
it without network.
"""

from __future__ import annotations

import platform
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

KI_URL = ("https://github.com/lzwei196/KISS---Knowledge-Infrastructure-for-"
          "Scientific-Simulation/releases/download/v0.2.0/kiss-ki-packages.tar.gz")


def data_dir() -> Path:
    """Per-user application data, by platform convention."""
    home = Path.home()
    if platform.system() == "Darwin":
        return home / "Library" / "Application Support" / "KISS"
    if platform.system() == "Windows":
        import os
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "KISS"
    return home / ".local" / "share" / "kiss"


def models_present() -> Path | None:
    m = data_dir() / "models"
    if m.is_dir() and any(m.glob("*/SKILL.md")):
        return m
    return None


def download_ki(progress: Callable[[str, float], None] | None = None) -> Path:
    """Fetch and extract the KI packages. Returns the models directory.

    ``progress(stage, fraction)`` is called as work proceeds so a window can
    show it; fraction is -1 when the total size is unknown.
    """
    dest = data_dir()
    dest.mkdir(parents=True, exist_ok=True)
    note = progress or (lambda s, f: None)

    note("downloading", 0.0)
    req = urllib.request.Request(KI_URL, headers={"User-Agent": "kiss-app"})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            got = 0
            while True:
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                tmp.write(chunk)
                got += len(chunk)
                note("downloading", (got / total) if total else -1.0)
            tmp_path = Path(tmp.name)

    note("extracting", -1.0)
    with tarfile.open(tmp_path) as t:
        # The tarball is built by our own release job, but extraction is still
        # filtered: a hostile mirror must not be able to write outside dest.
        t.extractall(dest, filter="data")
    tmp_path.unlink(missing_ok=True)

    m = dest / "models"
    if not (m.is_dir() and any(m.glob("*/SKILL.md"))):
        raise RuntimeError(f"downloaded archive did not contain models/ (looked in {dest})")
    note("done", 1.0)
    return m


SETUP_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>KISS</title>
<style>
body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
     background:#111215;color:#EEF0F2;font:15px/1.6 -apple-system,system-ui,sans-serif}
.box{text-align:center;max-width:420px}
.ring{width:72px;height:72px;margin:0 auto 18px;border-radius:50%;
      border:3px solid #EEF0F2;border-top-color:#416FD8;animation:r 1s linear infinite}
@keyframes r{to{transform:rotate(360deg)}}
#pct{color:#416FD8;font-weight:600}
.dim{color:#81858C;font-size:13px;margin-top:10px}
</style></head><body><div class="box">
<div class="ring"></div>
<div id="msg">Setting up KISS — downloading the 127 model packages <span id="pct"></span></div>
<div class="dim">~74 MB, one time only. They live in your user library afterwards.</div>
</div></body></html>"""
