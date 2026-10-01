"""Wine setup (2026-09-30). APEX0806.exe needs Wine on a Mac; Homebrew's wine-stable cask was
disabled on 2026-09-01, APEX's own Wine vanished on 2026-09-13 while its badge still said
"Verified on this machine", and Desktop's install card had no entry for Wine.
"""
from __future__ import annotations

import io
import hashlib
import json
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import gui, install, paths, wine
from kiss_cli import setup as setup_flow

FAKE_WINE = "#!/bin/sh\nif [ \"$1\" = --version ]; then echo wine-11.0; fi\nexit 0\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(wine, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    return tmp_path


def _managed(home_dir):
    b = wine.managed_bin()
    b.mkdir(parents=True)
    (b / "wine").write_text(FAKE_WINE)
    (b / "wine").chmod(0o755)
    return b / "wine"


def _archive(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tar:
        for name, text in members.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _opener(blob):
    return lambda req, timeout=None, context=None: io.BytesIO(blob)


def test_find_prefers_geoforges_wine_then_path_and_ignores_a_dangling_link(home, monkeypatch):
    shelf = home / "bin"
    shelf.mkdir()
    (shelf / "wine").symlink_to(home / "gone" / "wine")          # the 13 Sep state
    monkeypatch.setenv("PATH", str(shelf))
    assert wine.find() is None
    managed = _managed(home)
    assert wine.find() == str(managed)


def test_every_child_process_gets_geoforges_wine_and_no_imposed_prefix(home):
    _managed(home)
    env = paths.with_ki_tools_common(SimpleNamespace(roles={}), {"PATH": "/usr/bin"})
    assert env["PATH"].split(os.pathsep)[0] == str(wine.managed_bin())
    # Each KI decides its own Wine prefix: HEC_RAS keeps one inside its workspace and uses it
    # only when WINEPREFIX is not already set, so GeoForge must not set one for everybody.
    assert "WINEPREFIX" not in env


def test_no_wine_on_path_is_added_before_it_is_installed(home):
    env = paths.with_ki_tools_common(SimpleNamespace(roles={}), {"PATH": "/usr/bin"})
    assert env["PATH"] == "/usr/bin" and "WINEPREFIX" not in env


def test_install_verifies_extracts_and_starts_the_pinned_build(home, monkeypatch):
    monkeypatch.setattr(wine, "can_install", lambda: True)
    blob = _archive({f"{wine.APP}/Contents/Resources/wine/bin/wine": FAKE_WINE})
    said = []
    result = wine.install(said.append, sha256=hashlib.sha256(blob).hexdigest(), opener=_opener(blob))
    assert result["ok"] and result["detail"] == "wine-11.0"
    assert wine.find() == str(wine.managed_bin() / "wine")
    assert any("Checksum verified" in s for s in said)
    assert not list(wine.home().parent.glob(".wine-*"))            # no partial download left


def test_install_refuses_a_wrong_checksum_and_installs_nothing(home, monkeypatch):
    monkeypatch.setattr(wine, "can_install", lambda: True)
    blob = _archive({f"{wine.APP}/Contents/Resources/wine/bin/wine": FAKE_WINE})
    result = wine.install(sha256="0" * 64, opener=_opener(blob))
    assert not result["ok"] and "checksum mismatch" in result["detail"]
    assert wine.find() is None and not wine.home().exists()


def test_install_refuses_an_archive_that_writes_outside_its_folder(home, monkeypatch):
    monkeypatch.setattr(wine, "can_install", lambda: True)
    blob = _archive({"../escaped": "x", f"{wine.APP}/Contents/Resources/wine/bin/wine": FAKE_WINE})
    result = wine.install(sha256=hashlib.sha256(blob).hexdigest(), opener=_opener(blob))
    assert not result["ok"] and not (wine.home().parent / "escaped").exists()
    assert not wine.home().exists()


def test_install_is_mac_only(home, monkeypatch):
    monkeypatch.setattr(wine, "can_install", lambda: False)
    assert "package manager" in wine.install()["detail"]


def test_the_system_check_finds_geoforges_wine_and_skips_wine_on_windows(home, monkeypatch):
    assert not install.check_system_deps(["wine"]).ok
    _managed(home)
    assert install.check_system_deps(["wine"]).ok
    monkeypatch.setattr(wine, "managed_bin", lambda: home / "none")
    monkeypatch.setattr(wine, "needed", lambda: False)                # Windows runs the .exe itself
    assert install.check_system_deps(["wine"]).ok


def _status(tmp_path, ok=True, deps=("wine",)):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    (work / "status.json").write_text(json.dumps({"ok": ok, "verified_at": 1755800000, "steps": []}))
    handler = object.__new__(gui.Handler)
    handler._workdir = lambda ki: work
    handler._manifest = lambda ki: SimpleNamespace(verified="unverified", acquire=None, system_deps=list(deps))
    return handler._status_for(SimpleNamespace(name="WinModel"))


def test_verified_badge_is_withdrawn_when_a_declared_tool_has_gone(home):
    status = _status(home)
    assert status["can_run"] is False and status["state"] == "failed"
    assert "wine" in status["primary_error"]["detail"]


def test_verified_badge_stays_when_the_tools_are_there(home):
    _managed(home)
    assert _status(home)["can_run"] is True


def test_missing_wine_on_a_mac_gets_geoforges_install_card_not_a_dead_brew_command(home, monkeypatch):
    monkeypatch.setattr(wine, "can_install", lambda: True)
    root = home / "ws"
    root.mkdir()
    card = setup_flow.request_for_system_dependencies(root, {"steps": [
        {"name": "system-deps", "ok": False, "detail": "not on PATH: wine — install them with your package manager"}]})
    assert card["host_action"] == "install_wine" and "Wine" in card["title"]
    assert "brew" not in (card.get("command") or "")
    assert setup_flow.request(root)["host_action"] == "install_wine"      # survives a reload


def test_an_agent_cannot_create_the_install_card(tmp_path):
    doc = setup_flow.request_user(tmp_path, {"kind": "permission", "title": "Install Wine",
                                             "host_action": "install_wine"})
    assert "host_action" not in doc and "host_action" not in setup_flow.request(tmp_path)


def test_the_setup_page_offers_the_install_button_and_the_route_exists():
    import inspect
    html = (Path(gui.__file__).parent / "web" / "setup.html").read_text(encoding="utf-8")
    assert 'host_action==="install_wine"' in html and "/api/runtime/wine/install" in html
    assert '"/api/runtime/wine/install"' in inspect.getsource(gui.Handler.do_POST)


def test_apex_runs_its_exe_directly_on_windows_and_through_wine_elsewhere():
    repo = Path(gui.__file__).resolve().parents[2]
    run = (repo / "models" / "APEX" / "tools" / "s6_run_apex.py").read_text(encoding="utf-8")
    pre = (repo / "models" / "APEX" / "preflight_check.py").read_text(encoding="utf-8")
    assert 'os.name == "nt"' in run and 'os.name == "nt"' in pre


def test_setup_offers_the_wine_button_before_any_agent_runs(home, monkeypatch):
    """2026-09-30: the agent got there first and installed Wine Staging into the model folder."""
    import sys as _sys
    from kiss_cli import api, prompt
    monkeypatch.setattr(wine, "can_install", lambda: True)
    root = home / "apexws"
    root.mkdir()
    (root / "CLAUDE.md").write_text("setup contract")
    ki = SimpleNamespace(name="APEX", root=root / "ki", meta={})
    monkeypatch.setattr(install, "run_preflight", lambda *a, **k: install.Step("preflight", False, "[FAIL] binary: wine"))
    monkeypatch.setattr(gui.install_locations, "info", lambda *a, **k: {"installation_mode": "new"})
    monkeypatch.setattr(setup_flow, "prepare", lambda *a, **k: (ki, SimpleNamespace(python=_sys.executable)))
    monkeypatch.setattr(prompt, "compose", lambda *a, **k: "system")

    def agent(*a, **k):
        pytest.fail("the setup agent must not start while Wine is missing: GeoForge provides it")
        yield ""

    monkeypatch.setattr(api, "run", agent)
    monkeypatch.setitem(api.PROVIDERS, "deepseek", SimpleNamespace(name="deepseek"))
    handler = object.__new__(gui.Handler)
    handler.workroot, handler.repo_root = home, home
    handler.catalog = SimpleNamespace(models_dir=home / "models")
    shown = []
    handler._ki = lambda name: ki
    handler._validate_binding = lambda *a, **k: None
    handler._workdir = lambda _ki: root
    handler._manifest = lambda _ki: SimpleNamespace(system_deps=["wine"])
    handler._status_for = lambda _ki: {"can_run": False}
    handler._open_stream = handler._end_stream = lambda: None
    handler._chunk = lambda text: shown.append(text) or True
    handler._stream_agent_setup({"model": "APEX", "provider": "api:deepseek"})
    assert setup_flow.request(root)["host_action"] == "install_wine"
    assert "Install Wine for GeoForge" in "".join(shown)


def _apex_preflight():
    import importlib.util
    path = Path(gui.__file__).resolve().parents[2] / "models" / "APEX" / "preflight_check.py"
    spec = importlib.util.spec_from_file_location("apex_preflight_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_apex_preflight_survives_a_timed_out_start_with_byte_output(tmp_path, monkeypatch):
    """preflight_check.py:205 joined bytes and text and crashed whenever the start check timed out."""
    import subprocess
    pre = _apex_preflight()
    exe = tmp_path / "APEX0806.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(pre, "BINARY", exe)
    monkeypatch.setattr(pre.shutil, "which", lambda name: "/opt/wine/bin/wine")

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], k.get("timeout"), output=b"APEXRUN.DAT IS MISSING", stderr="wine: warm-up")

    monkeypatch.setattr(pre.subprocess, "run", slow)
    checks = []
    pre.check_wine_and_start(checks)
    started = [c for c in checks if c["kind"] == "run"][0]
    assert started["status"] == "pass"


