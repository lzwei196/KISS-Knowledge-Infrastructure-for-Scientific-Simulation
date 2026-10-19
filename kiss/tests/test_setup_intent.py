"""Synthetic setup/project fixtures only; never install or run a scientific model."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from kiss_cli import (api, gui, install, install_locations, ki_guard, paths,
                      project_paths, providers, sessions, setup, setup_intent,
                      setup_jobs, software_verification)
from .test_gui_setup_jobs import ready
from .test_setup_final_runtime import case, install_spies, saved_status


@pytest.fixture
def project(ready, monkeypatch):
    c = ready
    s = sessions.create(c.workroot, ["Demo"], "api:deepseek")
    c.sid = s["id"]
    c.project = sessions.project_path(c.workroot, s).resolve()
    home = c.project / "models/Demo"
    home.mkdir(parents=True)
    shutil.copytree(c.ki.root, home / "ki")
    ki_guard.enroll(home / "ki")
    c.project_cfg = project_paths.model_config(c.project, "Demo", c.cfg)
    (home / "kiss.toml").write_text(c.project_cfg.dumps(), encoding="utf-8")
    (c.project / "runs").mkdir(exist_ok=True)
    (c.project / "runs/plan.json").write_text('{"goal":"official case"}', encoding="utf-8")
    c.intent = {"kind": "case_repair", "session": c.sid,
                "goal": "Confirm and build the official case's required feature; retain its inputs."}
    c.request = {"model": "Demo", "provider": "api:deepseek", "session": c.sid,
                 "setup_intent": c.intent}
    monkeypatch.setattr(gui.project_status, "snapshot", lambda *_: {"progress": {}})
    return c


def capture(c):
    return setup_intent.capture(c.workroot, model="Demo", source_root=c.ki.root,
        setup_root=c.root, intent=c.intent)


@pytest.mark.parametrize("value", [False, [], {}, {"kind":"other","session":"a"*12,"goal":"x"},
    {"kind":"case_repair","session":"../bad","goal":"x"},
    {"kind":"case_repair","session":[],"goal":"x"},
    {"kind":"case_repair","session":"a"*12,"goal":" "},
    {"kind":"case_repair","session":"a"*12,"goal":"x"*4001},
    {"kind":"case_repair","session":"a"*12,"goal":"x\0y"},
    {"kind":"case_repair","session":"a"*12,"goal":"x","root":"/override"}])
def test_request_is_bounded_and_never_accepts_path_or_command_overrides(value):
    with pytest.raises(ValueError): setup_intent.parse(value)


def test_capture_is_read_only_and_uses_exact_host_project_and_runtime(project, monkeypatch):
    c = project
    before = {p: p.read_bytes() for p in (c.root / "kiss.toml", c.project / "models/Demo/kiss.toml",
                                         c.project / "runs/plan.json")}
    monkeypatch.setattr(install, "run_preflight", lambda *_a, **_kw: pytest.fail("no probe"))
    ctx = capture(c)
    assert ctx["project"] == str(c.project)
    assert ctx["runtime_paths"]["python"] == c.cfg.python
    assert ctx["runtime_paths"]["binaries"] == str(c.cfg.roles["binaries"])
    assert ctx["project_evidence"]["runs/plan.json"]["sha256"] == hashlib.sha256(before[c.project / "runs/plan.json"]).hexdigest()
    setup_intent.require_current(ctx, c.workroot)
    assert before == {p: p.read_bytes() for p in before}
    assert not (c.root / setup_intent.RECORD).exists()


def test_legitimate_same_path_engine_and_dependency_repair_does_not_expire_intent(project):
    c = project
    engine = c.cfg.roles["binaries"] / "official-engine"
    engine.parent.mkdir(parents=True, exist_ok=True)
    engine.write_bytes(b"old engine fixture")
    dependency = c.cfg.roles["python_env"] / "installed-dependency.txt"
    dependency.parent.mkdir(parents=True, exist_ok=True)
    dependency.write_bytes(b"old dependency fixture")
    ctx = capture(c)
    engine.write_bytes(b"new official build fixture")
    dependency.write_bytes(b"new dependency fixture")
    setup_intent.require_current(ctx, c.workroot)
    assert setup_intent.state(c.root) is None, "path intent cannot grant new-byte readiness"


@pytest.mark.parametrize("mutation", ["project_ki", "source", "project_config", "setup_config", "plan", "new_inventory"])
def test_bound_evidence_or_paths_drift_refuses(project, mutation):
    c = project
    ctx = capture(c)
    path = {"project_ki": c.project / "models/Demo/ki/SKILL.md", "source": c.ki.root / "SKILL.md",
            "project_config": c.project / "models/Demo/kiss.toml", "setup_config": c.root / "kiss.toml",
            "plan": c.project / "runs/plan.json", "new_inventory": c.project / "runs/data-inventory.json"}[mutation]
    with path.open("a", encoding="utf-8") as f: f.write("\n# changed")
    with pytest.raises((ValueError, RuntimeError)):
        setup_intent.require_current(ctx, c.workroot)


@pytest.mark.parametrize("mutation", ["model", "interpreter", "binary_path", "absent_session"])
def test_wrong_case_or_shared_binding_rejected_before_setup(project, mutation):
    c = project
    if mutation == "model":
        s = sessions.load(c.workroot, c.sid);s["models"] = ["Other"];sessions.save(c.workroot, s)
    elif mutation == "absent_session": c.intent["session"] = "f" * 12
    else:
        cfg = c.project_cfg
        if mutation == "interpreter": cfg.python = str(c.project / "fake-python")
        else: cfg.roles["binaries"] = c.project / "fake-binaries"
        (c.project / "models/Demo/kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    with pytest.raises(ValueError): capture(c)


@pytest.mark.parametrize("provider_kind", ["api", "cli", "cli_resume"])
def test_explicit_goal_enters_provider_even_when_initial_and_final_checks_pass(project, monkeypatch, provider_kind):
    c = project
    install_spies(monkeypatch)
    seen = []
    if provider_kind == "api":
        def provider(_prov, _ki, _cfg, _system, task, **kw):
            seen.append(task)
            assert kw["setup_context"]["project_root"] == c.root
            yield "Fixture diagnosis; no software/model execution.\n"
        monkeypatch.setattr(api, "run", provider)
    else:
        prov = providers.Provider(name="fixture", binary="fixture", argv=["fixture"], output="text", label="Fixture")
        monkeypatch.setitem(providers.PROVIDERS, "fixture", prov)
        c.request["provider"] = "cli:fixture"
        if provider_kind == "cli_resume":
            setup.request_user(c.root, {"kind":"other", "title":"Supply evidence", "message":"Need build evidence"})
            setup.resume(c.root, "Evidence supplied")
            monkeypatch.setattr(setup, "cli_session", lambda *_: "old-session")
            monkeypatch.setattr(type(prov), "can_resume", lambda _: True)
        def provider(_prov, task, _root, **kw):
            seen.append(task)
            if "session_out" in kw: kw["session_out"].update(produced=True, returncode=0)
            yield "Fixture diagnosis only.\n"
        monkeypatch.setattr(providers, "run", provider)
    c.handler._stream_agent_setup(c.request)
    assert len(seen) == 1, (c.responses, c.output)
    assert c.intent["goal"] in seen[0] and "[EXPLICIT PROJECT SOFTWARE REPAIR GOAL]" in seen[0]
    assert "not permission overrides" in seen[0]
    assert saved_status(c)["ok"] is True
    outcome = setup_intent.state(c.root)
    assert outcome["state"] == "completed" and outcome["case_outcome"] == "unverified"
    assert "case compatibility remains unverified" in outcome["detail"]
    assert "is already verified and ready" not in "".join(c.output)
    assert not gui._PROJECT_OPERATIONS.get(c.sid)


def test_no_intent_preserves_early_pass_and_no_provider_or_case_record(ready, monkeypatch):
    c = ready; install_spies(monkeypatch)
    monkeypatch.setattr(api, "run", lambda *a, **kw: pytest.fail("existing early-pass route"))
    c.handler._stream_agent_setup({"model":"Demo","provider":"api:deepseek"})
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "completed"
    assert setup_intent.state(c.root) is None


@pytest.mark.parametrize("failure", ["native", "cancel", "evidence_drift"])
def test_intent_cannot_replace_final_verification_or_hide_cancellation(project, monkeypatch, failure):
    c = project; install_spies(monkeypatch, requirements_ok=failure != "native")
    def provider(*args, **kw):
        if failure == "cancel": kw["handle"].stopped.set()
        elif failure == "evidence_drift": (c.project / "runs/plan.json").write_text("{}")
        yield "Provider claimed success, which is not authority.\n"
    monkeypatch.setattr(api, "run", provider)
    c.handler._stream_agent_setup(c.request)
    assert not saved_status(c)["ok"]
    outcome = setup_intent.state(c.root)
    assert outcome["state"] == ("cancelled" if failure == "cancel" else "failed")
    assert outcome["case_outcome"] == "unverified"


@pytest.mark.parametrize("failure", ["conflicting_session", "installation_only", "project_busy", "existing", "acquisition"])
def test_invalid_or_busy_intent_never_starts_setup_job(project, monkeypatch, failure):
    c = project
    if failure == "conflicting_session": c.request["session"] = "a" * 12
    elif failure == "installation_only": c.request["installation_only"] = True
    elif failure == "project_busy": monkeypatch.setattr(gui, "_agent_run_snapshot", lambda *_: {"state":"running"})
    elif failure == "existing": install_locations.select_mode(c.workroot, "Demo", "existing", str(c.root))
    else: monkeypatch.setattr(gui.project_status, "snapshot", lambda *_: {"progress":{"acquisition":{"active":True}}})
    monkeypatch.setattr(setup_jobs, "start", lambda *a, **kw: pytest.fail("must reject before job"))
    c.handler._stream_agent_setup(c.request)
    assert c.responses[-1][0] == 409
    assert not gui._PROJECT_OPERATIONS.get(c.sid)


def test_separate_signed_history_never_confers_case_success_and_tamper_is_unavailable(project):
    c = project; ctx = capture(c)
    for ident, state in [("a"*32,"completed"),("b"*32,"cancelled")]:
        setup_intent.record(c.root, ctx, ident, state=state, detail="Software check result only")
    assert len(list((c.root / ".geoforge/setup-intents").glob("*.json"))) == 2
    assert setup_intent.state(c.root)["case_outcome"] == "unverified"
    path = c.root / setup_intent.RECORD
    doc = json.loads(path.read_text());doc["case_outcome"] = "passed"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert setup_intent.state(c.root)["state"] == "unavailable"
