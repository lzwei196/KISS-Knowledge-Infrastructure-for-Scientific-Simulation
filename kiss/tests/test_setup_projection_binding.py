"""Runtime selection precedes immutable KI projection; no downloads/model runs."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import venv

import pytest

from kiss_cli import catalog, cli, gui, install, ki_guard, ki_updates, paths, setup
from kiss_cli.manifest import Manifest


@pytest.fixture
def case(tmp_path, monkeypatch, request):
    library = tmp_path / "library"
    source = library / "models" / "Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Harmless runtime binding fixture\n", encoding="utf-8")
    (source / "preflight_check.py").write_text(
        "import json, os, sys\nfrom pathlib import Path\n"
        "expected = 'KISSPATH_PYTHON_ENV/bin/python'\n"
        "common = Path('KISSPATH_KI_TOOLS_COMMON')\n"
        "norm = lambda p: os.path.normcase(os.path.abspath(p))\n"
        "helper = json.loads((common / 'binding.json').read_text())\n"
        "ok = norm(expected) == norm(sys.executable) == norm(helper['python'])\n"
        "print('projected=' + expected + '; actual=' + sys.executable)\n"
        "print('PREFLIGHT_REPORT=' + json.dumps({'checks': [{'critical': True, 'status': 'pass' if ok else 'fail'}]}))\n"
        "raise SystemExit(0 if ok else 1)\n", encoding="utf-8")
    common = library / "ki_tools_common"
    common.mkdir()
    (common / "binding.json").write_text('{"python": "KISSPATH_PYTHON_ENV/bin/python"}\n')
    if getattr(request, "param", "bundled") == "snapshot":
        (library / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
            "source_commit": "a" * 40, "content_sha256": "b" * 64,
            "trees": {"shared_tools": "c" * 40}}))
    root = tmp_path / "workspace"
    root.mkdir()
    cfg = paths.KissConfig.default(root)
    cfg.python, cfg.relocation = sys.executable, "none"
    (root / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    # A real isolated interpreter already exists; ensure_python_env must select
    # it before projecting either the KI or its shared helper's literals.
    venv.EnvBuilder(with_pip=False).create(cfg.roles["python_env"])
    selected = cfg.roles["python_env"] / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    ki = catalog.KI("Demo", source)
    ki_guard.enroll(source)
    monkeypatch.setattr(ki_guard, "_legacy_installation_roots", lambda: [])
    monkeypatch.setattr(install, "needs_shared_tools", lambda *_: True)
    monkeypatch.setattr(install, "check_system_deps", lambda *_: install.Step("system-deps", True))
    monkeypatch.setattr(install, "install_python_deps", lambda *a, **k: install.Step("python-deps", True))
    monkeypatch.setattr(install, "acquire", lambda *a, **k: (install.Step("acquire", True), None))
    # Only pip/network is replaced. Shared-helper projection and the native
    # harmless preflight run are real and retain their own independent checks.
    def helpers(config, repo):
        setup.prepare_common(config, repo)
        return install.Step("ki-tools-common", True)
    monkeypatch.setattr(install, "install_ki_tools_common", helpers)
    return SimpleNamespace(root=root, cfg=cfg, library=library, ki=ki,
                           selected=selected, man=Manifest(model="Demo"))


def run(case, route):
    if route == "gui":
        gui.run_install(case.ki, case.man, case.root, lambda _: None, case.library)
        return json.loads((case.root / "status.json").read_text())["ok"]
    args = SimpleNamespace(models=case.library / "models", model="Demo",
                           workdir=str(case.root), python=None, relocation="none")
    return cli.cmd_init(args) == 0


@pytest.mark.parametrize("case", ["bundled", "snapshot"], indirect=True)
@pytest.mark.parametrize("route", ["gui", "cli"])
def test_final_runtime_is_projected_into_ki_and_helpers(case, route):
    assert run(case, route)
    saved = paths.KissConfig.load(case.root)
    assert saved.python == str(case.selected)
    assert case.selected.as_posix() in (case.root / "ki/preflight_check.py").read_text()
    assert json.loads((saved.roles["ki_tools_common"] / "binding.json").read_text())["python"] == case.selected.as_posix()
    before = ki_guard.require_intact(case.root / "ki")
    assert run(case, route), "a repeated setup must preserve its original binding"
    assert ki_guard.require_intact(case.root / "ki") == before


@pytest.mark.parametrize("route", ["gui", "cli"])
@pytest.mark.parametrize("failure", ["python", "helpers"])
def test_failed_binding_preparation_does_not_enroll_stale_ki(case, monkeypatch, route, failure):
    if failure == "python":
        monkeypatch.setattr(install, "ensure_python_env", lambda *a, **k: install.Step("python-env", False, "fixture environment unavailable"))
    else:
        monkeypatch.setattr(install, "install_ki_tools_common", lambda *a, **k: install.Step("ki-tools-common", False, "fixture helper unavailable"))
    assert not run(case, route)
    assert not (case.root / "ki/SKILL.md").exists()
    assert not ki_guard.is_managed(case.root / "ki")


@pytest.mark.parametrize("case", ["bundled", "snapshot"], indirect=True)
def test_agent_prepare_then_builtin_keeps_the_finalized_binding(case):
    live, cfg = setup.prepare(case.ki, case.man, case.root, case.library, case.library / "models")
    assert cfg.python == str(case.selected)
    assert case.selected.as_posix() in live.preflight.read_text()
    assert run(case, "gui")


@pytest.mark.parametrize("route", ["gui", "cli"])
def test_active_explicit_interpreter_is_preserved_even_if_managed_venv_exists(case, monkeypatch, route):
    setup.prepare_common(case.cfg, case.library)
    (case.root / paths.CONFIG_NAME).write_text(case.cfg.dumps(), encoding="utf-8")
    setup.materialise_active(case.ki.root, case.root / "ki", case.cfg)
    before = (case.root / "ki/preflight_check.py").read_bytes()
    monkeypatch.setattr(install, "ensure_python_env", lambda *a, **k: pytest.fail("active runtime must not be replaced"))
    assert run(case, route)
    assert paths.KissConfig.load(case.root).python == sys.executable
    assert (case.root / "ki/preflight_check.py").read_bytes() == before


@pytest.mark.parametrize("route", ["gui", "cli", "prepare"])
@pytest.mark.parametrize("missing", ["config", "interpreter"])
def test_active_missing_runtime_never_falls_back_or_rewrites_config(case, monkeypatch, route, missing):
    setup.prepare_common(case.cfg, case.library)
    setup.materialise_active(case.ki.root, case.root / "ki", case.cfg)
    config = case.root / paths.CONFIG_NAME
    if missing == "config":
        config.unlink()
        before = None
    else:
        case.cfg.python = str(case.root / "absent-python.exe")
        config.write_text(case.cfg.dumps(), encoding="utf-8")
        before = config.read_bytes()
    baseline = ki_guard.require_intact(case.root / "ki")
    monkeypatch.setattr(install, "ensure_python_env", lambda *a, **k: pytest.fail("must not replace broken saved runtime"))
    if route == "prepare":
        with pytest.raises(ValueError, match="saved runtime|unavailable"):
            setup.prepare(case.ki, case.man, case.root, case.library, case.library / "models")
    else:
        assert not run(case, route)
    assert (config.read_bytes() if config.exists() else None) == before
    assert ki_guard.require_intact(case.root / "ki") == baseline


def test_new_explicit_cli_python_is_not_replaced_by_managed_venv(case, monkeypatch):
    monkeypatch.setattr(install, "ensure_python_env", lambda *a, **k: pytest.fail("explicit runtime must be preserved"))
    args = SimpleNamespace(models=case.library / "models", model="Demo",
                           workdir=str(case.root), python=sys.executable, relocation="none")
    assert cli.cmd_init(args) == 0
    assert paths.KissConfig.load(case.root).python == sys.executable


def test_new_custom_environment_is_never_recreated(case, monkeypatch):
    outside = case.root.parent / "external-environment"
    outside.mkdir()
    (outside / "keep.txt").write_text("user environment")
    case.cfg.roles["python_env"] = outside
    monkeypatch.setattr(install, "ensure_python_env", lambda *a, **k: pytest.fail("external runtime must not be recreated"))
    assert setup.prepare_python(case.cfg, case.root / "ki").ok
    assert case.cfg.python == sys.executable
    assert (outside / "keep.txt").read_text() == "user environment"


@pytest.mark.parametrize("case", ["bundled", "snapshot"], indirect=True)
def test_cached_helpers_with_old_frozen_python_are_not_silently_reused(case):
    cached = setup.prepare_common(case.cfg, case.library)
    before = (cached / "binding.json").read_bytes()
    if (case.library / ki_updates.SNAPSHOT_MANIFEST).is_file():
        # No KI has been enrolled yet. Content/runtime-addressed helpers can
        # select a new immutable revision instead of reusing stale literals.
        assert run(case, "gui")
        saved = paths.KissConfig.load(case.root)
        assert saved.roles["ki_tools_common"] != cached
        assert json.loads((saved.roles["ki_tools_common"] / "binding.json").read_text())["python"] == case.selected.as_posix()
    else:
        with pytest.raises(ValueError, match="runtime binding"):
            run(case, "gui")
        assert not (case.root / "ki/SKILL.md").exists()
    assert (cached / "binding.json").read_bytes() == before


@pytest.mark.parametrize("route", ["gui", "cli", "prepare"])
def test_active_malformed_config_is_preserved_and_never_defaults(case, monkeypatch, route):
    setup.prepare_common(case.cfg, case.library)
    setup.materialise_active(case.ki.root, case.root / "ki", case.cfg)
    config = case.root / paths.CONFIG_NAME
    config.write_text("[kiss\nroot='broken'", encoding="utf-8")
    before = config.read_bytes()
    monkeypatch.setattr(install, "ensure_python_env", lambda *a, **k: pytest.fail("malformed config must not default"))
    if route == "gui":
        assert not run(case, route)
        assert json.loads((case.root / "status.json").read_text())["primary_error"]["name"] == "runtime-config"
    else:
        with pytest.raises(ValueError):
            if route == "prepare":
                setup.prepare(case.ki, case.man, case.root, case.library, case.library / "models")
            else:
                run(case, route)
    assert config.read_bytes() == before


@pytest.mark.parametrize("route", ["gui", "cli", "prepare"])
@pytest.mark.parametrize("field", ["python", "root"])
def test_active_missing_identity_field_is_not_filled_from_defaults(case, monkeypatch, route, field):
    setup.prepare_common(case.cfg, case.library)
    setup.materialise_active(case.ki.root, case.root / "ki", case.cfg)
    config = case.root / paths.CONFIG_NAME
    config.write_text("\n".join(line for line in case.cfg.dumps().splitlines()
                               if not line.startswith(field + " =")), encoding="utf-8")
    before = config.read_bytes()
    monkeypatch.setattr(install, "_run", lambda *a, **k: pytest.fail("invalid saved binding must not launch a probe"))
    if route == "gui":
        assert not run(case, route)
        failure = json.loads((case.root / "status.json").read_text())["primary_error"]
        assert failure["name"] == "runtime-config" and "explicit nonempty kiss" in failure["detail"]
    else:
        with pytest.raises(ValueError, match="explicit nonempty kiss"):
            if route == "prepare":
                setup.prepare(case.ki, case.man, case.root, case.library, case.library / "models")
            else:
                run(case, route)
    assert config.read_bytes() == before


def test_default_environment_alias_is_not_recreated(case, monkeypatch):
    # Use an unused workspace; the fixture's own real venv remains untouched.
    fresh = case.root / "fresh"
    fresh.mkdir()
    cfg = paths.KissConfig.default(fresh)
    cfg.python = sys.executable
    (fresh / "venv").symlink_to(case.cfg.roles["python_env"], target_is_directory=True)
    monkeypatch.setattr(install, "ensure_python_env", lambda *a, **k: pytest.fail("aliased environment must not be recreated"))
    result = setup.prepare_python(cfg, fresh / "ki")
    assert not result.ok and "link" in result.detail
    assert case.selected.is_file()


def test_saved_root_redirect_fails_before_environment_or_projection(case, monkeypatch):
    case.cfg.root = case.root.parent / "unrelated-workspace"
    monkeypatch.setattr(install, "ensure_python_env", lambda *a, **k: pytest.fail("redirect must fail before runtime changes"))
    result = setup.prepare_python(case.cfg, case.root / "ki")
    assert not result.ok and "different workspace root" in result.detail
    assert not (case.root / "ki").exists()


@pytest.mark.parametrize("route", ["gui", "cli"])
def test_frozen_host_projects_the_real_selected_interpreter(case, monkeypatch, route):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(install, "find_base_python", lambda: sys.executable)
    assert run(case, route)
    saved = paths.KissConfig.load(case.root)
    assert saved.python == str(case.selected)
    assert case.selected.as_posix() in (case.root / "ki/preflight_check.py").read_text()
