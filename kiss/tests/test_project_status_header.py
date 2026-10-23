"""Project header and data reads use current exact-project evidence, read-only."""
import json
from pathlib import Path
import shutil
import subprocess
from http.client import HTTPMessage

import pytest

from kiss_cli import gui, ki_guard, project_status
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest
from .test_project_verification import case, pv, _forbid_checks

SID = "b8b03523f587"
PAGE = Path(__file__).parents[1] / "kiss_cli/web/app.html"
NODE = shutil.which("node")


def handler_for(case, monkeypatch):
    project, ki, man, cfg, config = case
    h = object.__new__(gui.Handler)
    h.headers = HTTPMessage()
    h.workroot = project.parent
    h._setup_ok_for = lambda s: False
    h._ki = lambda name: KI(name, project.parent / "shared-library" / name)
    h._manifest = lambda selected: Manifest.load(selected.manifest) if selected.manifest else man
    h._status_for = lambda *a: pytest.fail("retained project must not read shared readiness")
    h._session_config = lambda *a: pytest.fail("status must not prepare project or change bindings")
    monkeypatch.setattr(gui.sessions, "project_path", lambda *a: project)
    monkeypatch.setattr(gui.sessions, "load", lambda *a: {"id": SID, "models": [ki.name]})
    monkeypatch.setattr(gui.sessions, "input_files", lambda *a: [])
    monkeypatch.setattr(gui.sessions, "reference_files", lambda *a: [])
    monkeypatch.setattr(gui.sessions, "provenance_records", lambda *a: [])
    monkeypatch.setattr(gui.flowrun, "poll_acquisition", lambda *a, **k: None)
    monkeypatch.setattr(gui.projectrun, "load", lambda *a, **k: {"selected_kis": [ki.name]})
    monkeypatch.setattr(gui, "_agent_run_snapshot", lambda *a: {})
    monkeypatch.setattr(gui.calibration, "project_state", lambda *a: {})
    return h


@pytest.mark.parametrize("drift", [None, "config", "ki", "receipt"])
def test_run_route_carries_actual_current_project_proof_without_shared_fallback(case, monkeypatch, drift):
    project, ki, man, cfg, config = case
    assert pv.verify(project, ki, man)["ok"]  # Real harmless preflight subprocess.
    if drift == "config":
        cfg.python = str(project / "missing-python")
        config.write_text(cfg.dumps(), encoding="utf-8")
    elif drift == "ki":
        (ki.root / "SKILL.md").write_text("changed", encoding="utf-8")
    elif drift == "receipt":
        p = pv._receipt_path(project, ki.name)
        d = json.loads(p.read_text(encoding="utf-8")); d["checked_at"] += 1
        p.write_text(json.dumps(d), encoding="utf-8")
    flow = gui.flowrun.flowgate.load()
    ctx = flow.states.FlowContext.load(project); ctx.selected_kis = [ki.name]; ctx.save()
    before = {str(p): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    h = handler_for(case, monkeypatch)
    h.path = f"/api/session/{SID}/run"
    h._json = lambda doc, *a: doc
    _forbid_checks(monkeypatch)
    result = h.do_GET()
    assert result["session"] == SID
    assert result["selected_kis"] == [ki.name]
    row = result["project_preflights"][0]
    assert row["name"] == ki.name and row["can_run"] is (drift is None)
    assert row["state"] == ("verified" if drift is None else "stale")
    assert before == {str(p): p.read_bytes() for p in project.rglob("*") if p.is_file()}


def test_data_panel_uses_adopted_manifest_and_exact_saved_roles(case, monkeypatch):
    project, ki, man, cfg, config = case
    manifest = ki.root / "kiss.yaml"
    manifest.write_text("kiss_manifest_version: 1\nmodel: Demo\ndata:\n  - name: Adopted inputs\n    role: data\n    probe: adopted\n", encoding="utf-8")
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(project.parent / "new-fixture-guard"))
    ki_guard.enroll(ki.root)
    man = Manifest.load(manifest)
    cfg.roles["data"].mkdir(parents=True, exist_ok=True)
    (cfg.roles["data"] / "adopted").write_text("actual file", encoding="utf-8")
    assert pv.verify(project, ki, man)["ok"]
    h = handler_for((project, ki, man, cfg, config), monkeypatch)
    seen = []
    original = gui.build_data_plan
    def capture(k, m, c, status, deps):
        seen.append((k, m, c, status))
        return original(k, m, c, status, deps)
    monkeypatch.setattr(gui, "build_data_plan", capture)
    _forbid_checks(monkeypatch)
    before = config.read_bytes()
    result = h._session_data({"id": SID, "models": [ki.name]})
    assert seen[0][0].root == ki.root
    assert seen[0][1].data[0].name == "Adopted inputs"
    assert seen[0][2].roles["data"] == cfg.roles["data"]
    assert seen[0][3]["can_run"] is True
    assert result["plans"][0]["datasets"][0]["name"] == "Adopted inputs"
    assert config.read_bytes() == before


