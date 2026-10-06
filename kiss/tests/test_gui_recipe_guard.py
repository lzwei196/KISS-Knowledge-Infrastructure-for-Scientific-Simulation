"""Recipe provider wiring uses the real host guard without launching an agent."""
from types import SimpleNamespace

import pytest

from kiss_cli import api, gui, ki_guard, paths, providers, recipe
from kiss_cli.catalog import KI


def recipe_handler(tmp_path, monkeypatch, route, *, live_registered=True, live_present=True):
    source = tmp_path / "models/M"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("canonical baseline")
    ki_guard.enroll(source)
    workspace = tmp_path / "work/M"
    workspace.mkdir(parents=True)
    live = workspace / "ki"
    if live_present:
        live.mkdir()
        (live / "SKILL.md").write_text("installed baseline")
        if live_registered:
            ki_guard.enroll(live)
    ki = KI("M", source)
    handler = object.__new__(gui.Handler)
    handler.repo_root = tmp_path
    handler.workroot = workspace.parent
    handler.catalog = SimpleNamespace(models_dir=source.parent)
    handler._ki = lambda _: ki
    handler._workdir = lambda _: workspace
    handler._config = lambda _: paths.KissConfig.default(workspace)
    handler._open_stream = handler._end_stream = lambda: None
    messages = []
    handler._chunk = lambda text: messages.append(text) or True
    provider = SimpleNamespace(name="fixture", available=lambda: True)
    monkeypatch.setattr(providers, "available", lambda: [provider])
    monkeypatch.setattr(providers, "get", lambda _: provider)
    monkeypatch.setitem(api.PROVIDERS, "fixture", provider)
    def propose(_ki, _harvested, _models, _wd, _manifests, run_agent, _emit, **_kwargs):
        run_agent("propose a recipe")
        return False
    monkeypatch.setattr(recipe, "propose_and_verify", propose)
    if route == "api":
        def run_api(_prov, selected, cfg, _system, _task, **kwargs):
            yield api.execute_tool("run_setup_command", {}, selected, cfg,
                                   setup_context=kwargs.get("setup_context"))
        monkeypatch.setattr(api, "run", run_api)
    return handler, source, live, messages


@pytest.mark.parametrize("route", ["api", "cli"])
@pytest.mark.parametrize("target", ["source", "live"])
def test_recipe_provider_preserves_rejected_edits_to_both_kis(tmp_path, monkeypatch, route, target):
    handler, source, live, messages = recipe_handler(tmp_path, monkeypatch, route)
    changed = source if target == "source" else live
    def mutate(*_args, **_kwargs):
        (changed / "SKILL.md").write_text("unaccepted recipe edit")
        return "claimed success"
    if route == "api":
        monkeypatch.setattr(api, "_execute_tool", mutate)
    else:
        def fake_cli(*args, **kwargs):
            yield mutate(*args, **kwargs)
        monkeypatch.setattr(providers, "_run", fake_cli)
    handler._stream_recipe({"model": "M", "provider": f"{route}:fixture"})
    assert "recipe failed" in "".join(messages)
    assert "retained" in "".join(messages)
    with pytest.raises(ki_guard.KIIntegrityError, match="changed"):
        ki_guard.require_intact(changed)
    assert any((draft / "SKILL.md").read_text() == "unaccepted recipe edit"
               for draft in changed.parent.glob("ki-draft-*"))
    ki_guard.require_intact(live if target == "source" else source)


@pytest.mark.parametrize("route", ["api", "cli"])
def test_recipe_does_not_enroll_an_existing_unknown_live_ki(tmp_path, monkeypatch, route):
    handler, source, live, messages = recipe_handler(tmp_path, monkeypatch, route, live_registered=False)
    called = []
    def unexpected(*_args, **_kwargs):
        called.append(True)
        return "unexpected execution"
    monkeypatch.setattr(api, "_execute_tool", unexpected)
    monkeypatch.setattr(providers, "_run", unexpected)
    handler._stream_recipe({"model": "M", "provider": f"{route}:fixture"})
    assert not called and not ki_guard.is_managed(live)
    assert "installed and verified" not in "".join(messages)
    assert (live / "SKILL.md").read_text() == "installed baseline"
    ki_guard.require_intact(source)


@pytest.mark.parametrize("route", ["api", "cli"])
def test_recipe_can_propose_before_live_ki_exists(tmp_path, monkeypatch, route):
    handler, source, live, messages = recipe_handler(tmp_path, monkeypatch, route, live_present=False)
    called = []
    def propose(*_args, **_kwargs):
        called.append(True)
        return "candidate recipe"
    monkeypatch.setattr(api, "_execute_tool", propose)
    def fake_cli(*args, **kwargs):
        yield propose(*args, **kwargs)
    monkeypatch.setattr(providers, "_run", fake_cli)
    handler._stream_recipe({"model": "M", "provider": f"{route}:fixture"})
    assert called and not live.exists()
    assert "recipe failed" not in "".join(messages)
    ki_guard.require_intact(source)
