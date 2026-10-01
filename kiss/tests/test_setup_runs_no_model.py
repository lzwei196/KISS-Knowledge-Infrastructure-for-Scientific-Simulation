"""Setup installs and verifies software; it does not run the model.

Seen on Windows (known issue 3) and on Mac (2026-10-01): the setup agent ran the FSM2 example
during setup and left results in the software folder; on 2026-09-30 it ran APEX end to end.
The "installation-only" command guard existed but was applied only to the installation test.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from kiss_cli import api, execution, install


@pytest.fixture
def ws(tmp_path, monkeypatch):
    work = tmp_path / "work"
    (work / "ki" / "tools").mkdir(parents=True)
    (work / "ki" / "tools" / "run_model.py").write_text("print('simulating')\n")
    (work / "check_install.py").write_text("print('ok')\n")
    built = work / "binaries" / "model"
    built.parent.mkdir()
    built.write_text("#!/bin/sh\n")
    built.chmod(0o755)
    ext = tmp_path / "existing"
    (ext / "bin").mkdir(parents=True)
    (ext / "bin" / "model").write_text("#!/bin/sh\n")
    (ext / "bin" / "model").chmod(0o755)
    cfg = SimpleNamespace(root=work, python=sys.executable, roles={"binaries": work / "binaries"})
    ran = []

    def fake_run(argv, **kwargs):
        ran.append(list(argv))
        return execution.ProcessRun("succeeded", 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(execution, "run_process", fake_run)
    monkeypatch.setattr(api, "_os_sandbox_ok", lambda: False)      # the argument rules are under test

    def call(*argv, **context):
        return api.execute_tool("run_setup_command", {"argv": list(argv)}, SimpleNamespace(root=work / "ki"),
                                cfg, setup_mode=True, setup_context={"existing_roots": [str(ext)], **context})

    return SimpleNamespace(work=work, ext=ext, call=call, ran=ran)


@pytest.mark.parametrize("argv", [
    [sys.executable, "ki/tools/run_model.py", "outputs/q.csv"],      # the KI's run tool
    ["binaries/model", "namelist.txt"],                               # the built model with a case
    ["{ext}/bin/model", "namelist.txt"],                              # the existing install's model with a case
    ["make", "test"],
    ["find", ".", "-name", "*.exe", "-exec", "{}", ";"],
])
def test_an_ordinary_setup_turn_cannot_run_the_model(ws, argv):
    argv = [a.replace("{ext}", str(ws.ext)) for a in argv]
    with pytest.raises(api.ToolError, match="blocked|blocks"):
        ws.call(*argv)
    assert ws.ran == []


@pytest.mark.parametrize("argv", [
    ["binaries/model", "--version"],                                  # a start-up probe
    ["{ext}/bin/model", "--help"],
    [sys.executable, "check_install.py"],                             # a root-level inspection script
    ["make"],
    ["gfortran", "--version"],
    ["find", ".", "-name", "*.F90"],                                  # looking, not launching
    ["ls", "-la", "binaries"],
])
def test_setup_can_still_build_probe_and_inspect(ws, argv):
    argv = [a.replace("{ext}", str(ws.ext)) for a in argv]
    assert "ok" in ws.call(*argv)


def test_the_host_preflight_is_still_available_in_an_ordinary_setup(ws, monkeypatch):
    monkeypatch.setattr(install, "run_preflight", lambda *a, **k: install.Step("preflight", True, "27 passed"))
    out = api.execute_tool("run_preflight", {}, SimpleNamespace(root=ws.work / "ki"),
                           SimpleNamespace(root=ws.work, python=sys.executable, roles={}), setup_mode=True)
    assert out.startswith("PASS")


def test_the_setup_instructions_no_longer_ask_for_a_reference_run():
    """The workspace contract itself told the agent to "Run the reference case" once preflight
    passed; for CLI agents these instructions are the only control."""
    import inspect
    from kiss_cli import handoff
    source = inspect.getsource(handoff)
    assert "Run the reference case" not in source
    assert "Setup installs and verifies software only" in source
    assert "Do not run the model, its examples or a reference case here" in source


def test_the_card_no_longer_says_external_sources_came_from_the_database():
    from pathlib import Path
    html = (Path(api.__file__).parent / "web" / "app.html").read_text(encoding="utf-8")
    assert "found in the GeoForge Database" not in html
    assert "Each option says whether it comes from the GeoForge Database" in html