@pytest.mark.parametrize("damage", ["guard", "config"])
def test_data_route_reports_bad_retained_context_without_catalogue_fallback(case, monkeypatch, damage):
    project, ki, man, cfg, config = case
    if damage == "guard":
        (ki.root / "SKILL.md").write_text("tampered", encoding="utf-8")
    else:
        config.write_text("not toml {", encoding="utf-8")
    h = handler_for(case, monkeypatch)
    h.path = f"/api/session/{SID}/data"
    h._json = lambda data, code=200: (code, data)
    code, data = h.do_GET()
    assert code == 409 and data["error"]


def test_file_availability_does_not_claim_preparation_missing_or_science_passed():
    result = project_status._data_summary({"items": [{"id": "x"}], "counts": {"produced": 1}})
    assert result["label"] == "Files available" and result["available"] == 1
    note = project_status._technical({}, [], result)["overall"]["note"]
    assert "technical completion" in note and "independent scientific validation" in note


@pytest.mark.parametrize("state,expected", [("PLANNING", "planning"), ("REPLAN_REQUIRED", "planning"),
    ("PLAN_REVIEW", "planning"), ("WAITING_FOR_USER", "planning"), ("ACQUIRING", "acquiring"),
    ("EXECUTING", "preparing"), ("tampered", None)])
def test_activity_caption_uses_current_signed_host_phase_not_old_agent_stage(case, monkeypatch, state, expected):
    project, ki, *_ = case
    flow = gui.flowrun.flowgate.load()
    ctx = flow.states.FlowContext.load(project)
    ctx.state = flow.states.State.REPLAN_REQUIRED if state == "tampered" else flow.states.State(state)
    ctx.selected_kis = [ki.name]; ctx.save()
    if state == "tampered":
        p = project / "runs/flow-state.json"
        doc = json.loads(p.read_text(encoding="utf-8")); doc["state"] = "EXECUTING"
        p.write_text(json.dumps(doc), encoding="utf-8")
    before = (project / "runs/flow-state.json").read_bytes()
    monkeypatch.setattr(gui.projectrun, "load", lambda *a, **k: {"stage": "preparing", "status": "working"})
    monkeypatch.setattr(gui, "_project_file_evidence", lambda *a, **k: {})
    events = {"project": str(project), "provider": "api:deepseek"}
    gui._register_agent_run(SID, events)
    try:
        result = gui._agent_run_snapshot(SID)
        assert result["project_stage"] == expected
        assert result["process_alive"] is True
        assert (project / "runs/flow-state.json").read_bytes() == before
    finally:
        gui._LIVE_AGENT_RUNS.pop(SID, None)


RUNNER = r'''
const fs=require('node:fs'),vm=require('node:vm');
const page=fs.readFileSync(process.argv[1],'utf8'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const take=(a,b)=>page.slice(page.indexOf(a),page.indexOf(b,page.indexOf(a)));
const nodes=new Map(),requests=[];
const $=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',className:'',title:'',html:'',remove(){this.html=''},insertAdjacentHTML(_p,x){this.html=x}});return nodes.get(id)};
const c={console,$,CUR:{id:'one',models:['Demo']},SESSIONS:[],KI_UPDATE_REVISION:'revision',
 STATUS:{Demo:{state:'failed',can_run:false,label:'KI edit needs verification'}},
 chineseUI:()=>!!input.zh,esc:s=>String(s??''),drawRunStatus:()=>{},rememberAcquisition:()=>{},ACQUISITION_TRACKED:new Map(),
 fetch:async()=>{throw Error('unexpected fetch')}};
vm.createContext(c);
vm.runInContext(take('// Project readiness is distinct','function stateClass'),c);
vm.runInContext(take('function drawModelLabel(){','function addTurn'),c);
vm.runInContext(take('async function refreshRun(','const ACQUISITION_TRACKED='),c);
const snapshot=()=>({label:$('#mlabel').textContent,badge:$('#kistatus').textContent,cls:$('#kistatus').className,banner:$('#chat').html,title:$('#kistatus').title});
const run={session:'one',selected_kis:['Demo'],project_preflights:[{name:'Demo',state:'verified',can_run:true}]};
(async()=>{
 let result;
 if(input.mode==='header'){
   if(input.models)c.CUR.models=input.models;
   if(input.shared)c.STATUS=input.shared;
   c.fetch=async()=>({ok:true,json:async()=>({...run,...input.run})});
   await c.refreshRun('one');c.drawModelLabel();result=snapshot();
 }else if(input.mode==='failure'){
   c.fetch=async()=>({ok:true,json:async()=>run});await c.refreshRun('one');
   c.fetch=async()=>{throw Error('offline')};await c.refreshRun('one');result=snapshot();
 }else if(input.mode==='switch'){
   let finish;c.fetch=()=>new Promise(resolve=>finish=resolve);
   const pending=c.refreshRun('one');c.CUR={id:'two',models:['Other']};c.drawModelLabel();
   finish({ok:true,json:async()=>run});await pending;result=snapshot();
 }else if(input.mode==='race'){
   const finish=[];c.fetch=()=>new Promise(resolve=>finish.push(resolve));
   const old=c.refreshRun('one'),fresh=c.refreshRun('one',true);
   finish[1]({ok:true,json:async()=>({...run,project_preflights:[{name:'Demo',state:'stale',can_run:false}]})});await fresh;
   finish[0]({ok:true,json:async()=>run});await old;result=snapshot();
 }else if(input.mode==='slow'){
   let finish,count=0;c.fetch=()=>{count++;return new Promise(resolve=>finish=resolve)};
   const first=c.refreshRun('one'),second=c.refreshRun('one'),third=c.refreshRun('one');
   finish({ok:true,json:async()=>run});await Promise.all([first,second,third]);
   result={...snapshot(),count};
 }else if(input.mode==='selection'){
   c.fetch=async()=>({ok:true,json:async()=>run});await c.refreshRun('one');
   c.CUR.models=['Other'];c.drawModelLabel();result=snapshot();
 }else if(input.mode==='revision'){
   c.fetch=async()=>({ok:true,json:async()=>run});await c.refreshRun('one');
   c.KI_UPDATE_REVISION='new-revision';c.drawModelLabel();result=snapshot();
 }else if(input.mode==='summary'){
   c.rememberSessionSummary({id:'one',project_path:'/actual',models:['Demo'],messages:[{},{}],message_count:44});
   const pointer={id:'one',external:true,project_path:'/actual',models:[],n:0};
   const known=c.mergeSessionSummaries([pointer])[0],unknown=c.mergeSessionSummaries([{...pointer,id:'two'}])[0];
   const foreign=c.mergeSessionSummaries([{...pointer,project_path:'/moved'}])[0];
   const zero=c.mergeSessionSummaries([{...pointer,external:false}])[0];
   result={known,unknown,foreign,zero,text:c.sessionSummaryText(unknown)};
 }
 process.stdout.write(JSON.stringify(result));
})().catch(e=>{console.error(e);process.exitCode=1});
'''