def test_apex_preflight_gives_a_cold_wine_start_time_to_finish():
    pre = _apex_preflight()
    import inspect
    assert "timeout=6," not in inspect.getsource(pre.check_wine_and_start)


# ── Every KI whose own file says its model is a Windows program gets the Wine handling,
#    not only APEX (the one KI with a Desktop manifest): DLBreach, DNDC, EPIC, HEC_RAS ──

def _ki_dir(tmp_path, binary_type):
    root = tmp_path / "models" / "WinModel"
    root.mkdir(parents=True)
    (root / "knowledge_infrastructure.yaml").write_text(
        f"model: WinModel\nruntime:\n  binary:\n    path: KISSPATH_BINARIES/x/model.exe\n    type: {binary_type}\n")
    return SimpleNamespace(name="WinModel", root=root, meta={})


def test_a_ki_that_declares_a_windows_program_needs_wine_without_any_manifest(tmp_path, monkeypatch):
    no_manifest = SimpleNamespace(system_deps=[], binary_type="")
    assert wine.required_by(_ki_dir(tmp_path, "PE32_wine"), no_manifest)
    assert not wine.required_by(_ki_dir(tmp_path / "b", "ELF"), no_manifest)
    assert wine.required_by(_ki_dir(tmp_path / "c", "ELF"), SimpleNamespace(system_deps=["wine"], binary_type=""))
    monkeypatch.setattr(wine, "needed", lambda: False)                    # on Windows it runs natively
    assert not wine.required_by(_ki_dir(tmp_path / "d", "PE32_wine"), no_manifest)


