"""Exercise the shipped idle-page timers without a browser or live backend.

An ACQUIRING chat can outlive its agent turn. Its automatic subsets must keep
advancing while the user reads the chat with Project status closed.
"""
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
const page=fs.readFileSync(process.argv[1],'utf8');
const input=JSON.parse(fs.readFileSync(0,'utf8')||'{}');
const requests=[],timers=[],elements=new Map(),pending=[],unhandled=[],readReleases=[],sent=[];
let now=0,posts=0,release=null;
const run={session:'mixed',selected_kis:['M'],project_preflights:[],goal:'Synthetic mixed acquisition',status:'waiting_for_user',stage:'acquiring',
  summary:'Waiting for you to place: yearbook',flow_state:input.flow_state||'ACQUIRING',
  ready_to_start:Boolean(input.ready),
  acquisition:{active:!input.unsigned&&(input.flow_state||'ACQUIRING')==='ACQUIRING',status:'waiting',
    automatic:input.manual_only?[]:[{id:'forcing',dataset_id:'cmfd-fixture',
      status:input.automatic_done?'done':input.unconfirmed?'unconfirmed':'pending',
      job_status:input.automatic_done||input.unconfirmed?null:'running'}],
    manual:input.automatic_only?[]:[{id:'yearbook',dataset_id:'yearbook-fixture',status:'waiting',expected_path:'inputs/yearbook'}],
    counts:{automatic_pending:input.manual_only||input.automatic_done||input.unconfirmed?0:1,
      automatic_acquired:input.automatic_done?1:0,automatic_failed:0,manual_waiting:input.automatic_only?0:1}}};
