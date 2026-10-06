"""Real host-route/repair state integration; no providers or native models run."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import flowgate, gui, install, kdtstudio, ki_guard, ki_investigation as inv, paths, sessions
from kiss_cli.catalog import KI
from .test_ki_investigation import accepted, reviewer


@pytest.fixture
def case(tmp_path, monkeypatch):
    def unexpected_provider(*_args, **_kwargs):
        pytest.fail("Integration fixtures must explicitly mock every provider call")
    monkeypatch.setattr(gui.api, "run", unexpected_provider)
    monkeypatch.setattr(gui.providers, "run", unexpected_provider)
    for name, sub in (("GEOFORGE_KI_INVESTIGATION_HOME","investigations"),
                      ("GEOFORGE_FLOW_KEYS","keys"), ("GEOFORGE_FLOW_REGISTRY","registry"),
                      ("GEOFORGE_KDT_HOME","studio")):
        monkeypatch.setenv(name,str(tmp_path/sub))
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE",raising=False)
    monkeypatch.setattr(kdtstudio,"engine_source_digest",lambda *args:"e"*64)
    monkeypatch.setattr(gui,"_PROJECT_OPERATIONS",{})
    work=tmp_path/"work"
    session=sessions.create(work,["M"],provider="api:deepseek",project_name="Repair integration")
    session["cli_sessions"]={"fixture":{"id":"old-provider-conversation"}}
    for i in range(25):
        sessions.append_message(work,session,{"role":"user","text":f"Historical failure {i}"})
    sessions.save(work,session)
    project=sessions.project_path(work,session)
    root=project/"models/M/ki"
    (root/"tools").mkdir(parents=True)
    (root/"SKILL.md").write_text("Original KI")
    (root/"tools/reader.py").write_text("def read(): return 1\n")
    (root/"preflight_check.py").write_text("print('Original preflight')\n")
    ki_guard.enroll(root)
    (project/"runs/plan.json").write_text(json.dumps({"selected_kis":["M"],
        "steps":[{"id":"read","ki":"M","tool":str(root/"tools/reader.py") }]}))
    (project/"runs/data-inventory.json").write_text('{"items": []}')
    flow=flowgate.load()
    flow.approval.approve(project)
    ctx=flow.states.FlowContext(project=project)
    ctx.state=flow.states.State.FAILED;ctx.selected_kis=["M"];ctx.save()
    handler=object.__new__(gui.Handler)
    handler.workroot=work
    handler._json=lambda body,code=200:(body,code)
    handler._validate_binding=lambda req:None
    handler._investigation_roots=lambda *_:{"M":root}
    handler._ki=lambda name:KI(name,root)
    handler._status_for=lambda _: {"can_run":True}
    handler._manifest=lambda ki: gui.Manifest.stub_for(ki)
    handler._workdir=lambda _: tmp_path/"shared-install"
    monkeypatch.setattr(gui,"_agent_run_snapshot",lambda *_:{})
    monkeypatch.setattr(gui.project_status,"snapshot",lambda *_args,**_kw:{"progress":{}})
    monkeypatch.setattr(gui.ki_review_agents,"capability",lambda _: {"supported":True})
    yield SimpleNamespace(handler=handler,session=session,project=project,root=root,work=work)
    inv._RUNNING.clear();inv._STOPS.clear()


def make_draft(case):
    job=inv.create(case.project,case.session,{"M":case.root},"api:deepseek","deepseek-chat","Repair the reader")
    inv.run_reviews(case.project,job["id"],reviewer)
    return inv.create_draft(case.project,job["id"],"M")


def make_verified(case,monkeypatch):
    accepted(monkeypatch)
    job=make_draft(case)
    candidate=Path(job["draft"]["path"])
    (candidate/"preflight_check.py").write_text("print('Adopted preflight revision')\n")
    (candidate/"tools/reader.py").write_text("def read(): return 2\n")
    return inv.verify_draft(case.project,job["id"])


def apply_verified(case,monkeypatch):
    job=make_verified(case,monkeypatch)
    body,status=case.handler._project_investigation(case.session["id"],action="apply",job_id=job["id"],
        req={"verification_id":job["verification"]["id"]})
    assert status==200,body
    return body


@pytest.mark.parametrize("action",["start","build"])
def test_background_review_and_authoring_block_chat_until_worker_exits(case,monkeypatch,action):
    threads=[]
    class HeldThread:
        def __init__(self,*,target,**kwargs): self.target=target;threads.append(self)
        def start(self): pass
    monkeypatch.setattr(gui,"threading",SimpleNamespace(Thread=HeldThread))
    monkeypatch.setattr(gui.ki_review_agents,"review",lambda role,context,digest,**kwargs:
        reviewer(role,context,digest,kwargs["stop_event"],kwargs["emit"]))
    monkeypatch.setattr(gui.ki_review_agents,"author_draft",lambda *args,**kwargs:{"status":"completed"})
    job_id=make_draft(case)["id"] if action=="build" else None
    response,status=case.handler._project_investigation(case.session["id"],action=action,job_id=job_id,
        req={"issue":"Investigate the reader"})
    assert status==202,response
    calls=[]
    case.handler._stream_session_chat_owned=lambda *args: calls.append(args) or "chat-accepted"
    rejected,code=case.handler._stream_session_chat(case.session["id"],{"message":"Continue"})
    assert code==409 and "still running" in rejected["error"] and not calls
    assert len(threads)==1
    threads[0].target()
    assert case.handler._stream_session_chat(case.session["id"],{"message":"Continue"})=="chat-accepted"
    assert len(calls)==1


def test_investigation_cannot_start_during_owned_chat(case):
    token=gui._claim_project_operation(case.session["id"],"Project agent")
    try:
        response,status=case.handler._project_investigation(case.session["id"],action="start",req={"issue":"Check"})
        assert status==409 and "Project agent" in response["error"]
        assert inv.get(case.project)["status"]=="none"
    finally: gui._release_project_operation(case.session["id"],token)


def test_author_retry_receives_the_previous_host_gate_failure(case,monkeypatch):
    job=make_verified(case,monkeypatch)
    stored=inv._load(case.project,job["id"])
    stored["status"]="verification_failed"
    stored["verification"]["ok"]=False
    stored["verification"]["report"]={"ok":False,"error":"MISSING_EXECUTION_POLICY"}
    inv._save(case.project,stored)
    threads=[]
    class HeldThread:
        def __init__(self,*,target,**kwargs): threads.append(target)
        def start(self): pass
    monkeypatch.setattr(gui,"threading",SimpleNamespace(Thread=HeldThread))
    prompts=[]
    def author(*args,**kwargs):
        prompts.append(kwargs["task_extra"])
        return {"status":"completed","raw_response":"Fixed the stated execution policy; native tests not run."}
    monkeypatch.setattr(gui.ki_review_agents,"author_draft",author)
    response,status=case.handler._project_investigation(case.session["id"],action="build",job_id=job["id"])
    assert status==202,response
    threads[0]()
    assert "PREVIOUS HOST KDT CHECK" in prompts[0] and "MISSING_EXECUTION_POLICY" in prompts[0]
    assert inv.get(case.project,job["id"])["verification"] is None


def test_apply_forwards_exact_id_and_keeps_old_provider_binding_on_rejection(case,monkeypatch):
    job=make_verified(case,monkeypatch)
    before=(case.root/"tools/reader.py").read_bytes()
    response,status=case.handler._project_investigation(case.session["id"],action="apply",job_id=job["id"],
        req={"verification_id":"wrong-verification"})
    assert status==409 and "exact current verification" in response["error"]
    assert sessions.load(case.work,case.session["id"])["cli_sessions"]==case.session["cli_sessions"]
    assert (case.root/"tools/reader.py").read_bytes()==before


def test_successful_apply_clears_cli_conversation_but_retains_full_transcript(case,monkeypatch):
    archive=case.project/"memory/transcript.jsonl"
    before=archive.read_bytes()
    result=apply_verified(case,monkeypatch)
    saved=sessions.load(case.work,case.session["id"])
    assert saved["cli_sessions"]=={}
    assert saved["ki_repair_generation"]==result["job"]["apply"]["generation"]
    assert saved["ki_repair_resume"]["job_id"]==result["job"]["id"]
    assert result["resume_message"]==saved["ki_repair_resume"]["message"]
    assert archive.read_bytes()==before and len(saved["messages"])==25
    current,seed=gui._repair_history(saved)
    assert current["messages"]==[]
    assert "HOST KI REPAIR HANDOFF" in seed and "not native validation" in seed
    sessions.append_message(case.work,saved,{"role":"user","text":"Continue repaired revision"})
    sessions.save(case.work,saved)
    current,seed=gui._repair_history(sessions.load(case.work,saved["id"]))
    assert [m["text"] for m in current["messages"]]==["Continue repaired revision"]
    assert b"Historical failure 0" in archive.read_bytes()
    assert (case.root/"tools/reader.py").read_text()=="def read(): return 2\n"


def test_apply_releases_project_before_publishing_the_resume_response(case, monkeypatch):
    job = make_verified(case, monkeypatch)
    case.handler._stream_session_chat_owned = lambda *_: "fresh-chat-accepted"
    def publish(body, code=200):
        assert code == 200 and body["job"]["status"] == "applied"
        saved = sessions.load(case.work, case.session["id"])
        assert saved["ki_repair_generation"] == body["job"]["apply"]["generation"]
        assert case.handler._stream_session_chat(case.session["id"], {"message": "Continue"}) == "fresh-chat-accepted"
        return body, code
    case.handler._json = publish
    case.handler._project_investigation(case.session["id"], action="apply", job_id=job["id"],
        req={"verification_id": job["verification"]["id"]})


def test_nonrepair_chat_history_keeps_legacy_behavior():
    session={"messages":[{"role":"user","text":"Keep this","ts":1}]}
    selected,seed=gui._repair_history(session)
    assert selected is session and seed==""


def test_chat_recovers_committed_repair_after_session_save_was_interrupted(case,monkeypatch):
    job=make_verified(case,monkeypatch)
    applied=inv.apply(case.project,job["id"],job["verification"]["id"])
    old=sessions.load(case.work,case.session["id"])
    assert old["cli_sessions"]
    assert gui._reconcile_ki_repair(old,case.project)
    assert old["cli_sessions"]=={}
    assert old["ki_repair_generation"]==applied["apply"]["generation"]
    assert gui._repair_history(old)[0]["messages"]==[]
    report=case.project/"memory"/f"ki-repair-{old['ki_repair_generation']}.json"
    assert json.loads(report.read_text())["job_id"]==job["id"]
    assert not gui._reconcile_ki_repair(old,case.project), "a resumed conversation must not be reset again"


def test_large_review_has_short_handoff_and_full_saved_report(case,monkeypatch):
    result=apply_verified(case,monkeypatch)
    job=result["job"]
    job["combined_report"]["summary"]="Evidence detail. "*2000
    session={"messages":[]}
    assert gui._reconcile_ki_repair(session,case.project,job)
    _,seed=gui._repair_history(session)
    assert len(seed)<8000 and "Summary shortened" in seed
    report=case.project/"memory"/f"ki-repair-{session['ki_repair_generation']}.json"
    assert json.loads(report.read_text())["report"]["summary"]==job["combined_report"]["summary"]


@pytest.mark.parametrize("passes",[False,True])
def test_project_preflight_reads_adopted_bytes_and_only_pass_clears_readiness(case,monkeypatch,passes):
    apply_verified(case,monkeypatch)
    assert not case.handler._setup_ok_for(case.session)
    cfg=paths.KissConfig.default(case.root.parent)
    seen=[]
    def probe(ki,python,config,**kwargs):
        seen.append((ki.root,(ki.root/"preflight_check.py").read_text(),kwargs["project"]))
        return install.Step("preflight",passes,"Actual fixture probe outcome")
    monkeypatch.setattr(install,"run_preflight",probe)
    messages=[]
    assert case.handler._repair_preflight(case.project,[(KI("M",case.root),cfg)],messages.append) is passes
    assert seen==[(case.root,"print('Adopted preflight revision')\n",case.project)]
    assert inv.pending_preflight(case.project)["pending"] is not passes
    assert case.handler._setup_ok_for(case.session) is passes
    assert ("Scientific execution remains blocked" in "".join(messages)) is not passes


def test_repair_preflight_missing_new_manifest_dependency_stays_blocked(case,monkeypatch):
    apply_verified(case,monkeypatch)
    cfg=paths.KissConfig.default(case.root.parent)
    ki=KI("M",case.root)
    seen=[]
    manifest=gui.Manifest.stub_for(ki)
    manifest.depends_on=["NEW_DEPENDENCY"]
    case.handler._manifest=lambda actual: manifest if actual.root==case.root else None
    case.handler._status_for=lambda dependency: {"can_run":dependency.name!="NEW_DEPENDENCY"}
    monkeypatch.setattr(install,"run_preflight",lambda *_args,**_kw:install.Step("preflight",True,"script passed"))
    assert not case.handler._repair_preflight(case.project,[(ki,cfg)],seen.append)
    assert inv.pending_preflight(case.project)["pending"]
    assert "NEW_DEPENDENCY" in "".join(seen)


def test_shared_ki_cannot_substitute_for_applied_project_preflight(case,monkeypatch):
    apply_verified(case,monkeypatch)
    shared=case.root.parent.parent/"shared"
    shared.mkdir();(shared/"SKILL.md").write_text("another copy")
    with pytest.raises(ValueError,match="adopted project KI"):
        case.handler._repair_preflight(case.project,[(KI("M",shared),paths.KissConfig.default(shared))],lambda _:None)
    assert inv.pending_preflight(case.project)["pending"]


def test_chat_passing_repair_preflight_hands_off_without_provider(case,monkeypatch):
    apply_verified(case,monkeypatch)
    cfg=paths.KissConfig.default(case.root.parent)
    ki=KI("M",case.root)
    case.handler._session_workspaces=lambda *_:[(ki,cfg)]
    monkeypatch.setattr(gui.flowrun,"provider_refusal",lambda *_:None)
    monkeypatch.setattr(gui.flowrun,"setup_allowed",lambda *_:True)
    turn=object();verified=[]
    monkeypatch.setattr(gui.flowrun,"setup_turn",lambda *_args,**_kw:turn)
    monkeypatch.setattr(gui.flowrun,"setup_verified",lambda *args:verified.append(args))
    monkeypatch.setattr(install,"run_preflight",lambda *_args,**_kw:install.Step("preflight",True,"fixture probe"))
    result=case.handler._chat_with_models(["M"],"api:deepseek","Continue",lambda _:None,case.project,
                                        flow_pre=SimpleNamespace(gated=True))
    assert result is turn
    assert len(verified)==1
    assert not inv.pending_preflight(case.project)["pending"]


@pytest.mark.parametrize("provider", ["api:deepseek", "cli:claude"])
@pytest.mark.parametrize("outcome", ["pass", "fail", "stop_before_setup", "stop_during_setup"])
def test_failed_repair_preflight_gets_bounded_setup_then_exact_project_recheck(
        case, monkeypatch, provider, outcome):
    apply_verified(case, monkeypatch)
    project_ki = KI("M", case.root)
    source = case.work / "catalogue/M/ki"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("Library revision, not the adopted project revision")
    source_ki = KI("M", source)
    cfg = paths.KissConfig.default(case.project)
    saved_cfg_value = cfg.dumps()
    (case.project / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    saved_config = (case.project / paths.CONFIG_NAME).read_bytes()
    saved_ki = kdtstudio.tree_digest(case.root)
    shared = case.handler._workdir(project_ki)
    shared.mkdir(parents=True)
    status = shared / "status.json"
    status.write_text('{"ok":true,"retained":"shared installation"}')
    saved_status = status.read_bytes()
    adopted_manifest = gui.Manifest.stub_for(project_ki)
    adopted_manifest.python_deps = ["repair-test-dep>=2"]
    library_manifest = gui.Manifest.stub_for(source_ki)
    library_manifest.python_deps = ["obsolete-library-dep"]
    case.handler._ki = lambda _name: source_ki
    case.handler._manifest = lambda ki: adopted_manifest if ki.root == case.root else library_manifest
    case.handler._session_workspaces = lambda *_: [(project_ki, cfg)]
    case.handler._software_status_prompt = lambda *_: ""
    case.handler._agent_runtime_env = lambda *_: {}
    case.handler.repo_root = case.work
    case.handler.catalog = SimpleNamespace(models_dir=source.parent.parent)
    calls, prompts, verified, probes, requirements = [], [], [], [], []
    handle = gui.api.TurnHandle()
    events = {"_handle": handle}
    turn = SimpleNamespace(kind="setup", session=SimpleNamespace(check_tool=lambda *_: None),
                           wrappers={}, fingerprint_extra="repair-setup", planning_worktree=None)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Project repair must not rematerialize or write shared installation status")

    monkeypatch.setattr(gui.setup_flow, "prepare", forbidden)
    monkeypatch.setattr(gui, "run_install", forbidden)
    case.handler._record_agent_preflight = forbidden
    monkeypatch.setattr(gui.flowrun, "provider_refusal", lambda *_: None)
    monkeypatch.setattr(gui.flowrun, "setup_allowed", lambda *_: True)
    monkeypatch.setattr(gui.flowrun, "setup_turn", lambda *_args, **_kw: calls.append("setup-turn") or turn)
    monkeypatch.setattr(gui.flowrun, "setup_verified", lambda *args: verified.append(args))
    monkeypatch.setattr(gui.flowrun, "policy_for_cli", lambda *_: None)
    monkeypatch.setattr(gui.skilllib, "prompt_block", lambda *_: "")
    monkeypatch.setattr(gui.skilllib, "roots", lambda: [])
    monkeypatch.setattr(gui.skilllib, "selected", lambda *_: [])
    monkeypatch.setattr(gui.mcp, "prompt_block", lambda *_args, **_kw: "")
    monkeypatch.setattr(gui.calibration, "prompt_block", lambda *_: "")
    monkeypatch.setattr(gui.calibration, "framework_root", lambda: None)
    monkeypatch.setattr(gui.install_locations, "info", lambda *_: {})
    monkeypatch.setattr(gui.settings, "database_access_mode", lambda: "off")
    monkeypatch.setattr(gui.prompt, "compose_multi", lambda _kis, _cfg, **kw: kw.get("task", "KI contract"))

    def preflight(ki, python, config, **kwargs):
        assert ki.root == case.root and config is cfg and python == cfg.python
        assert kwargs["project"] == case.project
        assert "Adopted preflight revision" in (ki.root / "preflight_check.py").read_text()
        probes.append(ki.root)
        return install.Step("preflight", True, "Adopted fixture script passed")

    def check_requirements(manifest, config, **kwargs):
        assert manifest is adopted_manifest and config is cfg
        requirements.append(manifest.python_deps)
        passed = len(requirements) > 1 and outcome == "pass"
        if outcome == "stop_before_setup":
            handle.stop()
        return install.Step("manifest-requirements", passed,
                            "Requirements satisfied" if passed else "Missing repair-test-dep>=2 in recorded Python")

    monkeypatch.setattr(install, "run_preflight", preflight)
    monkeypatch.setattr(gui.software_verification, "requirements", check_requirements)

    def provider_effect(prompt):
        calls.append("provider")
        prompts.append(prompt)
        assert "REPAIRED PROJECT KI SOFTWARE SETUP" in prompt
        assert "repair-test-dep>=2" in prompt and "obsolete-library-dep" not in prompt
        assert "Missing repair-test-dep>=2 in recorded Python" in prompt
        assert "Do not edit KI files" in prompt and "do not run simulations" in prompt
        assert cfg.dumps() == saved_cfg_value
        if outcome == "stop_during_setup":
            handle.stop()

    def api_run(_provider, ki, config, system, _task, **kwargs):
        assert ki.root == case.root and config is cfg
        assert kwargs["setup_mode"] and kwargs["project_mode"] and kwargs["flow"] is turn.session
        context = kwargs["setup_context"]
        assert context["installation_only"] and context["project_root"] == case.project
        assert "run_builtin" not in context
        provider_effect(system)
        yield "Fixture dependency setup attempted; host verification remains authoritative."

    def cli_run(_provider, **kwargs):
        assert kwargs["wd"] == case.project and kwargs["cfg"] is cfg
        assert kwargs["ki_root"] == case.root and kwargs["managed_roots"] == [case.root]
        assert kwargs["pol"].allows("exec", "pip")
        provider_effect(kwargs["replay_prompt"])
        return {"returncode": 0}

    monkeypatch.setattr(gui.api, "run", api_run)
    cli_provider = SimpleNamespace(name="claude")
    monkeypatch.setattr(gui.providers, "available", lambda: [cli_provider])
    monkeypatch.setattr(gui.providers, "get", lambda *_: cli_provider)
    case.handler._cli_turn = cli_run
    result = case.handler._chat_with_models(["M"], provider, "Continue", lambda _: True,
        case.project, flow_pre=SimpleNamespace(gated=True), runtime_events=events)

    assert result is turn
    assert calls == ["setup-turn"] + ([] if outcome == "stop_before_setup" else ["provider"])
    assert len(probes) == len(requirements) == (2 if outcome in {"pass", "fail"} else 1)
    assert len(verified) == (1 if outcome == "pass" else 0)
    if verified:
        assert verified == [(case.project, [project_ki], cfg)]
    assert inv.pending_preflight(case.project)["pending"] is (outcome != "pass")
    assert (case.project / paths.CONFIG_NAME).read_bytes() == saved_config
    assert cfg.dumps() == saved_cfg_value
    assert kdtstudio.tree_digest(case.root) == saved_ki
    assert status.read_bytes() == saved_status


@pytest.mark.parametrize("status,expected,retryable",[("review_failed","partial",True),
    ("author_failed","failed",True),("verification_failed","failed",True),("apply_failed","failed",False)])
def test_public_failure_states_preserve_repair_retry_policy(status,expected,retryable):
    value=gui._investigation_view({"id":"test","status":status,"draft":{"ki_name":"M","studio_job_id":"studio"}})
    assert value["status"]==expected and value["repair"]["retryable"] is retryable


@pytest.mark.parametrize("operation,retryable",[("authoring",True),("verifying",True),("applying",False)])
def test_interrupted_jobs_preserve_host_recovery_restrictions(operation,retryable):
    value=gui._investigation_view({"id":"test","status":"recovery_required" if operation=="applying" else "interrupted",
        "interrupted":True,"interrupted_operation":operation,"retryable":retryable,
        "draft":{"ki_name":"M","studio_job_id":"studio"}})
    assert value["status"]=="failed" and value["repair"]["retryable"] is retryable


@pytest.mark.parametrize("status,can_verify", [("draft", True), ("verified", True),
    ("verification_failed", True), ("author_failed", False), ("apply_failed", False),
    ("recovery_required", False), ("applied", False), ("authoring", False), ("verifying", False)])
def test_verification_can_retry_a_gate_failure_without_new_authoring(status, can_verify):
    view = gui._investigation_view({"id": "test", "status": status,
        "draft": {"ki_name": "M", "studio_job_id": "studio"}})
    assert view["repair"]["can_verify"] is can_verify
    assert not view["repair"]["can_apply"]


@pytest.mark.parametrize("operation,can_verify", [("authoring", False), ("verifying", True)])
def test_interrupted_verification_is_retryable_after_worker_recovery(operation, can_verify):
    view = gui._investigation_view({"id": "test", "status": "interrupted", "interrupted": True,
        "interrupted_operation": operation, "retryable": True,
        "draft": {"ki_name": "M", "studio_job_id": "studio"}})
    assert view["repair"]["can_verify"] is can_verify
