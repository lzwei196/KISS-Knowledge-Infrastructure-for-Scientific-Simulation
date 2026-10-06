"""Run the shipped catalogue watcher/picker against fake HTTP and timer events."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

PAGE = Path(__file__).parents[1] / "kiss_cli" / "web" / "app.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is required")
RUNNER = r"""
const fs=require('node:fs'),vm=require('node:vm');
const page=fs.readFileSync(process.argv[1],'utf8'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const elements=new Map(),timers=new Map(),requests=[],snapshots=[],events={};
let nextTimer=1,step={},releaseUpdate,releaseStatus,holdStatus=false,headerDraws=0;
const oldStatus={CRHM:{state:'verified',label:'Verified on this machine'},SHAW:{state:'verified'}};
const newStatus={CRHM:{state:'setup_needed',label:'Recheck updated KI'},SHAW:{state:'setup_needed'}};
const oldModels=[{name:'CRHM',reference:'old CRHM'},{name:'SHAW'}];
const newModels=[{name:'CRHM',reference:'updated CRHM'},{name:'SHAW'},
  {name:'HYDAT',package_role:'data_reader'}];
function element(key){
  if(!elements.has(key)){
    const names=new Set(),node={value:'',textContent:'',innerHTML:''};
    node.classList={add:n=>names.add(n),remove:n=>names.delete(n),contains:n=>names.has(n)};
    elements.set(key,node);
  }
  return elements.get(key);
}
element('#msg').value='  Keep my unsent scientific question.\n';
element('#mq').value='CRHM';element('#mpick').classList.add('open');
element('#prov').value='api:deepseek';element('#llm').value='deepseek-chat';
const session={id:'case',models:['CRHM'],provider:'api:deepseek',llm_model:null};
const context={console,Date,$:element,CUR:session,MODELS:oldModels,STATUS:oldStatus,
  PICK:new Set(['CRHM','SHAW']),DRAFTS:new Map([['case',element('#msg').value]]),
  PROV:{providers:[]},LAST_PROVIDER_CHECK:0,LAST_STATUS_CHECK:0,STATUS_REFRESHING:null,
  chineseUI:()=>!!input.zh,esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;'),
  drawModelLabel(){headerDraws++;},refreshSessionList(){},refreshProviders(){},
  pauseProjectMedia(){},resumeProjectMedia(){},
  document:{hidden:false,querySelectorAll:()=>[],addEventListener:(name,fn)=>events[name]=fn},
  window:{addEventListener:(name,fn)=>events[name]=fn},
  setTimeout(fn,delay){const id=nextTimer++;timers.set(id,{fn,delay});return id;},
  clearTimeout:id=>timers.delete(id)};
context.fetch=async(url,options)=>{
  requests.push({url,method:options?.method||'GET'});
  if(url==='/api/ki-updates'){
    if(step.deferUpdate)await new Promise(resolve=>{releaseUpdate=resolve;});
    if(step.reportFailure)throw new Error('Temporary local read failure');
    return {ok:true,json:async()=>step.report};
  }
  if(url==='/api/status'&&holdStatus){
    holdStatus=false;
    await new Promise(resolve=>{releaseStatus=resolve;});
    return {ok:true,json:async()=>oldStatus};
  }
  const failed=step.fail===url;
  return {ok:!failed,status:failed?503:200,json:async()=>
    step.invalid===url?null:url==='/api/models'?(step.old?oldModels:newModels):(step.old?oldStatus:newStatus)};
};
vm.createContext(context);
function shipped(start,end){
  const a=page.indexOf(start),b=page.indexOf(end,a);
  if(a<0||b<0)throw new Error('Missing shipped segment '+start);
  vm.runInContext(page.slice(a,b),context);
}
shipped('let KI_UPDATE_REVISION=','function workLabel(');
shipped('function stateClass(n){','async function loadAll(');
shipped('function drawPick(){','$("#pickmodels").onclick=');
shipped('window.addEventListener("focus",()=>{','$("#theme").onclick=');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function snapshot(){return {
  revision:vm.runInContext('KI_UPDATE_REVISION',context),models:context.MODELS,status:context.STATUS,
  timerDelays:[...timers.values()].map(t=>t.delay),requests:[...requests],headerDraws,
  picker:element('#mrows').innerHTML,pendingSelection:[...context.PICK],query:element('#mq').value,
  session:context.CUR,sameSession:context.CUR===session,composer:element('#msg').value,
  draft:context.DRAFTS.get('case'),provider:element('#prov').value,model:element('#llm').value,
  noticeOpen:element('#ki-update-toast').classList.contains('open'),title:element('#ki-update-title').textContent
};}
(async()=>{
  context.drawPick();
  for(step of input.steps){
    if(step.dismiss)element('#ki-update-toast').classList.remove('open');
    let oldPending;
    if(step.staleStatus){holdStatus=true;oldPending=context.refreshMachineStatus(true,true);await flush();}
    let pending;
    if(step.tick){
      const [id,timer]=[...timers.entries()][0]||[];
      if(!timer)throw new Error('Watcher stopped after terminal report');
      timers.delete(id);pending=timer.fn();
    }else if(step.event){events[step.event]();pending=vm.runInContext('KI_UPDATE_REFRESHING',context);}
    else pending=context.watchKiUpdates();
    await flush();
    if(step.concurrent){context.watchKiUpdates();context.watchKiUpdates();await flush();}
    if(step.deferUpdate)releaseUpdate();
    await pending;
    if(oldPending){releaseStatus();await oldPending;}
    await context.STATUS_REFRESHING;
    snapshots.push(snapshot());
  }
  process.stdout.write(JSON.stringify(snapshots));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


def run_steps(*steps, **kwargs):
    result = subprocess.run([NODE, "-e", RUNNER, str(PAGE)],
                            input=json.dumps({"steps": steps, **kwargs}), capture_output=True,
                            text=True, encoding="utf-8", check=True, timeout=10)
    return json.loads(result.stdout)


OLD = {"state": "error", "active_revision": "old", "checked_at": 1, "error": "Old failure"}
NEW = {"state": "updated", "active_revision": "new", "checked_at": 2, "summary": "Updated"}


def test_terminal_then_checking_then_activated_refreshes_open_picker_without_losing_work():
    old, checking, updated = run_steps(
        {"report": OLD, "old": True},
        {"tick": True, "report": {**OLD, "state": "checking"}, "old": True},
        {"tick": True, "report": NEW})
    assert old["noticeOpen"] and old["timerDelays"] == [5000]
    assert "Verified on this machine" in old["picker"]
    assert not checking["noticeOpen"] and checking["timerDelays"] == [1000]
    assert updated["revision"] == "new" and updated["timerDelays"] == [5000]
    assert updated["noticeOpen"] and updated["title"] == "KI library checked"
    assert "Recheck updated KI" in updated["picker"] and "updated CRHM" in updated["picker"]
    assert "Verified on this machine" not in updated["picker"]
    assert updated["pendingSelection"] == ["CRHM", "SHAW"] and updated["query"] == "CRHM"
    assert updated["sameSession"] and updated["session"] == old["session"]
    assert updated["session"]["models"] == ["CRHM"] and updated["session"]["llm_model"] is None
    assert updated["composer"] == updated["draft"] == old["composer"]
    assert updated["provider"] == "api:deepseek" and updated["model"] == "deepseek-chat"
    assert all(r["method"] == "GET" for r in updated["requests"])
    assert {r["url"] for r in updated["requests"]} == {"/api/ki-updates", "/api/models", "/api/status"}


def test_same_report_does_not_reopen_dismissed_notice_or_refetch_catalogue():
    first, same, changed = run_steps(
        {"report": NEW}, {"tick": True, "dismiss": True, "report": NEW},
        {"tick": True, "report": {**NEW, "state": "up_to_date", "checked_at": 3}})
    assert first["noticeOpen"] and not same["noticeOpen"] and changed["noticeOpen"]
    assert sum(r["url"] == "/api/models" for r in changed["requests"]) == 1
    assert sum(r["url"] == "/api/status" for r in changed["requests"]) == 1


@pytest.mark.parametrize("failure", [{"fail": "/api/models"}, {"fail": "/api/status"},
                                    {"invalid": "/api/models"}, {"invalid": "/api/status"}])
def test_failed_refresh_keeps_previous_pair_and_retries_same_revision(failure):
    old, failed, recovered = run_steps(
        {"report": OLD, "old": True}, {"tick": True, "report": NEW, **failure},
        {"tick": True, "report": NEW})
    assert failed["revision"] == "old"
    assert failed["models"] == old["models"] and failed["status"] == old["status"]
    assert not failed["noticeOpen"] and failed["timerDelays"] == [5000]
    assert recovered["revision"] == "new" and "Recheck updated KI" in recovered["picker"]


def test_transient_report_failure_keeps_polling():
    failed, recovered = run_steps({"reportFailure": True}, {"tick": True, "report": NEW})
    assert failed["revision"] == "" and failed["timerDelays"] == [5000]
    assert recovered["revision"] == "new"


def test_overlapping_watchers_share_one_request_and_one_timer():
    result, = run_steps({"report": NEW, "deferUpdate": True, "concurrent": True})
    assert [r["url"] for r in result["requests"]].count("/api/ki-updates") == 1
    assert result["timerDelays"] == [5000] and result["revision"] == "new"


def test_status_response_started_before_activation_cannot_restore_old_verification():
    old, result = run_steps({"report": OLD, "old": True},
                            {"tick": True, "report": NEW, "staleStatus": True})
    assert old["status"]["CRHM"]["state"] == "verified"
    assert result["status"]["CRHM"]["state"] == "setup_needed"
    assert "Recheck updated KI" in result["picker"]


@pytest.mark.parametrize("event", ["focus", "visibilitychange"])
def test_returning_to_chat_checks_catalogue_without_waiting_for_timer(event):
    old, result = run_steps({"report": OLD, "old": True}, {"event": event, "report": NEW})
    assert old["revision"] == "old" and result["revision"] == "new"
    assert "Recheck updated KI" in result["picker"] and result["sameSession"]
    assert result["timerDelays"] == [5000]


def test_updated_notice_remains_bilingual():
    result, = run_steps({"report": NEW}, zh=True)
    assert result["title"] == "KI 库检查完成"