def test_the_real_wine_kis_are_all_recognised():
    repo = Path(gui.__file__).resolve().parents[2]
    no_manifest = SimpleNamespace(system_deps=[], binary_type="")
    for name in ("APEX", "DLBreach", "DNDC", "EPIC", "HEC_RAS"):
        assert wine.required_by(SimpleNamespace(root=repo / "models" / name), no_manifest), name
    for name in ("VIC", "FSM2", "DSSAT"):
        assert not wine.required_by(SimpleNamespace(root=repo / "models" / name), no_manifest), name


def test_the_badge_and_the_install_card_cover_a_wine_ki_without_a_manifest(home, monkeypatch):
    import sys as _sys
    from kiss_cli import api, prompt
    monkeypatch.setattr(wine, "can_install", lambda: True)
    ki = _ki_dir(home, "PE32_wine")
    work = home / "ws2"
    work.mkdir()
    (work / "status.json").write_text(json.dumps({"ok": True, "verified_at": 1755800000, "steps": []}))
    (work / "CLAUDE.md").write_text("setup contract")
    handler = object.__new__(gui.Handler)
    handler.workroot, handler.repo_root = home, home
    handler.catalog = SimpleNamespace(models_dir=home / "models")
    handler._ki = lambda name: ki
    handler._validate_binding = lambda *a, **k: None
    handler._workdir = lambda _ki: work
    handler._manifest = lambda _ki: SimpleNamespace(verified="unverified", acquire=None, system_deps=[], binary_type="")
    status = handler._status_for(ki)
    assert status["can_run"] is False and "wine" in status["primary_error"]["detail"]

    monkeypatch.setattr(install, "run_preflight", lambda *a, **k: install.Step("preflight", False, "[FAIL] wine"))
    monkeypatch.setattr(gui.install_locations, "info", lambda *a, **k: {"installation_mode": "new"})
    monkeypatch.setattr(setup_flow, "prepare", lambda *a, **k: (ki, SimpleNamespace(python=_sys.executable)))
    monkeypatch.setattr(prompt, "compose", lambda *a, **k: "system")

    def agent(*a, **k):
        pytest.fail("no setup agent before Wine is installed")
        yield ""

    monkeypatch.setattr(api, "run", agent)
    monkeypatch.setitem(api.PROVIDERS, "deepseek", SimpleNamespace(name="deepseek"))
    handler._open_stream = handler._end_stream = lambda: None
    handler._chunk = lambda text: True
    handler._stream_agent_setup({"model": "WinModel", "provider": "api:deepseek"})
    assert setup_flow.request(work)["host_action"] == "install_wine"


def test_dndc_tells_a_mac_user_where_to_get_wine():
    repo = Path(gui.__file__).resolve().parents[2]
    source = (repo / "models" / "DNDC" / "tools" / "run_dndc.py").read_text(encoding="utf-8")
    assert "Wine is required on Linux" not in source and "Darwin" in source
