"""Execute the shipped status renderer with fixture projections, without a browser.

These tests do not reimplement the renderer: Node evaluates the actual functions
and request handlers extracted from app.html. No server or provider is contacted.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


PAGE = Path(__file__).parents[1] / "kiss_cli" / "web" / "app.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is required for renderer checks")

RUNNER = r"""
const fs=require('node:fs'),vm=require('node:vm');
const page=fs.readFileSync(process.argv[1],'utf8');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const extract=(start,end)=>{
  const a=page.indexOf(start),b=page.indexOf(end,a);
  if(a<0||b<0)throw new Error('Renderer extraction point not found');
  return page.slice(a,b);
};
const elements=new Map();
const element=selector=>{
  if(!elements.has(selector))elements.set(selector,{value:'',textContent:'',style:{},focus(){},classList:{remove(){}}});
  return elements.get(selector);
};
const context={
  RUN:null,console,CUR:{id:'fixture-session'},DRAFTS:new Map(),PENDING_ACTIONS:new Map(),
  chineseUI:()=>Boolean(input.zh),
  esc:value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),
  durationLabel:seconds=>`${Math.floor(Number(seconds)||0)}s`,
  drawRunStatus:run=>{context.drawnRun=run;},
  itemNote:()=>'',sessionBusy:()=>false,
  $:element,document:{querySelectorAll:()=>[]},
  navigator:{clipboard:{writeText:async value=>{context.copied=value;}}},
  showActionPicker:(request,id)=>{context.picked={request,id};},
  send:async()=>{context.sent=element('#msg').value;},
  providerDisplay:value=>value,elapsedTime:()=> '30s',
  status:'', // A real browser has window.status; it must not mask agentStatus.
};
vm.createContext(context);
vm.runInContext(extract('const RUN_GROUPS=[','function runButtonLabel'),context);
vm.runInContext(extract('const sizeLabel=','let SUBSET_TIMER=null;'),context);
(async()=>{
  let result;
  if(input.mode==='action'){
    const handlers=extract('  const respond=$("#request-respond");','  const calibrationButton=$("#calibration-agent");');
    vm.runInContext(`function wireStatusActions(data){${handlers}}`,context);
    context.wireStatusActions(input.data);
    await element(input.selector).onclick();
    result={picked:context.picked,sent:context.sent,copied:context.copied,
      pending:context.PENDING_ACTIONS.get(context.CUR.id)};
  }else if(input.mode==='activity'){
    vm.runInContext(extract('function agentLiveState(flight){','function agentActivityTitle'),context);
    vm.runInContext(extract('function agentStateText(flight,compact=false){','function liveWaitingHtml'),context);
    result={text:context.agentStateText(input.flight)};
  }else{
    result={html:context.renderData(input.data),run:context.drawnRun,
      request:context.projectStatusRequest(input.data)};
  }
  process.stdout.write(JSON.stringify(result));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


def evaluate(data=None, **extra):
    completed = subprocess.run(
        [NODE, "-e", RUNNER, str(PAGE)],
        input=json.dumps({"data": data, **extra}), text=True,
        capture_output=True, check=True, timeout=15,
    )
    return json.loads(completed.stdout)


def fixture_data():
    return {
        "human_request": {"status": "waiting", "title": "Stale raw request"},
        "project_run": {"goal": "Test the real model", "status": "complete", "stage": "results",
                        "blocker": {"status": "waiting", "title": "Stale blocker"}},
        "plans": [{"model": "Demo", "datasets": [{"name": "Weather", "present": False}]}],
        "preparation": {
            "active": True, "models": [{"name": "Demo"}], "software_summary": {},
            "lanes": [{"id": "parameters", "label": "Parameters", "count": 1, "items": []}],
        },
        "plan_data": {"total": 1, "counts": {"failed": 1},
                      "items": [{"id": "rain", "group": "fetch", "status": "failed"}]},
        "project_status": {
            "request": None,
            "progress": {"goal": "Test the real model", "selected_kis": ["Demo"],
                         "status": "working", "stage": "running", "summary": "Host run state",
                         "source": "flow-state", "age_seconds": 12},
            "data_summary": {"severity": "block", "available": 0, "total": 1,
                             "label": "Acquisition failed"},
            "technical": {
                "overall": {"label": "Input evidence incomplete", "cls": "warn", "mark": "?"},
                "lanes": {"parameters": {"label": "No validation evidence", "cls": "warn", "mark": "?"}},
            },
            "observations": [{"source": "download-receipt", "age_seconds": 30,
                              "summary": "Download did not finish"}],
        },
    }


def test_running_stage_does_not_mark_unevidenced_lane_ready():
    result = evaluate(fixture_data())
    assert 'data-ready-group warn' in result["html"]
    assert "No validation evidence" in result["html"]
    assert "Ready to use" not in result["html"]
    assert result["run"]["status"] == "working"
    assert "Project complete" not in result["html"]


@pytest.mark.parametrize("stage", ["validating", "running", "results"])
def test_current_stage_does_not_check_off_earlier_scientific_steps(stage):
    data = fixture_data()
    data["project_status"]["progress"].update(status="working", stage=stage)
    html = evaluate(data)["html"]
    assert 'runstep active' in html
    assert 'runstep done' not in html
    assert '<span class="stepdot">✓</span>' not in html


def test_plan_summary_renders_host_severity_and_count_not_local_count_rules():
    data = fixture_data()
    # Deliberately incompatible legacy counts must not override the projection.
    data["plan_data"]["counts"] = {"done": 1}
    html = evaluate(data)["html"]
    assert 'class="statuspill block" data-plan-data-summary>0/1 · Acquisition failed' in html
    assert "Fetch failed" in html


@pytest.mark.parametrize("status,label", [
    ("present_unverified", "Present; not verified"),
    ("acquired", "Acquired; scientific checks pending"),
    ("produced", "Produced; scientific checks pending"),
])
def test_file_presence_and_production_are_not_scientific_readiness(status, label):
    data = fixture_data()
    data["plan_data"]["items"][0].update(status=status, how="provide")
    data["project_status"]["data_summary"].update(severity="warn", available=1, label="Files available")
    html = evaluate(data)["html"]
    assert f'class="actiontag warn">{label}' in html
    assert 'pd-upload' not in html
    assert "Ready to use" not in html


def test_missing_projection_does_not_promote_old_completion_or_stale_request():
    data = fixture_data()
    del data["project_status"]
    html = evaluate(data)["html"]
    assert "Status unconfirmed" in html
    assert "Data status unconfirmed" in html
    assert "Project complete" not in html
    assert "Ready to use" not in html
    assert 'id="human-request"' not in html
    assert 'runstep done' not in html


def test_cleared_request_does_not_reappear_from_raw_or_historical_blocker():
    html = evaluate(fixture_data())["html"]
    assert 'id="human-request"' not in html
    assert "Stale raw request" not in html
    assert "Stale blocker" not in html


def request_data(kind="decision"):
    data = fixture_data()
    data["project_status"]["request"] = {
        "id": "flow-approve-current", "status": "waiting", "kind": kind,
        "title": "Current canonical request", "message": "Host-issued review",
        "expected_path": "inputs/current.dat", "options": [{"id": "approve", "label": "Approve"}],
        "plan_review": {"goal": "Full plan retained", "steps": [{"id": "scientific-step"}]},
        "review": {"shown_sha256": "host-display-proof"},
    }
    return data


def test_request_display_and_respond_preserve_full_canonical_plan_review():
    data = request_data()
    rendered = evaluate(data)
    assert "Current canonical request" in rendered["html"]
    assert "Stale raw request" not in rendered["html"]
    assert rendered["html"].index('id="human-request"') < rendered["html"].index('id="plan-data"')
    action = evaluate(data, mode="action", selector="#request-respond")
    assert action["picked"]["request"] == data["project_status"]["request"]


def test_download_done_uses_the_path_and_title_actually_displayed():
    data = request_data("download")
    action = evaluate(data, mode="action", selector="#request-done")
    assert action["sent"] == "I placed Current canonical request at inputs/current.dat. Please continue."


def test_change_plan_uses_the_same_current_request_id():
    action = evaluate(request_data("download"), mode="action", selector="#request-modify")
    assert action["pending"] == {"request_id": "flow-approve-current", "option_id": "modify", "note": ""}


def test_copy_path_uses_the_same_current_request():
    action = evaluate(request_data("download"), mode="action", selector="#request-copy-path")
    assert action["copied"] == "inputs/current.dat"


def test_evidence_source_age_and_untrusted_text_are_rendered_safely():
    data = fixture_data()
    data["project_status"]["observations"][0]["summary"] = "<script>bad()</script>"
    html = evaluate(data)["html"]
    assert "flow-state · observed 12s ago" in html
    assert "download-receipt · observed 30s ago" in html
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html
    assert "<script>bad()</script>" not in html


@pytest.mark.parametrize("silence", [2, 25])
def test_activity_detail_comes_from_agent_status_not_window_status(silence):
    result = evaluate(mode="activity", flight={
        "provider": "Kimi", "started": 1, "agentStatus": {
            "process_alive": True, "event_silence_seconds": silence,
            "activity_detail": "Inspecting source dataset header",
        },
    })
    assert "Inspecting source dataset header" in result["text"]
