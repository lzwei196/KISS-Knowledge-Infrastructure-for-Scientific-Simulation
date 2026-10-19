"""Isolated model-Python bootstrap, without model/package execution."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import install


def fixture_env(tmp_path, monkeypatch, *, existing=False, ready=False, invalid=False):
    target = tmp_path / "model/venv"
    python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    cfg = SimpleNamespace(roles={"python_env": target}, python="unchanged")
    state = {"ready": ready, "invalid": invalid, "calls": []}
    if existing:
        python.parent.mkdir(parents=True)
        python.touch()
        (target / "keep.txt").write_text("retained")
    def run(argv, **kwargs):
        state["calls"].append((argv, kwargs))
        if install._MODEL_ENV_PROBE in argv:
            if state["invalid"]:
                return 1, "Model virtual environment must not inherit system site packages"
            return 0, "__GEOFORGE_MODEL_ENV__=" + json.dumps({"pip_available": state["ready"]})
        if "venv" in argv:
            assert "--without-pip" in argv and "--system-site-packages" not in argv and "--clear" not in argv
            python.parent.mkdir(parents=True, exist_ok=True)
            python.touch()
            return 0, ""
        if "ensurepip" in argv:
            return 1, "No module named ensurepip"
        if "--python" in argv:
            assert argv[argv.index("--python") + 1] == str(python)
            assert argv[argv.index("--prefix") + 1] == str(target)
            assert argv[-1] == "pip" and "--require-virtualenv" in argv and "--no-deps" in argv
            assert kwargs["env"]["PIP_CONFIG_FILE"] == os.devnull
            state["ready"] = True
            return 0, ""
        pytest.fail("Unexpected bootstrap command: " + repr(argv))
    monkeypatch.setattr(install, "_run", run)
    return cfg, python, state


def test_missing_ensurepip_uses_base_pip_for_exact_isolated_target(tmp_path, monkeypatch):
    cfg, python, state = fixture_env(tmp_path, monkeypatch)
    result = install.ensure_python_env(cfg, base_python="base-python")
    assert result.ok, result.detail
    assert cfg.python == str(python)
    assert any("--python" in args for args, _ in state["calls"])


def test_partial_venv_preserved_and_only_missing_pip_repaired(tmp_path, monkeypatch):
    cfg, python, state = fixture_env(tmp_path, monkeypatch, existing=True)
    result = install.ensure_python_env(cfg, base_python="base-python")
    assert result.ok, result.detail
    assert (cfg.roles["python_env"] / "keep.txt").read_text() == "retained"
    assert not any("venv" in args for args, _ in state["calls"])


def test_complete_isolated_venv_is_reused_without_installs(tmp_path, monkeypatch):
    cfg, python, state = fixture_env(tmp_path, monkeypatch, existing=True, ready=True)
    result = install.ensure_python_env(cfg, base_python="base-python")
    assert result.ok and cfg.python == str(python)
    assert len(state["calls"]) == 1


def test_wrong_or_system_site_environment_fails_without_removing_files(tmp_path, monkeypatch):
    cfg, _, state = fixture_env(tmp_path, monkeypatch, existing=True, invalid=True)
    result = install.ensure_python_env(cfg, base_python="base-python")
    assert not result.ok and cfg.python == "unchanged"
    assert (cfg.roles["python_env"] / "keep.txt").exists()
    assert len(state["calls"]) == 1


def test_base_pip_failure_never_publishes_interpreter(tmp_path, monkeypatch):
    cfg, _, state = fixture_env(tmp_path, monkeypatch, existing=True)
    run = install._run
    def fail(argv, **kwargs):
        if "--python" in argv:
            return 2, "no such option: --python"
        return run(argv, **kwargs)
    monkeypatch.setattr(install, "_run", fail)
    result = install.ensure_python_env(cfg, base_python="base-python")
    assert not result.ok and "pip 22.3+" in result.detail
    assert cfg.python == "unchanged"


def test_probe_rejects_actual_system_interpreter(tmp_path):
    import sys
    valid, pip_ready, detail = install._model_env_probe(Path(sys.executable), tmp_path / "not-a-venv")
    assert not valid and not pip_ready and "expected isolated" in detail
