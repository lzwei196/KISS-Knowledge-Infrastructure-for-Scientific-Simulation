"""Real Desktop KI materialization keeps legacy migration independent of order."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kiss_cli import gui, paths, project_paths
from kiss_cli.catalog import KI


def _setup(tmp_path, monkeypatch):
    project = tmp_path / "scenario"
    project.mkdir()
    kis = {}
    installs = {}
    for name in ("A", "B"):
        root = tmp_path / "source" / name
        root.mkdir(parents=True)
        (root / "SKILL.md").write_text(
            "input=KISSPATH_STATIC/INPUT.DAT\n"
            "output=KISSPATH_OUTPUTS/result.nc\n")
        kis[name] = KI(name, root)
        cfg = paths.KissConfig.default(tmp_path / "install" / name)
        cfg.python = str(cfg.roles["python_env"] / "bin" / "python")
        installs[name] = cfg
    handler = object.__new__(gui.Handler)
    handler._config = lambda ki: installs[ki.name]
    handler.repo_root = None
    monkeypatch.setattr(gui.install, "runtime_python", lambda *args: sys.executable)
    legacy = project_paths.model_config(project, "B", installs["B"])
    legacy.roles["static"] = project / "outputs" / "B" / "legacy-deck"
    legacy.roles["static"].mkdir(parents=True)
    (legacy.roles["static"] / "INPUT.DAT").write_text("user case data")
    (project / paths.CONFIG_NAME).write_text(legacy.dumps())
    return handler, project, kis, installs, legacy


@pytest.mark.parametrize("order", [("A", "B"), ("B", "A")])
def test_batch_preserves_legacy_b_deck_for_both_selected_orders(tmp_path, monkeypatch, order):
    handler, project, kis, installs, legacy = _setup(tmp_path, monkeypatch)
    resolved = handler._session_workspaces(project, [kis[name] for name in order])
    configs = {ki.name: cfg for ki, cfg in resolved}
    for name in ("A", "B"):
        cfg = configs[name]
        assert cfg.roles["outputs"] == project / "outputs" / name
        assert cfg.python == installs[name].python
        assert project_paths.load_model_config(project, name).dumps() == cfg.dumps()
    assert configs["A"].roles["static"] == project / "inputs" / "static"
    assert configs["B"].roles["static"] == legacy.roles["static"]
    for ki, cfg in resolved:
        text = (ki.root / "SKILL.md").read_text()
        assert (cfg.roles["outputs"] / "result.nc").as_posix() in text
        assert (cfg.roles["static"] / "INPUT.DAT").as_posix() in text
    neutral = paths.KissConfig.load(project)
    assert neutral.python == sys.executable
    assert neutral.roles["outputs"] == project / "outputs"
    assert neutral.roles["binaries"] == project / "binaries"

    # Restart and reverse order must not change root identity or B's saved deck.
    neutral_bytes = (project / paths.CONFIG_NAME).read_bytes()
    repeated = handler._session_workspaces(project, [kis[name] for name in reversed(order)])
    assert (project / paths.CONFIG_NAME).read_bytes() == neutral_bytes
    assert {ki.name: cfg for ki, cfg in repeated}["B"].roles["static"] == legacy.roles["static"]
    assert (legacy.roles["static"] / "INPUT.DAT").read_text() == "user case data"


def test_batch_resolves_every_config_before_materialization_or_neutral_write(tmp_path, monkeypatch):
    handler, project, kis, _installs, _legacy = _setup(tmp_path, monkeypatch)
    original = (project / paths.CONFIG_NAME).read_bytes()
    events = []
    real_config = handler._session_config
    real_workspace = handler._session_workspace

    def config(project, ki):
        assert (project / paths.CONFIG_NAME).read_bytes() == original
        events.append(("resolve", ki.name))
        return real_config(project, ki)

    def workspace(project, ki, **kwargs):
        assert (project / paths.CONFIG_NAME).read_bytes() == original
        events.append(("materialize", ki.name))
        return real_workspace(project, ki, **kwargs)

    handler._session_config = config
    handler._session_workspace = workspace
    handler._session_workspaces(project, [kis["A"], kis["B"]])
    assert events == [("resolve", "A"), ("resolve", "B"), ("materialize", "A"), ("materialize", "B")]


def test_materialization_failure_does_not_discard_legacy_global_bindings(tmp_path, monkeypatch):
    handler, project, kis, _installs, legacy = _setup(tmp_path, monkeypatch)
    before = (project / paths.CONFIG_NAME).read_bytes()
    real_materialise = gui.port.materialise

    def materialise(root, live, cfg):
        if Path(root).name == "B":
            raise OSError("test materialization failure")
        return real_materialise(root, live, cfg)

    monkeypatch.setattr(gui.port, "materialise", materialise)
    with pytest.raises(OSError, match="test materialization failure"):
        handler._session_workspaces(project, [kis["A"], kis["B"]])
    assert (project / paths.CONFIG_NAME).read_bytes() == before
    assert not (project / "models" / "B" / paths.CONFIG_NAME).exists()
    assert (legacy.roles["static"] / "INPUT.DAT").read_text() == "user case data"


def test_empty_batch_does_not_replace_legacy_root(tmp_path, monkeypatch):
    handler, project, _kis, _installs, _legacy = _setup(tmp_path, monkeypatch)
    before = (project / paths.CONFIG_NAME).read_bytes()
    assert handler._session_workspaces(project, []) == []
    assert (project / paths.CONFIG_NAME).read_bytes() == before


@pytest.mark.parametrize("chat", ["auto", "pinned"])
def test_chat_surfaces_failed_materialization_without_provider_fallback(tmp_path, monkeypatch, chat):
    handler, project, kis, installs, _legacy = _setup(tmp_path, monkeypatch)
    handler.catalog = list(kis.values())
    handler._ki = lambda name: kis[name]
    handler._status_for = lambda ki: {"can_run": True}
    handler._workdir = lambda ki: installs[ki.name].root
    before = (project / paths.CONFIG_NAME).read_bytes()
    monkeypatch.setattr(gui.settings, "database_access_mode", lambda: "off")
    monkeypatch.setattr(gui.projectrun, "load", lambda project: {"selected_kis": ["A", "B"]})
    monkeypatch.setattr(gui.projectrun, "prompt_block", lambda project: "")
    real_materialise = gui.port.materialise

    def materialise(root, live, cfg):
        if Path(root).name == "B":
            raise OSError("test materialization failure")
        return real_materialise(root, live, cfg)

    def unexpected_provider(*args, **kwargs):
        pytest.fail("a failed batch must not invoke a provider with partial KI config")

    monkeypatch.setattr(gui.port, "materialise", materialise)
    monkeypatch.setattr(gui.api, "run", unexpected_provider)
    messages = []
    if chat == "auto":
        handler._chat_auto("api:deepseek", "test request", messages.append, project)
    else:
        handler._chat_with_models(["A", "B"], "api:deepseek", "test request", messages.append, project)
    assert "could not prepare selected KI workspaces" in "".join(messages)
    assert "test materialization failure" in "".join(messages)
    assert (project / paths.CONFIG_NAME).read_bytes() == before


@pytest.mark.parametrize("batch", [False, True])
def test_unselected_legacy_owner_is_preserved_then_migrated_later(tmp_path, monkeypatch, batch):
    handler, project, kis, _installs, legacy = _setup(tmp_path, monkeypatch)
    before = (project / paths.CONFIG_NAME).read_bytes()
    if batch:
        handler._session_workspaces(project, [kis["A"]])
    else:
        handler._session_workspace(project, kis["A"])
    assert (project / paths.CONFIG_NAME).read_bytes() == before
    assert project_paths.load_model_config(project, "A").roles["outputs"] == project / "outputs" / "A"
    assert not (project / "models" / "B" / paths.CONFIG_NAME).exists()

    resolved = handler._session_workspaces(project, [kis["B"]])
    assert resolved[0][1].roles["static"] == legacy.roles["static"]
    neutral = paths.KissConfig.load(project)
    assert neutral.roles["outputs"] == project / "outputs"
    assert neutral.python == sys.executable


def test_ambiguous_legacy_root_is_retained_without_blocking_exact_model_configs(tmp_path, monkeypatch):
    handler, project, kis, _installs, legacy = _setup(tmp_path, monkeypatch)
    legacy.roles["outputs"] = project / "unknown-case"
    legacy.roles["outputs_disk1"] = project / "unknown-case"
    legacy.roles["binaries"] = project / "unknown-install"
    legacy.python = "unknown-legacy-python"
    path = project / paths.CONFIG_NAME
    path.write_text(legacy.dumps())
    before = path.read_bytes()
    resolved = handler._session_workspaces(project, [kis["A"], kis["B"]])
    assert path.read_bytes() == before
    for ki, cfg in resolved:
        assert project_paths.load_model_config(project, ki.name).dumps() == cfg.dumps()
        assert cfg.roles["outputs"] == project / "outputs" / ki.name


@pytest.mark.parametrize("batch", [False, True])
def test_neutral_root_custom_binding_is_not_lost_on_refresh(tmp_path, monkeypatch, batch):
    handler, project, kis, _installs, _legacy = _setup(tmp_path, monkeypatch)
    neutral = project_paths.project_config(project, python=sys.executable)
    neutral.roles["survey"] = project / "inputs" / "user-survey"
    path = project / paths.CONFIG_NAME
    path.write_text(neutral.dumps())
    before = path.read_bytes()
    if batch:
        handler._session_workspaces(project, [kis["A"], kis["B"]])
    else:
        handler._session_workspace(project, kis["A"])
    assert path.read_bytes() == before
    assert project_paths.load_model_config(project, "A").roles["outputs"] == project / "outputs" / "A"
