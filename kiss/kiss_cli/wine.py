"""Wine for KIs whose model is a Windows program (APEX0806.exe), on hosts that are not Windows.

On Windows the program runs directly and Wine is never required. On macOS GeoForge can install
one pinned WineHQ build into its own data folder when the user clicks the setup card's button:
no sudo, nothing in /Applications or /opt/homebrew, and outside every model workspace, so
re-materialising a model cannot remove it (APEX lost its Wine this way or similar on 2026-09-13).
Homebrew's wine-stable cask was disabled on 2026-09-01 (fails Gatekeeper); this is the same
artifact it installed, verified by the same sha256. On Linux the user installs Wine with the
system package manager.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Callable

from . import tls
from .firstrun import data_dir

VERSION = "11.0_1"
URL = ("https://github.com/Gcenx/macOS_Wine_builds/releases/download/"
       f"{VERSION}/wine-stable-{VERSION}-osx64.tar.xz")
SHA256 = "b50dc50ec7f41d58b115a6b685d4d1315ba3c797bd3aa0f49213f2703cb82388"
SIZE_LABEL = "185 MB"
APP = "Wine Stable.app"


def needed() -> bool:
    """A Windows program runs natively on Windows; everywhere else it needs Wine."""
    return sys.platform != "win32"


def required_by(ki, manifest=None) -> bool:
    """Does this KI's model need Wine on this host? Declared in its Desktop manifest
    (`system_deps: [wine]` or a PE32 `binary_type`) or in the KI's own
    knowledge_infrastructure.yaml (`binary.type: PE32_wine`). Only APEX has a manifest;
    DLBreach, DNDC, EPIC and HEC_RAS say it in the KI file."""
    if not needed():
        return False
    if "wine" in (getattr(manifest, "system_deps", None) or []):
        return True
    if str(getattr(manifest, "binary_type", "") or "").upper().startswith("PE32"):
        return True
    try:
        text = (Path(ki.root) / "knowledge_infrastructure.yaml").read_text(encoding="utf-8", errors="replace")
    except (OSError, AttributeError, TypeError):
        return False
    return bool(re.search(r"^\s*type:\s*[\"']?PE\w*wine", text, re.M | re.I))


def can_install() -> bool:
    """GeoForge installs Wine itself only on macOS (the pinned build is a macOS bundle)."""
    return sys.platform == "darwin"


def home() -> Path:
    return data_dir() / "runtimes" / f"wine-{VERSION}"


def managed_bin() -> Path:
    return home() / APP / "Contents" / "Resources" / "wine" / "bin"


def find() -> str | None:
    """The Wine to use: GeoForge's own install first, then one on PATH. A dangling link is none."""
    managed = managed_bin() / "wine"
    if managed.is_file() and os.access(managed, os.X_OK):
        return str(managed)
    return shutil.which("wine")


def env(base: dict[str, str]) -> dict[str, str]:
    """Put GeoForge's Wine on PATH for every child process.

    WINEPREFIX is deliberately left alone: each KI decides its own. HEC_RAS installs HEC-RAS
    in a prefix inside its workspace and uses it only when none is already set."""
    out = dict(base)
    if not (managed_bin() / "wine").is_file():
        return out
    parts = [p for p in out.get("PATH", "").split(os.pathsep) if p]
    if str(managed_bin()) not in parts:
        out["PATH"] = os.pathsep.join([str(managed_bin()), *parts])
    out.setdefault("WINEDEBUG", "-all")
    return out


def install(progress: Callable[[str], object] = lambda text: None, *, url: str = URL,
            sha256: str = SHA256, opener=None) -> dict:
    """Download, verify, extract and initialise the pinned Wine. Idempotent; never partial.

    Returns {"ok": bool, "wine": path | None, "detail": str}."""
    if not can_install():
        return {"ok": False, "wine": None,
                "detail": "GeoForge installs Wine only on macOS; install it with your package manager."}
    if (managed_bin() / "wine").is_file():
        return {"ok": True, "wine": str(managed_bin() / "wine"), "detail": "already installed"}
    root = home()
    root.parent.mkdir(parents=True, exist_ok=True)
    partial = root.parent / f".wine-{VERSION}.tar.xz.partial"
    staging = root.parent / f".wine-{VERSION}.staging"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        progress(f"Downloading WineHQ {VERSION} ({SIZE_LABEL}) from {url}\n")
        req = urllib.request.Request(url, headers={"User-Agent": "GeoForge-Desktop"})
        digest = hashlib.sha256()
        with (opener or urllib.request.urlopen)(req, timeout=60, context=tls.context()) as r, \
                open(partial, "wb") as fh:
            while chunk := r.read(1 << 20):
                digest.update(chunk)
                fh.write(chunk)
        if digest.hexdigest() != sha256:
            return {"ok": False, "wine": None,
                    "detail": f"checksum mismatch: got {digest.hexdigest()}, expected {sha256}; nothing installed"}
        progress("Checksum verified. Extracting…\n")
        staging.mkdir(parents=True)
        with tarfile.open(partial, "r:xz") as tar:
            tar.extractall(staging, filter="data")        # refuses paths or links outside staging
        if not (staging / APP / "Contents" / "Resources" / "wine" / "bin" / "wine").is_file():
            return {"ok": False, "wine": None, "detail": f"the archive has no {APP}/…/bin/wine; nothing installed"}
        staging.replace(root)
        wine = str(managed_bin() / "wine")
        run_env = env(dict(os.environ))
        progress("Checking that Wine starts (Apple Silicon runs it through Rosetta 2)…\n")
        check = subprocess.run([wine, "--version"], capture_output=True, text=True, timeout=120, env=run_env)
        if check.returncode != 0:
            shutil.rmtree(root, ignore_errors=True)
            return {"ok": False, "wine": None, "detail": (
                f"Wine did not start ({(check.stderr or check.stdout).strip()[-300:]}). On Apple Silicon "
                "install Rosetta 2 (softwareupdate --install-rosetta --agree-to-license) and try again.")}
        progress(f"{check.stdout.strip()} runs. Preparing its Windows environment (first start takes a minute)…\n")
        subprocess.run([wine, "wineboot", "--init"], capture_output=True, text=True, timeout=600, env=run_env)
        progress("Wine is installed for GeoForge.\n")
        return {"ok": True, "wine": wine, "detail": check.stdout.strip()}
    except (OSError, tarfile.TarError, subprocess.SubprocessError) as error:
        shutil.rmtree(root, ignore_errors=True)
        return {"ok": False, "wine": None, "detail": f"{type(error).__name__}: {error}; nothing installed"}
    finally:
        partial.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
