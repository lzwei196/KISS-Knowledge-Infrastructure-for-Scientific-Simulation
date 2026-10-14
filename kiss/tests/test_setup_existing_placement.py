"""An explicit existing distribution is placed before the setup agent runs."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import (api, catalog, cli, gui, install, install_locations, ki_guard,
                      paths, providers, runnable, setup, setup_jobs)


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "user-home"))
    library = tmp_path / "library"
    source = library / "models/DSSAT"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# DSSAT fixture\n")
    executable = "dscsm048" if os.name == "nt" else "dscsm048.exe"
    (source / "preflight_check.py").write_text(
        'from pathlib import Path\n'
        f'DSSAT_BINARY = Path("KISSPATH_HOME/DSSAT/build/bin/{executable}")\n'
        'DSSAT_DATA = Path("KISSPATH_HOME/DSSAT/Data")\n'
        'def check_file(path, executable=False): return path.is_file()\n'
        'check_file(DSSAT_BINARY, executable=True)\n')
    (source / "kiss.yaml").write_text(yaml.safe_dump({
        "kiss_manifest_version": 1, "model": "DSSAT", "install_dir": "DSSAT",
        "acquire": {"strategy": "build", "produces": "build/bin/dscsm048.exe"}}))
    workroot = tmp_path / "work"
    root = workroot / "dssat"
    root.mkdir(parents=True)
    cfg = paths.KissConfig.default(root)
    cfg.python = sys.executable
    cfg.relocation = "none"
    (root / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    ki = catalog.KI("DSSAT", source)
    ki_guard.enroll(source)
    setup.materialise_active(source, root / "ki", cfg)
    live = catalog.KI("DSSAT", root / "ki")
    distribution = tmp_path / "official/DSSAT"
    binary = distribution / "build/bin/dscsm048.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"MZ harmless fixture; never executed")
    (distribution / "Data/Genotype").mkdir(parents=True)
    (distribution / "Data/MODEL.ERR").write_bytes(b"official error messages")
    (distribution / "Data/Genotype/demo.CUL").write_bytes(b"official cultivar")
    handler = object.__new__(gui.Handler)
    handler.repo_root = handler.library_root = library
    handler.workroot = workroot
    handler.catalog = SimpleNamespace(models_dir=library / "models")
    handler._ki = lambda name: ki
    handler._validate_binding = lambda req: None
    handler._helper_repo_root = lambda: library
    handler._open_stream = handler._end_stream = lambda: None
    output = []
    handler._chunk = lambda piece: output.append(piece) or True
    handler._json = lambda *args: pytest.fail(str(args))
    (root / "CLAUDE.md").write_text("Fixture setup contract")
    monkeypatch.setattr(setup, "prepare", lambda *args: (live, cfg))
    monkeypatch.setattr(gui.prompt, "compose", lambda *args, **kwargs: "Fixture prompt")
    monkeypatch.setattr(setup, "agent_task", lambda *args, **kwargs: "Fixture task")
    install_locations.select_mode(workroot, "DSSAT", "existing", distribution)
    return SimpleNamespace(handler=handler, ki=ki, live=live, cfg=cfg,
                           root=root, workroot=workroot, distribution=distribution,
                           binary=binary, output=output,
                           prefix=root / "binaries/DSSAT")


def source_bytes(case):
    return {str(p.relative_to(case.distribution)): p.read_bytes()
            for p in case.distribution.rglob("*") if p.is_file()}


def assert_placed(case):
    for relative, expected in source_bytes(case).items():
        assert (case.prefix / relative).read_bytes() == expected
        assert (case.root / "DSSAT" / relative).read_bytes() == expected


def run(case, provider="api:deepseek", **kwargs):
    case.handler._stream_agent_setup({"model": "DSSAT", "provider": provider, **kwargs})
    return setup_jobs.status(case.workroot, "DSSAT")


@pytest.mark.parametrize("kind", ["api", "cli"])
@pytest.mark.parametrize("selection", ["folder", "binary"])
def test_explicit_distribution_precedes_first_preflight_and_provider(case, monkeypatch, kind, selection):
    if selection == "binary":
        install_locations.select_mode(case.workroot, "DSSAT", "existing", case.binary)
    before, seen = source_bytes(case), []
    config_before = (case.root / "kiss.toml").read_bytes()
    ki_before = (case.live.root / "preflight_check.py").read_bytes()

    def preflight(*args, **kwargs):
        assert_placed(case)
        seen.append("preflight")
        return install.Step("preflight", False, "Remaining fixture prerequisites")

    def provider(*args, **kwargs):
        assert_placed(case)
        seen.append("provider")
        yield "Provider inspected the already-placed distribution.\n"

    monkeypatch.setattr(install, "run_preflight", preflight)
    if kind == "api":
        monkeypatch.setattr(api, "run", provider)
        want = "api:deepseek"
    else:
        fake = providers.Provider(name="fixture", binary="fixture", argv=["fixture"],
                                  output="text", label="Fixture CLI")
        monkeypatch.setitem(providers.PROVIDERS, "fixture", fake)
        monkeypatch.setattr(providers, "run", provider)
        want = "cli:fixture"
    for _ in range(2):
        state = run(case, want)
        assert state["state"] == "failed", (state, case.output)
    assert seen == ["preflight", "provider", "preflight"] * 2, case.output
    assert source_bytes(case) == before
    assert (case.root / "kiss.toml").read_bytes() == config_before
    assert (case.live.root / "preflight_check.py").read_bytes() == ki_before
    ki_guard.require_intact(case.live.root)
    assert not case.handler._status_for(case.ki)["can_run"]


def test_existing_distribution_conflict_stops_before_preflight_or_provider(case, monkeypatch):
    conflict = case.prefix / "Data/MODEL.ERR"
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"different existing distribution")
    before = source_bytes(case)
    monkeypatch.setattr(install, "run_preflight", lambda *a, **kw: pytest.fail("preflight after conflict"))
    monkeypatch.setattr(api, "run", lambda *a, **kw: pytest.fail("agent after conflict"))
    state = run(case)
    assert state["state"] == "failed" and "conflict" in state["detail"].lower()
    assert conflict.read_bytes() == b"different existing distribution"
    assert not (case.prefix / "build/bin/dscsm048.exe").exists()
    assert source_bytes(case) == before


@pytest.mark.parametrize("origin", ["agent_record", "discovery"])
def test_discovered_or_agent_recorded_candidate_is_not_automatically_placed(case, monkeypatch, origin):
    index = install_locations._read_index(case.workroot)
    index["models"]["dssat"]["existing_path"] = None
    install_locations._write_index(case.workroot, index)
    if origin == "agent_record":
        (case.root / install_locations.RECORD_FILE).write_text(json.dumps({
            "resolved_existing_path": str(case.distribution),
            "discovery_candidates": [str(case.distribution)]}))
    else:
        monkeypatch.setattr(gui.setup_discovery, "discover", lambda *a, **kw: {
            "candidates": [str(case.distribution)], "complete": True})
    seen = []

    def preflight(*args, **kwargs):
        assert not case.prefix.exists()
        assert not (case.root / "DSSAT").exists()
        seen.append(True)
        return install.Step("preflight", False, "Agent must inspect candidate")

    monkeypatch.setattr(install, "run_preflight", preflight)
    monkeypatch.setattr(api, "run", lambda *a, **kw: iter(["Candidate inspection pending.\n"]))
    assert run(case)["state"] == "failed"
    assert seen == [True, True], case.output
    assert not (case.root / ".geoforge/existing-placement.json").exists()


def test_installation_only_places_before_provider_without_scientific_preflight(case, monkeypatch):
    seen = []
    def provider(*args, **kwargs):
        assert_placed(case)
        seen.append(True)
        yield "Ready for cheap startup probe.\n"
    monkeypatch.setattr(api, "run", provider)
    monkeypatch.setattr(install, "run_preflight", lambda *a, **kw: pytest.fail("scientific preflight"))
    monkeypatch.setattr(runnable, "check", lambda *a, **kw: runnable.Verdict(
        "DSSAT", present=True, shaped=True, linked=True, responds=True))
    assert run(case, installation_only=True)["state"] == "completed", case.output
    assert seen == [True]
    assert not case.handler._status_for(case.ki)["can_run"]


def test_stop_during_selected_placement_never_reaches_preflight(case, monkeypatch):
    original = install.place_agent_install
    def stop_then_place(*args, **kwargs):
        state = setup_jobs.status(case.workroot, "DSSAT")
        setup_jobs.stop(case.workroot, "DSSAT", state["id"])
        return original(*args, **kwargs)
    monkeypatch.setattr(install, "place_agent_install", stop_then_place)
    monkeypatch.setattr(install, "run_preflight", lambda *a, **kw: pytest.fail("preflight after Stop"))
    assert run(case)["state"] == "cancelled"
    assert not case.prefix.exists()


@pytest.mark.parametrize("layout", ["different_folder", "different_file", "no_product", "pip"])
def test_unmapped_selection_is_reported_for_agent_inspection_without_guessing(case, monkeypatch, layout):
    if layout == "different_folder":
        install_locations.select_mode(case.workroot, "DSSAT", "existing", case.distribution.parent)
    elif layout == "different_file":
        alternate = case.distribution / "other/dscsm048.exe"
        alternate.parent.mkdir()
        alternate.write_bytes(case.binary.read_bytes())
        install_locations.select_mode(case.workroot, "DSSAT", "existing", alternate)
    else:
        from kiss_cli.manifest import Acquire, Manifest
        man = Manifest(model="DSSAT", acquire=Acquire(strategy="pip", produces="dssat")
                       if layout == "pip" else None)
        case.handler._manifest = lambda ki: man
    seen = []
    def provider(*args, **kwargs):
        assert not case.prefix.exists()
        record = json.loads((case.root / ".geoforge/existing-placement.json").read_text())
        assert record["state"] == "not_placed" and not record["verified"]
        assert "inspect" in record["reason"]
        seen.append(True)
        yield "Inspecting the selected path.\n"
    monkeypatch.setattr(api, "run", provider)
    monkeypatch.setattr(install, "run_preflight", lambda *a, **kw: install.Step("preflight", False, "Not ready"))
    assert run(case)["state"] == "failed", case.output
    assert seen == [True]
    assert not case.prefix.exists()


def test_missing_selected_path_fails_without_provider_search(case, monkeypatch):
    index = install_locations._read_index(case.workroot)
    index["models"]["dssat"]["existing_path"] = str(case.distribution / "removed")
    install_locations._write_index(case.workroot, index)
    monkeypatch.setattr(api, "run", lambda *a, **kw: pytest.fail("provider on missing path"))
    monkeypatch.setattr(install, "run_preflight", lambda *a, **kw: pytest.fail("preflight on missing path"))
    state = run(case)
    assert state["state"] == "failed" and "missing" in state["detail"]
    assert not case.prefix.exists()


def test_conflicting_ki_expected_tree_is_not_silently_retained(case, monkeypatch):
    conflict = case.root / "DSSAT/Data/MODEL.ERR"
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"unrelated existing checkout")
    monkeypatch.setattr(install, "run_preflight", lambda *a, **kw: pytest.fail("preflight after conflict"))
    monkeypatch.setattr(api, "run", lambda *a, **kw: pytest.fail("provider after conflict"))
    state = run(case)
    assert state["state"] == "failed" and "conflict" in state["detail"].lower()
    assert conflict.read_bytes() == b"unrelated existing checkout"
    assert not case.prefix.exists()


def test_placement_does_not_write_to_an_external_binaries_role(case, monkeypatch, tmp_path):
    external = tmp_path / "unrelated-installations"
    case.cfg.roles["binaries"] = external
    monkeypatch.setattr(install, "run_preflight", lambda *a, **kw: pytest.fail("preflight after boundary failure"))
    state = run(case)
    assert state["state"] == "failed" and "inside this setup workspace" in state["detail"]
    assert not external.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows native executable spelling")
def test_exact_native_suffix_is_supported_without_a_recursive_search(case, monkeypatch):
    man = case.handler._manifest(case.ki)
    man.acquire.produces = "build/bin/dscsm048"
    monkeypatch.setattr(Path, "rglob", lambda *a, **kw: pytest.fail("recursive candidate discovery"))
    report = gui._place_selected_existing_install(case.live, man, case.cfg, str(case.distribution))
    assert report["state"] == "placed" and not report["verified"]
    assert (case.root / "DSSAT/Data/MODEL.ERR").read_bytes() == b"official error messages"


@pytest.mark.parametrize("product", ["../build/bin/dscsm048.exe", "C:/dscsm048.exe"])
def test_unsafe_product_is_rejected_before_placement(case, product):
    man = case.handler._manifest(case.ki)
    man.acquire.produces = product
    with pytest.raises(ValueError, match="bounded relative"):
        gui._place_selected_existing_install(case.live, man, case.cfg, str(case.distribution))
    assert not case.prefix.exists()


@pytest.mark.parametrize("route", ["gui_init", "agent_builtin"])
@pytest.mark.parametrize("selection", ["exact", "unmapped", "none"])
def test_builtin_existing_mode_never_acquires_or_rebuilds(case, monkeypatch, route, selection):
    if selection == "unmapped":
        install_locations.select_mode(case.workroot, "DSSAT", "existing", case.distribution.parent)
    elif selection == "none":
        index = install_locations._read_index(case.workroot)
        index["models"]["dssat"]["existing_path"] = None
        install_locations._write_index(case.workroot, index)
        monkeypatch.setattr(gui.setup_discovery, "discover", lambda *a, **kw: {
            "candidates": [str(case.distribution)], "complete": True})
    monkeypatch.setattr(install, "needs_shared_tools", lambda *a: False)
    monkeypatch.setattr(install, "check_system_deps", lambda *a: install.Step("system-deps", True))
    monkeypatch.setattr(install, "install_python_deps", lambda *a, **kw: install.Step("python-deps", True))
    monkeypatch.setattr(install, "acquire", lambda *a, **kw: pytest.fail("existing mode downloaded or built software"))
    def preflight(*args, **kwargs):
        if selection == "exact":
            assert_placed(case)
        return install.Step("preflight", False, "Remaining mandatory KI requirements")
    monkeypatch.setattr(install, "run_preflight", preflight)
    seen = []
    def provider(*args, **kwargs):
        output = kwargs["setup_context"]["run_builtin"]()
        assert "strategy: existing" in output
        seen.append(True)
        yield "Built-in respected the existing installation.\n"
    monkeypatch.setattr(api, "run", provider)
    before = source_bytes(case)
    if route == "gui_init":
        case.handler._stream_init({"model": "DSSAT"})
    else:
        run(case)
        assert seen == [True], case.output
    state = setup_jobs.status(case.workroot, "DSSAT")
    assert state["state"] == "failed", (state, case.output)
    assert source_bytes(case) == before
    if selection == "exact":
        assert_placed(case)
    else:
        assert not case.prefix.exists()
    assert not case.handler._status_for(case.ki)["can_run"]


@pytest.mark.parametrize("placed", [False, True])
def test_cli_init_registered_existing_workspace_never_acquires(case, monkeypatch, tmp_path, placed):
    if placed:
        gui._place_selected_existing_install(case.live, case.handler._manifest(case.ki),
                                              case.cfg, str(case.distribution))
    monkeypatch.setattr(install, "needs_shared_tools", lambda *a: False)
    monkeypatch.setattr(install, "check_system_deps", lambda *a: install.Step("system-deps", True))
    monkeypatch.setattr(install, "install_python_deps", lambda *a, **kw: install.Step("python-deps", True))
    monkeypatch.setattr(install, "acquire", lambda *a, **kw: pytest.fail("CLI rebuilt an existing installation"))
    checks = []
    def preflight(*args, **kwargs):
        assert_placed(case)
        checks.append(True)
        return install.Step("preflight", True, "Harmless fixture verification")
    monkeypatch.setattr(install, "run_preflight", preflight)
    args = SimpleNamespace(models=case.handler.catalog.models_dir, model="DSSAT",
                           workdir=str(case.root), python=None, relocation="none")
    selected = install_locations._read_index(case.workroot)["models"]["dssat"].copy()
    for _ in range(2):
        assert cli.cmd_init(args) == (0 if placed else 2)
        assert install_locations._read_index(case.workroot)["models"]["dssat"] == selected
    assert checks == ([True, True] if placed else [])
    assert not (Path.home() / "kiss" / install_locations.INDEX_FILE).exists()


def test_cli_new_workspace_does_not_inherit_other_registration_existing_mode(case, monkeypatch, tmp_path):
    user_home = Path.home()
    install_locations._write_index(case.workroot, {"schema_version": 2, "models": {}})
    install_locations.select_mode(user_home / "kiss", "DSSAT", "existing", case.distribution)
    monkeypatch.setattr(install, "needs_shared_tools", lambda *a: False)
    monkeypatch.setattr(install, "check_system_deps", lambda *a: install.Step("system-deps", True))
    monkeypatch.setattr(install, "install_python_deps", lambda *a, **kw: install.Step("python-deps", True))
    acquired = []
    def acquire(*args, **kwargs):
        acquired.append(True)
        return install.Step("acquire", False, "Fixture build not executed"), None
    monkeypatch.setattr(install, "acquire", acquire)
    args = SimpleNamespace(models=case.handler.catalog.models_dir, model="DSSAT",
                           workdir=str(case.root), python=None, relocation="none")
    assert cli.cmd_init(args) == 2
    assert acquired == [True]
    saved = install_locations._read_index(user_home / "kiss")["models"]["dssat"]
    assert saved["workspace"] == str(case.root)
    assert saved["installation_mode"] == "new" and saved["existing_path"] is None
