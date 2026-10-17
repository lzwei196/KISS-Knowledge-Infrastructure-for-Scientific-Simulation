"""Real model subprocess imports must not inherit the desktop source launcher.

No scientific model, package download or package installer is executed. The
editable-import test creates a real isolated venv and a local .pth binding.
"""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import venv

import pytest

from kiss_cli import api, install, paths


def package(root, value):
    target = root / "ki_tools_common"
    target.mkdir(parents=True)
    (target / "__init__.py").write_text(f"ORIGIN = {value!r}\n", encoding="utf-8")
    (target / "units.py").write_text("VALUE = 1\n", encoding="utf-8")


def shadow(tmp_path, monkeypatch):
    host = tmp_path / "host-imports"
    package(host, "host")
    (host / "desktop_only_dependency.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(host))
    monkeypatch.setenv("PYTHONUSERBASE", str(tmp_path / "host-usersite"))
    return host


def test_model_environment_removes_host_python_configuration_only(tmp_path):
    inherited = {"PYTHONPATH": "host", "PYTHONHOME": "host-home",
                 "PYTHONUSERBASE": "host-site", "__PYVENV_LAUNCHER__": "host-python",
                 "PYTHONEXECUTABLE": "host-executable", "PYTHONSTARTUP": "host-startup",
                 "PATH": "toolchain", "HTTPS_PROXY": "http://proxy.example",
                 "GEOFORGE_EXECUTION_TURN": "current-turn"}
    cfg = SimpleNamespace(roles={})
    actual = paths.with_ki_tools_common(cfg, inherited)
    assert actual == {"PATH": "toolchain", "HTTPS_PROXY": "http://proxy.example",
                      "GEOFORGE_EXECUTION_TURN": "current-turn", "PYTHONNOUSERSITE": "1"}
    assert inherited["PYTHONPATH"] == "host", "parent/host dispatch environment is not mutated"


@pytest.mark.parametrize("supervised", [False, True])
def test_real_install_child_cannot_import_desktop_only_package(tmp_path, monkeypatch, supervised):
    shadow(tmp_path, monkeypatch)
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "nonexistent-host-python"))
    command = [sys.executable, "-c", "import importlib.util,sys; "
               "print(importlib.util.find_spec('desktop_only_dependency')); print(sys.prefix)"]
    if supervised:
        with install.cancellation_context(tmp_path, stop=lambda: False):
            code, output = install._run(command, cwd=tmp_path)
    else:
        code, output = install._run(command, cwd=tmp_path)
    assert code == 0, output
    assert output.splitlines()[0] == "None"


def test_explicit_selected_helper_environment_survives_install_child(tmp_path, monkeypatch):
    shadow(tmp_path, monkeypatch)
    common = tmp_path / "workspace-helper"
    package(common, "workspace")
    cfg = SimpleNamespace(roles={"ki_tools_common": common})
    environment = paths.with_ki_tools_common(cfg, {})
    code, output = install._run(
        [sys.executable, "-c", "import ki_tools_common; print(ki_tools_common.ORIGIN)"],
        cwd=tmp_path, env=environment)
    assert code == 0 and output.strip() == "workspace", output
    assert environment["PYTHONPATH"] == str(common.resolve())


def test_shared_helper_probe_checks_actual_editable_install_not_host_shadow(tmp_path, monkeypatch):
    library = tmp_path / "library"
    package(library / "ki_tools_common", "workspace")
    root = tmp_path / "workspace"
    root.mkdir()
    cfg = paths.KissConfig.default(root)
    environment = root / "venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    cfg.python = str(environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    real_run = install._run
    code, output = real_run([cfg.python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"])
    assert code == 0, output
    site_packages = Path(output.strip())
    # Equivalent local import binding to an editable install, without invoking pip.
    (site_packages / "workspace-helper.pth").write_text(str(root / "ki_tools_common") + "\n")
    host = shadow(tmp_path, monkeypatch)
    installs = []

    def skip_installer(command, *args, **kwargs):
        if command[1:4] == ["-m", "pip", "install"]:
            installs.append(command)
            return 0, "local fixture dependency already present"
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(install, "_run", skip_installer)
    result = install.install_ki_tools_common(cfg, library)
    assert result.ok, result.detail
    assert installs
    assert os.environ["PYTHONPATH"] == str(host)


@pytest.mark.parametrize("with_helper", [False, True])
def test_api_setup_child_has_only_selected_model_imports(tmp_path, monkeypatch, with_helper):
    host = shadow(tmp_path, monkeypatch)
    root = tmp_path / "workspace"
    root.mkdir()
    common = root / "helpers"
    roles = {"binaries": root / "binaries"}
    if with_helper:
        package(common, "workspace")
        roles["ki_tools_common"] = common
    script = root / "check_environment.py"
    script.write_text(
        "import json,os,importlib.util\n"
        "row={'host_module':importlib.util.find_spec('desktop_only_dependency') is not None,"
        "'pythonpath':os.environ.get('PYTHONPATH')}\n"
        + ("import ki_tools_common\nrow['origin']=ki_tools_common.ORIGIN\n" if with_helper else "")
        + "print('RESULT='+json.dumps(row))\n", encoding="utf-8")
    cfg = SimpleNamespace(root=root, python=sys.executable, roles=roles)
    result = api.execute_tool("run_setup_command", {"argv": [sys.executable, str(script)]},
                              SimpleNamespace(root=root / "ki"), cfg, setup_mode=True)
    assert "exit_code=0" in result, result
    row = json.loads(next(line[7:] for line in result.splitlines() if line.startswith("RESULT=")))
    assert row["host_module"] is False
    assert row["pythonpath"] == (str(common.resolve()) if with_helper else None)
    if with_helper:
        assert row["origin"] == "workspace"
    assert os.environ["PYTHONPATH"] == str(host)
