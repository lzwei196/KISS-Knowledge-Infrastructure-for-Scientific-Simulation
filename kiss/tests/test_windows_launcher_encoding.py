"""Windows agent launchers must be readable by cmd.exe under any code page.

cmd.exe decodes a .cmd file in the console's current code page: the OEM page
(cp936 on Chinese Windows) in a fresh console, but 65001 once an agent such as
Codex or Claude Code's PowerShell has switched to UTF-8.  An install folder or
Python below a user name in Chinese must therefore never be spelt in the file.
Launchers are pure ASCII: a non-ASCII target is named by its 8.3 alias or via an
ASCII junction beside the launcher, which cmd.exe reaches through %~dp0.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from kiss_cli import flowrun


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows cmd.exe launchers")

CHINESE = "张三"
# A fresh console (OEM code page), and the UTF-8 console agents create.
CODE_PAGES = ("", "chcp 65001 >nul & ")


@pytest.fixture
def home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _frozen_install(monkeypatch, folder: Path) -> Path:
    """A frozen app in ``folder`` whose bridge is a real console program."""
    folder.mkdir(parents=True)
    bridge = folder / "geoforge-agent-bridge.exe"
    # cmd.exe as the stand-in bridge: `bridge flow /c echo X` prints X, so a
    # launcher that names the bridge wrongly cannot pass.
    shutil.copy(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe", bridge)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(folder / "GeoForge Desktop.exe"))
    return bridge


def _run(launcher: Path, args: str, code_page: str, **kwargs):
    # A console of its own (CREATE_NO_WINDOW still creates one), so the test
    # runner's console code page cannot decide the result.
    return subprocess.run(
        f'cmd /d /s /c "{code_page}"{launcher}" {args}"', capture_output=True,
        stdin=subprocess.DEVNULL, timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)


def _reaches_bridge(launcher: Path, code_page: str) -> bool:
    result = _run(launcher, "/c echo BRIDGE-REACHED", code_page)
    return result.returncode == 0 and b"BRIDGE-REACHED" in result.stdout


def _launchers():
    return [(flowrun._launcher_path(), "flow"), (flowrun._database_launcher_path(), "database")]


def test_launchers_for_a_chinese_install_path_are_ascii_and_work_in_any_code_page(
        monkeypatch, tmp_path, home):
    bridge = _frozen_install(
        monkeypatch, tmp_path / CHINESE / "AppData" / "Local" / "Programs" / "GeoForge")
    # A launcher written as UTF-8 by an earlier build is replaced, not kept.
    stale = home / ".kiss" / "bin" / "geoforge-flow.cmd"
    stale.parent.mkdir(parents=True)
    stale.write_text(f'@echo off\n"{bridge}" flow %*\n', encoding="utf-8")

    launchers = _launchers()

    assert launchers[0][0] == stale
    for launcher, mode in launchers:
        raw = launcher.read_bytes()
        assert raw.isascii(), raw
        assert raw.decode("ascii").rstrip().endswith(f" {mode} %*")
        for code_page in CODE_PAGES:
            assert _reaches_bridge(launcher, code_page), (code_page, raw)


def test_without_an_8dot3_alias_the_launcher_goes_through_an_ascii_junction(
        monkeypatch, tmp_path, home):
    _frozen_install(monkeypatch, tmp_path / CHINESE / "GeoForge")
    # As on a volume with 8.3 names disabled.
    monkeypatch.setattr(flowrun, "_windows_short_path", lambda path: path)

    launchers = _launchers()

    link = home / ".kiss" / "bin" / flowrun._WINDOWS_TARGET_LINK
    assert os.lstat(link).st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
    for launcher, mode in launchers:
        body = launcher.read_bytes().decode("ascii")
        assert f'"%~dp0{flowrun._WINDOWS_TARGET_LINK}\\geoforge-agent-bridge.exe" {mode} %*' in body
        for code_page in CODE_PAGES:
            assert _reaches_bridge(launcher, code_page), (code_page, body)


def test_a_moved_install_repoints_the_junction_but_never_replaces_a_real_folder(
        monkeypatch, tmp_path, home):
    monkeypatch.setattr(flowrun, "_windows_short_path", lambda path: path)
    old = tmp_path / f"old-{CHINESE}"
    old.mkdir()
    link = home / ".kiss" / "bin" / flowrun._WINDOWS_TARGET_LINK
    link.parent.mkdir(parents=True)
    assert flowrun._ensure_junction(link, old)

    _frozen_install(monkeypatch, tmp_path / f"new-{CHINESE}")
    launcher = flowrun._launcher_path()

    assert os.path.samefile(link, tmp_path / f"new-{CHINESE}")
    assert old.is_dir()                                  # only the link moved
    assert _reaches_bridge(launcher, CODE_PAGES[1])

    real = tmp_path / "real-folder"
    real.mkdir()
    (real / "keep.txt").write_text("user data", encoding="utf-8")
    assert not flowrun._ensure_junction(real, old)
    assert (real / "keep.txt").read_text(encoding="utf-8") == "user data"


def test_unreachable_path_is_a_clear_error_and_writes_no_launcher(
        monkeypatch, tmp_path, home):
    _frozen_install(monkeypatch, tmp_path / CHINESE / "GeoForge")
    # No 8.3 alias and no junction possible.
    monkeypatch.setattr(flowrun, "_windows_short_path", lambda path: path)
    monkeypatch.setattr(flowrun, "_ensure_junction", lambda link, target: False)

    for create in (flowrun._launcher_path, flowrun._database_launcher_path,
                   flowrun.wrapper_commands):
        with pytest.raises(flowrun.WindowsLauncherPathError, match="8.3"):
            create()
    assert not list((home / ".kiss" / "bin").glob("*.cmd"))


def test_source_launchers_run_python_below_a_chinese_folder(monkeypatch, tmp_path):
    venv = tmp_path / CHINESE / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)],
                   check=True, capture_output=True, timeout=120)
    python = venv / "Scripts" / "python.exe"
    # The launcher's own folder is Chinese too; cmd.exe expands %~dp0 itself.
    home = tmp_path / f"home-{CHINESE}"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", str(python))

    launcher = flowrun._database_launcher_path()

    assert launcher.parent == home / ".kiss" / "bin"
    body = launcher.read_bytes()
    assert body.isascii() and b'-X utf8 "%~dp0geoforge-db.py" %*' in body
    # The launcher forces -X utf8, so the helper's stdout is UTF-8.
    for code_page in CODE_PAGES:
        result = _run(launcher, "--help", code_page, text=True,
                      encoding="utf-8", errors="replace")
        assert result.returncode == 0, (code_page, result.stderr)
        assert "Search GeoForge Database" in result.stdout
