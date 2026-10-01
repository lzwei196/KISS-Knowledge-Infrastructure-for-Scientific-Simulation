"""The setup tool's argument checks see only the command line. On 2026-09-30 a DeepSeek setup
agent, refused a write outside its workspace, wrote a Python script inside the workspace that made
the same change (re-pointing /opt/homebrew/bin/wine, creating ~/.wine) and ran it. On macOS setup
commands now run under the kernel sandbox, which blocks such writes for the whole process tree.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists(), reason="macOS sandbox only")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    if subprocess.run(["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)", "/usr/bin/true"],
                      capture_output=True).returncode != 0:
        pytest.skip("sandbox-exec cannot apply here (the test runner is itself sandboxed)")
    work = tmp_path / "work"
    (work / "ki").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (work / "linked").symlink_to(outside, target_is_directory=True)
    # temp folders are writable in production; here the outside folder lives under temp too
    monkeypatch.setattr(api, "_setup_scratch_roots", lambda: [])
    cfg = SimpleNamespace(root=work, python=sys.executable, roles={"binaries": work / "binaries"})

    def run(script: str) -> str:
        # setup may run only build helpers and root-level inspection scripts, hence the name
        (work / "check_step.py").write_text(script)
        return api.execute_tool("run_setup_command", {"argv": [sys.executable, "check_step.py"]},
                                SimpleNamespace(root=work / "ki"), cfg, setup_mode=True)

    return SimpleNamespace(work=work, outside=outside, run=run)


def test_a_workspace_script_cannot_write_outside_the_workspace(ws):
    out = ws.run(f"open({str(ws.outside / 'x.txt')!r}, 'w').write('escaped')\n")
    assert "exit_code=0" not in out and "Operation not permitted" in out
    assert not (ws.outside / "x.txt").exists()


def test_nor_through_a_symlink_in_the_workspace(ws):
    out = ws.run("open('linked/z.txt', 'w').write('escaped')\n")
    assert "exit_code=0" not in out and not (ws.outside / "z.txt").exists()


def test_a_workspace_script_can_still_write_its_workspace(ws):
    out = ws.run("import os; os.makedirs('build', exist_ok=True); open('build/y.txt', 'w').write('ok')\n")
    assert "exit_code=0" in out and (ws.work / "build" / "y.txt").read_text() == "ok"


def test_without_a_usable_sandbox_the_setup_log_says_so(ws, monkeypatch):
    monkeypatch.setattr(api, "_os_sandbox_ok", lambda: False)
    out = ws.run("print('hello')\n")
    assert "exit_code=0" in out and "OS sandbox unavailable" in out


def test_the_writable_places_include_temp_and_package_caches_but_not_home():
    import os
    roots = {str(p) for p in api._setup_scratch_roots()}
    assert os.path.realpath(__import__("tempfile").gettempdir()) in roots
    assert str(Path.home()) not in roots and str(Path.home() / ".wine") not in roots