def ui(mode, **kw):
    if NODE is None:
        pytest.skip("Node required for actual shipped UI checks")
    result = subprocess.run([NODE, "-e", RUNNER, str(PAGE)], input=json.dumps({"mode": mode, **kw}),
                            encoding="utf-8", capture_output=True, check=True, timeout=15)
    return json.loads(result.stdout)


@pytest.mark.parametrize("zh", [False, True])
def test_current_project_pass_overrides_shared_dirty_header(zh):
    result = ui("header", zh=zh)
    assert result["cls"] == "statuspill ok"
    assert result["badge"] == ("项目预检通过" if zh else "Project preflight passed")
    assert not result["banner"] and "KI edit" not in result["badge"]


@pytest.mark.parametrize("state", ["failed", "stale", "cancelled", "unverified"])
def test_shared_pass_cannot_substitute_project_failure_or_absence(state):
    result = ui("header", shared={"Demo": {"state": "verified", "can_run": True}},
                run={"project_preflights": [{"name": "Demo", "state": state, "can_run": False}]})
    assert result["cls"] != "statuspill ok"
    if state == "failed":
        assert result["cls"] == "statuspill block" and result["badge"] == "Project preflight failed"
        assert "session=one" in result["banner"]
    else:
        # Not yet checked for this project: it is checked when an approved plan runs.
        assert result["cls"] == "statuspill" and result["badge"] == "Checked when it runs"
        assert not result["banner"]


@pytest.mark.parametrize("rows", [[], [{"name": "Other", "state": "verified", "can_run": True}],
    [{"name": "Demo", "state": "verified", "can_run": True}] * 2])
def test_missing_foreign_duplicate_rows_never_green(rows):
    assert ui("header", run={"project_preflights": rows})["cls"] != "statuspill ok"


@pytest.mark.parametrize("mode", ["failure", "switch", "selection", "revision", "race"])
def test_stale_async_or_changed_context_cannot_retain_green(mode):
    assert ui(mode)["cls"] != "statuspill ok"


def test_wrong_session_payload_cannot_mark_current_header_passed():
    assert ui("header", run={"session": "other"})["cls"] != "statuspill ok"


def test_pointer_poll_preserves_loaded_summary_without_inventing_unread_counts():
    result = ui("summary")
    assert result["known"]["models"] == ["Demo"] and result["known"]["n"] == 44
    assert result["unknown"]["n"] is None and "Messages not loaded" in result["text"]
    assert result["foreign"]["n"] is None
    assert result["zero"]["n"] == 0 and result["zero"]["metadata_loaded"]


def test_slow_overlapping_polls_coalesce_and_eventually_render_current_status():
    result = ui("slow")
    assert result["count"] == 1 and result["cls"] == "statuspill ok"