const otherRun={session:'other',selected_kis:['M'],project_preflights:[],goal:'Other project',status:'ready',flow_state:input.other_acquiring?'ACQUIRING':'PLANNING',acquisition:null};
function element(selector){
  if(!elements.has(selector))elements.set(selector,{innerHTML:'',textContent:'',value:'',dataset:{},hidden:true,
    classList:{contains:()=>false,add(){},remove(){},toggle(){}},
    querySelectorAll:()=>[],style:{},setAttribute(){},removeAttribute(){}});
  return elements.get(selector);
}
const context={console,KI_UPDATE_REVISION:'fixture',drawModelLabel(){},CUR:{id:'mixed',models:['M']},RUN:run,VIEW:null,SESSIONS:[],DRAFTS:new Map(),
  INFLIGHT:new Map(),DATA_ACTIONS:new Set(),LAST_PREP:null,$:element,
  document:{hidden:Boolean(input.hidden),querySelectorAll:()=>[]},chineseUI:()=>Boolean(input.zh),
  // Like the real send(): it reads the composer, then clears it and the chat's draft.
  async send(){sent.push(element('#msg').value);element('#msg').value='';context.DRAFTS.delete(context.CUR.id);},
  updateActivityUI(){},drawSessions(){},renderData:()=>'',esc:String,
  async drawDatabaseStatus(){},async refreshSubsets(){},
  searchObservationCatalogue(){},
  async refreshProjectView(){throw new Error('Closed Project View must not render');},
  sessionBusy:()=>false,
  Date:class extends Date {static now(){return now;}},
  setInterval(callback,ms){timers.push({callback,ms});return timers.length;},
  clearInterval(){},setTimeout(){return 1;},clearTimeout(){},
};
function response(payload,ok=true,status=ok?200:503){return {ok,status,json:async()=>payload};}
context.fetch=async(url,options={})=>{
  requests.push({url,method:options.method||'GET',at:now,current:context.CUR.id,
    headers:options.headers,body:options.body});
  const selected=url.includes('/other/')?otherRun:run;
  if(url.endsWith('/acquire')){
    posts++;
    if(input.error_once&&posts===1)throw new Error('Temporary connection failure');
    if(input.http_error_once&&posts===1)return response({error:'Temporarily unavailable'},false);
    if(input.archived_after_switch&&context.CUR.id==='other')return response({error:'Archived'},false,404);
    if(input.slow&&posts===1)await new Promise(resolve=>{release=resolve;});
    if(input.complete_after_post){
      selected.acquisition.automatic[0].status='done';
      selected.acquisition.automatic[0].job_status=null;
      selected.acquisition.counts.automatic_pending=0;
      selected.acquisition.counts.automatic_acquired=1;
    }
    return response({ok:true,flow_state:selected.flow_state,run:selected,acquisition:selected.acquisition});
  }
  if(input.slow_current_read&&url==='/api/session/other/run'){
    await new Promise(resolve=>{readReleases.push(resolve);});
  }
  return response(url==='/api/sessions'?[]:url.endsWith('/run')?selected:
    url.endsWith('/view')?{panels:[]}:url.endsWith('/data')?{run:selected,flow:{state:selected.flow_state},
      acquisition:selected.acquisition}:{configured:false});
};
vm.createContext(context);
function shipped(start,end){
  const a=page.indexOf(start),b=page.indexOf(end,a);
  if(a<0||b<0)throw new Error('Missing shipped JavaScript segment: '+start);
  vm.runInContext(page.slice(a,b),context);
}
shipped('// Project readiness is distinct','function stateClass');
shipped('let SESSION_REFRESHING=false;','const RUN_GROUPS=');
shipped('function runCompletionTitle(run){','function runButtonLabel');
shipped('function drawRunStatus(','function drawSessions(){');
context.runButtonLabel=()=>input.zh?'项目状态':'Project status';
context.runStateText=()=>'';
shipped('async function refreshData(){','$("#opendata").onclick=');
shipped('async function sendDataPanelPrompt(','async function startDataAgent(');
shipped('$("#acquisition-open").onclick=','$("#activity-refresh").onclick=');
// The page timer delegates its hidden/closed-view guard to this shipped helper.
// Keep the real guard; the rendering stub above still fails if it is bypassed.
shipped('async function pollProjectView(){','function pauseProjectMedia()');
// These are the actual page-lifetime timers after send() has cleared runPoll
// and deleted INFLIGHT. Do not reconstruct their logic in the fixture.
shipped('setInterval(updateActivityUI,1000);','$("#ki-update-view").onclick=');
async function flush(){for(let n=0;n<40;n++)await Promise.resolve();}
async function tick(){
  now+=5000;
  for(const timer of timers){
    const result=timer.callback();
    if(result&&typeof result.then==='function')pending.push(result.catch(error=>{unhandled.push(String(error));}));
  }
  await flush();
}
(async()=>{
  await tick();
  if(input.switch_session){context.CUR={id:'other',models:['M']};context.RUN=otherRun;}
  for(let n=1;n<(input.ticks||3);n++)await tick();
  const postsBeforeRelease=posts,requestsBeforeRelease=requests.slice();
  if(release){release();await flush();await tick();}
  for(const resolve of readReleases)resolve();
  await flush();
  if(input.click_start){
    if(input.draft){element('#msg').value=input.draft;context.DRAFTS.set('mixed',input.draft);}
    // A double click; a disabled button does not fire.
    for(let n=0;n<2;n++)if(!element('#acquisition-start').disabled)await element('#acquisition-start').onclick();
    await flush();
  }
  await Promise.all(pending);
  process.stdout.write(JSON.stringify({requests,sent,timerPeriods:timers.map(t=>t.ms),
    postsBeforeRelease,requestsBeforeRelease,unhandled,elements:[...elements.entries()].map(([key,e])=>
      ({key,text:e.textContent,html:e.innerHTML,hidden:e.hidden,disabled:Boolean(e.disabled)})),
    msg:element('#msg').value,draft:context.DRAFTS.get('mixed')??null,
    inflight:context.INFLIGHT.size,projectPanelOpen:element('#datapanel').classList.contains('open')}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


def poll(**options):
    # Node always writes UTF-8; the locale default (GBK on Chinese Windows) cannot decode it.
    result = subprocess.run([NODE, "-e", RUNNER, str(PAGE)],
                            input=json.dumps(options), capture_output=True, text=True,
                            encoding="utf-8", check=True, timeout=10)
    observed = json.loads(result.stdout)
    assert observed["inflight"] == 0 and not observed["projectPanelOpen"]
    assert not observed["unhandled"]
    return observed


def commands(observed):
    return [request for request in observed["requests"] if request["method"] != "GET"]


def test_idle_chat_polls_host_acquisition_with_manual_card_and_closed_project_panel():
    observed = poll()
    assert any(request["url"] == "/api/session/mixed/acquire" and request["method"] == "POST"
               for request in commands(observed)), (
        "No automatic acquisition tick after the agent turn ended. The real idle-page "
        f"timers made only these requests over 15 seconds: {observed['requests']}"
    )
    assert all(request["url"].endswith("/acquire") for request in commands(observed))
    assert all(request["headers"] == {"Content-Type": "application/json"}
               and json.loads(request["body"]) == {} for request in commands(observed)), (
        "Idle progress must not edit the plan or add a data selection")
    assert not any(request["url"].endswith("/data") for request in observed["requests"]), (
        "Automatic advancement must use its explicit command, not a read-only status GET")


@pytest.mark.parametrize("flow_state", ["PLANNING", "WAITING_FOR_USER", "EXECUTING", "BLOCKED"])
def test_idle_page_does_not_start_acquisition_outside_acquiring(flow_state):
    assert not commands(poll(flow_state=flow_state))


def test_acquiring_label_without_approved_active_acquisition_does_not_send_command():
    assert not commands(poll(unsigned=True))


@pytest.mark.parametrize("options", [{"manual_only": True}, {"automatic_done": True}])
def test_manual_wait_alone_does_not_keep_triggering_acquisition(options):
    assert not commands(poll(**options))


def test_slow_acquisition_request_is_not_duplicated_by_idle_timers():
    observed = poll(slow=True)
    assert observed["postsBeforeRelease"] == 1
    assert len(commands(observed)) >= 1


@pytest.mark.parametrize("failure", ["error_once", "http_error_once"])
def test_temporary_acquisition_failure_does_not_disable_later_retry(failure):
    observed = poll(**{failure: True})
    assert len(commands(observed)) >= 2
    assert {request["url"] for request in commands(observed)} == {"/api/session/mixed/acquire"}


def test_navigation_keeps_pending_acquisition_targeted_to_original_session():
    observed = poll(switch_session=True)
    original = [request for request in commands(observed) if request["url"] == "/api/session/mixed/acquire"]
    assert any(request["current"] == "other" for request in original)
    assert not any(request["url"] == "/api/session/other/acquire" for request in commands(observed))


def test_slow_current_status_read_does_not_stall_or_duplicate_background_acquisition():
    observed = poll(switch_session=True, slow_current_read=True, other_acquiring=True)
    requests = observed["requestsBeforeRelease"]
    background_ticks = [request for request in requests
                        if request["url"] == "/api/session/mixed/acquire"
                        and request["current"] == "other"]
    status_reads = [request for request in requests
                    if request["url"] == "/api/session/other/run"]
    assert (len(background_ticks) >= 2, len(status_reads)) == (True, 1), (
        "Already-approved background acquisition must keep advancing while the "
        "unrelated current project's status read is pending, with only one such "
        f"read in flight. Before releasing that read: {requests}"
    )


def test_archived_background_session_stops_acquisition_after_not_found():
    observed = poll(switch_session=True, archived_after_switch=True)
    original = [request for request in commands(observed) if request["url"] ==
                "/api/session/mixed/acquire"]
    assert [request["current"] for request in original] == ["mixed", "other"], (
        "A 404 must retire the tracked background session instead of retrying forever")


def test_mixed_banner_shows_automatic_progress_and_outstanding_manual_input():
    observed = poll()
    elements = {element["key"]: element for element in observed["elements"]}
    assert not elements["#acquisition-note"]["hidden"]
    automatic = elements["#acquisition-automatic"]["text"].lower()
    manual = elements["#acquisition-manual"]["text"].lower()
    assert "forcing" in automatic or "cmfd-fixture" in automatic
    assert "server subsetting" in automatic
    assert "yearbook" in manual
    assert "model execution waits for all required inputs" in elements["#acquisition-execution"]["text"].lower()


def test_banner_keeps_automatic_success_visible_while_manual_input_is_outstanding():
    observed = poll(automatic_done=True)
    elements = {element["key"]: element for element in observed["elements"]}
    assert not elements["#acquisition-note"]["hidden"]
    automatic = elements["#acquisition-automatic"]["text"].lower()
    assert any(word in automatic for word in ("acquired", "downloaded", "complete", "done"))
    assert "yearbook" in elements["#acquisition-manual"]["text"].lower()
    assert not commands(observed), "Acquired data must not be downloaded repeatedly during manual wait"


def test_automatic_completion_stops_polling_but_keeps_manual_wait_visible():
    observed = poll(complete_after_post=True)
    assert len(commands(observed)) == 1
    elements = {element["key"]: element for element in observed["elements"]}
    assert not elements["#acquisition-note"]["hidden"]
    assert "files acquired" in elements["#acquisition-automatic"]["text"].lower()
    assert "yearbook" in elements["#acquisition-manual"]["text"].lower()



def _banner(observed):
    return {element["key"]: element for element in observed["elements"]}


def _status_reads(observed):
    return [request for request in observed["requests"] if request["url"].endswith("/run")]


@pytest.mark.parametrize("flow_state", ["COMPLETED", "PLANNING"])
def test_idle_chat_outside_acquisition_reads_status_only_as_a_slow_fallback(flow_state):
    observed = poll(flow_state=flow_state, ticks=7)          # 35 simulated seconds
    assert len(_status_reads(observed)) == 1, _status_reads(observed)
    assert not commands(observed)


def test_hidden_page_does_not_read_project_status():
    assert not _status_reads(poll(hidden=True, ticks=7))


@pytest.mark.parametrize("options,title,footer", [
    ({}, "automatic and manual downloads are independent", "manual downloads do not block"),
    ({"automatic_only": True}, "fetching approved data", "waits for acquisition receipts"),
    ({"manual_only": True}, "manual download needed", "place the files, then confirm"),
    ({"automatic_only": True, "zh": True}, "正在获取已批准的数据", "获取回执"),
    ({"manual_only": True, "zh": True}, "需要手动下载", "放好文件后"),
])
def test_banner_wording_matches_the_outstanding_work(options, title, footer):
    elements = _banner(poll(**options))
    assert not elements["#acquisition-note"]["hidden"]
    assert title in elements["#acquisition-title"]["text"].lower()
    assert footer in elements["#acquisition-execution"]["text"].lower()
    assert elements["#acquisition-start"]["hidden"]


def test_unconfirmed_receipt_is_labelled_and_does_not_restart_acquisition():
    observed = poll(unconfirmed=True)
    assert "receipt check pending" in _banner(observed)["#acquisition-automatic"]["text"].lower()
    assert not commands(observed)


@pytest.mark.parametrize("zh,flow_state,title", [
    (False, "EXECUTING", "run not started"), (True, "EXECUTING", "运行尚未开始"),
    (False, "SETUP_REQUIRED", "software setup needed"), (True, "SETUP_REQUIRED", "需要先配置软件"),
])
def test_acquired_data_banner_offers_start_through_the_chat_send_path(zh, flow_state, title):
    observed = poll(flow_state=flow_state, ready=True, click_start=True, zh=zh, ticks=7)   # 35 s
    elements = _banner(observed)
    assert not elements["#acquisition-note"]["hidden"]
    assert not elements["#acquisition-start"]["hidden"]
    assert title in elements["#acquisition-title"]["text"].lower()
    assert observed["sent"] == ["开始已批准的运行。" if zh else "Start the approved run."]
    assert not commands(observed), "starting the run is the user's chat message, not a timer"
    assert len(_status_reads(observed)) == 1, "only the user changes this state: slow fallback reads only"


def test_start_button_keeps_the_users_draft_and_sends_once():
    draft = "Also compare against the 2019 gauge record"
    observed = poll(flow_state="EXECUTING", ready=True, click_start=True, ticks=7, draft=draft)
    assert observed["sent"] == ["Start the approved run."]
    assert (observed["msg"], observed["draft"]) == (draft, draft)
    assert _banner(observed)["#acquisition-start"]["disabled"]


def test_visible_tracked_chat_reads_status_through_its_acquire_tick_only():
    observed = poll(ticks=6)
    assert len(commands(observed)) == 6, "one /acquire request per tick"
    assert len(_status_reads(observed)) == 1, "each /acquire result already carries the status"


SWITCH_RUNNER = r"""
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const page=fs.readFileSync(process.argv[1],'utf8'),mode=process.argv[2];
const elements=new Map(),releases=[],catalogueReads=[];
function element(selector){
  if(!elements.has(selector))elements.set(selector,{innerHTML:'',textContent:'',value:'',dataset:{},hidden:true,
    style:{},scrollTop:0,scrollHeight:0,classList:{contains:()=>false,add(){},remove(){},toggle(){}},
    querySelectorAll:()=>[],setAttribute(){},removeAttribute(){}});
  return elements.get(selector);
}
const acquiring={session:'A',selected_kis:[],project_preflights:[],goal:'A',status:'working',flow_state:'ACQUIRING',acquisition:{active:true,status:'waiting',
  automatic:[{id:'forcing',dataset_id:'cmfd-A',status:'pending',job_status:'running'}],
  manual:[{id:'yearbook',dataset_id:'yearbook-A',status:'waiting'}]}};
// Include the real scope helper and the independent catalogue/status surfaces
// openSession now loads before it commits the new current project.
const context={console,Date,URL,URLSearchParams,Headers,location:new URL('http://127.0.0.1:8799/'),
  history:{replaceState(){}},
  SESSIONS:[],KI_UPDATE_REVISION:'fixture',CUR:{id:'A'},RUN:null,INVESTIGATION:null,DRAFTS:new Map(),OPEN_SEQ:0,ACTION_SESSION:null,
  MODELS:[],STATUS:{},LAST_STATUS_CHECK:0,
  CHAT_FOLLOW:true,INFLIGHT:new Map(),DATA_ACTIONS:new Set(),$:element,sessionBusy:()=>false,
  chineseUI:()=>false,document:{hidden:false,querySelectorAll:()=>[],querySelector:()=>null,addEventListener(){}},
  runButtonLabel:()=>'Project status',runStateText:()=>'',closeActionPicker(){},drawSessions(){},
  rememberSessionSummary(){},mergeSessionSummaries:value=>value,
  drawModelLabel(){},drawSkillButton(){},addTurn:()=>element('turn'),messageHtml:()=>'',renderLiveTurn(){},
  renderAttachments(){},drawProviders(){},async refreshViewStatus(){},async refreshProjectView(){},
  setControls(){},async maybeShowAction(){},async refreshMachineStatus(){}};
context.fetch=async url=>{
  if(url==='/api/session/B')return {ok:true,status:200,json:async()=>({id:'B',title:'B',messages:[]})};
  if(url==='/api/models'||url==='/api/status'){
    catalogueReads.push(url);
    return {ok:true,status:200,json:async()=>url==='/api/models'?[]:{}};
  }
  if(url==='/api/session/A/run')return {ok:true,status:200,json:async()=>acquiring};
  if(url==='/api/session/B/run'){
    if(mode==='fail')return {ok:false,status:500,json:async()=>({error:'Synthetic failure'})};
    await new Promise(resolve=>releases.push(resolve));
    return {ok:true,status:200,json:async()=>({session:'B',selected_kis:[],project_preflights:[],goal:'B',status:'ready',flow_state:'PLANNING',acquisition:null})};
  }
  if(url.endsWith('/acquire'))return {ok:true,status:200,json:async()=>({run:acquiring})};
  throw new Error('unexpected '+url);
};
context.window=context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(path.dirname(process.argv[1]),'ki-scope.js'),'utf8'),context);
function shipped(start,end){
  const a=page.indexOf(start),b=page.indexOf(end,a);
  if(a<0||b<0)throw new Error('Missing shipped JavaScript segment: '+start);
  vm.runInContext(page.slice(a,b),context);
}
shipped('// Project readiness is distinct','function stateClass');
shipped('function runCompletionTitle(run){','function runButtonLabel');
shipped('function drawRunStatus(','function drawViewStatus(');
shipped('async function openSession(id){','function drawModelLabel(){');
const flush=async()=>{for(let n=0;n<50;n++)await Promise.resolve();};
const banner=()=>({hidden:element('#acquisition-note').hidden,
  text:element('#acquisition-automatic').textContent+' '+element('#acquisition-manual').textContent});
(async()=>{
  await vm.runInContext('refreshRun("A")',context);
  const before=banner();
  const opening=vm.runInContext('openSession("B")',context);
  await flush();
  const loading=banner();
  for(let n=0;n<3;n++){await vm.runInContext('refreshAcquisitionProgress()',context);await flush();}
  const later=banner();
  for(const release of releases)release();
  await opening;await flush();
  process.stdout.write(JSON.stringify({before,loading,later,after:banner(),opened:context.CUR.id,catalogueReads}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


@pytest.mark.parametrize("mode", ["slow", "fail"])
def test_switching_chats_never_shows_the_previous_projects_banner(mode):
    result = subprocess.run([NODE, "-e", SWITCH_RUNNER, str(PAGE), mode], capture_output=True,
                            text=True, encoding="utf-8", check=True, timeout=10)
    observed = json.loads(result.stdout)
    assert observed["opened"] == "B"
    assert observed["catalogueReads"] == ["/api/models", "/api/status"]
    assert not observed["before"]["hidden"] and "cmfd-A" in observed["before"]["text"]
    for moment in ("loading", "later", "after"):
        assert observed[moment]["hidden"], (moment, observed[moment])


SESSION_URL_RUNNER = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const page=fs.readFileSync(process.argv[1],'utf8').replaceAll('\r\n','\n'),mode=process.argv[2];
function fn(name){
  const start=page.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.ok(start>=0,name);const end=page.indexOf('\n}',start);assert.ok(end>start,name);
  return page.slice(start,end+2);
}
function deferred(){let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};}
const response=value=>({ok:true,json:async()=>value});
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
const waiting=deferred(),entered=deferred(),writes=[],elements=new Map(),storage=new Map();
const firstScope='a'.repeat(32),nextScope='b'.repeat(32);
const sessions={A:{id:'A',title:'A',messages:[],library_scope:firstScope},
  B:{id:'B',title:'B',messages:[],library_scope:mode==='unscoped'?'':nextScope},
  C:{id:'C',title:'C',messages:[],library_scope:'c'.repeat(32)}};
function element(name){
  if(!elements.has(name))elements.set(name,{value:'',innerHTML:'',textContent:'',style:{},scrollHeight:0,
    classList:{contains:()=>false},focus(){}});
  return elements.get(name);
}
const location=new URL(`http://127.0.0.1:8800/?session=A&library_scope=${firstScope}`);
let context;
context=vm.createContext({console,Date,URL,URLSearchParams,Headers,location,Promise,
  history:{replaceState(_state,_title,url){location.href=new URL(url,location).href;writes.push(url);}},
  sessionStorage:{getItem:key=>storage.get(key)||null,removeItem:key=>storage.delete(key)},
  document:{addEventListener(){}},$:element,OPEN_SEQ:0,CUR:sessions.A,SESSIONS:Object.values(sessions),
  DRAFTS:new Map(),ACTION_SESSION:null,INVESTIGATION:null,MODELS:[],STATUS:{},LAST_STATUS_CHECK:0,
  INFLIGHT:new Map([['A',{raw:'ongoing A response'}]]),CHAT_FOLLOW:true,
  drawSessions(){},rememberSessionSummary(){},mergeSessionSummaries:rows=>rows,invalidateProjectStatus(){},
  closeActionPicker(){},drawModelLabel(){},drawSkillButton(){},renderLiveTurn(){},renderAttachments(){},
  drawProviders(){},drawRunStatus(){},refreshRun:async()=>{},refreshViewStatus:async()=>{},
  refreshProjectView:async()=>{},setControls(){},maybeShowAction:async()=>{},
  refreshProviders:async()=>{},refreshMachineStatus:async()=>{},drawEmpty(){},
  setTimeout(){},chineseUI:()=>false,esc:String,currentProviderReady:()=>false,
  chooseProjectLocation:async()=>({project_name:'B'}),LAST_PROJECT_ERROR:'',
  fetch:async(url,options)=>{
    if(url==='/api/sessions')return response(options?.method==='POST'?sessions.B:Object.values(sessions));
    if(url.startsWith('/api/session/')){
      const id=url.split('/')[3];
      if(mode==='late-session'&&id==='B'){entered.resolve();await waiting.promise;}
      return response(sessions[id]);
    }
    if(url==='/api/models')return response([]);
    if(url==='/api/status'){
      const scope=context.GeoForgeKIScope.get();
      if((mode==='late-status'||mode==='scope-changed'||mode==='failed-status')&&scope===nextScope){
        entered.resolve();await waiting.promise;
        if(mode==='failed-status')return {ok:false,json:async()=>({error:'unavailable'})};
      }
      return response({});
    }
    return response([]);
  }});
context.window=context;
vm.runInContext(fs.readFileSync(path.join(path.dirname(process.argv[1]),'ki-scope.js'),'utf8'),context);
vm.runInContext([fn('openSession'),fn('loadAll'),fn('createSessionAt'),fn('ensureSession')].join('\n'),context);
const run=code=>vm.runInContext(code,context);
(async()=>{
  if(mode==='bootstrap'){
    context.CUR=null;
    context.refreshRun=async id=>{if(id==='A'){entered.resolve();await waiting.promise;}};
    storage.set('kiss.draft.A','saved A draft');storage.set('kiss.autosend.A','yes');
    const loading=run('loadAll()');await entered.promise;
    await run('openSession("B")');element('#msg').value='unsent B draft';
    waiting.resolve();await loading;
    assert.equal(element('#msg').value,'unsent B draft');
    assert.equal(storage.get('kiss.draft.A'),'saved A draft');
    assert.equal(storage.get('kiss.autosend.A'),'yes');
  }else if(mode==='create'){
    context.CUR=null;
    element('#msg').value='new project draft';
    const created=await run('ensureSession()');assert.equal(created.id,'B');
    assert.equal(element('#msg').value,'new project draft');
  }else if(['late-session','late-status'].includes(mode)){
    const opening=run('openSession("B")');await entered.promise;
    assert.equal(writes.length,0,'pending session must not replace current URL');
    await run('openSession("C")');waiting.resolve();await opening;
  }else if(mode==='scope-changed'){
    const opening=run('openSession("B")');await entered.promise;
    context.GeoForgeKIScope.set('c'.repeat(32));waiting.resolve();await opening;
    assert.equal(writes.length,0);assert.equal(context.CUR.id,'A');
  }else if(mode==='failed-status'){
    const opening=run('openSession("B")');await entered.promise;waiting.resolve();
    await assert.rejects(opening,/Could not load/);assert.equal(writes.length,0);
    assert.equal(context.CUR.id,'A');
  }else await run('openSession("B")');
  const expected=['late-session','late-status'].includes(mode)?'C':
    ['scope-changed','failed-status'].includes(mode)?'A':'B';
  assert.equal(context.CUR.id,expected);
  assert.equal(location.searchParams.get('session'),expected);
  assert.equal(location.searchParams.get('library_scope'),sessions[expected].library_scope||null);
  assert.equal(context.INFLIGHT.get('A').raw,'ongoing A response');
  assert.equal(context.INFLIGHT.size,1);
  process.stdout.write(JSON.stringify({session:expected,writes}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


@pytest.mark.parametrize("mode", ["switch", "unscoped", "late-session", "late-status",
    "scope-changed", "failed-status", "bootstrap", "create"])
def test_session_url_follows_only_committed_project_and_scope(mode):
    subprocess.run([NODE, "-e", SESSION_URL_RUNNER, str(PAGE), mode],
                   capture_output=True, text=True, encoding="utf-8", check=True, timeout=10)
