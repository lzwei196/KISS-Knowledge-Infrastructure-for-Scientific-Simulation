"""Bug #1 (live Mac test, 2026-09-29): "Use already-installed software" overwrote the user's
installation. The setup agent's cp/chmod went through a symlink in the setup workspace and
replaced ~/kiss/aquacrop/ki/run_and_score.py, and preflight still passed 14/14.

Layer 1: the API setup tool treats the existing installation as read-only.
Layer 2: for any provider, setup is not verified when the installation changed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, execution, gui, install, install_locations
from kiss_cli import setup as setup_flow


@pytest.fixture
def ws(tmp_path, monkeypatch):
    work = tmp_path / "work"
    ki_root = work / "ki"
    ki_root.mkdir(parents=True)
    ext = tmp_path / "aquacrop"
    (ext / "ki").mkdir(parents=True)
    runner = ext / "ki" / "run_and_score.py"
    runner.write_text("original\n")
    (ext / "bin").mkdir()
    exe = ext / "bin" / "model"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    (work / "gen.py").write_text("generated\n")
    (work / "linked").symlink_to(ext, target_is_directory=True)     # what the agent made
    cfg = SimpleNamespace(root=work, python=sys.executable, roles={"binaries": work / "binaries"})
    ran = []

    envs = []

    def fake_run(argv, **kwargs):
        ran.append(list(argv))
        envs.append(kwargs.get("env") or {})
        return execution.ProcessRun("succeeded", 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(execution, "run_process", fake_run)

    def call(*argv):
        return api.execute_tool("run_setup_command", {"argv": list(argv)}, SimpleNamespace(root=ki_root),
                                cfg, setup_mode=True, setup_context={"existing_roots": [str(ext)]})

    return SimpleNamespace(work=work, ext=ext, runner=runner, exe=exe, call=call, ran=ran, envs=envs)


@pytest.mark.parametrize("argv", [
    ["cp", "gen.py", "linked/ki/run_and_score.py"],        # the reproduced path: through the symlink
    ["cp", "gen.py", "{ext}/ki/run_and_score.py"],          # named directly
    ["chmod", "755", "linked/ki/run_and_score.py"],
    ["sed", "-i.bak", "s/a/b/", "{ext}/ki/run_and_score.py"],
    ["mv", "{ext}/ki/run_and_score.py", "old.py"],
    ["ln", "-sf", "gen.py", "linked/ki/run_and_score.py"],
    ["python3", "-m", "pip", "install", "--target", "{ext}/lib", "x"],
    ["find", "{ext}", "-name", "*.py", "-delete"],
    ["tar", "-xf", "a.tar", "-C", "{ext}"],
])
def test_setup_cannot_write_into_the_existing_installation(ws, argv):
    argv = [a.replace("{ext}", str(ws.ext)) for a in argv]
    # `find … -delete` is refused one step earlier, as a command that launches or deletes
    with pytest.raises(api.ToolError, match="read-only during setup|blocks find"):
        ws.call(*argv)
    assert ws.ran == [] and ws.runner.read_text() == "original\n"


@pytest.mark.parametrize("argv", [
    ["cp", "{ext}/ki/run_and_score.py", "run_and_score.py"],   # copy out, then edit the copy
    ["ln", "-s", "{ext}/bin/model", "model"],                  # link from the workspace
    ["ln", "-s", "{ext}/bin/model"],
    ["ls", "-la", "{ext}/ki"],
    ["cat", "{ext}/ki/run_and_score.py"],
    ["sed", "-n", "1p", "{ext}/ki/run_and_score.py"],
    ["find", "{ext}", "-name", "*.py"],
    ["file", "{ext}/bin/model"],
    ["{ext}/bin/model", "--version"],                          # probing the installed program
])
def test_setup_can_still_read_copy_link_and_run_the_existing_installation(ws, argv):
    argv = [a.replace("{ext}", str(ws.ext)) for a in argv]
    assert "ok" in ws.call(*argv)
    assert len(ws.ran) == 1


def test_setup_commands_do_not_write_bytecode_into_the_installation(ws):
    ws.call(str(ws.exe), "--version")
    assert ws.envs[0].get("PYTHONDONTWRITEBYTECODE") == "1"


def test_fingerprint_sees_edits_new_files_deletions_and_mode_changes(tmp_path):
    root = tmp_path / "inst"
    (root / "ki").mkdir(parents=True)
    (root / "ki" / "a.py").write_text("a")
    (root / "ki" / "b.py").write_text("b")
    (root / "ki" / "__pycache__").mkdir()
    before = install_locations.fingerprint([str(root)])
    (root / "ki" / "a.py").write_text("changed")
    (root / "ki" / "b.py").unlink()
    (root / "ki" / "c.py").write_text("new")
    (root / "ki" / "__pycache__" / "a.cpython-313.pyc").write_bytes(b"cache")   # regenerated cache
    changes = install_locations.changes(before, install_locations.fingerprint([str(root)]))
    assert changes == [f"{root}/ki/a.py (changed)", f"{root}/ki/b.py (deleted)", f"{root}/ki/c.py (new)"]
    before = install_locations.fingerprint([str(root)])
    (root / "ki" / "c.py").chmod(0o755)
    assert install_locations.changes(before, install_locations.fingerprint([str(root)])) == [
        f"{root}/ki/c.py (changed)"]


def test_a_setup_turn_that_changes_the_installation_is_not_verified(tmp_path, monkeypatch):
    """Through the real setup handler: the agent writes into the install, preflight would pass."""
    ext = tmp_path / "aquacrop"
    (ext / "ki").mkdir(parents=True)
    runner = ext / "ki" / "run_and_score.py"
    runner.write_text("original\n")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "CLAUDE.md").write_text("setup contract")
    ki = SimpleNamespace(name="AquaCrop", root=root / "ki", meta={})
    cfg = SimpleNamespace(python=sys.executable)
    checks = iter([install.Step("preflight", False, "not set up yet"),
                   install.Step("preflight", True, "14 passed")])
    monkeypatch.setattr(install, "run_preflight", lambda *a, **k: next(checks))
    monkeypatch.setattr(install_locations, "info",
                        lambda *a, **k: {"installation_mode": "existing", "existing_path": str(ext)})
    monkeypatch.setattr(install_locations, "record", lambda *a, **k: None)
    monkeypatch.setattr(setup_flow, "prepare", lambda *a, **k: (ki, cfg))
    monkeypatch.setattr(gui.prompt, "compose", lambda *a, **k: "system")

    def agent_overwrites_the_install(*a, **k):
        runner.write_text("smoke runner\n")
        yield "copied the entry script\n"

    monkeypatch.setattr(api, "run", agent_overwrites_the_install)
    monkeypatch.setitem(api.PROVIDERS, "deepseek", SimpleNamespace(name="deepseek"))
    handler = object.__new__(gui.Handler)
    handler.workroot = tmp_path
    handler.repo_root = tmp_path
    handler.catalog = SimpleNamespace(models_dir=tmp_path / "models")
    shown = []
    handler._ki = lambda name: ki
    handler._validate_binding = lambda *a, **k: None
    handler._workdir = lambda _ki: root
    handler._manifest = lambda _ki: SimpleNamespace()
    handler._status_for = lambda _ki: {"can_run": False}
    handler._open_stream = lambda: None
    handler._end_stream = lambda: None
    handler._chunk = lambda text: shown.append(text) or True
    handler._stream_agent_setup({"model": "AquaCrop", "provider": "api:deepseek"})
    log = "".join(shown)
    status = json.loads((root / "status.json").read_text())
    assert status["ok"] is False and "GeoForge final check: FAIL" in log
    assert str(runner) in log and "existing installation" in log
