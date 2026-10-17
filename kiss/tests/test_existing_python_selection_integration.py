"""User-selected Python survives real setup and project KI projection.

The first case runs only the selected interpreter's isolated identity probe.
No model, provider, pip install or scientific preflight is invoked.
"""
import ast
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import pytest

from kiss_cli import gui, install, install_locations, ki_adaptations, ki_fresh_paths
from kiss_cli import paths, project_verification, setup
from kiss_cli.catalog import KI
from kiss_cli.manifest import Acquire, Manifest


REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def workspace(monkeypatch):
    # Real shared helpers have long paths; keep Windows test scaffolding short.
    with tempfile.TemporaryDirectory(prefix="gf-pysel-") as directory:
        root = Path(directory).resolve()
        for name, child in (
            ("GEOFORGE_FLOW_KEYS", "keys"),
            ("GEOFORGE_KI_GUARD_HOME", "guard"),
            ("GEOFORGE_KI_ADAPTATION_HOME", "adaptations"),
            ("GEOFORGE_KI_VERIFICATION_HOME", "verification"),
        ):
            monkeypatch.setenv(name, str(root / child))
        yield root


def handler_for(root):
    handler = object.__new__(gui.Handler)
    handler.repo_root = handler.library_root = REPO
    handler.workroot = root / "work"
    handler.catalog = SimpleNamespace(models_dir=REPO / "models")
    return handler


