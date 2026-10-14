"""A shared installation cannot authorize different project KI bytes."""
import json
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import api, catalog, execution, flowrun, gui, ki_guard, paths, project_paths, project_verification


@pytest.fixture
def project_case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project = tmp_path / "project"
    project.mkdir()
    sources, pairs = {}, []
    for name, code in (("A", "print('project A passed')"), ("B", "raise SystemExit('project B fails')")):
        source = tmp_path / "library" / "models" / name
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text(f"# {name}")
        (source / "preflight_check.py").write_text("print('shared source passes')")
        sources[name] = catalog.KI(name, source)
        home = project / "models" / name
        root = home / "ki"
        root.mkdir(parents=True)
        (root / "SKILL.md").write_text(f"# {name}")
        (root / "preflight_check.py").write_text(code)
        ki_guard.enroll(root)
        shared = paths.KissConfig.default(tmp_path / "shared" / name)
        shared.python = sys.executable
        cfg = project_paths.model_config(project, name, shared)
        (home / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
        pairs.append((catalog.KI(name, root), cfg))
    handler = object.__new__(gui.Handler)
    handler.workroot = tmp_path / "work"
    handler._ki = lambda name: sources[name]
    handler._status_for = lambda ki: {"can_run": True}
    handler._workdir = lambda ki: tmp_path / "shared" / ki.name
    handler._manifest = lambda ki: gui.Manifest.stub_for(ki)
    handler._session_workspaces = lambda _project, kis: [pair for pair in pairs if pair[0].name in {k.name for k in kis}]
    handler.repo_root = tmp_path / "library"
    handler.catalog = SimpleNamespace(models_dir=handler.repo_root / "models")
    monkeypatch.setattr(gui.api, "run", lambda *a, **kw: pytest.fail("host project check must precede provider"))
    monkeypatch.setattr(gui.providers, "run", lambda *a, **kw: pytest.fail("host project check must precede provider"))
    monkeypatch.setattr(flowrun, "provider_refusal", lambda *args: None)
    return SimpleNamespace(project=project, pairs=pairs, handler=handler)


@pytest.mark.parametrize("provider", ["api:deepseek", "cli:claude"])
@pytest.mark.parametrize("names", [["A"], ["A", "B"]])
def test_approved_project_checks_every_exact_ki_before_handoff(project_case, monkeypatch, provider, names):
    c = project_case
    transitions, messages = [], []
    turn = SimpleNamespace(kind="setup")
    monkeypatch.setattr(flowrun, "setup_allowed", lambda _project: True)
    monkeypatch.setattr(flowrun, "setup_turn", lambda *a, **kw: turn)
    monkeypatch.setattr(flowrun, "setup_verified", lambda *a: transitions.append("verified"))
    monkeypatch.setattr(flowrun, "project_setup_failed", lambda *a: transitions.append("failed"))
    result = c.handler._chat_with_models(names, provider, "Run the approved case", messages.append,
        c.project, flow_pre=SimpleNamespace(gated=True))
    assert result is turn
    assert transitions == (["verified"] if names == ["A"] else ["failed"])
    assert project_verification.status(c.project, c.pairs[0][0])["can_run"]
    if "B" in names:
        assert not project_verification.status(c.project, c.pairs[1][0])["can_run"]
        assert "project B fails" in "".join(messages)
    assert not list(c.handler.workroot.rglob("status.json")), "project verification must not write shared status"


def test_secondary_shared_runtime_missing_cannot_inherit_first_pass(project_case, monkeypatch):
    c = project_case
    c.handler._status_for = lambda ki: {"can_run": ki.name == "A"}
    messages = []
    assert not c.handler._verify_project_preflight(c.project, c.pairs, messages.append)
    assert "B shared runtime needs verification" in "".join(messages)
    assert not c.handler._project_setup_ok(c.project, ["A", "B"])


def test_readiness_never_runs_preflight_and_detects_changed_config(project_case, monkeypatch):
    c = project_case
    ki, cfg = c.pairs[0]
    assert project_verification.verify(c.project, ki, c.handler._manifest(ki))["can_run"]
    monkeypatch.setattr(gui.install, "run_preflight", lambda *a, **kw: pytest.fail("status is read-only"))
    assert c.handler._project_setup_ok(c.project, ["A"])
    cfg.python = "moved-python"
    (ki.root.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    assert not c.handler._project_setup_ok(c.project, ["A"])


def test_stop_prevents_project_probe_and_handoff(project_case, monkeypatch):
    c = project_case
    handle = api.TurnHandle()
    handle.stop()
    monkeypatch.setattr(project_verification, "verify", lambda *a, **kw: pytest.fail("cancelled check"))
    assert not c.handler._verify_project_preflight(c.project, [c.pairs[0]], lambda _: None,
                                                  {"_handle": handle})


def test_project_failure_returns_setup_to_retry_without_authorizing_execution(project_case):
    c = project_case
    ki, cfg = c.pairs[0]
    fs = flowrun.flowgate.FlowSession.open(c.project, {ki.name: ki.root})
    fs.ctx.state = fs.flow.states.State.SETUP_RUNNING
    fs.ctx.selected_kis = [ki.name]
    fs.ctx.save()
    flowrun.project_setup_failed(c.project, [ki], "Exact project check failed")
    assert flowrun.current_state(c.project) == "SETUP_REQUIRED"
