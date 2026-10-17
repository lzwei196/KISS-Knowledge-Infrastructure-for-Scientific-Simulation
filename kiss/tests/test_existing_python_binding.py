"""Explicit existing-Python selection is identity checked and never installed into."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import catalog, cli, gui, install, install_locations, ki_guard, paths, runnable, setup
from kiss_cli.manifest import Manifest, Acquire


@pytest.fixture
def cfg(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    return paths.KissConfig.default(root)


def test_real_selected_interpreter_is_bound_without_managed_venv(cfg, monkeypatch):
    monkeypatch.setattr(install, "ensure_python_env", lambda *_a, **_k: pytest.fail("created a replacement venv"))
    selected = str(Path(sys.executable).absolute())
    step = setup.prepare_existing_python(cfg, cfg.root / "ki", selected)
    assert step.ok, step.detail
    assert cfg.python == selected
    assert cfg.roles["python_env"] == Path(sys.prefix)
    assert step.evidence["version"] == list(sys.version_info[:3])
    assert step.evidence["model_verified"] is False
    assert not (cfg.root / "venv").exists()
    assert not (cfg.root / "kiss.toml").exists(), "selection alone does not persist readiness"


@pytest.mark.parametrize("kind", ["missing", "directory", "invalid_executable", "unselected"])
def test_invalid_selection_does_not_change_config(cfg, kind):
    original = deepcopy(cfg)
    selected = cfg.root / kind
    if kind == "directory":
        selected.mkdir()
    elif kind == "invalid_executable":
        selected.write_bytes(b"not a Python executable")
        selected.chmod(0o755)
    step = setup.prepare_existing_python(cfg, cfg.root / "ki", "" if kind == "unselected" else str(selected))
    assert not step.ok and step.detail
    assert cfg == original
    assert not (cfg.root / "ki").exists()


@pytest.mark.parametrize("kind", ["no_marker", "duplicate_marker", "wrong_executable", "python2"])
def test_zero_exit_or_plausible_version_text_is_not_interpreter_identity(cfg, monkeypatch, kind):
    identity = {"executable": sys.executable, "prefix": sys.prefix, "version": list(sys.version_info[:3])}
    if kind == "wrong_executable":
        wrong = cfg.root / "other.exe"
        wrong.write_bytes(b"other")
        identity["executable"] = str(wrong)
    elif kind == "python2":
        identity["version"] = [2, 7, 18]
    payload = "GEOFORGE_PYTHON_IDENTITY=" + json.dumps(identity) + "\n"
    if kind == "no_marker":
        payload = "Python 3.12.10\n"
    elif kind == "duplicate_marker":
        payload *= 2
    monkeypatch.setattr(install, "_run", lambda *_a, **_k: (0, payload))
    before = deepcopy(cfg)
    step = setup.prepare_existing_python(cfg, cfg.root / "ki", sys.executable)
    assert not step.ok
    assert cfg == before


def test_active_ki_different_python_requires_fresh_workspace_without_probe(cfg, monkeypatch):
    old = cfg.root / "old-python.exe"
    old.write_bytes(b"retained identity")
    cfg.python = str(old)
    (cfg.root / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    live = cfg.root / "ki"
    live.mkdir()
    (live / "SKILL.md").write_text("# retained KI\n")
    before = {p: p.read_bytes() for p in cfg.root.rglob("*") if p.is_file()}
    monkeypatch.setattr(install, "_run", lambda *_a, **_k: pytest.fail("must reject migration before launch"))
    result = setup.prepare_existing_python(cfg, live, sys.executable)
    assert not result.ok and "new empty setup workspace" in result.detail
    assert all(p.read_bytes() == value for p, value in before.items())
    assert cfg.python == str(old)


def test_missing_existing_dependency_is_a_failure_not_a_skipped_install(cfg, monkeypatch):
    cfg.python = sys.executable
    seen = []
    def probe(argv, **kwargs):
        seen.append(argv)
        return 1, "required-package: no distribution metadata found"
    monkeypatch.setattr(install, "_run", probe)
    result = setup.check_existing_python_dependencies(Manifest(model="Demo", python_deps=["required-package"]), cfg)
    assert not result.ok and not result.skipped
    assert seen[0][:4] == [sys.executable, "-I", "-B", "-c"]
    assert json.loads(seen[0][-1]) == ["required-package"]
    assert "pip install" not in " ".join(seen[0])


@pytest.mark.parametrize("missing", [False, True])
def test_exact_runtime_probe_never_selects_a_fallback(cfg, monkeypatch, missing):
    cfg.python = str(cfg.root / "missing-python") if missing else sys.executable
    ki = SimpleNamespace(name="Demo", root=cfg.root, meta={"language": "python"})
    man = Manifest(model="Demo", binary_type="Python", acquire=Acquire(strategy="pip", produces="json"))
    monkeypatch.setattr(runnable, "select_python", lambda *_a, **_k: pytest.fail("selected fallback"))
    monkeypatch.setattr(runnable, "declared_imports", lambda *_a: ["json"])
    seen = []
    def imports(modules, python, *_a, **_k):
        seen.append(python)
        return []
    monkeypatch.setattr(runnable, "missing_imports", imports)
    verdict = runnable.check(ki, man, cfg, python=cfg.python, exact_python=True)
    assert verdict.usable is not missing
    assert seen == ([] if missing else [cfg.python])


def test_cli_custom_gui_workspace_cannot_silently_become_new_install(tmp_path, monkeypatch, capsys):
    library = tmp_path / "library/models/Demo"
    library.mkdir(parents=True)
    (library / "SKILL.md").write_text("# Demo\n")
    (library / "kiss.yaml").write_text(yaml.safe_dump({"kiss_manifest_version": 1, "model": "Demo"}))
    ki_guard.enroll(library)
    root = tmp_path / "custom-location/model"
    root.mkdir(parents=True)
    cfg = paths.KissConfig.default(root)
    cfg.python = sys.executable
    (root / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    install_locations.select_mode(tmp_path / "unrelated-gui-workroot", "Demo", "existing", sys.executable)
    install_locations.record("Demo", root, cfg, installation_mode="existing", existing_path=sys.executable)
    original = (root / "kiss.toml").read_bytes()
    monkeypatch.setattr(install, "_run", lambda *_a, **_k: pytest.fail("unknown selection must not execute"))
    args = SimpleNamespace(models=library.parent, model="Demo", workdir=str(root), python=None, relocation="none")
    assert cli.cmd_init(args) == 2
    assert "GeoForge GUI setup" in capsys.readouterr().out
    assert (root / "kiss.toml").read_bytes() == original
    assert not (root / "ki").exists()


@pytest.mark.parametrize("route", ["builtin", "cli"])
@pytest.mark.parametrize("missing_dependency", [False, True])
def test_existing_python_install_routes_never_pip_or_replace_selected_runtime(
        tmp_path, monkeypatch, route, missing_dependency):
    library = tmp_path / "library"
    source = library / "models/Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    dependencies = ["geoforge-test-no-such-distribution-8f5ae2"] if missing_dependency else ["pip"]
    manifest = {"kiss_manifest_version": 1, "model": "Demo", "binary_type": "Python",
                "acquire": {"strategy": "pip", "produces": "json"}, "python_deps": dependencies}
    (source / "kiss.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    helpers = library / "ki_tools_common/ki_tools_common"
    helpers.mkdir(parents=True)
    (helpers / "__init__.py").write_text("# fixture helpers\n", encoding="utf-8")
    ki_guard.enroll(source)
    workroot = tmp_path / "work"
    selected = str(Path(sys.executable).absolute())
    install_locations.select_mode(workroot, "Demo", "existing", selected)
    root = install_locations.resolve(workroot, "Demo")
    before = Path(selected).read_bytes()

    def forbidden(*_args, **_kwargs):
        pytest.fail("Existing Python must never be installed into or replaced")
    for name in ("ensure_python_env", "install_python_deps", "install_ki_tools_common", "acquire"):
        monkeypatch.setattr(install, name, forbidden)
    monkeypatch.setattr(setup, "prepare_python", forbidden)
    preflight_calls = []
    def preflight(_ki, python, cfg, **_kwargs):
        # CLI always includes a preflight stage; this test verifies routing,
        # not a scientific model, so no KI reader or model code is launched.
        assert python == cfg.python == selected
        preflight_calls.append(python)
        return install.Step("preflight", True, "routing fixture only")
    monkeypatch.setattr(install, "run_preflight", preflight)
    output = []
    if route == "builtin":
        gui._run_install(catalog.KI("Demo", source), Manifest.load(source / "kiss.yaml"), root,
                         output.append, library, installation_mode="existing",
                         existing_path=selected, installation_only=True)
        status = json.loads((root / "status.json").read_text("utf-8"))
        assert status["ok"] is not missing_dependency
        assert status["installation_only"] and status["verified_at"] is None
        assert preflight_calls == []
    else:
        args = SimpleNamespace(models=source.parent, model="Demo", workdir=str(root),
                               python=None, relocation="none")
        assert cli.cmd_init(args) == (2 if missing_dependency else 0)
        assert preflight_calls == ([] if missing_dependency else [selected])
    cfg = setup.load_runtime_config(root)
    assert cfg.python == selected and cfg.roles["python_env"] == Path(sys.prefix)
    record = json.loads((root / install_locations.RECORD_FILE).read_text("utf-8"))
    assert record["existing_path"] == record["resolved_existing_path"] == selected
    assert record["installation_mode"] == "existing"
    assert not (root / "venv").exists()
    assert Path(selected).read_bytes() == before
