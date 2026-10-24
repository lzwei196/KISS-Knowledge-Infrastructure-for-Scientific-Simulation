"""Projected KIs find model software where a desktop installs it, not where the server kept it."""
import ast
import importlib.util
import os
import sys
from pathlib import Path

import pytest
import yaml

from kiss_cli import paths, port

REPO = Path(__file__).resolve().parents[2]
LIBRARY = REPO / "models"
MARRMOT_SCRIPTS = ("tools/calib_run.py", "run_and_score_verify2_bengbu.py", "run_and_score_verify2_xixian.py",
                   "run_and_score_verify2_zhimenda.py", "run_and_score_verify_caravan_all47.py",
                   "run_and_score_verify_caravan_both.py")


def project(tmp_path, name):
    """A project copy of KI ``name`` whose software lives in a separate shared setup."""
    shared = tmp_path / "shared"
    cfg = paths.KissConfig.default(tmp_path / "project")
    cfg.roles["binaries"] = shared / "binaries"
    cfg.python = sys.executable
    home = Path(cfg.roles["ki_root"]) / name
    port.materialise(LIBRARY / name, home / "ki", cfg, ki_target=home / "ki", model=name)
    (home / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    return cfg, home / "ki"


def load(path, name, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "ki_tools_common"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_landlab_preflight_checks_the_package_its_interpreter_imports(tmp_path, monkeypatch):
    _cfg, ki = project(tmp_path, "Landlab")
    site = tmp_path / "site"
    (site / "landlab").mkdir(parents=True)
    (site / "landlab" / "__init__.py").write_text('__version__ = "2.10.1"\n', encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(site))
    preflight = load(ki / "preflight_check.py", "landlab_preflight", monkeypatch)

    preflight.check_manifest_package()
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "empty"))
    preflight.check_manifest_package()

    installed, missing = preflight.checks
    assert installed["status"] == "pass"
    assert Path(installed["subject"]) == (site / "landlab" / "__init__.py").resolve()
    assert missing["status"] == "fail" and "source/repo/src/landlab" in missing["subject"].replace("\\", "/")


def test_landlab_installs_the_version_its_preflight_requires():
    manifest = yaml.safe_load((REPO / "kiss" / "manifests" / "Landlab.yaml").read_text(encoding="utf-8"))
    tree = ast.parse((LIBRARY / "Landlab" / "preflight_check.py").read_text(encoding="utf-8"))
    required = next(node.value.value for node in tree.body if isinstance(node, ast.Assign)
                    and getattr(node.targets[0], "id", None) == "EXPECTED_VERSION")
    assert manifest["acquire"]["package"] == f"landlab=={required}"
    assert manifest["python_deps"] == [f"landlab=={required}"]


def test_marrmot_scripts_use_the_installed_source(tmp_path, monkeypatch):
    cfg, ki = project(tmp_path, "MARRMoT")
    source = Path(cfg.roles["binaries"]) / "MARRMoT" / "source" / "repo" / "MARRMoT"
    (source / "Models" / "Model files").mkdir(parents=True)
    (source / "Models" / "Model files" / "MARRMoT_model.m").write_text("% model\n", encoding="utf-8")
    monkeypatch.delenv("MARRMOT_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    # A KI run is its own process; here an earlier test may have imported another copy's helper.
    monkeypatch.delitem(sys.modules, "octave_runtime", raising=False)

    run = load(ki / "tools" / "calib_run.py", "marrmot_calib_source", monkeypatch)

    assert Path(run.MARRMOT_SRC) == source
    for script in MARRMOT_SCRIPTS:
        tree = ast.parse((ki / script).read_text(encoding="utf-8"))
        assigned = [node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                    and getattr(node.targets[0], "id", None) == "MARRMOT_SRC"]
        assert len(assigned) == 1 and isinstance(assigned[0], ast.BoolOp), script
        call = assigned[0].values[0]
        assert isinstance(call, ast.Call) and call.func.id == "marrmot_source", script