def reject_mutating_runtime_operations(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Existing Python setup must not create an environment, install packages or run a model/preflight")
    for name in ("ensure_python_env", "install_python_deps", "install_ki_tools_common",
                 "acquire", "run_preflight"):
        monkeypatch.setattr(install, name, forbidden)
    monkeypatch.setattr(setup, "prepare_python", forbidden)


def assert_selected_chain(root, monkeypatch, selected, prefix, probe):
    handler = handler_for(root)
    unselected_default = root / "unselected-default-python.exe"
    unselected_default.write_bytes(b"host default fixture; must not run for this KI")
    assert unselected_default != selected
    monkeypatch.setattr(install, "find_base_python", lambda: str(unselected_default))
    ki = KI("WOFOST", REPO / "models/WOFOST")
    source_before = ki_fresh_paths.tree_files(ki.root)
    selection = install_locations.select_mode(handler.workroot, ki.name, "existing", selected)
    assert selection["existing_path"] == str(selected)
    assert install_locations.info(handler.workroot, ki.name)["existing_path"] == str(selected)
    target = install_locations.resolve(handler.workroot, ki.name)
    selected_before = hashlib.sha256(selected.read_bytes()).hexdigest()
    events = []
    monkeypatch.setattr(install, "_run", probe(events))
    reject_mutating_runtime_operations(monkeypatch)
    original_common = setup.prepare_common
    original_materialise = setup.materialise_active

    def common(cfg, repo):
        assert cfg.python == str(selected)
        assert cfg.roles["python_env"] == prefix
        assert events and events[0] == "identity-probe"
        events.append("helpers")
        return original_common(cfg, repo)

    def materialise(source, live, cfg, **kwargs):
        assert cfg.python == str(selected)
        assert cfg.roles["python_env"] == prefix
        assert events == ["identity-probe", "helpers"]
        assert not (target / "venv").exists()
        events.append("KI-projection")
        return original_materialise(source, live, cfg, **kwargs)

    monkeypatch.setattr(setup, "prepare_common", common)
    monkeypatch.setattr(setup, "materialise_active", materialise)
    live, cfg = handler._prepare_setup_workspace(ki, target)
    assert events == ["identity-probe", "helpers", "KI-projection"]
    assert cfg.python == str(selected)
    assert cfg.roles["python_env"] == prefix
    saved = paths.KissConfig.load(target)
    assert saved.python == cfg.python and saved.roles == cfg.roles
    record = json.loads((target / install_locations.RECORD_FILE).read_text("utf-8"))
    assert record["existing_path"] == record["resolved_existing_path"] == cfg.python
    assert record["installation_mode"] == "existing" and record["verified"] is False
    lineage = ki_adaptations.projection(live.root, cfg)
    assert lineage["path_projection"]["runtime"]["selected_python"]["path"] == cfg.python

    # A new project's normal GUI entrypoint must pick up the saved selection;
    # passing cfg manually here would miss the original integration defect.
    project = root / "project 中文"
    working, project_cfg = handler._session_workspace(project, ki)
    assert project_cfg.python == str(selected)
    assert project_cfg.roles["python_env"] == prefix
    # The neutral project default may differ; per-model runtime selection must
    # remain authoritative instead of falling back to this host default.
    assert paths.KissConfig.load(project).python == str(unselected_default)
    proof = ki_adaptations.projection(working.root, project_cfg)["path_projection"]
    ki_fresh_paths.require_fresh_current(proof, candidate_root=working.root)
    assert proof["runtime"]["selected_python"]["path"] == str(selected)
    values = {n.targets[0].id: n.value for n in ast.parse(
        (working.root / "preflight_check.py").read_text("utf-8")).body
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
    assert ast.literal_eval(values["PYTHON"]) == str(selected).replace("\\", "/")
    assert ast.literal_eval(values["KI_TOOLS_COMMON"]) == str(project_cfg.roles["ki_tools_common"]).replace("\\", "/")
    assert "tools/s3_weather_prep/convert_vic_to_pcse_weather.py" in ast.literal_eval(values["TOOL_FILES"])
    assert not project_verification.status(project, working)["can_run"]
    before = ki_fresh_paths.tree_files(working.root)
    reopened, reopened_cfg = handler._session_workspace(project, ki)
    assert reopened_cfg.python == str(selected) and reopened.root == working.root
    assert ki_fresh_paths.tree_files(working.root) == before
    assert ki_fresh_paths.tree_files(ki.root) == source_before
    assert hashlib.sha256(selected.read_bytes()).hexdigest() == selected_before
    assert not (target / "venv").exists()
    assert not (project / "venv").exists()
    assert events.count("identity-probe") == 1


def test_actual_selected_interpreter_is_bound_before_projection_and_retained_in_project(workspace, monkeypatch):
    selected = Path(sys.executable).absolute()
    prefix = Path(sys.prefix)
    real_run = install._run

    def probe(events):
        def checked(argv, **kwargs):
            assert argv[:4] == [str(selected), "-I", "-B", "-c"]
            assert len(argv) == 5 and "GEOFORGE_PYTHON_IDENTITY=" in argv[4]
            assert "pip" not in argv[4] and "subprocess" not in argv[4]
            events.append("identity-probe")
            return real_run(argv, **kwargs)
        return checked

    assert_selected_chain(workspace, monkeypatch, selected, prefix, probe)


def test_posix_style_venv_spelling_survives_selection_setup_and_project(workspace, monkeypatch):
    # Simulate link resolution on every platform without needing Windows
    # symlink privileges. The selected venv and base remain distinct paths.
    prefix = workspace / "external-venv"
    selected = prefix / "bin/python"
    selected.parent.mkdir(parents=True)
    selected.write_bytes(b"identity-probe fixture; never executed")
    base = workspace / "base/python"
    base.parent.mkdir()
    base.write_bytes(b"base interpreter; never selected or executed")
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        return base if path == selected else original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    assert selected.resolve() != selected

    def probe(events):
        def checked(argv, **kwargs):
            assert argv[:4] == [str(selected), "-I", "-B", "-c"]
            events.append("identity-probe")
            return 0, "GEOFORGE_PYTHON_IDENTITY=" + json.dumps({
                "executable": str(selected), "prefix": str(prefix), "version": [3, 12, 10]})
        return checked

    assert_selected_chain(workspace, monkeypatch, selected, prefix, probe)


def test_native_existing_install_keeps_its_original_setup_route(workspace, monkeypatch):
    handler = handler_for(workspace)
    ki = KI("NativeCase", workspace / "native-ki")
    selected = workspace / "native-engine.exe"
    selected.write_bytes(b"native selection fixture; never executed")
    install_locations.select_mode(handler.workroot, ki.name, "existing", selected)
    man = Manifest(model=ki.name, binary_type="native",
                   acquire=Acquire(strategy="download", produces="engine.exe"))
    handler._manifest = lambda _: man
    seen = []

    def prepare(*args, **kwargs):
        seen.append((args, kwargs))
        return "native-setup-result"

    monkeypatch.setattr(setup, "prepare", prepare)
    target = install_locations.resolve(handler.workroot, ki.name)
    assert handler._prepare_setup_workspace(ki, target) == "native-setup-result"
    assert len(seen) == 1 and seen[0][0][:3] == (ki, man, target)
    assert seen[0][1] == {}
